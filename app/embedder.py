from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from textwrap import shorten
from typing import Any, Dict, List, Tuple

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain.text_splitter import RecursiveCharacterTextSplitter
from networkx.readwrite import json_graph
from tqdm import tqdm
from PyPDF2 import PdfReader
import docx

# --------------------------------------------------------------------------- paths
GRAPH_PATH = Path("data/crawled_graph.json")
PERSIST_DIR = "chroma_store"
COLLECTION_NAME = "rag_docs"

# --------------------------------------------------------------------------- class
class RAGEmbedder:
    def __init__(
        self,
        graph_path: Path = GRAPH_PATH,
        persist_dir: str = PERSIST_DIR,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        verbose: bool = True,
    ) -> None:
        self.graph_path = graph_path
        self.verbose = verbose

        self._log(f"[INIT] graph      → {self.graph_path}")
        self._log(f"[INIT] chroma dir → {persist_dir}")

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME, embedding_function=self.embedding_fn
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    # ------------------------------------------------------------------- logging
    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    # ------------------------------------------------------------------- helpers
    def _chunk_and_add(self, text: str, meta: Dict[str, Any]) -> int:
        chunks = self.splitter.split_text(text)
        if not chunks:
            return 0

        ids = [f"{meta['source']}__{i}" for i in range(len(chunks))]

        self._log(f"    ↳ {len(chunks)} chunk(s)")
        for i, c in enumerate(chunks):
            preview = shorten(c.replace("\n", " "), 80, placeholder="…")
            self._log(f"        {i+1:02}/{len(chunks):02}  {preview}")

        self.collection.add(documents=chunks, ids=ids, metadatas=[meta] * len(chunks))
        return len(chunks)

    def _extract_text_from_file(self, path: Path) -> str:
        mime = mimetypes.guess_type(path)[0] or ""
        try:
            if mime == "application/pdf":
                return "\n".join(
                    page.extract_text() or "" for page in PdfReader(str(path)).pages
                )
            if mime in (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
            ):
                return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
            if mime.startswith("text/"):
                return path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            self._log(f"[!] failed to read {path}: {exc}")
        return ""

    # ------------------------------------------------------------------- main
    def embed_graph(self) -> None:
        if not self.graph_path.exists():
            raise FileNotFoundError(self.graph_path)

        # ── load graph
        data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        graph = json_graph.node_link_graph(data)
        self._log(f"[LOAD] graph has {graph.number_of_nodes()} nodes\n")

        # ── stats
        page_ok = doc_ok = page_skip = doc_skip = 0
        total_chunks = 0

        # ── iterate nodes
        for node_id, attrs in tqdm(
            graph.nodes(data=True), total=graph.number_of_nodes(), desc="Embedding"
        ):
            ntype = attrs.get("node_type")
            url   = attrs.get("url", node_id)

            if ntype == "Page":
                text = attrs.get("text_content", "")
                if not text.strip():
                    page_skip += 1
                    self._log(f"[SKIP-PAGE] empty text • {url}")
                    continue

                self._log(f"[PAGE] {url}  ({len(text)} chars)")
                chunks = self._chunk_and_add(
                    text, {"source": url, "title": attrs.get("title", ""), "type": "html"}
                )
                total_chunks += chunks
                page_ok += 1

            elif ntype == "Document":
                local_path = attrs.get("local_path")
                if not local_path or not os.path.exists(local_path):
                    doc_skip += 1
                    self._log(f"[SKIP-DOC ] file missing • {url}")
                    continue

                text = self._extract_text_from_file(Path(local_path))
                if not text.strip():
                    doc_skip += 1
                    self._log(f"[SKIP-DOC ] no text extracted • {local_path}")
                    continue

                self._log(f"[DOC ] {local_path}  ({len(text)} chars)")
                chunks = self._chunk_and_add(
                    text,
                    {
                        "source": url,
                        "title": attrs.get("doc_name", Path(local_path).name),
                        "type": attrs.get("content_type", "application/octet-stream"),
                    },
                )
                total_chunks += chunks
                doc_ok += 1

            else:
                # Error or some other node type – ignore for embedding
                self._log(f"[SKIP-{ntype}] {url}")
                continue

        # ── finish
        self.client.persist()
        self._log("\n[✓] Embedding finished")
        self._log(f"    pages embedded    : {page_ok}")
        self._log(f"    documents embedded: {doc_ok}")
        self._log(f"    pages skipped     : {page_skip}")
        self._log(f"    documents skipped : {doc_skip}")
        self._log(f"    total chunks      : {total_chunks}")
        self._log(f"    collection size   : {self.collection.count()} vectors")

# --------------------------------------------------------------------------- CLI
if __name__ == "__main__":
    RAGEmbedder(verbose=True).embed_graph()
