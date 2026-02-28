from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str, timeout_seconds: float = 45.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(f"{base_url}/api/health", timeout=10) as response:
                if int(getattr(response, "status", 200)) == 200:
                    return
        except Exception:
            time.sleep(0.2)
            continue
    raise RuntimeError("quality_review server did not become ready")


def _start_server() -> tuple[subprocess.Popen[bytes], str]:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "scripts/quality_review.py", "--serve", "--port", str(port)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )
    try:
        _wait_for_health(base_url)
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


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], str]:
    data = json.dumps(payload or {}).encode("utf-8") if method in {"POST", "PUT", "PATCH"} else None
    request = Request(
        f"{base_url}{path}",
        method=method,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            content_type = str(response.headers.get("Content-Type", ""))
            parsed = json.loads(body) if body else {}
            return int(getattr(response, "status", 200)), parsed, content_type
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        parsed = json.loads(body) if body else {}
        return int(exc.code), parsed, str(exc.headers.get("Content-Type", ""))


def test_api_contract_get_endpoints_status_and_content_type():
    process, base_url = _start_server()
    try:
        json_endpoints = [
            "/api/version",
            "/api/health",
            "/api/metrics",
            "/api/catalogs",
            "/api/books?limit=5&offset=0",
            "/api/review-data?limit=5&offset=0",
            "/api/iterate-data?limit=5&offset=0",
            "/api/config/cover-source-default",
            "/api/generation-history?limit=5&offset=0",
            "/api/jobs?limit=5&offset=0",
            "/api/analytics/costs",
            "/api/analytics/costs/by-book?limit=5&offset=0",
            "/api/analytics/costs/by-model",
            "/api/analytics/costs/timeline",
            "/api/analytics/budget",
            "/api/analytics/quality/trends",
            "/api/analytics/quality/distribution",
            "/api/analytics/models/compare",
            "/api/analytics/cost-projection?books=10&variants=2&models=openrouter/google/gemini-2.5-flash-image",
            "/api/analytics/completion",
            "/api/analytics/audit?limit=5&offset=0",
            "/api/analytics/reports",
            "/api/review-queue",
            "/api/review-stats",
            "/api/similarity-matrix?limit=5&offset=0",
            "/api/similarity/recompute/status",
            "/api/similarity-alerts",
            "/api/similarity-clusters",
            "/api/mockup-status?limit=5&offset=0",
            "/api/drive/status",
            "/api/drive/sync-status",
            "/api/drive/input-covers",
            "/api/drive/schedule",
            "/api/providers/connectivity",
            "/api/batch-generate?limit=5&offset=0",
            "/api/exports?limit=5&offset=0",
            "/api/export/status?limit=5&offset=0",
            "/api/delivery/status",
            "/api/delivery/tracking?limit=5&offset=0",
            "/api/archive/stats",
            "/api/storage/usage",
            "/api/cache/stats",
        ]
        for path in json_endpoints:
            status, payload, content_type = _request_json(base_url, path)
            assert status == 200, path
            assert "application/json" in content_type.lower(), path
            assert isinstance(payload, dict), path
            assert isinstance(payload.get("success"), bool), path

        with urlopen(f"{base_url}/api/docs", timeout=15) as response:
            assert int(getattr(response, "status", 200)) == 200
            assert "text/html" in str(response.headers.get("Content-Type", "")).lower()
    finally:
        _stop_server(process)


def test_api_contract_cover_source_default_endpoint_shape():
    process, base_url = _start_server()
    try:
        status, payload, content_type = _request_json(base_url, "/api/config/cover-source-default")
        assert status == 200
        assert "application/json" in content_type.lower()
        assert payload.get("ok") is True
        assert payload.get("default") in {"catalog", "drive"}
        assert isinstance(payload.get("local_input_covers_available"), bool)
    finally:
        _stop_server(process)


def test_api_contract_generate_drive_without_selected_cover_is_accepted():
    process, base_url = _start_server()
    try:
        status, payload, content_type = _request_json(
            base_url,
            "/api/generate?catalog=classics",
            method="POST",
            payload={
                "book": 1,
                "models": ["openrouter/google/gemini-2.5-flash-image"],
                "variants": 1,
                "prompt": "contract smoke",
                "provider": "all",
                "cover_source": "drive",
                "dry_run": True,
            },
        )
        assert status == 200
        assert "application/json" in content_type.lower()
        assert payload.get("ok") is True
        assert isinstance(payload.get("job"), dict)
    finally:
        _stop_server(process)


def test_api_contract_pagination_shape():
    process, base_url = _start_server()
    try:
        paginated_endpoints = [
            "/api/review-data?limit=5&offset=0",
            "/api/iterate-data?limit=5&offset=0",
            "/api/generation-history?limit=5&offset=0",
            "/api/analytics/audit?limit=5&offset=0",
            "/api/analytics/costs/by-book?limit=5&offset=0",
            "/api/jobs?limit=5&offset=0",
            "/api/batch-generate?limit=5&offset=0",
            "/api/similarity-matrix?limit=5&offset=0",
            "/api/mockup-status?limit=5&offset=0",
            "/api/exports?limit=5&offset=0",
            "/api/export/status?limit=5&offset=0",
            "/api/delivery/tracking?limit=5&offset=0",
            "/api/books?limit=5&offset=0",
        ]

        for path in paginated_endpoints:
            status, payload, _ = _request_json(base_url, path)
            assert status == 200, path
            pagination = payload.get("pagination")
            assert isinstance(pagination, dict), path
            assert isinstance(pagination.get("total"), int), path
            assert isinstance(pagination.get("limit"), int), path
            assert isinstance(pagination.get("offset"), int), path
            assert isinstance(pagination.get("has_more"), bool), path
            assert isinstance(payload.get("success"), bool), path
    finally:
        _stop_server(process)


def test_api_contract_error_payload_shape():
    process, base_url = _start_server()
    try:
        status, payload, content_type = _request_json(base_url, "/api/does-not-exist")
        assert status == 404
        assert "application/json" in content_type.lower()
        assert payload.get("ok") is False
        assert payload.get("success") is False
        assert isinstance(payload.get("error"), str)
        assert isinstance(payload.get("error_code"), str)
        assert isinstance(payload.get("request_id"), str)
        assert isinstance(payload.get("message"), str)
        assert isinstance(payload.get("error_message"), str)

        status, payload, content_type = _request_json(base_url, "/api/mockup-zip")
        assert status == 400
        assert "application/json" in content_type.lower()
        assert payload.get("ok") is False
        assert isinstance(payload.get("error"), str)
        assert isinstance(payload.get("error_code"), str)
        assert isinstance(payload.get("request_id"), str)
        assert payload.get("success") is False

        status, payload, content_type = _request_json(base_url, "/api/archive/restore/0", method="POST", payload={})
        assert status == 400
        assert "application/json" in content_type.lower()
        assert payload.get("ok") is False
        assert isinstance(payload.get("error"), str)
        assert isinstance(payload.get("error_code"), str)
        assert isinstance(payload.get("request_id"), str)
        assert isinstance(payload.get("message"), str)
        assert isinstance(payload.get("error_message"), str)
        assert payload.get("success") is False
    finally:
        _stop_server(process)


def test_api_contract_mutation_endpoints_return_json_and_success_flags():
    process, base_url = _start_server()
    try:
        checks: list[tuple[str, str, dict[str, Any], int]] = [
            ("/api/drive/schedule?catalog=classics", "POST", {"enabled": True, "interval_hours": 4, "mode": "push"}, 200),
            ("/api/similarity/recompute?catalog=classics", "POST", {"threshold": 0.25, "reason": "contract"}, 200),
            ("/api/delivery/enable?catalog=classics", "POST", {}, 200),
            ("/api/delivery/disable?catalog=classics", "POST", {}, 200),
            ("/api/archive/old-exports?days=30", "POST", {"catalog": "classics"}, 200),
            ("/api/archive/restore/9999?catalog=classics", "POST", {}, 200),
            ("/api/exports/not-real-id", "DELETE", {}, 404),
        ]
        for path, method, payload, expected_status in checks:
            status, body, content_type = _request_json(base_url, path, method=method, payload=payload)
            assert status == expected_status, path
            assert "application/json" in content_type.lower(), path
            assert isinstance(body, dict), path
            assert isinstance(body.get("success"), bool), path
            if expected_status == 200:
                assert body.get("ok") is True, path
            else:
                assert body.get("ok") is False, path
                err = body.get("error")
                assert isinstance(err, (str, bool)), path
                if isinstance(err, bool):
                    assert isinstance(body.get("message"), str), path
    finally:
        _stop_server(process)


def test_api_contract_export_validate_endpoint_shapes():
    process, base_url = _start_server()
    try:
        status, payload, content_type = _request_json(base_url, "/api/export/validate/not-a-book", method="POST", payload={})
        assert status == 400
        assert "application/json" in content_type.lower()
        assert payload.get("ok") is False
        assert isinstance(payload.get("error_code"), str)

        status, payload, content_type = _request_json(base_url, "/api/export/validate/1", method="POST", payload={})
        assert status in {200, 422}
        assert "application/json" in content_type.lower()
        assert isinstance(payload.get("platforms"), dict)
        assert isinstance(payload.get("request_id"), str)
    finally:
        _stop_server(process)
