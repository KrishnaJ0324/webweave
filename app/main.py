from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import FileResponse
from .crawler import WebsiteCrawler
from .models import CrawlRequest, NodeResponse, GraphStatsResponse, QueryRequest
import networkx as nx
import asyncio
import sys
from pathlib import Path
from typing import Optional

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Fix event loop policy on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(
    title="Webweave – Graph RAG Web Crawler",
    description="Crawl a site, embed its knowledge graph, and query it with RAG.",
    version="1.1.0"
)

crawler_instance = {"crawler": None, "status": "idle"}
rag_service_instance: Optional[object] = None  # type: ignore

@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")

def run_crawl_task(url: str):
    asyncio.run(_async_crawl(url))

async def _async_crawl(url: str):
    crawler = WebsiteCrawler(start_url=url)
    crawler_instance["crawler"] = crawler
    crawler_instance["status"] = "crawling"
    crawler_instance["error"] = None
    try:
        await crawler.crawl()
        Path("data").mkdir(exist_ok=True)
        crawler.save_graph("data/crawled_graph.json")
        crawler_instance["status"] = "finished"
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[!!!] CRAWL FAILED: {e}")
        crawler_instance["status"] = "failed"
        crawler_instance["error"] = f"{type(e).__name__}: {e}"

@app.post("/crawl", status_code=202)
async def start_crawl(request: CrawlRequest, background_tasks: BackgroundTasks):
    if crawler_instance["status"] == "crawling":
        return {"message": "A crawl is already in progress."}
    # mark as crawling synchronously so the UI reflects it before the bg task starts
    crawler_instance["status"] = "crawling"
    crawler_instance["error"] = None
    background_tasks.add_task(run_crawl_task, request.start_url)
    return {"message": "Crawl initiated successfully."}

@app.get("/status", response_model=GraphStatsResponse)
async def get_status():
    crawler = crawler_instance.get("crawler")
    if not crawler:
        return {
            "status": crawler_instance.get("status", "idle"),
            "node_count": 0,
            "edge_count": 0,
            "frontier_size": 0,
            "visited_count": 0,
            "error": crawler_instance.get("error"),
        }
    return {
        "status": crawler_instance["status"],
        "node_count": crawler.graph.number_of_nodes(),
        "edge_count": crawler.graph.number_of_edges(),
        "frontier_size": len(crawler.frontier),
        "visited_count": len(crawler.visited),
        "error": crawler_instance.get("error"),
    }

@app.get("/node/{node_path:path}", response_model=NodeResponse)
async def get_node_data(node_path: str):
    if not node_path.startswith('/'):
        node_path = '/' + node_path
    crawler = crawler_instance.get("crawler")
    if not crawler or not crawler.graph.has_node(node_path):
        return {"error": "Node not found"}
    node_data = crawler.graph.nodes[node_path]
    return {"node_id": node_path, "attributes": node_data}

@app.get("/graph")
async def get_graph_data():
    crawler = crawler_instance.get("crawler")
    if not crawler:
        return {"error": "No graph data available."}
    return nx.cytoscape_data(crawler.graph)

@app.post("/embed")
async def run_embedding():
    try:
        from .embedder import RAGEmbedder
        RAGEmbedder(verbose=True).embed_graph()
        return {"message": "Embedding complete."}
    except Exception as e:
        return {"error": f"Embedding failed: {e}"}

@app.post("/rag")
async def rag_query(request: QueryRequest):
    global rag_service_instance
    if rag_service_instance is None:
        try:
            from .rag_service import RAGService
            rag_service_instance = RAGService()
        except Exception as e:
            return {"error": f"Failed to initialize RAG service: {e}"}
    
    try:
        result = rag_service_instance.answer_query(request.query)
        if "error" in result:
            return result
        return {
            "Results": result["summary"],
            "chunks": result.get("refined_chunks", []),
        }
    except Exception as e:
        return {"error": f"RAG query failed: {e}"}
