"""
FAISS-backed vector store.

Index type: IndexFlatIP (inner product) on L2-normalised vectors
-> equivalent to cosine similarity; scores range from -1 to +1.

Persistence layout (./storage/ by default):
    index.faiss   - FAISS binary index
    chunks.pkl    - list[Chunk] in the same order as index vectors
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
from openai import OpenAI

from rag.chunker import Chunk

logger = logging.getLogger(__name__)

_INDEX_FILE = "index.faiss"
_CHUNKS_FILE = "chunks.pkl"
_EMBED_BATCH = 100


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

    # ------------------------------------------------------------------
    # Build / rebuild
    # ------------------------------------------------------------------

    def build(self, chunks: list[Chunk]) -> None:
        """
        Embed *chunks*, build a new FAISS index, and persist to disk.

        This fully replaces any previously loaded index.
        """
        if not chunks:
            raise ValueError("Cannot build vector store from an empty chunk list.")

        logger.info("Embedding %d chunks with model '%s'...", len(chunks), self._model)
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

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        k: int = 6,
        min_semantic_score: float = 0.0,
        max_per_source: int = 2,
    ) -> list[tuple[Chunk, float]]:
        """
        Return up to *k* (chunk, cosine_score) pairs ranked by relevance.

        Uses hybrid scoring: semantic similarity + keyword overlap boost.
        Retrieves extra candidates from FAISS and re-ranks with keyword bonus.

        *min_semantic_score* gates the keyword bonus: chunks below this
        pure cosine threshold get no keyword boost, preventing off-topic
        queries from passing the answerer's min_score via keyword matches alone.

        *max_per_source* limits how many chunks from the same source_file
        can appear in the final results, ensuring source diversity.
        """
        if not self.is_ready:
            raise RuntimeError(
                "Vector store is not initialised. Call build() or load() first."
            )

        query_vec = np.array(
            [self._embed_single(query)], dtype=np.float32
        )
        faiss.normalize_L2(query_vec)

        # Search the full index for diversity filtering.
        # IndexFlatIP is brute-force, so searching all chunks has
        # negligible extra cost — but guarantees small files aren't buried
        # by large sources that dominate the index.
        candidates_k = len(self._chunks)
        scores, indices = self._index.search(query_vec, candidates_k)

        # Extract query keywords (3+ chars, lowercased)
        query_words = set(
            w for w in query.lower().split() if len(w) >= 3
        )

        scored: list[tuple[Chunk, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            chunk = self._chunks[int(idx)]
            semantic_score = float(score)

            # Keyword bonus only for semantically relevant chunks
            if semantic_score >= min_semantic_score and query_words:
                text_lower = chunk.text.lower()
                keyword_hits = sum(1 for w in query_words if w in text_lower)
                bonus = keyword_hits * 0.05
            else:
                bonus = 0.0

            scored.append((chunk, semantic_score + bonus))

        # Re-sort by hybrid score
        scored.sort(key=lambda x: x[1], reverse=True)

        # Source diversity: limit chunks per source_file.
        # Normalize source names so near-duplicate files (e.g. "welcome
        # lessons export" vs "welcome lessons export fixed rowheights")
        # share the same diversity budget.
        results: list[tuple[Chunk, float]] = []
        source_counts: dict[str, int] = {}
        for chunk, score in scored:
            key = _normalize_source(chunk.source_file)
            cnt = source_counts.get(key, 0)
            if cnt >= max_per_source:
                continue
            source_counts[key] = cnt + 1
            results.append((chunk, score))
            if len(results) >= k:
                break

        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """
        Try to load a previously saved index from disk.

        Returns True on success, False if files are missing.
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

    def extend(self, chunks: list[Chunk]) -> None:
        """Embed *chunks* and append them to the existing index without a full rebuild."""
        if not self.is_ready:
            raise RuntimeError("Vector store must be built before extending.")
        if not chunks:
            return

        texts = [c.text for c in chunks]
        embeddings = self._embed_batch(texts)

        matrix = np.array(embeddings, dtype=np.float32)
        faiss.normalize_L2(matrix)

        self._index.add(matrix)
        self._chunks.extend(chunks)
        self._save()
        logger.info(
            "Extended vector store with %d chunks. Total: %d",
            len(chunks), len(self._chunks),
        )

    def _save(self) -> None:
        """Atomically persist index and chunks using temp files + rename."""
        self._dir.mkdir(parents=True, exist_ok=True)
        index_tmp = self._dir / (_INDEX_FILE + ".tmp")
        chunks_tmp = self._dir / (_CHUNKS_FILE + ".tmp")

        faiss.write_index(self._index, str(index_tmp))
        with open(chunks_tmp, "wb") as fh:
            pickle.dump(self._chunks, fh)

        index_tmp.rename(self._dir / _INDEX_FILE)
        chunks_tmp.rename(self._dir / _CHUNKS_FILE)
        logger.debug("Vector store persisted to '%s'.", self._dir)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._index is not None and len(self._chunks) > 0

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    # ------------------------------------------------------------------
    # OpenAI embedding helpers
    # ------------------------------------------------------------------

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
            logger.debug("Embedding batch %d/%d...", batch_num, total_batches)

            response = self._client.embeddings.create(model=self._model, input=batch)
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_embeddings.extend(d.embedding for d in sorted_data)

        return all_embeddings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import re as _re

_STRIP_SUFFIXES = _re.compile(
    r"\s*(lessons export|fixed rowheights|compressed|szhatyy).*$",
    _re.IGNORECASE,
)


def _normalize_source(source_file: str) -> str:
    """Collapse near-duplicate file names into a single diversity key.

    Examples:
        "welcome lessons export"                    → "welcome"
        "welcome lessons export fixed rowheights"   → "welcome"
        "baristika lessons export"                  → "baristika"
        "Karta Napitkov Uppetit"                    → "karta napitkov uppetit"
    """
    key = _STRIP_SUFFIXES.sub("", source_file).strip().lower()
    return key or source_file.lower()
