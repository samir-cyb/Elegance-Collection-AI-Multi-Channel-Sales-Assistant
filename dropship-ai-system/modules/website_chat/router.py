"""SELLABLE SEPARATELY: mount this router alone if a client only wants
the website chatbot, without Facebook."""

import logging
from fastapi import APIRouter, Request
from core.gemini_brain import chat, GeminiConfigError
from core.order_manager import is_order_confirmed, strip_order_json, process_confirmed_order

router = APIRouter()
logger = logging.getLogger("website_chat")


@router.post("/chat")
async def website_chat(request: Request):
    data = await request.json()
    user_id = data["user_id"]
    message = data.get("message", "")
    image_base64 = data.get("image_base64")
    image_mime = data.get("image_mime")

    # Guard against huge uploads before they ever reach Gemini (20MB request
    # limit on Google's side) — base64 is ~33% bigger than raw bytes.
    if image_base64 and len(image_base64) > 15_000_000:
        logger.warning("[/chat] user=%s uploaded an oversized image (%d chars base64)", user_id, len(image_base64))
        return {
            "reply": "ছবিটা একটু বেশি বড় মনে হচ্ছে 😅 একটু ছোট সাইজের ছবি (৫-৬ MB-এর কম) পাঠানোর চেষ্টা করুন।",
            "order_placed": False,
        }

    try:
        reply = chat(user_id, message, image_base64=image_base64, image_mime=image_mime)
    except GeminiConfigError as e:
        # Setup problem (missing/bad API key) — tell the frontend clearly
        # instead of a generic 500, so it's obvious what to fix.
        logger.error("[/chat] config error: %s", e)
        return {
            "reply": "দুঃখিত, সার্ভারে একটা সেটআপ সমস্যা আছে (Gemini API key)। Admin-কে জানানো হয়েছে।",
            "error": str(e),
        }
    except Exception as e:
        logger.exception("[/chat] unexpected error for user=%s", user_id)
        return {
            "reply": "দুঃখিত, এই মুহূর্তে উত্তর দিতে সমস্যা হচ্ছে। একটু পরে আবার চেষ্টা করুন।",
            "error": str(e),
        }

    order_placed = False
    if is_order_confirmed(reply):
        order = process_confirmed_order(reply, platform="website", user_id=user_id)
        order_placed = order is not None
        reply = strip_order_json(reply)  # never show the raw JSON block to the customer

    return {"reply": reply, "order_placed": order_placed}
