"""
RAG pipeline: vector search -> context assembly -> ChatGPT -> structured answer.

Anti-hallucination guarantees
-----------------------------
* temperature=0.05 - near-deterministic sampling.
* System prompt explicitly forbids the model from using external knowledge.
* Only retrieved chunks are passed as context; no document summary or history.
* If retrieved chunks score below MIN_SCORE the query is returned unanswered.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field

from openai import OpenAI

from rag.chunker import Chunk
from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt (strict no-hallucination contract)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Ты — корпоративный ассистент компании UPPETIT.
Ты отвечаешь на основе предоставленного КОНТЕКСТА из базы знаний компании.

=== ПРАВИЛА ===

1. Используй информацию из блока [КОНТЕКСТ] как основной источник.
   Синтезируй ответ из всех предоставленных фрагментов, даже если они частично релевантны.

2. НАЧИНАЙ С ГЛАВНОГО. Определи тип вопроса и структурируй ответ:
   - О человеке/сотруднике → первое предложение: полное имя + должность/роль в компании
   - О процедуре/процессе → начни с чёткого порядка действий
   - О рецепте/напитке → начни с точных ингредиентов и пропорций
   - О правиле/стандарте → начни с формулировки правила
   Ключевой факт должен быть в первых двух предложениях ответа.

3. ПРИОРИТЕТ ИСТОЧНИКОВ: если в контексте есть фрагменты со стандартами, рецептами
   или регламентами UPPETIT (документы «Стандарты», «ТТК», «Зерно», инструкции) —
   используй именно их. Общеобразовательные фрагменты о кофе, продуктах и т.д.
   используй только как дополнение, НЕ противоречащее стандартам компании.

4. Не придумывай факты, процедуры, контакты, цифры, имена, регламенты, даты,
   которых нет в КОНТЕКСТЕ. Если данных не хватает — так и скажи, но сначала
   дай максимум полезной информации из того, что есть.

5. Не ссылайся на интернет или общедоступные источники.

6. Если вопрос допускает несколько трактовок — кратко ответь на наиболее вероятную
   и предложи уточнить.

7. Отвечай структурированно: используй списки, абзацы, выделение где уместно.

8. Отвечай на том же языке, на котором задан вопрос.

9. В конце ответа перечисли источники:
   Источники:
   - [chunk_id] Документ → «раздел»

10. Только если контекст СОВСЕМ не содержит полезной информации по теме вопроса,
    ответь: «К сожалению, в базе знаний не нашлось информации по этому вопросу.
    Попробуйте перефразировать или обратитесь к руководителю.»
"""


# ---------------------------------------------------------------------------
# Query rewrite prompt — expand short questions for better retrieval
# ---------------------------------------------------------------------------

_QUERY_REWRITE_PROMPT = """\
Ты — помощник для поиска по корпоративной базе знаний компании UPPETIT \
(сеть кафе: еда, напитки, кофе, процедуры, сотрудники, стандарты).

Расширь вопрос пользователя: добавь синонимы и ключевые слова, \
которые могут встречаться в документах с ответом.

Правила:
- Сохрани исходный смысл
- Добавь 3-7 релевантных ключевых слов/синонимов
- Верни ТОЛЬКО расширенный запрос одной строкой, без пояснений
"""


# ---------------------------------------------------------------------------
# Stop words for image keyword gate (common Russian function words that
# match in almost any chunk and would defeat the relevance filter).
# ---------------------------------------------------------------------------
_IMAGE_STOP_WORDS = frozenset({
    "наше", "наши", "наша", "наших", "нашим", "нашей", "нашу",
    "свой", "свою", "свои", "своей", "своих", "своим",
    "этот", "этих", "этой", "этим", "этого", "этому",
    "такой", "такие", "такая", "такое", "таких", "таким",
    "какой", "какие", "какая", "какое", "каких", "каким",
    "тоже", "также", "очень", "можно", "нужно", "будет", "будем", "будут",
    "было", "были", "была", "есть", "всего", "когда", "чтобы",
    "после", "через", "перед", "между", "более", "менее",
    "только", "просто", "другой", "должен", "должна", "расскажи",
})

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class AnswerResult:
    text: str
    sources: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    image_sources: list[str] = field(default_factory=list)  # source_file per image
    found: bool = True     # False when KB has no relevant info


# ---------------------------------------------------------------------------
# Answerer
# ---------------------------------------------------------------------------

class RAGAnswerer:

    def __init__(
        self,
        vector_store: VectorStore,
        openai_client: OpenAI,
        chat_model: str,
        top_k: int,
        max_tokens: int,
        min_score: float = 0.25,
        min_semantic_score: float = 0.25,
        query_rewrite: bool = True,
    ) -> None:
        self._store = vector_store
        self._client = openai_client
        self._model = chat_model
        self._top_k = top_k
        self._max_tokens = max_tokens
        self._min_score = min_score
        self._min_semantic_score = min_semantic_score
        self._query_rewrite = query_rewrite

    # ------------------------------------------------------------------

    def _rewrite_query(self, question: str) -> str:
        """Expand user question with keywords for better FAISS retrieval."""
        try:
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _QUERY_REWRITE_PROMPT},
                    {"role": "user", "content": question},
                ],
                max_tokens=150,
                temperature=0,
            )
            expanded = (response.choices[0].message.content or "").strip()
            if expanded:
                logger.debug("Query rewrite: %r -> %r", question[:60], expanded[:80])
                return expanded
        except Exception as exc:
            logger.warning("Query rewrite failed, using original: %s", exc)
        return question

    # ------------------------------------------------------------------

    def answer(self, question: str) -> AnswerResult:
        """
        Retrieve relevant chunks, build a context pack, call ChatGPT.

        This is a **synchronous** method; call it inside asyncio.to_thread()
        from async handlers.
        """
        if not self._store.is_ready:
            return AnswerResult(
                text=(
                    "База знаний ещё не загружена.\n"
                    "Администратор может обновить базу знаний в панели управления."
                ),
                found=False,
            )

        # 1. Query rewrite for better retrieval (original question used for LLM)
        search_query = self._rewrite_query(question) if self._query_rewrite else question

        # 2. Semantic search
        results = self._store.search(
            search_query, k=self._top_k, min_semantic_score=self._min_semantic_score,
        )
        relevant = [(chunk, score) for chunk, score in results if score >= self._min_score]

        logger.debug(
            "Query: %r  ->  %d/%d chunks above threshold %.2f",
            question[:80],
            len(relevant),
            len(results),
            self._min_score,
        )

        if not relevant:
            return AnswerResult(
                text=(
                    "В базе знаний не найдено информации, релевантной вашему вопросу.\n\n"
                    "Попробуйте:\n"
                    "- Перефразировать вопрос\n"
                    "- Уточнить детали\n"
                    "- Использовать другие ключевые слова"
                ),
                found=False,
            )

        # 2. Assemble context
        context_text = self._build_context(relevant)
        user_message = f"Вопрос: {question}\n\n[КОНТЕКСТ]\n{context_text}"

        # 3. Call ChatGPT
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=self._max_tokens,
            temperature=0.05,
        )
        answer_text = (response.choices[0].message.content or "").strip()

        # 3b. Detect LLM-generated "not found" response.
        #     The system prompt instructs the model to say this when context
        #     is irrelevant. If detected, treat as "not found" — no images/sources.
        _NOT_FOUND_MARKERS = (
            "не нашлось информации",
            "не найдено информации",
            "нет информации по этому вопросу",
            "не содержит информации по данному вопросу",
        )
        if any(marker in answer_text.lower() for marker in _NOT_FOUND_MARKERS):
            return AnswerResult(text=answer_text, found=False)

        # 4. Collect images via caption-based matching.
        #    Two passes:
        #    Pass A: images from retrieved chunks (score gate + caption match)
        #    Pass B: images from sibling chunks (same source files) matched
        #            purely by caption keywords — catches photos in chunks
        #            that scored too low for retrieval.
        query_kws = set()
        for w in question.lower().split():
            w = w.strip("?!.,;:«»\"'()[]")
            if len(w) >= 4 and w not in _IMAGE_STOP_WORDS:
                query_kws.add(w)

        images: list[str] = []
        image_sources: list[str] = []
        seen_paths: set[str] = set()
        seen_hashes: set[str] = set()

        def _try_add_image(img_path: str, source_file: str) -> bool:
            if img_path in seen_paths:
                return False
            seen_paths.add(img_path)
            try:
                h = _perceptual_hash(img_path)
            except Exception:
                return False
            if _is_duplicate_image(h, seen_hashes):
                return False
            seen_hashes.add(h)
            images.append(img_path)
            image_sources.append(source_file)
            return True

        # Pass A: retrieved chunks — only images with captions matching ALL keywords
        top_score = relevant[0][1] if relevant else 0
        image_score_threshold = top_score * 0.75
        for chunk, score in relevant:
            if score < image_score_threshold:
                continue
            captions = getattr(chunk, 'image_captions', None) or []
            for idx, img_path in enumerate(chunk.images):
                caption = captions[idx] if idx < len(captions) else ""
                if not caption:
                    continue
                if query_kws and not all(kw in caption.lower() for kw in query_kws):
                    continue
                _try_add_image(img_path, chunk.source_file)

        # Pass B: scan sibling chunks from same source files for
        # caption-matched images not yet found.
        if query_kws and len(images) < 5:
            retrieved_sources = {c.source_file for c, _ in relevant}
            for chunk in self._store.chunks:
                if chunk.source_file not in retrieved_sources:
                    continue
                captions = getattr(chunk, 'image_captions', None) or []
                for idx, img_path in enumerate(chunk.images):
                    caption = captions[idx] if idx < len(captions) else ""
                    if not caption:
                        continue
                    if all(kw in caption.lower() for kw in query_kws):
                        _try_add_image(img_path, chunk.source_file)

        images = images[:10]
        image_sources = image_sources[:10]

        sources = [chunk.source_label for chunk, _ in relevant]

        logger.info(
            "Answer generated. chunks_used=%d, sources=%s",
            len(relevant),
            [s[:40] for s in sources],
        )

        return AnswerResult(
            text=answer_text, sources=sources, images=images,
            image_sources=image_sources, found=True,
        )

    # ------------------------------------------------------------------

    def _build_context(self, results: list[tuple[Chunk, float]]) -> str:
        parts: list[str] = []
        for chunk, score in results:
            header = f"[chunk_id: {chunk.chunk_id[:8]}]"
            if chunk.source_file:
                header += f"\nДокумент: \u00ab{chunk.source_file}\u00bb"
            header += f"\nРаздел: \u00ab{chunk.heading}\u00bb"
            header += f"\nСхожесть: {score:.2f}"
            parts.append(f"{header}\n---\n{chunk.text}")
        return "\n\n".join(parts)


def _perceptual_hash(img_path: str) -> str:
    """Average hash (aHash): resize to 8x8 grayscale, threshold by mean.

    Returns a 64-char binary string.  Two visually similar images
    (e.g. same photo from different Excel exports) will have a small
    Hamming distance even if raw pixels differ slightly.
    """
    from PIL import Image
    with Image.open(img_path) as img:
        thumb = img.convert("L").resize((8, 8))
        pixels = list(thumb.getdata())
        avg = sum(pixels) / len(pixels)
        return "".join("1" if p >= avg else "0" for p in pixels)


_HASH_DISTANCE_THRESHOLD = 8  # max bit flips to consider "same image"


def _is_duplicate_image(new_hash: str, seen: set[str]) -> bool:
    """Check if *new_hash* is within Hamming distance of any seen hash."""
    for existing in seen:
        dist = sum(a != b for a, b in zip(new_hash, existing))
        if dist <= _HASH_DISTANCE_THRESHOLD:
            return True
    return False


