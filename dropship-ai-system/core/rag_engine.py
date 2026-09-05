"""
RAG (Retrieval-Augmented Generation) engine for the product catalog.

Replaces the old "context stuffing" approach (pasting the entire
products.json into every prompt) with real retrieval:
  1. Each product is turned into one text "passage" (name, price, colors,
     fabric details, description).
  2. All passages are embedded with a local multilingual e5 model
     (intfloat/multilingual-e5-base — handles English, Bangla, and
     Banglish, per your setup) and stored in a FAISS vector index.
  3. On every customer message, we embed the message (as an e5 "query")
     and retrieve the top-K most similar product passages via cosine
     similarity (FAISS IndexFlatIP on L2-normalized vectors = cosine sim).
  4. Only those top-K products go into the Gemini system prompt, instead
     of the whole catalog.

Why this matters even for 5 products: it's the correct architecture to
scale to hundreds of products without changing the pipeline, and it's
what you explicitly asked for. At 5 products the accuracy difference vs.
context-stuffing will be small — but the retrieval quality is fully
inspectable via the logs below (see [rag] log lines) so you can verify it.

Index files live in core/data/faiss_index/ and are rebuilt automatically
whenever products.json changes (detected via a content hash stored
alongside the index) — otherwise the saved index is reused, so you don't
pay the embedding cost on every server restart.
"""

import hashlib
import json
import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger("rag_engine")

BASE_DIR = Path(__file__).resolve().parent
INDEX_DIR = BASE_DIR / "data" / "faiss_index"
INDEX_PATH = INDEX_DIR / "catalog.index"
META_PATH = INDEX_DIR / "catalog_meta.json"

EMBEDDING_MODEL_PATH = os.getenv(
    "EMBEDDING_MODEL_PATH",
    r"D:\Samir\capstone\models\full codes\notebooks\model_cache\models--intfloat--multilingual-e5-base\snapshots\d128750597153bb5987e10b1c3493a34e5a4502a",
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
TOP_K = int(os.getenv("RAG_TOP_K", "3"))

_model = None
_index = None
_meta = None  # list of {"product_id": ..., "text": ...} aligned with FAISS vector ids


def get_embedder():
    """Lazy-loads the local sentence-transformers e5 model. This can take
    a few seconds on first use — logged clearly so it's not mistaken for
    a hang."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("[rag] Loading embedding model from: %s", EMBEDDING_MODEL_PATH)
        t0 = __import__("time").time()
        _model = SentenceTransformer(EMBEDDING_MODEL_PATH)
        logger.info("[rag] Embedding model loaded in %.2fs", __import__("time").time() - t0)
    return _model


def _embed(texts: list, is_query: bool) -> np.ndarray:
    """e5 models require a 'query: ' or 'passage: ' prefix on every input
    — this is documented behavior of the intfloat/e5 model family, not
    optional. Skipping it measurably hurts retrieval quality."""
    model = get_embedder()
    prefix = "query: " if is_query else "passage: "
    prefixed = [prefix + t for t in texts]
    vectors = model.encode(prefixed, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.astype("float32")


def _product_to_passage(product: dict) -> str:
    """Turns one product into a single retrieval-friendly text chunk.
    Written in Bangla (matching the catalog's own language) so the
    multilingual embedding space aligns well with how customers actually
    ask questions (Bangla, English, or Banglish)."""
    colors = ", ".join(c["name"] for c in product.get("colors", []))
    details = product.get("details", {})
    detail_text = " ".join(f"{k}: {v}" for k, v in details.items())
    price = product.get("discount_price", product.get("price"))
    return (
        f"{product['name_bn']} ({product['name']}). "
        f"ক্যাটাগরি: {product.get('category', '')}. "
        f"দাম: {price} টাকা। "
        f"রঙ: {colors}। "
        f"{detail_text}। "
        f"{product.get('description_bn', '')}"
    ).strip()


def _content_hash(products_data: dict) -> str:
    raw = json.dumps(products_data["products"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_index(products_data: dict):
    import faiss

    products = products_data["products"]
    passages = [_product_to_passage(p) for p in products]
    logger.info("[rag] Building FAISS index for %d products...", len(products))
    t0 = __import__("time").time()
    vectors = _embed(passages, is_query=False)

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    meta = {
        "products_hash": _content_hash(products_data),
        "items": [{"product_id": p["id"], "text": passage} for p, passage in zip(products, passages)],
    }

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(
        "[rag] Index built and saved in %.2fs (%d vectors, dim=%d)",
        __import__("time").time() - t0, index.ntotal, vectors.shape[1],
    )
    return index, meta["items"]


def build_or_load_index(products_data: dict, force_rebuild: bool = False):
    """Called once at server startup (see main.py). Rebuilds the index
    only if products.json changed since the last build, or if the index
    files are missing/corrupt — otherwise loads the cached index from
    disk, which is near-instant."""
    global _index, _meta

    current_hash = _content_hash(products_data)

    if not force_rebuild and INDEX_PATH.exists() and META_PATH.exists():
        try:
            import faiss
            with open(META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("products_hash") == current_hash:
                _index = faiss.read_index(str(INDEX_PATH))
                _meta = meta["items"]
                logger.info(
                    "[rag] Loaded cached FAISS index from disk (%d vectors) — products.json unchanged.",
                    _index.ntotal,
                )
                return _index, _meta
            else:
                logger.info("[rag] products.json changed since last index build — rebuilding.")
        except Exception as e:
            logger.warning("[rag] Cached index unreadable (%s) — rebuilding.", e)

    _index, _meta = _build_index(products_data)
    return _index, _meta


def search(query_text: str, products_data: dict, top_k: int = None) -> list:
    """Returns the top_k most relevant FULL product dicts (from
    products_data) for the given query text, most relevant first. Falls
    back to returning the whole catalog if the RAG engine isn't ready for
    any reason — a broken vector search should never mean the bot goes
    silent on a customer."""
    top_k = top_k or TOP_K
    global _index, _meta

    if _index is None or _meta is None:
        try:
            build_or_load_index(products_data)
        except Exception as e:
            logger.error("[rag] Index unavailable (%s) — falling back to full catalog.", e)
            return products_data["products"]

    try:
        query_vec = _embed([query_text], is_query=True)
        k = min(top_k, _index.ntotal)
        scores, ids = _index.search(query_vec, k)
    except Exception as e:
        logger.exception("[rag] Search failed (%s) — falling back to full catalog.", e)
        return products_data["products"]

    products_by_id = {p["id"]: p for p in products_data["products"]}
    results = []
    for rank, (idx, score) in enumerate(zip(ids[0], scores[0])):
        if idx < 0 or idx >= len(_meta):
            continue
        product_id = _meta[idx]["product_id"]
        product = products_by_id.get(product_id)
        if product:
            results.append(product)
        logger.info(
            "[rag] match #%d: product_id=%s score=%.4f",
            rank + 1, product_id, float(score),
        )

    if not results:
        logger.warning("[rag] No matches found for query — falling back to full catalog.")
        return products_data["products"]

    return results
