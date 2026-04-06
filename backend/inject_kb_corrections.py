#!/usr/bin/env python3
"""
One-time script: inject correction chunks into the existing vector store.

These corrections fix factual errors discovered via the attestation benchmark.
After running, the corrections become part of the current KB.

NOTE: corrections will be lost on next KB rebuild from Google Drive.
Add 'KB_corrections.docx' to the GDrive folder for persistence.

Usage:
    cd /opt/neurobot/backend
    .venv/bin/python3 inject_kb_corrections.py
"""
from __future__ import annotations

import hashlib
import logging
import pickle
import sys
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI

# Ensure project root on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND_DIR))

from config import get_settings
from rag.chunker import Chunk

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Correction entries — factual fixes per attestation benchmark
# ---------------------------------------------------------------------------

CORRECTIONS = [
    {
        "heading": "Рецепт Рафа — стандарт UPPETIT",
        "source_file": "KB_corrections",
        "text": (
            "Документ: «KB_corrections»\n"
            "Раздел: «Рецепт Рафа — стандарт UPPETIT»\n"
            "---\n"
            "СТАНДАРТНЫЙ РЕЦЕПТ РАФА UPPETIT\n\n"
            "Раф 0,3 (300 мл):\n"
            "- Эспрессо: 1 шот\n"
            "- Молоко 3,2%: 140 гр.\n"
            "- Сливки 10%: 140 гр.\n"
            "- Сироп: по желанию гостя (3 нажатия помпы)\n\n"
            "Раф 0,4 (400 мл):\n"
            "- Эспрессо: 2 шота\n"
            "- Молоко 3,2%: 140 гр.\n"
            "- Сливки 10%: 140 гр.\n"
            "- Сироп: по желанию гостя (4 нажатия помпы)\n\n"
            "Технология: в питчер налить молоко, сливки, добавить эспрессо "
            "(по желанию гостя добавить сироп). Вспенить. "
            "Перелить получившийся напиток в стакан.\n"
            "Раф не рекомендуется готовить на альтернативном молоке, "
            "но по просьбе гостя можем заменить."
        ),
    },
    {
        "heading": "Ротация ассортимента на полках",
        "source_file": "KB_corrections",
        "text": (
            "Документ: «KB_corrections»\n"
            "Раздел: «Ротация ассортимента на полках»\n"
            "---\n"
            "РОТАЦИЯ АССОРТИМЕНТА НА ПОЛКАХ\n\n"
            "Ротация блюд на полках (смена ассортимента) происходит раз в неделю.\n\n"
            "Важно не путать два понятия:\n"
            "1. Ротация ассортимента — смена позиций блюд на полках, "
            "происходит раз в неделю.\n"
            "2. Ротация по сроку годности (FIFO) — ежедневная перестановка товаров "
            "так, чтобы товар с меньшим сроком стоял впереди. "
            "Проверяется ежедневно, особенно утром перед выкладкой и после потока гостей."
        ),
    },
    {
        "heading": "Стоп-лист — правила заполнения",
        "source_file": "KB_corrections",
        "text": (
            "Документ: «KB_corrections»\n"
            "Раздел: «Стоп-лист — правила заполнения»\n"
            "---\n"
            "ПРАВИЛА ЗАПОЛНЕНИЯ СТОП-ЛИСТА\n\n"
            "Стоп-лист необходимо заполнять ежедневно, сразу после поставки, "
            "и редактировать в течение дня.\n\n"
            "Необходимо ли вносить продукт в стоп-лист, если на полке "
            "осталось 2 позиции? Да, необходимо.\n\n"
            "Правило: если на полке осталось 2 или менее позиций товара, "
            "его нужно внести в стоп-лист с указанием фактического остатка. "
            "Это позволяет системе корректно отображать наличие товара "
            "для заказов через Яндекс.Еду и UPPETIT."
        ),
    },
    {
        "heading": "Списание продукции Онигири — статья Брак Мистер Че",
        "source_file": "KB_corrections",
        "text": (
            "Документ: «KB_corrections»\n"
            "Раздел: «Списание продукции Онигири»\n"
            "---\n"
            "СПИСАНИЕ БРАКОВАННОЙ ПРОДУКЦИИ ОНИГИРИ\n\n"
            "Бракованную продукцию Онигири необходимо списывать на статью "
            "«Брак Мистер Че».\n\n"
            "Онигири поставляет компания «Мистер Че», поэтому списание "
            "бракованной продукции онигири идёт на статью «Брак Мистер Че», "
            "а НЕ на «Брак Честная еда» и НЕ на «Брак производства».\n\n"
            "Статья «Брак Честная еда» предназначена для бракованных роллов "
            "и моти от поставщика «Честная еда».\n"
            "Статья «Брак Мистер Че» предназначена для бракованных онигири "
            "от поставщика «Мистер Че»."
        ),
    },
    {
        "heading": "Наше зерно — стандарт UPPETIT",
        "source_file": "KB_corrections",
        "text": (
            "Документ: «KB_corrections»\n"
            "Раздел: «Наше зерно — стандарт UPPETIT»\n"
            "---\n"
            "ЗЕРНО UPPETIT — СТАНДАРТ КОМПАНИИ\n\n"
            "В UPPETIT мы используем:\n"
            "- 100% Арабика (моносорт)\n"
            "- Страна: Бразилия\n"
            "- Регион: Серрадо\n"
            "- Обработка: натуральная\n"
            "- Обжарка: средняя\n"
            "- Вкусовой профиль: шоколад и жареные орехи\n\n"
            "Мы НЕ используем робусту. В UPPETIT применяется исключительно "
            "100% арабика из Бразилии.\n\n"
            "Примечание: в обучающих материалах о кофе упоминается робуста "
            "в образовательных целях (для понимания разницы между сортами), "
            "но в наших точках используется только арабика."
        ),
    },
]


def make_chunk_id(heading: str, idx: int) -> str:
    raw = f"correction_{heading}_{idx}"
    return hashlib.md5(raw.encode()).hexdigest()


def apply_corrections(vector_store) -> int:
    """Embed and append all correction chunks to an existing VectorStore.

    Called automatically after every KB rebuild so corrections always survive.
    Returns the number of correction chunks added.
    """
    new_chunks = [
        Chunk(
            chunk_id=make_chunk_id(entry["heading"], i),
            text=entry["text"],
            heading=entry["heading"],
            heading_level=1,
            source_file=entry["source_file"],
            images=[],
            image_captions=[],
        )
        for i, entry in enumerate(CORRECTIONS)
    ]
    vector_store.extend(new_chunks)
    logger.info("Applied %d KB correction chunks.", len(new_chunks))
    return len(new_chunks)


def main():
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    storage_dir = Path(settings.storage_dir)
    index_path = storage_dir / "index.faiss"
    chunks_path = storage_dir / "chunks.pkl"

    if not index_path.exists() or not chunks_path.exists():
        logger.error("Vector store not found at %s", storage_dir)
        sys.exit(1)

    # Load existing
    index = faiss.read_index(str(index_path))
    with open(chunks_path, "rb") as f:
        chunks: list[Chunk] = pickle.load(f)

    logger.info("Loaded existing store: %d chunks, dim=%d", len(chunks), index.d)

    # Remove previous corrections (idempotent)
    old_count = len(chunks)
    correction_mask = [c.source_file != "KB_corrections" for c in chunks]
    if not all(correction_mask):
        # Need to rebuild index without old corrections
        kept_indices = [i for i, keep in enumerate(correction_mask) if keep]
        chunks = [chunks[i] for i in kept_indices]

        # Extract vectors for kept chunks and rebuild index
        all_vecs = np.zeros((index.ntotal, index.d), dtype=np.float32)
        for i in range(index.ntotal):
            all_vecs[i] = faiss.rev_swig_ptr(
                index.get_xb().data() if hasattr(index, 'get_xb') else None, index.d
            )

        # Simpler: just reconstruct from index
        kept_vecs = np.zeros((len(kept_indices), index.d), dtype=np.float32)
        for new_i, old_i in enumerate(kept_indices):
            kept_vecs[new_i] = index.reconstruct(old_i)

        index = faiss.IndexFlatIP(index.d)
        index.add(kept_vecs)
        logger.info("Removed %d old correction chunks", old_count - len(chunks))

    # Create new correction chunks
    new_chunks: list[Chunk] = []
    for i, entry in enumerate(CORRECTIONS):
        chunk = Chunk(
            chunk_id=make_chunk_id(entry["heading"], i),
            text=entry["text"],
            heading=entry["heading"],
            heading_level=1,
            source_file=entry["source_file"],
            images=[],
        )
        new_chunks.append(chunk)

    logger.info("Embedding %d correction chunks...", len(new_chunks))

    # Embed corrections
    texts = [c.text for c in new_chunks]
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    sorted_data = sorted(response.data, key=lambda d: d.index)
    new_vecs = np.array(
        [d.embedding for d in sorted_data], dtype=np.float32
    )
    faiss.normalize_L2(new_vecs)

    # Add to index
    index.add(new_vecs)
    chunks.extend(new_chunks)

    # Save
    faiss.write_index(index, str(index_path))
    with open(chunks_path, "wb") as f:
        pickle.dump(chunks, f)

    logger.info(
        "Done. Total chunks: %d (added %d corrections). Saved to %s",
        len(chunks), len(new_chunks), storage_dir,
    )
    logger.info("Restart the backend to pick up the new index.")


if __name__ == "__main__":
    main()
