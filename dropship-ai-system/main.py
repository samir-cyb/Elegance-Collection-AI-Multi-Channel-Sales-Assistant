"""Combined server — runs Website Chat + Facebook Bot + Admin/Pixel modules
together, and serves the marketing website.

To sell "Website only" or "Facebook only" separately, comment out the
router you don't need (see the include_router calls below) — everything
else keeps working because each module only depends on core/, not on
each other.
"""

import logging
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from core.database import setup_database
from core.gemini_brain import load_products
from core import rag_engine

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "marketing-website"
from modules.website_chat.router import router as website_chat_router
from modules.facebook_bot.router import router as facebook_router
from modules.admin.router import router as admin_router

app = FastAPI(title="AI Dress Shop Bot")

# --- Startup sanity checks: fail loud at boot, not silently on first click ---
if not os.getenv("GEMINI_API_KEY"):
    logger.warning(
        "=" * 70 + "\n"
        "GEMINI_API_KEY is NOT set! The chatbot will return an error on\n"
        "every message until this is fixed.\n"
        "Fix: open the '.env' file (next to main.py) and add:\n"
        "    GEMINI_API_KEY=your_real_key_here\n"
        "(Note: '.env.example' is just a template — the app reads '.env'.)\n"
        + "=" * 70
    )
else:
    logger.info("GEMINI_API_KEY loaded OK.")

if not os.getenv("META_PIXEL_ID") or os.getenv("META_PIXEL_ID") == "YOUR_PIXEL_ID":
    logger.info("META_PIXEL_ID is a placeholder — real Meta Pixel will stay inactive (internal tracking still works).")

if not os.getenv("FB_PAGE_TOKEN"):
    logger.info("FB_PAGE_TOKEN is empty — Facebook module is inactive until you set it.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before production
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_database()

# --- Build (or load cached) the RAG vector index for product retrieval ---
# This loads the local e5 embedding model once at startup (can take a few
# seconds the very first time) so the first customer message isn't slow.
# If the embedding model path is wrong/missing, we log it loudly but don't
# crash the server — rag_engine.search() falls back to the full catalog.
try:
    _products_data = load_products()
    rag_engine.build_or_load_index(_products_data)
    logger.info("RAG index ready (product retrieval via FAISS is active).")
except Exception as e:
    logger.error(
        "=" * 70 + "\n"
        "RAG index could not be built! The bot will still work, but will\n"
        "fall back to sending the FULL product catalog on every message\n"
        "instead of using smart retrieval.\n"
        "Fix: check EMBEDDING_MODEL_PATH in your '.env' file points to a\n"
        "valid local sentence-transformers model folder.\n"
        f"Error: {e}\n"
        + "=" * 70
    )

# --- Modules (comment out one to sell the other separately) ---
app.include_router(website_chat_router)
app.include_router(facebook_router)
app.include_router(admin_router)

# --- Product images ---
app.mount("/assets", StaticFiles(directory=str(WEB_DIR / "assets")), name="assets")
app.mount("/css", StaticFiles(directory=str(WEB_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB_DIR / "js")), name="js")


@app.get("/")
async def home():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/products.html")
async def products_page():
    return FileResponse(str(WEB_DIR / "products.html"))


@app.get("/chatbot.html")
async def chatbot_page():
    return FileResponse(str(WEB_DIR / "chatbot.html"))


@app.get("/admin-login.html")
async def admin_login_page():
    return FileResponse(str(WEB_DIR / "admin-login.html"))


@app.get("/admin-dashboard.html")
async def admin_dashboard_page():
    return FileResponse(str(WEB_DIR / "admin-dashboard.html"))


if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 50)
    print("  Server ready! Open this in your browser:")
    print("  http://localhost:8000")
    print("=" * 50 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
