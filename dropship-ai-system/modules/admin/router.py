"""Admin analytics API.
- POST /api/track  → called by pixel.js on every page, mirrors what the Meta
  Pixel fires (PageView, ViewContent, AddToCart, Lead) into our own DB, since
  pulling real numbers from Facebook Ads Manager needs a separate Marketing
  API + business verification (out of scope for the demo).
- GET  /api/admin/stats → powers the admin dashboard chart/numbers.

Note: the "Demo" login button on the frontend does NOT call any protected
auth endpoint — it just unlocks the dashboard page in the browser. That's
fine for a showcase; before real production use, put a real login here.
"""

import logging
import os
from fastapi import APIRouter, Request
from core.order_manager import log_event, get_event_stats, get_orders, update_order_status
from core.gemini_brain import load_products

logger = logging.getLogger("admin")

router = APIRouter()


@router.get("/api/config")
async def public_config():
    """Frontend fetches this once to get the Meta Pixel ID, so it's set
    in ONE place (.env) instead of being hardcoded into every HTML page."""
    return {"pixel_id": os.getenv("META_PIXEL_ID", "")}


@router.post("/api/track")
async def track_event(request: Request):
    data = await request.json()
    log_event(
        event_name=data.get("event_name", "Unknown"),
        page=data.get("page"),
        product_id=data.get("product_id"),
        meta=data.get("meta"),
    )
    return {"status": "logged"}


@router.get("/api/admin/stats")
async def admin_stats():
    return get_event_stats()


@router.get("/api/products")
async def get_products():
    return load_products()


@router.get("/api/admin/orders")
async def admin_orders():
    """Returns every saved order (customer name, phone, address, product,
    color, qty, price, platform, status) — most recent first — so the
    admin dashboard can list which orders came in and their full details."""
    orders = get_orders()
    logger.info("[admin] /api/admin/orders returned %d orders", len(orders))
    return {"orders": orders}


@router.post("/api/admin/orders/{order_id}/status")
async def admin_update_order_status(order_id: int, request: Request):
    data = await request.json()
    status = (data.get("status") or "").strip()
    if not status:
        return {"ok": False, "error": "status is required"}
    ok = update_order_status(order_id, status)
    logger.info("[admin] order id=%s status -> %s (updated=%s)", order_id, status, ok)
    return {"ok": ok}
