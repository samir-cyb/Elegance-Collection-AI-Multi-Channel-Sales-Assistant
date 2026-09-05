# Elegance Collection AI — Multi-Channel Dropshipping Sales Assistant

An AI-powered sales chatbot system for a Bangladeshi women's dress/clothing shop, built as a modular, independently-sellable product: a website chat widget and a Facebook Messenger bot, both sharing one AI "brain," backed by a RAG (retrieval-augmented generation) product-catalog pipeline and an admin analytics dashboard.

## What this is

**রাফি** is a warm, human-like Bangla-speaking AI sales assistant that talks to customers, shows them real product photos, understands photos *they* send back (visual matching against the catalog), walks them through placing an order step by step, and saves confirmed orders straight into the database — visible on a live admin dashboard. It's built to be sold as "Website chatbot," "Facebook chatbot," or both, to different clients, without duplicating code.

## Architecture

```
dropship-ai-system/
├── core/                     # Shared AI brain — used by every sellable module
│   ├── gemini_brain.py       #   Gemini chat logic, prompt, vision (photo matching), retry/fallback
│   ├── rag_engine.py         #   FAISS + multilingual-e5 embeddings — retrieves relevant products per query
│   ├── order_manager.py      #   Order extraction/persistence, duplicate-order guard, event logging
│   ├── database.py           #   SQLite setup (orders + events tables)
│   └── data/products.json    #   Product catalog (name, price, colors, stock, images)
├── modules/
│   ├── website_chat/         # Sellable separately — website chat widget API
│   ├── facebook_bot/         # Sellable separately — Facebook Messenger webhook + sender
│   └── admin/                # Pixel-style event tracking + orders/analytics API
├── marketing-website/        # Home / Products / Chatbot / Admin pages (GSAP-animated, vanilla JS)
├── docs/facebook-setup.md    # Step-by-step Meta App + webhook setup guide
├── main.py                   # Combined server — comment out a router to sell a module standalone
└── requirements.txt
```

## Key design choices

- **Modular by design** — `core/` has zero dependency on any specific channel; `modules/website_chat` and `modules/facebook_bot` can each be deployed alone.
- **RAG over context-stuffing** — product retrieval uses a local `intfloat/multilingual-e5-base` embedding model + FAISS cosine similarity, not "paste the whole catalog into every prompt." Handles English, Bangla, and Banglish queries. Falls back to the full catalog if the index isn't ready, so a broken vector search never means the bot goes silent.
- **Vision-based photo matching** — when a customer sends their own photo, real catalog reference images are attached alongside it so Gemini compares images directly instead of guessing from text descriptions (several dresses in the catalog look visually similar).
- **Structured order capture** — Gemini is instructed to emit a machine-parseable confirmation block once an order is confirmed; the backend extracts, validates, and persists it (with a duplicate-order guard for slow replies / double-submits), rather than just logging a generic "lead" event.
- **Resilient by default** — automatic retry + model fallback on Gemini overload errors, graceful handling of missing API keys/tokens, and heavy structured logging throughout for debugging in production.

## Tech stack

- **Backend:** FastAPI, Uvicorn, SQLite
- **AI:** Google `google-genai` SDK (Gemini), `sentence-transformers` (multilingual-e5), FAISS
- **Frontend:** Vanilla HTML/CSS/JS, GSAP + ScrollTrigger, `marked.js` for markdown rendering
- **Channels:** Website chat widget, Facebook Messenger (Graph API)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Mac/Linux

pip install -r requirements.txt
cp .env.example .env            # then fill in real values — see below
python main.py
```

Open **http://localhost:8000**.

### Required `.env` values

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio API key |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | Override if your key's available models change |
| `FB_PAGE_TOKEN` / `FB_VERIFY_TOKEN` | Facebook Messenger — see `docs/facebook-setup.md` |
| `META_PIXEL_ID` | Optional — leave as placeholder for internal-only event tracking |
| `EMBEDDING_MODEL_PATH` | Local path or Hugging Face model id for the RAG embedding model |

## Status

Website chatbot: fully working (chat, order capture, image upload/matching, admin dashboard).
Facebook Messenger: code complete, pending live webhook verification with a real Meta App (see `docs/facebook-setup.md`).
Admin login is demo-only (no real auth) — replace before selling to a real client.
