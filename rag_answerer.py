"""
RAG pipeline: vector search → context assembly → ChatGPT → structured answer.

Anti-hallucination guarantees
──────────────────────────────
* temperature=0.05 – near-deterministic sampling.
* System prompt explicitly forbids the model from using external knowledge.
* Only retrieved chunks are passed as context; no document summary or history.
* If retrieved chunks score below MIN_SCORE the query is returned unanswered.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from openai import OpenAI

from chunker import Chunk
from vector_store import VectorStore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# System prompt (strict no-hallucination contract)
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Ты — корпоративный ассистент компании UPPETIT.
Ты отвечаешь СТРОГО на основе предоставленного КОНТЕКСТА из базы знаний компании.

═══ ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА ═══

1. Используй ТОЛЬКО информацию из блока [КОНТЕКСТ].
   Не используй свои общие знания, не додумывай, не дополняй.

2. Если контекст не содержит достаточно информации для ответа — ответь строго:
   «В базе знаний нет информации для точного ответа на этот вопрос.»
   Затем укажи: «Уточните: …» или «Чтобы ответить, нужно добавить в базу знаний: …»

3. Не придумывай процедуры, контакты, цифры, имена, регламенты, даты.
   Только то, что явно указано в КОНТЕКСТЕ.

4. Не ссылайся на интернет, Wikipedia, общедоступные источники.
   Не пиши «обычно», «как правило», «в большинстве компаний» и т.п.

5. Если вопрос допускает несколько трактовок — укажи все и попроси уточнить.

6. Если в контексте есть противоречие — явно укажи на него.

7. В конце КАЖДОГО ответа обязательно перечисли источники:
   📌 Источники:
   - [xxxxxxxx] Раздел: «название»
   - …

8. Отвечай на том же языке, на котором задан вопрос.

═══ ФОРМАТ ОТВЕТА ═══

[Ответ строго по контексту]

📌 Источники:
- [chunk_id] Раздел: «…»

───
Если ответа нет:
В базе знаний нет информации для точного ответа на этот вопрос.
Уточните: [что нужно уточнить]
Чтобы ответить, нужно добавить в базу знаний: [что именно]
"""


# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AnswerResult:
    text: str
    sources: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    found: bool = True     # False when KB has no relevant info


# ─────────────────────────────────────────────────────────────────────────────
# Answerer
# ─────────────────────────────────────────────────────────────────────────────

class RAGAnswerer:

    def __init__(
        self,
        vector_store: VectorStore,
        openai_client: OpenAI,
        chat_model: str,
        top_k: int,
        max_tokens: int,
        min_score: float = 0.20,
    ) -> None:
        self._store = vector_store
        self._client = openai_client
        self._model = chat_model
        self._top_k = top_k
        self._max_tokens = max_tokens
        self._min_score = min_score

    # ─────────────────────────────────────────────────────────────────────────

    def answer(self, question: str) -> AnswerResult:
        """
        Retrieve relevant chunks, build a context pack, call ChatGPT.

        This is a **synchronous** method; call it inside asyncio.to_thread()
        from async handlers.
        """
        if not self._store.is_ready:
            return AnswerResult(
                text=(
                    "⚠️ База знаний ещё не загружена.\n"
                    "Администратор может исправить это командой /reload_kb."
                ),
                found=False,
            )

        # 1. Semantic search
        results = self._store.search(question, k=self._top_k)
        relevant = [(chunk, score) for chunk, score in results if score >= self._min_score]

        logger.debug(
            "Query: %r  →  %d/%d chunks above threshold %.2f",
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
                    "• Перефразировать вопрос\n"
                    "• Уточнить детали\n"
                    "• Использовать другие ключевые слова"
                ),
                found=False,
            )

        # 2. Assemble context
        context_text = self._build_context(relevant)
        user_message = f"Вопрос: {question}\n\n[КОНТЕКСТ]\n{context_text}"

        # 3. Call ChatGPT (may raise; caller handles exceptions)
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

        # 4. Collect images from retrieved chunks (deduplicated, preserving order)
        images: list[str] = []
        seen: set[str] = set()
        for chunk, _ in relevant:
            for img_path in chunk.images:
                if img_path not in seen:
                    images.append(img_path)
                    seen.add(img_path)

        sources = [chunk.source_label for chunk, _ in relevant]

        logger.info(
            "Answer generated. chunks_used=%d, sources=%s",
            len(relevant),
            [s[:40] for s in sources],
        )

        return AnswerResult(text=answer_text, sources=sources, images=images, found=True)

    # ─────────────────────────────────────────────────────────────────────────

    def _build_context(self, results: list[tuple[Chunk, float]]) -> str:
        parts: list[str] = []
        for chunk, score in results:
            parts.append(
                f"[chunk_id: {chunk.chunk_id[:8]}]\n"
                f"Раздел: «{chunk.heading}»\n"
                f"Схожесть: {score:.2f}\n"
                f"---\n"
                f"{chunk.text}"
            )
        return "\n\n".join(parts)
