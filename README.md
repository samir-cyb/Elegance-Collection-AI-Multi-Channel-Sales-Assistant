# AI Chatbot for Bangladeshi Ladies’ Dress Shop

An intelligent conversational assistant for an e‑commerce store, combining **Google Gemini** (generative AI) with a **local RAG (Retrieval‑Augmented Generation)** pipeline. It helps customers browse products, compare styles from uploaded photos, and place orders – all in natural Bangla, with a warm and professional sales personality.

![Demo](https://via.placeholder.com/800x400?text=Chatbot+Demo) <!-- replace with actual screenshot -->

---

## ✨ Features

- **Product Discovery** – Users can ask about dresses, colors, fabrics, and prices.
- **Visual Matching** – Upload a photo of a dress; the bot compares it against the real catalog images (not just text) and suggests the closest matches.
- **Order Management** – Guided conversation to collect customer details, confirm orders, and save them to a local SQLite database.
- **Admin Dashboard Ready** – Orders and analytics events are logged for later visualization.
- **Bangla-first** – The bot speaks fluently in Bangla, with a friendly, human-like tone.
- **RAG for Scale** – Uses a local FAISS index + `multilingual-e5-base` embeddings to retrieve the most relevant products for each user query, even when the catalog grows to hundreds of items.

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|------------|
| **AI / LLM** | Google Gemini (via `google-genai` SDK) – `gemini-3.5-flash-lite` |
| **RAG** | FAISS + `sentence-transformers/multilingual-e5-base` (local) |
| **Backend** | Python 3.10+ (FastAPI / Flask – adapt as needed) |
| **Database** | SQLite (local) |
| **State** | In-memory conversation history per user |
| **Image Handling** | Base64 + MIME support for user‑uploaded photos |

---

## 📦 Prerequisites

- Python 3.10 or higher
- A **Google Gemini API key** (get one from [Google AI Studio](https://ai.google.dev/))
- (Optional) A local copy of the embedding model – or you can set the `EMBEDDING_MODEL_PATH` to use a cached Hugging Face model.

---

## 🔧 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/your-repo.git
   cd your-repo