"""Index all supplied knowledge-base Markdown documents."""

from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rag.retriever import RAGRetriever


def main() -> int:
    retriever = RAGRetriever(ROOT / "knowledge-base", persist_directory=ROOT / ".chroma")
    print(f"Indexed {retriever.ingest()} chunks from knowledge-base/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())