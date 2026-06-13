# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Webweave – Graph RAG Web Crawler.** A Graph-native Retrieval-Augmented Generation (RAG) pipeline over crawled websites. It runs as a single FastAPI service exposing a three-stage workflow: **crawl → embed → query**. The crawler renders JavaScript-heavy/SPA sites (Angular, React) with Playwright, builds a directed knowledge graph of pages and documents, embeds the content into a vector store, and answers questions by retrieving chunks and summarizing them with Anthropic Claude.

## Commands

All commands run from the repo root. The virtualenv is `projvenv/` (Windows).

```powershell
# Activate the venv
.\projvenv\Scripts\Activate.ps1

# Install dependencies + Playwright browser binaries (required before first crawl)
pip install -r requirements.txt
playwright install

# Run the API server (hot reload)
uvicorn app.main:app --reload     # serves http://127.0.0.1:8000

# Run the crawler standalone (bypasses the API)
python -m app.crawler <start_url>

# Run the embedder standalone
python -m app.embedder

# Debug / inspection scripts (run from inside the debug/ dir — they use ../ relative paths)
cd debug; python graph.py        # dumps the crawled graph
cd debug; python retrieval.py    # inspects the ChromaDB collection
```

There is no test suite, linter, or build step configured.

### API endpoints (the intended workflow, in order)
- `POST /crawl` `{"start_url": "..."}` — starts a background crawl; writes `data/crawled_graph.json`.
- `GET /status` — crawl progress (node/edge/frontier/visited counts).
- `POST /embed` — chunks + embeds the saved graph into ChromaDB at `chroma_store/`.
- `POST /rag` `{"query": "..."}` — retrieves top-5 chunks and returns a Gemini summary.
- `GET /graph` — full graph as Cytoscape JSON. `GET /node/{path}` — one node's attributes.

## Architecture

The pipeline is three decoupled stages that hand off via files on disk — there is no shared in-memory state between them except the crawler instance held in `app/main.py`'s `crawler_instance` dict.

1. **Crawl (`app/crawler.py` → `WebsiteCrawler`)**
   - Async BFS over a single domain using a Playwright Chromium page. The frontier is a plain list; `visited` / `downloaded_docs` are sets.
   - Builds a `networkx.DiGraph` where **node IDs are URL paths** (not full URLs). Nodes are typed `Page`, `Document`, or `Error`; edges are hyperlinks (parent path → child path).
   - Link extraction scans *every* element (not just `<a>`) to capture Angular `routerLink`-style attributes — this is the key to SPA support. URLs are normalized (fragment stripped, trailing slash removed).
   - Pages are JS-rendered with a **fixed 10-second sleep** after `goto` (not `networkidle`). Documents (`.pdf/.docx/...`) are downloaded via a `requests.Session` (TLS verification disabled) into `documents/`. Asset extensions (`.css/.js/.png/...`) are ignored.
   - Persists via `json_graph.node_link_data` to `data/crawled_graph.json`. `load_graph` reverses this.

2. **Embed (`app/embedder.py` → `RAGEmbedder`)**
   - Loads the node-link JSON, iterates nodes, and for `Page` nodes chunks `text_content`; for `Document` nodes extracts text from the downloaded file (PyPDF2 / python-docx).
   - Chunking: `RecursiveCharacterTextSplitter`, 512 chars / 64 overlap. Chunk IDs are `{source_url}__{i}`.
   - Stores into a ChromaDB `PersistentClient` collection `rag_docs` at `chroma_store/`, embedded with the SentenceTransformer model **`all-MiniLM-L6-v2`** (downloaded on first run).

3. **Query (`app/rag_service.py` → `RAGService`)**
   - Reopens the same `rag_docs` collection with the identical embedding function (the embedding model **must match** the embedder, or retrieval breaks).
   - Queries top-5 chunks, then prompts Anthropic Claude (`claude-haiku-4-5`, via the `anthropic` SDK) to refine/summarize. `answer_query` returns `{refined_chunks, summary}`; `app/main.py` returns only the `summary` field.
   - Lazily instantiated and cached as a module global in `app/main.py` on first `/rag` call.

`app/models.py` holds the Pydantic request/response schemas. `data/`, `chroma_store/`, `documents/`, and `.env` are gitignored (build artifacts / secrets).

## Configuration & environment

- **`ANTHROPIC_API_KEY`** must be set in a `.env` file at repo root (loaded via `python-dotenv`; see `.env.example`). `RAGService` raises on startup if it is missing — `/rag` will return an init error.
- **Windows-specific**: `app/main.py` sets `WindowsProactorEventLoopPolicy` so Playwright's subprocess transport works under asyncio. Preserve this when touching event-loop or startup code.
- The embedding model (`all-MiniLM-L6-v2`) is hardcoded in both `embedder.py` and `rag_service.py` — change them together. The Claude model is set via `ANTHROPIC_MODEL` in `rag_service.py`.

## Gotchas

- The crawler uses a **fixed 10-second sleep** per page rather than waiting on `networkidle`, so large crawls are slow but predictable. Tune in `WebsiteCrawler._process_page`.
- TLS verification is disabled on the document-download session (`requests`), and `InsecureRequestWarning` is silenced — intentional for crawling sites with bad certs.
- The README's "Phase 2 / Future Development" section describes an aspirational n8n/Supabase pipeline that is **not** what's implemented; the actual phase-2 is the `embed`/`rag` endpoints in this repo (ChromaDB + Claude).
