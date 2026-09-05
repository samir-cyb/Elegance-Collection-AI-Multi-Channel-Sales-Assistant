"""
Gemini AI Brain — uses the NEW official 'google-genai' SDK
(the old 'google-generativeai' package is deprecated).

pip install google-genai

NOTE ON RAG: This does NOT use Retrieval-Augmented Generation (no vector
database, no embeddings, no similarity search). Instead it uses the much
simpler "context stuffing" approach — the ENTIRE products.json is pasted
directly into the system prompt on every request. This is fine (actually
better — faster, no missed matches, no extra infra) for a catalog this
size (5-50 products). RAG only starts to make sense once the catalog is
too large to fit in Gemini's context window (roughly hundreds of products
with long descriptions) or you need it to search across other documents
(policies, FAQs, etc.) — see the note at the bottom of this file if you
reach that point.
"""

import base64
import json
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from core import rag_engine

# Same switch as main.py — when the embedding model is disabled (e.g. to
# fit a low-RAM hosting plan), always fall back to the full catalog instead
# of calling rag_engine.search() (which would otherwise lazily load the
# heavy sentence-transformers model on first use anyway).
RAG_ENABLED = os.getenv("ENABLE_RAG", "true").lower() == "true"

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gemini_brain")

BASE_DIR = Path(__file__).resolve().parent
PRODUCTS_PATH = BASE_DIR / "data" / "products.json"
PROJECT_ROOT = BASE_DIR.parent
PRODUCT_IMAGES_DIR = PROJECT_ROOT / "marketing-website" / "assets" / "products"

_client = None
_reference_images_cache = None  # loaded once, products.json images rarely change mid-session


class GeminiConfigError(RuntimeError):
    """Raised when the API key / client can't be set up — a setup problem,
    not a runtime AI error."""


def get_client():
    """Lazy-init so the module can be imported even before the API key is set."""
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error(
                "GEMINI_API_KEY is missing from environment. "
                "Check that a real .env file (not .env.example) exists next to main.py "
                "and contains GEMINI_API_KEY=<your key>."
            )
            raise GeminiConfigError(
                "GEMINI_API_KEY is missing. Add it to your .env file (not .env.example)."
            )
        logger.info("Initializing Gemini client (key starts with: %s...)", api_key[:6])
        _client = genai.Client(api_key=api_key)
    return _client


def load_products():
    with open(PRODUCTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


MIME_BY_EXT = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def get_reference_images(products_data: dict):
    """Loads every catalog photo (all products, all colors) into memory once
    and caches it, so when a customer uploads their own photo we can hand
    Gemini the REAL product photos to visually compare against — not just
    text descriptions. This matters a lot here because several dresses in
    this catalog look quite similar (all salwar kameez), so text alone
    ("soft georgette, embroidery, sequins") isn't enough to tell them apart
    reliably — actual photo-to-photo comparison is far more accurate.

    Returns a list of (label, types.Part) tuples.
    """
    global _reference_images_cache
    if _reference_images_cache is not None:
        return _reference_images_cache

    refs = []
    for product in products_data["products"]:
        for color in product["colors"]:
            path = PRODUCT_IMAGES_DIR / color["image"]
            if not path.exists():
                logger.warning("[reference_images] Missing file, skipping: %s", path)
                continue
            mime = MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")
            try:
                image_bytes = path.read_bytes()
            except Exception as e:
                logger.warning("[reference_images] Could not read %s: %s", path, e)
                continue
            label = f"[ক্যাটালগ রেফারেন্স ছবি — প্রোডাক্ট আইডি: {product['id']} | রং: {color['name']} | নাম: {product['name_bn']}]"
            refs.append((label, types.Part.from_bytes(data=image_bytes, mime_type=mime)))

    _reference_images_cache = refs
    logger.info("[reference_images] Loaded %d catalog reference images into cache", len(refs))
    return refs


# Gemini can't attach real image files — it only knows the product catalog
# text. So instead we teach it to emit a plain-text tag referencing which
# product/color image to show, e.g. [SHOW_IMAGE: DRESS003 | Black].
# resolve_image_tags() then swaps that tag for an actual Markdown image
# pointing at the real file in marketing-website/assets/products/, using
# the same products.json data the model was given. Multiple tags in one
# reply → multiple images (e.g. customer asks to see all colors).
IMAGE_TAG_RE = re.compile(r"\[SHOW_IMAGE:\s*([A-Za-z0-9_]+)\s*\|\s*([^\]]+?)\s*\]")


def resolve_image_tags(reply: str, products_data: dict) -> str:
    products_by_id = {p["id"]: p for p in products_data["products"]}

    def replace(match):
        product_id, color_name = match.group(1).strip(), match.group(2).strip()
        # Debug visibility: this is exactly what Gemini decided to show —
        # useful to see, for example, when comparing an uploaded photo
        # against the catalog, whether the model's own decision was right
        # (in which case the bug is elsewhere) or wrong (a matching issue).
        logger.info("[image_tag] Gemini requested: product_id=%s color=%s", product_id, color_name)
        product = products_by_id.get(product_id)
        if not product:
            logger.warning(
                "[image_tag] Unknown product_id in tag: %s (not in the %d products given to the model — "
                "if this happens on an image turn, the product list passed to Gemini may have been "
                "incomplete)", product_id, len(products_by_id),
            )
            return ""
        color_entry = next(
            (c for c in product["colors"] if c["name"].lower() == color_name.lower()),
            None,
        ) or (product["colors"][0] if product["colors"] else None)
        if not color_entry:
            logger.warning("[image_tag] No image found for %s / %s", product_id, color_name)
            return ""
        alt = f"{product['name_bn']} - {color_entry['name']}"
        url = "/assets/products/" + urllib.parse.quote(color_entry["image"])
        return f"![{alt}]({url})"

    resolved = IMAGE_TAG_RE.sub(replace, reply)
    if resolved != reply:
        logger.info("[image_tag] Resolved %d image tag(s) in reply", len(IMAGE_TAG_RE.findall(reply)))
    return resolved


def build_system_prompt(shop_name_bn: str, products: list) -> str:
    return f"""
তুমি '{shop_name_bn}' নামের একটি বাংলাদেশি অনলাইন লেডিস ড্রেস শপের AI সহকারী।
তোমার নাম 'রাফি'। তুমি এই দোকানের সবচেয়ে প্রিয়, প্রাণবন্ত, প্রফেশনাল সেলস-পার্সন — একজন সত্যিকারের, খুশি-মনের মানুষ যে সত্যিই কাস্টমারকে সাহায্য করতে ভালোবাসে। তুমি রোবটের মতো না, তোমার প্রতিটা কথায় উষ্ণতা আর আন্তরিকতা থাকবে। তুমি সবসময় বাংলায় কথা বলো।

তোমার ব্যক্তিত্ব ও কথা বলার স্টাইল:
- সবসময় ইতিবাচক, উৎসাহী, হাসিখুশি — কাস্টমার যেন মনে করে একজন যত্নশীল বান্ধবী/বোনের সাথে কথা বলছে, কোনো bot-এর সাথে না
- হালকা ইমোজি ব্যবহার করো স্বাভাবিকভাবে (😊 🥻 ✨ 💝 📦 🎉 😍 ইত্যাদি) — বেশি না, প্রতিটা মেসেজে ২-৪টা যথেষ্ট
- গুরুত্বপূর্ণ তথ্য (পণ্যের নাম, দাম) **বোল্ড** করে লেখো (markdown **text** ফরম্যাটে) — bullet list/asterisk দিয়ে ঠাসা robotic answer না দিয়ে, স্বাভাবিক কথোপকথনের মতো লেখো, মাঝে মাঝে ছোট লাইন-ব্রেক দিয়ে পড়তে সহজ করো
- কাস্টমারকে আন্তরিকভাবে appreciate করো, compliment দাও ("আপনার choice টা সত্যিই অসাধারণ! 😍"), তাকে special ও গুরুত্বপূর্ণ অনুভব করাও
- এক লাইনে সব প্রশ্ন না করে, স্বাভাবিক কথোপকথনের মতো ধাপে ধাপে একটা একটা করে জিজ্ঞেস করো
- তুমি একজন দক্ষ বিক্রয়কর্মী — কাস্টমার দ্বিধায় থাকলে হালকা করে upsell/encourage করো ("এটা কিন্তু এখন খুব কম স্টকে আছে, এখনই নিয়ে ফেলুন! 🎉"), কিন্তু কখনো জোর করবে না বা বিরক্তিকর হবে না — বন্ধুত্বপূর্ণ থেকে বিক্রি বাড়ানোই লক্ষ্য
- কাস্টমার হতাশ/বিরক্ত মনে হলে সহানুভূতিশীল হও, দ্রুত সমাধান দেওয়ার চেষ্টা করো

তোমার কাছে এই পণ্যগুলো আছে:
{json.dumps(products, ensure_ascii=False)}

তুমি যা করবে:
1. পণ্যের নাম, দাম (ডিসকাউন্ট থাকলে আগের দাম কেটে নতুন দাম), রঙ/ভ্যারিয়েন্ট, কাপড়ের তথ্য উষ্ণভাবে বলবে
2. Stock না থাকলে সেটা জানাবে, বিকল্প suggest করবে
3. কাস্টমার order করতে আগ্রহ দেখালে, একটা একটা করে প্রশ্ন করে এই তথ্যগুলো নেবে (সবগুলো একসাথে না চেয়ে):
   - নাম
   - ঠিকানা (পুরো, ডেলিভারির জন্য)
   - ফোন নম্বর
   - কোন রং (পণ্যে একাধিক রং থাকলে)
   - কয়টা (quantity)
4. সব তথ্য পাওয়ার পর, একটা সুন্দর সামারি দিয়ে কনফার্ম করতে বলবে (যেমন: "তাহলে ঠিক আছে তো? ✅") এবং কাস্টমার হ্যাঁ/কনফার্ম/ঠিক আছে জাতীয় কিছু বললে তুমি ধরে নেবে অর্ডার confirmed
5. অর্ডার confirmed হওয়ার সাথে সাথে reply-তে অবশ্যই দুটো জিনিস থাকবে:
   a. একটা উষ্ণ, খুশি করার মতো confirmation message, ধন্যবাদ দিয়ে (কাস্টমারের কাছে এটাই দেখাবে)
   b. একদম শেষে, নতুন লাইনে, প্রথমে লিখবে ORDER_CONFIRMED তারপর একটা ```json ``` ব্লকে অর্ডারের পুরো তথ্য এই exact ফরম্যাটে (এই অংশটা কাস্টমারকে দেখানো হবে না, শুধু আমাদের সিস্টেমের জন্য — তাই এটা ছাড়া বাকি মেসেজ যেন নিজেই সম্পূর্ণ ও readable হয়):
```json
{{"name": "কাস্টমারের নাম", "phone": "ফোন নম্বর", "address": "পুরো ঠিকানা", "product_id": "পণ্যের id (যেমন DRESS002)", "product_name": "পণ্যের নাম", "color": "নির্বাচিত রং", "quantity": 1, "unit_price": 2380, "total_price": 2380}}
```
   - product_id অবশ্যই উপরের catalog থেকে সঠিক id বসাবে, নিজে বানাবে না
   - total_price = unit_price × quantity হিসাব করে বসাবে
6. কখনো পণ্যের বাইরের কিছু (অন্য দোকানের প্রশ্ন ইত্যাদি) নিয়ে আলোচনা করবে না, ভদ্রভাবে বিষয় ফিরিয়ে আনবে

ছবি দেখানো (এটা গুরুত্বপূর্ণ, ঠিক ফরম্যাট মেনে করবে):
- কাস্টমার কোনো পণ্যের ছবি/picture দেখতে চাইলে, অথবা তুমি প্রথমবার কোনো পণ্য introduce করার সময়, মেসেজের মধ্যে (যেকোনো জায়গায়, নিজের বাক্যের ফাঁকে) এই ঠিক ফরম্যাটে একটা ট্যাগ বসাবে:
  [SHOW_IMAGE: প্রোডাক্ট_আইডি | রঙের নাম]
  উদাহরণ: [SHOW_IMAGE: DRESS003 | Black]
- প্রোডাক্ট_আইডি এবং রঙের নাম হুবহু উপরের catalog থেকে নেবে (JSON-এ "id" আর "colors"-এর "name" ফিল্ড দেখে), নিজে থেকে বানাবে না বা অনুমান করবে না
- কাস্টমার একাধিক রঙ দেখতে চাইলে (যেমন "সব রং দেখান"), একাধিক ট্যাগ ব্যবহার করবে, প্রতিটা আলাদা লাইনে — যতগুলো রং আছে সবগুলোর জন্য একটা করে ট্যাগ
- এই ট্যাগটা ছবি হিসেবে automatically রেন্ডার হয়ে যাবে, তুমি ছবির URL বা লিংক নিজে বানানোর চেষ্টা করবে না, শুধু এই ট্যাগ ফরম্যাটটাই ব্যবহার করবে
- ট্যাগ বসানোর সাথে সাথেই একটা ছোট উষ্ণ বাক্য লিখবে (যেমন: "এই যে দেখুন! 😍")

কাস্টমার যখন নিজে একটা ছবি পাঠায় (যেমন কোথাও দেখা কোনো ড্রেসের ছবি, বা "এই রকম কিছু আছে?" জিজ্ঞেস করার জন্য):
- এই মেসেজের সাথে তোমাকে কাস্টমারের ছবির পাশাপাশি আমাদের প্রতিটা পণ্যের আসল রেফারেন্স ছবিও দেওয়া হচ্ছে, প্রতিটার আগে লেখা আছে সেটা কোন প্রোডাক্ট আইডি ও রং
- **শুধু text description-এর উপর ভরসা করবে না** — কাস্টমারের ছবি আর প্রতিটা রেফারেন্স ছবি সরাসরি চোখে দেখে visually তুলনা করো: রঙ প্রথমে মেলাও (এটা সবচেয়ে নির্ভরযোগ্য), তারপর embroidery/প্যাটার্নের জায়গা ও ঘনত্ব, কাপড়ের texture, silhouette/কাটিং দেখো
- আমাদের অনেক পণ্য একই রকম দেখতে (সব salwar kameez স্টাইল), তাই তাড়াহুড়ো করে অনুমান করবে না — সাবধানে compare করো
- একটা পণ্যের সাথে স্পষ্ট মিল থাকলে, আত্মবিশ্বাসের সাথে বলো এবং [SHOW_IMAGE: ...] ট্যাগ দিয়ে সেটা দেখাও
- একাধিক পণ্য কাছাকাছি মনে হলে, নিশ্চিত না হয়ে একটাকেই "এটাই" বলে চালিয়ে দিও না — ২-৩টা কাছাকাছি option দেখাও (প্রতিটার জন্য আলাদা [SHOW_IMAGE: ...] ট্যাগ) এবং সততার সাথে বলো "এই কয়েকটার মধ্যে যেকোনো একটার সাথে মিলতে পারে, কোনটা বেশি পছন্দ?"
- কোনোটার সাথেই ভালো মিল না থাকলে, সততার সাথে জানাও এবং সবচেয়ে কাছাকাছি যেটা আছে সেটা suggest করো
- কাস্টমারের পাঠানো ছবিতে যদি কোনো প্রশ্ন থাকে (যেমন "সাইজ কেমন হবে বুঝতে পারছি না") সেটারও সরাসরি জবাব দাও
""".strip()


# conversation_history[user_id] = [{"role": "user"/"model", "content": "..."}]
conversation_history: dict[str, list] = {}

# Google keeps rotating which models are available to newer API keys —
# "gemini-2.5-flash" returned 404 "no longer available to new users" on
# your key even though it's still in the docs. Using gemini-3.5-flash-lite
# by your choice (fastest/cheapest current model). Overridable via .env
# so you don't need to touch code again if availability changes.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Google's popular models occasionally return 503 "high demand" — this is
# temporary and NOT a bug in this code. We retry a few times, then fall
# back to a second (usually less busy) model rather than showing the
# customer an error. Falls back to the fuller gemini-3.5-flash since the
# primary is already the "lite" tier.
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash")
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [1, 2, 4]


def _is_overloaded_error(e: Exception) -> bool:
    s = str(e)
    return "503" in s or "UNAVAILABLE" in s or "high demand" in s.lower()


def _call_model(client, model_name, contents, system_prompt):
    return client.models.generate_content(
        model=model_name,
        contents=contents,
        config={"system_instruction": system_prompt},
    )


def _generate_with_resilience(client, contents, system_prompt):
    """Try MODEL_NAME with a few retries on 503 overload, then fall back
    to FALLBACK_MODEL before giving up."""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _call_model(client, MODEL_NAME, contents, system_prompt)
        except Exception as e:
            last_error = e
            if not _is_overloaded_error(e):
                raise  # not an overload issue (bad key, bad request, etc.) — fail fast
            wait = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            logger.warning(
                "[chat] '%s' overloaded (attempt %d/%d) — retrying in %ds",
                MODEL_NAME, attempt, MAX_RETRIES, wait,
            )
            time.sleep(wait)

    logger.warning(
        "[chat] '%s' still overloaded after %d attempts — falling back to '%s'",
        MODEL_NAME, MAX_RETRIES, FALLBACK_MODEL,
    )
    try:
        return _call_model(client, FALLBACK_MODEL, contents, system_prompt)
    except Exception as e:
        logger.error("[chat] Fallback model '%s' also failed: %s", FALLBACK_MODEL, e)
        raise last_error or e


def chat(user_id: str, message: str, image_base64: str = None, image_mime: str = None) -> str:
    t0 = time.time()
    has_image = bool(image_base64)
    logger.info(
        "[chat] user=%s model=%s has_image=%s incoming_message=%r",
        user_id, MODEL_NAME, has_image, message,
    )

    client = get_client()
    data = load_products()

    history = conversation_history.setdefault(user_id, [])
    logger.debug("[chat] user=%s history_turns=%d", user_id, len(history))

    # Build the RAG retrieval query from recent conversation context + the
    # current message. Using recent turns too (not just `message` alone)
    # matters for short follow-ups like "হ্যাঁ কনফার্ম" that have no product
    # info by themselves but are clearly about the product just discussed.
    #
    # IMPORTANT: skip RAG filtering entirely when the customer sends an
    # image. Image matching works by visually comparing against ALL 11
    # reference photos (see get_reference_images below, unaffected by RAG),
    # but the system prompt also tells Gemini it MUST pick a product_id
    # from the text catalog list we give it. If that list is narrowed to
    # only the top-3 RAG matches of a weak/generic text query (image
    # messages often have no caption, so the query falls back to a vague
    # word like "পোশাক"), the real visual match can be visually correct
    # but get reported under the WRONG product id/name simply because the
    # right one wasn't in the shortlist — this was reproduced as "purple
    # dress 5 detected as dress 1". So for image turns we always pass the
    # FULL catalog, same as the reference images.
    if has_image or not RAG_ENABLED:
        retrieved_products = data["products"]
        logger.info(
            "[chat] user=%s has_image=%s RAG_ENABLED=%s — using full catalog (%d products).",
            user_id, has_image, RAG_ENABLED, len(retrieved_products),
        )
    else:
        recent_context = " ".join(turn["content"] for turn in history[-4:])
        query_text = (recent_context + " " + (message or "")).strip() or "পোশাক"
        retrieved_products = rag_engine.search(query_text, data, top_k=3)
        logger.debug(
            "[chat] user=%s retrieved %d/%d products via RAG for query=%r",
            user_id, len(retrieved_products), len(data["products"]), query_text[:120],
        )

    system_prompt = build_system_prompt(data["shop_bn"], retrieved_products)
    logger.debug(
        "[chat] system_prompt length=%d chars, product_count=%d",
        len(system_prompt), len(retrieved_products),
    )

    contents = []
    for turn in history[-10:]:
        contents.append(
            {"role": turn["role"], "parts": [{"text": turn["content"]}]}
        )

    # Build this turn's parts. Images aren't kept in `history` (would bloat
    # every future request) — only the resulting text conversation is.
    user_parts = [{"text": message or "(কাস্টমার একটা ছবি পাঠিয়েছেন, বিশ্লেষণ করে সাহায্য করো)"}]
    if has_image:
        try:
            image_bytes = base64.b64decode(image_base64)
            logger.info(
                "[chat] user=%s received image: mime=%s size=%d bytes",
                user_id, image_mime, len(image_bytes),
            )
            user_parts.append(
                types.Part.from_bytes(data=image_bytes, mime_type=image_mime or "image/jpeg")
            )
        except Exception as e:
            logger.exception("[chat] Failed to decode uploaded image for user=%s: %s", user_id, e)
            has_image = False

        if has_image:
            # Attach the REAL catalog photos too, so Gemini compares actual
            # image-to-image instead of guessing from text descriptions —
            # important since several dresses in this catalog look similar.
            refs = get_reference_images(data)
            user_parts.append({
                "text": "\n\nনিচে আমাদের ক্যাটালগের প্রতিটা পণ্যের আসল রেফারেন্স ছবি দেওয়া হলো, প্রতিটার আগে কোন প্রোডাক্ট সেটা লেখা আছে:"
            })
            for label, part in refs:
                user_parts.append({"text": label})
                user_parts.append(part)
            logger.info("[chat] user=%s attached %d reference images for comparison", user_id, len(refs))

    contents.append({"role": "user", "parts": user_parts})

    try:
        response = _generate_with_resilience(client, contents, system_prompt)
    except Exception as e:
        # This is where API-key / network / quota errors surface. Logging
        # the full exception here (not just "something went wrong") is
        # what lets you actually diagnose it instead of guessing.
        if "NOT_FOUND" in str(e) or "404" in str(e):
            logger.error(
                "[chat] Model '%s' seems unavailable to your API key. "
                "Set GEMINI_MODEL=<a current model id> in .env to override "
                "(check https://ai.google.dev/gemini-api/docs/models for what your key can access).",
                MODEL_NAME,
            )
        elif _is_overloaded_error(e):
            logger.error(
                "[chat] Both '%s' and fallback '%s' are overloaded right now. "
                "This is temporary on Google's side — try again shortly.",
                MODEL_NAME, FALLBACK_MODEL,
            )
        logger.exception("[chat] Gemini API call FAILED for user=%s: %s", user_id, e)
        raise

    reply = resolve_image_tags(response.text, data)
    elapsed = time.time() - t0
    logger.info(
        "[chat] user=%s reply_length=%d chars, took=%.2fs, reply_preview=%r",
        user_id, len(reply or ""), elapsed, (reply or "")[:120],
    )

    history_text = message if message else "(কাস্টমার একটা ছবি পাঠিয়েছিলেন)"
    if has_image and message:
        history_text = f"[ছবি সহ] {message}"
    history.append({"role": "user", "content": history_text})
    history.append({"role": "model", "content": reply})

    return reply


def clear_history(user_id: str):
    logger.info("[chat] clearing history for user=%s", user_id)
    conversation_history.pop(user_id, None)


# --- If you outgrow context-stuffing and actually need RAG later ---
# When your catalog grows into the hundreds of products (or you add
# unstructured docs like return policy / size guide / FAQs) and it no
# longer all fits cleanly in one prompt, the upgrade path is:
#   1. Embed each product/doc chunk (e.g. with a Gemini embedding model
#      or a local sentence-transformer).
#   2. Store vectors in a small vector DB (Chroma/FAISS are the easiest
#      to self-host; no separate server needed for FAISS).
#   3. On each user message, embed the query, retrieve the top-K most
#      relevant product chunks, and only inject THOSE into the prompt
#      instead of the whole catalog.
# Not needed today — flagging so you know where this file would change.
