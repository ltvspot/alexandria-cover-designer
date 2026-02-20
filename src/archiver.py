"""Prompt 5 archiver: move non-winning variants to Archive and support undo."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src import config
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SELECTIONS_PATH = config.DATA_DIR / "variant_selections.json"
DEFAULT_ARCHIVE_LOG_PATH = config.DATA_DIR / "archive_log.json"


def archive_non_winners(
    *,
    output_root: Path = config.OUTPUT_DIR,
    selections_path: Path = DEFAULT_SELECTIONS_PATH,
    archive_log_path: Path = DEFAULT_ARCHIVE_LOG_PATH,
) -> dict[str, Any]:
    """Archive all non-winning variants without deleting files."""
    selections = _load_selections(selections_path)
    archive_root = output_root / "Archive"
    archive_root.mkdir(parents=True, exist_ok=True)

    operation_id = str(uuid.uuid4())
    operation = {
        "operation_id": operation_id,
        "timestamp": _utc_now(),
        "moves": [],
    }

    for book_dir in sorted([p for p in output_root.iterdir() if p.is_dir()]):
        if book_dir.name == "Archive":
            continue

        book_number = _parse_book_number(book_dir.name)
        if book_number is None:
            continue

        winner_variant = int(selections.get(str(book_number), selections.get(book_dir.name, 0) or 0))
        if winner_variant <= 0:
            continue

        for variant_dir in sorted([p for p in book_dir.iterdir() if p.is_dir() and p.name.startswith("Variant-")]):
            variant_num = _parse_variant_number(variant_dir.name)
            if variant_num is None or variant_num == winner_variant:
                continue

            target = archive_root / book_dir.name / variant_dir.name
            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(variant_dir), str(target))

            operation["moves"].append(
                {
                    "from": str(variant_dir),
                    "to": str(target),
                    "book_number": book_number,
                    "variant": variant_num,
                }
            )

    _append_archive_log(operation, archive_log_path)

    summary = {
        "operation_id": operation_id,
        "moved_variants": len(operation["moves"]),
        "archive_root": str(archive_root),
    }
    return summary


def undo_archive(
    *,
    output_root: Path = config.OUTPUT_DIR,
    archive_log_path: Path = DEFAULT_ARCHIVE_LOG_PATH,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Undo a previous archive operation (default: latest)."""
    payload = _load_archive_log(archive_log_path)
    operations = payload.get("operations", []) if isinstance(payload, dict) else []
    if not operations:
        return {"restored_variants": 0, "message": "No archive operations found."}

    target_op = None
    if operation_id:
        for op in operations:
            if op.get("operation_id") == operation_id:
                target_op = op
                break
    else:
        target_op = operations[-1]

    if not target_op:
        return {"restored_variants": 0, "message": f"Operation {operation_id} not found."}

    restored = 0
    for move in reversed(target_op.get("moves", [])):
        source = Path(move["to"])
        destination = Path(move["from"])

        if not source.exists():
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)

        shutil.move(str(source), str(destination))
        restored += 1

    return {
        "operation_id": target_op.get("operation_id"),
        "restored_variants": restored,
        "output_root": str(output_root),
    }


def _load_selections(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return {}
    return {}


def _append_archive_log(operation: dict[str, Any], path: Path) -> None:
    payload = _load_archive_log(path)
    operations = payload.get("operations", []) if isinstance(payload, dict) else []
    operations.append(operation)

    output = {
        "updated_at": _utc_now(),
        "operations": operations,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_archive_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"operations": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return {"operations": []}
    return {"operations": []}


def _parse_book_number(name: str) -> int | None:
    prefix = name.split(".", 1)[0].strip()
    try:
        return int(prefix)
    except ValueError:
        return None


def _parse_variant_number(name: str) -> int | None:
    if not name.startswith("Variant-"):
        return None
    try:
        return int(name.split("-", 1)[1])
    except ValueError:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive or restore non-winning variants")
    parser.add_argument("--output-root", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--selections", type=Path, default=DEFAULT_SELECTIONS_PATH)
    parser.add_argument("--archive-log", type=Path, default=DEFAULT_ARCHIVE_LOG_PATH)
    parser.add_argument("--undo", action="store_true")
    parser.add_argument("--operation-id", type=str, default=None)

    args = parser.parse_args()

    if args.undo:
        result = undo_archive(
            output_root=args.output_root,
            archive_log_path=args.archive_log,
            operation_id=args.operation_id,
        )
    else:
        result = archive_non_winners(
            output_root=args.output_root,
            selections_path=args.selections,
            archive_log_path=args.archive_log,
        )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
