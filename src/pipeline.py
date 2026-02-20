"""Prompt 4A end-to-end orchestration for Alexandria Cover Designer."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src import config
    from src import cover_analyzer
    from src import cover_compositor
    from src import image_generator
    from src import output_exporter
    from src import prompt_generator
    from src import quality_gate
    from src.prompt_library import PromptLibrary
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import cover_analyzer  # type: ignore
    import cover_compositor  # type: ignore
    import image_generator  # type: ignore
    import output_exporter  # type: ignore
    import prompt_generator  # type: ignore
    import quality_gate  # type: ignore
    from prompt_library import PromptLibrary  # type: ignore


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PIPELINE_STATE_PATH = config.DATA_DIR / "pipeline_state.json"
PIPELINE_SUMMARY_PATH = config.DATA_DIR / "pipeline_summary.json"
PIPELINE_SUMMARY_MD_PATH = config.DATA_DIR / "pipeline_summary.md"


@dataclass(slots=True)
class BookRunResult:
    book_number: int
    status: str
    generated: int
    quality_passed: int
    composited: int
    exported: int
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
    started_at: str
    finished_at: str
    book_results: list[BookRunResult]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["book_results"] = [item.to_dict() for item in self.book_results]
        return payload


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    config_overrides: dict[str, Any],
    book_numbers: list[int] | None = None,
    resume: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run full pipeline for specified books (default: first 20 titles)."""
    runtime = config.get_config()

    _ensure_prerequisites(input_dir=input_dir)
    state = _load_pipeline_state()

    books = book_numbers[:] if book_numbers else config.get_initial_scope_book_numbers(limit=20)
    books = sorted(set(books))

    model_list = _resolve_models(config_overrides, runtime)
    batch_size = int(config_overrides.get("batch_size") or len(books) or 1)
    prompt_variant_ids = list(config_overrides.get("prompt_variant_ids") or [])
    variation_count = int(config_overrides.get("variation_count", runtime.variants_per_cover))

    result_rows: list[BookRunResult] = []
    generated_count = 0
    exported_count = 0
    skipped_count = 0

    started_at = _utc_now()

    batches = [books[i : i + batch_size] for i in range(0, len(books), batch_size)]
    total_batches = len(batches)

    for batch_index, batch_books in enumerate(batches, start=1):
        logger.info("=== Batch %d/%d (%d books) ===", batch_index, total_batches, len(batch_books))

        for idx, book_number in enumerate(batch_books, start=1):
            overall_index = sum(len(batch) for batch in batches[: batch_index - 1]) + idx
            _log_progress(
                processed=overall_index - 1,
                total=len(books),
                state=state,
                output_dir=output_dir,
            )

            if resume and _book_is_complete(book_number, output_dir, state):
                skipped_count += 1
                row = BookRunResult(
                    book_number=book_number,
                    status="skipped",
                    generated=0,
                    quality_passed=0,
                    composited=0,
                    exported=0,
                )
                result_rows.append(row)
                continue

            try:
                row = _run_single_book(
                    book_number=book_number,
                    runtime=runtime,
                    input_dir=input_dir,
                    output_dir=output_dir,
                    model_list=model_list,
                    dry_run=dry_run,
                    variation_count=variation_count,
                    prompt_variant_ids=prompt_variant_ids,
                    prompt_override=config_overrides.get("prompt_override"),
                    use_library=bool(config_overrides.get("use_library", False)),
                    prompt_id=config_overrides.get("prompt_id"),
                    style_anchors=config_overrides.get("style_anchors") or [],
                    all_models=bool(config_overrides.get("all_models", False)),
                    provider=config_overrides.get("provider"),
                    no_resume=bool(config_overrides.get("no_resume", False)),
                )
                result_rows.append(row)
                generated_count += row.generated
                exported_count += row.exported

                if row.status == "success":
                    state.setdefault("completed_books", {})[str(book_number)] = {
                        "completed_at": _utc_now(),
                        "exported_files": row.exported,
                    }
                else:
                    state.setdefault("failed_books", {})[str(book_number)] = {
                        "failed_at": _utc_now(),
                        "error": row.error,
                    }
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Pipeline book failure for %s: %s", book_number, exc)
                row = BookRunResult(
                    book_number=book_number,
                    status="failed",
                    generated=0,
                    quality_passed=0,
                    composited=0,
                    exported=0,
                    error=str(exc),
                )
                result_rows.append(row)
                state.setdefault("failed_books", {})[str(book_number)] = {
                    "failed_at": _utc_now(),
                    "error": str(exc),
                }

        logger.info("Batch %d/%d complete", batch_index, total_batches)

    _save_pipeline_state(state)

    summary = PipelineResult(
        processed_books=len(books),
        succeeded_books=sum(1 for row in result_rows if row.status == "success"),
        failed_books=sum(1 for row in result_rows if row.status == "failed"),
        skipped_books=skipped_count,
        generated_images=generated_count,
        exported_files=exported_count,
        dry_run=dry_run,
        started_at=started_at,
        finished_at=_utc_now(),
        book_results=result_rows,
    )

    _write_summary(summary)
    return summary.to_dict()


def get_pipeline_status(output_dir: Path) -> dict[str, Any]:
    """Get pipeline progress overview."""
    state = _load_pipeline_state()
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
        "state_path": str(PIPELINE_STATE_PATH),
    }


def _run_single_book(
    *,
    book_number: int,
    runtime: config.Config,
    input_dir: Path,
    output_dir: Path,
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
    generated_dir = runtime.tmp_dir / "generated"
    composited_dir = runtime.tmp_dir / "composited"

    active_models = model_list or ([*runtime.all_models] if all_models else [runtime.ai_model])

    prompts_payload = json.loads(runtime.prompts_path.read_text(encoding="utf-8"))
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

    generation_results: list[image_generator.GenerationResult] = []

    if prompt_variant_ids:
        for prompt_variant in prompt_variant_ids:
            source_variant = _find_variant_entry(book_entry, prompt_variant)
            used_prompt = prompt_text or source_variant.get("prompt", "")
            used_negative = negative_prompt or source_variant.get("negative_prompt", "")

            generation_results.extend(
                image_generator.generate_all_models(
                    book_number=book_number,
                    prompt=used_prompt,
                    negative_prompt=used_negative,
                    models=active_models,
                    variants_per_model=1,
                    output_dir=generated_dir,
                    resume=not no_resume,
                    dry_run=dry_run,
                    provider_override=provider,
                )
            )
    else:
        generation_results = image_generator.generate_single_book(
            book_number=book_number,
            prompts_path=runtime.prompts_path,
            output_dir=generated_dir,
            models=active_models,
            variants=variation_count,
            prompt_text=prompt_text,
            negative_prompt=negative_prompt,
            provider_override=provider,
            resume=not no_resume,
            dry_run=dry_run,
        )

    generated_successes = sum(1 for row in generation_results if row.success)

    if dry_run:
        return BookRunResult(
            book_number=book_number,
            status="success",
            generated=generated_successes,
            quality_passed=generated_successes,
            composited=0,
            exported=0,
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

    all_scores = quality_gate.run_quality_gate(
        generated_dir=quality_scope_root,
        prompts_path=runtime.prompts_path,
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
        regions=json.loads((runtime.config_dir / "cover_regions.json").read_text(encoding="utf-8")),
    )

    exported_paths = output_exporter.export_book_variants(
        book_number=book_number,
        composited_root=composited_dir,
        output_root=output_dir,
    )

    return BookRunResult(
        book_number=book_number,
        status="success",
        generated=generated_successes,
        quality_passed=len(passed_scores),
        composited=len(composited_paths),
        exported=len(exported_paths),
    )


def _ensure_prerequisites(*, input_dir: Path) -> None:
    runtime = config.get_config()

    regions_path = runtime.config_dir / "cover_regions.json"
    if not regions_path.exists():
        cover_analyzer.analyze_all_covers(input_dir)

    prompts_path = runtime.prompts_path
    if not prompts_path.exists():
        prompts = prompt_generator.generate_all_prompts(
            catalog_path=runtime.book_catalog_path,
            templates_path=runtime.prompt_templates_path,
        )
        prompt_generator.save_prompts(prompts, prompts_path)

    if not runtime.prompt_library_path.exists():
        PromptLibrary(runtime.prompt_library_path)


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


def _load_pipeline_state() -> dict[str, Any]:
    if not PIPELINE_STATE_PATH.exists():
        return {"completed_books": {}, "failed_books": {}}
    try:
        return json.loads(PIPELINE_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"completed_books": {}, "failed_books": {}}


def _save_pipeline_state(state: dict[str, Any]) -> None:
    PIPELINE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _book_is_complete(book_number: int, output_dir: Path, state: dict[str, Any]) -> bool:
    if str(book_number) not in state.get("completed_books", {}):
        return False

    catalog = json.loads(config.BOOK_CATALOG_PATH.read_text(encoding="utf-8"))
    match = next((row for row in catalog if int(row.get("number", 0)) == int(book_number)), None)
    if not match:
        return False

    folder_name = str(match["folder_name"])
    if folder_name.endswith(" copy"):
        folder_name = folder_name[:-5]

    book_dir = output_dir / folder_name
    return book_dir.exists() and len(list(book_dir.rglob("*.*"))) >= 15


def _write_summary(summary: PipelineResult) -> None:
    payload = summary.to_dict()
    PIPELINE_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_SUMMARY_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

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
        "| Book | Status | Generated | Quality Pass | Composited | Exported |",
        "|---:|---|---:|---:|---:|---:|",
    ]

    for row in summary.book_results:
        lines.append(
            f"| {row.book_number} | {row.status} | {row.generated} | {row.quality_passed} | {row.composited} | {row.exported} |"
        )

    PIPELINE_SUMMARY_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _log_progress(*, processed: int, total: int, state: dict[str, Any], output_dir: Path) -> None:
    completed = len(state.get("completed_books", {}))
    exported_images = len(list(output_dir.rglob("*.jpg"))) if output_dir.exists() else 0
    shown_complete = min(total, max(completed, processed))
    logger.info("Progress: [%d/%d books complete, %d exported jpgs]", shown_complete, total, exported_images)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 4A pipeline orchestrator")
    parser.add_argument("--input-dir", type=Path, default=config.INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)

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

    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")

    args = parser.parse_args()
    runtime = config.get_config()

    if args.status:
        print(json.dumps(get_pipeline_status(args.output_dir), indent=2))
        return 0

    if args.book is not None:
        books = [args.book]
    else:
        books = _parse_books(args.books) or config.get_initial_scope_book_numbers(limit=20)

    variation_count, prompt_variant_ids = _resolve_variant_options(args.variants, args.variant, runtime)

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
        "variation_count": variation_count,
        "prompt_variant_ids": prompt_variant_ids,
        "no_resume": args.no_resume,
    }

    result = run_pipeline(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        config_overrides=overrides,
        book_numbers=books,
        resume=(args.resume and not args.no_resume),
        dry_run=args.dry_run,
    )

    logger.info("Pipeline result: %s", result)
    return 0 if int(result.get("failed_books", 0)) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
