from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import List
from urllib.parse import urljoin, urlparse

import networkx as nx
from bs4 import BeautifulSoup
from networkx.readwrite import json_graph
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─────────────────────────────── paths ────────────────────────────────────────
DATA_DIR  = Path("data")
DOCS_DIR  = Path("documents")
GRAPH_PATH = DATA_DIR / "crawled_graph.json"

# ─────────────────────────────── crawler ──────────────────────────────────────
class WebsiteCrawler:
    """
    Asynchronous crawler that builds a directed graph of every internal page
    and downloadable document, then stores it as JSON (node-link format).
    """

    # ------------------------------------------------------------------ init
    def __init__(self, start_url: str, *, headless: bool = True) -> None:
        self.start_url = self._normalize_url(start_url)
        self.domain     = urlparse(self.start_url).netloc

        self.frontier:   List[str]   = [self.start_url]
        self.visited:    set[str]    = set()      # HTML pages already processed
        self.downloaded_docs: set[str] = set()    # document-URLs already fetched
        self.graph                   = nx.DiGraph()

        self.headless   = headless
        self.playwright = None
        self.browser    = None
        self.page       = None

        # single requests.Session for all binary downloads
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        )

        # what to treat as “documents” and what to ignore completely
        self.doc_ext   = {".pdf", ".docx", ".doc", ".pptx", ".ppt",
                          ".xlsx", ".xls"}
        self.ignore_ext = {".css", ".js", ".svg", ".ico", ".jpg", ".jpeg",
                           ".png", ".gif", ".webmanifest", ".xml", ".zip",
                           ".rar", ".mp4", ".mp3"}

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _normalize_url(url: str) -> str:
        """strip whitespace + fragment, normalise path slashes etc."""
        p = urlparse(url.strip())
        path = p.path.rstrip("/") or "/"
        return p._replace(fragment="", path=path).geturl()

    async def _start_browser(self):
        self.playwright = await async_playwright().start()
        self.browser    = await self.playwright.chromium.launch(headless=self.headless)
        self.page       = await self.browser.new_page()

    async def _close_browser(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    # ---------------------------------------------------------------- crawl
    async def crawl(self):
        await self._start_browser()
        try:
            while self.frontier:
                url = self.frontier.pop(0)
                if url in self.visited:
                    continue

                print(f"[*] {url}")
                self.visited.add(url)

                # direct document URL
                if any(url.lower().endswith(ext) for ext in self.doc_ext):
                    await self._handle_document(url, source_text="Direct-link")
                    continue

                # HTML page
                await self._process_page(url)
                await asyncio.sleep(1)         # politeness delay
        finally:
            await self._close_browser()

    # ---------------------------------------------------------------- pages
    async def _process_page(self, url: str):
        try:
            await self.page.goto(url, timeout=60_000)
            # fixed 10-second wait instead of networkidle
            await asyncio.sleep(10)
            html = await self.page.content()

            soup  = BeautifulSoup(html, "lxml")
            title = soup.title.string if soup.title else "No title"

            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)

            links = await self._extract_links(url, soup)
            self._add_page_node(url, title, text, links)

            print(f"    ↳ {len(links)} new link(s)")

        except PlaywrightTimeoutError:
            print(f"[!] timeout while loading {url}")
            self._add_error_node(url, "Timeout while loading page")
        except Exception as exc:
            print(f"[!] page error {url} -> {exc}")
            self._add_error_node(url, str(exc))

    # async def _extract_links(self, base_url: str, soup: BeautifulSoup) -> List[str]:
    #     parent_path = urlparse(base_url).path or "/"
    #     found: List[str] = []

    #     for tag in soup.find_all("a", href=True):
    #         href = tag["href"]

    #         if href.startswith(("#", "mailto:", "tel:", "javascript:")):
    #             continue
    #         if any(href.lower().endswith(ext) for ext in self.ignore_ext):
    #             continue

    #         abs_url = self._normalize_url(urljoin(base_url, href))
    #         if urlparse(abs_url).netloc != self.domain:
    #             continue

    #         child_path = urlparse(abs_url).path or "/"
    #         self.graph.add_edge(parent_path, child_path)

    #         if any(abs_url.lower().endswith(ext) for ext in self.doc_ext):
    #             # document
    #             if abs_url not in self.downloaded_docs:
    #                 await self._handle_document(abs_url, tag.get_text(strip=True))
    #         else:
    #             # html page
    #             if abs_url not in self.visited and abs_url not in self.frontier:
    #                 self.frontier.append(abs_url)

    #         found.append(abs_url)
    #     return found

    # ── crawler.py – replace the whole _extract_links method ─────────────
    async def _extract_links(self, base_url: str, soup: BeautifulSoup) -> List[str]:
        """
        Return a list of absolute URLs discovered in the page.

        • Handles classic <a href="…"> links.  
        • Handles Angular / SPA links that live on *any* element via
          routerLink-style attributes (routerLink, routerlink, ng-reflect-router-link).
        """
        parent_path = urlparse(base_url).path or "/"
        found: List[str] = []

        # look at **every** element, not only <a>
        for tag in soup.find_all(True):
            # ---- 1. pick the best candidate URL on this tag -----------------
            candidate = None

            href = tag.get("href")
            # usable <a href="…"> ?
            if href and href not in ("", "#", "javascript:void(0)"):
                candidate = href
            else:
                # fall back to Angular routerLink-style directives
                for attr in (
                    "routerLink",
                    "routerlink",
                    "ng-reflect-router-link",
                ):
                    if attr in tag.attrs and tag.attrs[attr]:
                        candidate = tag.attrs[attr]
                        break

            if not candidate:
                continue  # nothing useful on this element

            # ---- 2. clean & validate ---------------------------------------
            if any(candidate.lower().startswith(p) for p in ("mailto:", "tel:", "javascript:")):
                continue
            if any(candidate.lower().endswith(ext) for ext in self.ignore_ext):
                continue

            abs_url = self._normalize_url(urljoin(base_url, candidate))
            if urlparse(abs_url).netloc != self.domain:
                continue

            # ---- 3. add to graph / queues ----------------------------------
            child_path = urlparse(abs_url).path or "/"
            self.graph.add_edge(parent_path, child_path)

            if any(abs_url.lower().endswith(ext) for ext in self.doc_ext):
                # document
                if abs_url not in self.downloaded_docs:
                    await self._handle_document(abs_url, tag.get_text(strip=True))
            else:
                # html page
                if abs_url not in self.visited and abs_url not in self.frontier:
                    self.frontier.append(abs_url)

            found.append(abs_url)

        return found

    # ---------------------------------------------------------------- documents
    async def _handle_document(self, url: str, source_text: str):
        if url in self.downloaded_docs:
            return

        try:
            resp = self.session.get(url, timeout=30, stream=True)
            resp.raise_for_status()

            name      = os.path.basename(urlparse(url).path) or "file"
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", name)
            DOCS_DIR.mkdir(exist_ok=True)
            local_path = DOCS_DIR / safe_name

            with local_path.open("wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)

            print(f"    ↳ downloaded {safe_name}")

            self._add_doc_node(
                url,
                source_text,
                str(local_path),
                resp.headers.get("content-type", "application/octet-stream"),
            )
            self.downloaded_docs.add(url)

        except Exception as exc:
            print(f"[!] download error {url} -> {exc}")
            self._add_error_node(url, str(exc))

    # ---------------------------------------------------------------- graph nodes
    def _add_page_node(self, url: str, title: str, text: str, links: List[str]):
        path = urlparse(url).path or "/"
        self.graph.add_node(
            path,
            node_type="Page",
            url=url,
            title=title,
            text_content=text,
            hyperlink_targets=links,
            crawled=dt.datetime.utcnow().isoformat(),
        )

    def _add_doc_node(self, url: str, anchor: str, local_path: str, mime: str):
        path = urlparse(url).path or "/"
        self.graph.add_node(
            path,
            node_type="Document",
            url=url,
            source_text=anchor,
            local_path=local_path,
            content_type=mime,
            doc_name=os.path.basename(path),
            crawled=dt.datetime.utcnow().isoformat(),
        )

    def _add_error_node(self, url: str, message: str):
        path = urlparse(url).path or "/"
        self.graph.add_node(
            path,
            node_type="Error",
            url=url,
            error_message=message,
            crawled=dt.datetime.utcnow().isoformat(),
        )

    # ---------------------------------------------------------------- persist
    def save_graph(self, path: Path | str = GRAPH_PATH):
        """
        Serialise the graph as node-link JSON.
        edges='links' keeps current behaviour and silences the NetworkX warning.
        """
        path = Path(path)
        DATA_DIR.mkdir(exist_ok=True)

        data = json_graph.node_link_data(self.graph, edges="links")
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        print(f"[+] graph saved to {path} "
              f"({self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges)")

    # utility for other modules
    @staticmethod
    def load_graph(path: Path | str = GRAPH_PATH) -> nx.DiGraph:
        path = Path(path)
        return json_graph.node_link_graph(json.loads(path.read_text(encoding="utf-8")))

# ─────────────────────────────── CLI helper ───────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python crawler.py <start_url>")
        sys.exit(1)

    start = sys.argv[1]
    crawler = WebsiteCrawler(start)
    asyncio.run(crawler.crawl())
    crawler.save_graph()
