from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_endpoint_is_browser_friendly() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Aster & Row" in response.text
    assert "fetch(\"/chat\"" in response.text


def test_favicon_endpoint_is_empty_success() -> None:
    assert client.get("/favicon.ico").status_code == 204


def test_chat_works_with_placeholder_or_unavailable_embedding_credentials() -> None:
    response = client.post(
        "/chat",
        json={"session_id": "credential-fallback", "message": "What is the standard return window?"},
    )
    assert response.status_code == 200
    assert response.json()["route"] == "rag"