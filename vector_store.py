"""
FAISS-backed vector store.

Index type: IndexFlatIP (inner product) on L2-normalised vectors
→ equivalent to cosine similarity; scores range from −1 to +1.

Persistence layout (./storage/ by default):
    index.faiss   – FAISS binary index
    chunks.pkl    – list[Chunk] in the same order as index vectors
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
from openai import OpenAI

from chunker import Chunk

logger = logging.getLogger(__name__)

_INDEX_FILE = "index.faiss"
_CHUNKS_FILE = "chunks.pkl"
_EMBED_BATCH = 100   # OpenAI embeddings API batch size limit


class VectorStore:

    def __init__(
        self,
        storage_dir: str,
        embedding_model: str,
        openai_client: OpenAI,
    ) -> None:
        self._dir = Path(storage_dir)
        self._model = embedding_model
        self._client = openai_client

        self._index: Optional[faiss.Index] = None
        self._chunks: list[Chunk] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Build / rebuild
    # ─────────────────────────────────────────────────────────────────────────

    def build(self, chunks: list[Chunk]) -> None:
        """
        Embed *chunks*, build a new FAISS index, and persist to disk.

        This fully replaces any previously loaded index.
        """
        if not chunks:
            raise ValueError("Cannot build vector store from an empty chunk list.")

        logger.info("Embedding %d chunks with model '%s'…", len(chunks), self._model)
        texts = [c.text for c in chunks]
        embeddings = self._embed_batch(texts)

        matrix = np.array(embeddings, dtype=np.float32)
        faiss.normalize_L2(matrix)

        dim = matrix.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(matrix)

        self._index = index
        self._chunks = chunks

        self._save()
        logger.info(
            "Vector store built: %d vectors, dim=%d, saved to '%s'",
            len(chunks),
            dim,
            self._dir,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Search
    # ─────────────────────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 6) -> list[tuple[Chunk, float]]:
        """
        Return up to *k* (chunk, cosine_score) pairs ranked by relevance.

        Raises RuntimeError if the store has not been loaded or built yet.
        """
        if not self.is_ready:
            raise RuntimeError(
                "Vector store is not initialised. Call build() or load() first."
            )

        query_vec = np.array(
            [self._embed_single(query)], dtype=np.float32
        )
        faiss.normalize_L2(query_vec)

        k_clamped = min(k, len(self._chunks))
        scores, indices = self._index.search(query_vec, k_clamped)

        results: list[tuple[Chunk, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append((self._chunks[int(idx)], float(score)))

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    def load(self) -> bool:
        """
        Try to load a previously saved index from disk.

        Returns True on success, False if files are missing.
        Logs a warning and returns False on read errors.
        """
        index_path = self._dir / _INDEX_FILE
        chunks_path = self._dir / _CHUNKS_FILE

        if not index_path.exists() or not chunks_path.exists():
            logger.info("No saved index found at '%s'. Will build from scratch.", self._dir)
            return False

        try:
            self._index = faiss.read_index(str(index_path))
            with open(chunks_path, "rb") as fh:
                self._chunks = pickle.load(fh)
            logger.info(
                "Loaded vector store from '%s': %d chunks.", self._dir, len(self._chunks)
            )
            return True
        except Exception as exc:
            logger.warning("Failed to load saved index: %s. Will rebuild.", exc)
            return False

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._dir / _INDEX_FILE))
        with open(self._dir / _CHUNKS_FILE, "wb") as fh:
            pickle.dump(self._chunks, fh)
        logger.debug("Vector store persisted to '%s'.", self._dir)

    # ─────────────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._index is not None and len(self._chunks) > 0

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    # ─────────────────────────────────────────────────────────────────────────
    # OpenAI embedding helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _embed_single(self, text: str) -> list[float]:
        response = self._client.embeddings.create(model=self._model, input=text)
        return response.data[0].embedding

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* in batches, respecting the API's per-request limit."""
        all_embeddings: list[list[float]] = []

        for batch_start in range(0, len(texts), _EMBED_BATCH):
            batch = texts[batch_start: batch_start + _EMBED_BATCH]
            batch_num = batch_start // _EMBED_BATCH + 1
            total_batches = (len(texts) - 1) // _EMBED_BATCH + 1
            logger.debug("Embedding batch %d/%d…", batch_num, total_batches)

            response = self._client.embeddings.create(model=self._model, input=batch)
            # Sort by index to guarantee order matches input.
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_embeddings.extend(d.embedding for d in sorted_data)

        return all_embeddings
