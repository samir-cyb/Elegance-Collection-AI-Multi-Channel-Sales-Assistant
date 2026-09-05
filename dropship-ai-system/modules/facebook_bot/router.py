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
import re
import time
from urllib.parse import urljoin

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from core.gemini_brain import chat, GeminiConfigError
from core.order_manager import is_order_confirmed, strip_order_json, process_confirmed_order
from modules.facebook_bot.facebook_client import send_fb_reply, send_fb_image

router = APIRouter()
logger = logging.getLogger("facebook_bot")

# Website chat renders Gemini's reply as Markdown (marked.js), so
# resolve_image_tags() in gemini_brain.py returns things like
# "![alt](/assets/products/dress-1.webp)" and "**bold**". Messenger has no
# Markdown renderer at all — it just shows that literally as text, and a
# relative "/assets/..." path means nothing to Facebook's servers anyway
# (they need a full public https:// URL to fetch and attach an image).
#
# So for Facebook we do the two things marked.js + the browser normally do
# for us: pull out each image link, turn it into an absolute URL, and send
# it as a real image attachment via the Send API — then strip the
# Markdown image/bold syntax out of the text reply so customers don't see
# literal "![...]()" or "**" characters.
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _split_text_and_images(reply: str, base_url: str) -> tuple[str, list[str]]:
    image_urls = []

    def _extract(match):
        url = match.group(2)
        # Facebook's Send API frequently rejects .webp attachments with
        # "(#100) Upload failed" — main.py exposes a /assets/products-jpg/
        # route that converts the same file to JPEG on the fly, so route
        # Facebook (only Facebook — the website keeps using the original
        # webp path, which it renders fine) through that instead.
        url = url.replace("/assets/products/", "/assets/products-jpg/", 1)
        image_urls.append(urljoin(base_url, url))
        return ""

    text_only = _MD_IMAGE_RE.sub(_extract, reply)
    text_only = re.sub(r"\*\*(.+?)\*\*", r"\1", text_only)  # **bold** -> bold
    text_only = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"\1", text_only)  # *italic* -> italic
    text_only = re.sub(r"\n{3,}", "\n\n", text_only).strip()
    return text_only, image_urls


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

            # CRITICAL: every message our own Page sends back to a customer
            # (via send_fb_reply/send_fb_image) is echoed back to THIS SAME
            # webhook by Facebook, as a "message_echoes" event with
            # message.is_echo = true — sender.id there is the PAGE, not the
            # customer. Without this check, the bot's own reply gets treated
            # as a new incoming message, which makes it reply to itself
            # forever (exactly the "messaging non-stop" bug). Always ignore
            # echoes; never generate a reply for one.
            if event.get("message", {}).get("is_echo"):
                logger.debug(
                    "[fb_message] Ignoring echo of our own outgoing message (sender=%s) — "
                    "not a real customer message.", sender,
                )
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

            text_only, image_urls = _split_text_and_images(reply, str(request.base_url))
            logger.info(
                "[fb_message] psid=%s reply has %d image(s) to send as attachments",
                sender, len(image_urls),
            )
            if text_only:
                send_fb_reply(sender, text_only)
            for url in image_urls:
                send_fb_image(sender, url)

    elapsed = time.time() - t0
    logger.info("[fb_message] Done — processed %d text message(s) in %.2fs", processed, elapsed)
    return {"status": "ok"}
