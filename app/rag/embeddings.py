"""Configurable embeddings with an offline deterministic fallback."""

import hashlib
import math
import os
import re
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class HashEmbeddingProvider:
    """Small stable vectors for tests and local runs without API access."""

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in _tokens(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class OpenAIEmbeddingProvider:
    def __init__(self, model: str = "text-embedding-3-small") -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


class ResilientEmbeddingProvider:
    """Use OpenAI when available, but keep local operation safe if it fails."""

    def __init__(self, primary: EmbeddingProvider, fallback: EmbeddingProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self.primary.embed(texts)
        except Exception:
            return self.fallback.embed(texts)


def create_embedding_provider() -> EmbeddingProvider:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    placeholder_keys = {"your_api_key_here", "your-api-key-here", ""}
    fallback = HashEmbeddingProvider()
    if api_key.lower() not in placeholder_keys:
        try:
            return ResilientEmbeddingProvider(
                OpenAIEmbeddingProvider(os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")),
                fallback,
            )
        except Exception:
            pass
    return fallback