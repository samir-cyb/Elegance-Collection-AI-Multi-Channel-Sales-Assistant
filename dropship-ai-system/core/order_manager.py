import json
import logging
import re
from datetime import datetime
from pathlib import Path
from core.database import get_connection

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_PATH = BASE_DIR / "data" / "products.json"

logger = logging.getLogger("order_manager")

# Matches a ```json ... ``` block anywhere in the AI reply, so we can pull
# out structured order data the model was told to emit (see gemini_brain.py
# system prompt). This is how "detect the customer confirmed → actually
# save the order" is implemented, instead of just logging a generic event.
ORDER_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _is_recent_duplicate(phone, product, color, quantity, price, window_seconds=120) -> bool:
    """Guards against the same order being saved twice.

    Root cause of the duplicate-order bug: Gemini replies can take
    30-65+ seconds (see logs), and nothing stopped a customer from
    sending the same "yes/confirm" message twice while waiting (or a
    flaky network/proxy retrying the POST) — each call independently
    saw ORDER_CONFIRMED in its own reply and saved its own row. The
    frontend now also disables the send button while a reply is in
    flight, but this DB-level check is the real safety net: if an
    order with the exact same phone/product/color/quantity/price was
    saved in the last `window_seconds`, treat this as a duplicate and
    skip saving instead of creating a second row.
    """
    conn = get_connection()
    cur = conn.execute(
        """
        SELECT created_at FROM orders
        WHERE phone = ? AND product = ? AND IFNULL(color, '') = IFNULL(?, '')
              AND quantity = ? AND total_price = ?
        ORDER BY id DESC LIMIT 1
        """,
        (phone, product, color, quantity, price),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    try:
        last_created = datetime.fromisoformat(row[0])
    except (TypeError, ValueError):
        return False
    return (datetime.now() - last_created).total_seconds() < window_seconds


def save_order(name, phone, address, product, color, quantity, price, platform):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO orders
        (customer_name, phone, address, product, color, quantity, total_price, platform, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name, phone, address, product, color, quantity, price, platform,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def update_stock(product_id, color, qty=1):
    with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for p in data["products"]:
        if p["id"] == product_id:
            for c in p["colors"]:
                if c["name"] == color:
                    c["stock"] = max(0, c["stock"] - qty)
            p["stock"] = sum(c["stock"] for c in p["colors"])
    with open(PRODUCTS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_order_confirmed(ai_reply: str) -> bool:
    return "ORDER_CONFIRMED" in ai_reply


def extract_order_data(ai_reply: str) -> dict | None:
    """Pulls the ```json {...} ``` block the model was instructed to emit
    once an order is confirmed. Returns None if not present or malformed
    (logged, not raised — a malformed block should never crash the chat)."""
    match = ORDER_JSON_RE.search(ai_reply)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        logger.warning("[order] Found an order JSON block but couldn't parse it: %s", e)
        return None


def strip_order_json(ai_reply: str) -> str:
    """Removes the raw ```json {...} ``` block AND the ORDER_CONFIRMED
    marker from what's shown to the customer — both are for our backend
    only, the customer should just see the warm confirmation message."""
    cleaned = ORDER_JSON_RE.sub("", ai_reply)
    cleaned = cleaned.replace("ORDER_CONFIRMED", "")
    return cleaned.strip()


def process_confirmed_order(ai_reply: str, platform: str, user_id: str) -> dict | None:
    """Given a reply that contains ORDER_CONFIRMED, extract the structured
    order data, save it to the orders table, update stock, and log a Lead
    event. Returns the saved order dict, or None if extraction failed."""
    order = extract_order_data(ai_reply)
    if not order:
        logger.warning(
            "[order] ORDER_CONFIRMED seen but no valid ```json``` block found "
            "for user=%s — nothing was saved to the orders table.", user_id,
        )
        log_event("Lead", page=platform, meta={"user_id": user_id, "note": "unparsed order"})
        return None

    phone = order.get("phone", "")
    product_name = order.get("product_name", "")
    color = order.get("color", "")
    quantity = order.get("quantity", 1)
    price = order.get("total_price", 0)

    if _is_recent_duplicate(phone, product_name, color, quantity, price):
        logger.warning(
            "[order] Duplicate order detected for user=%s (same phone/product/color/qty/price "
            "saved within the last 2 minutes) — SKIPPING save to avoid a duplicate row. "
            "order=%s", user_id, order,
        )
        return order  # tell the caller it "succeeded" (customer already has a real order on file)

    try:
        save_order(
            name=order.get("name", ""),
            phone=phone,
            address=order.get("address", ""),
            product=product_name,
            color=color,
            quantity=quantity,
            price=price,
            platform=platform,
        )
        if order.get("product_id") and order.get("color"):
            update_stock(order["product_id"], order["color"], quantity)
        logger.info("[order] Saved order for user=%s: %s", user_id, order)
        log_event("Lead", page=platform, product_id=order.get("product_id"),
                   meta={"user_id": user_id, "order": order})
        return order
    except Exception as e:
        logger.exception("[order] Failed to save order for user=%s: %s", user_id, e)
        return None


def log_event(event_name: str, page: str = None, product_id: str = None, meta: dict = None):
    """Mirrors what the Meta Pixel fires on the frontend, so the admin
    dashboard can show real numbers without needing the Facebook Marketing API."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO events (event_name, page, product_id, meta, created_at) VALUES (?, ?, ?, ?, ?)",
        (event_name, page, product_id, json.dumps(meta or {}), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_orders(limit: int = 200) -> list:
    """Returns saved orders, most recent first — powers the admin
    dashboard's Orders table so you can see exactly which customer
    ordered what, with full contact/delivery details."""
    conn = get_connection()
    cur = conn.execute(
        """
        SELECT id, customer_name, phone, address, product, color, quantity,
               total_price, platform, status, created_at
        FROM orders
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    columns = [
        "id", "customer_name", "phone", "address", "product", "color",
        "quantity", "total_price", "platform", "status", "created_at",
    ]
    return [dict(zip(columns, row)) for row in rows]


def update_order_status(order_id: int, status: str) -> bool:
    """Lets the admin mark an order as confirmed/shipped/cancelled etc.
    Returns True if a row was actually updated."""
    conn = get_connection()
    cur = conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def get_event_stats():
    conn = get_connection()
    cur = conn.execute(
        "SELECT event_name, COUNT(*) FROM events GROUP BY event_name ORDER BY COUNT(*) DESC"
    )
    by_event = [{"event_name": r[0], "count": r[1]} for r in cur.fetchall()]

    cur = conn.execute(
        "SELECT date(created_at) as d, COUNT(*) FROM events GROUP BY d ORDER BY d DESC LIMIT 14"
    )
    by_day = [{"date": r[0], "count": r[1]} for r in cur.fetchall()][::-1]

    cur = conn.execute("SELECT COUNT(*) FROM orders")
    total_orders = cur.fetchone()[0]

    cur = conn.execute("SELECT COUNT(*) FROM events")
    total_events = cur.fetchone()[0]

    conn.close()
    return {
        "by_event": by_event,
        "by_day": by_day,
        "total_orders": total_orders,
        "total_events": total_events,
    }
