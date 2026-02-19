"""
Splits DocSection objects into overlapping text chunks ready for embedding.

Chunking strategy
─────────────────
* Preferred split boundaries (in order): paragraph break → sentence end → word.
* Images from a section are attached only to the **first** chunk of that section
  so they are returned when the section heading matches the query.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from kb_loader import DocSection

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A text fragment with all metadata needed for retrieval and citation."""

    chunk_id: str          # deterministic MD5-based identifier
    heading: str           # section heading (for citation)
    heading_level: int
    text: str              # actual chunk content
    images: list[str] = field(default_factory=list)
    section_index: int = 0
    chunk_index: int = 0   # position within the section's chunks

    @property
    def source_label(self) -> str:
        """Human-readable citation string shown to users."""
        return f"[{self.chunk_id[:8]}] Раздел: «{self.heading}»"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

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

        text_chunks = _split_text(section.text, chunk_size, overlap)
        for chunk_idx, text in enumerate(text_chunks):
            chunk_id = _make_id(section.heading, sec_idx, chunk_idx)
            # Images are attached only to the first chunk of the section.
            images = section.images if chunk_idx == 0 else []
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    heading=section.heading,
                    heading_level=section.heading_level,
                    text=text,
                    images=images,
                    section_index=sec_idx,
                    chunk_index=chunk_idx,
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


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

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

        # Next window starts *overlap* characters before the split point.
        start = max(split_at - overlap, start + 1)  # +1 guarantees progress

    return chunks


def _best_split(text: str, start: int, end: int) -> int:
    """
    Find the best split position at or before *end*.

    Preference order: blank line > single newline > sentence end > word boundary.
    """
    # Double newline (paragraph break)
    pos = text.rfind("\n\n", start, end)
    if pos > start + 80:
        return pos + 2

    # Single newline
    pos = text.rfind("\n", start, end)
    if pos > start + 80:
        return pos + 1

    # Sentence-ending punctuation followed by space or newline
    for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        pos = text.rfind(sep, start, end)
        if pos > start + 40:
            return pos + len(sep)

    # Word boundary
    pos = text.rfind(" ", start, end)
    if pos > start:
        return pos + 1

    return end


def _make_id(heading: str, sec_idx: int, chunk_idx: int) -> str:
    raw = f"{heading}|{sec_idx}|{chunk_idx}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()
