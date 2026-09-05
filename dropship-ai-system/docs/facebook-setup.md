# Facebook Messenger Setup — Step by Step

This is the setup guide for `modules/facebook_bot/` — the code is already
written and ready (see `router.py` and `facebook_client.py`), it's just
waiting for real credentials. Once you complete the steps below and put
the values in `.env`, this module goes live automatically.

## What the code expects (so you know exactly what you're collecting)

| `.env` variable | Where it's used | What it is |
|---|---|---|
| `FB_PAGE_TOKEN` | `facebook_client.py` | Page Access Token — lets the server send messages AS your Page |
| `FB_VERIFY_TOKEN` | `router.py` (`GET /webhook/facebook`) | A random string YOU invent — Facebook echoes it back once, to prove you control the server |

Webhook URL your server exposes: `POST/GET https://<your-public-url>/webhook/facebook`

## Step 1 — Create a Meta Developer account + App

1. Go to https://developers.facebook.com/ and log in with your normal Facebook account.
2. Click **My Apps → Create App**.
3. Choose the **"Other"** use case (or **"Business"** depending on what Meta shows you) → App type **"Business"**.
4. Give it a name (e.g. "Elegance Collection Bot") and create it.

## Step 2 — Add the Messenger product

1. Inside your new App's dashboard, find **Messenger** in the left sidebar / "Add Products" screen and click **Set up**.

## Step 3 — Connect your Facebook Page

1. You need a **Facebook Page** (not a personal profile) for your shop — create one first at https://facebook.com/pages/create if you don't have one yet.
2. In the App dashboard → **Messenger → Settings → Access Tokens** section, click **Add or Remove Pages** and connect your shop's Page (you must be an Admin of that Page).

## Step 4 — Generate the Page Access Token

1. Still in **Messenger → Settings → Access Tokens**, select your Page from the dropdown.
2. Click the **Page Access Token** field — it copies the token to your clipboard.
3. **Important:** Facebook does NOT save this token anywhere for you to see again later — copy it immediately into your `.env` file as `FB_PAGE_TOKEN=...`.
4. This token type only works while your app is in **Development mode** — it lets your Page talk to accounts that have Admin/Developer/Tester role on your app (perfect for testing before going public — see Step 7).

## Step 5 — Expose your local server publicly (needed for testing)

Facebook's webhook requires a real HTTPS public URL — it cannot reach `localhost:8000` directly. For local testing, use a tunnel tool like **ngrok**:

```
ngrok http 8000
```

This gives you a temporary public URL like `https://abcd1234.ngrok-free.app`. Your webhook URL to give Facebook is:

```
https://abcd1234.ngrok-free.app/webhook/facebook
```

(This URL changes every time you restart ngrok on the free plan — you'll need to re-save it in the Meta dashboard each time during testing. For a permanent setup, deploy the server to a real host later.)

## Step 6 — Configure the Webhook in the Meta dashboard

1. In your App dashboard → **Messenger → Settings → Webhooks**, click **Add Callback URL** (or **Edit**).
2. **Callback URL:** your ngrok/public URL + `/webhook/facebook` (from Step 5).
3. **Verify Token:** type any random string YOU choose (e.g. `samir_verify_2026`, already set as the default in this project's `.env.example`) — this MUST exactly match `FB_VERIFY_TOKEN` in your `.env` file.
4. Click **Verify and Save**. Facebook will send a GET request to your server; our `router.py`'s `fb_verify()` function checks the token matches and responds — if your server isn't running (or the URL is wrong), this step fails.
5. After verifying, **subscribe your Page to webhook fields**: check the boxes for **`messages`** and **`messaging_postbacks`** at minimum.
6. Also make sure your Page is subscribed under **Messenger → Settings → Webhooks → Page Subscriptions** (select your Page → Subscribe).

## Step 7 — Test it

1. Fill in `.env`:
   ```
   FB_PAGE_TOKEN=<the token from Step 4>
   FB_VERIFY_TOKEN=<the same string you typed in Step 6>
   ```
2. Restart your server (`python main.py`), keep ngrok running.
3. Open your Facebook Page, click **Message**, and send it a text as a customer would.
4. Check your server logs — you should see the message come in through `/webhook/facebook`, get a reply from রাফি (Gemini), and see the reply sent back via `send_fb_reply()`.
5. While in Development mode, only accounts with an Admin/Developer/Tester role on your App (add them under **App Roles → Roles**) can message the bot and get a reply — this is fine for your own testing.

## Step 8 — Going public (production, for real customers)

Right now the bot only replies to testers. To let ANY customer message your Page:

1. In the App dashboard, request **App Review** for the `pages_messaging` permission (Meta reviews this — you'll need to explain how the bot is used, screen recordings, privacy policy URL, etc.).
2. Once approved, switch the App from **Development** to **Live** mode.
3. Your ngrok tunnel needs to be replaced with a permanent server (a real domain/host) before going live — ngrok free URLs are not meant for production.

## Notes

- This module is independent from the website chatbot — you can sell "Facebook only" by only including `modules/facebook_bot/router.py` in `main.py` and removing the website widget, or sell both together (current setup).
- Image-sending to Facebook customers uses `send_fb_image()` in `facebook_client.py` (already written) — not yet wired into the `[SHOW_IMAGE: ...]` tag resolver the way the website chat is; flag this if you want Facebook customers to also see product photos automatically (currently only text replies are sent to Facebook).
