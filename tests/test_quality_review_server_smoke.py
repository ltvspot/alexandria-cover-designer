from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image

from scripts import quality_review as qr
from src import job_store


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fetch_status(base_url: str, path: str) -> int:
    with urlopen(f"{base_url}{path}", timeout=10) as response:
        return int(getattr(response, "status", 200))


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload or {}).encode("utf-8") if method in {"POST", "PUT", "PATCH"} else None
    req_headers: dict[str, str] = {}
    if data is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)
    request = Request(
        f"{base_url}{path}",
        method=method,
        data=data,
        headers=req_headers,
    )
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return int(getattr(response, "status", 200)), parsed
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        return int(exc.code), parsed


def _wait_for_health(base_url: str, *, path: str = "/api/health", timeout_seconds: float = 45.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            status = _fetch_status(base_url, path)
            if status == 200:
                return
        except URLError as exc:
            last_error = str(exc)
        except Exception as exc:  # pragma: no cover - defensive
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"quality_review server did not become ready at {path}: {last_error}")


def _start_server(
    *,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    wait_path: str = "/api/health",
    timeout_seconds: float = 45.0,
) -> tuple[subprocess.Popen[bytes], str]:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("JOB_WORKER_MODE", "disabled")
    env.setdefault("SLO_MONITOR_INTERVAL_SECONDS", "0")
    if extra_env:
        env.update({str(key): str(value) for key, value in extra_env.items()})
    args = [sys.executable, "scripts/quality_review.py", "--serve", "--port", str(port)]
    if extra_args:
        args.extend(extra_args)
    process = subprocess.Popen(
        args,
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        _wait_for_health(base_url, path=wait_path, timeout_seconds=timeout_seconds)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    return process, base_url


def _stop_server(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def _write_image(path: Path, color: tuple[int, int, int], *, format_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 80), color).save(path, format=format_name)


def _seed_completed_save_raw_job(
    *,
    jobs_db_path: Path,
    job_id: str,
    book_number: int,
    variant: int,
    model: str,
    raw_art_path: Path,
    saved_composited_path: Path,
) -> None:
    store = job_store.JobStore(jobs_db_path)
    now = datetime.now(timezone.utc).isoformat()
    qr._write_saved_composite_manifest(
        composite_path=saved_composited_path,
        job_token=job_id,
        book_number=book_number,
        variant=variant,
        model_token=str(model or "unknown").replace("/", "_").replace(" ", "_"),
        raw_art_source=raw_art_path,
        raw_art_path_token=str(raw_art_path),
    )
    store.create_or_get_job(
        job_id=job_id,
        idempotency_key=f"idem-{job_id}",
        job_type="generate_cover",
        catalog_id="classics",
        book_number=book_number,
        payload={},
    )
    completed = store.mark_completed(
        job_id,
        result={
            "results": [
                {
                    "success": True,
                    "book_number": book_number,
                    "variant": variant,
                    "model": model,
                    "raw_art_path": str(raw_art_path),
                    "saved_composited_path": str(saved_composited_path),
                    "timestamp": now,
                }
            ]
        },
    )
    assert completed is not None


def _write_save_raw_smoke_config(*, config_dir: Path, input_dir: Path, output_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    book_catalog_path = config_dir / "book_catalog.json"
    prompts_path = config_dir / "book_prompts.json"
    prompt_library_path = config_dir / "prompt_library.json"
    prompt_templates_path = config_dir / "prompt_templates.json"
    catalogs_path = config_dir / "catalogs.json"

    book_catalog_path.write_text(
        json.dumps([{"number": 4, "title": "Emma", "author": "Jane Austen"}]),
        encoding="utf-8",
    )
    prompts_path.write_text("[]", encoding="utf-8")
    prompt_library_path.write_text(json.dumps({"prompts": []}), encoding="utf-8")
    prompt_templates_path.write_text(json.dumps({"templates": []}), encoding="utf-8")
    catalogs_path.write_text(
        json.dumps(
            {
                "default_catalog": "save-raw-smoke",
                "catalogs": [
                    {
                        "id": "save-raw-smoke",
                        "name": "Save Raw Smoke",
                        "catalog_file": str(book_catalog_path),
                        "prompts_file": str(prompts_path),
                        "input_covers_dir": str(input_dir),
                        "output_covers_dir": str(output_dir),
                        "cover_style": "navy_gold_medallion",
                        "status": "complete",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_quality_review_server_primary_routes_smoke():
    process, base_url = _start_server()
    try:
        pages = [
            "/",
            "/iterate",
            "/review",
            "/review?mode=speed",
            "/visual-qa",
            "/batch",
            "/catalogs",
            "/jobs",
            "/compare",
            "/history",
            "/dashboard",
            "/analytics/models",
            "/prompts",
            "/catalog/settings",
            "/admin/performance",
            "/similarity",
            "/mockups",
        ]
        apis = [
            "/api/version",
            "/api/health",
            "/api/metrics",
            "/api/models",
            "/api/providers",
            "/api/catalog",
            "/api/templates",
            "/api/stats",
            "/api/config",
            "/api/performance/summary",
            "/api/providers/runtime",
            "/api/workers",
            "/api/jobs",
            "/api/jobs/active",
            "/api/generation-failures",
            "/api/batch-generate",
            "/api/analytics/costs",
            "/api/analytics/costs/by-book",
            "/api/analytics/costs/by-model",
            "/api/analytics/costs/by-operation",
            "/api/analytics/costs/timeline",
            "/api/analytics/budget",
            "/api/analytics/quality/trends",
            "/api/analytics/quality/by-model",
            "/api/analytics/quality/by-prompt-pattern",
            "/api/analytics/quality/distribution",
            "/api/analytics/models/compare",
            "/api/analytics/models/recommendation",
            "/api/analytics/ab-tests",
            "/api/analytics/cost-projection?books=10&variants=2&models=openrouter/google/gemini-2.5-flash-image",
            "/api/analytics/prompts/effectiveness",
            "/api/analytics/quality/breakdown",
            "/api/analytics/completion",
            "/api/analytics/audit",
            "/api/analytics/reports",
            "/api/analytics/reports/schedule",
            "/api/drive-status",
            "/api/drive/status",
            "/api/drive/sync-status",
            "/api/drive/input-covers",
            "/api/drive/schedule",
            "/api/exports",
            "/api/export/status",
            "/api/delivery/status",
            "/api/delivery/tracking",
            "/api/archive/stats",
            "/api/storage/usage",
            "/api/review-data",
            "/api/iterate-data",
            "/api/prompts",
            "/api/prompts/export",
            "/api/dashboard-data",
            "/api/visual-qa",
            "/api/books",
            "/api/compare",
            "/api/similarity-matrix",
            "/api/similarity/recompute/status",
            "/api/review-queue",
            "/api/mockup-status",
            "/api/cache/stats",
            "/api/catalogs",
            "/api/docs",
            "/docs",
        ]

        for path in pages + apis:
            assert _fetch_status(base_url, path) == 200, path
    finally:
        _stop_server(process)


def test_quality_review_server_healthz_binds_before_full_startup():
    process, base_url = _start_server(wait_path="/api/healthz", timeout_seconds=10.0)
    try:
        assert _fetch_status(base_url, "/api/healthz") == 200
        assert _fetch_status(base_url, "/healthz") == 200
    finally:
        _stop_server(process)


def test_quality_review_server_drive_and_provider_connectivity_payloads():
    process, base_url = _start_server()
    try:
        status_save_raw_drive, save_raw_drive = _request_json(base_url, "/api/drive-status")
        assert status_save_raw_drive == 200
        assert save_raw_drive.get("ok") is True
        for key in ("connected", "mode", "service_account_email", "parent_folder_id", "parent_folder_access"):
            assert key in save_raw_drive

        status_drive, drive = _request_json(base_url, "/api/drive/status")
        assert status_drive == 200
        assert drive.get("ok") is True
        for key in ("connected", "mode", "source_folder_id", "output_folder_id", "error"):
            assert key in drive

        status_conn_1, connectivity_1 = _request_json(base_url, "/api/providers/connectivity")
        status_conn_2, connectivity_2 = _request_json(base_url, "/api/providers/connectivity")
        status_conn_force, connectivity_force = _request_json(base_url, "/api/providers/connectivity?force=1")

        assert status_conn_1 == 200
        assert status_conn_2 == 200
        assert status_conn_force == 200
        assert connectivity_1.get("ok") is True
        assert isinstance(connectivity_1.get("providers"), dict)
        assert connectivity_2.get("cached") is True
        assert connectivity_force.get("cached") is False
    finally:
        _stop_server(process)


def test_quality_review_server_save_raw_rejects_mismatched_card_selector(tmp_path: Path):
    config_dir = tmp_path / "config"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    tmp_dir = tmp_path / "tmp"
    data_dir = tmp_path / "data"
    jobs_db_path = data_dir / "jobs.sqlite3"
    _write_save_raw_smoke_config(config_dir=config_dir, input_dir=input_dir, output_dir=output_dir)
    raw_art_path = output_dir / "raw_art" / "4" / "job-emma-a_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    saved_composited_path = output_dir / "saved_composites" / "4" / "job-emma-a_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    _write_image(raw_art_path, (24, 44, 84), format_name="PNG")
    _write_image(saved_composited_path, (84, 44, 24), format_name="JPEG")
    _seed_completed_save_raw_job(
        jobs_db_path=jobs_db_path,
        job_id="job-emma-a",
        book_number=4,
        variant=1,
        model="openrouter/google/gemini-3-pro-image-preview",
        raw_art_path=raw_art_path,
        saved_composited_path=saved_composited_path,
    )

    process, base_url = _start_server(
        extra_env={
            "CATALOG_ID": "save-raw-smoke",
            "CONFIG_DIR": str(config_dir),
            "OUTPUT_DIR": str(output_dir),
            "TMP_DIR": str(tmp_dir),
            "DATA_DIR": str(data_dir),
            "JOBS_DB_PATH": str(jobs_db_path),
            "GOOGLE_CREDENTIALS_PATH": str(tmp_path / "missing-drive-creds.json"),
            "GOOGLE_CREDENTIALS_JSON": "",
        }
    )
    try:
        status, payload = _request_json(
            base_url,
            "/api/save-raw",
            method="POST",
            payload={
                "job_id": "job-emma-a",
                "expected_variant": 1,
                "expected_model": "openrouter/google/gemini-3-pro-image-preview",
                "expected_raw_art_path": str(raw_art_path),
                "expected_saved_composited_path": str(saved_composited_path.with_name("wrong-card.jpg")),
            },
        )
        assert status == 409
        assert payload.get("ok") is False
        assert payload.get("error_code") == "SAVE_RAW_SELECTION_MISMATCH"
        assert payload.get("success") is False
    finally:
        _stop_server(process)


def test_quality_review_server_save_raw_separates_same_book_results_into_unique_packages(tmp_path: Path):
    config_dir = tmp_path / "config"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    tmp_dir = tmp_path / "tmp"
    data_dir = tmp_path / "data"
    jobs_db_path = data_dir / "jobs.sqlite3"
    _write_save_raw_smoke_config(config_dir=config_dir, input_dir=input_dir, output_dir=output_dir)

    raw_a = output_dir / "raw_art" / "4" / "job-emma-a_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    comp_a = output_dir / "saved_composites" / "4" / "job-emma-a_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    raw_b = output_dir / "raw_art" / "4" / "job-emma-b_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    comp_b = output_dir / "saved_composites" / "4" / "job-emma-b_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    _write_image(raw_a, (16, 36, 96), format_name="PNG")
    _write_image(comp_a, (96, 36, 16), format_name="JPEG")
    _write_image(raw_b, (33, 63, 123), format_name="PNG")
    _write_image(comp_b, (123, 63, 33), format_name="JPEG")

    _seed_completed_save_raw_job(
        jobs_db_path=jobs_db_path,
        job_id="job-emma-a",
        book_number=4,
        variant=1,
        model="openrouter/google/gemini-3-pro-image-preview",
        raw_art_path=raw_a,
        saved_composited_path=comp_a,
    )
    _seed_completed_save_raw_job(
        jobs_db_path=jobs_db_path,
        job_id="job-emma-b",
        book_number=4,
        variant=1,
        model="openrouter/google/gemini-3-pro-image-preview",
        raw_art_path=raw_b,
        saved_composited_path=comp_b,
    )

    process, base_url = _start_server(
        extra_env={
            "CATALOG_ID": "save-raw-smoke",
            "CONFIG_DIR": str(config_dir),
            "OUTPUT_DIR": str(output_dir),
            "TMP_DIR": str(tmp_dir),
            "DATA_DIR": str(data_dir),
            "JOBS_DB_PATH": str(jobs_db_path),
            "GOOGLE_CREDENTIALS_PATH": str(tmp_path / "missing-drive-creds.json"),
            "GOOGLE_CREDENTIALS_JSON": "",
        }
    )
    try:
        status_a, payload_a = _request_json(
            base_url,
            "/api/save-raw",
            method="POST",
            payload={
                "job_id": "job-emma-a",
                "expected_variant": 1,
                "expected_model": "openrouter/google/gemini-3-pro-image-preview",
                "expected_raw_art_path": str(raw_a),
                "expected_saved_composited_path": str(comp_a),
            },
        )
        status_b, payload_b = _request_json(
            base_url,
            "/api/save-raw",
            method="POST",
            payload={
                "job_id": "job-emma-b",
                "expected_variant": 1,
                "expected_model": "openrouter/google/gemini-3-pro-image-preview",
                "expected_raw_art_path": str(raw_b),
                "expected_saved_composited_path": str(comp_b),
            },
        )

        assert status_a == 200
        assert status_b == 200
        assert payload_a.get("status") == "partial"
        assert payload_b.get("status") == "partial"
        assert payload_a.get("book_folder_name") == "4. Emma - Jane Austen"
        assert payload_b.get("book_folder_name") == "4. Emma - Jane Austen"
        assert payload_a.get("package_folder_name") != payload_b.get("package_folder_name")
        assert str(payload_a.get("package_folder_name", "")).startswith("save-raw__job-emma-a__variant-1__")
        assert str(payload_b.get("package_folder_name", "")).startswith("save-raw__job-emma-b__variant-1__")
        assert payload_a.get("local_folder") != payload_b.get("local_folder")
        assert payload_a.get("drive_ok") is False
        assert payload_b.get("drive_ok") is False
        assert len(payload_a.get("saved_files", [])) == 4
        assert len(payload_b.get("saved_files", [])) == 4
        assert all(Path(path).exists() for path in payload_a.get("saved_files", []))
        assert all(Path(path).exists() for path in payload_b.get("saved_files", []))
    finally:
        _stop_server(process)


def test_quality_review_server_save_result_returns_json_payload(tmp_path: Path):
    config_dir = tmp_path / "config"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    tmp_dir = tmp_path / "tmp"
    data_dir = tmp_path / "data"
    jobs_db_path = data_dir / "jobs.sqlite3"
    _write_save_raw_smoke_config(config_dir=config_dir, input_dir=input_dir, output_dir=output_dir)

    raw_art_path = output_dir / "raw_art" / "4" / "job-emma-save-result_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    saved_composited_path = output_dir / "saved_composites" / "4" / "job-emma-save-result_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    _write_image(raw_art_path, (24, 44, 84), format_name="PNG")
    _write_image(saved_composited_path, (84, 44, 24), format_name="JPEG")
    _seed_completed_save_raw_job(
        jobs_db_path=jobs_db_path,
        job_id="job-emma-save-result",
        book_number=4,
        variant=1,
        model="openrouter/google/gemini-3-pro-image-preview",
        raw_art_path=raw_art_path,
        saved_composited_path=saved_composited_path,
    )

    process, base_url = _start_server(
        extra_env={
            "CATALOG_ID": "save-raw-smoke",
            "CONFIG_DIR": str(config_dir),
            "OUTPUT_DIR": str(output_dir),
            "TMP_DIR": str(tmp_dir),
            "DATA_DIR": str(data_dir),
            "JOBS_DB_PATH": str(jobs_db_path),
            "GOOGLE_CREDENTIALS_PATH": str(tmp_path / "missing-drive-creds.json"),
            "GOOGLE_CREDENTIALS_JSON": "",
        }
    )
    try:
        status, payload = _request_json(
            base_url,
            "/api/save-result",
            method="POST",
            payload={
                "job_id": "job-emma-save-result",
                "expected_variant": 1,
                "expected_model": "openrouter/google/gemini-3-pro-image-preview",
                "expected_saved_composited_path": str(saved_composited_path),
            },
        )

        assert status == 200
        assert payload.get("ok") is True
        assert payload.get("status") == "partial"
        assert payload.get("drive_ok") is False
        assert payload.get("local_path") == payload.get("local_folder")
        assert str(payload.get("package_folder_name", "")).startswith("save-result__job-emma-save-result__variant-1__")
        assert len(payload.get("saved_files", [])) == 3
        assert all(Path(path).exists() for path in payload.get("saved_files", []))
    finally:
        _stop_server(process)


def test_quality_review_server_cover_preview_and_visual_qa_missing_errors_are_json():
    process, base_url = _start_server(wait_path="/api/healthz", timeout_seconds=10.0)
    try:
        cover_status, cover_payload = _request_json(base_url, "/api/books/99999/cover-preview?catalog=classics")
        assert cover_status == 404
        assert cover_payload.get("ok") is False
        assert "error" in cover_payload

        qa_status, qa_payload = _request_json(base_url, "/api/visual-qa/image/99999?catalog=classics")
        assert qa_status == 404
        assert qa_payload.get("ok") is False
        assert qa_payload.get("error") == "No generated images available for this book. Generate covers first."
    finally:
        _stop_server(process)


def test_quality_review_server_iterate_data_returns_22_priced_models():
    process, base_url = _start_server(wait_path="/api/healthz", timeout_seconds=10.0)
    try:
        status, payload = _request_json(base_url, "/api/iterate-data?catalog=classics&limit=1&offset=0")
        assert status == 200
        models = payload.get("models", [])
        model_costs = payload.get("model_costs", {})
        assert isinstance(models, list)
        assert len(models) == 22
        assert isinstance(model_costs, dict)
        assert all(float(model_costs.get(model, 0) or 0) > 0 for model in models)
        assert {
            "openrouter/sourceful/riverflow-v2-pro",
            "openrouter/sourceful/riverflow-v2-max-preview",
            "openrouter/black-forest-labs/flux.2-max",
            "openrouter/black-forest-labs/flux.2-flex",
            "openrouter/sourceful/riverflow-v2-standard-preview",
            "openrouter/sourceful/riverflow-v2-fast",
            "google/gemini-3-pro-image-preview",
            "google/gemini-3.1-flash-image-preview",
        }.issubset(set(models))
    finally:
        _stop_server(process)


def test_quality_review_server_prompt_library_crud_and_versions():
    process, base_url = _start_server()
    try:
        mutation_headers: dict[str, str] = {}
        token = str(os.environ.get("MUTATION_API_TOKEN", "")).strip()
        if token:
            mutation_headers["X-API-Token"] = token

        status_create, created = _request_json(
            base_url,
            "/api/prompts",
            method="POST",
            payload={
                "name": "Smoke Prompt",
                "prompt_template": "Dramatic cover for {title} with layered symbolism.",
                "category": "smoke",
                "tags": ["smoke", "test"],
            },
            headers=mutation_headers,
        )
        assert status_create == 200
        assert created.get("ok") is True
        prompt = created.get("prompt", {})
        prompt_id = str(prompt.get("id") or created.get("prompt_id") or "")
        assert prompt_id

        status_list, listing = _request_json(base_url, "/api/prompts")
        assert status_list == 200
        prompt_ids = {str(item.get("id")) for item in listing.get("prompts", []) if isinstance(item, dict)}
        assert prompt_id in prompt_ids

        status_update, updated = _request_json(
            base_url,
            f"/api/prompts/{prompt_id}",
            method="POST",
            payload={
                "action": "update",
                "name": "Smoke Prompt v2",
                "prompt_template": "Bold redesign concept for {title} with higher contrast.",
            },
            headers=mutation_headers,
        )
        assert status_update == 200
        assert updated.get("ok") is True
        assert str(updated.get("prompt", {}).get("name", "")) == "Smoke Prompt v2"

        status_versions, versions = _request_json(base_url, f"/api/prompts/{prompt_id}/versions")
        assert status_versions == 200
        assert versions.get("ok") is True
        assert isinstance(versions.get("versions"), list)
        assert len(versions.get("versions", [])) >= 1

        status_usage, usage = _request_json(
            base_url,
            f"/api/prompts/{prompt_id}",
            method="POST",
            payload={"action": "record_usage", "won": True},
            headers=mutation_headers,
        )
        assert status_usage == 200
        usage_prompt = usage.get("prompt", {})
        assert int(usage_prompt.get("usage_count", 0)) >= 1
        assert int(usage_prompt.get("win_count", 0)) >= 1

        status_delete, deleted = _request_json(
            base_url,
            f"/api/prompts/{prompt_id}",
            method="POST",
            payload={"action": "delete"},
            headers=mutation_headers,
        )
        assert status_delete == 200
        assert deleted.get("ok") is True
    finally:
        _stop_server(process)


def test_quality_review_server_serves_favicon():
    process, base_url = _start_server()
    try:
        assert _fetch_status(base_url, "/favicon.ico") == 200
        assert _fetch_status(base_url, "/static/shared.css") == 200
    finally:
        _stop_server(process)


def test_quality_review_server_sigint_shutdown_is_clean():
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("JOB_WORKER_MODE", "disabled")
    env.setdefault("SLO_MONITOR_INTERVAL_SECONDS", "0")
    process = subprocess.Popen(
        [sys.executable, "scripts/quality_review.py", "--serve", "--port", str(port)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        _wait_for_health(base_url)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=12)
    except Exception:
        process.kill()
        process.wait(timeout=8)
        raise

    combined = (stdout + stderr).decode("utf-8", errors="replace")
    assert process.returncode == 0
    assert "Traceback (most recent call last)" not in combined


def test_quality_review_server_external_worker_mode_starts():
    process, base_url = _start_server(extra_args=["--worker-mode", "external"])
    try:
        assert _fetch_status(base_url, "/api/workers") == 200
        assert _fetch_status(base_url, "/api/health") == 200
    finally:
        _stop_server(process)


def test_quality_review_server_exposes_enrichment_health():
    process, base_url = _start_server()
    try:
        status, body = _request_json(base_url, "/api/enrichment-health")
        assert status == 200
        assert body.get("ok") is True
        assert "health" in body
        assert "run_status" in body
    finally:
        _stop_server(process)


def test_quality_review_server_sets_security_headers():
    process, base_url = _start_server()
    try:
        with urlopen(f"{base_url}/api/health", timeout=10) as response:
            headers = response.headers
            assert headers.get("X-Content-Type-Options") == "nosniff"
            assert headers.get("X-Frame-Options") == "DENY"
            assert headers.get("X-XSS-Protection") == "1; mode=block"
            assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
            csp = headers.get("Content-Security-Policy", "")
            assert "default-src 'self'" in csp
    finally:
        _stop_server(process)


def test_quality_review_server_rejects_idempotency_payload_conflict():
    process, base_url = _start_server()
    try:
        idem = f"idem-{uuid.uuid4().hex}"
        status, body = _request_json(
            base_url,
            "/api/jobs",
            method="POST",
            payload={
                "book": 1,
                "models": ["openai/gpt-image-1"],
                "variants": 1,
                "prompt": "Prompt one",
                "provider": "all",
                "dry_run": True,
                "max_attempts": 1,
                "idempotency_key": idem,
            },
        )
        assert status == 200
        assert body.get("ok") is True

        conflict_request = Request(
            f"{base_url}/api/jobs",
            method="POST",
            data=json.dumps(
                {
                    "book": 1,
                    "models": ["openrouter/flux-2-pro"],
                    "variants": 1,
                    "prompt": "Prompt two",
                    "provider": "all",
                    "dry_run": True,
                    "max_attempts": 1,
                    "idempotency_key": idem,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            urlopen(conflict_request, timeout=15)
            assert False, "Expected HTTP 409 conflict"
        except HTTPError as exc:
            assert int(exc.code) == 409
            payload = json.loads(exc.read().decode("utf-8"))
            assert payload.get("code") == "IDEMPOTENCY_CONFLICT"
            assert payload.get("details", {}).get("idempotency_key") == idem
    finally:
        _stop_server(process)


def test_quality_review_server_provider_runtime_reset_endpoint():
    process, base_url = _start_server()
    try:
        status, payload = _request_json(base_url, "/api/providers/reset", method="POST", payload={"provider": "all"})
        assert status == 200
        assert payload.get("ok") is True
        assert payload.get("provider") == "all"
        providers = payload.get("providers")
        assert isinstance(providers, dict)
        assert "openai" in providers

        bad_request = Request(
            f"{base_url}/api/providers/reset",
            method="POST",
            data=json.dumps({"provider": "not-a-provider"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            urlopen(bad_request, timeout=15)
            raise AssertionError("Expected invalid provider reset to fail")
        except HTTPError as exc:
            assert exc.code == 400
    finally:
        _stop_server(process)


def test_quality_review_server_generate_requires_explicit_models():
    process, base_url = _start_server()
    try:
        request = Request(
            f"{base_url}/api/generate",
            method="POST",
            data=json.dumps(
                {
                    "catalog": "classics",
                    "book": 1,
                    "models": [],
                    "variants": 1,
                    "prompt": "test",
                    "provider": "all",
                    "dry_run": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            urlopen(request, timeout=20)
            raise AssertionError("Expected missing-model payload to fail")
        except HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode("utf-8"))
            assert body.get("ok") is False
            assert body.get("error_code") == "MODELS_REQUIRED"
    finally:
        _stop_server(process)


def test_quality_review_server_generate_dry_run_resolves_placeholder_prompt_from_enrichment():
    process, base_url = _start_server()
    try:
        request = Request(
            f"{base_url}/api/generate",
            method="POST",
            data=json.dumps(
                {
                    "catalog": "classics",
                    "book": 1,
                    "models": ["openrouter/google/gemini-3-pro-image-preview"],
                    "variants": 1,
                    "prompt": "Book cover illustration only — {SCENE}. The mood is {MOOD}. Era reference: {ERA}.",
                    "prompt_source": "custom",
                    "compose_prompt": False,
                    "cover_source": "drive",
                    "async": True,
                    "dry_run": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=20) as response:
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
        payload = body.get("job", {}).get("payload", {})
        prompt = str(payload.get("prompt", "")).strip()
        assert "{SCENE}" not in prompt
        assert "{MOOD}" not in prompt
        assert "{ERA}" not in prompt
        assert "romantic longing" in prompt
        assert "Early 20th century" in prompt
    finally:
        _stop_server(process)


def test_quality_review_server_async_generate_preserves_precomposed_prompt_flags():
    process, base_url = _start_server()
    try:
        request = Request(
            f"{base_url}/api/generate",
            method="POST",
            data=json.dumps(
                {
                    "catalog": "classics",
                    "book": 11,
                    "models": ["openrouter/google/gemini-3-pro-image-preview"],
                    "variants": 1,
                    "variant": 1,
                    "prompt": (
                        "Book cover illustration only — no text, no title, no author name, no lettering of any kind. "
                        "No border, no frame, no ornamental elements, no medallion, no decorative edges. "
                        "This illustration MUST depict the following specific scene: Romeo and Juliet meet beneath a moonlit balcony. "
                        "Full scene composition filling the entire canvas, no circular framing."
                    ),
                    "prompt_source": "custom",
                    "compose_prompt": False,
                    "preserve_prompt_text": True,
                    "library_prompt_id": "alexandria-base-romantic-realism",
                    "cover_source": "drive",
                    "async": True,
                    "dry_run": True,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=20) as response:
            assert response.status == 200
            body = json.loads(response.read().decode("utf-8"))
        payload = body.get("job", {}).get("payload", {})
        assert payload.get("compose_prompt") is False
        assert payload.get("preserve_prompt_text") is True
        assert payload.get("library_prompt_id") == "alexandria-base-romantic-realism"
        assert "no medallion" in str(payload.get("prompt", "")).lower()
    finally:
        _stop_server(process)


def test_quality_review_server_rejects_invalid_json_body():
    process, base_url = _start_server()
    try:
        request = Request(
            f"{base_url}/api/generate",
            method="POST",
            data=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        try:
            urlopen(request, timeout=20)
            raise AssertionError("Expected invalid JSON to fail")
        except HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode("utf-8"))
            assert body.get("ok") is False
            assert body.get("error_code") == "INVALID_JSON_BODY"
            assert isinstance(body.get("request_id"), str)
    finally:
        _stop_server(process)


def test_quality_review_server_request_id_headers_are_consistent():
    process, base_url = _start_server()
    try:
        supplied = f"req-{uuid.uuid4().hex}"
        request = Request(f"{base_url}/api/health", headers={"X-Request-Id": supplied})
        with urlopen(request, timeout=10) as response:
            assert response.headers.get("X-Request-Id") == supplied

        with urlopen(f"{base_url}/api/health", timeout=10) as response:
            generated = str(response.headers.get("X-Request-Id", "")).strip()
            assert generated

        with urlopen(f"{base_url}/static/shared.css", timeout=10) as response:
            generated_file = str(response.headers.get("X-Request-Id", "")).strip()
            assert generated_file
    finally:
        _stop_server(process)


def test_quality_review_server_error_payload_contains_request_id():
    process, base_url = _start_server()
    try:
        supplied = f"req-{uuid.uuid4().hex}"
        request = Request(f"{base_url}/api/does-not-exist", headers={"X-Request-Id": supplied})
        try:
            urlopen(request, timeout=10)
            assert False, "Expected 404 response"
        except HTTPError as exc:
            assert int(exc.code) == 404
            body = json.loads(exc.read().decode("utf-8"))
            assert body.get("request_id") == supplied
            assert str(exc.headers.get("X-Request-Id", "")).strip() == supplied
    finally:
        _stop_server(process)


def test_quality_review_server_budget_and_reports_endpoints_work():
    process, base_url = _start_server()
    try:
        status, budget = _request_json(
            base_url,
            "/api/analytics/budget?catalog=classics",
            method="POST",
            payload={"catalog": "classics", "limit_usd": 25, "warning_threshold": 0.8, "hard_stop": True},
        )
        assert status == 200
        assert budget.get("ok") is True
        assert "budget" in budget

        status, report = _request_json(
            base_url,
            "/api/analytics/export-report?catalog=classics",
            method="POST",
            payload={"catalog": "classics", "period": "30d"},
        )
        assert status == 200
        assert report.get("ok") is True
        assert report.get("report_id")

        status, listing = _request_json(base_url, "/api/analytics/reports?catalog=classics")
        assert status == 200
        assert listing.get("ok") is True
        assert isinstance(listing.get("reports"), list)
    finally:
        _stop_server(process)


def test_quality_review_server_drive_schedule_crud():
    process, base_url = _start_server()
    try:
        status, created = _request_json(
            base_url,
            "/api/drive/schedule?catalog=classics",
            method="POST",
            payload={"enabled": True, "interval_hours": 4, "mode": "push", "catalogs": ["classics"]},
        )
        assert status == 200
        assert created.get("ok") is True
        assert created.get("schedule", {}).get("enabled") is True

        status, fetched = _request_json(base_url, "/api/drive/schedule?catalog=classics")
        assert status == 200
        assert fetched.get("ok") is True
        assert fetched.get("schedule", {}).get("mode") == "push"

        status, deleted = _request_json(base_url, "/api/drive/schedule?catalog=classics", method="DELETE")
        assert status == 200
        assert deleted.get("ok") is True
        assert deleted.get("schedule", {}).get("enabled") is False
    finally:
        _stop_server(process)


def test_quality_review_server_blocks_report_path_traversal():
    process, base_url = _start_server()
    try:
        bad_url = f"{base_url}/api/analytics/reports/../../etc/passwd"
        try:
            urlopen(bad_url, timeout=10)
            assert False, "expected HTTPError"
        except HTTPError as exc:
            assert exc.code == 400
    finally:
        _stop_server(process)


def test_quality_review_server_blocks_direct_repo_file_access():
    process, base_url = _start_server()
    try:
        blocked_paths = ["/.env", "/config/book_catalog.json", "/scripts/quality_review.py"]
        for path in blocked_paths:
            try:
                urlopen(f"{base_url}{path}", timeout=10)
                assert False, f"expected HTTPError for {path}"
            except HTTPError as exc:
                assert exc.code in {403, 404}, path
    finally:
        _stop_server(process)


def test_quality_review_server_blocks_static_path_traversal_attempts():
    process, base_url = _start_server()
    try:
        blocked_paths = [
            "/src/static/../../.env",
            "/src/static/%2e%2e/%2e%2e/.env",
            "/src/static/..%2F..%2F.env",
        ]
        for path in blocked_paths:
            try:
                urlopen(f"{base_url}{path}", timeout=10)
                assert False, f"expected HTTPError for {path}"
            except HTTPError as exc:
                assert exc.code in {400, 403, 404}, path
    finally:
        _stop_server(process)


def test_quality_review_server_batch_generation_endpoints_work():
    process, base_url = _start_server()
    try:
        status, iterate_payload = _request_json(base_url, "/api/iterate-data?catalog=classics&limit=25&offset=0")
        assert status == 200
        books = [int(row.get("number", 0)) for row in iterate_payload.get("books", []) if int(row.get("number", 0)) > 0][:2]
        assert books
        models = [str(item) for item in iterate_payload.get("models", []) if str(item).strip()][:1]
        assert models

        status, create_payload = _request_json(
            base_url,
            "/api/batch-generate?catalog=classics",
            method="POST",
            payload={
                "catalog": "classics",
                "books": books,
                "models": models,
                "variants": 1,
                "promptSource": "template",
                "budgetUsd": 1.0,
                "dry_run": True,
            },
        )
        assert status == 200
        assert create_payload.get("ok") is True
        batch_id = str(create_payload.get("batchId", "")).strip()
        assert batch_id

        status, snapshot = _request_json(base_url, f"/api/batch-generate/{batch_id}/status?catalog=classics&limit=10&offset=0")
        assert status == 200
        assert snapshot.get("ok") is True
        assert snapshot.get("batchId") == batch_id
        assert isinstance(snapshot.get("books"), list)
        assert isinstance(snapshot.get("pagination"), dict)

        for action in ("pause", "resume", "cancel"):
            status, action_payload = _request_json(
                base_url,
                f"/api/batch-generate/{batch_id}/{action}?catalog=classics",
                method="POST",
                payload={"reason": f"test-{action}"},
            )
            assert status == 200
            assert action_payload.get("ok") is True
    finally:
        _stop_server(process)


def test_quality_review_server_iterate_books_view_filters_by_number():
    process, base_url = _start_server()
    try:
        status, payload = _request_json(base_url, "/api/iterate-data?catalog=classics&view=books&search=3&limit=10&offset=0")
        assert status == 200
        assert isinstance(payload.get("books"), list)
        assert payload.get("books")
        assert "models" not in payload
        first = payload["books"][0]
        assert "smart_prompts" not in first
        assert isinstance(first.get("prompt_components", {}).get("title_keywords", []), list)
        assert int(payload["books"][0].get("number", 0)) == 3
        assert str(first.get("enrichment", {}).get("emotional_tone", "")).strip()
        assert "Gulliver" in str(first.get("composed_prompt", ""))
        assert "A pivotal dramatic moment from the literary work" not in str(first.get("composed_prompt", ""))
    finally:
        _stop_server(process)


def test_quality_review_server_generation_failures_endpoint_returns_shape():
    process, base_url = _start_server()
    try:
        status, payload = _request_json(base_url, "/api/generation-failures?catalog=classics&limit=5")
        assert status == 200
        assert payload.get("ok") is True
        assert isinstance(payload.get("failures"), list)
        assert isinstance(payload.get("count"), int)
    finally:
        _stop_server(process)


def test_quality_review_server_thumbnail_endpoint_rejects_non_image_and_disallowed_paths():
    token = uuid.uuid4().hex
    disallowed = PROJECT_ROOT / "config" / f"thumb-{token}.txt"
    disallowed.write_text("not-an-image", encoding="utf-8")

    tmp_allowed = PROJECT_ROOT / "tmp" / f"thumb-{token}.jpg"
    tmp_allowed.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (40, 40), color=(120, 80, 40))
    image.save(tmp_allowed, format="JPEG")

    process, base_url = _start_server()
    try:
        # Existing but disallowed source root -> 400 (invalid source policy)
        try:
            urlopen(f"{base_url}/api/thumbnail?path={disallowed.relative_to(PROJECT_ROOT)}&size=small", timeout=10)
            assert False, "expected HTTPError for disallowed thumbnail source"
        except HTTPError as exc:
            assert exc.code == 400

        # Allowed source root and valid image -> 200
        assert _fetch_status(base_url, f"/api/thumbnail?path={tmp_allowed.relative_to(PROJECT_ROOT)}&size=small") == 200
    finally:
        _stop_server(process)
        for target in (disallowed, tmp_allowed):
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass


def test_quality_review_server_asset_and_thumbnail_endpoints_accept_encoded_cachebuster_paths():
    token = uuid.uuid4().hex
    tmp_allowed = PROJECT_ROOT / "tmp" / f"thumb asset {token}.jpg"
    tmp_allowed.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (64, 64), color=(90, 70, 50))
    image.save(tmp_allowed, format="JPEG")
    rel = str(tmp_allowed.relative_to(PROJECT_ROOT))
    encoded = f"{quote(rel)}%3Fv%3D2026-03-10T18%253A40%253A00Z"

    process, base_url = _start_server()
    try:
        assert _fetch_status(base_url, f"/api/asset?path={encoded}") == 200
        assert _fetch_status(base_url, f"/api/thumbnail?path={encoded}&size=small") == 200
    finally:
        _stop_server(process)
        try:
            if tmp_allowed.exists():
                tmp_allowed.unlink()
        except OSError:
            pass
