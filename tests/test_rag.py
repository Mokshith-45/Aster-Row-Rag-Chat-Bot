from pathlib import Path

from app.rag.chunker import chunk_document
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.loader import load_documents
from app.rag.retriever import RAGRetriever


ROOT = Path(__file__).parents[1]


def make_retriever() -> RAGRetriever:
    return RAGRetriever(ROOT / "knowledge-base", HashEmbeddingProvider())


def test_loader_preserves_metadata_and_filename() -> None:
    documents = load_documents(ROOT / "knowledge-base")
    current = next(document for document in documents if document.source_filename == "01-returns-policy-current.md")
    assert current.metadata["status"] == "active"
    assert current.metadata["policy_authority"] == "official"
    assert current.metadata["document_id"] == "RET-2026-01"


def test_chunks_preserve_heading_context() -> None:
    document = load_documents(ROOT / "knowledge-base")[0]
    chunks = chunk_document(document)
    assert chunks
    assert all(chunk.source_filename == document.source_filename for chunk in chunks)
    assert any(chunk.heading == "Returns Policy > Standard return window" for chunk in chunks)


def test_active_returns_policy_beats_superseded_policy() -> None:
    result = make_retriever().retrieve("How long can a regular customer return an item?", top_k=5)
    filenames = [item.chunk.source_filename for item in result.chunks]
    assert filenames[0] == "01-returns-policy-current.md"
    assert not result.conflicts


def test_active_authoritative_product_sources_report_conflict() -> None:
    result = make_retriever().retrieve("Can I put the entire Breeze Tumbler in the dishwasher?", top_k=8)
    assert {"11-product-care.md", "12-breeze-tumbler-product-card.md"}.issubset(
        {item.chunk.source_filename for item in result.chunks}
    )
    assert result.conflicts
    assert set(result.conflicts[0]["sources"]) == {
        "11-product-care.md",
        "12-breeze-tumbler-product-card.md",
    }


def test_unrelated_query_does_not_report_product_conflict() -> None:
    result = make_retriever().retrieve("Do you ship internationally?", top_k=8)
    assert not result.conflicts


def test_products_retrieve_product_card() -> None:
    result = make_retriever().retrieve("What products do you offer?", top_k=5)
    assert result.chunks[0].chunk.source_filename == "12-breeze-tumbler-product-card.md"
    assert "Product details" in result.chunks[0].chunk.heading


def test_shipping_returns_and_warranty_retrieve_expected_documents() -> None:
    cases = {
        "What is your shipping policy?": "05-domestic-shipping.md",
        "What is your return policy?": "01-returns-policy-current.md",
        "What is your warranty policy?": "07-warranty.md",
    }
    for query, expected_source in cases.items():
        result = make_retriever().retrieve(query, top_k=5)
        assert expected_source in {item.chunk.source_filename for item in result.chunks}


def test_payment_query_has_no_accepted_methods_evidence() -> None:
    result = make_retriever().retrieve("What payment methods do you accept?", top_k=5)
    assert not any(
        "accepted payment" in item.chunk.text.lower()
        or "payment options" in item.chunk.text.lower()
        for item in result.chunks
    )