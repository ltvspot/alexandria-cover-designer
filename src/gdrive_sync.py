"""Prompt 4B Google Drive sync with API mode and local fallback mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import mimetypes
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from google.oauth2 import service_account  # type: ignore
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    from googleapiclient.discovery import build  # type: ignore
    from googleapiclient.http import MediaFileUpload  # type: ignore

    GOOGLE_API_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    GOOGLE_API_AVAILABLE = False

try:
    from src import config
    from src.logger import get_logger
    from src import safe_json
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    from logger import get_logger  # type: ignore
    import safe_json  # type: ignore

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
SYNC_STATE_PATH = config.gdrive_sync_state_path()
ProgressCallback = Callable[[dict[str, Any]], None]


def authenticate(credentials_path: Path | None = None):
    """Authenticate to Google Drive API using service account or OAuth client JSON."""
    if not GOOGLE_API_AVAILABLE:
        raise RuntimeError(
            "Google Drive dependencies are not installed. Install: "
            "google-api-python-client, google-auth-oauthlib, google-auth-httplib2"
        )

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    if creds_json:
        try:
            info = json.loads(creds_json)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse GOOGLE_CREDENTIALS_JSON: %s", exc)
            raise ValueError("GOOGLE_CREDENTIALS_JSON is not valid JSON") from exc
        if not isinstance(info, dict):
            raise ValueError("GOOGLE_CREDENTIALS_JSON must be a JSON object")
        if info.get("type") != "service_account":
            raise ValueError("GOOGLE_CREDENTIALS_JSON must be a service account key")
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build("drive", "v3", credentials=creds)

    resolved_path = Path(credentials_path) if credentials_path is not None else Path()
    if credentials_path is None:
        raise FileNotFoundError(
            "No Google credentials found. Set GOOGLE_CREDENTIALS_JSON env var "
            "or provide GOOGLE_CREDENTIALS_PATH."
        )

    if not resolved_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {resolved_path}")

    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if payload.get("type") == "service_account":
        creds = service_account.Credentials.from_service_account_file(str(resolved_path), scopes=SCOPES)
        return build("drive", "v3", credentials=creds)

    # OAuth desktop flow fallback.
    flow = InstalledAppFlow.from_client_secrets_file(str(resolved_path), SCOPES)
    creds = flow.run_local_server(port=0)
    return build("drive", "v3", credentials=creds)


def credential_details(credentials_path: Path | None = None) -> dict[str, Any]:
    """Return non-secret credential metadata for diagnostics."""
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    payload: dict[str, Any] | None = None
    source = "missing"
    resolved_path = Path(credentials_path) if credentials_path is not None else None

    if creds_json:
        try:
            parsed = json.loads(creds_json)
        except json.JSONDecodeError as exc:
            return {
                "source": "env",
                "loaded": False,
                "error": f"GOOGLE_CREDENTIALS_JSON is not valid JSON: {exc}",
                "path": "",
                "type": "",
                "client_email": "",
                "project_id": "",
                "client_id": "",
            }
        if not isinstance(parsed, dict):
            return {
                "source": "env",
                "loaded": False,
                "error": "GOOGLE_CREDENTIALS_JSON must be a JSON object",
                "path": "",
                "type": "",
                "client_email": "",
                "project_id": "",
                "client_id": "",
            }
        payload = parsed
        source = "env"
    elif resolved_path is not None and resolved_path.exists():
        try:
            parsed = json.loads(resolved_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "source": "file",
                "loaded": False,
                "error": str(exc),
                "path": str(resolved_path),
                "type": "",
                "client_email": "",
                "project_id": "",
                "client_id": "",
            }
        if not isinstance(parsed, dict):
            return {
                "source": "file",
                "loaded": False,
                "error": "Credentials file must contain a JSON object",
                "path": str(resolved_path),
                "type": "",
                "client_email": "",
                "project_id": "",
                "client_id": "",
            }
        payload = parsed
        source = "file"

    if not isinstance(payload, dict):
        return {
            "source": source,
            "loaded": False,
            "error": "No Google credentials found",
            "path": str(resolved_path) if resolved_path is not None else "",
            "type": "",
            "client_email": "",
            "project_id": "",
            "client_id": "",
        }

    return {
        "source": source,
        "loaded": True,
        "error": "",
        "path": str(resolved_path) if (resolved_path is not None and source == "file") else "",
        "type": str(payload.get("type", "") or ""),
        "client_email": str(payload.get("client_email", "") or ""),
        "project_id": str(payload.get("project_id", "") or ""),
        "client_id": str(payload.get("client_id", "") or ""),
    }


def sync_to_drive(
    local_output_dir: Path,
    drive_folder_id: str,
    credentials_path: Path,
    incremental: bool = True,
    *,
    files: list[Path] | None = None,
    sync_state_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Sync local output structure to Google Drive (or local fallback mirror)."""
    local_output_dir = local_output_dir.resolve()

    if drive_folder_id.startswith("local:"):
        mirror_dir = Path(drive_folder_id.split("local:", 1)[1])
        return _sync_to_local_mirror(
            local_output_dir,
            mirror_dir,
            incremental,
            files=files,
            progress_callback=progress_callback,
        )

    service = authenticate(credentials_path)
    state_path = sync_state_path or SYNC_STATE_PATH
    state = _load_sync_state(state_path)

    if not local_output_dir.exists():
        raise FileNotFoundError(f"Local output directory not found: {local_output_dir}")

    folder_cache: dict[tuple[str, str], str] = {}
    file_list = _resolve_files(local_output_dir, files)
    summary = _new_summary(mode="google_api", total_files=len(file_list))
    total = len(file_list)
    chunk_size = max(1, int(os.getenv("GDRIVE_SYNC_CHUNK_SIZE", "50")))
    chunk_sleep_seconds = max(0.0, float(os.getenv("GDRIVE_SYNC_CHUNK_SLEEP_SECONDS", "2")))

    for chunk_start in range(0, total, chunk_size):
        chunk = file_list[chunk_start : chunk_start + chunk_size]
        for offset, file_path in enumerate(chunk):
            index = chunk_start + offset + 1
            rel = file_path.relative_to(local_output_dir)
            outcome = "failed"
            try:
                parent_id = drive_folder_id
                for part in rel.parts[:-1]:
                    parent_id = _ensure_remote_folder(
                        service=service,
                        parent_id=parent_id,
                        folder_name=part,
                        cache=folder_cache,
                    )

                logger.info("[%d/%d] Uploading %s", index, total, rel)
                outcome = _upload_file(
                    service=service,
                    parent_id=parent_id,
                    local_path=file_path,
                    incremental=incremental,
                    state=state,
                )
                summary[outcome] += 1
            except Exception as exc:  # pragma: no cover - defensive
                summary["failed"] += 1
                summary["errors"].append({"file": str(rel), "error": str(exc)})
            finally:
                event = {
                    "index": index,
                    "total": total,
                    "file": str(rel),
                    "status": outcome,
                }
                summary["progress"].append(event)
                if progress_callback:
                    progress_callback(event)
        if chunk_start + chunk_size < total and chunk_sleep_seconds > 0:
            time.sleep(chunk_sleep_seconds)

    _save_sync_state(state, state_path)
    return summary


def sync_selected_to_drive(
    local_output_dir: Path,
    relative_paths: Iterable[str],
    drive_folder_id: str,
    credentials_path: Path,
    incremental: bool = True,
    *,
    sync_state_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Sync a selected subset of files from local_output_dir while preserving folders."""
    files: list[Path] = []
    for rel in relative_paths:
        token = str(rel).strip().lstrip("/")
        if not token:
            continue
        candidate = (local_output_dir / token).resolve()
        if candidate.exists() and candidate.is_file():
            files.append(candidate)

    return sync_to_drive(
        local_output_dir=local_output_dir,
        drive_folder_id=drive_folder_id,
        credentials_path=credentials_path,
        incremental=incremental,
        files=files,
        sync_state_path=sync_state_path,
        progress_callback=progress_callback,
    )


def get_sync_status(drive_folder_id: str, credentials_path: Path) -> dict[str, Any]:
    """Get sync status for Google Drive or local mirror fallback."""
    if drive_folder_id.startswith("local:"):
        mirror_dir = Path(drive_folder_id.split("local:", 1)[1])
        return {
            "mode": "local_mirror",
            "mirror_dir": str(mirror_dir),
            "file_count": len(list(mirror_dir.rglob("*"))) if mirror_dir.exists() else 0,
        }

    service = authenticate(credentials_path)
    response = service.files().list(
        q=f"'{drive_folder_id}' in parents and trashed=false",
        fields="files(id, name, mimeType)",
        pageSize=1000,
    ).execute()

    files = response.get("files", [])
    return {
        "mode": "google_api",
        "drive_folder_id": drive_folder_id,
        "item_count": len(files),
        "folders": sum(1 for row in files if row.get("mimeType") == "application/vnd.google-apps.folder"),
        "files": sum(1 for row in files if row.get("mimeType") != "application/vnd.google-apps.folder"),
    }


def _sync_to_local_mirror(
    local_output_dir: Path,
    mirror_dir: Path,
    incremental: bool,
    *,
    files: list[Path] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    mirror_dir.mkdir(parents=True, exist_ok=True)
    file_list = _resolve_files(local_output_dir, files)
    summary = _new_summary(mode="local_mirror", total_files=len(file_list))
    total = len(file_list)

    for idx, source in enumerate(file_list, start=1):
        rel = source.relative_to(local_output_dir)
        target = mirror_dir / rel
        status = "failed"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            logger.info("[%d/%d] Mirroring %s", idx, total, rel)

            if incremental and target.exists() and target.stat().st_size == source.stat().st_size:
                summary["skipped"] += 1
                status = "skipped"
                continue

            shutil.copy2(source, target)
            summary["uploaded"] += 1
            status = "uploaded"
        except Exception as exc:  # pragma: no cover - defensive
            summary["failed"] += 1
            summary["errors"].append({"file": str(rel), "error": str(exc)})
        finally:
            event = {
                "index": idx,
                "total": total,
                "file": str(rel),
                "status": status,
            }
            summary["progress"].append(event)
            if progress_callback:
                progress_callback(event)

    return summary


def _new_summary(*, mode: str, total_files: int) -> dict[str, Any]:
    return {
        "mode": mode,
        "total_files": int(total_files),
        "uploaded": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "progress": [],
    }


def _resolve_files(local_output_dir: Path, files: list[Path] | None) -> list[Path]:
    if files is None:
        return sorted([path for path in local_output_dir.rglob("*") if path.is_file()])

    resolved: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        candidate = path if path.is_absolute() else (local_output_dir / path)
        candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            candidate.relative_to(local_output_dir.resolve())
        except ValueError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        resolved.append(candidate)
    return sorted(resolved)


def _ensure_remote_folder(
    *,
    service,
    parent_id: str,
    folder_name: str,
    cache: dict[tuple[str, str], str],
) -> str:
    key = (parent_id, folder_name)
    if key in cache:
        return cache[key]

    q = (
        f"name='{_escape_query(folder_name)}' and '{parent_id}' in parents "
        "and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    resp = service.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
    files = resp.get("files", [])
    if files:
        folder_id = files[0]["id"]
        cache[key] = folder_id
        return folder_id

    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(body=metadata, fields="id").execute()
    folder_id = created["id"]
    cache[key] = folder_id
    return folder_id


def _upload_file(*, service, parent_id: str, local_path: Path, incremental: bool, state: dict[str, Any]) -> str:
    rel_key = str(local_path)
    mime_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    local_size = int(local_path.stat().st_size)
    local_sig = _file_signature(local_path)

    q = (
        f"name='{_escape_query(local_path.name)}' and '{parent_id}' in parents "
        "and trashed=false"
    )
    existing = service.files().list(q=q, fields="files(id, name, size, md5Checksum)", pageSize=1).execute().get("files", [])

    if existing:
        remote = existing[0]
        remote_size = str(remote.get("size", "")).strip()
        remote_md5 = str(remote.get("md5Checksum", "")).strip().lower()
        if incremental and str(local_size) == remote_size:
            if remote_md5:
                local_md5 = _file_md5(local_path)
                if local_md5 == remote_md5:
                    state[rel_key] = {
                        "id": remote["id"],
                        "size": local_size,
                        "signature": local_sig,
                        "md5": local_md5,
                    }
                    return "skipped"
            else:
                state[rel_key] = {
                    "id": remote["id"],
                    "size": local_size,
                    "signature": local_sig,
                }
                return "skipped"
        if incremental and str(local_size) == remote_size:
            return "skipped"

        media = _media_file_upload(local_path=local_path, mime_type=mime_type)
        service.files().update(fileId=remote["id"], media_body=media).execute()
        state[rel_key] = {
            "id": remote["id"],
            "size": local_size,
            "signature": local_sig,
            "md5": _file_md5(local_path),
        }
        return "uploaded"

    metadata = {"name": local_path.name, "parents": [parent_id]}
    media = _media_file_upload(local_path=local_path, mime_type=mime_type)
    created = service.files().create(body=metadata, media_body=media, fields="id").execute()
    state[rel_key] = {
        "id": created["id"],
        "size": local_size,
        "signature": local_sig,
        "md5": _file_md5(local_path),
    }
    return "uploaded"


def _escape_query(value: str) -> str:
    return value.replace("'", "\\'")


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _file_signature(path: Path) -> str:
    stat = path.stat()
    return f"{int(stat.st_size)}:{int(stat.st_mtime_ns)}"


def _media_file_upload(*, local_path: Path, mime_type: str):
    try:
        return MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True, chunksize=5 * 1024 * 1024)
    except TypeError:  # test doubles may not accept chunksize
        return MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)


def _load_sync_state(path: Path | None = None) -> dict[str, Any]:
    target_path = path or SYNC_STATE_PATH
    payload = safe_json.load_json(target_path, {})
    return payload if isinstance(payload, dict) else {}


def _save_sync_state(state: dict[str, Any], path: Path | None = None) -> None:
    target_path = path or SYNC_STATE_PATH
    safe_json.atomic_write_json(target_path, state)


def _book_number_from_folder(name: str) -> int | None:
    token = name.split(".", 1)[0].strip()
    if token.isdigit():
        return int(token)
    return None


def _load_winner_map(path: Path) -> dict[int, int]:
    payload = safe_json.load_json(path, {})
    raw = payload.get("selections", payload) if isinstance(payload, dict) else {}

    winners: dict[int, int] = {}
    if not isinstance(raw, dict):
        return winners

    for key, value in raw.items():
        try:
            book = int(str(key))
        except ValueError:
            continue
        if isinstance(value, dict):
            winner = int(value.get("winner", 0) or 0)
        else:
            winner = int(value or 0)
        if winner > 0:
            winners[book] = winner
    return winners


def _winner_files_for_book(book_dir: Path, winner_variant: int) -> list[Path]:
    variant_dir = book_dir / f"Variant-{winner_variant}"
    if variant_dir.exists():
        return sorted([p for p in variant_dir.glob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".pdf", ".ai"}])
    return sorted([p for p in book_dir.glob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".pdf", ".ai"}])


def _build_winners_sync_tree(*, output_dir: Path, selections_path: Path) -> tuple[Path, dict[str, Any]]:
    winners = _load_winner_map(selections_path)
    staging_root = Path(tempfile.mkdtemp(prefix="winners_sync_"))

    staged_books = 0
    staged_files = 0
    skipped_books: list[int] = []

    for book_dir in sorted([p for p in output_dir.iterdir() if p.is_dir() and p.name != "Archive"]):
        book = _book_number_from_folder(book_dir.name)
        if book is None:
            continue
        winner_variant = winners.get(book)
        if not winner_variant:
            continue

        files = _winner_files_for_book(book_dir, winner_variant)
        if not files:
            skipped_books.append(book)
            continue

        target_dir = staging_root / book_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in files:
            shutil.copy2(source, target_dir / source.name)
            staged_files += 1
        staged_books += 1

    metadata = {
        "staged_books": staged_books,
        "staged_files": staged_files,
        "skipped_books": skipped_books,
        "selection_file": str(selections_path),
    }
    return staging_root, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 4B Google Drive sync")
    parser.add_argument("--catalog", type=str, default=config.DEFAULT_CATALOG_ID, help="Catalog id from config/catalogs.json")
    parser.add_argument("--local-output-dir", type=Path, default=None)
    parser.add_argument("--input", type=Path, default=None, help="Alias for --local-output-dir")
    parser.add_argument("--drive-folder-id", type=str, default=None)
    parser.add_argument(
        "--credentials-path",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--selected-files",
        type=Path,
        default=None,
        help="Optional JSON file containing relative file paths to sync (subset mode).",
    )
    parser.add_argument("--winners-only", action="store_true", help="Sync only winner files (flattened, no Variant-N dirs).")
    parser.add_argument(
        "--selections",
        type=Path,
        default=None,
        help="Winner selections JSON used with --winners-only.",
    )
    parser.add_argument("--no-incremental", action="store_true")
    parser.add_argument("--status", action="store_true")

    args = parser.parse_args()
    try:
        runtime = config.get_config(args.catalog)
    except TypeError:  # pragma: no cover - compatibility for patched tests/helpers
        runtime = config.get_config()  # type: ignore[call-arg]

    runtime_catalog = str(getattr(runtime, "catalog_id", args.catalog) or config.DEFAULT_CATALOG_ID)
    runtime_data_dir = Path(getattr(runtime, "data_dir", config.DATA_DIR))
    sync_state_path = config.gdrive_sync_state_path(catalog_id=runtime_catalog, data_dir=runtime_data_dir)
    selections_path = args.selections or config.winner_selections_path(catalog_id=runtime_catalog, data_dir=runtime_data_dir)

    local_output_dir = args.input or args.local_output_dir or Path(getattr(runtime, "output_dir", config.OUTPUT_DIR))
    drive_folder_id = args.drive_folder_id or str(getattr(runtime, "gdrive_output_folder_id", config.GDRIVE_OUTPUT_FOLDER_ID))

    runtime_credentials = str(getattr(runtime, "google_credentials_path", "") or "")
    runtime_config_dir = Path(getattr(runtime, "config_dir", config.CONFIG_DIR))
    credentials_path = (
        args.credentials_path
        or (Path(runtime_credentials) if runtime_credentials else (runtime_config_dir / "credentials.json"))
    )

    try:
        if args.status:
            status = get_sync_status(drive_folder_id, credentials_path)
            logger.info("Sync status: %s", json.dumps(status, ensure_ascii=False))
            return 0

        selected: list[Path] | None = None
        if args.selected_files:
            payload = json.loads(args.selected_files.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                selected = [Path(str(row)) for row in payload if str(row).strip()]

        staging_root = None
        winners_meta: dict[str, Any] | None = None
        sync_root = local_output_dir
        sync_files = selected

        if args.winners_only:
            if not selections_path.exists():
                raise FileNotFoundError(f"Winner selections not found: {selections_path}")
            staging_root, winners_meta = _build_winners_sync_tree(output_dir=local_output_dir, selections_path=selections_path)
            sync_root = staging_root
            sync_files = None

        summary = sync_to_drive(
            local_output_dir=sync_root,
            drive_folder_id=drive_folder_id,
            credentials_path=credentials_path,
            incremental=not args.no_incremental,
            files=sync_files,
            sync_state_path=sync_state_path,
        )

        if staging_root is not None:
            shutil.rmtree(staging_root, ignore_errors=True)
            summary["winners_only"] = True
            summary["winners_meta"] = winners_meta or {}

        logger.info("Sync summary: %s", json.dumps(summary, ensure_ascii=False))
        return 0 if summary.get("failed", 0) == 0 else 1
    except Exception as exc:  # pragma: no cover - CLI boundary
        logger.error("Sync failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
