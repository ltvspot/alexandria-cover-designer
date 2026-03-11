from __future__ import annotations

from dataclasses import replace
import json
import os
import queue
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image
import pytest

from scripts import quality_review as qr
from src import config


def test_cache_key_stable_and_sorted():
    key = qr._cache_key("/api/x", {"b": ["2", "1"], "a": ["z"]}, "classics")
    assert key == "classics:/api/x?a=z&b=1,2"


def test_performance_summary_payload_reports_quantiles(monkeypatch: pytest.MonkeyPatch):
    runtime = SimpleNamespace(catalog_id="classics")
    sample_rows = [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": "GET",
            "path": "/api/a",
            "duration_seconds": 5.2,
            "status_code": 200,
            "catalog": "classics",
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "method": "POST",
            "path": "/api/b",
            "duration_seconds": 8.1,
            "status_code": 500,
            "catalog": "classics",
        },
    ]
    with qr._SLOW_REQUEST_LOG_LOCK:
        previous = list(qr._SLOW_REQUEST_LOG)
        qr._SLOW_REQUEST_LOG[:] = sample_rows

    monkeypatch.setattr(qr.error_metrics, "get_metrics", lambda **_kwargs: {"total": 2, "by_error": {"TimeoutError": 1}})
    monkeypatch.setattr(qr.data_cache, "stats", lambda: {"hits": 3, "misses": 1, "hit_rate": 0.75})
    monkeypatch.setattr(qr.job_db_store, "status_counts", lambda: {"queued": 1, "running": 0})
    monkeypatch.setattr(qr, "_worker_runtime_status", lambda: {"mode": "inline", "workers": {}})

    try:
        payload = qr._performance_summary_payload(runtime=runtime)  # type: ignore[arg-type]
    finally:
        with qr._SLOW_REQUEST_LOG_LOCK:
            qr._SLOW_REQUEST_LOG[:] = previous

    assert payload.get("ok") is True
    response = payload.get("response_time", {})
    assert response.get("sample_size") == 2
    assert float(response.get("p95_seconds", 0.0)) >= float(response.get("p50_seconds", 0.0))
    slow = payload.get("slow_requests", {})
    assert int(slow.get("count", 0)) == 2
    assert isinstance(slow.get("top_endpoints"), list)


def test_generation_idempotency_key_stable_model_order():
    key_a = qr._generation_idempotency_key(
        catalog_id="classics",
        book=7,
        models=["openai/a", "openrouter/b"],
        variants=5,
        prompt="Prompt",
        provider="all",
    )
    key_b = qr._generation_idempotency_key(
        catalog_id="classics",
        book=7,
        models=["openrouter/b", "openai/a"],
        variants=5,
        prompt="Prompt",
        provider="all",
    )
    key_c = qr._generation_idempotency_key(
        catalog_id="classics",
        book=7,
        models=["openrouter/b", "openai/a", "openai/a", " "],
        variants=5,
        prompt="  Prompt   ",
        provider="ALL",
    )
    assert key_a == key_b
    assert key_b == key_c


def test_api_models_payload_prefers_runtime_cost_when_history_is_zero(monkeypatch: pytest.MonkeyPatch):
    runtime = config.get_config("classics")
    monkeypatch.setattr(
        qr,
        "_quality_by_model_payload",
        lambda **_kwargs: {
            "models": [
                {
                    "model": "openrouter/google/gemini-2.5-flash-image",
                    "provider": "openrouter",
                    "count": 0,
                    "avg_cost_per_variant": 0.0,
                }
            ]
        },
    )

    payload = qr._api_models_payload(runtime=runtime)
    models = payload.get("models", [])
    target = next(row for row in models if row.get("id") == "openrouter/google/gemini-2.5-flash-image")
    assert float(target.get("cost_per_image", 0.0)) == pytest.approx(runtime.get_model_cost("openrouter/google/gemini-2.5-flash-image"))


def test_generation_idempotency_key_changes_with_cover_source_and_selected_cover():
    base = qr._generation_idempotency_key(
        catalog_id="classics",
        book=7,
        models=["openai/a"],
        variants=5,
        prompt="Prompt",
        provider="all",
    )
    drive = qr._generation_idempotency_key(
        catalog_id="classics",
        book=7,
        models=["openai/a"],
        variants=5,
        prompt="Prompt",
        provider="all",
        cover_source="drive",
    )
    drive_selected = qr._generation_idempotency_key(
        catalog_id="classics",
        book=7,
        models=["openai/a"],
        variants=5,
        prompt="Prompt",
        provider="all",
        cover_source="drive",
        selected_cover_id="file-123",
    )
    assert base != drive
    assert drive != drive_selected


def test_validate_drive_cover_request_uses_hint_and_ignores_stale_selection(monkeypatch: pytest.MonkeyPatch):
    runtime = SimpleNamespace(
        gdrive_source_folder_id="source-folder",
        gdrive_input_folder_id="",
        gdrive_output_folder_id="output-folder",
        google_credentials_path="",
        config_dir=Path("/tmp"),
        book_catalog_path=Path("/tmp/book_catalog.json"),
    )
    called = {"list": 0}

    def _fake_list_input_covers(**_kwargs):  # type: ignore[no-untyped-def]
        called["list"] += 1
        return {"covers": [{"id": "cover-1", "book_number": 1}]}

    monkeypatch.setattr(qr.drive_manager, "list_input_covers", _fake_list_input_covers)
    ok, error, selected_id = qr._validate_drive_cover_request(
        runtime=runtime,
        book=1,
        cover_source="drive",
        selected_cover_id="cover-x",
        selected_cover={"id": "cover-x", "book_number": 2},
        selected_cover_book_number=2,
        drive_folder_id="",
        input_folder_id="",
        credentials_path_token="",
    )
    assert ok is True
    assert error == ""
    assert selected_id == ""
    assert called["list"] == 0


def test_validate_drive_cover_request_allows_auto_resolution_without_selected_cover():
    runtime = SimpleNamespace()
    ok, error, selected_id = qr._validate_drive_cover_request(
        runtime=runtime,  # type: ignore[arg-type]
        book=1,
        cover_source="drive",
        selected_cover_id="",
        selected_cover=None,
        selected_cover_book_number=0,
        drive_folder_id="",
        input_folder_id="",
        credentials_path_token="",
    )
    assert ok is True
    assert error == ""
    assert selected_id == ""


def test_validate_catalog_cover_request_rejects_missing_local_cover(monkeypatch: pytest.MonkeyPatch):
    runtime = SimpleNamespace()
    monkeypatch.setattr(qr, "_local_cover_available", lambda **_kwargs: False)
    ok, error = qr._validate_catalog_cover_request(
        runtime=runtime,  # type: ignore[arg-type]
        book=12,
        cover_source="catalog",
    )
    assert ok is False
    assert "No local cover is available for book 12" in error


def test_validate_catalog_cover_request_allows_drive_or_available_catalog(monkeypatch: pytest.MonkeyPatch):
    runtime = SimpleNamespace()
    monkeypatch.setattr(qr, "_local_cover_available", lambda **_kwargs: True)

    ok_catalog, error_catalog = qr._validate_catalog_cover_request(
        runtime=runtime,  # type: ignore[arg-type]
        book=4,
        cover_source="catalog",
    )
    ok_drive, error_drive = qr._validate_catalog_cover_request(
        runtime=runtime,  # type: ignore[arg-type]
        book=4,
        cover_source="drive",
    )
    assert ok_catalog is True
    assert error_catalog == ""
    assert ok_drive is True
    assert error_drive == ""


def test_default_cover_source_for_runtime_defaults_to_drive_when_input_dir_is_empty(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    assert qr._default_cover_source_for_runtime(cfg) == "drive"


def test_default_cover_source_for_runtime_defaults_to_catalog_with_local_images(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    source_folder = cfg.input_dir / "1. Book"
    source_folder.mkdir(parents=True, exist_ok=True)
    (source_folder / "cover.jpg").write_bytes(b"image")
    assert qr._default_cover_source_for_runtime(cfg) == "catalog"


def test_title_author_from_drive_name_handles_numeric_prefix_without_becoming_untitled():
    title, author = qr._title_author_from_drive_name("2. Moby Dick_ Or, The Whale - Herman Melville")
    assert title == "Moby Dick Or, The Whale"
    assert author == "Herman Melville"


def test_title_author_from_drive_name_preserves_initials_and_em_dash_author():
    title, author = qr._title_author_from_drive_name("25. The Eyes Have It — Philip K. Dick")
    assert title == "The Eyes Have It"
    assert author == "Philip K. Dick"


def test_build_catalog_rows_from_drive_covers_prefers_parsed_title_when_mapping_is_untitled():
    rows = qr._build_catalog_rows_from_drive_covers(
        covers=[
            {
                "id": "cover-2",
                "name": "2. Moby Dick_ Or, The Whale - Herman Melville",
                "kind": "folder",
                "book_number": 2,
                "title": "Untitled",
            }
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert int(row.get("number", 0)) == 2
    assert row.get("title") == "Moby Dick Or, The Whale"
    assert row.get("author") == "Herman Melville"


def test_build_catalog_rows_from_drive_covers_uses_mapped_title_for_generic_book_tokens():
    rows = qr._build_catalog_rows_from_drive_covers(
        covers=[
            {
                "id": "cover-2",
                "name": "2. Book 2.jpg",
                "kind": "file",
                "book_number": 2,
                "title": "Moby Dick' Or, The Whale",
                "author": "Herman Melville",
            }
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert int(row.get("number", 0)) == 2
    assert row.get("title") == "Moby Dick' Or, The Whale"
    assert row.get("author") == "Herman Melville"


def test_validate_drive_cover_request_lookup_success_and_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    runtime = SimpleNamespace(
        gdrive_source_folder_id="source-folder",
        gdrive_input_folder_id="",
        gdrive_output_folder_id="output-folder",
        google_credentials_path="",
        config_dir=tmp_path,
        book_catalog_path=tmp_path / "book_catalog.json",
    )
    runtime.book_catalog_path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        qr.drive_manager,
        "list_input_covers",
        lambda **_kwargs: {
            "covers": [
                {"id": "cover-1", "book_number": 1},
                {"id": "cover-2", "book_number": 2},
            ]
        },
    )

    ok_good, error_good, selected_id_good = qr._validate_drive_cover_request(
        runtime=runtime,
        book=1,
        cover_source="drive",
        selected_cover_id="cover-1",
        selected_cover=None,
        selected_cover_book_number=0,
        drive_folder_id="",
        input_folder_id="",
        credentials_path_token="",
    )
    assert ok_good is True
    assert error_good == ""
    assert selected_id_good == "cover-1"

    ok_missing, error_missing, selected_id_missing = qr._validate_drive_cover_request(
        runtime=runtime,
        book=1,
        cover_source="drive",
        selected_cover_id="does-not-exist",
        selected_cover=None,
        selected_cover_book_number=0,
        drive_folder_id="",
        input_folder_id="",
        credentials_path_token="",
    )
    assert ok_missing is True
    assert error_missing == ""
    assert selected_id_missing == "cover-1"


def test_validate_drive_cover_request_does_not_trust_spoofed_book_hint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    runtime = SimpleNamespace(
        gdrive_source_folder_id="source-folder",
        gdrive_input_folder_id="",
        gdrive_output_folder_id="output-folder",
        google_credentials_path="",
        config_dir=tmp_path,
        book_catalog_path=tmp_path / "book_catalog.json",
    )
    runtime.book_catalog_path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        qr.drive_manager,
        "list_input_covers",
        lambda **_kwargs: {
            "covers": [
                {"id": "cover-1", "book_number": 2},
            ]
        },
    )

    ok, error, selected_id = qr._validate_drive_cover_request(
        runtime=runtime,
        book=1,
        cover_source="drive",
        selected_cover_id="cover-1",
        selected_cover=None,
        selected_cover_book_number=1,  # spoofed hint
        drive_folder_id="",
        input_folder_id="",
        credentials_path_token="",
    )
    assert ok is False
    assert "no cover found in google drive for book #1" in error.lower()
    assert selected_id == ""


def test_job_worker_enqueue_normalizes_payload():
    captured: dict[str, object] = {}

    class _Store:
        def create_or_get_job(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            job = SimpleNamespace(id="job-1", status="queued", job_type="generate_cover")
            return job, True

    pool = qr.JobWorkerPool(_Store(), worker_count=1, heartbeat_path=None)
    _job, created = pool.enqueue_generate_job(
        catalog_id="classics",
        book=7,
        models=["openrouter/b", "openai/a", "openai/a", " "],
        variants=5,
        prompt="  Prompt   with   spacing ",
        provider="ALL",
        idempotency_key="idem-x",
        dry_run=False,
    )
    assert created is True
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["models"] == ["openai/a", "openrouter/b"]
    assert payload["prompt"] == "Prompt with spacing"
    assert payload["provider"] == "all"
    assert payload["cover_source"] == "catalog"
    assert payload["selected_cover_id"] == ""


def test_job_worker_enqueue_propagates_idempotency_conflict():
    class _Store:
        def create_or_get_job(self, **kwargs):  # type: ignore[no-untyped-def]
            raise qr.job_store.IdempotencyConflictError(
                idempotency_key="idem-x",
                existing_job_id="job-1",
                existing_status="queued",
                conflict_fields=["payload"],
            )

    pool = qr.JobWorkerPool(_Store(), worker_count=1, heartbeat_path=None)
    with pytest.raises(qr.job_store.IdempotencyConflictError):
        pool.enqueue_generate_job(
            catalog_id="classics",
            book=7,
            models=["openai/a"],
            variants=5,
            prompt="Prompt",
            provider="all",
            idempotency_key="idem-x",
        )


def test_max_generation_variants_uses_runtime_value(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, max_generation_variants=37)
    assert qr._max_generation_variants(cfg) == 37


def test_parse_variant():
    assert qr._parse_variant("variant_5_model") == 5
    assert qr._parse_variant("foo") == 0


def test_project_path_if_exists_accepts_project_root_relative_token():
    probe = qr.PROJECT_ROOT / "tmp" / "project_path_resolution_probe.txt"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("ok", encoding="utf-8")
    try:
        resolved = qr._project_path_if_exists("/tmp/project_path_resolution_probe.txt")
        assert resolved == probe
    finally:
        probe.unlink(missing_ok=True)


def test_parse_variant_number():
    assert qr._parse_variant_number("Variant-4") == 4
    assert qr._parse_variant_number("bad") is None


def test_winner_map_to_plain():
    payload = {
        "1": {"winner": 3, "score": 0.8},
        "2": 4,
        "x": {"winner": 2},
        "3": {"winner": 0},
    }
    assert qr._winner_map_to_plain(payload) == {"1": 3, "2": 4}


def test_catalog_id_from_winner_path():
    assert qr._catalog_id_from_winner_path(Path("/tmp/winner_selections.json")) == "classics"
    assert qr._catalog_id_from_winner_path(Path("/tmp/winner_selections_testcat.json")) == "testcat"


def test_normalize_worker_mode():
    assert qr._normalize_worker_mode("inline") == "inline"
    assert qr._normalize_worker_mode("external") == "external"
    assert qr._normalize_worker_mode("disabled") == "disabled"
    assert qr._normalize_worker_mode("weird") == "inline"


def test_sync_generation_allowed_by_mode_and_flag(monkeypatch):
    monkeypatch.setattr(qr, "ALLOW_SYNC_GENERATION", False)
    monkeypatch.setattr(qr, "ACTIVE_WORKER_MODE", "external")
    assert qr._sync_generation_allowed() is False
    monkeypatch.setattr(qr, "ACTIVE_WORKER_MODE", "inline")
    assert qr._sync_generation_allowed() is True
    monkeypatch.setattr(qr, "ACTIVE_WORKER_MODE", "disabled")
    monkeypatch.setattr(qr, "ALLOW_SYNC_GENERATION", True)
    assert qr._sync_generation_allowed() is True


def test_job_stale_recovery_config_uses_runtime_values():
    runtime = SimpleNamespace(
        job_stale_recovery_seconds=321,
        job_stale_recovery_retry_delay_seconds=4.5,
    )
    stale, retry = qr._job_stale_recovery_config(runtime)
    assert stale == 321
    assert retry == 4.5

    fallback = SimpleNamespace(
        job_stale_recovery_seconds="bad",
        job_stale_recovery_retry_delay_seconds="bad",
    )
    stale_fallback, retry_fallback = qr._job_stale_recovery_config(fallback)
    assert stale_fallback >= 30
    assert retry_fallback >= 1.0


def test_slo_monitor_interval_seconds_uses_runtime_values():
    runtime = SimpleNamespace(slo_monitor_interval_seconds=123)
    assert qr._slo_monitor_interval_seconds(runtime) == 123

    fallback = SimpleNamespace(slo_monitor_interval_seconds="bad")
    assert qr._slo_monitor_interval_seconds(fallback) == qr.SLO_MONITOR_INTERVAL_SECONDS


def test_slo_background_monitor_run_once_scans_catalogs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        qr,
        "_build_slo_evaluation",
        lambda *, runtime: (
            {},
            {},
            {
                "api_success_rate_7d": {"status": "met"},
                "job_completion_without_manual_intervention": {"status": "at_risk"},
                "same_stage_retry_rate": {"status": "breached"},
            },
        ),
    )

    class _AlertManager:
        def __init__(self, catalog_id: str) -> None:
            self.catalog_id = catalog_id

        def maybe_alert(self, *, runtime, slo_evaluation):  # type: ignore[no-untyped-def]
            return {
                "checked": True,
                "sent": runtime.catalog_id == "demo",
                "reason": "ok",
                "severity": "breached" if runtime.catalog_id == "demo" else "at_risk",
            }

    monkeypatch.setattr(qr, "_slo_alert_manager_for_runtime", lambda runtime: _AlertManager(runtime.catalog_id))
    monitor = qr.SLOBackgroundMonitor(
        interval_seconds=30,
        runtime_loader=lambda catalog_id: SimpleNamespace(catalog_id=str(catalog_id or "classics")),
        catalog_ids_loader=lambda: ["classics", "demo", "classics"],
    )
    snapshot = monitor.run_once()
    assert snapshot["catalogs_checked"] == 2
    assert snapshot["alerts_sent"] == 1
    assert [row["catalog_id"] for row in snapshot["catalog_summaries"]] == ["classics", "demo"]


def test_slo_background_monitor_start_and_stop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        qr,
        "_build_slo_evaluation",
        lambda *, runtime: (
            {},
            {},
            {
                "api_success_rate_7d": {"status": "met"},
                "job_completion_without_manual_intervention": {"status": "met"},
                "same_stage_retry_rate": {"status": "met"},
            },
        ),
    )

    class _AlertManager:
        def maybe_alert(self, *, runtime, slo_evaluation):  # type: ignore[no-untyped-def]
            return {"checked": True, "sent": False, "reason": "no_alert_conditions"}

    monkeypatch.setattr(qr, "_slo_alert_manager_for_runtime", lambda _runtime: _AlertManager())
    monitor = qr.SLOBackgroundMonitor(
        interval_seconds=1,
        runtime_loader=lambda catalog_id: SimpleNamespace(catalog_id=str(catalog_id or "classics")),
        catalog_ids_loader=lambda: ["classics"],
    )
    assert monitor.start() is True
    deadline = time.time() + 1.5
    while time.time() < deadline:
        if monitor.snapshot().get("last_run_at"):
            break
        time.sleep(0.05)
    monitor.stop()
    snapshot = monitor.snapshot()
    assert snapshot["last_run_at"]
    assert snapshot["running"] is False


def test_slo_background_monitor_snapshot_defaults_and_global_setter():
    qr._set_slo_background_monitor(None)
    disabled = qr._slo_background_monitor_snapshot()
    assert disabled["enabled"] is False
    assert disabled["running"] is False

    class _StubMonitor:
        def snapshot(self) -> dict[str, Any]:
            return {
                "enabled": True,
                "running": True,
                "interval_seconds": 5,
                "last_run_at": "2026-02-23T00:00:00+00:00",
                "last_duration_ms": 1.0,
                "catalogs_checked": 1,
                "alerts_sent": 0,
                "errors": [],
                "catalog_summaries": [],
            }

    qr._set_slo_background_monitor(_StubMonitor())  # type: ignore[arg-type]
    active = qr._slo_background_monitor_snapshot()
    assert active["enabled"] is True
    assert active["running"] is True
    qr._set_slo_background_monitor(None)


def test_worker_runtime_status_from_heartbeat(tmp_path: Path, monkeypatch):
    heartbeat_path = tmp_path / "worker_heartbeat.json"
    heartbeat_path.write_text(
        json.dumps(
            {
                "service": "external",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "worker_count": 2,
                "workers": {
                    "worker-1": {"state": "running", "updated_at": datetime.now(timezone.utc).isoformat()},
                    "worker-2": {"state": "idle", "updated_at": datetime.now(timezone.utc).isoformat()},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(qr, "JOB_WORKER_HEARTBEAT_PATH", heartbeat_path)
    monkeypatch.setattr(qr, "JOB_WORKER_HEARTBEAT_STALE_SECONDS", 300)
    monkeypatch.setattr(qr, "ACTIVE_WORKER_MODE", "external")
    status = qr._worker_runtime_status()
    assert status["mode"] == "external"
    assert status["alive"] is True
    assert status["running_workers"] == 1
    assert status["idle_workers"] == 1


def test_run_worker_service_recovers_stale_jobs_and_stops_pool(monkeypatch, tmp_path: Path):
    events: dict[str, Any] = {}
    heartbeat_path = tmp_path / "hb.json"
    runtime = SimpleNamespace(
        catalog_id="demo",
        job_stale_recovery_seconds=222,
        job_stale_recovery_retry_delay_seconds=3.5,
        slo_monitor_interval_seconds=0,
        job_worker_heartbeat_path=heartbeat_path,
        job_workers=4,
    )
    monkeypatch.setattr(qr.config, "get_config", lambda _catalog_id=None: runtime)
    monkeypatch.setattr(qr, "_bootstrap_state_store_for_runtime", lambda cfg: events.setdefault("boot_catalog", cfg.catalog_id))

    def _fake_recover(**kwargs):  # type: ignore[no-untyped-def]
        events["recover_kwargs"] = dict(kwargs)
        return 2

    monkeypatch.setattr(qr.job_db_store, "recover_stale_running_jobs", _fake_recover)

    class _FakePool:
        def __init__(self, _store, *, worker_count, heartbeat_path, service_name):
            events["pool_init"] = {
                "worker_count": int(worker_count),
                "heartbeat_path": heartbeat_path,
                "service_name": service_name,
            }
            self.worker_count = int(worker_count)

        def start(self):  # type: ignore[no-untyped-def]
            events["started"] = True

        def stop(self):  # type: ignore[no-untyped-def]
            events["stopped"] = True

    monkeypatch.setattr(qr, "JobWorkerPool", _FakePool)
    monkeypatch.setattr(qr.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    qr.run_worker_service(catalog_id="demo", worker_count=None)

    assert events["boot_catalog"] == "demo"
    assert events["recover_kwargs"]["stale_after_seconds"] == 222
    assert events["recover_kwargs"]["retry_delay_seconds"] == 3.5
    assert events["pool_init"]["worker_count"] == 4
    assert events["pool_init"]["heartbeat_path"] == heartbeat_path
    assert events["pool_init"]["service_name"] == "external"
    assert events["started"] is True
    assert events["stopped"] is True


def test_run_worker_service_starts_and_stops_slo_monitor(monkeypatch, tmp_path: Path):
    events: dict[str, Any] = {}
    runtime = SimpleNamespace(
        catalog_id="demo",
        job_stale_recovery_seconds=120,
        job_stale_recovery_retry_delay_seconds=2.0,
        slo_monitor_interval_seconds=5,
        job_worker_heartbeat_path=tmp_path / "hb.json",
        job_workers=1,
    )
    monkeypatch.setattr(qr.config, "get_config", lambda _catalog_id=None: runtime)
    monkeypatch.setattr(qr, "_bootstrap_state_store_for_runtime", lambda _cfg: None)
    monkeypatch.setattr(qr.job_db_store, "recover_stale_running_jobs", lambda **_kwargs: 0)

    class _FakePool:
        def __init__(self, _store, *, worker_count, heartbeat_path, service_name):
            self.worker_count = int(worker_count)
            events["pool_init"] = {
                "worker_count": int(worker_count),
                "heartbeat_path": heartbeat_path,
                "service_name": service_name,
            }

        def start(self):  # type: ignore[no-untyped-def]
            events["pool_started"] = True

        def stop(self):  # type: ignore[no-untyped-def]
            events["pool_stopped"] = True

    class _FakeMonitor:
        def __init__(self, *, interval_seconds, runtime_loader, catalog_ids_loader):
            events["monitor_init"] = {
                "interval_seconds": int(interval_seconds),
                "catalog_ids": catalog_ids_loader(),
                "runtime_catalog": runtime_loader(None).catalog_id,
            }

        def start(self):  # type: ignore[no-untyped-def]
            events["monitor_started"] = True
            return True

        def stop(self):  # type: ignore[no-untyped-def]
            events["monitor_stopped"] = True

        def snapshot(self):  # type: ignore[no-untyped-def]
            return {"enabled": True, "running": True}

    monkeypatch.setattr(qr, "JobWorkerPool", _FakePool)
    monkeypatch.setattr(qr, "SLOBackgroundMonitor", _FakeMonitor)
    monkeypatch.setattr(qr.time, "sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    qr.run_worker_service(catalog_id="demo", worker_count=None)

    assert events["pool_started"] is True
    assert events["pool_stopped"] is True
    assert events["monitor_init"]["interval_seconds"] == 5
    assert events["monitor_init"]["catalog_ids"] == ["demo"]
    assert events["monitor_init"]["runtime_catalog"] == "demo"
    assert events["monitor_started"] is True
    assert events["monitor_stopped"] is True


def test_parse_books_ranges_and_values():
    assert qr._parse_books("1,3-5") == [1, 3, 4, 5]
    assert qr._parse_books(None) is None


def test_safe_int_and_float():
    assert qr._safe_int("7", 0) == 7
    assert qr._safe_int("bad", 9) == 9
    assert qr._safe_float("0.75", 0.0) == 0.75
    assert qr._safe_float("bad", 1.5) == 1.5
    assert qr._safe_float("nan", 1.5) == 1.5
    assert qr._safe_float("inf", 2.5) == 2.5


def test_safe_iso_datetime():
    dt = qr._safe_iso_datetime("2026-02-21T00:00:00+00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert qr._safe_iso_datetime("not-date") is None


def test_normalize_model_name():
    assert qr._normalize_model_name("openai__gpt-image-1") == "openai/gpt-image-1"
    assert qr._normalize_model_name("openai/gpt-image-1") == "openai/gpt-image-1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,2,3", [1, 2, 3]),
        ("2-4", [2, 3, 4]),
        ("5-3", [3, 4, 5]),
        ("1,3-4,6", [1, 3, 4, 6]),
        ("", None),
    ],
)
def test_parse_books_variants(raw, expected):
    assert qr._parse_books(raw if raw else None) == expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        ("10", 0, 10),
        (None, 5, 5),
        ("bad", -1, -1),
        (3.6, 0, 3),
        ("7", 9, 7),
    ],
)
def test_safe_int_matrix(value, default, expected):
    assert qr._safe_int(value, default) == expected


def test_load_json_type_guard(tmp_path: Path):
    path = tmp_path / "x.json"
    path.write_text('{"a":1}', encoding="utf-8")
    assert qr._load_json(path, {"x": 1}) == {"a": 1}
    assert qr._load_json(path, []) == []


def test_load_quality_lookup_uses_best_score(tmp_path: Path):
    path = tmp_path / "quality.json"
    payload = {
        "scores": [
            {"book_number": 1, "variant_id": 2, "overall_score": 0.6},
            {"book_number": 1, "variant_id": 2, "overall_score": 0.9},
            {"book_number": 2, "variant_id": 1, "overall_score": 0.7},
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    lookup = qr._load_quality_lookup(path)
    assert lookup[(1, 2)] == 0.9
    assert lookup[(2, 1)] == 0.7


def test_append_generation_history(tmp_path: Path):
    path = tmp_path / "history.json"
    items = [{"book_number": 1, "timestamp": datetime.now(timezone.utc).isoformat()}]
    qr._append_generation_history(path, items)
    payload = qr._load_json(path, {"items": []})
    assert isinstance(payload, dict)
    assert len(payload["items"]) == 1
    built = qr._build_generation_history_payload(path, [{"book_number": 2}])
    assert "items" in built


def test_build_generation_history_payload_dedupes_job_rows(tmp_path: Path):
    path = tmp_path / "history.json"
    existing = {
        "items": [
            {
                "job_id": "job-1",
                "book_number": 1,
                "variant": 1,
                "model": "openrouter/flux-2-pro",
                "provider": "openrouter",
                "dry_run": False,
                "timestamp": "2026-02-23T00:00:00+00:00",
            }
        ]
    }
    path.write_text(json.dumps(existing), encoding="utf-8")
    output = qr._build_generation_history_payload(
        path,
        [
            {
                "job_id": "job-1",
                "book_number": 1,
                "variant": 1,
                "model": "openrouter/flux-2-pro",
                "provider": "openrouter",
                "dry_run": False,
                "timestamp": "2026-02-23T00:00:01+00:00",
            },
            {
                "job_id": "job-2",
                "book_number": 1,
                "variant": 1,
                "model": "openrouter/flux-2-pro",
                "provider": "openrouter",
                "dry_run": False,
                "timestamp": "2026-02-23T00:00:02+00:00",
            },
        ],
    )
    assert len(output["items"]) == 2
    assert sorted(item.get("job_id") for item in output["items"]) == ["job-1", "job-2"]


def test_filter_generation_records_all_filters():
    rows = [
        {
            "book_number": 1,
            "model": "openai/gpt-image-1",
            "provider": "openai",
            "status": "success",
            "timestamp": "2026-02-20T00:00:00+00:00",
            "quality_score": 0.8,
        },
        {
            "book_number": 2,
            "model": "openrouter/flux",
            "provider": "openrouter",
            "status": "error",
            "timestamp": "2026-02-19T00:00:00+00:00",
            "quality_score": 0.2,
        },
    ]
    filtered = qr._filter_generation_records(
        rows,
        filters={
            "book": ["1"],
            "model": ["gpt-image"],
            "provider": ["openai"],
            "status": ["success"],
            "date_from": ["2026-02-19"],
            "date_to": ["2026-02-21"],
            "quality_min": ["0.7"],
            "quality_max": ["1.0"],
        },
    )
    assert len(filtered) == 1
    assert filtered[0]["book_number"] == 1


def test_collect_selected_variant_files(tmp_path: Path):
    output_dir = tmp_path / "Output Covers"
    folder = output_dir / "Book One" / "Variant-2"
    folder.mkdir(parents=True, exist_ok=True)
    for ext in ("jpg", "pdf", "ai"):
        (folder / f"cover.{ext}").write_bytes(b"x")

    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([{"number": 1, "folder_name": "Book One"}]), encoding="utf-8")

    files = qr._collect_selected_variant_files(
        output_dir=output_dir,
        selections={"1": {"winner": 2}},
        catalog_path=catalog,
    )
    assert sorted(files) == sorted(["Book One/Variant-2/cover.ai", "Book One/Variant-2/cover.jpg", "Book One/Variant-2/cover.pdf"])


def test_save_raw_helpers_resolve_paths_and_preserve_display_naming(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 7, "title": "Temple / Dawn", "author": "A. Writer"}]),
        encoding="utf-8",
    )
    raw_path = cfg.tmp_dir / "generated" / "7" / "openrouter__google__gemini-3-pro-image-preview" / "variant_1.png"
    comp_path = cfg.tmp_dir / "composited" / "7" / "openrouter__google__gemini-3-pro-image-preview" / "variant_1.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (12, 34, 56)).save(raw_path, format="PNG")
    Image.new("RGB", (64, 64), (56, 34, 12)).save(comp_path, format="JPEG")
    qr._write_saved_composite_manifest(
        composite_path=comp_path,
        job_token="job-raw-partial",
        book_number=7,
        variant=1,
        model_token="openrouter_google_gemini-3-pro-image-preview",
        raw_art_source=raw_path,
        raw_art_path_token=qr._to_project_relative(raw_path),
    )

    job = qr.job_store.JobRecord(
        id="job-1",
        idempotency_key="idem-1",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=7,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 1,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "image_path": str(raw_path),
                    "composited_path": str(comp_path),
                }
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )

    assert qr._resolve_raw_image_path_for_job(runtime=cfg, job=job) == raw_path
    assert qr._resolve_composite_image_path_for_job(runtime=cfg, job=job) == comp_path
    assert qr._display_filename_token("Temple / Dawn") == "Temple Dawn"
    assert qr._display_filename_token("Temple – Dawn") == "Temple – Dawn"


def test_save_raw_helpers_do_not_fallback_to_directory_scans(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    raw_path = cfg.tmp_dir / "generated" / "7" / "openrouter__google__gemini-3-pro-image-preview" / "variant_1.png"
    comp_path = cfg.tmp_dir / "composited" / "7" / "openrouter__google__gemini-3-pro-image-preview" / "variant_1.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (12, 34, 56)).save(raw_path, format="PNG")
    Image.new("RGB", (64, 64), (56, 34, 12)).save(comp_path, format="JPEG")

    job = qr.job_store.JobRecord(
        id="job-no-fallback",
        idempotency_key="idem-no-fallback",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=7,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 1,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                }
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )

    assert qr._resolve_raw_image_path_for_job(runtime=cfg, job=job) is None
    assert qr._resolve_composite_image_path_for_job(runtime=cfg, job=job) is None


def test_upload_single_file_to_drive_retries_and_updates_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    file_path = tmp_path / "cover.jpg"
    file_path.write_bytes(b"jpg-bytes")
    monkeypatch.setattr(qr.gdrive_sync, "MediaFileUpload", lambda path, mimetype=None: SimpleNamespace(path=path, mimetype=mimetype))

    class _FakeFiles:
        def __init__(self) -> None:
            self.update_attempts = 0

        def list(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(execute=lambda: {"files": [{"id": "file-existing", "name": file_path.name}]})

        def update(self, **kwargs):  # type: ignore[no-untyped-def]
            def _execute():
                self.update_attempts += 1
                if self.update_attempts == 1:
                    raise RuntimeError("temporary drive failure")
                return {"id": kwargs["fileId"]}

            return SimpleNamespace(execute=_execute)

    class _FakeService:
        def __init__(self) -> None:
            self._files = _FakeFiles()

        def files(self):
            return self._files

    result = qr._upload_single_file_to_drive(
        service=_FakeService(),
        parent_folder_id="folder-1",
        file_path=file_path,
    )

    assert result["ok"] is True
    assert result["action"] == "updated"
    assert result["attempts"] == 2
    assert result["file_id"] == "file-existing"


def test_upload_folder_to_drive_returns_structured_failure_when_drive_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    local_folder = tmp_path / "Chosen Winner Generated Covers" / "1. Book - Author"
    local_folder.mkdir(parents=True, exist_ok=True)
    (local_folder / "Book – Author.jpg").write_bytes(b"jpg")

    monkeypatch.setattr(
        qr,
        "_drive_service_for_runtime",
        lambda _runtime: (
            None,
            Path("/tmp/credentials.json"),
            None,
            {"client_email": "", "source": "missing", "loaded": False},
            "No Google credentials found.",
        ),
    )

    result = qr._upload_folder_to_drive(
        runtime=cfg,
        local_folder=local_folder,
        folder_name="1. Book - Author",
        parent_folder_id="parent-folder",
    )

    assert result["ok"] is False
    assert result["uploaded_count"] == 0
    assert result["failed_count"] == 1
    assert "No Google credentials found" in str(result["warning"])
    assert result["failed"][0]["name"] == "Book – Author.jpg"


def test_save_raw_payload_for_job_returns_partial_when_drive_upload_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 7, "title": "Temple Dawn", "author": "A. Writer"}]),
        encoding="utf-8",
    )
    raw_path = cfg.output_dir / "raw_art" / "7" / "job-raw-partial_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    comp_path = cfg.output_dir / "saved_composites" / "7" / "job-raw-partial_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (12, 34, 56)).save(raw_path, format="PNG")
    Image.new("RGB", (64, 64), (56, 34, 12)).save(comp_path, format="JPEG")
    qr._write_saved_composite_manifest(
        composite_path=comp_path,
        job_token="job-raw-partial",
        book_number=7,
        variant=1,
        model_token="openrouter_google_gemini-3-pro-image-preview",
        raw_art_source=raw_path,
        raw_art_path_token=qr._to_project_relative(raw_path),
    )
    job = qr.job_store.JobRecord(
        id="job-raw-partial",
        idempotency_key="idem-raw-partial",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=7,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 1,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "raw_art_path": qr._to_project_relative(raw_path),
                    "saved_composited_path": qr._to_project_relative(comp_path),
                }
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )
    monkeypatch.setattr(
        qr,
        "_upload_folder_to_drive",
        lambda **_kwargs: {
            "ok": False,
            "folder_id": "drive-folder-1",
            "drive_url": "https://drive.google.com/drive/folders/drive-folder-1",
            "uploaded": [{"name": "Temple Dawn – A. Writer (generated raw).jpg"}],
            "failed": [{"name": "Temple Dawn – A. Writer.ai", "error": "storageQuotaExceeded"}],
            "warning": "Drive upload partially completed: 5 uploaded, 1 failed.",
        },
    )

    payload = qr._save_raw_payload_for_job(runtime=cfg, job=job)

    assert payload["ok"] is True
    assert payload["status"] == "partial"
    assert payload["retry_available"] is True
    assert payload["drive_folder_id"] == "drive-folder-1"
    assert len(payload["saved_files"]) == 6
    assert {Path(path).suffix for path in payload["saved_files"]} == {".jpg", ".pdf", ".ai"}
    assert all(Path(path).exists() for path in payload["saved_files"])
    assert "Drive upload partially completed" in str(payload["warning"])


def test_save_raw_context_uses_unique_package_folder_per_result(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 7, "title": "Temple Dawn", "author": "A. Writer"}]),
        encoding="utf-8",
    )

    def _make_job(job_id: str, raw_color: tuple[int, int, int], comp_color: tuple[int, int, int]):
        raw_path = cfg.output_dir / "raw_art" / "7" / f"{job_id}_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
        comp_path = cfg.output_dir / "saved_composites" / "7" / f"{job_id}_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        comp_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), raw_color).save(raw_path, format="PNG")
        Image.new("RGB", (64, 64), comp_color).save(comp_path, format="JPEG")
        return qr.job_store.JobRecord(
            id=job_id,
            idempotency_key=f"idem-{job_id}",
            job_type="generate_cover",
            status="completed",
            catalog_id="classics",
            book_number=7,
            payload={},
            result={
                "results": [
                    {
                        "success": True,
                        "variant": 1,
                        "model": "openrouter/google/gemini-3-pro-image-preview",
                        "raw_art_path": qr._to_project_relative(raw_path),
                        "saved_composited_path": qr._to_project_relative(comp_path),
                    }
                ]
            },
            error={},
            attempts=1,
            max_attempts=3,
            priority=100,
            retry_after="",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            worker_id="",
        )

    first = _make_job("job-alpha", (12, 34, 56), (56, 34, 12))
    second = _make_job("job-beta", (23, 45, 67), (67, 45, 23))

    first_context = qr._save_raw_context_for_job(runtime=cfg, job=first)
    second_context = qr._save_raw_context_for_job(runtime=cfg, job=second)

    assert first_context["book_folder_name"] == second_context["book_folder_name"]
    assert first_context["package_folder_name"] != second_context["package_folder_name"]
    assert Path(first_context["local_folder"]) != Path(second_context["local_folder"])
    assert "job-alpha" in str(first_context["package_folder_name"])
    assert "job-beta" in str(second_context["package_folder_name"])


def test_save_raw_context_refuses_mutable_tmp_only_artifacts(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 7, "title": "Temple Dawn", "author": "A. Writer"}]),
        encoding="utf-8",
    )
    raw_path = cfg.tmp_dir / "generated" / "7" / "openrouter__google__gemini-3-pro-image-preview" / "variant_1.png"
    comp_path = cfg.tmp_dir / "composited" / "7" / "openrouter__google__gemini-3-pro-image-preview" / "variant_1.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (12, 34, 56)).save(raw_path, format="PNG")
    Image.new("RGB", (64, 64), (56, 34, 12)).save(comp_path, format="JPEG")

    job = qr.job_store.JobRecord(
        id="job-mutable-only",
        idempotency_key="idem-mutable-only",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=7,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 1,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "image_path": qr._to_project_relative(raw_path),
                    "composited_path": qr._to_project_relative(comp_path),
                }
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )

    with pytest.raises(qr.SaveRawIntegrityError) as exc_info:
        qr._save_raw_context_for_job(runtime=cfg, job=job)
    assert exc_info.value.code == "SAVE_RAW_IMMUTABLE_ARTIFACTS_REQUIRED"


def test_row_for_save_raw_requires_exact_selector_for_multi_result_job(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 7, "title": "Temple Dawn", "author": "A. Writer"}]),
        encoding="utf-8",
    )
    raw_one = cfg.output_dir / "raw_art" / "7" / "job-multi_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    comp_one = cfg.output_dir / "saved_composites" / "7" / "job-multi_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    raw_two = cfg.output_dir / "raw_art" / "7" / "job-multi_variant_2_openrouter_google_gemini-3-pro-image-preview.png"
    comp_two = cfg.output_dir / "saved_composites" / "7" / "job-multi_variant_2_openrouter_google_gemini-3-pro-image-preview.jpg"
    for path, color in (
        (raw_one, (12, 34, 56)),
        (comp_one, (56, 34, 12)),
        (raw_two, (22, 44, 66)),
        (comp_two, (66, 44, 22)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), color).save(path, format="PNG" if path.suffix.lower() == ".png" else "JPEG")

    job = qr.job_store.JobRecord(
        id="job-multi",
        idempotency_key="idem-job-multi",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=7,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 1,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "raw_art_path": qr._to_project_relative(raw_one),
                    "saved_composited_path": qr._to_project_relative(comp_one),
                },
                {
                    "success": True,
                    "variant": 2,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "raw_art_path": qr._to_project_relative(raw_two),
                    "saved_composited_path": qr._to_project_relative(comp_two),
                },
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )

    with pytest.raises(qr.SaveRawIntegrityError) as exc_info:
        qr._row_for_save_raw(job=job)
    assert exc_info.value.code == "SAVE_RAW_SELECTION_REQUIRED"

    selected = qr._row_for_save_raw(
        job=job,
        expected={
            "expected_variant": 2,
            "expected_model": "openrouter/google/gemini-3-pro-image-preview",
            "expected_raw_art_path": qr._to_project_relative(raw_two),
            "expected_saved_composited_path": qr._to_project_relative(comp_two),
        },
    )
    assert qr._row_variant_number(selected) == 2
    assert str(selected["saved_composited_path"]) == qr._to_project_relative(comp_two)


def test_row_for_save_raw_rejects_mismatch_with_pre_normalized_selector(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 7, "title": "Temple Dawn", "author": "A. Writer"}]),
        encoding="utf-8",
    )
    raw_path = cfg.output_dir / "raw_art" / "7" / "job-single_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    comp_path = cfg.output_dir / "saved_composites" / "7" / "job-single_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (15, 35, 55)).save(raw_path, format="PNG")
    Image.new("RGB", (64, 64), (55, 35, 15)).save(comp_path, format="JPEG")

    job = qr.job_store.JobRecord(
        id="job-single",
        idempotency_key="idem-job-single",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=7,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 1,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "raw_art_path": qr._to_project_relative(raw_path),
                    "saved_composited_path": qr._to_project_relative(comp_path),
                }
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )

    with pytest.raises(qr.SaveRawIntegrityError) as exc_info:
        qr._row_for_save_raw(
            job=job,
            expected={
                "variant": 1,
                "model": "openrouter/google/gemini-3-pro-image-preview",
                "raw_art_path": qr._to_project_relative(raw_path),
                "saved_composited_path": qr._to_project_relative(comp_path.with_name("wrong-card.jpg")),
            },
        )
    assert exc_info.value.code == "SAVE_RAW_SELECTION_MISMATCH"


def test_save_raw_payload_uses_nested_drive_folder_parts_per_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 4, "title": "Emma", "author": "Jane Austen"}]),
        encoding="utf-8",
    )
    raw_path = cfg.output_dir / "raw_art" / "4" / "job-emma_variant_3_openrouter_google_gemini-3-pro-image-preview.png"
    comp_path = cfg.output_dir / "saved_composites" / "4" / "job-emma_variant_3_openrouter_google_gemini-3-pro-image-preview.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (13, 23, 33)).save(raw_path, format="PNG")
    Image.new("RGB", (64, 64), (43, 53, 63)).save(comp_path, format="JPEG")

    job = qr.job_store.JobRecord(
        id="job-emma",
        idempotency_key="idem-job-emma",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=4,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 3,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "raw_art_path": qr._to_project_relative(raw_path),
                    "saved_composited_path": qr._to_project_relative(comp_path),
                }
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )

    captured: dict[str, Any] = {}

    def _fake_upload_folder_to_drive(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {
            "ok": True,
            "folder_id": "drive-folder-1",
            "drive_url": "https://drive.google.com/drive/folders/drive-folder-1",
            "uploaded": [],
            "failed": [],
            "warning": None,
        }

    monkeypatch.setattr(qr, "_upload_folder_to_drive", _fake_upload_folder_to_drive)

    payload = qr._save_raw_payload_for_job(runtime=cfg, job=job)

    assert payload["status"] == "saved"
    assert captured["folder_parts"][0] == "4. Emma - Jane Austen"
    assert captured["folder_parts"][1].startswith("save-raw__job-emma__variant-3__")


def test_save_raw_drive_status_payload_reports_parent_folder_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)

    class _FakeFiles:
        def get(self, **kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(
                execute=lambda: {
                    "id": kwargs["fileId"],
                    "name": "Chosen Winner Generated Covers",
                    "webViewLink": f"https://drive.google.com/drive/folders/{kwargs['fileId']}",
                }
            )

    class _FakeService:
        def files(self):
            return _FakeFiles()

    monkeypatch.setattr(
        qr,
        "_drive_service_for_runtime",
        lambda _runtime: (
            _FakeService(),
            Path("/tmp/credentials.json"),
            "service_account_env",
            {"client_email": "alexandria-bot@example.iam.gserviceaccount.com", "source": "env", "loaded": True},
            None,
        ),
    )
    monkeypatch.setattr(qr, "_probe_drive_write_access", lambda **_kwargs: {"ok": True, "error": "", "file_id": "probe-file"})

    payload = qr._save_raw_drive_status_payload(runtime=cfg)

    assert payload["ok"] is True
    assert payload["connected"] is True
    assert payload["parent_folder_access"] is True
    assert payload["parent_folder_id"] == "0ABLZWLOVzq-qUk9PVA"
    assert payload["write_access"] is True
    assert payload["retry_supported"] is True
    assert payload["service_account_email"] == "alexandria-bot@example.iam.gserviceaccount.com"
    assert payload["parent_folder_url"].startswith("https://drive.google.com/drive/folders/")


def test_probe_drive_write_access_with_timeout_returns_quickly(monkeypatch: pytest.MonkeyPatch):
    def _slow_probe(**_kwargs):  # type: ignore[no-untyped-def]
        time.sleep(0.2)
        return {"ok": True, "error": "", "file_id": "late"}

    monkeypatch.setattr(qr, "_probe_drive_write_access", _slow_probe)

    started = time.perf_counter()
    payload = qr._probe_drive_write_access_with_timeout(
        service=object(),
        parent_folder_id="folder-1",
        timeout_seconds=0.01,
    )
    elapsed = time.perf_counter() - started

    assert payload["ok"] is False
    assert payload["timed_out"] is True
    assert "timed out after 0.0s" in str(payload["error"])
    assert elapsed < 0.15


def test_probe_drive_write_access_retries_cleanup_visibility_lag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(qr.gdrive_sync, "MediaFileUpload", lambda path, mimetype=None: SimpleNamespace(path=path, mimetype=mimetype))
    monkeypatch.setattr(qr.time, "sleep", lambda _seconds: None)

    class _FakeFiles:
        def __init__(self) -> None:
            self.cleanup_attempts = 0

        def create(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(execute=lambda: {"id": "probe-file"})

        def update(self, **_kwargs):  # type: ignore[no-untyped-def]
            def _execute():
                self.cleanup_attempts += 1
                if self.cleanup_attempts == 1:
                    raise RuntimeError("File not found: probe-file")
                return {}

            return SimpleNamespace(execute=_execute)

    class _FakeService:
        def __init__(self) -> None:
            self._files = _FakeFiles()

        def files(self):
            return self._files

    service = _FakeService()
    payload = qr._probe_drive_write_access(service=service, parent_folder_id="folder-1")

    assert payload["ok"] is True
    assert payload["file_id"] == "probe-file"
    assert service._files.cleanup_attempts == 2


def test_run_startup_checks_logs_shared_drive_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    cfg = replace(_build_runtime_for_startup_checks(tmp_path), gdrive_source_folder_id="source-folder")
    monkeypatch.setattr(
        qr,
        "_drive_service_for_runtime",
        lambda _runtime: (
            object(),
            Path("/tmp/credentials.json"),
            "service_account_env",
            {"client_email": "alexandria-bot@example.iam.gserviceaccount.com", "source": "env", "loaded": True},
            None,
        ),
    )
    monkeypatch.setattr(
        qr,
        "_probe_drive_write_access_with_timeout",
        lambda **_kwargs: {"ok": True, "error": "", "file_id": "probe-file"},
    )

    with caplog.at_level("INFO"):
        report = qr._run_startup_checks(cfg)

    drive_check = next(row for row in report["checks"] if row["name"] == "save_raw_drive_write_access")
    assert drive_check["ok"] is True
    assert drive_check["detail"] == "Drive upload: OK (Shared Drive)"
    assert "Drive upload: OK (Shared Drive)" in caplog.text


def test_sync_catalog_from_drive_queues_auto_enrichment_for_new_books(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, gdrive_source_folder_id="source-folder")
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 1, "title": "Book", "author": "Author"}]),
        encoding="utf-8",
    )
    queued: dict[str, Any] = {}

    monkeypatch.setattr(qr, "_resolve_credentials_path", lambda _runtime: tmp_path / "creds.json")
    monkeypatch.setattr(
        qr.drive_manager,
        "list_input_covers",
        lambda **_kwargs: {
            "covers": [{"id": "cover-1"}, {"id": "cover-2"}],
            "total": 2,
        },
    )
    monkeypatch.setattr(
        qr,
        "_merge_catalog_rows_with_drive",
        lambda **_kwargs: (
            [
                {"number": 1, "title": "Book", "author": "Author"},
                {"number": 2, "title": "New Book", "author": "New Author"},
            ],
            {"matched": 1, "unmatched": 0, "added": 1},
        ),
    )
    monkeypatch.setattr(
        qr,
        "_queue_catalog_enrichment",
        lambda **kwargs: queued.update(kwargs) or {"queued": True, "reason": kwargs["reason"], "books": kwargs["books"], "count": len(kwargs["books"])},
    )
    monkeypatch.setattr(qr, "write_iterate_data", lambda **_kwargs: None)
    iterate_path = qr._iterate_data_path_for_runtime(cfg)

    def _fake_load_json(path, default):  # type: ignore[no-untyped-def]
        if Path(path) == iterate_path:
            return {"books": []}
        if Path(path).exists():
            return json.loads(Path(path).read_text(encoding="utf-8"))
        return default

    monkeypatch.setattr(qr, "_load_json", _fake_load_json)
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)

    payload = qr._sync_catalog_from_drive(runtime=cfg)

    assert payload["ok"] is True
    assert payload["added_drive_entries"] == 1
    assert payload["auto_enrichment"]["queued"] is True
    assert payload["auto_enrichment"]["books"] == [2]
    assert queued["books"] == [2]
    assert queued["reason"] == "drive_sync_new_books"


def test_serialize_generation_results_persists_job_unique_raw_and_composite_artifacts(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    model = "openrouter/google/gemini-3-pro-image-preview"
    model_dir = cfg.tmp_dir / "generated" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    model_dir.mkdir(parents=True, exist_ok=True)
    image_path = model_dir / "variant_1.png"
    Image.new("RGB", (64, 64), (11, 22, 33)).save(image_path, format="PNG")

    composite_dir = cfg.tmp_dir / "composited" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    composite_dir.mkdir(parents=True, exist_ok=True)
    composite_path = composite_dir / "variant_1.jpg"
    Image.new("RGB", (64, 64), (44, 55, 66)).save(composite_path, format="JPEG")

    result = qr.image_generator.GenerationResult(
        book_number=1,
        variant=1,
        prompt="Book cover illustration only — no text. Prompt.",
        model=model,
        image_path=image_path,
        success=True,
        error=None,
        generation_time=1.2,
        cost=0.02,
        provider="openrouter",
        attempts=1,
    )

    first = qr._serialize_generation_results(runtime=cfg, book=1, results=[result], job_id="job-alpha")
    second = qr._serialize_generation_results(runtime=cfg, book=1, results=[result], job_id="job-beta")

    assert first[0]["raw_art_path"] != second[0]["raw_art_path"]
    assert first[0]["saved_composited_path"] != second[0]["saved_composited_path"]
    assert (qr.PROJECT_ROOT / str(first[0]["raw_art_path"])).exists()
    assert (qr.PROJECT_ROOT / str(second[0]["raw_art_path"])).exists()
    assert (qr.PROJECT_ROOT / str(first[0]["saved_composited_path"])).exists()
    assert (qr.PROJECT_ROOT / str(second[0]["saved_composited_path"])).exists()


def test_hydrate_serialized_result_paths_persists_saved_composite_after_compositing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    model = "openrouter/google/gemini-3-pro-image-preview"
    model_dir = cfg.tmp_dir / "generated" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    model_dir.mkdir(parents=True, exist_ok=True)
    image_path = model_dir / "variant_1.png"
    Image.new("RGB", (64, 64), (21, 31, 41)).save(image_path, format="PNG")

    composite_dir = cfg.tmp_dir / "composited" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    composite_dir.mkdir(parents=True, exist_ok=True)
    composite_path = composite_dir / "variant_1.jpg"
    Image.new("RGB", (64, 64), (51, 61, 71)).save(composite_path, format="JPEG")

    raw_dir = cfg.output_dir / "raw_art" / "1"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "job-hydrate_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    Image.new("RGB", (64, 64), (81, 91, 101)).save(raw_path, format="PNG")

    def _fake_rebuild(*, runtime: config.Config, row: dict[str, Any], output_path: Path) -> Path:
        del runtime, row
        Image.new("RGB", (64, 64), (81, 91, 101)).save(output_path, format="PNG")
        return output_path

    monkeypatch.setattr(qr, "_rebuild_saved_composite_from_raw_art", _fake_rebuild)

    hydrated = qr._hydrate_serialized_result_paths(
        runtime=cfg,
        rows=[
            {
                "book_number": 1,
                "variant": 1,
                "model": model,
                "image_path": qr._to_project_relative(image_path),
                "raw_art_path": qr._to_project_relative(raw_path),
                "composited_path": None,
                "saved_composited_path": None,
            }
        ],
    )

    assert hydrated[0]["saved_composited_path"]
    assert (qr.PROJECT_ROOT / str(hydrated[0]["saved_composited_path"])).exists()


def test_hydrate_serialized_result_paths_prefers_verified_saved_composite_over_mutable_tmp(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    model = "openrouter/google/gemini-3-pro-image-preview"
    model_dir = cfg.tmp_dir / "generated" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    model_dir.mkdir(parents=True, exist_ok=True)
    image_path = model_dir / "variant_1.png"
    Image.new("RGB", (64, 64), (21, 31, 41)).save(image_path, format="PNG")

    composite_dir = cfg.tmp_dir / "composited" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    composite_dir.mkdir(parents=True, exist_ok=True)
    mutable_composite = composite_dir / "variant_1.jpg"
    Image.new("RGB", (64, 64), (200, 10, 10)).save(mutable_composite, format="JPEG")

    raw_dir = cfg.output_dir / "raw_art" / "1"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "job-hydrate-safe_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    Image.new("RGB", (64, 64), (81, 91, 101)).save(raw_path, format="PNG")

    stable_source = tmp_path / "stable-source.jpg"
    Image.new("RGB", (64, 64), (12, 140, 220)).save(stable_source, format="JPEG")
    saved_rel = qr._persist_composite_image(
        runtime=cfg,
        book_number=1,
        variant=1,
        model_token="openrouter_google_gemini-3-pro-image-preview",
        composite_source=stable_source,
        job_token="job-hydrate-safe",
        raw_art_source=raw_path,
        raw_art_path_token=qr._to_project_relative(raw_path),
    )
    assert saved_rel

    hydrated = qr._hydrate_serialized_result_paths(
        runtime=cfg,
        rows=[
            {
                "book_number": 1,
                "variant": 1,
                "model": model,
                "image_path": qr._to_project_relative(image_path),
                "raw_art_path": qr._to_project_relative(raw_path),
                "composited_path": qr._to_project_relative(mutable_composite),
                "saved_composited_path": saved_rel,
            }
        ],
    )

    saved_path = qr.PROJECT_ROOT / str(hydrated[0]["saved_composited_path"])
    assert hydrated[0]["composited_path"] == str(saved_rel)
    assert qr._file_sha256(saved_path) == qr._file_sha256(stable_source)


def test_hydrate_serialized_result_paths_repairs_untrusted_saved_composite_from_raw_art(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    model = "openrouter/google/gemini-3-pro-image-preview"
    model_dir = cfg.tmp_dir / "generated" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    model_dir.mkdir(parents=True, exist_ok=True)
    image_path = model_dir / "variant_1.png"
    Image.new("RGB", (64, 64), (21, 31, 41)).save(image_path, format="PNG")

    composite_dir = cfg.tmp_dir / "composited" / "1" / qr.image_generator._model_to_directory(model)  # type: ignore[attr-defined]
    composite_dir.mkdir(parents=True, exist_ok=True)
    mutable_composite = composite_dir / "variant_1.jpg"
    Image.new("RGB", (64, 64), (220, 10, 10)).save(mutable_composite, format="JPEG")

    raw_dir = cfg.output_dir / "raw_art" / "1"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "job-hydrate-repair_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    Image.new("RGB", (64, 64), (81, 91, 101)).save(raw_path, format="PNG")

    saved_dir = cfg.output_dir / "saved_composites" / "1"
    saved_dir.mkdir(parents=True, exist_ok=True)
    saved_path = saved_dir / "job-hydrate-repair_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    Image.new("RGB", (64, 64), (10, 10, 220)).save(saved_path, format="JPEG")

    rebuilt = {"called": False}

    def _fake_rebuild(*, runtime: config.Config, row: dict[str, Any], output_path: Path) -> Path:
        del runtime, row
        rebuilt["called"] = True
        Image.new("RGB", (64, 64), (20, 200, 40)).save(output_path, format="PNG")
        return output_path

    monkeypatch.setattr(qr, "_rebuild_saved_composite_from_raw_art", _fake_rebuild)

    hydrated = qr._hydrate_serialized_result_paths(
        runtime=cfg,
        rows=[
            {
                "book_number": 1,
                "variant": 1,
                "model": model,
                "image_path": qr._to_project_relative(image_path),
                "raw_art_path": qr._to_project_relative(raw_path),
                "composited_path": qr._to_project_relative(mutable_composite),
                "saved_composited_path": qr._to_project_relative(saved_path),
            }
        ],
    )

    assert hydrated[0]["saved_composited_path"] == qr._to_project_relative(saved_path)
    assert hydrated[0]["composited_path"] == qr._to_project_relative(saved_path)
    assert rebuilt["called"] is True
    with Image.open(saved_path) as image:
        assert image.getpixel((0, 0)) == (20, 200, 40)


def test_save_raw_context_repairs_untrusted_saved_composite_before_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 7, "title": "Temple Dawn", "author": "A. Writer"}]),
        encoding="utf-8",
    )
    raw_path = cfg.output_dir / "raw_art" / "7" / "job-safe-raw_variant_1_openrouter_google_gemini-3-pro-image-preview.png"
    comp_path = cfg.output_dir / "saved_composites" / "7" / "job-safe-raw_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    comp_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (12, 34, 56)).save(raw_path, format="PNG")
    Image.new("RGB", (64, 64), (200, 20, 20)).save(comp_path, format="JPEG")

    rebuilt = {"called": False}

    def _fake_rebuild(*, runtime: config.Config, row: dict[str, Any], output_path: Path) -> Path:
        del runtime, row
        rebuilt["called"] = True
        Image.new("RGB", (64, 64), (20, 200, 40)).save(output_path, format="PNG")
        return output_path

    monkeypatch.setattr(qr, "_rebuild_saved_composite_from_raw_art", _fake_rebuild)

    job = qr.job_store.JobRecord(
        id="job-safe-raw",
        idempotency_key="idem-job-safe-raw",
        job_type="generate_cover",
        status="completed",
        catalog_id="classics",
        book_number=7,
        payload={},
        result={
            "results": [
                {
                    "success": True,
                    "variant": 1,
                    "model": "openrouter/google/gemini-3-pro-image-preview",
                    "raw_art_path": qr._to_project_relative(raw_path),
                    "saved_composited_path": qr._to_project_relative(comp_path),
                }
            ]
        },
        error={},
        attempts=1,
        max_attempts=3,
        priority=100,
        retry_after="",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        worker_id="",
    )

    context = qr._save_raw_context_for_job(runtime=cfg, job=job)
    assert rebuilt["called"] is True
    with Image.open(context["comp_source"]) as image:
        assert image.getpixel((0, 0)) == (20, 200, 40)


def test_seed_builtin_prompts_is_retired_and_idempotent(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    seeded = qr._seed_builtin_prompts(runtime=cfg, actor="test", overwrite=False)
    assert seeded["ok"] is True
    assert int(seeded["total_builtins"]) == 0
    assert int(seeded["created"]) == 0
    assert int(seeded["updated"]) == 0
    assert int(seeded["skipped"]) == 0
    library_rows = qr.PromptLibrary(cfg.prompt_library_path).get_prompts()
    names = {str(row.name) for row in library_rows}
    assert "Sevastopol / Dramatic Conflict" not in names
    assert "Cossack / Epic Journey" not in names

    second = qr._seed_builtin_prompts(runtime=cfg, actor="test", overwrite=False)
    assert second["ok"] is True
    assert int(second["created"]) == 0
    assert int(second["total_builtins"]) == 0
    assert int(second["skipped"]) == 0


def test_seed_builtin_prompts_no_longer_repairs_retired_legacy_rows(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.prompt_library_path.write_text(
        json.dumps(
            {
                "style_anchors": [
                    {
                        "name": "fixture-anchor",
                        "description": "fixture",
                        "style_text": "fixture",
                        "tags": ["fixture"],
                    }
                ],
                "prompts": [
                    {
                        "id": "builtin-malformed-1",
                        "name": "Sevastopol / Dramatic Conflict",
                        "prompt_template": (
                            "Create an illustration for {title} by {author}, no, no text, no, no frame, "
                            "dramatic composition."
                        ),
                        "style_anchors": ["sevastopol-dramatic-conflict"],
                        "negative_prompt": "text, no, no, frame, border",
                        "source_book": "builtin",
                        "source_model": "openrouter/google/gemini-3-pro-image-preview",
                        "quality_score": 0.4,
                        "saved_by": "test",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "notes": "malformed fixture",
                        "tags": ["builtin", "builtin_v2", "builtin_v2:sevastopol-dramatic-conflict"],
                        "category": "builtin",
                    }
                ],
                "versions": {},
            }
        ),
        encoding="utf-8",
    )

    seeded = qr._seed_builtin_prompts(runtime=cfg, actor="test", overwrite=False)
    assert seeded["ok"] is True
    assert int(seeded.get("total_builtins", 0)) == 0
    assert int(seeded.get("repaired", 0)) == 0
    assert int(seeded["updated"]) == 0

    rows = qr.PromptLibrary(cfg.prompt_library_path).get_prompts(tags=["builtin_v2:sevastopol-dramatic-conflict"])
    assert rows
    untouched = rows[0]
    assert untouched.id == "builtin-malformed-1"
    assert "no, no" in str(untouched.prompt_template).lower()


def test_save_prompt_from_request_creates_winner_prompt_and_dedupes(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)

    created = qr._save_prompt_from_request(
        runtime=cfg,
        body={
            "job_id": "job-123",
            "book_id": "1",
            "prompt_text": "Book cover illustration only — Lucy Honeychurch embracing George Emerson on a Florentine hillside at sunset.",
            "scene_description": "Lucy Honeychurch embracing George Emerson on a Florentine hillside at sunset.",
            "mood": "romantic, luminous, emotionally urgent",
            "era": "Edwardian Italy",
            "model_id": "openrouter/google/gemini-3-pro-image-preview",
            "library_prompt_id": "alexandria-base-romantic-realism",
            "quality_score": None,
            "notes": "",
        },
    )

    assert created["ok"] is True
    assert created["already_exists"] is False

    library = qr.PromptLibrary(cfg.prompt_library_path)
    saved = library.get_prompt(created["prompt_id"])
    assert saved is not None
    assert saved.category == "winner"
    assert saved.saved_by == "user"
    assert saved.source_book.startswith("Book")
    assert saved.source_model == "openrouter/google/gemini-3-pro-image-preview"
    assert saved.win_count == 1
    assert "winner" in saved.tags
    assert "book" in saved.tags
    assert "base-4-romantic-realism" in saved.tags

    duplicate = qr._save_prompt_from_request(
        runtime=cfg,
        body={
            "job_id": "job-456",
            "book_id": "1",
            "prompt_text": "Book cover illustration only — Lucy Honeychurch embracing George Emerson on a Florentine hillside at sunset.",
            "model_id": "openrouter/google/gemini-3-pro-image-preview",
        },
    )
    assert duplicate["ok"] is True
    assert duplicate["already_exists"] is True
    assert duplicate["prompt_id"] == created["prompt_id"]


def test_save_prompt_from_request_returns_drive_url_when_upload_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    monkeypatch.setattr(
        qr,
        "_upload_saved_prompt_metadata_to_drive",
        lambda **_kwargs: "https://drive.google.com/file/d/prompt-file/view",
    )

    created = qr._save_prompt_from_request(
        runtime=cfg,
        body={
            "job_id": "job-789",
            "book_id": "1",
            "prompt_text": "Book cover illustration only — Lucy Honeychurch and George Emerson on a Florentine hillside at sunset.",
            "model_id": "openrouter/google/gemini-3-pro-image-preview",
        },
    )

    assert created["ok"] is True
    assert created["drive_url"] == "https://drive.google.com/file/d/prompt-file/view"
    assert created["drive_warning"] is None


def test_save_prompt_from_request_keeps_local_save_when_drive_upload_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)

    def _raise_drive_failure(**_kwargs):
        raise RuntimeError("storageQuotaExceeded")

    monkeypatch.setattr(qr, "_upload_saved_prompt_metadata_to_drive", _raise_drive_failure)

    created = qr._save_prompt_from_request(
        runtime=cfg,
        body={
            "job_id": "job-790",
            "book_id": "1",
            "prompt_text": "Book cover illustration only — Lucy Honeychurch alone on a Florentine terrace at blue hour.",
            "model_id": "openrouter/google/gemini-3-pro-image-preview",
        },
    )

    assert created["ok"] is True
    assert created["already_exists"] is False
    assert created["drive_url"] is None
    assert "storageQuotaExceeded" in str(created["drive_warning"])


def test_dashboard_recent_results_includes_prompt_and_style_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    preview = cfg.tmp_dir / "composited" / "1" / "model" / "variant_1.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (12, 34, 56)).save(preview, format="JPEG")

    monkeypatch.setattr(
        qr,
        "_project_path_if_exists",
        lambda token: preview if str(token or "").strip() else None,
    )
    monkeypatch.setattr(qr, "_to_project_relative", lambda _path: "tmp/composited/1/model/variant_1.jpg")
    items = [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "book_number": 1,
            "book_title": "Moby Dick",
            "model": "openrouter/google/gemini-3-pro-image-preview",
            "variant": 1,
            "prompt": "Cossack epic journey with dramatic cobalt lighting",
            "quality_score": 0.82,
            "cost": 0.01,
            "image_path": "tmp/generated/1/model/variant_1.png",
            "composited_path": "tmp/composited/1/model/variant_1.jpg",
        }
    ]
    rows = qr._dashboard_recent_results(items=items, runtime=cfg, limit=10)
    assert len(rows) == 1
    assert rows[0]["book_title"] == "Moby Dick"
    assert "thumbnail_url" in rows[0]
    assert "Cossack" in rows[0]["style_tags"]


def test_dashboard_recent_results_orders_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    preview = cfg.tmp_dir / "composited" / "1" / "model" / "variant_1.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (18, 52, 86)).save(preview, format="JPEG")

    monkeypatch.setattr(qr, "_project_path_if_exists", lambda token: preview if str(token or "").strip() else None)
    monkeypatch.setattr(qr, "_to_project_relative", lambda _path: "tmp/composited/1/model/variant_1.jpg")

    items = [
        {
            "timestamp": "2026-03-01T09:00:00+00:00",
            "book_number": 1,
            "book_title": "Older Result",
            "model": "openrouter/google/gemini-3-pro-image-preview",
            "variant": 1,
            "prompt": "Older style prompt",
            "quality_score": 0.7,
            "cost": 0.01,
            "image_path": "tmp/generated/1/model/variant_1.png",
            "composited_path": "tmp/composited/1/model/variant_1.jpg",
        },
        {
            "timestamp": "2026-03-01T10:00:00+00:00",
            "book_number": 2,
            "book_title": "Newest Result",
            "model": "openrouter/google/gemini-3-pro-image-preview",
            "variant": 1,
            "prompt": "Newest style prompt",
            "quality_score": 0.8,
            "cost": 0.01,
            "image_path": "tmp/generated/1/model/variant_1.png",
            "composited_path": "tmp/composited/1/model/variant_1.jpg",
        },
    ]

    rows = qr._dashboard_recent_results(items=items, runtime=cfg, limit=10)
    assert len(rows) == 2
    assert rows[0]["book_title"] == "Newest Result"
    assert rows[1]["book_title"] == "Older Result"


def test_dashboard_recent_results_ignores_unresolved_duplicate_until_valid_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    preview = cfg.tmp_dir / "composited" / "7" / "openrouter__google__gemini-3-pro-image-preview" / "variant_3.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (33, 66, 99)).save(preview, format="JPEG")

    def _fake_project_path(token: str | Path | None):  # type: ignore[no-untyped-def]
        raw = str(token or "").strip()
        if not raw or "missing-asset" in raw:
            return None
        path = Path(raw)
        if path.exists():
            return path
        maybe = qr.PROJECT_ROOT / raw.lstrip("/")
        if maybe.exists():
            return maybe
        return None

    monkeypatch.setattr(qr, "_project_path_if_exists", _fake_project_path)
    monkeypatch.setattr(qr, "_to_project_relative", lambda _path: "tmp/composited/7/openrouter__google__gemini-3-pro-image-preview/variant_3.jpg")
    monkeypatch.setattr(qr.job_db_store, "list_jobs", lambda **_kwargs: [])

    items = [
        {
            "timestamp": "2026-03-02T10:00:00+00:00",
            "book_number": 7,
            "book_title": "Stale",
            "model": "openrouter/google/gemini-3-pro-image-preview",
            "variant": 3,
            "image_path": "missing-asset.png",
            "composited_path": "missing-asset.jpg",
            "prompt": "broken path row",
        },
        {
            "timestamp": "2026-03-02T09:00:00+00:00",
            "book_number": 7,
            "book_title": "Valid",
            "model": "openrouter/google/gemini-3-pro-image-preview",
            "variant": 3,
            "image_path": "",
            "composited_path": str(preview),
            "prompt": "valid fallback row",
        },
    ]

    rows = qr._dashboard_recent_results(items=items, runtime=cfg, limit=10)
    assert len(rows) == 1
    assert rows[0]["book_title"] == "Valid"
    assert rows[0]["image_url"].endswith("variant_3.jpg")


def test_dashboard_recent_results_falls_back_to_file_discovery_when_items_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    discovered = cfg.tmp_dir / "composited" / "2" / "openrouter__google__gemini-2.5-flash-image" / "variant_1.jpg"
    discovered.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (55, 77, 99)).save(discovered, format="JPEG")

    def _fake_project_path(token: str | Path | None):  # type: ignore[no-untyped-def]
        raw = str(token or "").strip()
        if not raw or "missing-asset" in raw:
            return None
        path = Path(raw)
        if path.exists():
            return path
        maybe = qr.PROJECT_ROOT / raw.lstrip("/")
        if maybe.exists():
            return maybe
        return None

    monkeypatch.setattr(qr, "_project_path_if_exists", _fake_project_path)
    monkeypatch.setattr(qr.job_db_store, "list_jobs", lambda **_kwargs: [])

    rows = qr._dashboard_recent_results(
        items=[
            {
                "timestamp": "2026-03-02T10:00:00+00:00",
                "book_number": 2,
                "book_title": "Unresolved persisted row",
                "model": "openrouter/google/gemini-2.5-flash-image",
                "variant": 1,
                "image_path": "missing-asset.png",
                "composited_path": "missing-asset.jpg",
                "prompt": "",
            }
        ],
        runtime=cfg,
        limit=10,
    )
    assert rows
    assert any(int(row.get("book_number", 0)) == 2 for row in rows)
    assert any(str(row.get("image_url", "")).endswith(".jpg") for row in rows)


def test_dashboard_recent_results_falls_back_to_composited_files_when_records_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    preview = cfg.tmp_dir / "composited" / "2" / "openrouter__google__gemini-2.5-flash-image" / "variant_1.jpg"
    preview.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (44, 88, 132)).save(preview, format="JPEG")
    monkeypatch.setattr(qr.state_db_store, "list_generation_records", lambda **_kwargs: [])
    monkeypatch.setattr(qr.job_db_store, "list_jobs", lambda **_kwargs: [])

    rows = qr._dashboard_recent_results(items=[], runtime=cfg, limit=10)
    assert len(rows) >= 1
    assert any(int(row.get("book_number", 0)) == 2 for row in rows)
    assert any(str(row.get("image_url", "")).endswith(".jpg") for row in rows)


def test_prune_stale_generated_variants_for_book_keeps_current_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    generated_root = cfg.tmp_dir / "generated" / "2" / "model-a"
    generated_root.mkdir(parents=True, exist_ok=True)
    keep_file = generated_root / "variant_1.png"
    stale_file = generated_root / "variant_2.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(keep_file, format="PNG")
    Image.new("RGB", (64, 64), (40, 50, 60)).save(stale_file, format="PNG")

    monkeypatch.setattr(qr, "_project_path_if_exists", lambda token: Path(token) if str(token or "").strip() else None)
    rows = [{"image_path": str(keep_file)}]
    keep_paths = qr._current_run_generated_paths(runtime=cfg, rows=rows)
    qr._prune_stale_generated_variants_for_book(runtime=cfg, book_number=2, keep_paths=keep_paths)

    assert keep_file.exists()
    assert not stale_file.exists()


def test_assert_composite_validation_within_limits_allows_edge_artifact_only(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    report_path = cfg.tmp_dir / "composited" / "3" / "composite_validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "book_number": 3,
        "total": 1,
        "invalid": 1,
        "items": [
            {
                "output_path": "tmp/composited/3/model/variant_1.jpg",
                "valid": False,
                "issues": ["edge_artifact_risk"],
            }
        ],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    qr._assert_composite_validation_within_limits(runtime=cfg, book_number=3)


def _build_runtime_for_startup_checks(tmp_path: Path) -> config.Config:
    base = tmp_path / "runtime"
    input_dir = base / "Input Covers"
    output_dir = base / "Output Covers"
    tmp_dir = base / "tmp"
    data_dir = base / "data"
    config_dir = base / "config"

    for path in (input_dir, output_dir, tmp_dir, data_dir, config_dir):
        path.mkdir(parents=True, exist_ok=True)

    catalog_path = config_dir / "book_catalog.json"
    prompts_path = config_dir / "book_prompts.json"
    library_path = config_dir / "prompt_library.json"

    catalog_path.write_text(json.dumps([{"number": 1, "title": "Book", "author": "Author"}]), encoding="utf-8")
    prompts_path.write_text(json.dumps({"1": {"variants": []}}), encoding="utf-8")
    library_path.write_text(json.dumps({"prompts": [], "style_anchors": []}), encoding="utf-8")

    cfg = config.get_config()
    cfg = replace(
        cfg,
        input_dir=input_dir,
        output_dir=output_dir,
        tmp_dir=tmp_dir,
        data_dir=data_dir,
        config_dir=config_dir,
        book_catalog_path=catalog_path,
        prompts_path=prompts_path,
        prompt_library_path=library_path,
        openrouter_api_key="",
        openai_api_key="",
        google_api_key="",
        fal_api_key="",
        replicate_api_token="",
    )
    return cfg


def test_run_startup_checks_healthy_with_valid_runtime_layout(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    report = qr._run_startup_checks(cfg)
    assert report["healthy"] is True
    assert isinstance(report["checks"], list)
    assert any(row["name"] == "book_catalog_json" and row["ok"] for row in report["checks"])
    assert any(row["name"] == "prompts_json" and row["ok"] for row in report["checks"])
    assert any(row["name"] == "enrichment_coverage" for row in report["checks"])


def test_run_startup_checks_reports_missing_prompts_as_issue(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, prompts_path=tmp_path / "missing" / "book_prompts.json")
    report = qr._run_startup_checks(cfg)
    assert report["healthy"] is False
    assert any("prompts" in issue for issue in report["issues"])


def test_enrichment_health_payload_counts_real_generic_missing_and_running(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps(
            [
                {"number": 1, "title": "Book One", "author": "Author A"},
                {"number": 2, "title": "Book Two", "author": "Author B"},
                {"number": 3, "title": "Book Three", "author": "Author C"},
            ]
        ),
        encoding="utf-8",
    )
    enriched_path = config.enriched_catalog_path(catalog_id=cfg.catalog_id, config_dir=cfg.config_dir)
    enriched_path.write_text(
        json.dumps(
            [
                {
                    "number": 1,
                    "enrichment": {
                        "protagonist": "Victor Frankenstein",
                        "iconic_scenes": ["scene one", "scene two", "scene three"],
                    },
                },
                {
                    "number": 2,
                    "enrichment": {
                        "protagonist": "central protagonist",
                        "iconic_scenes": ["scene one", "scene two", "scene three"],
                    },
                },
            ]
        ),
        encoding="utf-8",
    )

    class _AliveThread:
        def is_alive(self) -> bool:
            return True

    with qr._CATALOG_ENRICHMENT_THREADS_LOCK:
        previous = dict(qr._CATALOG_ENRICHMENT_RUN_STATUS)
        previous_threads = dict(qr._CATALOG_ENRICHMENT_THREADS)
        qr._CATALOG_ENRICHMENT_RUN_STATUS[cfg.catalog_id] = {
            "catalog": cfg.catalog_id,
            "status": "running",
            "running": True,
            "books": [2, 3],
        }
        qr._CATALOG_ENRICHMENT_THREADS[cfg.catalog_id] = _AliveThread()  # type: ignore[assignment]

    try:
        payload = qr._enrichment_health_payload(runtime=cfg)
    finally:
        with qr._CATALOG_ENRICHMENT_THREADS_LOCK:
            qr._CATALOG_ENRICHMENT_RUN_STATUS.clear()
            qr._CATALOG_ENRICHMENT_RUN_STATUS.update(previous)
            qr._CATALOG_ENRICHMENT_THREADS.clear()
            qr._CATALOG_ENRICHMENT_THREADS.update(previous_threads)

    assert payload["ok"] is True
    assert payload["health"] == "critical"
    assert payload["total_books"] == 3
    assert payload["enriched_real"] == 1
    assert payload["enriched_generic"] == 1
    assert payload["no_enrichment"] == 1
    assert payload["books_needing_reenrichment"] == [2, 3]
    assert payload["run_status"]["running"] is True


def test_health_payload_includes_startup_checks(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    original_startup = dict(qr.STARTUP_HEALTH)
    try:
        qr.STARTUP_HEALTH = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "healthy": False,
            "issues": ["prompts missing"],
            "warnings": [],
            "checks": [],
        }
        payload = qr._health_payload(runtime=cfg)
        assert payload["healthy"] is False
        assert "startup_checks" in payload
        assert payload["startup_checks"]["issues"] == ["prompts missing"]
    finally:
        qr.STARTUP_HEALTH = original_startup


def test_startup_healthz_payload_reports_initializing_without_catalog_reads(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    original_startup = dict(qr.STARTUP_HEALTH)
    original_state = qr._startup_state_snapshot()
    try:
        qr.STARTUP_HEALTH = {}
        qr._set_startup_state(status="initializing", started_at="2026-03-09T00:00:00+00:00", completed_at="", error="")
        payload = qr._startup_healthz_payload(runtime=cfg)
        assert payload["ok"] is True
        assert payload["healthy"] is True
        assert payload["startup"]["status"] == "initializing"
        assert payload["startup"]["checks_completed"] is False
    finally:
        qr.STARTUP_HEALTH = original_startup
        qr._set_startup_state(
            status=str(original_state.get("status", "idle") or "idle"),
            started_at=str(original_state.get("started_at", "") or ""),
            completed_at=str(original_state.get("completed_at", "") or ""),
            error=str(original_state.get("error", "") or ""),
        )


def test_health_payload_includes_structured_drive_connectivity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, gdrive_source_folder_id="source-folder-id")
    monkeypatch.setattr(qr, "_resolve_credentials_path", lambda _runtime: tmp_path / "creds.json")
    monkeypatch.setattr(qr, "_drive_credentials_mode", lambda *_args, **_kwargs: ("service_account_env", ""))
    monkeypatch.setattr(qr.gdrive_sync, "authenticate", lambda *_args, **_kwargs: object())

    payload = qr._health_payload(runtime=cfg)
    drive = payload.get("drive", {})
    assert isinstance(drive, dict)
    assert drive.get("connected") is True
    assert drive.get("source_folder_id") == "source-folder-id"
    assert drive.get("credential_type") == "service_account_env"
    assert payload.get("drive_connection") == "connected"


def test_health_payload_degrades_when_external_worker_offline_with_pending_jobs(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    original_startup = dict(qr.STARTUP_HEALTH)
    try:
        qr.STARTUP_HEALTH = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "healthy": True,
            "issues": [],
            "warnings": [],
            "checks": [],
        }
        monkeypatch.setattr(
            qr,
            "_worker_runtime_status",
            lambda **_kwargs: {
                "mode": "external",
                "alive": False,
                "updated_at": "",
                "worker_count": 0,
            },
        )
        monkeypatch.setattr(qr.job_db_store, "status_counts", lambda: {"queued": 2, "retrying": 1, "running": 0, "completed": 0, "failed": 0, "cancelled": 0})
        monkeypatch.setattr(
            qr.job_db_store,
            "slo_summary",
            lambda **_kwargs: {
                "window_days": 7,
                "completion_without_manual_intervention": 1.0,
                "same_stage_retry_rate": 0.0,
                "terminal_total": 0,
                "retry_jobs": 0,
            },
        )
        payload = qr._health_payload(runtime=cfg)
        assert payload["healthy"] is False
        assert payload["status"] == "degraded"
        assert payload["runtime_issues"]
    finally:
        qr.STARTUP_HEALTH = original_startup


def test_provider_runtime_payload_includes_defaults_and_rate_windows(monkeypatch: pytest.MonkeyPatch):
    runtime = SimpleNamespace(
        provider_keys={
            "openrouter": "",
            "fal": "",
            "replicate": "",
            "openai": "key-openai",
            "google": "",
        }
    )
    monkeypatch.setattr(
        qr.image_generator,
        "get_provider_runtime_stats",
        lambda: {
            "openai": {
                "requests_today": 4,
                "errors_today": 1,
                "state": "open",
                "consecutive_failures": 2,
                "cooldown_remaining_seconds": 12.5,
                "open_events": 3,
                "probe_in_flight": False,
                "rate_limit_window_second": 1,
                "rate_limit_window_minute": 7,
                "last_error": "temporary outage",
                "opened_until_utc": "2026-02-23T00:00:00+00:00",
            },
            "custom-provider": {
                "requests_today": 2,
                "errors_today": 0,
                "state": "closed",
                "rate_limit_window_second": 0,
                "rate_limit_window_minute": 1,
            },
        },
    )

    payload = qr._provider_runtime_payload(runtime=runtime)
    assert payload["openai"]["status"] == "active"
    assert payload["openai"]["requests_today"] == 4
    assert payload["openai"]["circuit_state"] == "open"
    assert payload["openai"]["rate_limit_window_minute"] == 7
    assert payload["openrouter"]["status"] == "inactive"
    assert payload["openrouter"]["requests_today"] == 0
    assert "replicate" not in payload
    assert payload["custom-provider"]["status"] == "inactive"
    assert payload["custom-provider"]["reason"] == "no API key"


def test_provider_connectivity_payload_caches_for_five_minutes(monkeypatch: pytest.MonkeyPatch):
    runtime = SimpleNamespace(
        catalog_id="classics",
        provider_keys={"openrouter": "k1", "fal": "k2", "openai": "k3", "google": "k4"},
        all_models=[
            "openrouter/google/gemini-2.5-flash-image",
            "fal/fal-ai/flux-2/klein/4b",
            "openai/gpt-image-1-mini",
            "google/gemini-2.5-flash-image",
        ],
        resolve_model_provider=lambda model: str(model).split("/", 1)[0],  # type: ignore[return-value]
    )
    monkeypatch.setattr(qr, "_provider_connectivity_cache", {})
    monkeypatch.setattr(qr, "PROVIDER_CONNECTIVITY_CACHE_SECONDS", 300)

    calls = {"count": 0}

    def _fake_test_api_keys(*, runtime, providers):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return {
            "providers": [
                {"provider": "openrouter", "status": "KEY_VALID", "detail": "ok"},
                {"provider": "fal", "status": "KEY_INVALID", "detail": "Balance exhausted"},
                {"provider": "openai", "status": "KEY_VALID", "detail": "ok"},
                {"provider": "google", "status": "KEY_VALID", "detail": "ok"},
            ]
        }

    monkeypatch.setattr(qr.pipeline_runner, "test_api_keys", _fake_test_api_keys)

    first = qr._provider_connectivity_payload(runtime=runtime, force=False)
    second = qr._provider_connectivity_payload(runtime=runtime, force=False)
    forced = qr._provider_connectivity_payload(runtime=runtime, force=True)

    assert first["ok"] is True
    assert first["cached"] is False
    assert second["cached"] is True
    assert forced["cached"] is False
    assert first["providers"]["fal"]["status"] == "error"
    assert "Balance exhausted" in str(first["providers"]["fal"]["error"])
    assert calls["count"] == 2


def test_job_event_broker_publish_subscribe_roundtrip():
    broker = qr.JobEventBroker(max_queue_size=2)
    token, client_queue = broker.subscribe()
    delivered = broker.publish("job_started", {"job_id": "job-1", "catalog_id": "classics", "progress": 0.0})
    assert delivered == 1
    event = client_queue.get(timeout=1.0)
    assert event["event"] == "job_started"
    assert event["job_id"] == "job-1"
    broker.unsubscribe(token)
    assert broker.publish("job_completed", {"job_id": "job-1"}) == 0


def test_job_event_broker_drops_oldest_when_queue_full():
    broker = qr.JobEventBroker(max_queue_size=10)
    token, client_queue = broker.subscribe()
    for idx in range(11):
        broker.publish("job_progress", {"job_id": "job-1", "progress": idx / 10.0})
    first = client_queue.get(timeout=1.0)
    assert first["event"] == "job_progress"
    assert first["progress"] == 0.1
    latest = first
    while True:
        try:
            latest = client_queue.get_nowait()
        except queue.Empty:
            break
    assert latest["progress"] == 1.0
    broker.unsubscribe(token)


def test_write_iterate_data_includes_variant_limits_and_catalog_scoped_files(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, catalog_id="demo", variants_per_cover=7, max_generation_variants=33)

    demo_prompts = {
        "books": [
            {
                "number": 1,
                "title": "Demo Book",
                "author": "Author",
                "variants": [{"prompt": "Base prompt"}],
            }
        ]
    }
    cfg.prompts_path.write_text(json.dumps(demo_prompts), encoding="utf-8")

    enriched_path = config.enriched_catalog_path(catalog_id=cfg.catalog_id, config_dir=cfg.config_dir)
    enriched_path.write_text(json.dumps([{"number": 1, "enrichment": {"genre": ["Novel"]}}]), encoding="utf-8")

    intelligent_path = config.intelligent_prompts_path(catalog_id=cfg.catalog_id, config_dir=cfg.config_dir)
    intelligent_path.write_text(
        json.dumps({"books": [{"number": 1, "variants": [{"variant_id": 1, "prompt": "Smart prompt"}]}]}),
        encoding="utf-8",
    )

    iterate_path = config.iterate_data_path(catalog_id=cfg.catalog_id, data_dir=cfg.data_dir)
    output = qr.write_iterate_data(runtime=cfg, prompts_path=cfg.prompts_path)
    assert output == iterate_path

    payload = json.loads(iterate_path.read_text(encoding="utf-8"))
    assert payload["default_variants_per_model"] == 7
    assert payload["max_generation_variants"] == 33
    assert payload["catalog"] == "demo"
    assert payload["default_cover_source"] == "drive"
    assert payload["local_input_covers_available"] is False
    assert payload["books"][0]["enrichment"]["genre"] == ["Novel"]
    assert payload["books"][0]["smart_prompts"][0]["prompt"] == "Smart prompt"


def test_quality_review_runtime_path_helpers_are_catalog_scoped(tmp_path: Path):
    runtime = SimpleNamespace(catalog_id="demo", data_dir=tmp_path)
    assert qr._review_data_path_for_runtime(runtime) == (tmp_path / "review_data_demo.json")
    assert qr._iterate_data_path_for_runtime(runtime) == (tmp_path / "iterate_data_demo.json")
    assert qr._compare_data_path_for_runtime(runtime) == (tmp_path / "compare_data_demo.json")
    assert qr._selection_path_for_runtime(runtime) == (tmp_path / "variant_selections_demo.json")
    assert qr._review_stats_path_for_runtime(runtime) == (tmp_path / "review_stats_demo.json")
    assert qr._similarity_hashes_path_for_runtime(runtime) == (tmp_path / "cover_hashes_demo.json")
    assert qr._similarity_matrix_path_for_runtime(runtime) == (tmp_path / "similarity_matrix_demo.json")
    assert qr._similarity_clusters_path_for_runtime(runtime) == (tmp_path / "similarity_clusters_demo.json")
    assert qr._similarity_dismissed_path_for_runtime(runtime) == (tmp_path / "similarity_dismissed_demo.json")
    assert qr._llm_usage_path_for_runtime(runtime) == (tmp_path / "llm_usage_demo.json")
    assert qr._cost_ledger_path_for_runtime(runtime) == (tmp_path / "cost_ledger_demo.json")
    assert qr._budget_config_path_for_runtime(runtime) == (tmp_path / "budget_config_demo.json")
    assert qr._delivery_config_path_for_runtime(runtime) == (tmp_path / "delivery_pipeline_demo.json")
    assert qr._delivery_tracking_path_for_runtime(runtime) == (tmp_path / "delivery_tracking_demo.json")
    assert qr._report_schedules_path_for_runtime(runtime) == (tmp_path / "report_schedules_demo.json")
    assert qr._slo_metrics_path_for_runtime(runtime) == (tmp_path / "slo_metrics_demo.json")
    assert qr._slo_alert_state_path_for_runtime(runtime) == (tmp_path / "slo_alert_state_demo.json")
    assert qr._review_sessions_dir_for_runtime(runtime) == (qr.REVIEW_SESSIONS_DIR / "demo")

    classics = SimpleNamespace(catalog_id="classics", data_dir=tmp_path)
    assert qr._review_sessions_dir_for_runtime(classics) == qr.REVIEW_SESSIONS_DIR


def test_cover_preview_helpers_build_thumbnail_file(tmp_path: Path):
    runtime = SimpleNamespace(catalog_id="demo", tmp_dir=tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (1200, 900), color=(12, 34, 56)).save(source)

    preview_path = qr._cover_preview_path_for_runtime(runtime=runtime, book_number=7, source="drive")
    assert preview_path == (tmp_path / "cover_previews" / "demo_7_drive.jpg")

    written = qr._write_cover_preview(source_image=source, preview_path=preview_path, max_size=320)
    assert written.exists()
    with Image.open(written) as rendered:
        assert rendered.width <= 320
        assert rendered.height <= 320


def test_resolve_cover_preview_source_path_returns_not_found_for_missing_book(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    resolved, status, meta = qr._resolve_cover_preview_source_path(runtime=cfg, book_number=99999, source="catalog")
    assert resolved is None
    assert status == 404
    assert "not found" in str(meta.get("error", "")).lower()


def test_resolve_cover_preview_source_path_returns_service_unavailable_when_source_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg.book_catalog_path.write_text(
        json.dumps([{"number": 1, "title": "Book", "author": "Author", "folder_name": "Book 1"}]),
        encoding="utf-8",
    )
    with qr._JSON_LIST_ROWS_CACHE_LOCK:
        qr._JSON_LIST_ROWS_CACHE.clear()
    monkeypatch.setattr(qr.drive_manager, "ensure_local_input_cover", lambda **_kwargs: {"ok": False, "error": "No source cover is available for book 1."})
    resolved, status, meta = qr._resolve_cover_preview_source_path(runtime=cfg, book_number=1, source="catalog")
    assert resolved is None
    assert status == 503
    assert "no source cover" in str(meta.get("error", "")).lower()


def test_load_visual_qa_payload_does_not_generate_on_cache_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    generate_calls = {"visual": 0, "structural": 0}

    def _unexpected_visual(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        generate_calls["visual"] += 1
        raise AssertionError("visual QA generation should not run on GET cache miss")

    def _unexpected_structural(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        generate_calls["structural"] += 1
        raise AssertionError("structural QA generation should not run on GET cache miss")

    monkeypatch.setattr(qr, "_generate_visual_qa", _unexpected_visual)
    monkeypatch.setattr(qr, "_generate_structural_visual_qa", _unexpected_structural)

    payload = qr._load_visual_qa_payload(runtime=cfg, force_generate=False, book_number=1)
    assert payload["comparisons"] == []
    assert payload["message"] == "No generated images available for this book. Generate covers first."
    assert generate_calls == {"visual": 0, "structural": 0}


def test_visual_qa_image_path_reads_index_without_triggering_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    visual_dir = qr._visual_qa_dir_for_runtime(cfg)
    visual_dir.mkdir(parents=True, exist_ok=True)
    image_path = visual_dir / "compare_001.jpg"
    Image.new("RGB", (128, 128), color=(100, 120, 140)).save(image_path)
    qr._visual_qa_index_path_for_runtime(cfg).write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "book_number": 1,
                        "book_title": "Book",
                        "comparison_path": qr._to_project_relative(image_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        qr,
        "_generate_visual_qa",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("visual QA generation should not run when resolving image paths")),
    )

    resolved = qr._visual_qa_image_path(runtime=cfg, book_number=1)
    assert resolved == image_path


def test_ensure_winner_payload_writes_catalog_scoped_plain_selection_map(tmp_path: Path):
    winner_path = tmp_path / "winner_selections_demo.json"
    books = [
        {
            "number": 1,
            "variants": [
                {"variant": 1, "quality_score": 0.9},
                {"variant": 2, "quality_score": 0.2},
            ],
        }
    ]
    payload = qr._ensure_winner_payload(books, path=winner_path)
    assert payload["selections"]["1"]["winner"] == 1
    plain_path = tmp_path / "variant_selections_demo.json"
    plain = json.loads(plain_path.read_text(encoding="utf-8"))
    assert plain == {"1": 1}


def test_save_winner_payload_writes_payload_and_plain_map_in_single_staged_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    winner_path = tmp_path / "winner_selections_demo.json"
    selections = {"1": {"winner": 2, "score": 0.88}, "2": {"winner": 1, "score": 0.73}}
    calls: list[list[Path]] = []

    def _fake_upsert(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    def _fake_atomic_many(items):  # type: ignore[no-untyped-def]
        calls.append([path for path, _ in items])
        for path, payload in items:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(qr.state_db_store, "upsert_winner_selections", _fake_upsert)
    monkeypatch.setattr(qr.safe_json, "atomic_write_many_json", _fake_atomic_many)

    payload = qr._save_winner_payload(winner_path, selections, total_books=2)

    assert payload["total_books"] == 2
    assert len(calls) == 1
    assert calls[0] == [winner_path, (tmp_path / "variant_selections_demo.json")]
    plain = json.loads((tmp_path / "variant_selections_demo.json").read_text(encoding="utf-8"))
    assert plain == {"1": 2, "2": 1}


def test_record_audit_event_uses_runtime_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    captured: dict[str, object] = {}

    def _fake_append_event(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)

    monkeypatch.setattr(qr.audit_log, "append_event", _fake_append_event)
    qr._record_audit_event(
        action="test_action",
        impact="cost",
        actor="tester",
        source_ip="127.0.0.1",
        endpoint="/api/test",
        catalog_id="demo",
        status="ok",
        details={"note": "demo"},
        data_dir=tmp_path,
    )

    assert captured.get("catalog_id") == "demo"
    assert captured.get("path") == (tmp_path / "audit_log_demo.json")


def test_api_docs_include_catalog_routes():
    html = qr._build_api_docs_html()
    assert "/catalogs" in html
    assert "/api/generate-catalog" in html
    assert "/api/jobs/{id}" in html
    assert "/api/models" in html
    assert "/api/providers" in html
    assert "/api/catalog" in html
    assert "/api/templates" in html
    assert "/api/stats" in html
    assert "/api/config" in html
    assert "/api/validate/cover" in html
    assert "/api/metrics" in html
    assert "/api/providers/runtime" in html
    assert "/api/workers" in html
    assert "/api/audit-log" in html
    assert "/api/export/amazon" in html
    assert "/api/delivery/status" in html
    assert "/api/storage/usage" in html
    assert "/api/providers/reset" in html


def test_execute_generation_payload_validates_book():
    with pytest.raises(ValueError):
        qr._execute_generation_payload({"catalog": "classics", "book": 0})


def test_execute_generation_payload_validates_variants_cap(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, max_generation_variants=12)
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)
    with pytest.raises(ValueError, match="between 1 and 12"):
        qr._execute_generation_payload(
            {
                "catalog": "classics",
                "book": 1,
                "models": ["openrouter/flux-2-pro"],
                "variants": 13,
                "prompt": "test",
                "provider": "all",
                "dry_run": True,
            }
        )


def test_execute_generation_payload_rejects_unknown_template_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, max_generation_variants=12)
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)
    with pytest.raises(ValueError, match="Unknown template_id"):
        qr._execute_generation_payload(
            {
                "catalog": "classics",
                "book": 1,
                "models": ["openrouter/flux-2-pro"],
                "variants": 1,
                "prompt": "test",
                "provider": "all",
                "dry_run": True,
                "template_id": "not-real-template",
            }
        )


def test_resolve_alexandria_placeholders_uses_enrichment_fields():
    resolved = qr._resolve_alexandria_placeholders(
        "Book cover illustration only — {SCENE}. The mood is {MOOD}. Era reference: {ERA}.",
        {
            "title": "Gulliver's Travels",
            "author": "Jonathan Swift",
            "enrichment": {
                "iconic_scenes": ["Gulliver bound by tiny ropes in Lilliput"],
                "emotional_tone": "satirical wonder with unease",
                "era": "18th-century voyage literature",
            },
        },
    )

    assert "{SCENE}" not in resolved
    assert "Gulliver bound by tiny ropes in Lilliput" in resolved
    assert "satirical wonder with unease" in resolved
    assert "18th-century voyage literature" in resolved


def test_sanitize_prompt_placeholders_logs_and_replaces(caplog: pytest.LogCaptureFixture):
    book = {
        "title": "Gulliver's Travels",
        "author": "Jonathan Swift",
        "enrichment": {
            "iconic_scenes": ["Gulliver bound by tiny ropes in Lilliput"],
            "emotional_tone": "satirical wonder with unease",
            "era": "18th-century voyage literature",
        },
    }

    with caplog.at_level("WARNING"):
        resolved = qr._sanitize_prompt_placeholders(
            "Book cover illustration only — {SCENE}. The mood is {MOOD}. Era reference: {ERA}.",
            book,
        )

    assert "{SCENE}" not in resolved
    assert "Gulliver bound by tiny ropes in Lilliput" in resolved
    assert "satirical wonder with unease" in resolved
    assert "18th-century voyage literature" in resolved
    assert "Sanitized unresolved placeholder {SCENE}" in caplog.text
    assert "Sanitized unresolved placeholder {MOOD}" in caplog.text
    assert "Sanitized unresolved placeholder {ERA}" in caplog.text


def test_validate_prompt_before_generation_flags_generic_and_unresolved_content(caplog: pytest.LogCaptureFixture):
    book = {"title": "Emma"}
    with caplog.at_level("WARNING"):
        valid, warnings = qr._validate_prompt_before_generation(
            "Book cover illustration only — {SCENE}. Central protagonist in a pivotal narrative tableau.",
            book,
        )

    assert valid is False
    assert any("Unresolved placeholder" in warning for warning in warnings)
    assert any("Generic content" in warning for warning in warnings)
    assert any("Scene content does not appear" in warning for warning in warnings)
    assert "Prompt validation warnings for 'Emma'" in caplog.text


def test_ensure_enriched_prompt_replaces_generic_scene_and_mood():
    book = {
        "title": "Gulliver's Travels",
        "author": "Jonathan Swift",
        "enrichment": {
            "iconic_scenes": [
                "Gulliver bound by tiny ropes in Lilliput while miniature figures swarm over him",
                "Gulliver stands before the giant court of Brobdingnag while nobles crowd around him",
            ],
            "protagonist": "Gulliver",
            "setting_primary": "the shore of Lilliput",
            "emotional_tone": "satirical wonder with unease",
            "era": "18th-century voyage literature",
        },
    }

    resolved = qr._ensure_enriched_prompt(
        'Create a colorful circular medallion illustration for "Gulliver\'s Travels" by Jonathan Swift. '
        'A pivotal dramatic moment from the literary work "Gulliver\'s Travels" by Jonathan Swift, '
        'depicting the central emotional conflict with period-accurate setting, costume, and atmosphere. '
        'Mood: classical, timeless, evocative.',
        book,
        variant_index=1,
    )

    assert "A pivotal dramatic moment from the literary work" not in resolved
    assert "Brobdingnag" in resolved
    assert "satirical wonder with unease" in resolved


def test_ensure_prompt_book_context_rotates_scene_anchor_for_variant():
    book = {
        "title": "Gulliver's Travels",
        "author": "Jonathan Swift",
        "enrichment": {
            "iconic_scenes": [
                "Gulliver bound by tiny ropes in Lilliput while miniature figures swarm over him",
                "Gulliver stands before the giant court of Brobdingnag while nobles crowd around him",
            ],
        },
    }

    resolved = qr._ensure_prompt_book_context(
        prompt="Painterly scene with atmospheric depth.",
        book=book,
        require_motif=True,
        variant_index=1,
    )

    assert "CRITICAL SCENE REQUIREMENT" in resolved
    assert "Brobdingnag" in resolved
    assert "Lilliput" not in resolved


def test_ensure_prompt_book_context_preserves_scene_first_prompt_order():
    book = {
        "title": "Emma",
        "author": "Jane Austen",
        "enrichment": {
            "iconic_scenes": [
                "Emma Woodhouse and Harriet Smith walk through the gardens of Hartfield at sunset",
            ],
            "emotional_tone": "witty romantic self-discovery",
            "era": "Regency England",
        },
    }

    prompt = (
        "Book cover illustration only - no text, no title, no author name, no lettering of any kind. "
        "No border, no frame, no ornamental elements. "
        "This circular medallion illustration MUST depict the following specific scene: {SCENE}. "
        "Every figure, object, and setting element in this scene must be clearly recognizable and faithful to the source material. "
        "Rendered in Romantic Realism style - luminous regency atmosphere. "
        "The mood is {MOOD}. Era reference: {ERA}. "
        "Circular vignette composition with soft edges. Square format, high resolution, print-ready."
    )

    resolved = qr._ensure_prompt_book_context(
        prompt=prompt,
        book=book,
        require_motif=True,
        variant_index=0,
    )

    assert resolved.startswith("Book cover illustration only")
    assert "Illustration for 'Emma'" not in resolved
    assert "CRITICAL SCENE REQUIREMENT" not in resolved


def test_is_generic_enrichment_detects_placeholder_payload():
    assert qr._is_generic_enrichment(
        {
            "iconic_scenes": ["Iconic turning point in the story with classical dramatic tension"],
            "protagonist": "Central protagonist",
            "era": "Historically grounded era",
        }
    ) is True

    assert qr._is_generic_enrichment(
        {
            "iconic_scenes": ["Emma Woodhouse humiliates Miss Bates on Box Hill before Mr. Knightley intervenes"],
            "protagonist": "Emma Woodhouse",
            "era": "Regency England",
        }
    ) is False


def test_alexandria_placeholder_replacements_fall_back_to_book_motif_when_enrichment_is_generic():
    replacements = qr._alexandria_placeholder_replacements(
        {
            "title": "Moby Dick; Or, The Whale",
            "author": "Herman Melville",
            "enrichment": {
                "iconic_scenes": ["Iconic turning point in the story with period costume"],
                "protagonist": "Central protagonist",
                "visual_motifs": ["circular medallion-ready composition"],
            },
        }
    )

    assert "Captain Ahab" in replacements["SCENE"]
    assert "Iconic turning point" not in replacements["SCENE"]


def test_execute_generation_payload_preserves_precomposed_prompt_when_compose_prompt_disabled(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openrouter_api_key="test-key")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)

    captured: dict[str, Any] = {}

    def _fake_generate_single_book(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qr.image_generator, "generate_single_book", _fake_generate_single_book)
    monkeypatch.setattr(qr, "_serialize_generation_results", lambda **_kwargs: [])
    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 0)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)

    prompt = 'Book cover illustration only — no text. Illustration for "Book" by Author. Custom precomposed prompt.'
    result = qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 1,
            "models": ["openrouter/google/gemini-3-pro-image-preview"],
            "variants": 1,
            "prompt": prompt,
            "prompt_source": "custom",
            "compose_prompt": False,
            "preserve_prompt_text": True,
            "provider": "all",
            "cover_source": "drive",
            "dry_run": True,
        }
    )

    assert result["dry_run"] is True
    assert captured["prompt_text"] == prompt
    assert captured["library_prompt_id"] is None
    assert captured["preserve_prompt_text"] is True


def test_execute_generation_payload_sanitizes_unresolved_placeholders_before_generation(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openrouter_api_key="test-key")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)

    captured: dict[str, Any] = {}

    def _fake_generate_single_book(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qr.image_generator, "generate_single_book", _fake_generate_single_book)
    monkeypatch.setattr(qr, "_serialize_generation_results", lambda **_kwargs: [])
    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 0)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        qr,
        "_book_row_for_number",
        lambda **_kwargs: {
            "number": 52,
            "title": "Gulliver's Travels",
            "author": "Jonathan Swift",
            "enrichment": {
                "iconic_scenes": ["Gulliver bound by tiny ropes in Lilliput"],
                "emotional_tone": "satirical wonder with unease",
                "era": "18th-century voyage literature",
            },
        },
    )

    qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 52,
            "models": ["openrouter/google/gemini-3-pro-image-preview"],
            "variants": 1,
            "prompt": "Book cover illustration only — {SCENE}. The mood is {MOOD}. Era reference: {ERA}.",
            "prompt_source": "custom",
            "compose_prompt": False,
            "provider": "all",
            "cover_source": "drive",
            "dry_run": True,
        }
    )

    assert "{SCENE}" not in captured["prompt_text"]
    assert "{MOOD}" not in captured["prompt_text"]
    assert "{ERA}" not in captured["prompt_text"]
    assert "Gulliver bound by tiny ropes in Lilliput" in captured["prompt_text"]
    assert "satirical wonder with unease" in captured["prompt_text"]


def test_execute_generation_payload_appends_enrichment_for_generic_prompt(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openrouter_api_key="test-key")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)

    captured: dict[str, Any] = {}

    def _fake_generate_single_book(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qr.image_generator, "generate_single_book", _fake_generate_single_book)
    monkeypatch.setattr(qr, "_serialize_generation_results", lambda **_kwargs: [])
    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 0)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        qr,
        "_book_row_for_number",
        lambda **_kwargs: {
            "number": 52,
            "title": "Gulliver's Travels",
            "author": "Jonathan Swift",
            "enrichment": {
                "iconic_scenes": ["Gulliver wakes on the beach bound by hundreds of tiny ropes while Lilliputians climb over him"],
                "protagonist": "Gulliver",
                "setting_primary": "the shore of Lilliput",
                "emotional_tone": "satirical wonder with unease",
                "era": "18th-century voyage literature",
            },
        },
    )

    qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 52,
            "models": ["openrouter/google/gemini-3-pro-image-preview"],
            "variants": 1,
            "prompt": 'Create a colorful circular medallion illustration for "Gulliver\'s Travels" by Jonathan Swift.',
            "prompt_source": "custom",
            "compose_prompt": False,
            "provider": "all",
            "cover_source": "drive",
            "dry_run": True,
        }
    )

    assert "The illustration must depict: Gulliver wakes on the beach bound by hundreds of tiny ropes" in captured["prompt_text"]
    assert "satirical wonder with unease" in captured["prompt_text"]


def test_execute_generation_payload_honors_scene_description_for_variant_prompt(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openrouter_api_key="test-key")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)

    captured: dict[str, Any] = {}

    def _fake_generate_single_book(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qr.image_generator, "generate_single_book", _fake_generate_single_book)
    monkeypatch.setattr(qr, "_serialize_generation_results", lambda **_kwargs: [])
    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 0)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        qr,
        "_book_row_for_number",
        lambda **_kwargs: {
            "number": 52,
            "title": "Gulliver's Travels",
            "author": "Jonathan Swift",
            "enrichment": {
                "iconic_scenes": [
                    "Gulliver bound by tiny ropes in Lilliput while miniature figures swarm over him",
                    "Gulliver stands before the giant court of Brobdingnag while nobles crowd around him",
                ],
                "emotional_tone": "satirical wonder with unease",
                "era": "18th-century voyage literature",
            },
        },
    )

    qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 52,
            "models": ["openrouter/google/gemini-3-pro-image-preview"],
            "variants": 1,
            "variant": 2,
            "prompt": 'Create a colorful circular medallion illustration for "Gulliver\'s Travels" by Jonathan Swift.',
            "prompt_source": "template",
            "compose_prompt": False,
            "scene_description": "Gulliver stands before the giant court of Brobdingnag while nobles crowd around him",
            "provider": "all",
            "cover_source": "drive",
            "dry_run": True,
        }
    )

    assert "Brobdingnag" in captured["prompt_text"]
    assert "Lilliput" not in captured["prompt_text"]


def test_execute_generation_payload_forwards_preserve_prompt_text_flag(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openrouter_api_key="test-key")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)

    captured: dict[str, Any] = {}

    def _fake_generate_single_book(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(qr.image_generator, "generate_single_book", _fake_generate_single_book)
    monkeypatch.setattr(qr, "_serialize_generation_results", lambda **_kwargs: [])
    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 0)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)

    qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 1,
            "models": ["openrouter/google/gemini-3-pro-image-preview"],
            "variants": 1,
            "prompt": "Book cover illustration only — no text. Exact Alexandria prompt.",
            "prompt_source": "custom",
            "compose_prompt": False,
            "preserve_prompt_text": True,
            "library_prompt_id": "alexandria-base-romantic-realism",
            "provider": "all",
            "cover_source": "drive",
            "dry_run": True,
        }
    )

    assert captured["library_prompt_id"] == "alexandria-base-romantic-realism"
    assert captured["preserve_prompt_text"] is True


def test_execute_generation_payload_drive_source_downloads_cover_before_composite(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openai_api_key="test-key", gdrive_source_folder_id="source-folder-id")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)
    monkeypatch.setattr(qr.image_generator, "generate_single_book", lambda **_kwargs: [])
    monkeypatch.setattr(
        qr,
        "_serialize_generation_results",
        lambda **_kwargs: [
            {
                "book_number": 1,
                "variant": 1,
                "model": "openai/gpt-image-1-mini",
                "prompt": "test",
                "image_path": "tmp/generated/1/variant_1.png",
                "composited_path": None,
                "success": True,
                "error": "",
                "generation_time": 0.1,
                "cost": 0.01,
                "dry_run": False,
                "similarity_warning": False,
                "similar_to_book": None,
                "distinctiveness_score": 0.9,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fit_overlay_path": None,
            }
        ],
    )
    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 1)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)

    captured: dict[str, Any] = {}

    def _fake_ensure_local_input_cover(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"ok": True, "downloaded": True, "source": "google_drive"}

    monkeypatch.setattr(qr.drive_manager, "ensure_local_input_cover", _fake_ensure_local_input_cover)

    result = qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 1,
            "models": ["openai/gpt-image-1-mini"],
            "variants": 1,
            "prompt": "test prompt",
            "provider": "all",
            "cover_source": "drive",
            "selected_cover_id": "drive-file-123",
            "dry_run": False,
        }
    )

    assert result["dry_run"] is False
    assert captured["book_number"] == 1
    assert captured["drive_folder_id"] == "source-folder-id"
    assert captured["selected_cover_id"] == "drive-file-123"


def test_execute_generation_payload_stage_callback_emits_drive_download_and_persist(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openai_api_key="test-key", gdrive_source_folder_id="source-folder-id")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)
    monkeypatch.setattr(qr.image_generator, "generate_single_book", lambda **_kwargs: [])
    monkeypatch.setattr(
        qr,
        "_serialize_generation_results",
        lambda **_kwargs: [
            {
                "book_number": 1,
                "variant": 1,
                "model": "openai/gpt-image-1-mini",
                "prompt": "test",
                "image_path": "tmp/generated/1/variant_1.png",
                "composited_path": None,
                "success": True,
                "error": "",
                "generation_time": 0.1,
                "cost": 0.01,
                "dry_run": False,
                "similarity_warning": False,
                "similar_to_book": None,
                "distinctiveness_score": 0.9,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fit_overlay_path": None,
            }
        ],
    )
    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 1)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(
        qr.drive_manager,
        "ensure_local_input_cover",
        lambda **_kwargs: {"ok": True, "downloaded": True, "source": "google_drive"},
    )

    stages: list[dict[str, Any]] = []
    qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 1,
            "models": ["openai/gpt-image-1-mini"],
            "variants": 1,
            "prompt": "test prompt",
            "provider": "all",
            "cover_source": "drive",
            "dry_run": False,
            "job_id": "stage-callback-demo",
        },
        stage_callback=lambda payload: stages.append(dict(payload)),
    )

    stage_names = [str(item.get("stage", "")) for item in stages]
    assert "download" in stage_names
    assert "composite" in stage_names
    assert "persist" in stage_names
    assert any("Downloading cover from Google Drive" in str(item.get("message", "")) for item in stages)


def test_execute_generation_payload_calls_global_cache_invalidator(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)
    monkeypatch.setattr(qr.image_generator, "generate_single_book", lambda **_kwargs: [])
    monkeypatch.setattr(qr, "_serialize_generation_results", lambda **_kwargs: [])

    invalidated: list[tuple[str, ...]] = []

    def _fake_invalidate(*prefixes, **kwargs):  # type: ignore[no-untyped-def]
        invalidated.append(tuple(prefixes))
        return 1

    monkeypatch.setattr(qr, "_invalidate_cache", _fake_invalidate)
    result = qr._execute_generation_payload(
        {
            "catalog": "classics",
            "book": 1,
            "models": ["openrouter/flux-2-pro"],
            "variants": 1,
            "prompt": "test prompt",
            "provider": "all",
            "dry_run": True,
        }
    )
    assert result["book"] == 1
    assert invalidated


def test_execute_generation_payload_json_fallback_dedupes_by_job_id(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)
    monkeypatch.setattr(qr.image_generator, "generate_single_book", lambda **_kwargs: [])
    monkeypatch.setattr(
        qr,
        "_serialize_generation_results",
        lambda **_kwargs: [
            {
                "book_number": 1,
                "variant": 1,
                "model": "openrouter/flux-2-pro",
                "prompt": "test",
                "provider": "openrouter",
                "image_path": "tmp/generated/1/variant_1.png",
                "composited_path": None,
                "success": True,
                "error": "",
                "generation_time": 0.0,
                "cost": 0.0,
                "dry_run": True,
                "similarity_warning": "",
                "similar_to_book": 0,
                "distinctiveness_score": 1.0,
                "timestamp": "2026-02-23T00:00:00+00:00",
                "fit_overlay_path": None,
            }
        ],
    )
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("db down")))
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)

    payload = {
        "catalog": "classics",
        "book": 1,
        "models": ["openrouter/flux-2-pro"],
        "variants": 1,
        "prompt": "test prompt",
        "provider": "all",
        "dry_run": True,
        "job_id": "job-json-dedupe-1",
    }

    qr._execute_generation_payload(payload)
    qr._execute_generation_payload(payload)
    history_payload = json.loads(cfg.data_dir.joinpath("generation_history.json").read_text(encoding="utf-8"))
    assert len(history_payload["items"]) == 1
    assert history_payload["items"][0]["job_id"] == "job-json-dedupe-1"


def test_execute_generation_payload_resumes_after_composite_failure(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openrouter_api_key="test-key")
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)

    generate_calls = {"count": 0}

    def _fake_generate_single_book(**_kwargs):  # type: ignore[no-untyped-def]
        generate_calls["count"] += 1
        return []

    monkeypatch.setattr(qr.image_generator, "generate_single_book", _fake_generate_single_book)
    monkeypatch.setattr(
        qr,
        "_serialize_generation_results",
        lambda **_kwargs: [
            {
                "book_number": 1,
                "variant": 1,
                "model": "openrouter/flux-2-pro",
                "prompt": "test",
                "image_path": "tmp/generated/1/variant_1.png",
                "composited_path": None,
                "success": True,
                "error": "",
                "generation_time": 0.1,
                "cost": 0.0,
                "dry_run": False,
                "similarity_warning": False,
                "similar_to_book": None,
                "distinctiveness_score": 0.9,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fit_overlay_path": None,
            }
        ],
    )

    composite_calls = {"count": 0}

    def _fake_composite_all_variants(**_kwargs):  # type: ignore[no-untyped-def]
        composite_calls["count"] += 1
        if composite_calls["count"] == 1:
            raise OSError("temporary compose failure")
        out_dir = cfg.tmp_dir / "composited" / "1"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "variant_1.jpg").write_bytes(b"jpg")

    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", _fake_composite_all_variants)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    append_calls: list[dict[str, Any]] = []

    def _fake_append_generation_records(**kwargs):  # type: ignore[no-untyped-def]
        append_calls.append(dict(kwargs))
        return 1

    monkeypatch.setattr(qr.state_db_store, "append_generation_records", _fake_append_generation_records)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)

    payload = {
        "catalog": "classics",
        "book": 1,
        "models": ["openrouter/flux-2-pro"],
        "variants": 1,
        "prompt": "test prompt",
        "provider": "all",
        "dry_run": False,
        "job_id": "job-ckpt-1",
    }

    with pytest.raises(qr.JobStageError) as exc:
        qr._execute_generation_payload(payload)
    assert exc.value.stage == "composite"
    assert exc.value.retryable is True

    checkpoint_path = cfg.data_dir / "job_checkpoints" / "classics" / "job-ckpt-1.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["stages"]["generate"]["status"] == "completed"
    assert checkpoint["stages"]["composite"]["status"] == "failed"
    assert checkpoint["stages"]["persist"]["status"] == "pending"

    result = qr._execute_generation_payload(payload)
    assert result["resume_used"] is True
    assert result["stages"]["generate"]["status"] == "completed"
    assert result["stages"]["composite"]["status"] == "completed"
    assert result["stages"]["persist"]["status"] == "completed"
    assert result["stages"]["deliver"]["status"] == "skipped"
    assert result["stages"]["sync"]["status"] == "skipped"
    assert str(result["results"][0]["composited_path"]).endswith("/tmp/composited/1/variant_1.jpg")
    assert generate_calls["count"] == 1
    assert composite_calls["count"] == 2
    assert append_calls
    assert all(call.get("job_id") == "job-ckpt-1" for call in append_calls)
    assert result["results"][0]["job_id"] == "job-ckpt-1"
    assert not checkpoint_path.exists()


def test_cleanup_stale_checkpoints_removes_old_files(tmp_path: Path):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    stale_dir = cfg.data_dir / "job_checkpoints" / "classics"
    stale_dir.mkdir(parents=True, exist_ok=True)
    stale = stale_dir / "stale.json"
    fresh = stale_dir / "fresh.json"
    stale.write_text("{}", encoding="utf-8")
    fresh.write_text("{}", encoding="utf-8")
    old = time.time() - (26 * 3600)
    now = time.time()
    os.utime(stale, (old, old))
    os.utime(fresh, (now, now))

    removed = qr._cleanup_stale_checkpoints(runtime=cfg, max_age_hours=24)
    assert removed == 1
    assert not stale.exists()
    assert fresh.exists()


def test_assert_composite_validation_within_limits(tmp_path: Path):
    runtime = SimpleNamespace(
        tmp_dir=tmp_path,
        composite_max_invalid_variants=0,
    )
    report_path = tmp_path / "composited" / "7" / "composite_validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"book_number": 7, "total": 3, "invalid": 1}), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid variants 1/3 exceeds allowed 0"):
        qr._assert_composite_validation_within_limits(runtime=runtime, book_number=7)

    runtime_ok = SimpleNamespace(
        tmp_dir=tmp_path,
        composite_max_invalid_variants=1,
    )
    qr._assert_composite_validation_within_limits(runtime=runtime_ok, book_number=7)

    runtime_missing = SimpleNamespace(
        tmp_dir=tmp_path,
        composite_max_invalid_variants=0,
    )
    qr._assert_composite_validation_within_limits(runtime=runtime_missing, book_number=999)


def test_composite_validation_summary_aggregates_reports(tmp_path: Path):
    runtime = SimpleNamespace(tmp_dir=tmp_path)
    root = tmp_path / "composited"
    (root / "1").mkdir(parents=True, exist_ok=True)
    (root / "2").mkdir(parents=True, exist_ok=True)
    (root / "3").mkdir(parents=True, exist_ok=True)
    (root / "1" / "composite_validation.json").write_text(json.dumps({"total": 2, "invalid": 1}), encoding="utf-8")
    (root / "2" / "composite_validation.json").write_text(json.dumps({"total": 3, "invalid": 0}), encoding="utf-8")
    (root / "3" / "composite_validation.json").write_text("bad-json", encoding="utf-8")
    summary = qr._composite_validation_summary(runtime=runtime)
    assert summary["reports"] == 2
    assert summary["books_with_invalid"] == 1
    assert summary["invalid_variants"] == 1
    assert summary["total_variants_checked"] == 5


def test_execute_generation_payload_fails_on_invalid_composite_validation(tmp_path: Path, monkeypatch):
    cfg = _build_runtime_for_startup_checks(tmp_path)
    cfg = replace(cfg, openrouter_api_key="test-key", composite_max_invalid_variants=0)
    monkeypatch.setattr(qr.config, "get_config", lambda *_args, **_kwargs: cfg)
    monkeypatch.setattr(qr.image_generator, "generate_single_book", lambda **_kwargs: [])
    monkeypatch.setattr(
        qr,
        "_serialize_generation_results",
        lambda **_kwargs: [
            {
                "book_number": 1,
                "variant": 1,
                "model": "openrouter/flux-2-pro",
                "prompt": "test",
                "image_path": "tmp/generated/1/variant_1.png",
                "composited_path": None,
                "success": True,
                "error": "",
                "generation_time": 0.1,
                "cost": 0.0,
                "dry_run": False,
                "similarity_warning": False,
                "similar_to_book": None,
                "distinctiveness_score": 0.9,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fit_overlay_path": None,
            }
        ],
    )

    def _fake_composite_all_variants(**_kwargs):  # type: ignore[no-untyped-def]
        out_dir = cfg.tmp_dir / "composited" / "1"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "variant_1.jpg").write_bytes(b"jpg")
        (out_dir / "composite_validation.json").write_text(json.dumps({"book_number": 1, "total": 1, "invalid": 1}), encoding="utf-8")

    monkeypatch.setattr(qr.cover_compositor, "composite_all_variants", _fake_composite_all_variants)
    monkeypatch.setattr(qr, "_record_generation_costs", lambda **_kwargs: None)
    monkeypatch.setattr(qr.state_db_store, "append_generation_records", lambda **_kwargs: 1)
    monkeypatch.setattr(qr.state_db_store, "export_history_payload", lambda **_kwargs: {"items": []})
    monkeypatch.setattr(qr, "_build_review_data_payload", lambda *_args, **_kwargs: {"books": []})
    monkeypatch.setattr(qr, "_invalidate_cache", lambda *_args, **_kwargs: 1)

    payload = {
        "catalog": "classics",
        "book": 1,
        "models": ["openrouter/flux-2-pro"],
        "variants": 1,
        "prompt": "test prompt",
        "provider": "all",
        "dry_run": False,
        "job_id": "job-invalid-composite-1",
    }

    with pytest.raises(qr.JobStageError) as exc:
        qr._execute_generation_payload(payload)
    assert exc.value.stage == "composite"
    assert exc.value.retryable is False
    assert "invalid variants 1/1 exceeds allowed 0" in str(exc.value)

    checkpoint_path = cfg.data_dir / "job_checkpoints" / "classics" / "job-invalid-composite-1.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["stages"]["generate"]["status"] == "completed"
    assert checkpoint["stages"]["composite"]["status"] == "failed"
    assert "invalid variants 1/1 exceeds allowed 0" in checkpoint["stages"]["composite"]["error"]["message"]


def test_job_worker_injects_job_id_into_execution_payload(monkeypatch):
    captured: dict[str, Any] = {}

    class _Store:
        def __init__(self) -> None:
            self._leased = False

        def lease_next_job(self, **_kwargs):  # type: ignore[no-untyped-def]
            if self._leased:
                pool._stop_event.set()
                return None
            self._leased = True
            return SimpleNamespace(
                id="job-worker-1",
                catalog_id="classics",
                book_number=1,
                job_type="generate_cover",
                attempts=0,
                payload={
                    "catalog": "classics",
                    "book": 1,
                    "models": ["openrouter/flux-2-pro"],
                    "variants": 1,
                    "prompt": "test",
                    "provider": "all",
                    "dry_run": True,
                },
            )

        def record_attempt_start(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return 1

        def mark_completed(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(id="job-worker-1", catalog_id="classics", book_number=1, job_type="generate_cover", status="completed", attempts=1, result={})

        def record_attempt_end(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return None

    def _fake_execute(payload):  # type: ignore[no-untyped-def]
        captured.update(payload)
        return {"results": []}

    pool = qr.JobWorkerPool(_Store(), worker_count=1, heartbeat_path=None)
    monkeypatch.setattr(qr, "_execute_generation_payload", _fake_execute)
    pool._run_worker("worker-1")
    assert captured["job_id"] == "job-worker-1"


def test_job_worker_retryable_stage_error_sets_retrying(monkeypatch):
    captured: dict[str, Any] = {}

    class _Store:
        def __init__(self) -> None:
            self._leased = False

        def lease_next_job(self, **_kwargs):  # type: ignore[no-untyped-def]
            if self._leased:
                pool._stop_event.set()
                return None
            self._leased = True
            return SimpleNamespace(
                id="job-worker-retry",
                catalog_id="classics",
                book_number=1,
                job_type="generate_cover",
                attempts=0,
                payload={"catalog": "classics", "book": 1, "models": ["openai/gpt-image-1"], "variants": 1, "prompt": "p", "provider": "all", "dry_run": False},
            )

        def record_attempt_start(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return 7

        def mark_failed(self, _job_id, *, error, retryable, retry_delay_seconds):  # type: ignore[no-untyped-def]
            captured["error"] = dict(error)
            captured["retryable"] = bool(retryable)
            captured["retry_delay_seconds"] = float(retry_delay_seconds)
            return SimpleNamespace(status="retrying")

        def record_attempt_end(self, _attempt_id, *, status, error_text="", meta=None):  # type: ignore[no-untyped-def]
            captured["attempt_status"] = status
            captured["attempt_error_text"] = error_text
            captured["attempt_meta"] = dict(meta or {})

    def _fail_stage(_payload):  # type: ignore[no-untyped-def]
        raise qr.JobStageError(stage="persist", message="transient disk io", retryable=True)

    pool = qr.JobWorkerPool(_Store(), worker_count=1, heartbeat_path=None)
    monkeypatch.setattr(qr, "_execute_generation_payload", _fail_stage)
    pool._run_worker("worker-1")

    assert captured["retryable"] is True
    assert captured["attempt_status"] == "retrying"
    assert captured["error"]["stage"] == "persist"
    assert captured["attempt_meta"]["stage"] == "persist"


def test_job_worker_terminal_stage_error_sets_failed(monkeypatch):
    captured: dict[str, Any] = {}

    class _Store:
        def __init__(self) -> None:
            self._leased = False

        def lease_next_job(self, **_kwargs):  # type: ignore[no-untyped-def]
            if self._leased:
                pool._stop_event.set()
                return None
            self._leased = True
            return SimpleNamespace(
                id="job-worker-fail",
                catalog_id="classics",
                book_number=1,
                job_type="generate_cover",
                attempts=0,
                payload={"catalog": "classics", "book": 1, "models": ["openai/gpt-image-1"], "variants": 1, "prompt": "p", "provider": "all", "dry_run": False},
            )

        def record_attempt_start(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return 8

        def mark_failed(self, _job_id, *, error, retryable, retry_delay_seconds):  # type: ignore[no-untyped-def]
            captured["error"] = dict(error)
            captured["retryable"] = bool(retryable)
            captured["retry_delay_seconds"] = float(retry_delay_seconds)
            return SimpleNamespace(status="failed")

        def record_attempt_end(self, _attempt_id, *, status, error_text="", meta=None):  # type: ignore[no-untyped-def]
            captured["attempt_status"] = status
            captured["attempt_error_text"] = error_text
            captured["attempt_meta"] = dict(meta or {})

    def _fail_stage(_payload):  # type: ignore[no-untyped-def]
        raise qr.JobStageError(stage="persist", message="fatal persist corruption", retryable=False)

    pool = qr.JobWorkerPool(_Store(), worker_count=1, heartbeat_path=None)
    monkeypatch.setattr(qr, "_execute_generation_payload", _fail_stage)
    pool._run_worker("worker-1")

    assert captured["retryable"] is False
    assert captured["attempt_status"] == "failed"
    assert captured["error"]["stage"] == "persist"
    assert captured["attempt_meta"]["stage"] == "persist"
