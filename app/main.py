"""Minimal HTTP interface for the support agent."""

from pathlib import Path
import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .agent import SupportAgent
from .memory import SessionMemory
from .rag.retriever import RAGRetriever
from .tools.order_lookup import OrderLookupTool

load_dotenv()
ROOT = Path(__file__).parents[1]
agent = SupportAgent(
    RAGRetriever(ROOT / "knowledge-base", persist_directory=ROOT / ".chroma"),
    OrderLookupTool(ROOT / "data" / "orders.json"),
    SessionMemory(),
)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)
    debug: bool = False


app = FastAPI(title="Aster & Row Support Agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> FileResponse:
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.post("/chat")
def chat(request: ChatRequest) -> dict:
    response = agent.respond(request.session_id, request.message, request.debug)
    return {
        "answer": response.answer,
        "route": response.route,
        "sources": response.sources,
        "handoff": response.handoff,
        "tool_calls": response.tool_calls,
        "trace": response.trace,
    }


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)