from pydantic import BaseModel
from typing import Any, Dict

class CrawlRequest(BaseModel):
    start_url: str

class GraphStatsResponse(BaseModel):
    status: str
    node_count: int
    edge_count: int
    frontier_size: int
    visited_count: int

class NodeResponse(BaseModel):
    node_id: str
    attributes: Dict[str, Any]

class QueryRequest(BaseModel):
    query: str