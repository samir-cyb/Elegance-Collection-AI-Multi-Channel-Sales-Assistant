"""SELLABLE SEPARATELY: mount this router alone if a client only wants
Facebook Messenger, without the website widget.

This is fully written and ready — it just needs real credentials once you
create the Meta Developer App and connect it to your existing Page
(see docs/facebook-setup.md). Until then this module stays inactive.

DEBUG LOGGING: every step of both the webhook verification handshake and
the actual message-receive-reply flow is logged, so when something isn't
working you can look at the server terminal and see exactly which step
failed instead of guessing — see docs/facebook-setup.md "Troubleshooting"
for what each log line means.
"""

import json
import logging
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from core.gemini_brain import chat, GeminiConfigError
from core.order_manager import is_order_confirmed, strip_order_json, process_confirmed_order
from modules.facebook_bot.facebook_client import send_fb_reply

router = APIRouter()
logger = logging.getLogger("facebook_bot")


@router.get("/webhook/facebook")
async def fb_verify(request: Request):
    """Facebook calls this once, when you save the Webhook URL in the
    Meta App dashboard, to prove you control this server. If you see
    NOTHING logged here at all when you click "Verify and Save" in the
    Meta dashboard, the request isn't reaching this server — check that
    (a) ngrok is still running, (b) the Callback URL you typed in Meta
    ends with /webhook/facebook, (c) main.py is running."""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    received_token = params.get("hub.verify_token")
    expected_token = os.getenv("FB_VERIFY_TOKEN")

    logger.info(
        "[fb_verify] Incoming verification request: mode=%s received_token=%r challenge=%r",
        mode, received_token, params.get("hub.challenge"),
    )

    if not expected_token:
        logger.error(
            "[fb_verify] FB_VERIFY_TOKEN is not set in your .env file! "
            "Verification will always fail until you set it. See docs/facebook-setup.md."
        )
        return PlainTextResponse("Error", status_code=403)

    if received_token == expected_token:
        logger.info("[fb_verify] SUCCESS — token matched. Facebook should now show 'Verified'.")
        return PlainTextResponse(params["hub.challenge"])

    logger.warning(
        "[fb_verify] FAILED — token mismatch. received=%r expected=%r "
        "(check for extra spaces/newlines when you pasted the token into Meta's dashboard, "
        "and that you restarted main.py after editing .env).",
        received_token, expected_token,
    )
    return PlainTextResponse("Error", status_code=403)


@router.post("/webhook/facebook")
async def fb_message(request: Request):
    """Facebook POSTs here for every message event once the webhook is
    verified and subscribed. If verification succeeded in Meta's
    dashboard but you NEVER see '[fb_message] Received webhook payload'
    logged here when you message the Page, the webhook fields (messages /
    messaging_postbacks) most likely aren't subscribed — see
    docs/facebook-setup.md Step 6."""
    t0 = time.time()
    data = await request.json()
    logger.info("[fb_message] Received webhook payload: %s", json.dumps(data, ensure_ascii=False)[:2000])

    entries = data.get("entry", [])
    if not entries:
        logger.warning("[fb_message] Payload had no 'entry' — nothing to process. Raw: %s", data)
        return {"status": "ok"}

    processed = 0
    for entry in entries:
        messaging_events = entry.get("messaging", [])
        if not messaging_events:
            logger.debug("[fb_message] entry had no 'messaging' events (probably a non-message webhook field)")
            continue

        for event in messaging_events:
            sender = event.get("sender", {}).get("id")
            if not sender:
                logger.warning("[fb_message] Event had no sender.id, skipping: %s", event)
                continue

            msg = event.get("message", {}).get("text", "")
            if not msg:
                # Could be a "seen"/"delivery" receipt, a postback, a sticker/image
                # with no text, etc. — logged so it's visible but intentionally
                # not sent to Gemini (nothing to reply to yet).
                logger.info(
                    "[fb_message] psid=%s sent a non-text event (no message.text) — ignoring. keys=%s",
                    sender, list(event.keys()),
                )
                continue

            logger.info("[fb_message] psid=%s says: %r", sender, msg)
            processed += 1

            try:
                reply = chat(sender, msg)
            except GeminiConfigError as e:
                logger.error("[fb_message] Gemini config error for psid=%s: %s", sender, e)
                send_fb_reply(sender, "দুঃখিত, সার্ভারে একটা সেটআপ সমস্যা আছে। একটু পরে চেষ্টা করুন।")
                continue
            except Exception as e:
                logger.exception("[fb_message] Gemini call FAILED for psid=%s: %s", sender, e)
                send_fb_reply(sender, "দুঃখিত, এই মুহূর্তে উত্তর দিতে সমস্যা হচ্ছে। একটু পরে আবার চেষ্টা করুন।")
                continue

            if is_order_confirmed(reply):
                logger.info("[fb_message] ORDER_CONFIRMED detected in reply for psid=%s", sender)
                order = process_confirmed_order(reply, platform="facebook_messenger", user_id=sender)
                logger.info("[fb_message] process_confirmed_order result for psid=%s: %s", sender, order)
                reply = strip_order_json(reply)  # never show the raw JSON block to the customer

            send_fb_reply(sender, reply)

    elapsed = time.time() - t0
    logger.info("[fb_message] Done — processed %d text message(s) in %.2fs", processed, elapsed)
    return {"status": "ok"}
