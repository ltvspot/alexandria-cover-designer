"""Enhanced Drive synchronization manager with push/pull/bidirectional modes."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import difflib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src import gdrive_sync
except ModuleNotFoundError:  # pragma: no cover
    import gdrive_sync  # type: ignore


def _auth_credentials_path(credentials_path: Path) -> Path | None:
    if os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip():
        return None
    return credentials_path


@dataclass(slots=True)
class SyncSummary:
    mode: str
    direction: str
    uploaded: int = 0
    downloaded: int = 0
    skipped: int = 0
    conflicts: int = 0
    failed: int = 0
    errors: list[dict[str, Any]] | None = None
    changes: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "direction": self.direction,
            "uploaded": int(self.uploaded),
            "downloaded": int(self.downloaded),
            "skipped": int(self.skipped),
            "conflicts": int(self.conflicts),
            "failed": int(self.failed),
            "errors": list(self.errors or []),
            "changes": list(self.changes or []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def _is_local_mirror(drive_folder_id: str) -> bool:
    return str(drive_folder_id or "").startswith("local:")


def _mirror_root(drive_folder_id: str) -> Path:
    return Path(str(drive_folder_id).split("local:", 1)[1]).resolve()


def _drive_root(drive_folder_id: str) -> Path:
    return _mirror_root(drive_folder_id) / "Alexandria Covers"


def _iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([p for p in root.rglob("*") if p.is_file()])


def _safe_resolved_child(root: Path, candidate_rel: str) -> Path | None:
    rel = str(candidate_rel or "").strip().lstrip("/")
    if not rel:
        return None
    if "\x00" in rel:
        return None
    if ".." in rel.replace("\\", "/"):
        return None
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    # Reject symlink traversal and escape attempts when the final path resolves outside root.
    if not str(os.path.realpath(candidate)).startswith(str(root_resolved)):
        return None
    return candidate


def _copy_newer(
    *,
    src: Path,
    dst: Path,
    summary: SyncSummary,
    rel: str,
) -> None:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            src_mtime = src.stat().st_mtime
            dst_mtime = dst.stat().st_mtime
            src_size = src.stat().st_size
            dst_size = dst.stat().st_size
            if abs(src_mtime - dst_mtime) < 1.0 and src_size == dst_size:
                summary.skipped += 1
                summary.changes.append({"file": rel, "status": "skipped_unchanged"})
                return
            if src_mtime < dst_mtime:
                summary.conflicts += 1
                summary.skipped += 1
                summary.changes.append({"file": rel, "status": "conflict_keep_destination"})
                return
            summary.conflicts += 1
            summary.changes.append({"file": rel, "status": "conflict_keep_source"})
        shutil.copy2(src, dst)
        summary.uploaded += 1
        summary.changes.append({"file": rel, "status": "copied"})
    except Exception as exc:
        summary.failed += 1
        summary.errors.append({"file": rel, "error": str(exc)})


def _pending_count(*, src_root: Path, dst_root: Path) -> int:
    pending = 0
    for src_path in _iter_files(src_root):
        rel = src_path.relative_to(src_root)
        dst = dst_root / rel
        if not dst.exists():
            pending += 1
            continue
        if src_path.stat().st_size != dst.stat().st_size or src_path.stat().st_mtime > dst.stat().st_mtime + 1.0:
            pending += 1
    return pending


def push_to_drive(
    *,
    output_root: Path,
    input_root: Path,
    exports_root: Path,
    drive_folder_id: str,
    credentials_path: Path,
    sync_state_path: Path | None = None,
    selected_relative_files: list[str] | None = None,
) -> dict[str, Any]:
    """Push winners/mockups/catalogs/exports to Drive."""
    if not _is_local_mirror(drive_folder_id):
        files: list[Path] | None = None
        if selected_relative_files:
            files = []
            for rel in selected_relative_files:
                candidate = _safe_resolved_child(output_root, str(rel))
                if candidate and candidate.is_file():
                    files.append(candidate)
        payload = gdrive_sync.sync_to_drive(
            local_output_dir=output_root,
            drive_folder_id=drive_folder_id,
            credentials_path=credentials_path,
            incremental=True,
            files=files,
            sync_state_path=sync_state_path,
        )
        return {
            "mode": payload.get("mode", "google_api"),
            "direction": "push",
            "uploaded": int(payload.get("uploaded", 0)),
            "downloaded": 0,
            "skipped": int(payload.get("skipped", 0)),
            "conflicts": 0,
            "failed": int(payload.get("failed", 0)),
            "errors": payload.get("errors", []),
            "changes": payload.get("progress", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    summary = SyncSummary(mode="local_mirror", direction="push", errors=[], changes=[])
    drive_root = _drive_root(drive_folder_id)
    winners_target = drive_root / "Winners"
    mockups_target = drive_root / "Mockups"
    social_target = drive_root / "Social Cards"
    catalogs_target = drive_root / "Catalogs"
    exports_target = drive_root / "Exports"
    for folder in (winners_target, mockups_target, social_target, catalogs_target, exports_target):
        folder.mkdir(parents=True, exist_ok=True)

    if selected_relative_files:
        for rel_token in selected_relative_files:
            rel = str(rel_token or "").strip().lstrip("/")
            src = _safe_resolved_child(output_root, rel)
            if not src:
                continue
            if not src.is_file():
                continue
            dst = winners_target / rel
            _copy_newer(src=src, dst=dst, summary=summary, rel=f"Winners/{rel}")
    else:
        ignored = {"Mockups", "Social", "Archive", "Amazon"}
        for src in _iter_files(output_root):
            try:
                rel = src.relative_to(output_root)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in ignored:
                continue
            _copy_newer(src=src, dst=winners_target / rel, summary=summary, rel=f"Winners/{rel}")

    for src in _iter_files(output_root / "Mockups"):
        rel = src.relative_to(output_root / "Mockups")
        _copy_newer(src=src, dst=mockups_target / rel, summary=summary, rel=f"Mockups/{rel}")

    for src in _iter_files(output_root / "Social"):
        rel = src.relative_to(output_root / "Social")
        _copy_newer(src=src, dst=social_target / rel, summary=summary, rel=f"Social Cards/{rel}")

    for src in sorted(output_root.glob("*.pdf")):
        _copy_newer(src=src, dst=catalogs_target / src.name, summary=summary, rel=f"Catalogs/{src.name}")

    for src in _iter_files(exports_root):
        rel = src.relative_to(exports_root)
        _copy_newer(src=src, dst=exports_target / rel, summary=summary, rel=f"Exports/{rel}")

    # Keep Input Covers mirrored for pull operations.
    for src in _iter_files(input_root):
        rel = src.relative_to(input_root)
        _copy_newer(src=src, dst=(drive_root / "Input Covers" / rel), summary=summary, rel=f"Input Covers/{rel}")
    return summary.to_dict()


def pull_from_drive(
    *,
    input_root: Path,
    drive_folder_id: str,
    credentials_path: Path,
) -> dict[str, Any]:
    """Pull new source covers from Drive Input Covers folder."""
    if not _is_local_mirror(drive_folder_id):
        # Google Drive pull is intentionally conservative in this release.
        return {
            "mode": "google_api",
            "direction": "pull",
            "uploaded": 0,
            "downloaded": 0,
            "skipped": 0,
            "conflicts": 0,
            "failed": 1,
            "errors": [{"error": "Pull is only supported for local mirror drive ids (local:/path)."}],
            "changes": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    summary = SyncSummary(mode="local_mirror", direction="pull", errors=[], changes=[])
    source_root = _drive_root(drive_folder_id) / "Input Covers"
    input_root.mkdir(parents=True, exist_ok=True)

    for src in _iter_files(source_root):
        rel = src.relative_to(source_root)
        dst = input_root / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                src_mtime = src.stat().st_mtime
                dst_mtime = dst.stat().st_mtime
                src_size = src.stat().st_size
                dst_size = dst.stat().st_size
                if abs(src_mtime - dst_mtime) < 1.0 and src_size == dst_size:
                    summary.skipped += 1
                    summary.changes.append({"file": str(rel), "status": "skipped_unchanged"})
                    continue
                if src_mtime < dst_mtime:
                    summary.conflicts += 1
                    summary.skipped += 1
                    summary.changes.append({"file": str(rel), "status": "conflict_keep_local"})
                    continue
                summary.conflicts += 1
                summary.changes.append({"file": str(rel), "status": "conflict_keep_drive"})
            shutil.copy2(src, dst)
            summary.downloaded += 1
            summary.changes.append({"file": str(rel), "status": "copied"})
        except Exception as exc:
            summary.failed += 1
            summary.errors.append({"file": str(rel), "error": str(exc)})

    return summary.to_dict()


def sync_bidirectional(
    *,
    output_root: Path,
    input_root: Path,
    exports_root: Path,
    drive_folder_id: str,
    credentials_path: Path,
    sync_state_path: Path | None = None,
    selected_relative_files: list[str] | None = None,
) -> dict[str, Any]:
    pull_summary = pull_from_drive(input_root=input_root, drive_folder_id=drive_folder_id, credentials_path=credentials_path)
    push_summary = push_to_drive(
        output_root=output_root,
        input_root=input_root,
        exports_root=exports_root,
        drive_folder_id=drive_folder_id,
        credentials_path=credentials_path,
        sync_state_path=sync_state_path,
        selected_relative_files=selected_relative_files,
    )
    return {
        "mode": push_summary.get("mode", pull_summary.get("mode", "unknown")),
        "direction": "bidirectional",
        "pull": pull_summary,
        "push": push_summary,
        "uploaded": int(push_summary.get("uploaded", 0)),
        "downloaded": int(pull_summary.get("downloaded", 0)),
        "skipped": int(push_summary.get("skipped", 0)) + int(pull_summary.get("skipped", 0)),
        "conflicts": int(push_summary.get("conflicts", 0)) + int(pull_summary.get("conflicts", 0)),
        "failed": int(push_summary.get("failed", 0)) + int(pull_summary.get("failed", 0)),
        "errors": list(push_summary.get("errors", [])) + list(pull_summary.get("errors", [])),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_status(
    *,
    output_root: Path,
    input_root: Path,
    exports_root: Path,
    drive_folder_id: str,
    credentials_path: Path,
    last_sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _is_local_mirror(drive_folder_id):
        try:
            api_status = gdrive_sync.get_sync_status(drive_folder_id=drive_folder_id, credentials_path=credentials_path)
        except Exception as exc:
            api_status = {"mode": "unavailable", "error": str(exc)}
        return {
            "mode": "google_api",
            "connection": "connected" if "error" not in api_status else "error",
            "status": api_status,
            "last_sync": last_sync or {},
            "pending_changes": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    drive_root = _drive_root(drive_folder_id)
    pending_pull = _pending_count(src_root=drive_root / "Input Covers", dst_root=input_root)
    pending_push = _pending_count(src_root=output_root, dst_root=drive_root / "Winners")
    pending_exports = _pending_count(src_root=exports_root, dst_root=drive_root / "Exports")
    return {
        "mode": "local_mirror",
        "connection": "connected",
        "drive_root": str(drive_root),
        "last_sync": last_sync or {},
        "pending_changes": {
            "pull_input_covers": int(pending_pull),
            "push_winners": int(pending_push),
            "push_exports": int(pending_exports),
            "total": int(pending_pull + pending_push + pending_exports),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_PDF_SUFFIXES = {".pdf", ".ai"}
_DRIVE_COVER_LIST_CACHE_TTL_SECONDS = max(60, int(os.getenv("DRIVE_COVER_LIST_CACHE_TTL_SECONDS", "3600")))
_DRIVE_COVER_LIST_CACHE: dict[str, tuple[float, list[dict[str, Any]], str]] = {}
_DRIVE_COVER_LIST_CACHE_LOCK = threading.Lock()


def _normalize_title_token(value: str) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"^[0-9]+\s*[\.\-:)]*\s*", "", token)
    token = re.sub(r"\s+", " ", token)
    token = token.replace("&", "and")
    token = re.sub(r"[^a-z0-9 ]+", "", token)
    return token.strip()


def _catalog_maps(catalog_path: Path) -> tuple[dict[int, str], dict[str, int]]:
    if not catalog_path.exists():
        return {}, {}
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    if not isinstance(payload, list):
        return {}, {}

    title_by_book: dict[int, str] = {}
    book_by_title: dict[str, int] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        raw_number = row.get("number")
        number = int(raw_number) if isinstance(raw_number, int) else int(str(raw_number)) if str(raw_number).isdigit() else 0
        if number <= 0:
            continue
        title = str(row.get("title", "")).strip()
        title_by_book[number] = title
        normalized = _normalize_title_token(title)
        if normalized and normalized not in book_by_title:
            book_by_title[normalized] = number
    return title_by_book, book_by_title


def _resolve_book_mapping(*, name: str, title_by_book: dict[int, str], book_by_title: dict[str, int]) -> tuple[int, str]:
    token = str(name or "").strip()
    match = re.match(r"^\s*(\d+)\b", token)
    if match:
        book = int(match.group(1))
        return book, title_by_book.get(book, "")

    base = Path(token).stem
    variants = [
        base,
        base.split(" - ", 1)[0],
        base.split(" — ", 1)[0],
        base.split(" by ", 1)[0],
    ]
    for variant in variants:
        normalized = _normalize_title_token(variant)
        if not normalized:
            continue
        book = book_by_title.get(normalized, 0)
        if book > 0:
            return book, title_by_book.get(book, "")
        # Fallback fuzzy title matching when number-prefix and exact token lookup miss.
        if book_by_title:
            candidates = difflib.get_close_matches(normalized, list(book_by_title.keys()), n=1, cutoff=0.86)
            if candidates:
                fuzzy_book = int(book_by_title.get(candidates[0], 0) or 0)
                if fuzzy_book > 0:
                    return fuzzy_book, title_by_book.get(fuzzy_book, "")
    return 0, ""


def _drive_cover_cache_key(*, drive_folder_id: str, input_folder_id: str, catalog_path: Path) -> str:
    return f"{str(drive_folder_id).strip()}::{str(input_folder_id).strip()}::{str(catalog_path.resolve())}"


def _get_cached_drive_cover_entries(*, cache_key: str) -> tuple[list[dict[str, Any]], str] | None:
    now = time.time()
    with _DRIVE_COVER_LIST_CACHE_LOCK:
        row = _DRIVE_COVER_LIST_CACHE.get(cache_key)
        if row is None:
            return None
        ts, entries, resolved_input_folder_id = row
        if (now - ts) > _DRIVE_COVER_LIST_CACHE_TTL_SECONDS:
            _DRIVE_COVER_LIST_CACHE.pop(cache_key, None)
            return None
        # Return a defensive copy so callers cannot mutate cache state.
        return [dict(item) for item in entries], str(resolved_input_folder_id)


def _set_cached_drive_cover_entries(
    *,
    cache_key: str,
    entries: list[dict[str, Any]],
    resolved_input_folder_id: str,
) -> None:
    with _DRIVE_COVER_LIST_CACHE_LOCK:
        _DRIVE_COVER_LIST_CACHE[cache_key] = (
            time.time(),
            [dict(item) for item in entries if isinstance(item, dict)],
            str(resolved_input_folder_id or ""),
        )


def clear_drive_cover_cache() -> None:
    with _DRIVE_COVER_LIST_CACHE_LOCK:
        _DRIVE_COVER_LIST_CACHE.clear()


def _cached_drive_cover_entries(
    *,
    service: Any,
    drive_folder_id: str,
    input_folder_id: str,
    title_by_book: dict[int, str],
    book_by_title: dict[str, int],
    catalog_path: Path,
) -> tuple[list[dict[str, Any]], str]:
    cache_key = _drive_cover_cache_key(
        drive_folder_id=drive_folder_id,
        input_folder_id=input_folder_id,
        catalog_path=catalog_path,
    )
    cached = _get_cached_drive_cover_entries(cache_key=cache_key)
    if cached is not None:
        return cached
    entries, resolved_input_folder_id = _iter_drive_cover_entries(
        service=service,
        drive_folder_id=drive_folder_id,
        input_folder_id=input_folder_id,
        title_by_book=title_by_book,
        book_by_title=book_by_title,
    )
    _set_cached_drive_cover_entries(
        cache_key=cache_key,
        entries=entries,
        resolved_input_folder_id=resolved_input_folder_id,
    )
    return [dict(item) for item in entries], str(resolved_input_folder_id)


def _entry_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    book = int(row.get("book_number", 0) or 0)
    if book > 0:
        return (0, book, str(row.get("name", "")).lower())
    return (1, 10**9, str(row.get("name", "")).lower())


def _iter_local_cover_entries(*, root: Path, title_by_book: dict[int, str], book_by_title: dict[str, int]) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir():
            book, title = _resolve_book_mapping(name=child.name, title_by_book=title_by_book, book_by_title=book_by_title)
            rows.append(
                {
                    "id": f"local:{child.name}",
                    "name": child.name,
                    "kind": "folder",
                    "book_number": book,
                    "title": title,
                    "source": "local_mirror",
                    "relative_path": str(child.relative_to(root)),
                    "mime_type": "application/vnd.folder",
                }
            )
            continue
        if not child.is_file() or child.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        book, title = _resolve_book_mapping(name=child.name, title_by_book=title_by_book, book_by_title=book_by_title)
        rows.append(
            {
                "id": f"local-file:{child.name}",
                "name": child.name,
                "kind": "file",
                "book_number": book,
                "title": title,
                "source": "local_mirror",
                "relative_path": str(child.relative_to(root)),
                "mime_type": f"image/{child.suffix.lstrip('.').lower()}",
                "size": int(child.stat().st_size),
                "modified_time": datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    rows.sort(key=_entry_sort_key)
    return rows


def _drive_child_folder_id(*, service: Any, parent_id: str, folder_name: str) -> str:
    escaped_name = str(folder_name).replace("'", "\\'")
    query = (
        f"name='{escaped_name}' and "
        f"'{parent_id}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    response = service.files().list(q=query, fields="files(id,name)", pageSize=1).execute()
    files = response.get("files", [])
    if isinstance(files, list) and files:
        return str(files[0].get("id", "")).strip()
    return ""


def _drive_children(*, service: Any, parent_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    fields = "nextPageToken,files(id,name,mimeType,modifiedTime,size,webViewLink,thumbnailLink,parents)"
    while True:
        request = service.files().list(
            q=f"'{parent_id}' in parents and trashed=false",
            fields=fields,
            pageSize=1000,
            pageToken=page_token,
            orderBy="name_natural",
        )
        response = request.execute()
        files = response.get("files", [])
        if isinstance(files, list):
            rows.extend([row for row in files if isinstance(row, dict)])
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return rows


def _iter_drive_cover_entries(
    *,
    service: Any,
    drive_folder_id: str,
    input_folder_id: str,
    title_by_book: dict[int, str],
    book_by_title: dict[str, int],
) -> tuple[list[dict[str, Any]], str]:
    parent_id = str(input_folder_id or "").strip()
    if not parent_id:
        parent_id = _drive_child_folder_id(service=service, parent_id=drive_folder_id, folder_name="Input Covers")
    if not parent_id:
        parent_id = drive_folder_id

    entries: list[dict[str, Any]] = []
    for row in _drive_children(service=service, parent_id=parent_id):
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        mime_type = str(row.get("mimeType", "")).strip()
        is_folder = mime_type == "application/vnd.google-apps.folder"
        is_image = mime_type.startswith("image/")
        if not is_folder and not is_image:
            continue
        book, title = _resolve_book_mapping(name=name, title_by_book=title_by_book, book_by_title=book_by_title)
        entries.append(
            {
                "id": str(row.get("id", "")).strip() or f"drive:{name}",
                "name": name,
                "kind": "folder" if is_folder else "file",
                "book_number": book,
                "title": title,
                "source": "google_drive",
                "mime_type": mime_type,
                "size": int(row.get("size", 0) or 0) if str(row.get("size", "")).strip().isdigit() else 0,
                "modified_time": str(row.get("modifiedTime", "")).strip(),
                "web_view_link": str(row.get("webViewLink", "")).strip(),
                "thumbnail_link": str(row.get("thumbnailLink", "")).strip(),
                "parents": list(row.get("parents", [])) if isinstance(row.get("parents"), list) else [],
            }
        )
    entries.sort(key=_entry_sort_key)
    return entries, parent_id


def list_input_covers(
    *,
    drive_folder_id: str,
    input_folder_id: str,
    credentials_path: Path,
    catalog_path: Path,
    limit: int = 500,
) -> dict[str, Any]:
    title_by_book, book_by_title = _catalog_maps(catalog_path)
    max_rows = max(1, int(limit or 500))

    if _is_local_mirror(drive_folder_id):
        drive_root = _drive_root(drive_folder_id)
        input_root = drive_root / "Input Covers"
        if not input_root.exists():
            input_root = _mirror_root(drive_folder_id) / "Input Covers"
        entries = _iter_local_cover_entries(root=input_root, title_by_book=title_by_book, book_by_title=book_by_title)
        trimmed = entries[:max_rows]
        return {
            "mode": "local_mirror",
            "drive_folder_id": str(drive_folder_id),
            "input_folder_id": str(input_root),
            "covers": trimmed,
            "count": len(trimmed),
            "total": len(entries),
        }

    try:
        service = gdrive_sync.authenticate(_auth_credentials_path(credentials_path))
        entries, resolved_input_folder_id = _cached_drive_cover_entries(
            service=service,
            drive_folder_id=str(drive_folder_id),
            input_folder_id=str(input_folder_id or ""),
            title_by_book=title_by_book,
            book_by_title=book_by_title,
            catalog_path=catalog_path,
        )
        trimmed = entries[:max_rows]
        return {
            "mode": "google_api",
            "drive_folder_id": str(drive_folder_id),
            "input_folder_id": resolved_input_folder_id,
            "covers": trimmed,
            "count": len(trimmed),
            "total": len(entries),
        }
    except Exception as exc:
        return {
            "mode": "unavailable",
            "drive_folder_id": str(drive_folder_id),
            "input_folder_id": str(input_folder_id or ""),
            "covers": [],
            "count": 0,
            "total": 0,
            "error": str(exc),
        }


def _catalog_folder_name_for_book(*, catalog_path: Path, book_number: int) -> str:
    if not catalog_path.exists():
        return ""
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, list):
        return ""
    for row in payload:
        if not isinstance(row, dict):
            continue
        raw_number = row.get("number")
        number = int(raw_number) if isinstance(raw_number, int) else int(str(raw_number)) if str(raw_number).isdigit() else 0
        if number != int(book_number):
            continue
        return str(row.get("folder_name", "")).strip()
    return ""


def _pick_drive_image_from_folder(*, service: Any, folder_id: str) -> dict[str, Any] | None:
    for row in _drive_children(service=service, parent_id=folder_id):
        mime_type = str(row.get("mimeType", "")).strip().lower()
        if mime_type.startswith("image/"):
            return row
    return None


def _pick_drive_pdf_from_folder(*, service: Any, folder_id: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for row in _drive_children(service=service, parent_id=folder_id):
        name = str(row.get("name", "")).strip().lower()
        suffix = Path(name).suffix.lower()
        if suffix not in _PDF_SUFFIXES:
            continue
        candidates.append(row)
    if not candidates:
        return None
    pdfs = [row for row in candidates if Path(str(row.get("name", ""))).suffix.lower() == ".pdf"]
    if pdfs:
        return pdfs[0]
    return candidates[0]


def _download_drive_file_bytes(*, service: Any, file_id: str) -> bytes:
    media = service.files().get_media(fileId=file_id).execute()
    if isinstance(media, bytes):
        return media
    if hasattr(media, "read"):
        return media.read()  # type: ignore[return-value]
    raise RuntimeError(f"Unexpected Drive media payload for file {file_id}")


def ensure_local_input_cover(
    *,
    drive_folder_id: str,
    input_folder_id: str,
    credentials_path: Path,
    catalog_path: Path,
    input_root: Path,
    book_number: int,
    selected_cover_id: str = "",
) -> dict[str, Any]:
    """Ensure a local source cover exists; download JPG + PDF companion when available."""
    folder_name = _catalog_folder_name_for_book(catalog_path=catalog_path, book_number=book_number)
    if not folder_name:
        return {
            "ok": False,
            "downloaded": False,
            "error": f"Book {book_number} not found in catalog",
        }

    target_folder = input_root / folder_name
    target_folder.mkdir(parents=True, exist_ok=True)
    existing = sorted([path for path in target_folder.iterdir() if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES])
    existing_pdfs = sorted([path for path in target_folder.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"])
    selected_id = str(selected_cover_id or "").strip()
    if existing and not selected_id:
        return {
            "ok": True,
            "downloaded": False,
            "source": "local",
            "path": str(existing[0]),
            "pdf_path": str(existing_pdfs[0]) if existing_pdfs else "",
            "folder_name": folder_name,
        }

    if _is_local_mirror(drive_folder_id):
        source_root = _drive_root(drive_folder_id) / "Input Covers"
        if not source_root.exists():
            source_root = _mirror_root(drive_folder_id) / "Input Covers"
        if source_root.exists():
            candidates: list[Path] = []
            candidate_folders: list[Path] = []
            for row in _iter_local_cover_entries(root=source_root, title_by_book={}, book_by_title={}):
                if int(row.get("book_number", 0) or 0) != int(book_number):
                    continue
                rel = str(row.get("relative_path", "")).strip()
                src = source_root / rel
                if src.exists() and src.is_file():
                    candidates.append(src)
                elif src.exists() and src.is_dir():
                    candidate_folders.append(src)
            if not candidates and candidate_folders:
                for folder in candidate_folders:
                    for file_path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                        if file_path.is_file() and file_path.suffix.lower() in _IMAGE_SUFFIXES:
                            candidates.append(file_path)
            if candidates:
                source = candidates[0]
                suffix = source.suffix.lower() or ".jpg"
                destination = target_folder / f"cover_from_drive{suffix}"
                shutil.copy2(source, destination)
                copied_pdf = ""
                for sibling in sorted(source.parent.iterdir(), key=lambda p: p.name.lower()):
                    if not sibling.is_file():
                        continue
                    if sibling.suffix.lower() not in _PDF_SUFFIXES:
                        continue
                    pdf_dest = target_folder / "cover_from_drive.pdf"
                    shutil.copy2(sibling, pdf_dest)
                    copied_pdf = str(pdf_dest)
                    break
                return {
                    "ok": True,
                    "downloaded": True,
                    "source": "local_mirror",
                    "path": str(destination),
                    "pdf_path": copied_pdf,
                    "folder_name": folder_name,
                }
        return {
            "ok": False,
            "downloaded": False,
            "error": f"No input cover found in local mirror for book {book_number}",
        }

    service = gdrive_sync.authenticate(_auth_credentials_path(credentials_path))
    title_by_book, book_by_title = _catalog_maps(catalog_path)
    entries, _resolved_input_folder_id = _cached_drive_cover_entries(
        service=service,
        drive_folder_id=str(drive_folder_id),
        input_folder_id=str(input_folder_id or ""),
        title_by_book=title_by_book,
        book_by_title=book_by_title,
        catalog_path=catalog_path,
    )
    candidate_entry: dict[str, Any] | None = None
    if selected_id:
        candidate_entry = next((row for row in entries if str(row.get("id", "")).strip() == selected_id), None)
        if candidate_entry is None:
            return {
                "ok": False,
                "downloaded": False,
                "error": f"Selected Drive cover '{selected_id}' was not found",
            }
        mapped_book = int(candidate_entry.get("book_number", 0) or 0)
        if mapped_book != int(book_number):
            return {
                "ok": False,
                "downloaded": False,
                "error": (
                    f"Selected Drive cover maps to book {mapped_book or 'unknown'}, "
                    f"but requested book is {book_number}"
                ),
            }
    if candidate_entry is None:
        candidate_entry = next((row for row in entries if int(row.get("book_number", 0) or 0) == int(book_number)), None)
    if candidate_entry is None:
        book_title = str(title_by_book.get(int(book_number), "")).strip()
        title_suffix = f" '{book_title}'" if book_title else ""
        return {
            "ok": False,
            "downloaded": False,
            "error": (
                f"No cover found in Google Drive for book #{int(book_number)}{title_suffix}. "
                "Upload covers to the Drive folder first."
            ),
        }

    image_file: dict[str, Any] | None = None
    pdf_file: dict[str, Any] | None = None
    if str(candidate_entry.get("kind", "")).strip().lower() == "file":
        image_file = candidate_entry
        parent_ids = candidate_entry.get("parents", [])
        parent_id = ""
        if isinstance(parent_ids, list) and parent_ids:
            parent_id = str(parent_ids[0] or "").strip()
        file_id_token = str(candidate_entry.get("id", "")).strip()
        if not parent_id and file_id_token:
            try:
                row = service.files().get(fileId=file_id_token, fields="parents").execute()
                parent_values = row.get("parents", []) if isinstance(row, dict) else []
                if isinstance(parent_values, list) and parent_values:
                    parent_id = str(parent_values[0] or "").strip()
            except Exception:
                parent_id = ""
        if parent_id:
            pdf_file = _pick_drive_pdf_from_folder(service=service, folder_id=parent_id)
    else:
        folder_id = str(candidate_entry.get("id", "")).strip()
        if folder_id:
            image_file = _pick_drive_image_from_folder(service=service, folder_id=folder_id)
            pdf_file = _pick_drive_pdf_from_folder(service=service, folder_id=folder_id)
    if not image_file:
        return {
            "ok": False,
            "downloaded": False,
            "error": f"No image file found in selected Drive cover for book {book_number}",
        }

    file_id = str(image_file.get("id", "")).strip()
    file_name = str(image_file.get("name", "")).strip() or f"book_{book_number}.jpg"
    if not file_id:
        return {
            "ok": False,
            "downloaded": False,
            "error": f"Drive image id missing for book {book_number}",
        }

    content = _download_drive_file_bytes(service=service, file_id=file_id)

    suffix = Path(file_name).suffix.lower()
    if suffix not in _IMAGE_SUFFIXES:
        suffix = ".jpg"
    destination = target_folder / f"cover_from_drive{suffix}"
    destination.write_bytes(content)
    pdf_destination = ""
    if isinstance(pdf_file, dict):
        pdf_id = str(pdf_file.get("id", "")).strip()
        if pdf_id:
            try:
                pdf_bytes = _download_drive_file_bytes(service=service, file_id=pdf_id)
                resolved_pdf = target_folder / "cover_from_drive.pdf"
                resolved_pdf.write_bytes(pdf_bytes)
                pdf_destination = str(resolved_pdf)
            except Exception:
                pdf_destination = ""
    return {
        "ok": True,
        "downloaded": True,
        "source": "google_drive",
        "path": str(destination),
        "pdf_path": pdf_destination,
        "folder_name": folder_name,
        "drive_file_id": file_id,
    }
