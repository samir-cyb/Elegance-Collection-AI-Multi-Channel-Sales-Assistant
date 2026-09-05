# AI Dress Shop Chatbot System — Project Documentation

**Prepared for:** Samir
**Last updated:** August 14, 2026
**Status:** Phase 1 (Demo/Showcase) — built and running locally. Facebook module coded but inactive (no Meta App yet). Pixel wired but inactive (no real Pixel ID yet).

---

## 1. What this project is

A modular AI chatbot system for a women's dress/clothing shop, sellable to clients as "Website chatbot," "Facebook chatbot," or "Both" — plus a GSAP-animated marketing website (Home / Products / Chatbot) and an Admin analytics dashboard fed by pixel-style event tracking.

Two-phase plan:
- **Phase 1 (now):** working demo, sample real product data, local/free hosting, no payment gateway, no real auth.
- **Phase 2 (later):** real hosting, per-client config, proper admin auth, error logging/rate limiting, possibly multi-tenant support.

---

## 2. Where everything lives

Project root on your machine: `D:\Samir\programming\ai automation\dropship-ai-system\`

```
dropship-ai-system/
├── .env                          ← Your real secrets (Gemini key, tokens). Never share/commit this.
├── .env.example                  ← Template of what .env needs — you've filled this with your Gemini key.
├── requirements.txt              ← Python packages to install (see §5)
├── README.md                     ← Run/test instructions
├── main.py                       ← THE SERVER ENTRY POINT — run this file to start everything
│
├── core/                         ← Shared "brain" — every module below depends on this, nothing else
│   ├── gemini_brain.py           ← Talks to Gemini AI (google-genai SDK). Builds the AI's persona/rules,
│   │                               sends chat history + product list to Gemini, returns the reply.
│   ├── database.py               ← Creates the SQLite tables: `orders` and `events` (pixel log)
│   ├── order_manager.py          ← Saves orders, updates stock, logs pixel/analytics events,
│   │                               computes the numbers the Admin Dashboard shows
│   └── data/
│       ├── products.json         ← Your 5 real dresses (name, price, colors, stock, fabric details)
│       └── app.db                ← SQLite database file (auto-created the first time you run main.py)
│
├── modules/                      ← Each folder here is independently sellable — only imports from core/
│   ├── website_chat/
│   │   └── router.py             ← Defines POST /chat — the endpoint the chatbot page talks to
│   ├── facebook_bot/
│   │   ├── router.py             ← Defines the Facebook webhook (GET+POST /webhook/facebook) — fully
│   │   │                           written, INACTIVE until you add FB_PAGE_TOKEN etc. to .env
│   │   └── facebook_client.py    ← Sends replies/images back to Facebook Messenger via Graph API
│   └── admin/
│       └── router.py             ← Defines /api/track (logs pixel events), /api/admin/stats (dashboard
│                                    numbers), /api/config (hands the Pixel ID to the frontend),
│                                    /api/products (product list for the website)
│
└── marketing-website/            ← Pure HTML/CSS/JS — no build step, no npm. Served by main.py.
    ├── index.html                ← Home page — hero + GSAP ScrollTrigger scrollytelling sections
    ├── products.html             ← Product page — loads products live from /api/products, click → chatbot
    ├── chatbot.html               ← Live AI chat widget page
    ├── admin-login.html          ← Admin entry — "Demo" button (no real password yet, see §7)
    ├── admin-dashboard.html      ← Shows event counts + a 14-day bar chart, reads /api/admin/stats
    ├── css/style.css             ← All styling for every page (one shared stylesheet)
    ├── js/main.js                ← GSAP + ScrollTrigger animation setup (hero, story panels, product grid)
    ├── js/pixel.js               ← Meta Pixel loader + mirrors every event into our own /api/track
    └── assets/products/          ← Your actual product photos (dress-1 through dress-5, all color variants)
```

---

## 3. Architecture — how a message/click actually flows

**Chat flow (Website or Facebook, same brain):**
Customer types → `modules/website_chat/router.py` (or `modules/facebook_bot/router.py`) receives it → calls `core/gemini_brain.py` → which loads `core/data/products.json`, builds the system prompt (persona "রাফি", rules), sends it to Gemini via `google-genai` → gets a reply → if the reply contains `ORDER_CONFIRMED`, `core/order_manager.py` logs a "Lead" event → reply is sent back to the customer.

**Pixel/analytics flow:**
Every page load or click fires `js/pixel.js` → which does two things at once: (1) fires the real Meta Pixel `fbq(...)` if `META_PIXEL_ID` is set for real, (2) always calls `POST /api/track` on our own server → `modules/admin/router.py` → `core/order_manager.py: log_event()` → saved into the `events` table in `core/data/app.db`. The Admin Dashboard (`admin-dashboard.html`) then reads `GET /api/admin/stats`, which aggregates that same table.

**Why two tracking paths?** Facebook Ads Manager doesn't hand back real analytics through a simple API (needs Marketing API + business verification). This way you get a working, real dashboard today, and Facebook's own Pixel keeps working for ad retargeting once you add a real Pixel ID.

**Why modules are separate:** `website_chat/` and `facebook_bot/` each only import from `core/` — never from each other. `main.py` currently loads all three modules together (website + facebook + admin) as one combined server. To sell "Website only" or "Facebook only" to a client, comment out the router you don't need in `main.py` (each `app.include_router(...)` line is labeled).

---

## 4. Tech stack

| Layer | Technology | Note |
|---|---|---|
| AI | `google-genai` (NOT the deprecated `google-generativeai`) | `from google import genai; client = genai.Client(api_key=...)` |
| Backend | Python + FastAPI + Uvicorn | One process serves the API AND the website |
| Database | SQLite (`core/data/app.db`) | Fine for demo; swap to PostgreSQL for production (Railway gives this free) |
| Frontend | Vanilla HTML/CSS/JS | No framework, no build step — easy to duplicate per client |
| Animation | GSAP + ScrollTrigger (via CDN) | Scrollytelling on the Home page, reveal animations on Products |
| Facebook | Meta Graph API (Messenger Platform) | Coded, inactive until Meta App is created |
| Tracking | Meta Pixel + internal `events` table | Pixel ID placeholder until you create one in Events Manager |

---

## 5. Environment variables (`.env`)

| Variable | Purpose | Current status |
|---|---|---|
| `GEMINI_API_KEY` | Auth for Gemini AI calls | ✅ Filled in by you |
| `FB_PAGE_TOKEN` | Lets the server send Messenger replies | ⬜ Empty — needs Meta App |
| `FB_VERIFY_TOKEN` | Confirms webhook ownership to Facebook | Set to `samir_verify_2026` (your choice, no need to "get" this from anywhere) |
| `META_PIXEL_ID` | Real Facebook Pixel ID for ad retargeting | ⬜ Placeholder (`YOUR_PIXEL_ID`) — internal dashboard still works without it |

---

## 6. How to run & test

```bash
cd "D:\Samir\programming\ai automation\dropship-ai-system"
pip install -r requirements.txt
python main.py
```

Open `http://localhost:8000` in your browser:
- `/` → Home
- `/products.html` → Products (live from `products.json`)
- `/chatbot.html` → Chat with রাফি
- `/admin-login.html` → click "Demo হিসেবে প্রবেশ করুন" → dashboard

Direct API test (no browser needed):
```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"user_id\":\"t1\",\"message\":\"পার্টি ড্রেস আছে?\"}"
```

**Note:** I could not run this Gemini call from my side — my cloud workspace's network blocks `generativelanguage.googleapis.com` entirely (confirmed 403 before even reaching Google). Everything else (server boot, all pages, `/api/products`, `/api/admin/stats`) was tested and works. Test the actual chat reply on your own machine, and tell me the exact error text if it fails.

---

## 7. What's real vs. what's still a placeholder

| Feature | Status |
|---|---|
| Product catalog | ✅ Real — your 5 dresses, real prices/colors/fabric details |
| Website chat (Gemini) | ✅ Code complete — needs your local test to confirm the API key works |
| GSAP marketing website | ✅ Complete — Home/Products/Chatbot pages live |
| Pixel event logging (internal) | ✅ Complete — dashboard shows real numbers once you browse the site |
| Meta Pixel (real Facebook side) | ⬜ Inactive — needs a real Pixel ID from Facebook Events Manager |
| Facebook Messenger bot | ⬜ Inactive — code complete, needs Meta Developer App + tokens |
| Admin login | ⚠️ Demo-only — "Demo" button skips real auth on purpose (for showcasing). Must be replaced with real login before giving this to a client. |
| Order database | ✅ Working — SQLite, auto-created on first run |
| Hosting | Not deployed yet — plan is Railway (backend) + Vercel (frontend), see §8 |

---

## 8. Deployment plan (unchanged from earlier discussion)

- **Backend** (`main.py` + `core/` + `modules/`): Railway.app, free tier to start.
- **Marketing website**: can stay served by the same FastAPI app (current setup), or split off to Vercel/Netlify later if you want the site and API on separate URLs.
- **Facebook**: connect once you've created the Meta Developer App (Page already exists).
- **Database**: SQLite now → PostgreSQL (Railway free tier) when you're ready for production traffic.

---

## 9. Next steps (in order)

1. Rename `env_content_rename_to_dotenv.txt` cleanup is done — confirm `.env` has your real Gemini key (you've already updated `.env.example`; make sure the actual `.env` file also has it, since that's the file the code reads).
2. Run `python main.py` locally and test the chatbot reply — report back any error text.
3. Once chat works: decide on a real Meta Pixel ID (create one in Facebook Events Manager) and a Meta Developer App (for Messenger) when you're ready to activate those two modules.
4. When ready to show clients: deploy to Railway.
5. Before selling to any real client: replace the Admin "Demo" button with real authentication.
