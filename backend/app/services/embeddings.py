"""Embedding providers for the memory subsystem.

The default provider calls the OpenAI embeddings endpoint. A deterministic
hashing fallback keeps the system fully functional in tests and offline
environments without external dependencies, while preserving the vector
dimensionality so the schema and indexes are unchanged.
"""
from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod
from functools import lru_cache

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Calls OpenAI's embeddings API."""

    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": texts, "dimensions": self._dimensions},
            )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Hash-based embeddings: stable, dependency-free, good enough for dev/test.

    Produces a unit-normalised vector by hashing token n-grams into buckets.
    Not semantically rich, but consistent and L2-normalised so cosine search
    behaves sensibly.
    """

    def __init__(self, dimensions: int) -> None:
        self._dim = dimensions

    async def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = text.lower().split()
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for gram in grams:
            h = int(hashlib.blake2b(gram.encode(), digest_size=8).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h >> 1) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Select a provider based on configuration."""
    import os

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        logger.info("embedding_provider", provider="openai", model=settings.embedding_model)
        return OpenAIEmbeddingProvider(
            openai_key, settings.embedding_model, settings.embedding_dimensions
        )
    logger.info("embedding_provider", provider="deterministic")
    return DeterministicEmbeddingProvider(settings.embedding_dimensions)
