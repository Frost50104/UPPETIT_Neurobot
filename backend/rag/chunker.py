"""
Splits DocSection objects into overlapping text chunks ready for embedding.

Chunking strategy
-----------------
* Preferred split boundaries (in order): paragraph break -> sentence end -> word.
* Images from a section are attached to **all** chunks of that section
  so they are returned regardless of which chunk matches the query.
* Each chunk text is prepended with document/section context for better embeddings.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from rag.kb_loader import DocSection

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A text fragment with all metadata needed for retrieval and citation."""

    chunk_id: str          # deterministic MD5-based identifier
    heading: str           # section heading (for citation)
    heading_level: int
    text: str              # actual chunk content (with context prefix)
    images: list[str] = field(default_factory=list)
    section_index: int = 0
    chunk_index: int = 0   # position within the section's chunks
    source_file: str = ""  # cleaned filename

    @property
    def source_label(self) -> str:
        """Human-readable citation string shown to users."""
        if self.source_file and self.source_file != self.heading:
            return f"[{self.chunk_id[:8]}] {self.source_file} \u2192 \u00ab{self.heading}\u00bb"
        return f"[{self.chunk_id[:8]}] \u00ab{self.heading}\u00bb"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_sections(
    sections: list[DocSection],
    chunk_size: int = 800,
    overlap: int = 150,
) -> list[Chunk]:
    """
    Convert *sections* into overlapping chunks.

    Returns an empty list (without raising) if *sections* is empty.
    """
    chunks: list[Chunk] = []
    for sec_idx, section in enumerate(sections):
        if not section.text.strip():
            continue

        # Build context prefix for embedding quality
        context_prefix = _build_context_prefix(section)

        text_chunks = _split_text(section.text, chunk_size, overlap)

        # Map images to chunks: use "Изображение" markers if available,
        # otherwise distribute proportionally
        chunk_images_map = _distribute_images(
            section.text, section.images, text_chunks
        )

        for chunk_idx, text in enumerate(text_chunks):
            chunk_id = _make_id(section.heading, sec_idx, chunk_idx)
            images = chunk_images_map[chunk_idx]

            # Prepend context to chunk text so embeddings capture the topic
            full_text = context_prefix + text

            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    heading=section.heading,
                    heading_level=section.heading_level,
                    text=full_text,
                    images=images,
                    section_index=sec_idx,
                    chunk_index=chunk_idx,
                    source_file=section.source_file,
                )
            )

    logger.info(
        "Produced %d chunks from %d sections (chunk_size=%d, overlap=%d)",
        len(chunks),
        len(sections),
        chunk_size,
        overlap,
    )
    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _distribute_images(
    section_text: str,
    section_images: list[str],
    chunk_texts: list[str],
) -> list[list[str]]:
    """
    Distribute images across chunks using "Изображение" markers in text.

    XLSX exports contain literal "Изображение" where each image was.
    If marker count matches image count, map each image to the chunk
    containing its marker. Otherwise distribute proportionally.
    """
    n_chunks = len(chunk_texts)
    if not section_images:
        return [[] for _ in range(n_chunks)]
    if n_chunks <= 1:
        return [list(section_images)]

    n_imgs = len(section_images)

    # Find "Изображение" marker positions in original text
    marker = "Изображение"
    marker_positions: list[int] = []
    start = 0
    while True:
        pos = section_text.find(marker, start)
        if pos == -1:
            break
        marker_positions.append(pos)
        start = pos + len(marker)

    # Find approximate start position of each chunk in the original text
    chunk_starts: list[int] = []
    search_from = 0
    for ct in chunk_texts:
        snippet = ct.strip()[:60]
        pos = section_text.find(snippet, search_from)
        if pos == -1:
            pos = search_from
        chunk_starts.append(pos)
        search_from = max(search_from, pos + 1)
    chunk_starts.append(len(section_text))  # sentinel

    result: list[list[str]] = [[] for _ in range(n_chunks)]

    if len(marker_positions) == n_imgs:
        # Precise mapping: each marker → its chunk
        for img_idx, mpos in enumerate(marker_positions):
            for ci in range(n_chunks):
                if chunk_starts[ci] <= mpos < chunk_starts[ci + 1]:
                    result[ci].append(section_images[img_idx])
                    break
    else:
        # Proportional fallback
        per_chunk = n_imgs / n_chunks
        for ci in range(n_chunks):
            s = int(ci * per_chunk)
            e = int((ci + 1) * per_chunk)
            result[ci] = section_images[s:e]

    return result


def _build_context_prefix(section: DocSection) -> str:
    """Build a short prefix with file/section context for better embeddings."""
    parts: list[str] = []
    if section.source_file:
        parts.append(f"Документ: \u00ab{section.source_file}\u00bb")
    if section.heading and section.heading != section.source_file:
        parts.append(f"Раздел: \u00ab{section.heading}\u00bb")
    if parts:
        return "\n".join(parts) + "\n\n"
    return ""


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Return a list of overlapping sub-strings of *text*."""
    if len(text) <= chunk_size:
        return [text.strip()]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        split_at = _best_split(text, start, end)
        chunk = text[start:split_at].strip()
        if chunk:
            chunks.append(chunk)

        start = max(split_at - overlap, start + 1)

    return chunks


def _best_split(text: str, start: int, end: int) -> int:
    """
    Find the best split position at or before *end*.

    Preference order: blank line > single newline > sentence end > word boundary.
    """
    pos = text.rfind("\n\n", start, end)
    if pos > start + 80:
        return pos + 2

    pos = text.rfind("\n", start, end)
    if pos > start + 80:
        return pos + 1

    for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        pos = text.rfind(sep, start, end)
        if pos > start + 40:
            return pos + len(sep)

    pos = text.rfind(" ", start, end)
    if pos > start:
        return pos + 1

    return end


def _make_id(heading: str, sec_idx: int, chunk_idx: int) -> str:
    raw = f"{heading}|{sec_idx}|{chunk_idx}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()
