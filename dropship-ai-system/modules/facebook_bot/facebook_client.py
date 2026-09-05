"""Facebook Messenger sender helpers.
Needs FB_PAGE_TOKEN in .env once you create the Meta App (see docs/facebook-setup.md).

Debug logging added throughout so you can see, in the server terminal,
exactly whether a message actually reached Facebook's Graph API and what
Facebook said back — this is the #1 place things silently fail (expired
token, wrong recipient id, page not subscribed, etc.), so every call logs
its outcome instead of failing quietly.
"""

import logging
import os
import time

import requests

logger = logging.getLogger("facebook_client")

FB_URL = "https://graph.facebook.com/v18.0/me/messages"


def _token_preview() -> str:
    token = os.getenv("FB_PAGE_TOKEN") or ""
    if not token:
        return "(MISSING)"
    return f"{token[:8]}...({len(token)} chars)"


def send_fb_reply(recipient_id: str, text: str):
    token = os.getenv("FB_PAGE_TOKEN")
    if not token:
        logger.error(
            "[fb_send] FB_PAGE_TOKEN is missing from .env — cannot send reply to %s. "
            "See docs/facebook-setup.md Step 4.",
            recipient_id,
        )
        return {"error": "FB_PAGE_TOKEN missing"}

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "access_token": token,
    }
    logger.info(
        "[fb_send] Sending text reply to psid=%s (len=%d chars, token=%s)",
        recipient_id, len(text or ""), _token_preview(),
    )
    t0 = time.time()
    try:
        r = requests.post(FB_URL, json=payload, timeout=15)
    except requests.RequestException as e:
        logger.exception("[fb_send] Network error while sending to Facebook: %s", e)
        return {"error": str(e)}

    elapsed = time.time() - t0
    body = r.json()
    if r.status_code == 200 and "error" not in body:
        logger.info(
            "[fb_send] OK — Facebook accepted the message for psid=%s in %.2fs (message_id=%s)",
            recipient_id, elapsed, body.get("message_id"),
        )
    else:
        # Common causes logged explicitly so you don't have to guess:
        # - "Invalid OAuth access token": FB_PAGE_TOKEN expired/wrong
        # - "not subscribed to this app / this person": recipient isn't Admin/Dev/Tester
        #   while in Development mode (see docs/facebook-setup.md Step 8)
        err = body.get("error", {})
        logger.error(
            "[fb_send] FAILED (status=%d, %.2fs) for psid=%s — Facebook said: code=%s type=%s message=%r. "
            "Full response: %s",
            r.status_code, elapsed, recipient_id,
            err.get("code"), err.get("type"), err.get("message"), body,
        )
    return body


def send_fb_image(recipient_id: str, image_url: str):
    token = os.getenv("FB_PAGE_TOKEN")
    if not token:
        logger.error("[fb_send] FB_PAGE_TOKEN is missing from .env — cannot send image to %s.", recipient_id)
        return {"error": "FB_PAGE_TOKEN missing"}

    payload = {
        "recipient": {"id": recipient_id},
        "message": {"attachment": {"type": "image", "payload": {"url": image_url}}},
        "access_token": token,
    }
    logger.info("[fb_send] Sending image to psid=%s url=%s", recipient_id, image_url)
    try:
        r = requests.post(FB_URL, json=payload, timeout=15)
    except requests.RequestException as e:
        logger.exception("[fb_send] Network error while sending image to Facebook: %s", e)
        return {"error": str(e)}

    body = r.json()
    if r.status_code == 200 and "error" not in body:
        logger.info("[fb_send] Image sent OK to psid=%s (message_id=%s)", recipient_id, body.get("message_id"))
    else:
        # NOTE: image_url must be publicly reachable over HTTPS — a
        # localhost/ngrok URL pointing at your own /assets/products/ path
        # generally works fine through the ngrok tunnel, but if this fails
        # check the URL loads in a normal browser first.
        err = body.get("error", {})
        logger.error(
            "[fb_send] Image FAILED for psid=%s — Facebook said: %s. Full response: %s",
            recipient_id, err.get("message"), body,
        )
    return body
