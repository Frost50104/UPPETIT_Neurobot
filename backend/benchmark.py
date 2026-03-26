#!/usr/bin/env python3
"""
RAG Benchmark — automated quality evaluation for UPPETIT Neurobot.

Usage:
    cd /opt/neurobot/backend
    python3 benchmark.py              # full run
    python3 benchmark.py --no-judge   # skip LLM judge (faster, cheaper)
    python3 benchmark.py --category team  # run only one category

Outputs:
    - Console progress + summary table
    - benchmark_results_YYYYMMDD_HHMMSS.json  (full breakdown)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so imports work standalone
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND_DIR))

from config import get_settings
from openai import OpenAI
from rag.rag_answerer import RAGAnswerer, AnswerResult
from rag.vector_store import VectorStore

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("benchmark")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class QuestionSpec:
    id: str
    category: str
    question: str
    expected_facts: list[str]
    expected_sources: list[str]
    expect_images: bool
    expect_found: bool
    correct_answer: str = ""
    wrong_answers: list[str] = field(default_factory=list)


@dataclass
class JudgeScores:
    relevance: int = 0
    completeness: int = 0
    accuracy: int = 0
    comment: str = ""


@dataclass
class QuestionResult:
    id: str
    category: str
    question: str
    # RAG output
    answer_text: str = ""
    sources: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    found: bool = False
    image_sources: list[str] = field(default_factory=list)
    # Automated checks
    source_hit: bool = False
    matched_sources: list[str] = field(default_factory=list)
    fact_hits: int = 0
    fact_total: int = 0
    facts_missing: list[str] = field(default_factory=list)
    image_ok: bool = False
    image_source_ok: bool = True  # True when images come from relevant sources
    not_found_ok: bool = True
    # LLM judge
    judge: JudgeScores = field(default_factory=JudgeScores)
    judge_skipped: bool = False
    # Attestation
    attest_correct: bool = False
    attest_skipped: bool = True  # True for non-attestation questions
    attest_comment: str = ""
    correct_answer: str = ""  # reference answer for attestation
    # Timing
    elapsed_s: float = 0.0


# ---------------------------------------------------------------------------
# Pipeline initialisation (mirrors main._init_rag)
# ---------------------------------------------------------------------------

def init_pipeline() -> tuple[RAGAnswerer, OpenAI, dict]:
    """Build RAG pipeline from .env settings, return (answerer, client, config_snapshot)."""
    settings = get_settings()

    client = OpenAI(api_key=settings.openai_api_key)

    vector_store = VectorStore(
        storage_dir=settings.storage_dir,
        embedding_model=settings.embedding_model,
        openai_client=client,
    )
    vector_store.load()

    if not vector_store.is_ready:
        print("ERROR: Vector store is empty. Run KB rebuild first.")
        sys.exit(1)

    answerer = RAGAnswerer(
        vector_store=vector_store,
        openai_client=client,
        chat_model=settings.chat_model,
        top_k=settings.top_k,
        max_tokens=settings.max_tokens,
        min_score=settings.min_score,
        min_semantic_score=settings.min_semantic_score,
    )

    config_snapshot = {
        "chat_model": settings.chat_model,
        "embedding_model": settings.embedding_model,
        "top_k": settings.top_k,
        "max_tokens": settings.max_tokens,
        "min_score": settings.min_score,
        "min_semantic_score": settings.min_semantic_score,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunk_count": vector_store.chunk_count,
    }

    print(f"Pipeline ready. {vector_store.chunk_count} chunks loaded.")
    return answerer, client, config_snapshot


# ---------------------------------------------------------------------------
# Load benchmark data
# ---------------------------------------------------------------------------

def load_questions(path: str, category_filter: str | None = None) -> list[QuestionSpec]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    questions = [QuestionSpec(**q) for q in data["questions"]]

    if category_filter:
        questions = [q for q in questions if q.category == category_filter]
        if not questions:
            print(f"ERROR: No questions found for category '{category_filter}'.")
            sys.exit(1)

    return questions


# ---------------------------------------------------------------------------
# Automated checks
# ---------------------------------------------------------------------------

def check_sources(result: AnswerResult, spec: QuestionSpec) -> tuple[bool, list[str]]:
    """Check if any expected source substring appears in actual sources."""
    if not spec.expected_sources:
        return True, []

    actual = " ".join(result.sources).lower()
    matched = []
    for expected in spec.expected_sources:
        if expected.lower() in actual:
            matched.append(expected)

    return len(matched) > 0, matched


def check_facts(result: AnswerResult, spec: QuestionSpec) -> tuple[int, int, list[str]]:
    """Check how many expected fact substrings appear in the answer text."""
    if not spec.expected_facts:
        return 0, 0, []

    text_lower = result.text.lower()
    hits = 0
    missing = []
    for fact in spec.expected_facts:
        if fact.lower() in text_lower:
            hits += 1
        else:
            missing.append(fact)

    return hits, len(spec.expected_facts), missing


def check_images(result: AnswerResult, spec: QuestionSpec) -> bool:
    """Check if image presence/absence matches expectation."""
    has_images = len(result.images) > 0
    return has_images == spec.expect_images


def check_image_sources(result: AnswerResult, spec: QuestionSpec) -> bool:
    """Check if returned images come from relevant sources.

    Returns True when:
    - No images expected and none returned
    - Images returned and at least one image_source matches expected_sources
    - No expected_sources defined (can't check)
    """
    if not spec.expect_images or not result.images:
        return True  # nothing to check
    if not spec.expected_sources:
        return True  # no expected sources to compare against
    if not result.image_sources:
        return False  # images present but no source tracking

    sources_lower = " ".join(result.image_sources).lower()
    return any(es.lower() in sources_lower for es in spec.expected_sources)


def check_not_found(result: AnswerResult, spec: QuestionSpec) -> bool:
    """For edge cases: result.found should be False."""
    if spec.expect_found:
        return True  # not applicable
    return not result.found


# ---------------------------------------------------------------------------
# LLM Judge
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """\
Ты — эксперт по оценке качества ответов корпоративного чат-бота.

Тебе дан вопрос сотрудника и ответ бота. Оцени ответ по 3 критериям (от 1 до 5):

1. **Релевантность** — отвечает ли бот на заданный вопрос (1=совсем не по теме, 5=точно по теме)
2. **Полнота** — насколько полно раскрыта тема (1=минимум информации, 5=исчерпывающе)
3. **Точность** — нет ли выдуманных фактов или противоречий (1=много ошибок, 5=всё корректно)

Верни ТОЛЬКО валидный JSON без markdown-блоков:
{"relevance": N, "completeness": N, "accuracy": N, "comment": "краткий комментарий"}
"""


def call_with_retry(
    client: OpenAI,
    model: str,
    messages: list[dict],
    max_retries: int = 3,
) -> str:
    """Call OpenAI with exponential backoff on rate limits."""
    delays = [5, 15, 45]
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=200,
                temperature=0,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "limit" in err_str:
                if attempt < max_retries:
                    delay = delays[min(attempt, len(delays) - 1)]
                    print(f"  [rate limit] waiting {delay}s...")
                    time.sleep(delay)
                    continue
            raise
    return ""


def judge_answer(client: OpenAI, question: str, answer_text: str) -> JudgeScores:
    """Ask GPT-4o-mini to evaluate the answer quality."""
    user_msg = f"Вопрос: {question}\n\nОтвет бота:\n{answer_text}"

    raw = call_with_retry(
        client,
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _JUDGE_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    # Parse JSON from response (handle possible markdown wrapping)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        data = json.loads(raw)
        return JudgeScores(
            relevance=int(data.get("relevance", 0)),
            completeness=int(data.get("completeness", 0)),
            accuracy=int(data.get("accuracy", 0)),
            comment=str(data.get("comment", "")),
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Judge response parse error: %s. Raw: %s", e, raw[:200])
        return JudgeScores(comment=f"parse_error: {raw[:100]}")


# ---------------------------------------------------------------------------
# Attestation judge
# ---------------------------------------------------------------------------

_ATTEST_JUDGE_PROMPT = """\
Тебе даны: вопрос из аттестации, ответ бота, ПРАВИЛЬНЫЙ ответ и НЕПРАВИЛЬНЫЕ варианты.

Определи, соответствует ли ответ бота правильному варианту.

ПРАВИЛА ОЦЕНКИ:
- Бот НЕ обязан дословно повторить правильный ответ.
- Достаточно, чтобы ключевые факты (числа, названия, действия) из правильного ответа
  ПРИСУТСТВОВАЛИ в ответе бота.
- Если ответ бота содержит БОЛЬШЕ деталей, чем правильный ответ, но при этом
  ключевые факты правильного ответа присутствуют — это CORRECT.
- WRONG только если ответ бота явно противоречит правильному ответу, содержит
  данные из неправильных вариантов, или упускает ключевые факты правильного ответа.

Верни ТОЛЬКО валидный JSON без markdown-блоков:
{"correct": true, "comment": "краткое обоснование"}
или
{"correct": false, "comment": "краткое обоснование"}
"""


def judge_attestation(
    client: OpenAI,
    question: str,
    answer_text: str,
    correct_answer: str,
    wrong_answers: list[str],
) -> tuple[bool, str]:
    """Ask LLM to judge if the bot's answer matches the correct option.

    Returns (is_correct, comment).
    """
    wrong_str = "\n".join(f"  - {w}" for w in wrong_answers)
    user_msg = (
        f"ВОПРОС: {question}\n\n"
        f"ОТВЕТ БОТА:\n{answer_text}\n\n"
        f"ПРАВИЛЬНЫЙ ОТВЕТ: {correct_answer}\n\n"
        f"НЕПРАВИЛЬНЫЕ ВАРИАНТЫ:\n{wrong_str}"
    )

    raw = call_with_retry(
        client,
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _ATTEST_JUDGE_PROMPT},
            {"role": "user", "content": user_msg},
        ],
    )

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        data = json.loads(raw)
        return bool(data.get("correct", False)), str(data.get("comment", ""))
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Attestation judge parse error: %s. Raw: %s", e, raw[:200])
        return False, f"parse_error: {raw[:100]}"


# ---------------------------------------------------------------------------
# Run benchmark
# ---------------------------------------------------------------------------

def run_benchmark(
    answerer: RAGAnswerer,
    client: OpenAI,
    questions: list[QuestionSpec],
    use_judge: bool = True,
) -> list[QuestionResult]:
    results: list[QuestionResult] = []
    total = len(questions)

    for i, spec in enumerate(questions, 1):
        print(f"\n[{i:2d}/{total}] {spec.id}: {spec.question}")

        t0 = time.time()
        rag_result = answerer.answer(spec.question)
        elapsed = time.time() - t0

        qr = QuestionResult(
            id=spec.id,
            category=spec.category,
            question=spec.question,
            answer_text=rag_result.text,
            sources=rag_result.sources,
            images=rag_result.images,
            image_sources=rag_result.image_sources,
            found=rag_result.found,
            elapsed_s=round(elapsed, 2),
        )

        # Automated checks
        qr.source_hit, qr.matched_sources = check_sources(rag_result, spec)
        qr.fact_hits, qr.fact_total, qr.facts_missing = check_facts(rag_result, spec)
        qr.image_ok = check_images(rag_result, spec)
        qr.image_source_ok = check_image_sources(rag_result, spec)
        qr.not_found_ok = check_not_found(rag_result, spec)

        # Store reference answer for reporting
        qr.correct_answer = spec.correct_answer

        # LLM judge / attestation judge
        is_attestation = bool(spec.correct_answer)
        if is_attestation and use_judge and rag_result.found:
            qr.attest_skipped = False
            qr.attest_correct, qr.attest_comment = judge_attestation(
                client, spec.question, rag_result.text,
                spec.correct_answer, spec.wrong_answers,
            )
            qr.judge_skipped = True  # no general judge for attestation
            time.sleep(1)
        elif not is_attestation and use_judge and spec.expect_found and rag_result.found:
            qr.judge = judge_answer(client, spec.question, rag_result.text)
            time.sleep(1)
        else:
            qr.judge_skipped = True

        # Console line
        src_status = "OK" if qr.source_hit else "MISS"
        facts_str = f"{qr.fact_hits}/{qr.fact_total}" if qr.fact_total else "n/a"
        img_status = "OK" if qr.image_ok else "MISS"
        img_src_status = "OK" if qr.image_source_ok else "WRONG_SRC"
        nf_status = "OK" if qr.not_found_ok else "FAIL"

        if is_attestation:
            if qr.attest_skipped:
                attest_str = "skipped"
            else:
                attest_str = "CORRECT" if qr.attest_correct else "WRONG"
            print(
                f"        found={qr.found}  facts={facts_str}  "
                f"attest={attest_str}  ({qr.elapsed_s:.1f}s)"
            )
            if qr.attest_comment and not qr.attest_skipped:
                print(f"        attest: {qr.attest_comment[:100]}")
        else:
            if qr.judge_skipped:
                judge_str = "skipped"
            else:
                j = qr.judge
                judge_str = f"{j.relevance}/{j.completeness}/{j.accuracy}"

            print(
                f"        found={qr.found}  sources={src_status}  "
                f"facts={facts_str}  images={img_status}  "
                f"img_src={img_src_status}  "
                f"not_found={nf_status}  judge={judge_str}  "
                f"({qr.elapsed_s:.1f}s)"
            )

        if qr.facts_missing:
            print(f"        facts_missing={qr.facts_missing}")
        if not is_attestation and qr.judge.comment and not qr.judge_skipped:
            print(f"        judge: {qr.judge.comment[:100]}")

        results.append(qr)

    return results


# ---------------------------------------------------------------------------
# Summary & scoring
# ---------------------------------------------------------------------------

def compute_summary(results: list[QuestionResult]) -> dict:
    """Compute aggregate scores from individual results."""
    total = len(results)
    if not total:
        return {"overall": 0}

    # Retrieval (source_hit)
    applicable_retrieval = [r for r in results if r.found]
    retrieval_hits = sum(1 for r in applicable_retrieval if r.source_hit)
    retrieval_rate = retrieval_hits / len(applicable_retrieval) if applicable_retrieval else 0

    # Fact recall
    total_facts = sum(r.fact_total for r in results)
    hit_facts = sum(r.fact_hits for r in results)
    fact_recall = hit_facts / total_facts if total_facts else 0

    # Images (presence)
    image_hits = sum(1 for r in results if r.image_ok)
    image_rate = image_hits / total

    # Image source relevance
    img_src_applicable = [r for r in results if r.images and r.found]
    img_src_hits = sum(1 for r in img_src_applicable if r.image_source_ok)
    img_src_rate = img_src_hits / len(img_src_applicable) if img_src_applicable else 1.0

    # Not-found accuracy
    nf_applicable = [r for r in results if r.category == "edge_cases"]
    nf_correct = sum(1 for r in nf_applicable if r.not_found_ok)
    nf_rate = nf_correct / len(nf_applicable) if nf_applicable else 1.0

    # Judge averages
    judged = [r for r in results if not r.judge_skipped]
    if judged:
        avg_rel = sum(r.judge.relevance for r in judged) / len(judged)
        avg_comp = sum(r.judge.completeness for r in judged) / len(judged)
        avg_acc = sum(r.judge.accuracy for r in judged) / len(judged)
        avg_judge = (avg_rel + avg_comp + avg_acc) / 3
    else:
        avg_rel = avg_comp = avg_acc = avg_judge = 0

    # Attestation accuracy
    attest_results = [r for r in results if not r.attest_skipped]
    attest_correct = sum(1 for r in attest_results if r.attest_correct)
    attest_total = len(attest_results)
    attest_accuracy = attest_correct / attest_total if attest_total else 0

    # Overall weighted score — attestation gets highest weight as the most
    # objective metric (ground-truth answers). When no attestation questions
    # are present, weights redistribute proportionally.
    if attest_total > 0:
        overall = (
            retrieval_rate * 0.15
            + fact_recall * 0.15
            + (avg_judge / 5) * 0.20
            + nf_rate * 0.05
            + image_rate * 0.05
            + attest_accuracy * 0.40
        )
    else:
        # No attestation questions — use original weights
        overall = (
            retrieval_rate * 0.25
            + fact_recall * 0.25
            + (avg_judge / 5) * 0.30
            + nf_rate * 0.10
            + image_rate * 0.10
        )

    return {
        "overall_pct": round(overall * 100, 1),
        "retrieval": {
            "hits": retrieval_hits,
            "total": len(applicable_retrieval),
            "rate_pct": round(retrieval_rate * 100, 1),
        },
        "fact_recall": {
            "hits": hit_facts,
            "total": total_facts,
            "rate_pct": round(fact_recall * 100, 1),
        },
        "images": {
            "hits": image_hits,
            "total": total,
            "rate_pct": round(image_rate * 100, 1),
        },
        "image_sources": {
            "hits": img_src_hits,
            "total": len(img_src_applicable),
            "rate_pct": round(img_src_rate * 100, 1),
        },
        "not_found": {
            "correct": nf_correct,
            "total": len(nf_applicable),
            "rate_pct": round(nf_rate * 100, 1),
        },
        "judge_avg": {
            "relevance": round(avg_rel, 2),
            "completeness": round(avg_comp, 2),
            "accuracy": round(avg_acc, 2),
            "mean": round(avg_judge, 2),
        },
        "attestation": {
            "correct": attest_correct,
            "total": attest_total,
            "accuracy_pct": round(attest_accuracy * 100, 1),
        },
        "total_questions": total,
    }


def print_summary(summary: dict, results: list[QuestionResult]):
    """Print a readable summary table to console."""
    print("\n" + "=" * 50)
    print("                  BENCHMARK SUMMARY")
    print("=" * 50)

    print(f"\n  Overall score:   {summary['overall_pct']:.1f}%")
    print(f"  Questions:       {summary['total_questions']}")

    r = summary["retrieval"]
    print(f"\n  Retrieval:       {r['hits']}/{r['total']} ({r['rate_pct']}%)")

    f = summary["fact_recall"]
    print(f"  Fact recall:     {f['hits']}/{f['total']} ({f['rate_pct']}%)")

    im = summary["images"]
    print(f"  Images:          {im['hits']}/{im['total']} ({im['rate_pct']}%)")

    ims = summary["image_sources"]
    print(f"  Image sources:   {ims['hits']}/{ims['total']} ({ims['rate_pct']}%)")

    nf = summary["not_found"]
    print(f"  Not-found:       {nf['correct']}/{nf['total']} ({nf['rate_pct']}%)")

    j = summary["judge_avg"]
    print(f"\n  Judge averages:  rel={j['relevance']:.1f}  comp={j['completeness']:.1f}  acc={j['accuracy']:.1f}  mean={j['mean']:.1f}")

    att = summary["attestation"]
    if att["total"] > 0:
        print(f"\n  Attestation:     {att['correct']}/{att['total']} ({att['accuracy_pct']}%)")

    # Failures
    failures = [
        r for r in results
        if not r.source_hit or r.facts_missing or not r.image_ok
        or not r.image_source_ok or not r.not_found_ok
        or (not r.judge_skipped and min(r.judge.relevance, r.judge.completeness, r.judge.accuracy) <= 2)
        or (not r.attest_skipped and not r.attest_correct)
    ]

    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for r in failures:
            issues = []
            if not r.source_hit:
                issues.append("sources_miss")
            if r.facts_missing:
                issues.append(f"facts_missing={r.facts_missing}")
            if not r.image_ok:
                issues.append("images_miss")
            if not r.image_source_ok:
                issues.append(f"img_wrong_src={r.image_sources[:3]}")
            if not r.not_found_ok:
                issues.append("not_found_fail")
            if not r.judge_skipped:
                j = r.judge
                if min(j.relevance, j.completeness, j.accuracy) <= 2:
                    issues.append(f"judge={j.relevance}/{j.completeness}/{j.accuracy}")
            if not r.attest_skipped and not r.attest_correct:
                issues.append(f"attest=WRONG")
            print(f"    {r.id}: {', '.join(issues)}")

    # Per-category breakdown
    categories = sorted(set(r.category for r in results))
    print(f"\n  Per category:")
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        cat_judged = [r for r in cat_results if not r.judge_skipped]
        if cat_judged:
            cat_mean = sum(
                (r.judge.relevance + r.judge.completeness + r.judge.accuracy) / 3
                for r in cat_judged
            ) / len(cat_judged)
            judge_str = f"judge={cat_mean:.1f}"
        else:
            judge_str = "judge=n/a"

        cat_facts_hit = sum(r.fact_hits for r in cat_results)
        cat_facts_total = sum(r.fact_total for r in cat_results)
        fact_str = f"facts={cat_facts_hit}/{cat_facts_total}" if cat_facts_total else "facts=n/a"

        # Attestation accuracy for this category
        cat_attest = [r for r in cat_results if not r.attest_skipped]
        if cat_attest:
            cat_attest_ok = sum(1 for r in cat_attest if r.attest_correct)
            attest_str = f"attest={cat_attest_ok}/{len(cat_attest)}"
        else:
            attest_str = ""

        extra = f"  {attest_str}" if attest_str else ""
        print(f"    {cat:15s}  n={len(cat_results)}  {fact_str:15s}  {judge_str}{extra}")

    print("\n" + "=" * 50)


# ---------------------------------------------------------------------------
# Save JSON report
# ---------------------------------------------------------------------------

def save_report(
    results: list[QuestionResult],
    summary: dict,
    config_snapshot: dict,
    output_dir: str = ".",
) -> str:
    """Save full benchmark results to a timestamped JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_results_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    report = {
        "timestamp": datetime.now().isoformat(),
        "config": config_snapshot,
        "summary": summary,
        "results": [],
    }

    for r in results:
        report["results"].append({
            "id": r.id,
            "category": r.category,
            "question": r.question,
            "found": r.found,
            "source_hit": r.source_hit,
            "matched_sources": r.matched_sources,
            "fact_hits": r.fact_hits,
            "fact_total": r.fact_total,
            "facts_missing": r.facts_missing,
            "image_ok": r.image_ok,
            "image_source_ok": r.image_source_ok,
            "image_sources": r.image_sources,
            "not_found_ok": r.not_found_ok,
            "judge": asdict(r.judge) if not r.judge_skipped else None,
            "judge_skipped": r.judge_skipped,
            "attest_correct": r.attest_correct if not r.attest_skipped else None,
            "attest_skipped": r.attest_skipped,
            "attest_comment": r.attest_comment if not r.attest_skipped else None,
            "elapsed_s": r.elapsed_s,
            "answer_text": r.answer_text[:500],
            "sources": r.sources,
            "image_count": len(r.images),
        })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return filepath


def save_qa_report(results: list[QuestionResult], output_dir: str = ".") -> str:
    """Save a human-readable Q&A report as a text file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_qa_{timestamp}.txt"
    filepath = os.path.join(output_dir, filename)

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("  UPPETIT Neurobot — Вопросы и ответы бенчмарка")
    lines.append(f"  Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)

    for i, r in enumerate(results, 1):
        lines.append("")
        lines.append(f"{'─' * 70}")
        lines.append(f"  [{i}] {r.id} ({r.category})")
        lines.append(f"{'─' * 70}")
        lines.append("")
        lines.append(f"ВОПРОС: {r.question}")
        lines.append("")

        if not r.found:
            lines.append("ОТВЕТ: [Бот не нашёл информации в базе знаний]")
        else:
            lines.append(f"ОТВЕТ:\n{r.answer_text}")

        lines.append("")

        # Compact status line
        parts = [f"found={r.found}"]
        if r.source_hit:
            parts.append("sources=OK")
        else:
            parts.append("sources=MISS")
        if r.fact_total:
            parts.append(f"facts={r.fact_hits}/{r.fact_total}")
        parts.append(f"images={len(r.images)}")
        if r.images and r.image_sources:
            parts.append(f"img_from={r.image_sources[:3]}")
        if not r.image_source_ok:
            parts.append("IMG_WRONG_SOURCE")
        if not r.judge_skipped:
            j = r.judge
            parts.append(f"judge={j.relevance}/{j.completeness}/{j.accuracy}")
            if j.comment:
                parts.append(f"comment: {j.comment}")

        if not r.attest_skipped:
            verdict = "CORRECT" if r.attest_correct else "WRONG"
            parts.append(f"attest={verdict}")

        lines.append(f"ОЦЕНКА: {', '.join(parts)}")

        # Attestation block: show reference answer and verdict
        if not r.attest_skipped:
            lines.append("")
            lines.append(f"ЭТАЛОН: {r.correct_answer}")
            verdict = "CORRECT" if r.attest_correct else "WRONG"
            lines.append(f"ВЕРДИКТ: {verdict}")
            if r.attest_comment:
                lines.append(f"КОММЕНТАРИЙ: {r.attest_comment}")

    lines.append("")
    lines.append("=" * 70)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def audit_images(answerer: RAGAnswerer, questions: list[QuestionSpec]):
    """Quick audit: run each question and report actual vs expected image presence."""
    print("\n=== IMAGE AUDIT ===\n")
    mismatches = []
    for spec in questions:
        result = answerer.answer(spec.question)
        has_images = len(result.images) > 0
        match = has_images == spec.expect_images
        status = "OK" if match else "MISMATCH"
        if not match:
            mismatches.append(spec)
        print(
            f"  {spec.id:20s}  expect={spec.expect_images!s:5s}  "
            f"actual={has_images!s:5s}  images={len(result.images)}  {status}"
        )

    print(f"\n  Mismatches: {len(mismatches)}/{len(questions)}")
    if mismatches:
        print("\n  Fix these in benchmark_data.json:")
        for s in mismatches:
            new_val = not s.expect_images
            print(f'    {s.id}: "expect_images": {str(new_val).lower()}')
    print()


def main():
    parser = argparse.ArgumentParser(description="RAG Benchmark for UPPETIT Neurobot")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM judge evaluation")
    parser.add_argument("--category", type=str, default=None, help="Run only one category")
    parser.add_argument("--data", type=str, default=None, help="Path to benchmark_data.json")
    parser.add_argument("--audit-images", action="store_true", help="Audit image expectations only")
    args = parser.parse_args()

    data_path = args.data or os.path.join(_BACKEND_DIR, "benchmark_data.json")
    if not os.path.isfile(data_path):
        print(f"ERROR: Benchmark data not found at {data_path}")
        sys.exit(1)

    print("=" * 50)
    print("  UPPETIT Neurobot — RAG Benchmark")
    print("=" * 50)

    # 1. Init pipeline
    print("\nInitializing pipeline...")
    answerer, client, config_snapshot = init_pipeline()

    # 2. Load questions
    questions = load_questions(data_path, args.category)
    print(f"Loaded {len(questions)} questions.", end="")
    if args.category:
        print(f" (category: {args.category})", end="")
    if args.no_judge:
        print(" (LLM judge: OFF)", end="")
    print()

    # Audit-images mode: just check image expectations, no judge
    if args.audit_images:
        audit_images(answerer, questions)
        return

    # 3. Run
    t_start = time.time()
    results = run_benchmark(answerer, client, questions, use_judge=not args.no_judge)
    t_total = time.time() - t_start

    # 4. Summary
    summary = compute_summary(results)
    summary["total_time_s"] = round(t_total, 1)
    print_summary(summary, results)

    # 5. Save report
    filepath = save_report(results, summary, config_snapshot, output_dir=str(_BACKEND_DIR))
    print(f"\n  Report saved: {filepath}")

    # 6. Save readable Q&A file
    qa_path = save_qa_report(results, output_dir=str(_BACKEND_DIR))
    print(f"  Q&A report:   {qa_path}")
    print(f"  Total time:   {t_total:.0f}s")


if __name__ == "__main__":
    main()
