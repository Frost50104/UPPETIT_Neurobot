"""
Hybrid image captioning for KB images.

Two-phase approach:
  Phase 1 (text context): For XLSX sections with "Изображение" markers,
    extract the text between consecutive markers as the caption.  This gives
    names, titles, and descriptions that a vision model cannot know.
  Phase 2 (vision API fallback): For images without text-based captions
    (PDFs, DOCXs, or failed marker matching), use GPT-4o-mini vision.

Cost: vision phase ~$0.03 per rebuild (~700 images, detail=low).
"""
from __future__ import annotations

import base64
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import OpenAI

from rag.kb_loader import DocSection

logger = logging.getLogger(__name__)

_CAPTION_PROMPT = (
    "Кратко опиши изображение (1 предложение на русском). "
    "Если видишь имя, подпись или текст — обязательно укажи дословно."
)

_MIME_MAP = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


# ---------------------------------------------------------------------------
# Phase 1: text-based captions from "Изображение" markers
# ---------------------------------------------------------------------------

def _extract_text_captions(section: DocSection) -> dict[str, str]:
    """Extract captions from text surrounding "Изображение" markers.

    XLSX team lists have a pattern like:
        ... Изображение
        Текст | Александр Попов, руководитель ... Изображение
        Текст | Андрей Величко, менеджер ... Изображение

    The text AFTER each "Изображение" marker (up to the next marker)
    describes who/what is in that image.

    Returns {image_path: caption} for images that got a text caption.
    """
    text = section.text
    marker = "Изображение"

    # Find all marker positions
    positions: list[int] = []
    start = 0
    while True:
        pos = text.find(marker, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + len(marker)

    if not positions or len(positions) != len(section.images):
        return {}

    captions: dict[str, str] = {}

    for i, (mpos, img_path) in enumerate(zip(positions, section.images)):
        # Text region: from current marker end to next marker (or section end)
        region_start = mpos + len(marker)
        if i + 1 < len(positions):
            region_end = positions[i + 1]
        else:
            region_end = len(text)

        raw = text[region_start:region_end].strip()

        # Clean up: remove leading/trailing pipes, whitespace
        raw = raw.strip("| \t\n")
        # Collapse whitespace
        raw = re.sub(r"\s+", " ", raw).strip()

        if raw and len(raw) >= 5:
            # Truncate to ~200 chars — person name/title is always at the start;
            # long tails mention other people and cause false keyword matches.
            captions[img_path] = raw[:200]

    if captions:
        logger.info(
            "Extracted %d/%d text-based captions for section '%s'",
            len(captions), len(section.images), section.heading[:50],
        )

    return captions


# ---------------------------------------------------------------------------
# Phase 2: vision API fallback
# ---------------------------------------------------------------------------

def _caption_single_vision(img_path: str, client: OpenAI, model: str) -> str:
    """Return a short caption for one image via vision API, or "" on failure."""
    if not os.path.isfile(img_path):
        return ""
    try:
        with open(img_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()

        ext = img_path.rsplit(".", 1)[-1].lower()
        mime = _MIME_MAP.get(ext, "image/png")

        response = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _CAPTION_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{img_data}",
                        "detail": "low",
                    }},
                ],
            }],
            max_tokens=100,
            temperature=0,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.debug("Vision caption failed for %s: %s", os.path.basename(img_path), exc)
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def caption_all_images(
    sections: list[DocSection],
    openai_client: OpenAI,
    model: str = "gpt-4o-mini",
    max_workers: int = 3,
) -> int:
    """Generate captions for every image across *sections*.  Modifies in place.

    Phase 1: extract text-based captions from "Изображение" markers (free, instant).
    Phase 2: vision API for remaining uncaptioned images (paid, parallel).

    Returns the number of images successfully captioned.
    """
    # --- Phase 1: text-based captions ---
    text_captions: dict[str, str] = {}
    for section in sections:
        if section.images:
            extracted = _extract_text_captions(section)
            text_captions.update(extracted)

    if text_captions:
        logger.info("Phase 1: %d images captioned from text context.", len(text_captions))

    # --- Collect all unique image paths ---
    unique_paths: list[str] = []
    seen: set[str] = set()
    for section in sections:
        for img_path in section.images:
            if img_path not in seen:
                seen.add(img_path)
                unique_paths.append(img_path)

    if not unique_paths:
        return 0

    # --- Phase 2: vision API for uncaptioned images ---
    needs_vision = [p for p in unique_paths if p not in text_captions]

    vision_captions: dict[str, str] = {}
    if needs_vision:
        logger.info(
            "Phase 2: captioning %d/%d images via vision API...",
            len(needs_vision), len(unique_paths),
        )

        def _do_one(path: str) -> tuple[str, str]:
            return path, _caption_single_vision(path, openai_client, model)

        done = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_do_one, p): p for p in needs_vision}
            for future in as_completed(futures):
                path, caption = future.result()
                vision_captions[path] = caption
                done += 1
                if done % 50 == 0 or done == len(needs_vision):
                    logger.info("  Captioned %d/%d via vision...", done, len(needs_vision))

    # --- Merge: text captions take priority ---
    all_captions: dict[str, str] = {}
    for p in unique_paths:
        all_captions[p] = text_captions.get(p) or vision_captions.get(p, "")

    # --- Write captions back to sections (paired 1:1 with images) ---
    for section in sections:
        section.image_captions = [all_captions.get(p, "") for p in section.images]

    captioned = sum(1 for c in all_captions.values() if c)
    logger.info(
        "Captioning complete: %d/%d images captioned (%d text, %d vision).",
        captioned, len(unique_paths), len(text_captions),
        sum(1 for c in vision_captions.values() if c),
    )
    return captioned
