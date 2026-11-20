"""Local Embedding Engine for PROJECT ZORO Milestone 05.

Generates 384-dimensional dense vectors using Ollama's local 'all-minilm' model.
Includes an offline fallback projector to guarantee high-availability if Ollama
is temporarily unreachable.
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import List, Optional, Tuple
import httpx
import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL: str = "all-minilm"
DEFAULT_EMBEDDING_DIM: int = 384
DEFAULT_OLLAMA_URL: str = "http://127.0.0.1:11434"


class LocalEmbeddingEngine:
    """
    Manages local dense vector generation and cosine similarity matching.
    Guarantees 100% offline, local-only execution without external network calls.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        base_url: str = DEFAULT_OLLAMA_URL,
        dimension: int = DEFAULT_EMBEDDING_DIM,
        timeout_sec: float = 5.0,
    ) -> None:
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.dimension = dimension
        self.timeout_sec = timeout_sec
        self._cache: dict[str, Tuple[np.ndarray, str]] = {}
        self._max_cache_size: int = 1024
        self.last_model_used: str = self.model_name

    def embed_text(self, text: str) -> np.ndarray:
        """
        Generate a normalized 384-dim dense embedding for the given text.
        Returns a float32 NumPy array with unit norm.
        """
        vec, _ = self.embed_text_with_metadata(text)
        return vec

    def embed_text_with_metadata(self, text: str) -> Tuple[np.ndarray, str]:
        """
        Generate a normalized 384-dim dense embedding for the given text,
        along with the exact model name ('all-minilm' or 'fallback-ngram')
        that generated the vector.
        """
        cleaned = text.strip()
        if not cleaned:
            # Return zero vector for empty text
            return np.zeros(self.dimension, dtype=np.float32), "none"

        # Check cache
        cache_key = f"{self.model_name}:{cleaned}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Attempt Ollama local embedding
        vector = self._embed_via_ollama(cleaned)
        model_used = self.model_name
        if vector is None:
            # Offline deterministic fallback
            logger.debug("Falling back to local deterministic embedding for: '%.40s...'", cleaned)
            vector = self._embed_offline_fallback(cleaned)
            model_used = "fallback-ngram"

        self.last_model_used = model_used

        # Normalize to unit length for fast dot product cosine similarity
        norm = np.linalg.norm(vector)
        if norm > 1e-6:
            vector = vector / norm
        else:
            vector = np.zeros(self.dimension, dtype=np.float32)

        # Maintain cache
        if len(self._cache) >= self._max_cache_size:
            # Drop earliest 25% entries
            keys_to_drop = list(self._cache.keys())[: (self._max_cache_size // 4)]
            for k in keys_to_drop:
                self._cache.pop(k, None)
        self._cache[cache_key] = (vector, model_used)

        return vector, model_used

    def _embed_via_ollama(self, text: str) -> Optional[np.ndarray]:
        """Query local Ollama instance for embeddings."""
        endpoint = f"{self.base_url}/api/embeddings"
        payload = {"model": self.model_name, "prompt": text}
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.post(endpoint, json=payload)
                if resp.status_code == 200:
                    raw_emb = resp.json().get("embedding")
                    if raw_emb and len(raw_emb) == self.dimension:
                        return np.array(raw_emb, dtype=np.float32)
                    elif raw_emb:
                        # Resize or project if dimension differs
                        logger.warning(
                            "Ollama returned unexpected dimension %d (expected %d). Projecting.",
                            len(raw_emb),
                            self.dimension,
                        )
                        arr = np.array(raw_emb, dtype=np.float32)
                        if len(arr) > self.dimension:
                            return arr[: self.dimension]
                        else:
                            padded = np.zeros(self.dimension, dtype=np.float32)
                            padded[: len(arr)] = arr
                            return padded
                else:
                    logger.debug("Ollama embedding endpoint returned status %d", resp.status_code)
        except Exception as e:
            logger.debug("Ollama embedding query failed (%s)", e)

        return None

    def _embed_offline_fallback(self, text: str) -> np.ndarray:
        """
        Deterministic, local character n-gram pseudo-semantic projector.
        Guarantees that when Ollama is offline or restarting, search and storage
        continue functioning without unhandled exceptions.
        """
        vec = np.zeros(self.dimension, dtype=np.float32)
        words = text.lower().split()
        for idx, word in enumerate(words):
            # Positional hash weight
            pos_weight = 1.0 / math.sqrt(idx + 1)
            # Word hash
            h_word = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
            dim_idx = h_word % self.dimension
            sign = 1.0 if ((h_word >> 10) & 1) == 0 else -1.0
            vec[dim_idx] += sign * pos_weight

            # Character 3-grams for morphological similarity
            for i in range(max(1, len(word) - 2)):
                tri = word[i : i + 3]
                h_tri = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16)
                t_idx = h_tri % self.dimension
                t_sign = 1.0 if ((h_tri >> 5) & 1) == 0 else -1.0
                vec[t_idx] += 0.3 * t_sign * pos_weight

        return vec

    @staticmethod
    def vector_to_bytes(vector: np.ndarray) -> bytes:
        """Serialize a float32 NumPy vector to raw binary bytes for SQLite BLOB storage."""
        return vector.astype(np.float32).tobytes()

    @staticmethod
    def bytes_to_vector(blob: bytes, dimension: int = DEFAULT_EMBEDDING_DIM) -> np.ndarray:
        """Deserialize raw binary bytes from SQLite BLOB to a float32 NumPy vector."""
        if not blob:
            return np.zeros(dimension, dtype=np.float32)
        arr = np.frombuffer(blob, dtype=np.float32)
        if len(arr) != dimension:
            logger.warning("Deserialized vector has length %d, expected %d", len(arr), dimension)
            padded = np.zeros(dimension, dtype=np.float32)
            padded[: min(len(arr), dimension)] = arr[:dimension]
            return padded
        return arr

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors. Assumes unit-normalized vectors."""
        dot = float(np.dot(a, b))
        # Clamp to [-1.0, 1.0] to prevent floating point rounding drift
        return max(-1.0, min(1.0, dot))
