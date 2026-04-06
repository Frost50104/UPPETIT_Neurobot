import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db, AsyncSessionLocal
from models.user import User
from models.kb_sync import KBSyncLog
from schemas.kb import KBStatusOut, KBSyncOut
from core.rbac import require_permission, Perm
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_BENCHMARK_HISTORY_MAX = 3
_BENCHMARK_HISTORY_FILE = Path(__file__).resolve().parent.parent.parent / "storage" / "benchmark_history.json"


def _load_benchmark_history() -> list[dict]:
    try:
        if _BENCHMARK_HISTORY_FILE.exists():
            with open(_BENCHMARK_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.warning("Could not load benchmark history: %s", exc)
    return []


def _save_benchmark_history() -> None:
    try:
        _BENCHMARK_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_BENCHMARK_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(_benchmark_history, f, ensure_ascii=False)
    except Exception as exc:
        logger.warning("Could not save benchmark history: %s", exc)


# In-memory benchmark state (shared across requests)
_benchmark_running: dict | None = None   # current run (or None)
_benchmark_history: list[dict] = _load_benchmark_history()  # last N completed runs (newest first)

router = APIRouter(prefix="/api/admin/kb", tags=["admin-kb"])


@router.get("/status", response_model=KBStatusOut)
async def kb_status(
    request: Request,
    current_user: User = Depends(require_permission(Perm.KB_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    vector_store = request.app.state.vector_store

    # Last successful sync
    result = await db.execute(
        select(KBSyncLog)
        .where(KBSyncLog.status == "success")
        .order_by(KBSyncLog.finished_at.desc())
        .limit(1)
    )
    last_sync_log = result.scalar_one_or_none()

    # Last sync of any status
    result = await db.execute(
        select(KBSyncLog)
        .order_by(KBSyncLog.started_at.desc())
        .limit(1)
    )
    last_any = result.scalar_one_or_none()

    return KBStatusOut(
        is_ready=vector_store.is_ready,
        chunk_count=vector_store.chunk_count,
        last_sync=last_sync_log.finished_at if last_sync_log else None,
        last_sync_status=last_any.status if last_any else None,
    )


@router.post("/refresh")
async def refresh_kb(
    request: Request,
    current_user: User = Depends(require_permission(Perm.KB_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    # Check if sync already in progress
    result = await db.execute(
        select(KBSyncLog).where(KBSyncLog.status == "in_progress")
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Обновление уже выполняется")

    # Create sync log entry
    sync_log = KBSyncLog(
        triggered_by_id=current_user.id,
        status="in_progress",
    )
    db.add(sync_log)
    await db.commit()
    await db.refresh(sync_log)
    sync_log_id = sync_log.id

    # Run rebuild in background thread
    app = request.app

    async def _do_rebuild():
        app.state.kb_rebuilding = True
        async with AsyncSessionLocal() as session:
            log = await session.get(KBSyncLog, sync_log_id)
            try:
                result = await asyncio.to_thread(_sync_rebuild, app)
                log.status = "success"
                log.files_count = result["files_count"]
                log.chunks_count = result["chunks_count"]
                log.finished_at = datetime.now(timezone.utc)
                logger.info("KB refresh completed: %d files, %d chunks", result["files_count"], result["chunks_count"])
            except Exception as exc:
                log.status = "failed"
                log.error_message = str(exc)[:1000]
                log.finished_at = datetime.now(timezone.utc)
                logger.error("KB refresh failed: %s", exc, exc_info=True)
            finally:
                app.state.kb_rebuilding = False
            await session.commit()

    asyncio.create_task(_do_rebuild())

    return {"ok": True, "sync_id": sync_log_id, "message": "Обновление базы знаний запущено"}


def _sync_rebuild(app) -> dict:
    """Synchronous function that runs in a thread pool."""
    import shutil
    from rag.gdrive import GDriveSync
    from rag.kb_loader import load_knowledge_base_multi
    from rag.chunker import chunk_sections
    from inject_kb_corrections import apply_corrections

    # 1. Download from Google Drive
    gdrive = GDriveSync(
        credentials_path=settings.google_credentials_path,
        folder_id=settings.gdrive_folder_id,
        download_dir=settings.kb_downloads_dir,
    )
    file_paths, files_count = gdrive.sync()

    if not file_paths:
        raise ValueError("Не удалось скачать файлы с Google Drive")

    # 2. Clear old images before re-extracting (safe because chat is blocked during rebuild)
    images_path = Path(settings.images_dir)
    if images_path.exists():
        shutil.rmtree(images_path)
    images_path.mkdir(parents=True, exist_ok=True)

    # 3. Parse all docx files
    str_paths = [str(p) for p in file_paths]
    sections = load_knowledge_base_multi(str_paths, settings.images_dir)

    if not sections:
        raise ValueError("Не удалось извлечь содержимое из скачанных файлов")

    # 3b. Caption images using vision model
    from rag.image_captioner import caption_all_images
    client = app.state.openai_client
    caption_all_images(sections, client)

    # 4. Chunk
    chunks = chunk_sections(sections, settings.chunk_size, settings.chunk_overlap)

    if not chunks:
        raise ValueError("Не удалось создать чанки из контента")

    # 5. Build vector store
    vector_store = app.state.vector_store
    vector_store.build(chunks)

    # 6. Always re-apply factual corrections after every rebuild
    n_corrections = apply_corrections(vector_store)

    return {"files_count": files_count, "chunks_count": len(chunks) + n_corrections}


@router.get("/history", response_model=list[KBSyncOut])
async def kb_history(
    current_user: User = Depends(require_permission(Perm.KB_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KBSyncLog)
        .order_by(KBSyncLog.started_at.desc())
        .limit(20)
    )
    logs = result.scalars().all()

    out = []
    for log in logs:
        # Load triggered_by name
        triggered_by_name = None
        if log.triggered_by_id:
            user = await db.get(User, log.triggered_by_id)
            if user:
                triggered_by_name = user.full_name

        out.append(KBSyncOut(
            id=log.id,
            status=log.status,
            files_count=log.files_count,
            chunks_count=log.chunks_count,
            error_message=log.error_message,
            started_at=log.started_at,
            finished_at=log.finished_at,
            triggered_by_name=triggered_by_name,
        ))

    return out


@router.delete("/history/{log_id}", status_code=204)
async def delete_kb_history(
    log_id: int,
    current_user: User = Depends(require_permission(Perm.KB_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    log = await db.get(KBSyncLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    await db.delete(log)
    await db.commit()


# ---------------------------------------------------------------------------
# Benchmark endpoints
# ---------------------------------------------------------------------------

@router.post("/benchmark")
async def start_benchmark(
    request: Request,
    current_user: User = Depends(require_permission(Perm.KB_MANAGE)),
):
    global _benchmark_running

    if _benchmark_running is not None:
        raise HTTPException(status_code=409, detail="Бенчмарк уже выполняется")

    _benchmark_running = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "progress": 0,
        "total": 0,
        "summary": None,
        "qa_report": None,
        "error": None,
    }

    app = request.app
    asyncio.create_task(asyncio.to_thread(_run_benchmark_sync, app))

    return {"ok": True, "message": "Бенчмарк запущен"}


@router.get("/benchmark/status")
async def benchmark_status(
    current_user: User = Depends(require_permission(Perm.KB_MANAGE)),
):
    return {
        "running": _benchmark_running,
        "history": _benchmark_history,
    }


def _run_benchmark_sync(app) -> None:
    """Run full benchmark synchronously in a thread pool."""
    global _benchmark_running, _benchmark_history
    try:
        from benchmark import (
            load_questions, run_benchmark, compute_summary,
            init_pipeline, save_qa_report,
        )

        backend_dir = Path(__file__).resolve().parent.parent.parent
        data_path = str(backend_dir / "benchmark_data.json")

        questions = load_questions(data_path)
        _benchmark_running["total"] = len(questions)

        # Init pipeline (reuses app's vector store settings)
        answerer, client, config_snapshot = init_pipeline()

        # Patched run_benchmark that updates progress
        from benchmark import (
            QuestionResult, QuestionSpec, check_sources, check_facts,
            check_images, check_image_sources, check_not_found,
            check_key_fact_early, judge_answer, judge_attestation,
        )
        import time

        results: list[QuestionResult] = []
        for i, spec in enumerate(questions, 1):
            _benchmark_running["progress"] = i

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

            qr.source_hit, qr.matched_sources = check_sources(rag_result, spec)
            qr.fact_hits, qr.fact_total, qr.facts_missing = check_facts(rag_result, spec)
            qr.image_ok = check_images(rag_result, spec)
            qr.image_source_ok = check_image_sources(rag_result, spec)
            qr.not_found_ok = check_not_found(rag_result, spec)
            qr.key_fact_early = check_key_fact_early(rag_result, spec)
            qr.correct_answer = spec.correct_answer

            is_attestation = bool(spec.correct_answer)
            if is_attestation and rag_result.found:
                qr.attest_skipped = False
                qr.attest_correct, qr.attest_comment = judge_attestation(
                    client, spec.question, rag_result.text,
                    spec.correct_answer, spec.wrong_answers,
                )
                qr.judge_skipped = True
                time.sleep(1)
            elif not is_attestation and spec.expect_found and rag_result.found:
                qr.judge = judge_answer(client, spec.question, rag_result.text)
                time.sleep(1)
            else:
                qr.judge_skipped = True

            results.append(qr)

        summary = compute_summary(results)
        qa_path = save_qa_report(results, output_dir=str(backend_dir))

        # Rotate old benchmark files — keep max 3
        import glob as _glob
        old_reports = sorted(_glob.glob(str(backend_dir / "benchmark_qa_*.txt")))
        for old in old_reports[:-3]:
            try:
                os.remove(old)
            except OSError:
                pass

        # Read QA report text
        with open(qa_path, "r", encoding="utf-8") as f:
            qa_text = f.read()

        _benchmark_running["status"] = "done"
        _benchmark_running["finished_at"] = datetime.now(timezone.utc).isoformat()
        _benchmark_running["summary"] = summary
        _benchmark_running["qa_report"] = qa_text

        logger.info("Benchmark completed: overall=%.1f%%", summary.get("overall_pct", 0))

    except Exception as exc:
        _benchmark_running["status"] = "failed"
        _benchmark_running["finished_at"] = datetime.now(timezone.utc).isoformat()
        _benchmark_running["error"] = str(exc)[:1000]
        logger.error("Benchmark failed: %s", exc, exc_info=True)

    finally:
        # Move completed run to history, persist to disk, clear running state
        if _benchmark_running is not None:
            _benchmark_history.insert(0, _benchmark_running)
            _benchmark_history[:] = _benchmark_history[:_BENCHMARK_HISTORY_MAX]
            _benchmark_running = None
            _save_benchmark_history()
