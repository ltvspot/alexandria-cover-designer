"""Prompt 4A end-to-end orchestration for Alexandria Cover Designer."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import signal
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from src import book_enricher
    from src import config
    from src import cover_analyzer
    from src import cover_compositor
    from src import gdrive_sync
    from src import image_generator
    from src import intelligent_prompter
    from src import output_exporter
    from src import prompt_generator
    from src import quality_gate
    from src import safe_json
    from src.logger import get_logger
    from src.notifications import BatchNotifier
    from src.prompt_library import PromptLibrary
except ModuleNotFoundError:  # pragma: no cover
    import book_enricher  # type: ignore
    import config  # type: ignore
    import cover_analyzer  # type: ignore
    import cover_compositor  # type: ignore
    import gdrive_sync  # type: ignore
    import image_generator  # type: ignore
    import intelligent_prompter  # type: ignore
    import output_exporter  # type: ignore
    import prompt_generator  # type: ignore
    import quality_gate  # type: ignore
    import safe_json  # type: ignore
    from logger import get_logger  # type: ignore
    from notifications import BatchNotifier  # type: ignore
    from prompt_library import PromptLibrary  # type: ignore

logger = get_logger(__name__)

PIPELINE_STATE_PATH = config.pipeline_state_path()
PIPELINE_SUMMARY_PATH = config.pipeline_summary_path()
PIPELINE_SUMMARY_MD_PATH = config.pipeline_summary_markdown_path()
SUPPORTED_PROVIDERS = ["openrouter", "openai", "fal", "google"]
_SHUTDOWN_REQUESTED = False
_QUALITY_GATE_LOCK = threading.Lock()


def _pipeline_state_path(runtime: config.Config | None = None) -> Path:
    if runtime is None:
        return PIPELINE_STATE_PATH
    return config.pipeline_state_path(catalog_id=getattr(runtime, "catalog_id", None), data_dir=runtime.data_dir)


def _pipeline_summary_path(runtime: config.Config | None = None) -> Path:
    if runtime is None:
        return PIPELINE_SUMMARY_PATH
    return config.pipeline_summary_path(catalog_id=getattr(runtime, "catalog_id", None), data_dir=runtime.data_dir)


def _pipeline_summary_markdown_path(runtime: config.Config | None = None) -> Path:
    if runtime is None:
        return PIPELINE_SUMMARY_MD_PATH
    return config.pipeline_summary_markdown_path(catalog_id=getattr(runtime, "catalog_id", None), data_dir=runtime.data_dir)


@dataclass(slots=True)
class BookRunResult:
    book_number: int
    status: str
    generated: int
    quality_passed: int
    composited: int
    exported: int
    duration_seconds: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PipelineResult:
    processed_books: int
    succeeded_books: int
    failed_books: int
    skipped_books: int
    generated_images: int
    exported_files: int
    dry_run: bool
    interrupted: bool
    started_at: str
    finished_at: str
    book_results: list[BookRunResult]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["book_results"] = [item.to_dict() for item in self.book_results]
        return payload


def _request_shutdown(signum: int, _frame: Any) -> None:
    global _SHUTDOWN_REQUESTED
    _SHUTDOWN_REQUESTED = True
    logger.warning("Received signal %s; pipeline will stop after current book.", signum)


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    config_overrides: dict[str, Any],
    book_numbers: list[int] | None = None,
    resume: bool = True,
    dry_run: bool = False,
    *,
    catalog_id: str | None = None,
) -> dict[str, Any]:
    """Run full pipeline for specified books."""
    global _SHUTDOWN_REQUESTED
    _SHUTDOWN_REQUESTED = False
    runtime = config.get_config(catalog_id)
    prompts_path_override = _prepare_prompt_source(runtime=runtime, config_overrides=config_overrides)
    _ensure_prerequisites(input_dir=input_dir, runtime=runtime, prompts_path=prompts_path_override)
    state = _load_pipeline_state(runtime=runtime)

    books = (
        book_numbers[:]
        if book_numbers
        else config.get_initial_scope_book_numbers(limit=20, catalog_id=runtime.catalog_id)
    )
    books = sorted(set(books))
    if not books:
        summary = PipelineResult(
            processed_books=0,
            succeeded_books=0,
            failed_books=0,
            skipped_books=0,
            generated_images=0,
            exported_files=0,
            dry_run=dry_run,
            interrupted=False,
            started_at=_utc_now(),
            finished_at=_utc_now(),
            book_results=[],
        )
        _write_summary(summary, runtime=runtime)
        return summary.to_dict()

    model_list = _resolve_models(config_overrides, runtime)
    workers = max(1, int(config_overrides.get("workers", 1) or 1))
    priority_order = str(config_overrides.get("priority", "high,medium,low") or "high,medium,low")
    prompt_variant_ids = list(config_overrides.get("prompt_variant_ids") or [])
    variation_count = int(config_overrides.get("variation_count", runtime.variants_per_cover))
    no_resume = bool(config_overrides.get("no_resume", False))

    result_rows: list[BookRunResult] = []
    generated_count = 0
    exported_count = 0
    skipped_count = 0

    started_at = _utc_now()
    interrupted = False
    ordered_books = _prioritize_books(
        books,
        output_dir=output_dir,
        runtime=runtime,
        priority_order=priority_order,
        state=state,
    )

    notifier = BatchNotifier(runtime=runtime, enabled=bool(config_overrides.get("notify", False)))
    batch_id = f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    generation_state = {
        "catalog": runtime.catalog_id,
        "batch_id": batch_id,
        "total_books": len(ordered_books),
        "completed_books": [],
        "failed_books": [],
        "in_progress": [],
        "estimated_completion": None,
        "avg_time_per_book": 0.0,
        "avg_cost_per_book": 0.0,
        "workers": workers,
        "priority": priority_order,
        "started_at": started_at,
    }
    _save_generation_state(runtime=runtime, state=generation_state)

    notifier.batch_start(
        batch_id=batch_id,
        catalog_id=runtime.catalog_id,
        total_books=len(ordered_books),
        workers=workers,
        models=(model_list or ([*runtime.all_models] if bool(config_overrides.get("all_models", False)) else [runtime.ai_model])),
    )

    queue: list[int] = []
    for book_number in ordered_books:
        if resume and (not no_resume) and _book_is_complete(book_number, output_dir, state, runtime.book_catalog_path):
            skipped_count += 1
            row = BookRunResult(
                book_number=book_number,
                status="skipped",
                generated=0,
                quality_passed=0,
                composited=0,
                exported=0,
                duration_seconds=0.0,
                cost_usd=0.0,
            )
            result_rows.append(row)
            state.setdefault("completed_books", {})[str(book_number)] = {
                "completed_at": _utc_now(),
                "exported_files": 0,
                "status": "skipped",
            }
            generation_state["completed_books"].append(book_number)
        else:
            queue.append(book_number)

    _refresh_generation_state_estimate(
        generation_state=generation_state,
        rows=result_rows,
        workers=workers,
    )
    _save_generation_state(runtime=runtime, state=generation_state)
    _save_pipeline_state(state, runtime=runtime)

    def _record_row(row: BookRunResult) -> None:
        nonlocal generated_count, exported_count
        result_rows.append(row)
        generated_count += row.generated
        exported_count += row.exported

        if row.status in {"success", "skipped"}:
            state.setdefault("completed_books", {})[str(row.book_number)] = {
                "completed_at": _utc_now(),
                "exported_files": row.exported,
                "duration_seconds": round(row.duration_seconds, 3),
                "cost_usd": round(row.cost_usd, 4),
                "status": row.status,
            }
            state.get("failed_books", {}).pop(str(row.book_number), None)
            if row.book_number not in generation_state["completed_books"]:
                generation_state["completed_books"].append(row.book_number)
            if row.book_number in generation_state["failed_books"]:
                generation_state["failed_books"].remove(row.book_number)
        else:
            state.setdefault("failed_books", {})[str(row.book_number)] = {
                "failed_at": _utc_now(),
                "error": row.error,
                "duration_seconds": round(row.duration_seconds, 3),
            }
            if row.book_number not in generation_state["failed_books"]:
                generation_state["failed_books"].append(row.book_number)
            notifier.batch_error(
                batch_id=batch_id,
                catalog_id=runtime.catalog_id,
                book_number=row.book_number,
                error=row.error or "Unknown error",
            )

        if row.book_number in generation_state["in_progress"]:
            generation_state["in_progress"].remove(row.book_number)
        _refresh_generation_state_estimate(
            generation_state=generation_state,
            rows=result_rows,
            workers=workers,
        )
        _save_generation_state(runtime=runtime, state=generation_state)
        _save_pipeline_state(state, runtime=runtime)

        completed_total = len(generation_state["completed_books"]) + len(generation_state["failed_books"])
        if completed_total > 0 and (completed_total % 100 == 0):
            notifier.milestone(
                batch_id=batch_id,
                catalog_id=runtime.catalog_id,
                completed_books=completed_total,
                total_books=len(ordered_books),
                avg_cost_per_book=float(generation_state.get("avg_cost_per_book", 0.0) or 0.0),
                estimated_completion=generation_state.get("estimated_completion"),
            )

    run_kwargs = {
        "runtime": runtime,
        "input_dir": input_dir,
        "output_dir": output_dir,
        "prompts_path_override": prompts_path_override,
        "model_list": model_list,
        "dry_run": dry_run,
        "variation_count": variation_count,
        "prompt_variant_ids": prompt_variant_ids,
        "prompt_override": config_overrides.get("prompt_override"),
        "use_library": bool(config_overrides.get("use_library", False)),
        "prompt_id": config_overrides.get("prompt_id"),
        "style_anchors": config_overrides.get("style_anchors") or [],
        "all_models": bool(config_overrides.get("all_models", False)),
        "provider": config_overrides.get("provider"),
        "no_resume": no_resume,
    }

    if workers <= 1:
        for idx, book_number in enumerate(queue, start=1):
            if _SHUTDOWN_REQUESTED:
                interrupted = True
                logger.warning("Graceful shutdown before book %s.", book_number)
                break

            generation_state["in_progress"].append(book_number)
            _save_generation_state(runtime=runtime, state=generation_state)
            _log_progress(
                processed=(len(result_rows) + idx - 1),
                total=len(ordered_books),
                state=state,
                output_dir=output_dir,
            )
            try:
                row = _run_single_book(book_number=book_number, **run_kwargs)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Pipeline book failure for %s: %s", book_number, exc)
                row = BookRunResult(
                    book_number=book_number,
                    status="failed",
                    generated=0,
                    quality_passed=0,
                    composited=0,
                    exported=0,
                    duration_seconds=0.0,
                    cost_usd=0.0,
                    error=str(exc),
                )
            _record_row(row)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            active: dict[Future[BookRunResult], int] = {}
            pending = queue[:]

            while (pending or active) and not interrupted:
                while pending and len(active) < workers and (not _SHUTDOWN_REQUESTED):
                    book_number = pending.pop(0)
                    generation_state["in_progress"].append(book_number)
                    _save_generation_state(runtime=runtime, state=generation_state)
                    future = executor.submit(_run_single_book, book_number=book_number, **run_kwargs)
                    active[future] = book_number

                if _SHUTDOWN_REQUESTED and pending:
                    interrupted = True
                    logger.warning("Shutdown requested; not scheduling remaining %d books.", len(pending))

                if not active:
                    break

                done, _ = wait(active.keys(), timeout=1.0, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    book_number = active.pop(future)
                    try:
                        row = future.result()
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.error("Pipeline book failure for %s: %s", book_number, exc)
                        row = BookRunResult(
                            book_number=book_number,
                            status="failed",
                            generated=0,
                            quality_passed=0,
                            composited=0,
                            exported=0,
                            duration_seconds=0.0,
                            cost_usd=0.0,
                            error=str(exc),
                        )
                    _record_row(row)

                _log_progress(
                    processed=len(result_rows),
                    total=len(ordered_books),
                    state=state,
                    output_dir=output_dir,
                )

            if _SHUTDOWN_REQUESTED:
                interrupted = True

    summary = PipelineResult(
        processed_books=len(ordered_books),
        succeeded_books=sum(1 for row in result_rows if row.status == "success"),
        failed_books=sum(1 for row in result_rows if row.status == "failed"),
        skipped_books=skipped_count,
        generated_images=generated_count,
        exported_files=exported_count,
        dry_run=dry_run,
        interrupted=interrupted,
        started_at=started_at,
        finished_at=_utc_now(),
        book_results=result_rows,
    )
    generation_state["finished_at"] = summary.finished_at
    _save_generation_state(runtime=runtime, state=generation_state)
    _write_summary(summary, runtime=runtime)
    notifier.batch_complete(
        batch_id=batch_id,
        catalog_id=runtime.catalog_id,
        completed_books=(summary.succeeded_books + summary.skipped_books),
        failed_books=summary.failed_books,
        total_books=summary.processed_books,
        total_cost=round(sum(row.cost_usd for row in summary.book_results), 4),
        estimated_completion=generation_state.get("estimated_completion"),
    )
    return summary.to_dict()


def get_pipeline_status(output_dir: Path, *, catalog_id: str | None = None) -> dict[str, Any]:
    """Get pipeline progress overview."""
    runtime = config.get_config(catalog_id)
    state = _load_pipeline_state(runtime=runtime)
    completed = len(state.get("completed_books", {}))
    failed = len(state.get("failed_books", {}))

    book_dirs = [path for path in output_dir.iterdir() if path.is_dir()] if output_dir.exists() else []
    exported_books = len([path for path in book_dirs if path.name != "Archive"])
    exported_files = len(list(output_dir.rglob("*.*"))) if output_dir.exists() else 0

    return {
        "completed_books": completed,
        "failed_books": failed,
        "exported_books": exported_books,
        "exported_files": exported_files,
        "state_path": str(_pipeline_state_path(runtime)),
        "catalog": runtime.catalog_id,
    }


def test_api_keys(
    *,
    runtime: config.Config | None = None,
    providers: list[str] | None = None,
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Validate configured provider keys using low-cost account/models endpoints."""
    runtime = runtime or config.get_config()
    chosen = _normalize_providers(providers)

    rows: list[dict[str, str] | None] = [None] * len(chosen)
    probe_futures: dict[Future[tuple[bool, str]], tuple[int, str]] = {}
    max_workers = max(1, min(4, len(chosen)))
    executor: ThreadPoolExecutor | None = ThreadPoolExecutor(max_workers=max_workers)
    for idx, provider in enumerate(chosen):
        key = runtime.get_api_key(provider).strip()
        if not key:
            rows[idx] = {"provider": provider, "status": "KEY_MISSING", "detail": "No key configured."}
            continue
        assert executor is not None
        future = executor.submit(_probe_provider_key, provider=provider, api_key=key, timeout=timeout)
        probe_futures[future] = (idx, provider)

    try:
        for future in as_completed(probe_futures):
            idx, provider = probe_futures[future]
            try:
                ok, detail = future.result()
            except Exception as exc:  # pragma: no cover - defensive
                ok, detail = False, f"Probe failed: {exc}"
            rows[idx] = {
                "provider": provider,
                "status": "KEY_VALID" if ok else "KEY_INVALID",
                "detail": detail,
            }
    finally:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

    return {
        "checked_at": _utc_now(),
        "providers": [row for row in rows if isinstance(row, dict)],
    }


def _run_single_book(
    *,
    book_number: int,
    runtime: config.Config,
    input_dir: Path,
    output_dir: Path,
    prompts_path_override: Path | None,
    model_list: list[str] | None,
    dry_run: bool,
    variation_count: int,
    prompt_variant_ids: list[int],
    prompt_override: str | None,
    use_library: bool,
    prompt_id: str | None,
    style_anchors: list[str],
    all_models: bool,
    provider: str | None,
    no_resume: bool,
) -> BookRunResult:
    started = time.perf_counter()
    generated_dir = runtime.tmp_dir / "generated"
    composited_dir = runtime.tmp_dir / "composited"

    active_models = model_list or ([*runtime.all_models] if all_models else [runtime.ai_model])

    prompts_path = prompts_path_override or runtime.prompts_path
    prompts_payload = safe_json.load_json(prompts_path, {"books": []})
    if not isinstance(prompts_payload, dict):
        raise ValueError(f"Invalid prompts payload at {prompts_path}")
    book_entry = _find_book_entry(prompts_payload, book_number)

    prompt_text = prompt_override
    negative_prompt = None

    if use_library or prompt_id or style_anchors:
        library = PromptLibrary(runtime.prompt_library_path)
        if prompt_id:
            prompt_match = next((item for item in library.get_prompts() if item.id == prompt_id), None)
            if not prompt_match:
                raise KeyError(f"Prompt id '{prompt_id}' not found in prompt library")
            prompt_text = prompt_match.prompt_template.format(title=book_entry["title"])
            negative_prompt = prompt_match.negative_prompt
        elif style_anchors:
            prompt_text = library.build_prompt(
                book_title=book_entry["title"],
                style_anchors=style_anchors,
            )
            negative_prompt = prompts_payload.get("negative_prompt", "")
        elif use_library:
            best = library.get_best_prompts_for_bulk(top_n=1)
            if best:
                prompt_text = best[0].prompt_template.format(title=book_entry["title"])
                negative_prompt = best[0].negative_prompt

    overrides = _load_model_prompt_overrides(runtime.model_prompt_overrides_path)
    explicit_prompt_requested = bool(prompt_override or prompt_id or style_anchors or use_library)

    generation_results: list[image_generator.GenerationResult] = []

    if prompt_variant_ids:
        for prompt_variant in prompt_variant_ids:
            source_variant = _find_variant_entry(book_entry, prompt_variant)
            used_prompt = prompt_text or source_variant.get("prompt", "")
            used_negative = negative_prompt or source_variant.get("negative_prompt", "")

            generation_results.extend(
                _generate_with_model_prompts(
                    book_number=book_number,
                    base_prompt=used_prompt,
                    negative_prompt=used_negative,
                    models=active_models,
                    variants_per_model=1,
                    title=str(book_entry.get("title", f"Book {book_number}")),
                    overrides=overrides,
                    explicit_prompt_requested=explicit_prompt_requested,
                    output_dir=generated_dir,
                    resume=not no_resume,
                    dry_run=dry_run,
                    provider_override=provider,
                )
            )
    else:
        base_variant = _find_variant_entry(book_entry, 1)
        used_prompt = prompt_text or base_variant.get("prompt", "")
        used_negative = negative_prompt or base_variant.get("negative_prompt", "")
        generation_results = _generate_with_model_prompts(
            book_number=book_number,
            base_prompt=used_prompt,
            negative_prompt=used_negative,
            models=active_models,
            variants_per_model=variation_count,
            title=str(book_entry.get("title", f"Book {book_number}")),
            overrides=overrides,
            explicit_prompt_requested=explicit_prompt_requested,
            output_dir=generated_dir,
            resume=not no_resume,
            dry_run=dry_run,
            provider_override=provider,
        )

    generated_successes = sum(1 for row in generation_results if row.success)
    generation_cost = round(
        sum(float(row.cost or 0.0) for row in generation_results if row.success),
        4,
    )

    if dry_run:
        return BookRunResult(
            book_number=book_number,
            status="success",
            generated=generated_successes,
            quality_passed=generated_successes,
            composited=0,
            exported=0,
            duration_seconds=round(time.perf_counter() - started, 3),
            cost_usd=generation_cost,
        )

    # Quality gate (book-scoped directory to avoid re-scoring entire corpus each run).
    quality_scope_root = runtime.tmp_dir / "quality_scope" / f"book_{book_number}"
    if quality_scope_root.exists():
        shutil.rmtree(quality_scope_root)
    quality_scope_root.mkdir(parents=True, exist_ok=True)

    source_book_generated = generated_dir / str(book_number)
    if source_book_generated.exists():
        shutil.copytree(
            source_book_generated,
            quality_scope_root / str(book_number),
            dirs_exist_ok=True,
        )

    with _QUALITY_GATE_LOCK:
        all_scores = quality_gate.run_quality_gate(
            generated_dir=quality_scope_root,
            prompts_path=prompts_path,
            threshold=runtime.min_quality_score,
            max_retries=runtime.max_retries,
            perform_retries=True,
        )
    if (quality_scope_root / str(book_number)).exists():
        shutil.copytree(
            quality_scope_root / str(book_number),
            source_book_generated,
            dirs_exist_ok=True,
        )
    book_scores = [row for row in all_scores if row.book_number == book_number]
    passed_scores = [row for row in book_scores if row.passed]

    composited_paths = cover_compositor.composite_all_variants(
        book_number=book_number,
        input_dir=input_dir,
        generated_dir=generated_dir,
        output_dir=composited_dir,
        regions=json.loads(
            config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir).read_text(encoding="utf-8")
        ),
        catalog_path=runtime.book_catalog_path,
    )

    exported_paths = output_exporter.export_book_variants(
        book_number=book_number,
        composited_root=composited_dir,
        output_root=output_dir,
        catalog_path=runtime.book_catalog_path,
    )

    return BookRunResult(
        book_number=book_number,
        status="success",
        generated=generated_successes,
        quality_passed=len(passed_scores),
        composited=len(composited_paths),
        exported=len(exported_paths),
        duration_seconds=round(time.perf_counter() - started, 3),
        cost_usd=generation_cost,
    )


def _generate_with_model_prompts(
    *,
    book_number: int,
    base_prompt: str,
    negative_prompt: str,
    models: list[str],
    variants_per_model: int,
    title: str,
    overrides: dict[str, Any],
    explicit_prompt_requested: bool,
    output_dir: Path,
    resume: bool,
    dry_run: bool,
    provider_override: str | None,
) -> list[image_generator.GenerationResult]:
    if not models:
        return []

    base_prompt = prompt_generator.enforce_prompt_constraints(str(base_prompt or ""))
    normalized_negative = str(negative_prompt or "").strip()
    negative_low = normalized_negative.lower()
    required_negative_terms = (
        "border",
        "frame",
        "decorative edge",
        "ornamental border",
        "filigree",
        "scrollwork",
        "arabesque",
        "ornamental curls",
        "black ornamental silhouettes",
        "lace-like cutout motifs",
    )
    if any(term not in negative_low for term in required_negative_terms):
        for term in required_negative_terms:
            if term not in negative_low:
                normalized_negative = f"{normalized_negative}, {term}".strip(", ")
        negative_low = normalized_negative.lower()

    prompt_by_model: dict[str, str] = {}
    for model in models:
        resolved = _resolve_model_prompt(
            model=model,
            title=title,
            fallback_prompt=base_prompt,
            overrides=overrides,
            explicit_prompt_requested=explicit_prompt_requested,
        )
        prompt_by_model[model] = prompt_generator.enforce_prompt_constraints(str(resolved or base_prompt))

    unique_prompts = {value for value in prompt_by_model.values()}
    if len(unique_prompts) == 1:
        return image_generator.generate_all_models(
            book_number=book_number,
            prompt=next(iter(unique_prompts)),
            negative_prompt=normalized_negative,
            models=models,
            variants_per_model=variants_per_model,
            output_dir=output_dir,
            resume=resume,
            dry_run=dry_run,
            provider_override=provider_override,
        )

    results: list[image_generator.GenerationResult] = []
    for model in models:
        model_prompt = prompt_by_model.get(model, base_prompt)
        results.extend(
            image_generator.generate_all_models(
                book_number=book_number,
                prompt=model_prompt,
                negative_prompt=normalized_negative,
                models=[model],
                variants_per_model=variants_per_model,
                output_dir=output_dir,
                resume=resume,
                dry_run=dry_run,
                provider_override=provider_override,
            )
        )
    return results


def _load_model_prompt_overrides(path: Path) -> dict[str, Any]:
    payload = safe_json.load_json(path, {})
    models = payload.get("models", {}) if isinstance(payload, dict) else {}
    return models if isinstance(models, dict) else {}


def _resolve_model_prompt(
    *,
    model: str,
    title: str,
    fallback_prompt: str,
    overrides: dict[str, Any],
    explicit_prompt_requested: bool,
) -> str:
    if explicit_prompt_requested:
        return fallback_prompt
    row = overrides.get(model)
    if not isinstance(row, dict):
        row = overrides.get(model.split("/", 1)[-1], {})
    if not isinstance(row, dict):
        return fallback_prompt

    template = str(row.get("prompt_template", "")).strip()
    if not template:
        return fallback_prompt

    try:
        return template.format(title=title)
    except Exception:
        return template


def _probe_provider_key(*, provider: str, api_key: str, timeout: float) -> tuple[bool, str]:
    provider = provider.strip().lower()
    try:
        if provider == "openrouter":
            response = requests.get(
                "https://openrouter.ai/api/v1/models/user",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
        elif provider == "openai":
            response = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
        elif provider == "replicate":
            response = requests.get(
                "https://api.replicate.com/v1/account",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout,
            )
        elif provider == "fal":
            response = requests.get(
                "https://api.fal.ai/v1/models?limit=1",
                headers={"Authorization": f"Key {api_key}"},
                timeout=timeout,
            )
        elif provider == "google":
            response = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                headers={"x-goog-api-key": api_key},
                timeout=timeout,
            )
        else:
            return False, f"Unsupported provider '{provider}'."
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"

    if 200 <= response.status_code < 300:
        return True, f"HTTP {response.status_code}"

    body = response.text.strip().replace("\n", " ")
    if len(body) > 240:
        body = body[:240] + "..."
    return False, f"HTTP {response.status_code}: {body or 'empty response'}"


def _prepare_prompt_source(*, runtime: config.Config, config_overrides: dict[str, Any]) -> Path | None:
    intelligent_prompts = bool(config_overrides.get("intelligent_prompts", False))
    legacy_prompts = bool(config_overrides.get("legacy_prompts", False))
    enrich_first = bool(config_overrides.get("enrich_first", False))
    if (not intelligent_prompts) or legacy_prompts:
        return None

    enriched_catalog_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    intelligent_prompts_path = config.intelligent_prompts_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)

    if enrich_first or (not enriched_catalog_path.exists()):
        try:
            book_enricher.enrich_catalog(
                catalog_path=runtime.book_catalog_path,
                output_path=enriched_catalog_path,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Book enrichment step failed, falling back to existing catalog: %s", exc)

    source_catalog = enriched_catalog_path if enriched_catalog_path.exists() else runtime.book_catalog_path
    try:
        intelligent_prompter.generate_prompts(
            catalog_path=source_catalog,
            output_path=intelligent_prompts_path,
            provider=runtime.llm_provider,
            model=runtime.llm_model,
            max_tokens=runtime.llm_max_tokens,
        )
        return intelligent_prompts_path
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Intelligent prompt generation failed, using legacy prompts: %s", exc)
        return None


def _ensure_prerequisites(*, input_dir: Path, runtime: config.Config, prompts_path: Path | None = None) -> None:

    regions_path = config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    if not regions_path.exists():
        cover_analyzer.analyze_all_covers(input_dir, template_id=runtime.cover_style, regions_path=regions_path)

    target_prompts_path = prompts_path or runtime.prompts_path
    if not target_prompts_path.exists():
        prompts = prompt_generator.generate_all_prompts(
            catalog_path=runtime.book_catalog_path,
            templates_path=runtime.prompt_templates_path,
        )
        prompt_generator.save_prompts(prompts, target_prompts_path)

    if not runtime.prompt_library_path.exists():
        PromptLibrary(runtime.prompt_library_path)


def _normalize_providers(providers: list[str] | None) -> list[str]:
    if not providers:
        return SUPPORTED_PROVIDERS[:]

    selected: list[str] = []
    for provider in providers:
        token = str(provider).strip().lower()
        if not token:
            continue
        if token not in selected:
            selected.append(token)
    return selected


def _find_book_entry(prompts_payload: dict[str, Any], book_number: int) -> dict[str, Any]:
    for row in prompts_payload.get("books", []):
        if int(row.get("number", 0)) == int(book_number):
            return row
    raise KeyError(f"Book {book_number} missing from prompts payload")


def _find_variant_entry(book_entry: dict[str, Any], variant_id: int) -> dict[str, Any]:
    for row in book_entry.get("variants", []):
        if int(row.get("variant_id", 0)) == int(variant_id):
            return row
    variants = book_entry.get("variants", [])
    if variants:
        return variants[0]
    raise KeyError(f"No variants in book entry: {book_entry.get('number')}")


def _resolve_models(config_overrides: dict[str, Any], runtime: config.Config) -> list[str] | None:
    if config_overrides.get("all_models"):
        return [*runtime.all_models]
    models_raw = config_overrides.get("models")
    if models_raw:
        return [token.strip() for token in str(models_raw).split(",") if token.strip()]
    model_raw = config_overrides.get("model")
    if model_raw:
        return [str(model_raw).strip()]
    return None


def _load_pipeline_state(*, runtime: config.Config) -> dict[str, Any]:
    state_path = _pipeline_state_path(runtime)
    payload = safe_json.load_json(state_path, {"catalog": runtime.catalog_id, "completed_books": {}, "failed_books": {}})
    if not isinstance(payload, dict):
        return {"catalog": runtime.catalog_id, "completed_books": {}, "failed_books": {}}
    if str(payload.get("catalog", runtime.catalog_id)) != runtime.catalog_id:
        return {"catalog": runtime.catalog_id, "completed_books": {}, "failed_books": {}}
    if not isinstance(payload.get("completed_books"), dict):
        payload["completed_books"] = {}
    if not isinstance(payload.get("failed_books"), dict):
        payload["failed_books"] = {}
    payload["catalog"] = runtime.catalog_id
    return payload


def _save_pipeline_state(state: dict[str, Any], *, runtime: config.Config) -> None:
    state = copy.deepcopy(state)
    state["catalog"] = runtime.catalog_id
    state_path = _pipeline_state_path(runtime)
    safe_json.atomic_write_json(state_path, state)


def _book_is_complete(book_number: int, output_dir: Path, state: dict[str, Any], catalog_path: Path) -> bool:
    if str(book_number) not in state.get("completed_books", {}):
        return False

    catalog = safe_json.load_json(catalog_path, [])
    if not isinstance(catalog, list):
        return False
    match = next((row for row in catalog if int(row.get("number", 0)) == int(book_number)), None)
    if not match:
        return False

    folder_name = str(match["folder_name"])
    if folder_name.endswith(" copy"):
        folder_name = folder_name[:-5]

    book_dir = output_dir / folder_name
    return book_dir.exists() and len(list(book_dir.rglob("*.*"))) >= 15


def _write_summary(summary: PipelineResult, *, runtime: config.Config | None = None) -> None:
    payload = summary.to_dict()
    summary_path = _pipeline_summary_path(runtime)
    summary_md_path = _pipeline_summary_markdown_path(runtime)
    safe_json.atomic_write_json(summary_path, payload)

    lines = [
        "# Pipeline Summary",
        "",
        f"- Started: {summary.started_at}",
        f"- Finished: {summary.finished_at}",
        f"- Processed books: **{summary.processed_books}**",
        f"- Success: **{summary.succeeded_books}**",
        f"- Failed: **{summary.failed_books}**",
        f"- Skipped: **{summary.skipped_books}**",
        f"- Generated images: **{summary.generated_images}**",
        f"- Exported files: **{summary.exported_files}**",
        f"- Dry run: **{summary.dry_run}**",
        "",
        "## Per-Book Results",
        "",
        "| Book | Status | Generated | Quality Pass | Composited | Exported | Time (s) | Cost ($) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]

    for row in summary.book_results:
        lines.append(
            f"| {row.book_number} | {row.status} | {row.generated} | {row.quality_passed} | {row.composited} | {row.exported} | {row.duration_seconds:.2f} | {row.cost_usd:.4f} |"
        )

    summary_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _log_progress(*, processed: int, total: int, state: dict[str, Any], output_dir: Path) -> None:
    completed = len(state.get("completed_books", {}))
    exported_images = len(list(output_dir.rglob("*.jpg"))) if output_dir.exists() else 0
    shown_complete = min(total, max(completed, processed))
    logger.info("Progress: [%d/%d books complete, %d exported jpgs]", shown_complete, total, exported_images)


def _save_generation_state(*, runtime: config.Config, state: dict[str, Any]) -> None:
    safe_json.atomic_write_json(runtime.generation_state_path, state)


def _refresh_generation_state_estimate(
    *,
    generation_state: dict[str, Any],
    rows: list[BookRunResult],
    workers: int,
) -> None:
    success_rows = [row for row in rows if row.status == "success"]
    if success_rows:
        avg_time = sum(row.duration_seconds for row in success_rows) / len(success_rows)
        avg_cost = sum(row.cost_usd for row in success_rows) / len(success_rows)
    else:
        avg_time = 0.0
        avg_cost = 0.0

    total = int(generation_state.get("total_books", 0) or 0)
    completed = len(generation_state.get("completed_books", [])) + len(generation_state.get("failed_books", []))
    remaining = max(0, total - completed)

    generation_state["avg_time_per_book"] = round(avg_time, 3)
    generation_state["avg_cost_per_book"] = round(avg_cost, 4)

    if avg_time > 0 and remaining > 0:
        remaining_seconds = (remaining * avg_time) / max(1, workers)
        generation_state["estimated_completion"] = (datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds)).isoformat()
    else:
        generation_state["estimated_completion"] = None


def _books_below_quality_threshold(*, runtime: config.Config, threshold: float) -> set[int]:
    quality_path = config.quality_scores_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)
    payload = safe_json.load_json(quality_path, {})
    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return set()

    best_by_book: dict[int, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            book = int(row.get("book_number", 0))
            score = float(row.get("overall_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if book <= 0:
            continue
        best_by_book[book] = max(best_by_book.get(book, 0.0), score)

    return {book for book, score in best_by_book.items() if score < threshold}


def _prioritize_books(
    books: list[int],
    *,
    output_dir: Path,
    runtime: config.Config,
    priority_order: str,
    state: dict[str, Any],
) -> list[int]:
    failed = {int(key) for key in state.get("failed_books", {}).keys() if str(key).isdigit()}
    low_quality = _books_below_quality_threshold(runtime=runtime, threshold=runtime.min_quality_score)

    high: set[int] = set()
    medium: set[int] = set()
    low: set[int] = set()
    for book in books:
        if book in failed or book in low_quality:
            high.add(book)
            continue
        if _book_is_complete(book, output_dir, state, runtime.book_catalog_path):
            low.add(book)
        else:
            medium.add(book)

    buckets = {"high": sorted(high), "medium": sorted(medium), "low": sorted(low)}
    ordered_levels = [token.strip().lower() for token in priority_order.split(",") if token.strip()]
    if not ordered_levels:
        ordered_levels = ["high", "medium", "low"]

    ordered: list[int] = []
    seen: set[int] = set()
    for level in ordered_levels:
        for book in buckets.get(level, []):
            if book in seen:
                continue
            seen.add(book)
            ordered.append(book)

    for book in sorted(books):
        if book not in seen:
            ordered.append(book)
    return ordered


def estimate_batch(
    *,
    runtime: config.Config,
    books: list[int],
    models: list[str],
    variants_per_model: int,
    workers: int,
) -> dict[str, Any]:
    model_cost = sum(runtime.get_model_cost(model) for model in models)
    images_per_book = max(1, variants_per_model) * max(1, len(models))
    per_book_cost = model_cost * max(1, variants_per_model)
    total_cost = per_book_cost * max(0, len(books))

    avg_seconds = 45.0
    history_path = config.generation_history_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)
    payload = safe_json.load_json(history_path, {})
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    try:
        durations = [float(row.get("generation_time", 0.0) or 0.0) for row in rows if isinstance(row, dict)]
        durations = [value for value in durations if value > 0]
        if durations:
            avg_seconds = max(10.0, sum(durations) / len(durations))
    except Exception:
        avg_seconds = 45.0

    seconds_per_book = avg_seconds * images_per_book
    total_seconds = seconds_per_book * max(0, len(books)) / max(1, workers)
    return {
        "estimated_cost": round(total_cost, 2),
        "estimated_time_hours": round(total_seconds / 3600.0, 2),
        "books": len(books),
        "variants_per_model": max(1, variants_per_model),
        "models": models,
        "workers": max(1, workers),
        "cost_per_image": round(model_cost / max(1, len(models)), 4),
    }


def _parse_books(raw: str | None) -> list[int] | None:
    if not raw:
        return None

    values: set[int] = set()
    for piece in raw.split(","):
        token = piece.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            for value in range(min(int(start), int(end)), max(int(start), int(end)) + 1):
                values.add(value)
        else:
            values.add(int(token))

    return sorted(values)


def _format_api_key_report(report: dict[str, Any]) -> str:
    rows = report.get("providers", [])
    if not isinstance(rows, list):
        return "No providers checked."
    lines = []
    for row in rows:
        provider = str(row.get("provider", "unknown")).upper()
        status = str(row.get("status", "KEY_INVALID"))
        detail = str(row.get("detail", "")).strip()
        if detail:
            lines.append(f"{provider} — {status} — {detail}")
        else:
            lines.append(f"{provider} — {status}")
    return "\n".join(lines)


def _resolve_variant_options(variants_arg: str | None, variant_arg: int | None, runtime: config.Config) -> tuple[int, list[int]]:
    if variant_arg is not None:
        return 1, [int(variant_arg)]

    if not variants_arg:
        return runtime.variants_per_cover, []

    text = variants_arg.strip()
    if any(sep in text for sep in [",", "-"]):
        ids = _parse_books(text) or []
        return 1, ids

    try:
        return int(text), []
    except ValueError:
        return runtime.variants_per_cover, []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_credentials_path(runtime: config.Config) -> Path:
    token = runtime.google_credentials_path.strip()
    if token:
        path = Path(token)
        if not path.is_absolute():
            path = runtime.project_root / path
        return path
    return runtime.config_dir / "credentials.json"


def _collect_passed_sync_paths(output_dir: Path, books: list[int], scores_path: Path, catalog_path: Path) -> list[str]:
    payload = safe_json.load_json(scores_path, {})

    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    passed_variants: dict[int, set[int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not bool(row.get("passed")):
            continue
        try:
            book = int(row.get("book_number", 0))
            variant = int(row.get("variant_id", 0))
        except (TypeError, ValueError):
            continue
        passed_variants.setdefault(book, set()).add(variant)

    catalog = safe_json.load_json(catalog_path, [])
    if not isinstance(catalog, list):
        return []
    folder_by_book: dict[int, str] = {}
    for entry in catalog:
        try:
            number = int(entry.get("number", 0))
        except (TypeError, ValueError):
            continue
        folder_name = str(entry.get("folder_name", ""))
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]
        folder_by_book[number] = folder_name

    selected: list[str] = []
    for book in sorted(set(int(value) for value in books)):
        folder_name = folder_by_book.get(book)
        if not folder_name:
            continue
        book_dir = output_dir / folder_name
        if not book_dir.exists():
            continue
        variants = passed_variants.get(book, set())
        for variant in sorted(variants):
            variant_dir = book_dir / f"Variant-{variant}"
            if not variant_dir.exists():
                continue
            for file_path in sorted(variant_dir.glob("*")):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in {".jpg", ".pdf", ".ai"}:
                    continue
                selected.append(str(file_path.relative_to(output_dir)))
    return selected


def _sync_output_to_drive(*, output_dir: Path, books: list[int], runtime: config.Config) -> dict[str, Any]:
    drive_folder_id = runtime.gdrive_output_folder_id.strip()
    if not drive_folder_id:
        raise ValueError("GDRIVE_OUTPUT_FOLDER_ID is empty.")

    credentials_path = _resolve_credentials_path(runtime)
    if not drive_folder_id.startswith("local:") and not credentials_path.exists():
        raise FileNotFoundError(
            f"Google credentials missing at {credentials_path}. "
            "Create config/credentials.json or set GOOGLE_CREDENTIALS_PATH."
        )

    selected_paths = _collect_passed_sync_paths(
        output_dir=output_dir,
        books=books,
        scores_path=config.quality_scores_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir),
        catalog_path=runtime.book_catalog_path,
    )

    if not selected_paths:
        return {
            "mode": "google_api",
            "total_files": 0,
            "uploaded": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
            "progress": [],
            "note": "No quality-passed variant files found for sync.",
        }

    return gdrive_sync.sync_selected_to_drive(
        local_output_dir=output_dir,
        relative_paths=selected_paths,
        drive_folder_id=drive_folder_id,
        credentials_path=credentials_path,
        incremental=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 4A pipeline orchestrator")
    parser.add_argument("--catalog", type=str, default=config.DEFAULT_CATALOG_ID, help="Catalog id from config/catalogs.json")
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)

    parser.add_argument("--book", type=int, default=None)
    parser.add_argument("--books", type=str, default=None)

    parser.add_argument("--variant", type=int, default=None)
    parser.add_argument("--variants", type=str, default=None)

    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--models", type=str, default=None)
    parser.add_argument("--all-models", action="store_true")
    parser.add_argument("--provider", type=str, default=None)

    parser.add_argument("--prompt-override", type=str, default=None)
    parser.add_argument("--use-library", action="store_true")
    parser.add_argument("--prompt-id", type=str, default=None)
    parser.add_argument("--style-anchors", type=str, default=None)
    parser.add_argument("--intelligent-prompts", action="store_true", help="Use LLM-generated intelligent prompts")
    parser.add_argument("--enrich-first", action="store_true", help="Run enrichment before intelligent prompt generation")
    parser.add_argument("--legacy-prompts", action="store_true", help="Force template-based prompt generator")

    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4, help="Parallel book workers")
    parser.add_argument("--priority", type=str, default="high,medium,low", help="Priority queue order")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync", action="store_true", help="Upload quality-passed outputs to Google Drive after generation")
    parser.add_argument("--estimate", action="store_true", help="Estimate cost/time only")
    parser.add_argument("--notify", action="store_true", help="Send webhook notifications")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--test-api-keys", action="store_true")
    parser.add_argument("--retry-failures", action="store_true", help="Retry only failed generations from data/generation_failures.json")

    args = parser.parse_args()
    runtime = config.get_config(args.catalog)
    _install_signal_handlers()
    input_dir = args.input_dir or runtime.input_dir
    output_dir = args.output_dir or runtime.output_dir

    if args.status:
        logger.info("Pipeline status: %s", json.dumps(get_pipeline_status(output_dir, catalog_id=runtime.catalog_id), ensure_ascii=False))
        return 0

    if args.test_api_keys:
        providers = [args.provider] if args.provider else None
        report = test_api_keys(runtime=runtime, providers=providers)
        logger.info("API key validation report:\n%s", _format_api_key_report(report))
        return 0

    if args.retry_failures:
        results = image_generator.retry_failures(
            failures_path=runtime.failures_path,
            output_dir=runtime.tmp_dir / "generated",
            resume=(args.resume and not args.no_resume),
        )
        total = len(results)
        success = sum(1 for row in results if row.success)
        failed = total - success
        affected_books = sorted({row.book_number for row in results})
        logger.info(
            "Retried failures from %s: total=%s success=%s failed=%s books=%s",
            runtime.failures_path,
            total,
            success,
            failed,
            affected_books,
        )
        return 0 if failed == 0 else 1

    if args.book is not None:
        books = [args.book]
    else:
        books = _parse_books(args.books) or config.get_initial_scope_book_numbers(limit=20, catalog_id=runtime.catalog_id)

    variation_count, prompt_variant_ids = _resolve_variant_options(args.variants, args.variant, runtime)
    model_list = _resolve_models(
        {
            "model": args.model,
            "models": args.models,
            "all_models": args.all_models,
        },
        runtime,
    ) or ([*runtime.all_models] if args.all_models else [runtime.ai_model])

    if args.estimate:
        estimate = estimate_batch(
            runtime=runtime,
            books=books,
            models=model_list,
            variants_per_model=variation_count,
            workers=max(1, args.workers),
        )
        logger.info(
            "Estimated cost: $%.2f for %d books × %d variants/model across %d model(s). Estimated time: %.2f hours at %d workers.",
            estimate["estimated_cost"],
            estimate["books"],
            estimate["variants_per_model"],
            len(model_list),
            estimate["estimated_time_hours"],
            estimate["workers"],
        )
        return 0

    overrides = {
        "model": args.model,
        "models": args.models,
        "all_models": args.all_models,
        "provider": args.provider,
        "prompt_override": args.prompt_override,
        "use_library": args.use_library,
        "prompt_id": args.prompt_id,
        "style_anchors": [token.strip() for token in (args.style_anchors or "").split(",") if token.strip()],
        "batch_size": args.batch_size,
        "workers": args.workers,
        "priority": args.priority,
        "notify": args.notify,
        "variation_count": variation_count,
        "prompt_variant_ids": prompt_variant_ids,
        "no_resume": args.no_resume,
        "intelligent_prompts": args.intelligent_prompts,
        "enrich_first": args.enrich_first,
        "legacy_prompts": args.legacy_prompts,
    }

    result = run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        config_overrides=overrides,
        book_numbers=books,
        resume=(args.resume and not args.no_resume),
        dry_run=args.dry_run,
        catalog_id=runtime.catalog_id,
    )

    sync_failed = False
    if args.sync and not args.dry_run:
        try:
            sync_summary = _sync_output_to_drive(output_dir=output_dir, books=books, runtime=runtime)
            logger.info("Drive sync summary: %s", sync_summary)
        except Exception as exc:  # pragma: no cover - external boundary
            sync_failed = True
            logger.error("Drive sync failed: %s", exc)

    logger.info("Pipeline result: %s", result)
    return 0 if int(result.get("failed_books", 0)) == 0 and not sync_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
