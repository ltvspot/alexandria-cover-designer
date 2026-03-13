#!/usr/bin/env python3
"""Prompt 5 review tooling: /iterate, /review, fallback gallery, and API server."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import gzip
import hashlib
import importlib
import inspect
import io
import json
import logging
import math
import mimetypes
import os
import queue
import re
import signal
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

from PIL import Image, ImageDraw
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src import audit_log
    from src import api_responses
    from src import api_validation
    from src import book_metadata
    from src import book_enricher
    from src import catalog_manager
    from src import config
    from src import content_relevance
    from src import cost_tracker
    from src import cover_compositor
    from src import pdf_compositor
    from src import disaster_recovery
    from src import delivery_pipeline
    from src import drive_manager
    from src import error_metrics
    from src import export_amazon
    from src import export_ingram
    from src import export_social
    from src import export_utils
    from src import export_web
    from src import gdrive_sync
    from src import image_generator
    from src import intelligent_prompter
    from src import genre_intelligence
    from src import prompt_generator
    from src import job_store
    from src import mockup_generator
    from src import output_exporter
    from src import print_validator
    from src import repository
    from src import safe_json
    from src import security
    from src import social_card_generator
    from src import similarity_detector
    from src import state_store
    from src import template_registry
    from src import thumbnail_server
    from src.logger import get_logger
    from src import pipeline as pipeline_runner
    from src.prompt_library import LibraryPrompt, PromptLibrary
except ModuleNotFoundError:  # pragma: no cover
    import audit_log  # type: ignore
    import api_responses  # type: ignore
    import api_validation  # type: ignore
    import book_metadata  # type: ignore
    import book_enricher  # type: ignore
    import catalog_manager  # type: ignore
    import config  # type: ignore
    import content_relevance  # type: ignore
    import cost_tracker  # type: ignore
    import cover_compositor  # type: ignore
    import pdf_compositor  # type: ignore
    import disaster_recovery  # type: ignore
    import delivery_pipeline  # type: ignore
    import drive_manager  # type: ignore
    import error_metrics  # type: ignore
    import export_amazon  # type: ignore
    import export_ingram  # type: ignore
    import export_social  # type: ignore
    import export_utils  # type: ignore
    import export_web  # type: ignore
    import gdrive_sync  # type: ignore
    import image_generator  # type: ignore
    import intelligent_prompter  # type: ignore
    import genre_intelligence  # type: ignore
    import prompt_generator  # type: ignore
    import job_store  # type: ignore
    import mockup_generator  # type: ignore
    import output_exporter  # type: ignore
    import print_validator  # type: ignore
    import repository  # type: ignore
    import safe_json  # type: ignore
    import security  # type: ignore
    import social_card_generator  # type: ignore
    import similarity_detector  # type: ignore
    import state_store  # type: ignore
    import template_registry  # type: ignore
    import thumbnail_server  # type: ignore
    from logger import get_logger  # type: ignore
    import pipeline as pipeline_runner  # type: ignore
    from prompt_library import LibraryPrompt, PromptLibrary  # type: ignore

logger = get_logger(__name__)

STYLE_EDGE_TRIM_PROMPT_MARKERS = {
    "alphonse mucha and edward burne-jones": "base1",
    "dante gabriel rossetti and william morris": "base4",
}
STYLE_EDGE_TRIM_RATIO = 0.10

REVIEW_DATA_PATH = PROJECT_ROOT / "data" / "review_data.json"
ITERATE_DATA_PATH = PROJECT_ROOT / "data" / "iterate_data.json"
COMPARE_DATA_PATH = PROJECT_ROOT / "data" / "compare_data.json"
SELECTIONS_PATH = PROJECT_ROOT / "data" / "variant_selections.json"
WINNER_SELECTIONS_PATH = PROJECT_ROOT / "data" / "winner_selections.json"
FALLBACK_HTML_PATH = PROJECT_ROOT / "data" / "review_gallery.html"
HISTORY_PATH = config.generation_history_path()
QUALITY_SCORES_PATH = config.quality_scores_path()
CATALOG_OUTPUT_PATH = PROJECT_ROOT / "Output Covers" / "Alexandria_Cover_Catalog.pdf"
CONTACT_SHEET_OUTPUT_PATH = PROJECT_ROOT / "Output Covers" / "Alexandria_Contact_Sheet.pdf"
ALL_VARIANTS_CATALOG_OUTPUT_PATH = PROJECT_ROOT / "Output Covers" / "Alexandria_All_Variants_Catalog.pdf"
REGEN_RESULTS_PATH = config.regeneration_results_path()
REVIEW_SESSIONS_DIR = PROJECT_ROOT / "data" / "review_sessions"
REVIEW_STATS_PATH = PROJECT_ROOT / "data" / "review_stats.json"
SLO_METRICS_PATH = config.slo_metrics_path()
SLO_ALERT_STATE_PATH = config.slo_alert_state_path()
COST_LEDGER_PATH = config.cost_ledger_path()
BUDGET_CONFIG_PATH = config.budget_config_path()
EXPORTS_ROOT = PROJECT_ROOT / "exports"
DELIVERY_CONFIG_PATH = config.delivery_config_path()
DELIVERY_TRACKING_PATH = config.delivery_tracking_path()
DRIVE_SYNC_LOG_PATH = PROJECT_ROOT / "data" / "drive_sync_log.json"
SETTINGS_STORE_PATH = PROJECT_ROOT / "settings_store.json"
CGI_CATALOG_CACHE_PATH = PROJECT_ROOT / "catalog_cache.json"
CGI_CATALOG_MAX_AGE_SECONDS = 3600
SAVE_RAW_DRIVE_FOLDER_ID = "0ABLZWLOVzq-qUk9PVA"
SAVE_RESULT_DRIVE_FOLDER_ID = "0ABLZWLOVzq-qUk9PVA"
SAVE_RAW_LOCAL_DIRNAME = "Chosen Winner Generated Covers"
SAVE_RAW_DRIVE_RETRY_ATTEMPTS = max(1, int(os.getenv("SAVE_RAW_DRIVE_RETRY_ATTEMPTS", "2")))
SAVE_RAW_DRIVE_RETRY_DELAY_SECONDS = max(0.0, float(os.getenv("SAVE_RAW_DRIVE_RETRY_DELAY_SECONDS", "0.5")))
SAVE_RAW_DRIVE_PROBE_TIMEOUT_SECONDS = max(0.1, float(os.getenv("SAVE_RAW_DRIVE_PROBE_TIMEOUT_SECONDS", "5")))
SAVE_RAW_DRIVE_PROBE_DELETE_ATTEMPTS = max(1, int(os.getenv("SAVE_RAW_DRIVE_PROBE_DELETE_ATTEMPTS", "6")))
SAVE_RAW_DRIVE_PROBE_DELETE_DELAY_SECONDS = max(0.0, float(os.getenv("SAVE_RAW_DRIVE_PROBE_DELETE_DELAY_SECONDS", "0.1")))
SAVE_PROMPT_DRIVE_SUBDIR = "saved_prompts"
FALLBACK_FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    b'<rect width="64" height="64" rx="12" fill="#0A1628"/>'
    b'<circle cx="32" cy="32" r="19" fill="none" stroke="#D4AF37" stroke-width="6"/>'
    b'<circle cx="32" cy="32" r="8" fill="#D4AF37"/>'
    b"</svg>"
)
APP_STARTED_AT = time.time()
ACTIVE_WORKER_MODE = "inline"
STARTUP_HEALTH: dict[str, Any] = {
    "checked_at": "",
    "healthy": True,
    "issues": [],
    "warnings": [],
    "checks": [],
}
_STARTUP_STATE_LOCK = threading.Lock()
_STARTUP_STATE: dict[str, Any] = {
    "status": "idle",
    "started_at": "",
    "completed_at": "",
    "error": "",
}
JOBS_DB_PATH = PROJECT_ROOT / os.getenv("JOBS_DB_PATH", "data/jobs.sqlite3")
STATE_DB_PATH = PROJECT_ROOT / os.getenv("STATE_DB_PATH", "data/state.sqlite3")
JOB_WORKER_COUNT = max(1, int(os.getenv("JOB_WORKERS", "2")))
JOB_STALE_RECOVERY_SECONDS = max(30, int(os.getenv("JOB_STALE_RECOVERY_SECONDS", "900")))
JOB_STALE_RECOVERY_RETRY_DELAY_SECONDS = max(1.0, float(os.getenv("JOB_STALE_RECOVERY_RETRY_DELAY_SECONDS", "2.0")))
JOB_WORKER_MODE = str(os.getenv("JOB_WORKER_MODE", "inline")).strip().lower() or "inline"
JOB_WORKER_HEARTBEAT_PATH = PROJECT_ROOT / os.getenv("JOB_WORKER_HEARTBEAT_PATH", "data/worker_heartbeat.json")
JOB_WORKER_HEARTBEAT_STALE_SECONDS = max(30, int(os.getenv("JOB_WORKER_HEARTBEAT_STALE_SECONDS", "120")))
SLO_ALERT_COOLDOWN_SECONDS = max(60, int(os.getenv("SLO_ALERT_COOLDOWN_SECONDS", "900")))
SLO_ALERT_LEVELS = {
    token.strip().lower()
    for token in os.getenv("SLO_ALERT_LEVELS", "breached,at_risk").split(",")
    if token.strip()
}
SLO_MONITOR_INTERVAL_SECONDS = max(0, int(os.getenv("SLO_MONITOR_INTERVAL_SECONDS", "300")))
MUTATION_API_TOKEN = os.getenv("WEB_API_TOKEN", "").strip()
MUTATION_RATE_LIMIT_PER_MINUTE = max(10, int(os.getenv("WEB_RATE_LIMIT_PER_MINUTE", "120")))
READ_RATE_LIMIT_PER_MINUTE = max(60, int(os.getenv("WEB_READ_RATE_LIMIT_PER_MINUTE", "300")))
DATA_CACHE_MAX_ENTRIES = max(100, int(os.getenv("DATA_CACHE_MAX_ENTRIES", "1000")))
SSE_MAX_CONNECTIONS_PER_CLIENT = max(1, int(os.getenv("SSE_MAX_CONNECTIONS_PER_CLIENT", "3")))
ALLOW_SYNC_GENERATION = str(os.getenv("ALLOW_SYNC_GENERATION", "0")).strip().lower() in {"1", "true", "yes", "on"}
REQUEST_HANDLER_TIMEOUT_SECONDS = max(5.0, float(os.getenv("REQUEST_HANDLER_TIMEOUT_SECONDS", "30")))


def _normalize_worker_mode(raw: str | None) -> str:
    token = str(raw or "").strip().lower()
    if token in {"inline", "external", "disabled"}:
        return token
    return "inline"


ACTIVE_WORKER_MODE = _normalize_worker_mode(JOB_WORKER_MODE)
_JOB_CANCELLED_MODELS: dict[str, dict[str, set[str]]] = {}
_JOB_CANCELLED_MODELS_LOCK = threading.Lock()
_SLOW_REQUEST_LOG: list[dict[str, Any]] = []
_SLOW_REQUEST_LOG_LOCK = threading.Lock()
_SLOW_REQUEST_THRESHOLD_SECONDS = 5.0
_PRINT_VALIDATOR_LOCK = threading.Lock()
_PRINT_VALIDATOR_INSTANCE: print_validator.PrintValidator | None = None
_VISUAL_QA_RUNNING: set[str] = set()
_VISUAL_QA_RUNNING_LOCK = threading.Lock()
_CATALOG_ENRICHMENT_THREADS: dict[str, threading.Thread] = {}
_CATALOG_ENRICHMENT_THREADS_LOCK = threading.Lock()
_JSON_LIST_ROWS_CACHE_LOCK = threading.Lock()
_JSON_LIST_ROWS_CACHE: dict[str, dict[str, Any]] = {}


def _set_startup_state(*, status: str, started_at: str | None = None, completed_at: str | None = None, error: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _STARTUP_STATE_LOCK:
        _STARTUP_STATE["status"] = str(status or "idle").strip() or "idle"
        if started_at is not None:
            _STARTUP_STATE["started_at"] = str(started_at or "")
        elif not str(_STARTUP_STATE.get("started_at", "")).strip():
            _STARTUP_STATE["started_at"] = now
        if completed_at is not None:
            _STARTUP_STATE["completed_at"] = str(completed_at or "")
        elif _STARTUP_STATE["status"] in {"ready", "failed"}:
            _STARTUP_STATE["completed_at"] = now
        _STARTUP_STATE["error"] = str(error or "")


def _startup_state_snapshot() -> dict[str, Any]:
    with _STARTUP_STATE_LOCK:
        return dict(_STARTUP_STATE)


def _set_startup_health(payload: dict[str, Any]) -> None:
    global STARTUP_HEALTH
    STARTUP_HEALTH = dict(payload or {})


def _startup_healthz_payload(*, runtime: config.Config | None = None) -> dict[str, Any]:
    runtime = runtime or config.get_config()
    state = _startup_state_snapshot()
    startup_health = STARTUP_HEALTH if isinstance(STARTUP_HEALTH, dict) else {}
    status = str(state.get("status", "idle") or "idle")
    healthy = status != "failed"
    return {
        "ok": healthy,
        "status": "ok" if healthy else "degraded",
        "healthy": healthy,
        "version": "2.1.1",
        "uptime_seconds": int(max(0.0, time.time() - APP_STARTED_AT)),
        "catalog": runtime.catalog_id,
        "startup": {
            "status": status,
            "started_at": str(state.get("started_at", "") or ""),
            "completed_at": str(state.get("completed_at", "") or ""),
            "error": str(state.get("error", "") or ""),
            "checks_completed": bool(startup_health.get("checked_at")),
        },
    }


def _json_list_rows_cache_entry(path: Path) -> dict[str, Any]:
    target = Path(path)
    key = str(target.resolve())
    try:
        stat = target.stat()
    except OSError:
        return {"rows": [], "by_number": {}}

    cache_token = (int(stat.st_mtime_ns), int(stat.st_size))
    with _JSON_LIST_ROWS_CACHE_LOCK:
        cached = _JSON_LIST_ROWS_CACHE.get(key)
        if cached and cached.get("token") == cache_token:
            return cached

    payload = _load_json(target, [])
    rows = [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    by_number: dict[int, dict[str, Any]] = {}
    for row in rows:
        number = _safe_int(row.get("number"), 0)
        if number > 0 and number not in by_number:
            by_number[number] = row
    entry = {"token": cache_token, "rows": rows, "by_number": by_number}
    with _JSON_LIST_ROWS_CACHE_LOCK:
        _JSON_LIST_ROWS_CACHE[key] = entry
    return entry


def _prime_catalog_file_caches(runtime: config.Config) -> None:
    _json_list_rows_cache_entry(runtime.book_catalog_path)
    _json_list_rows_cache_entry(config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir))
_ENRICHMENT_RUN_LOCK = threading.Lock()
_ENRICHMENT_RUN_STATUS: dict[str, dict[str, Any]] = {}


def _budget_presets_for_runtime(runtime: config.Config) -> list[dict[str, Any]]:
    model_cost = {model: runtime.get_model_cost(model) for model in runtime.all_models}
    return [
        {
            "id": "cheapest",
            "name": "Cheapest",
            "description": "Fast smoke tests, quick iteration",
            "models": ["openrouter/google/gemini-2.5-flash-image"],
            "estimated_cost_per_image_usd": round(model_cost.get("openrouter/google/gemini-2.5-flash-image", 0.003), 6),
        },
        {
            "id": "balanced",
            "name": "Balanced",
            "description": "Good quality at reasonable cost",
            "models": [
                "openrouter/google/gemini-3-pro-image-preview",
                "openrouter/openai/gpt-5-image-mini",
            ],
            "estimated_cost_per_image_usd": round(
                model_cost.get("openrouter/google/gemini-3-pro-image-preview", 0.02)
                + model_cost.get("openrouter/openai/gpt-5-image-mini", 0.012),
                6,
            ),
        },
        {
            "id": "premium",
            "name": "Premium",
            "description": "Best quality, all top models",
            "models": [
                "openrouter/google/gemini-3-pro-image-preview",
                "openrouter/openai/gpt-5-image",
                "fal/fal-ai/flux-2-pro",
            ],
            "estimated_cost_per_image_usd": round(
                model_cost.get("openrouter/google/gemini-3-pro-image-preview", 0.02)
                + model_cost.get("openrouter/openai/gpt-5-image", 0.04)
                + model_cost.get("fal/fal-ai/flux-2-pro", 0.045),
                6,
            ),
        },
    ]


def _print_validator_instance() -> print_validator.PrintValidator:
    global _PRINT_VALIDATOR_INSTANCE
    with _PRINT_VALIDATOR_LOCK:
        if _PRINT_VALIDATOR_INSTANCE is None:
            _PRINT_VALIDATOR_INSTANCE = print_validator.PrintValidator()
        return _PRINT_VALIDATOR_INSTANCE


def _sync_generation_allowed(*, worker_mode: str | None = None) -> bool:
    mode = _normalize_worker_mode(worker_mode or ACTIVE_WORKER_MODE)
    if mode == "inline":
        return True
    return bool(ALLOW_SYNC_GENERATION)


def _job_stale_recovery_config(runtime: config.Config | None = None) -> tuple[int, float]:
    runtime = runtime or config.get_config()
    stale_after_seconds = max(
        30,
        _safe_int(getattr(runtime, "job_stale_recovery_seconds", JOB_STALE_RECOVERY_SECONDS), JOB_STALE_RECOVERY_SECONDS),
    )
    retry_delay_seconds = max(
        1.0,
        _safe_float(
            getattr(runtime, "job_stale_recovery_retry_delay_seconds", JOB_STALE_RECOVERY_RETRY_DELAY_SECONDS),
            JOB_STALE_RECOVERY_RETRY_DELAY_SECONDS,
        ),
    )
    return stale_after_seconds, retry_delay_seconds


class DataCache:
    """Small in-memory TTL cache for expensive GET responses."""

    def __init__(self, *, ttl_seconds: int = 60, max_entries: int = DATA_CACHE_MAX_ENTRIES):
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._rows: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def _expired(self, ts: float) -> bool:
        return (time.time() - ts) > self.ttl_seconds

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                self.misses += 1
                return None
            ts, value = row
            if self._expired(ts):
                self._rows.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            self._rows.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._rows:
                self._rows.pop(key, None)
            self._rows[key] = (time.time(), value)
            while len(self._rows) > self.max_entries:
                self._rows.popitem(last=False)
                self.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [key for key in self._rows.keys() if key.startswith(prefix)]
            for key in keys:
                self._rows.pop(key, None)
            return len(keys)

    def invalidate_exact(self, key: str) -> int:
        with self._lock:
            if key in self._rows:
                self._rows.pop(key, None)
                return 1
            return 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            expired = 0
            now = time.time()
            for ts, _ in self._rows.values():
                if (now - ts) > self.ttl_seconds:
                    expired += 1
            return {
                "ttl_seconds": self.ttl_seconds,
                "max_entries": self.max_entries,
                "entries": len(self._rows),
                "expired_entries": expired,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
            }


class RequestTracker:
    """Tracks in-flight long-running requests to avoid duplicate work."""

    def __init__(self):
        self._in_flight: set[str] = set()
        self._lock = threading.Lock()

    def start(self, request_id: str) -> bool:
        token = str(request_id or "").strip()
        if not token:
            return False
        with self._lock:
            if token in self._in_flight:
                return False
            self._in_flight.add(token)
            return True

    def finish(self, request_id: str) -> None:
        token = str(request_id or "").strip()
        if not token:
            return
        with self._lock:
            self._in_flight.discard(token)

    def active(self) -> list[str]:
        with self._lock:
            return sorted(self._in_flight)


class SimpleRateLimiter:
    """Per-client in-memory minute window limiter for mutation endpoints."""

    def __init__(self, *, per_minute: int):
        self.per_minute = max(1, int(per_minute))
        self._rows: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client_key: str) -> bool:
        token = str(client_key or "unknown").strip() or "unknown"
        now = time.time()
        window_start = now - 60.0
        with self._lock:
            history = self._rows.get(token, [])
            history = [ts for ts in history if ts >= window_start]
            if len(history) >= self.per_minute:
                self._rows[token] = history
                return False
            history.append(now)
            self._rows[token] = history
            return True


class SSEConnectionLimiter:
    """Track concurrent SSE streams per client key."""

    def __init__(self, *, per_client: int):
        self.per_client = max(1, int(per_client))
        self._rows: dict[str, int] = {}
        self._lock = threading.Lock()

    def start(self, client_key: str) -> bool:
        token = str(client_key or "unknown").strip() or "unknown"
        with self._lock:
            active = int(self._rows.get(token, 0) or 0)
            if active >= self.per_client:
                return False
            self._rows[token] = active + 1
            return True

    def finish(self, client_key: str) -> None:
        token = str(client_key or "unknown").strip() or "unknown"
        with self._lock:
            active = int(self._rows.get(token, 0) or 0)
            if active <= 1:
                self._rows.pop(token, None)
            else:
                self._rows[token] = active - 1

    def active(self, client_key: str) -> int:
        token = str(client_key or "unknown").strip() or "unknown"
        with self._lock:
            return int(self._rows.get(token, 0) or 0)


class RollingSLOTracker:
    """Track response outcomes in a rolling daily window for SLO evaluation."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        payload = safe_json.load_json(path, {"days": {}, "updated_at": ""})
        if not isinstance(payload, dict):
            payload = {"days": {}, "updated_at": ""}
        if not isinstance(payload.get("days"), dict):
            payload["days"] = {}
        self._payload = payload
        self._writes_since_flush = 0

    def record_response(self, status_code: int, *, catalog_id: str | None = None) -> None:
        code = int(status_code)
        day = datetime.now(timezone.utc).date().isoformat()
        catalog_token = str(catalog_id or "").strip()
        with self._lock:
            days = self._payload.setdefault("days", {})
            row = days.get(day, {})
            if not isinstance(row, dict):
                row = {}
            row["total"] = int(row.get("total", 0) or 0) + 1
            if 200 <= code < 400:
                row["success"] = int(row.get("success", 0) or 0) + 1
            elif code >= 500:
                row["server_errors"] = int(row.get("server_errors", 0) or 0) + 1
            else:
                row["client_errors"] = int(row.get("client_errors", 0) or 0) + 1
            if catalog_token:
                catalogs = row.get("catalogs", {})
                if not isinstance(catalogs, dict):
                    catalogs = {}
                catalog_row = catalogs.get(catalog_token, {})
                if not isinstance(catalog_row, dict):
                    catalog_row = {}
                catalog_row["total"] = int(catalog_row.get("total", 0) or 0) + 1
                if 200 <= code < 400:
                    catalog_row["success"] = int(catalog_row.get("success", 0) or 0) + 1
                elif code >= 500:
                    catalog_row["server_errors"] = int(catalog_row.get("server_errors", 0) or 0) + 1
                else:
                    catalog_row["client_errors"] = int(catalog_row.get("client_errors", 0) or 0) + 1
                catalogs[catalog_token] = catalog_row
                row["catalogs"] = catalogs
            days[day] = row

            cutoff = (datetime.now(timezone.utc).date() - timedelta(days=45)).isoformat()
            stale_days = [key for key in days.keys() if key < cutoff]
            for stale in stale_days:
                days.pop(stale, None)

            self._payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._writes_since_flush += 1
            if self._writes_since_flush >= 25:
                self._flush_locked()

    def snapshot(self, *, window_days: int, catalog_id: str | None = None) -> dict[str, Any]:
        days = max(1, int(window_days))
        cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
        catalog_token = str(catalog_id or "").strip()
        with self._lock:
            day_rows = self._payload.get("days", {})
            if not isinstance(day_rows, dict):
                day_rows = {}
            total = 0
            success = 0
            server_errors = 0
            client_errors = 0
            for key, row in day_rows.items():
                if not isinstance(row, dict):
                    continue
                try:
                    row_date = datetime.fromisoformat(str(key)).date()
                except ValueError:
                    continue
                if row_date < cutoff_date:
                    continue
                if catalog_token:
                    catalogs = row.get("catalogs", {})
                    if not isinstance(catalogs, dict):
                        continue
                    scoped = catalogs.get(catalog_token, {})
                    if not isinstance(scoped, dict):
                        continue
                    total += int(scoped.get("total", 0) or 0)
                    success += int(scoped.get("success", 0) or 0)
                    server_errors += int(scoped.get("server_errors", 0) or 0)
                    client_errors += int(scoped.get("client_errors", 0) or 0)
                else:
                    total += int(row.get("total", 0) or 0)
                    success += int(row.get("success", 0) or 0)
                    server_errors += int(row.get("server_errors", 0) or 0)
                    client_errors += int(row.get("client_errors", 0) or 0)
            success_rate = (success / total) if total else 1.0
            server_error_rate = (server_errors / total) if total else 0.0
            return {
                "window_days": days,
                "catalog_id": catalog_token,
                "total_requests": total,
                "successful_requests": success,
                "server_errors": server_errors,
                "client_errors": client_errors,
                "success_rate": round(success_rate, 6),
                "server_error_rate": round(server_error_rate, 6),
                "updated_at": str(self._payload.get("updated_at", "") or ""),
            }

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe_json.atomic_write_json(self.path, self._payload)
        self._writes_since_flush = 0


class SLOAlertManager:
    """Webhook alerting for SLO states with cooldown and de-duplication."""

    def __init__(self, *, state_path: Path, cooldown_seconds: int, alert_levels: set[str]):
        self.state_path = state_path
        self.cooldown_seconds = max(60, int(cooldown_seconds))
        self.alert_levels = {str(token).strip().lower() for token in alert_levels if str(token).strip()}
        payload = safe_json.load_json(state_path, {"last_sent_at": "", "last_digest": "", "last_status": "", "history": []})
        if not isinstance(payload, dict):
            payload = {"last_sent_at": "", "last_digest": "", "last_status": "", "history": []}
        if not isinstance(payload.get("history"), list):
            payload["history"] = []
        self._state = payload
        self._lock = threading.Lock()

    def maybe_alert(self, *, runtime: config.Config, slo_evaluation: dict[str, Any]) -> dict[str, Any]:
        levels = self.alert_levels or {"breached"}
        relevant: list[dict[str, Any]] = []
        for key, row in slo_evaluation.items():
            if key in {"window_days", "targets"}:
                continue
            if not isinstance(row, dict):
                continue
            status = str(row.get("status", "")).strip().lower()
            if status in levels:
                relevant.append({"name": key, "status": status, "actual": row.get("actual"), "target": row.get("target")})
        if not relevant:
            return {"checked": True, "sent": False, "reason": "no_alert_conditions"}

        webhook_url = str(getattr(runtime, "webhook_url", "") or "").strip()
        if not webhook_url:
            return {"checked": True, "sent": False, "reason": "webhook_not_configured", "alerts": relevant}

        severity = "breached" if any(item["status"] == "breached" for item in relevant) else "at_risk"
        digest_payload = {
            "catalog": runtime.catalog_id,
            "severity": severity,
            "items": sorted(relevant, key=lambda item: (str(item["status"]), str(item["name"]))),
        }
        digest = hashlib.sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._lock:
            last_sent = _safe_iso_datetime(str(self._state.get("last_sent_at", "")))
            last_digest = str(self._state.get("last_digest", "") or "")
            cooldown_active = False
            if last_sent is not None:
                elapsed = (now_dt - last_sent).total_seconds()
                cooldown_active = elapsed < self.cooldown_seconds
            if cooldown_active and digest == last_digest:
                return {
                    "checked": True,
                    "sent": False,
                    "reason": "cooldown_active",
                    "alerts": relevant,
                    "cooldown_seconds": self.cooldown_seconds,
                }

            text = (
                f"SLO alert ({severity}) for catalog '{runtime.catalog_id}': "
                + ", ".join(f"{item['name']}={item['status']}" for item in relevant)
            )
            payload = {
                "text": text,
                "event": "slo_alert",
                "severity": severity,
                "catalog": runtime.catalog_id,
                "alerts": relevant,
                "window_days": slo_evaluation.get("window_days"),
                "targets": slo_evaluation.get("targets", {}),
                "timestamp": now,
            }

            try:
                response = requests.post(webhook_url, json=payload, timeout=8.0)
                if response.status_code >= 400:
                    return {
                        "checked": True,
                        "sent": False,
                        "reason": f"webhook_http_{response.status_code}",
                        "alerts": relevant,
                    }
            except Exception as exc:  # pragma: no cover - network boundary
                logger.warning("SLO alert webhook failed: %s", exc)
                return {"checked": True, "sent": False, "reason": "webhook_error", "alerts": relevant}

            self._state["last_sent_at"] = now
            self._state["last_digest"] = digest
            self._state["last_status"] = severity
            history = self._state.get("history", [])
            if not isinstance(history, list):
                history = []
            history.append({"sent_at": now, "severity": severity, "catalog": runtime.catalog_id, "alerts": relevant})
            self._state["history"] = history[-200:]
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            safe_json.atomic_write_json(self.state_path, self._state)
            return {"checked": True, "sent": True, "severity": severity, "alerts": relevant}


class JobEventBroker:
    """In-memory pub/sub broker used by SSE job event stream."""

    def __init__(self, *, max_queue_size: int = 200):
        self.max_queue_size = max(10, int(max_queue_size))
        self._subs: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def subscribe(self) -> tuple[str, queue.Queue[dict[str, Any]]]:
        token = str(uuid.uuid4())
        client_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=self.max_queue_size)
        with self._lock:
            self._subs[token] = client_queue
        return token, client_queue

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._subs.pop(str(token), None)

    def publish(self, event_name: str, payload: dict[str, Any]) -> int:
        event = {
            "event": str(event_name or "message"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(payload if isinstance(payload, dict) else {}),
        }
        with self._lock:
            targets = list(self._subs.items())
        delivered = 0
        for _, client_queue in targets:
            try:
                client_queue.put_nowait(event)
                delivered += 1
            except queue.Full:
                try:
                    client_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    client_queue.put_nowait(event)
                    delivered += 1
                except queue.Full:
                    continue
        return delivered


class JobWorkerPool:
    """Background worker pool for async job execution."""

    def __init__(
        self,
        store: job_store.JobStore,
        *,
        worker_count: int = 2,
        heartbeat_path: Path | None = None,
        service_name: str = "inline",
    ):
        self.store = store
        self.worker_count = max(1, int(worker_count))
        self.heartbeat_path = heartbeat_path
        self.service_name = str(service_name or "inline")
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._started = False
        self._heartbeat_lock = threading.Lock()

    def _write_heartbeat(
        self,
        *,
        worker_id: str,
        state: str,
        job_id: str = "",
    ) -> None:
        if not self.heartbeat_path:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._heartbeat_lock:
            payload = safe_json.load_json(
                self.heartbeat_path,
                {
                    "service": self.service_name,
                    "updated_at": "",
                    "workers": {},
                    "pid": os.getpid(),
                },
            )
            if not isinstance(payload, dict):
                payload = {"service": self.service_name, "updated_at": "", "workers": {}, "pid": os.getpid()}
            workers = payload.get("workers", {})
            if not isinstance(workers, dict):
                workers = {}
            workers[str(worker_id)] = {
                "state": str(state),
                "job_id": str(job_id or ""),
                "updated_at": now,
            }
            payload["workers"] = workers
            payload["service"] = self.service_name
            payload["updated_at"] = now
            payload["pid"] = os.getpid()
            payload["worker_count"] = self.worker_count
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            safe_json.atomic_write_json(self.heartbeat_path, payload)

    def start(self) -> None:
        if self._started:
            return
        self._stop_event.clear()
        self._threads = []
        for idx in range(self.worker_count):
            worker_id = f"worker-{idx + 1}"
            thread = threading.Thread(
                target=self._run_worker,
                args=(worker_id,),
                name=f"job-{worker_id}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        self._started = True
        logger.info("Started job worker pool", extra={"workers": self.worker_count})

    def stop(self, *, timeout_seconds: float = 3.0) -> None:
        if not self._started:
            return
        self._stop_event.set()
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        for thread in self._threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        self._threads = []
        self._started = False
        for idx in range(self.worker_count):
            self._write_heartbeat(worker_id=f"worker-{idx + 1}", state="stopped")
        logger.info("Stopped job worker pool")

    def enqueue_generate_job(
        self,
        *,
        catalog_id: str,
        book: int,
        models: list[str],
        variants: int,
        prompt: str,
        provider: str,
        idempotency_key: str,
        compose_prompt: bool = True,
        preserve_prompt_text: bool = False,
        cover_source: str = "catalog",
        selected_cover_id: str = "",
        library_prompt_id: str = "",
        drive_folder_id: str = "",
        input_folder_id: str = "",
        credentials_path: str = "",
        dry_run: bool = False,
        max_attempts: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[job_store.JobRecord, bool]:
        normalized_models = sorted({str(item).strip() for item in models if str(item).strip()})
        normalized_prompt = " ".join(str(prompt or "").split())
        normalized_provider = str(provider or "all").strip().lower() or "all"
        normalized_cover_source = str(cover_source or "catalog").strip().lower() or "catalog"
        if normalized_cover_source not in {"catalog", "drive"}:
            normalized_cover_source = "catalog"
        normalized_selected_cover_id = str(selected_cover_id or "").strip()
        normalized_library_prompt_id = str(library_prompt_id or "").strip()
        payload = {
            "catalog": str(catalog_id),
            "book": int(book),
            "models": normalized_models,
            "variants": int(variants),
            "prompt": normalized_prompt,
            "provider": normalized_provider,
            "compose_prompt": bool(compose_prompt),
            "preserve_prompt_text": bool(preserve_prompt_text),
            "cover_source": normalized_cover_source,
            "selected_cover_id": normalized_selected_cover_id,
            "library_prompt_id": normalized_library_prompt_id,
            "drive_folder_id": str(drive_folder_id or "").strip(),
            "input_folder_id": str(input_folder_id or "").strip(),
            "credentials_path": str(credentials_path or "").strip(),
            "dry_run": bool(dry_run),
        }
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                token = str(key or "").strip()
                if not token:
                    continue
                if token in payload:
                    continue
                payload[token] = value
        job, created = self.store.create_or_get_job(
            job_id=str(uuid.uuid4()),
            idempotency_key=str(idempotency_key),
            job_type="generate_cover",
            catalog_id=str(catalog_id),
            book_number=int(book),
            payload=payload,
            max_attempts=max(1, int(max_attempts)),
            priority=100,
        )
        return job, created

    def _run_worker(self, worker_id: str) -> None:
        last_idle_heartbeat = 0.0
        self._write_heartbeat(worker_id=worker_id, state="idle")
        while not self._stop_event.is_set():
            job = self.store.lease_next_job(worker_id=worker_id, job_types=["generate_cover"])
            if job is None:
                now = time.time()
                if (now - last_idle_heartbeat) >= 10.0:
                    self._write_heartbeat(worker_id=worker_id, state="idle")
                    last_idle_heartbeat = now
                self._stop_event.wait(0.35)
                continue

            attempt_number = int(job.attempts or 0) + 1
            batch_id = str((job.payload or {}).get("batch_id", "") or "").strip()
            self._write_heartbeat(worker_id=worker_id, state="running", job_id=job.id)
            job_event_broker.publish(
                "job_started",
                {
                    "job_id": job.id,
                    "catalog_id": job.catalog_id,
                    "book_number": int(job.book_number or 0),
                    "job_type": job.job_type,
                    "status": "running",
                    "attempt_number": attempt_number,
                    "progress": 0.0,
                    "batch_id": batch_id,
                },
            )
            job_event_broker.publish(
                "job_progress",
                {
                    "job_id": job.id,
                    "catalog_id": job.catalog_id,
                    "book_number": int(job.book_number or 0),
                    "job_type": job.job_type,
                    "status": "running",
                    "progress": 0.0,
                    "batch_id": batch_id,
                },
            )
            attempt_id = self.store.record_attempt_start(
                job.id,
                attempt_number=attempt_number,
                meta={"worker_id": worker_id, "job_type": job.job_type},
            )
            try:
                execution_payload = dict(job.payload or {})
                execution_payload["job_id"] = job.id
                if batch_id:
                    execution_payload["batch_id"] = batch_id

                def _publish_stage_progress(stage_payload: dict[str, Any]) -> None:
                    stage = str(stage_payload.get("stage", "") or "").strip()
                    message = str(stage_payload.get("message", "") or "").strip()
                    progress = max(0.0, min(1.0, _safe_float(stage_payload.get("progress"), 0.0)))
                    event_payload = {
                        "job_id": job.id,
                        "catalog_id": job.catalog_id,
                        "book_number": int(job.book_number or 0),
                        "job_type": job.job_type,
                        "status": "running",
                        "progress": progress,
                        "batch_id": batch_id,
                        "stage": stage,
                        "message": message,
                    }
                    job_event_broker.publish("job_progress", event_payload)

                executor = _execute_generation_payload
                stage_supported = False
                try:
                    stage_supported = "stage_callback" in inspect.signature(executor).parameters
                except Exception:
                    stage_supported = False
                if stage_supported:
                    result = executor(execution_payload, stage_callback=_publish_stage_progress)
                else:
                    result = executor(execution_payload)
                result_rows = result.get("results", []) if isinstance(result, dict) else []
                if isinstance(result_rows, list):
                    for row in result_rows:
                        if not isinstance(row, dict):
                            continue
                        job_event_broker.publish(
                            "variant_complete",
                            {
                                "job_id": job.id,
                                "catalog_id": job.catalog_id,
                                "book_number": int(job.book_number or 0),
                                "batch_id": batch_id,
                                "variant": _safe_int(row.get("variant", row.get("variant_id", 0)), 0),
                                "model": str(row.get("model", "")).strip(),
                                "success": bool(row.get("success", False)),
                                "quality_score": _safe_float(row.get("quality_score"), 0.0),
                                "image_path": row.get("image_path"),
                                "composited_path": row.get("composited_path"),
                            },
                        )
                row = self.store.mark_completed(job.id, result=result)
                self.store.record_attempt_end(
                    attempt_id,
                    status="completed",
                    meta={"worker_id": worker_id, "results": len(result.get("results", []))},
                )
                job_event_broker.publish(
                    "job_progress",
                    {
                        "job_id": job.id,
                        "catalog_id": job.catalog_id,
                        "book_number": int(job.book_number or 0),
                        "job_type": job.job_type,
                        "status": "completed",
                        "progress": 1.0,
                        "batch_id": batch_id,
                    },
                )
                job_event_broker.publish(
                    "book_completed",
                    {
                        "job_id": job.id,
                        "catalog_id": job.catalog_id,
                        "book_number": int(job.book_number or 0),
                        "job_type": job.job_type,
                        "status": "completed",
                        "result_count": len(result.get("results", [])),
                        "batch_id": batch_id,
                    },
                )
                if row is not None:
                    job_event_broker.publish(
                        "job_completed",
                        {
                            "job_id": row.id,
                            "catalog_id": row.catalog_id,
                            "book_number": int(row.book_number or 0),
                            "job_type": row.job_type,
                            "status": row.status,
                            "attempts": int(row.attempts or 0),
                            "result": row.result,
                            "batch_id": batch_id,
                        },
                    )
                    _batch_publish_progress_for_job(row)
                self._write_heartbeat(worker_id=worker_id, state="idle")
            except JobStageError as exc:
                error_payload = {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                    "stage": exc.stage,
                    **({"failures": exc.details.get("failures", [])} if exc.details.get("failures") else {}),
                }
                attempt_meta = {
                    "worker_id": worker_id,
                    "stage": exc.stage,
                    "error_type": exc.__class__.__name__,
                    **({"failures": exc.details.get("failures", [])} if exc.details.get("failures") else {}),
                }
                if exc.retryable:
                    delay = min(60.0, max(2.0, 2.0 ** attempt_number))
                    state = self.store.mark_failed(
                        job.id,
                        error=error_payload,
                        retryable=True,
                        retry_delay_seconds=delay,
                    )
                    status = state.status if state else "retrying"
                    self.store.record_attempt_end(
                        attempt_id,
                        status=status,
                        error_text=str(exc),
                        meta={**attempt_meta, "retry_delay_seconds": delay},
                    )
                    job_event_broker.publish(
                        "job_failed",
                        {
                            "job_id": job.id,
                            "catalog_id": job.catalog_id,
                            "book_number": int(job.book_number or 0),
                            "job_type": job.job_type,
                            "status": status,
                            "error": str(exc),
                            "stage": exc.stage,
                            "retry_delay_seconds": delay,
                            "attempt_number": attempt_number,
                            "batch_id": batch_id,
                        },
                    )
                    if state is not None:
                        _batch_publish_progress_for_job(state)
                else:
                    row = self.store.mark_failed(
                        job.id,
                        error=error_payload,
                        retryable=False,
                        retry_delay_seconds=0.0,
                    )
                    status = row.status if row is not None else "failed"
                    self.store.record_attempt_end(
                        attempt_id,
                        status=status,
                        error_text=str(exc),
                        meta=attempt_meta,
                    )
                    job_event_broker.publish(
                        "job_failed",
                        {
                            "job_id": job.id,
                            "catalog_id": job.catalog_id,
                            "book_number": int(job.book_number or 0),
                            "job_type": job.job_type,
                            "status": status,
                            "error": str(exc),
                            "stage": exc.stage,
                            "attempt_number": attempt_number,
                            "batch_id": batch_id,
                        },
                    )
                    if row is not None:
                        _batch_publish_progress_for_job(row)
                    logger.error(
                        "Async generation job failed",
                        extra={"job_id": job.id, "error": str(exc), "stage": exc.stage},
                    )
                self._write_heartbeat(worker_id=worker_id, state="idle")
            except (image_generator.RetryableGenerationError, requests.RequestException) as exc:
                delay = min(60.0, max(2.0, 2.0 ** attempt_number))
                error_payload = {"message": str(exc), "type": exc.__class__.__name__, "stage": "generate"}
                state = self.store.mark_failed(
                    job.id,
                    error=error_payload,
                    retryable=True,
                    retry_delay_seconds=delay,
                )
                status = state.status if state else "retrying"
                self.store.record_attempt_end(
                    attempt_id,
                    status=status,
                    error_text=str(exc),
                    meta={
                        "worker_id": worker_id,
                        "retry_delay_seconds": delay,
                        "stage": "generate",
                        "error_type": exc.__class__.__name__,
                    },
                )
                job_event_broker.publish(
                    "job_failed",
                    {
                        "job_id": job.id,
                        "catalog_id": job.catalog_id,
                        "book_number": int(job.book_number or 0),
                        "job_type": job.job_type,
                        "status": status,
                        "error": str(exc),
                        "stage": "generate",
                        "retry_delay_seconds": delay,
                        "attempt_number": attempt_number,
                        "batch_id": batch_id,
                    },
                )
                if state is not None:
                    _batch_publish_progress_for_job(state)
                self._write_heartbeat(worker_id=worker_id, state="idle")
            except Exception as exc:  # pragma: no cover - defensive
                error_payload = {"message": str(exc), "type": exc.__class__.__name__}
                row = self.store.mark_failed(
                    job.id,
                    error=error_payload,
                    retryable=False,
                    retry_delay_seconds=0.0,
                )
                self.store.record_attempt_end(
                    attempt_id,
                    status="failed",
                    error_text=str(exc),
                    meta={"worker_id": worker_id, "error_type": exc.__class__.__name__},
                )
                job_event_broker.publish(
                    "job_failed",
                    {
                        "job_id": job.id,
                        "catalog_id": job.catalog_id,
                        "book_number": int(job.book_number or 0),
                        "job_type": job.job_type,
                        "status": row.status if row is not None else "failed",
                        "error": str(exc),
                        "attempt_number": attempt_number,
                        "batch_id": batch_id,
                    },
                )
                if row is not None:
                    _batch_publish_progress_for_job(row)
                logger.error("Async generation job failed", extra={"job_id": job.id, "error": str(exc)})
                self._write_heartbeat(worker_id=worker_id, state="idle")


data_cache = DataCache(ttl_seconds=60)
request_tracker = RequestTracker()
mutation_rate_limiter = SimpleRateLimiter(per_minute=MUTATION_RATE_LIMIT_PER_MINUTE)
read_rate_limiter = SimpleRateLimiter(per_minute=READ_RATE_LIMIT_PER_MINUTE)
generation_rate_limiter = SimpleRateLimiter(per_minute=max(1, int(os.getenv("GENERATION_RATE_LIMIT_PER_MINUTE", "5"))))
admin_rate_limiter = SimpleRateLimiter(per_minute=max(5, int(os.getenv("ADMIN_RATE_LIMIT_PER_MINUTE", "30"))))
sse_connection_limiter = SSEConnectionLimiter(per_client=SSE_MAX_CONNECTIONS_PER_CLIENT)
_catalog_mutation_limiters: dict[str, SimpleRateLimiter] = {}
_catalog_generation_limiters: dict[str, SimpleRateLimiter] = {}
_catalog_admin_limiters: dict[str, SimpleRateLimiter] = {}
_catalog_rate_limiter_lock = threading.Lock()
slo_tracker = RollingSLOTracker(SLO_METRICS_PATH)
slo_alert_manager = SLOAlertManager(
    state_path=SLO_ALERT_STATE_PATH,
    cooldown_seconds=SLO_ALERT_COOLDOWN_SECONDS,
    alert_levels=SLO_ALERT_LEVELS,
)
_slo_tracker_lock = threading.Lock()
_slo_trackers_by_path: dict[str, RollingSLOTracker] = {str(SLO_METRICS_PATH.resolve()): slo_tracker}
_similarity_recompute_lock = threading.Lock()
_similarity_recompute_jobs: dict[str, dict[str, Any]] = {}
_slo_alert_manager_lock = threading.Lock()
_slo_alert_managers_by_path: dict[str, SLOAlertManager] = {str(SLO_ALERT_STATE_PATH.resolve()): slo_alert_manager}
job_db_store = job_store.JobStore(JOBS_DB_PATH)
state_db_store = state_store.StateStore(STATE_DB_PATH)
catalog_registry = catalog_manager.CatalogManager(catalogs_path=config.CATALOGS_PATH, project_root=PROJECT_ROOT)
job_event_broker = JobEventBroker(max_queue_size=300)
job_worker_pool = JobWorkerPool(
    job_db_store,
    worker_count=JOB_WORKER_COUNT,
    heartbeat_path=JOB_WORKER_HEARTBEAT_PATH,
    service_name="web-inline",
)
state_lock = threading.Lock()
repository_lock = threading.Lock()
repository_cache: dict[str, repository.BookRepository] = {}
PROVIDER_CONNECTIVITY_CACHE_SECONDS = 300
_provider_connectivity_cache_lock = threading.Lock()
_provider_connectivity_cache: dict[str, dict[str, Any]] = {}


def _slo_tracker_for_runtime(runtime: config.Config) -> RollingSLOTracker:
    path = _slo_metrics_path_for_runtime(runtime)
    key = str(path.resolve())
    with _slo_tracker_lock:
        tracker = _slo_trackers_by_path.get(key)
        if tracker is None:
            tracker = RollingSLOTracker(path)
            _slo_trackers_by_path[key] = tracker
        return tracker


def _slo_alert_manager_for_runtime(runtime: config.Config) -> SLOAlertManager:
    path = _slo_alert_state_path_for_runtime(runtime)
    key = str(path.resolve())
    with _slo_alert_manager_lock:
        manager = _slo_alert_managers_by_path.get(key)
        if manager is None:
            manager = SLOAlertManager(
                state_path=path,
                cooldown_seconds=runtime.slo_alert_cooldown_seconds,
                alert_levels={str(token).strip().lower() for token in runtime.slo_alert_levels if str(token).strip()},
            )
            _slo_alert_managers_by_path[key] = manager
        return manager


def _flush_all_slo_trackers() -> None:
    with _slo_tracker_lock:
        trackers = list(_slo_trackers_by_path.values())
    for tracker in trackers:
        tracker.flush()


def _slo_monitor_interval_seconds(runtime: config.Config | None = None) -> int:
    runtime = runtime or config.get_config()
    interval = _safe_int(
        getattr(runtime, "slo_monitor_interval_seconds", SLO_MONITOR_INTERVAL_SECONDS),
        SLO_MONITOR_INTERVAL_SECONDS,
    )
    return max(0, int(interval))


class SLOBackgroundMonitor:
    """Periodic SLO evaluator that keeps alerting active without API polling."""

    def __init__(
        self,
        *,
        interval_seconds: int,
        runtime_loader: Callable[[str | None], Any] | None = None,
        catalog_ids_loader: Callable[[], list[str]] | None = None,
    ) -> None:
        self.interval_seconds = max(1, int(interval_seconds))
        self.runtime_loader = runtime_loader or (lambda catalog_id=None: config.get_config(catalog_id))
        self.catalog_ids_loader = catalog_ids_loader or self._default_catalog_ids
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "enabled": self.interval_seconds > 0,
            "running": False,
            "interval_seconds": int(self.interval_seconds),
            "last_run_at": "",
            "last_duration_ms": 0.0,
            "catalogs_checked": 0,
            "alerts_sent": 0,
            "errors": [],
            "catalog_summaries": [],
        }

    def _default_catalog_ids(self) -> list[str]:
        try:
            rows = config.list_catalogs()
        except Exception:
            rows = []
        ids = [str(row.id).strip() for row in rows if str(getattr(row, "id", "")).strip()]
        if not ids:
            return [str(config.DEFAULT_CATALOG_ID)]
        return ids

    @staticmethod
    def _normalize_catalog_ids(raw: list[str]) -> list[str]:
        seen: set[str] = set()
        ids: list[str] = []
        for item in raw:
            token = str(item or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            ids.append(token)
        return ids

    def start(self) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._state["running"] = True
            thread = threading.Thread(target=self._loop, name="slo-monitor", daemon=True)
            self._thread = thread
            thread.start()
            return True

    def stop(self, *, timeout_seconds: float = 2.0) -> None:
        thread: threading.Thread | None
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None:
            thread.join(timeout=max(0.1, float(timeout_seconds)))
        with self._lock:
            self._state["running"] = False
            self._thread = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["errors"] = list(self._state.get("errors", []))
            state["catalog_summaries"] = list(self._state.get("catalog_summaries", []))
            return state

    def run_once(self, *, catalog_ids: list[str] | None = None) -> dict[str, Any]:
        started = time.time()
        ids = self._normalize_catalog_ids(catalog_ids if catalog_ids is not None else self.catalog_ids_loader())
        now = datetime.now(timezone.utc).isoformat()
        summaries: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        alerts_sent = 0
        for catalog_id in ids:
            try:
                runtime = self.runtime_loader(catalog_id)
                _, _, evaluation = _build_slo_evaluation(runtime=runtime)
                alert = _slo_alert_manager_for_runtime(runtime).maybe_alert(runtime=runtime, slo_evaluation=evaluation)
                if bool(alert.get("sent", False)):
                    alerts_sent += 1
                summary = {
                    "catalog_id": str(getattr(runtime, "catalog_id", catalog_id) or catalog_id),
                    "sent": bool(alert.get("sent", False)),
                    "reason": str(alert.get("reason", "")),
                    "severity": str(alert.get("severity", "")),
                    "status": {
                        "api_success_rate_7d": str(evaluation.get("api_success_rate_7d", {}).get("status", "")),
                        "job_completion_without_manual_intervention": str(
                            evaluation.get("job_completion_without_manual_intervention", {}).get("status", "")
                        ),
                        "same_stage_retry_rate": str(evaluation.get("same_stage_retry_rate", {}).get("status", "")),
                    },
                }
                summaries.append(summary)
            except Exception as exc:
                logger.warning("Background SLO monitor failed for catalog %s: %s", catalog_id, exc)
                errors.append({"catalog_id": catalog_id, "error": str(exc)})

        snapshot = {
            "enabled": True,
            "running": True,
            "interval_seconds": int(self.interval_seconds),
            "last_run_at": now,
            "last_duration_ms": round((time.time() - started) * 1000.0, 3),
            "catalogs_checked": len(summaries),
            "alerts_sent": int(alerts_sent),
            "errors": errors[-20:],
            "catalog_summaries": summaries[-50:],
        }
        with self._lock:
            self._state.update(snapshot)
        return dict(snapshot)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                logger.warning("Background SLO monitor iteration failed: %s", exc)
            if self._stop_event.wait(self.interval_seconds):
                break
        with self._lock:
            self._state["running"] = False


_slo_background_monitor_lock = threading.Lock()
_slo_background_monitor: SLOBackgroundMonitor | None = None


def _set_slo_background_monitor(monitor: SLOBackgroundMonitor | None) -> None:
    global _slo_background_monitor
    with _slo_background_monitor_lock:
        _slo_background_monitor = monitor


def _slo_background_monitor_snapshot() -> dict[str, Any]:
    with _slo_background_monitor_lock:
        monitor = _slo_background_monitor
    if monitor is None:
        return {
            "enabled": False,
            "running": False,
            "interval_seconds": 0,
            "last_run_at": "",
            "last_duration_ms": 0.0,
            "catalogs_checked": 0,
            "alerts_sent": 0,
            "errors": [],
            "catalog_summaries": [],
        }
    return monitor.snapshot()


def _repository_for_runtime(runtime: config.Config) -> repository.BookRepository:
    key = f"{runtime.catalog_id}:{int(bool(runtime.use_sqlite))}:{runtime.sqlite_db_path}"
    with repository_lock:
        existing = repository_cache.get(key)
        if existing is not None:
            return existing
        repo = repository.get_repository(runtime=runtime)
        repository_cache[key] = repo
        return repo


def _cache_key(path: str, query: dict[str, list[str]], catalog: str) -> str:
    if not query:
        return f"{catalog}:{path}"
    items: list[str] = []
    for key in sorted(query.keys()):
        vals = ",".join(sorted([str(v) for v in query.get(key, [])]))
        items.append(f"{key}={vals}")
    return f"{catalog}:{path}?{'&'.join(items)}"


def _invalidate_cache(*prefixes: str, catalog_id: str | None = None) -> int:
    removed = 0
    for prefix in prefixes:
        if prefix == "*":
            data_cache.clear()
            return -1
        catalogs = {item.id for item in config.list_catalogs()} | {"classics"}
        if catalog_id:
            catalogs.add(str(catalog_id))
        for cat in catalogs:
            removed += data_cache.invalidate_prefix(f"{cat}:{prefix}")
    return removed


def _parse_pagination(
    query: dict[str, list[str]],
    *,
    default_limit: int,
    max_limit: int,
) -> tuple[int, int]:
    limit = _safe_int(query.get("limit", [str(default_limit)])[0], default_limit)
    offset = _safe_int(query.get("offset", ["0"])[0], 0)
    limit = max(1, min(max_limit, limit))
    offset = max(0, offset)
    return limit, offset


def _pagination_payload(*, total: int, limit: int, offset: int) -> dict[str, Any]:
    return {
        "total": int(max(0, total)),
        "limit": int(max(1, limit)),
        "offset": int(max(0, offset)),
        "has_more": int(offset + limit) < int(max(0, total)),
    }


def _paginate_rows(rows: list[dict[str, Any]], *, limit: int, offset: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(rows)
    start = max(0, int(offset))
    end = start + max(1, int(limit))
    page = rows[start:end]
    return page, _pagination_payload(total=total, limit=limit, offset=offset)


def _normalize_sort_order(query: dict[str, list[str]]) -> tuple[str, str]:
    sort = str(query.get("sort", ["book_number"])[0] or "book_number").strip().lower() or "book_number"
    order = str(query.get("order", ["asc"])[0] or "asc").strip().lower()
    if order not in {"asc", "desc"}:
        order = "asc"
    return sort, order


def _books_filters_from_query(query: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "status": str(query.get("status", [""])[0] or "").strip(),
        "quality_min": query.get("quality_min", [None])[0],
        "quality_max": query.get("quality_max", [None])[0],
        "tags": str(query.get("tags", [""])[0] or "").strip(),
        "search": str(query.get("search", [""])[0] or "").strip(),
    }


def _catalog_scoped_limiter(
    *,
    catalog_id: str | None,
    default_limiter: SimpleRateLimiter,
    catalog_rows: dict[str, SimpleRateLimiter],
) -> SimpleRateLimiter:
    token = str(catalog_id or "").strip().lower()
    if not token:
        return default_limiter
    with _catalog_rate_limiter_lock:
        limiter = catalog_rows.get(token)
        if limiter is None:
            limiter = SimpleRateLimiter(per_minute=default_limiter.per_minute)
            catalog_rows[token] = limiter
        return limiter


def _mutation_limiter(path: str, *, catalog_id: str | None = None) -> tuple[SimpleRateLimiter, int]:
    token = str(path or "").strip().lower()
    if token.startswith("/api/generate") or token.startswith("/api/jobs") or token.startswith("/api/export") or token.startswith("/api/delivery"):
        limiter = _catalog_scoped_limiter(
            catalog_id=catalog_id,
            default_limiter=generation_rate_limiter,
            catalog_rows=_catalog_generation_limiters,
        )
        return limiter, limiter.per_minute
    if token.startswith("/api/admin"):
        limiter = _catalog_scoped_limiter(
            catalog_id=catalog_id,
            default_limiter=admin_rate_limiter,
            catalog_rows=_catalog_admin_limiters,
        )
        return limiter, limiter.per_minute
    limiter = _catalog_scoped_limiter(
        catalog_id=catalog_id,
        default_limiter=mutation_rate_limiter,
        catalog_rows=_catalog_mutation_limiters,
    )
    return limiter, limiter.per_minute


def _worker_runtime_status(*, worker_mode: str | None = None) -> dict[str, Any]:
    mode = _normalize_worker_mode(worker_mode or ACTIVE_WORKER_MODE)
    payload = safe_json.load_json(JOB_WORKER_HEARTBEAT_PATH, {})
    if not isinstance(payload, dict):
        payload = {}
    updated_at = str(payload.get("updated_at", "") or "")
    workers = payload.get("workers", {})
    if not isinstance(workers, dict):
        workers = {}
    now = datetime.now(timezone.utc)
    updated_dt = _safe_iso_datetime(updated_at)
    age_seconds = (now - updated_dt).total_seconds() if updated_dt else None
    alive = bool(updated_dt and age_seconds is not None and age_seconds <= JOB_WORKER_HEARTBEAT_STALE_SECONDS)
    running = 0
    idle = 0
    for row in workers.values():
        if not isinstance(row, dict):
            continue
        state = str(row.get("state", "")).strip().lower()
        if state == "running":
            running += 1
        elif state == "idle":
            idle += 1
    return {
        "mode": mode,
        "heartbeat_path": str(JOB_WORKER_HEARTBEAT_PATH),
        "service": str(payload.get("service", "") or ""),
        "updated_at": updated_at,
        "age_seconds": round(float(age_seconds), 3) if age_seconds is not None else None,
        "stale_after_seconds": JOB_WORKER_HEARTBEAT_STALE_SECONDS,
        "alive": alive,
        "worker_count": int(payload.get("worker_count", 0) or len(workers)),
        "running_workers": running,
        "idle_workers": idle,
        "pid": int(payload.get("pid", 0) or 0),
    }


def _record_audit_event(
    *,
    action: str,
    impact: str,
    actor: str,
    source_ip: str,
    endpoint: str,
    catalog_id: str,
    status: str,
    details: dict[str, Any] | None = None,
    data_dir: Path | None = None,
) -> None:
    try:
        audit_log.append_event(
            action=action,
            impact=impact,
            actor=actor,
            source_ip=source_ip,
            endpoint=endpoint,
            catalog_id=catalog_id,
            status=status,
            details=details or {},
            path=config.audit_log_path(catalog_id=catalog_id, data_dir=(data_dir or config.DATA_DIR)),
        )
    except Exception as exc:  # pragma: no cover - audit logging must never break request flow
        logger.warning("Audit log write failed: %s", exc)


def _generation_idempotency_key(
    *,
    catalog_id: str,
    book: int,
    models: list[str],
    variants: int,
    prompt: str,
    provider: str,
    cover_source: str = "catalog",
    selected_cover_id: str = "",
    dry_run: bool = False,
) -> str:
    normalized_models = sorted({str(item).strip() for item in models if str(item).strip()})
    normalized_prompt = " ".join(str(prompt or "").split())
    normalized_provider = str(provider or "all").strip().lower() or "all"
    normalized_cover_source = str(cover_source or "catalog").strip().lower() or "catalog"
    if normalized_cover_source not in {"catalog", "drive"}:
        normalized_cover_source = "catalog"
    normalized_selected_cover_id = str(selected_cover_id or "").strip()
    payload = {
        "catalog": str(catalog_id),
        "book": int(book),
        "models": normalized_models,
        "variants": int(variants),
        "prompt": normalized_prompt,
        "provider": normalized_provider,
        "cover_source": normalized_cover_source,
        "selected_cover_id": normalized_selected_cover_id,
        "dry_run": bool(dry_run),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"generate:{digest}"


def _max_generation_variants(runtime: config.Config) -> int:
    configured = _safe_int(getattr(runtime, "max_generation_variants", config.MAX_GENERATION_VARIANTS), config.MAX_GENERATION_VARIANTS)
    return max(1, configured)


def _mark_job_model_cancelled(*, job_id: str, catalog_id: str, model: str) -> None:
    with _JOB_CANCELLED_MODELS_LOCK:
        catalog_rows = _JOB_CANCELLED_MODELS.setdefault(str(catalog_id), {})
        rows = catalog_rows.setdefault(str(job_id), set())
        rows.add(str(model))


def _is_job_model_cancelled(*, job_id: str, catalog_id: str, model: str) -> bool:
    with _JOB_CANCELLED_MODELS_LOCK:
        catalog_rows = _JOB_CANCELLED_MODELS.get(str(catalog_id), {})
        rows = catalog_rows.get(str(job_id), set())
        return str(model) in rows


def _clear_job_model_cancellations(*, job_id: str, catalog_id: str) -> None:
    with _JOB_CANCELLED_MODELS_LOCK:
        catalog_rows = _JOB_CANCELLED_MODELS.get(str(catalog_id), {})
        catalog_rows.pop(str(job_id), None)
        if not catalog_rows and str(catalog_id) in _JOB_CANCELLED_MODELS:
            _JOB_CANCELLED_MODELS.pop(str(catalog_id), None)


def _record_slow_request(*, method: str, path: str, duration_seconds: float, status_code: int, catalog_id: str) -> None:
    if float(duration_seconds) < _SLOW_REQUEST_THRESHOLD_SECONDS:
        return
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": str(method),
        "path": str(path),
        "duration_seconds": round(float(duration_seconds), 4),
        "status_code": int(status_code),
        "catalog": str(catalog_id),
    }
    with _SLOW_REQUEST_LOG_LOCK:
        _SLOW_REQUEST_LOG.append(row)
        if len(_SLOW_REQUEST_LOG) > 2000:
            del _SLOW_REQUEST_LOG[:-2000]


def _slow_request_snapshot(*, limit: int = 200) -> list[dict[str, Any]]:
    with _SLOW_REQUEST_LOG_LOCK:
        rows = list(_SLOW_REQUEST_LOG[-max(1, min(2000, int(limit))) :])
    rows.sort(key=lambda item: (_safe_float(item.get("duration_seconds"), 0.0), str(item.get("timestamp", ""))), reverse=True)
    return rows


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(float(v) for v in values)
    rank = max(0.0, min(1.0, float(p))) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(ordered[lower])
    weight = rank - float(lower)
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _performance_summary_payload(*, runtime: config.Config) -> dict[str, Any]:
    slow_rows = _slow_request_snapshot(limit=500)
    durations = [max(0.0, _safe_float(row.get("duration_seconds"), 0.0)) for row in slow_rows]
    endpoint_rollup: dict[str, dict[str, float]] = {}
    for row in slow_rows:
        path = str(row.get("path", "")).strip() or "/"
        bucket = endpoint_rollup.setdefault(path, {"count": 0.0, "max_duration_seconds": 0.0, "total_duration_seconds": 0.0})
        duration = max(0.0, _safe_float(row.get("duration_seconds"), 0.0))
        bucket["count"] += 1.0
        bucket["total_duration_seconds"] += duration
        if duration > bucket["max_duration_seconds"]:
            bucket["max_duration_seconds"] = duration
    top_slow = sorted(
        (
            {
                "path": path,
                "count": int(values["count"]),
                "max_duration_seconds": round(values["max_duration_seconds"], 4),
                "avg_duration_seconds": round(
                    values["total_duration_seconds"] / max(1.0, values["count"]),
                    4,
                ),
            }
            for path, values in endpoint_rollup.items()
        ),
        key=lambda item: (int(item.get("count", 0)), float(item.get("max_duration_seconds", 0.0))),
        reverse=True,
    )[:25]

    worker_status = _worker_runtime_status()
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_threshold_seconds": float(_SLOW_REQUEST_THRESHOLD_SECONDS),
        "response_time": {
            "sample_size": len(durations),
            "avg_seconds": round(sum(durations) / len(durations), 4) if durations else 0.0,
            "p50_seconds": round(_percentile(durations, 0.50), 4),
            "p95_seconds": round(_percentile(durations, 0.95), 4),
            "p99_seconds": round(_percentile(durations, 0.99), 4),
        },
        "slow_requests": {
            "count": len(slow_rows),
            "threshold_seconds": float(_SLOW_REQUEST_THRESHOLD_SECONDS),
            "top_endpoints": top_slow,
            "latest": slow_rows[:100],
        },
        "errors": error_metrics.get_metrics(catalog_id=runtime.catalog_id),
        "cache": data_cache.stats(),
        "jobs": {
            "status_counts": job_db_store.status_counts(),
            "workers_configured": JOB_WORKER_COUNT,
            "worker_mode": worker_status.get("mode"),
            "worker_service": worker_status,
        },
    }


def _serialize_generation_results(
    *,
    runtime: config.Config,
    book: int,
    results: list[image_generator.GenerationResult],
    job_id: str = "",
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    fit_overlay_rel = None
    fit_overlay = runtime.tmp_dir / "composited" / str(book) / "fit_overlay.png"
    if fit_overlay.exists():
        fit_overlay_rel = _to_project_relative(fit_overlay)

    raw_job_token = _generation_artifact_job_token(job_id=job_id)

    for row in results:
        image_rel = _to_project_relative(row.image_path) if row.image_path else None
        # Persist raw AI art to a durable location for download ZIPs.
        persisted_raw_path = None
        model_token = str(row.model or "unknown").replace("/", "_").replace(" ", "_")
        if row.image_path and Path(row.image_path).exists():
            raw_art_dir = runtime.output_dir / "raw_art" / str(row.book_number)
            raw_art_dir.mkdir(parents=True, exist_ok=True)
            dest = raw_art_dir / f"{raw_job_token}_variant_{row.variant}_{model_token}.png"
            try:
                shutil.copy2(str(row.image_path), str(dest))
                persisted_raw_path = _to_project_relative(dest)
                logger.info("Persisted raw AI art to %s", dest)
            except Exception as exc:
                logger.warning("Failed to persist raw AI art: %s", exc)
        composed = None
        persisted_composite_path = None
        if row.image_path:
            candidate = _resolve_composited_candidate(row.image_path, runtime=runtime)
            if candidate and candidate.exists():
                composed = _to_project_relative(candidate)
                persisted_composite_path = _persist_composite_image(
                    runtime=runtime,
                    book_number=row.book_number,
                    variant=row.variant,
                    model_token=model_token,
                    composite_source=candidate,
                    job_token=raw_job_token,
                    raw_art_source=(PROJECT_ROOT / str(persisted_raw_path)) if persisted_raw_path else (Path(row.image_path) if Path(row.image_path).exists() else None),
                    raw_art_path_token=str(persisted_raw_path or image_rel or "").strip(),
                )
        composed_pdf_path = None
        composed_ai_path = None
        if composed:
            composed_path = PROJECT_ROOT / str(composed)
            pdf_candidate = _resolve_composited_companion(composed_path, ".pdf")
            if pdf_candidate and pdf_candidate.exists():
                composed_pdf_path = _to_project_relative(pdf_candidate)
            ai_candidate = _resolve_composited_companion(composed_path, ".ai")
            if ai_candidate and ai_candidate.exists():
                composed_ai_path = _to_project_relative(ai_candidate)
        serialized.append(
            {
                "book_number": row.book_number,
                "variant": row.variant,
                "model": row.model,
                "provider": row.provider,
                "prompt": row.prompt,
                "image_path": image_rel,
                "raw_art_path": persisted_raw_path,
                "composited_path": persisted_composite_path or composed,
                "saved_composited_path": persisted_composite_path,
                "composited_pdf_path": composed_pdf_path,
                "composited_ai_path": composed_ai_path,
                "success": row.success,
                "error": row.error,
                "generation_time": row.generation_time,
                "cost": row.cost,
                "dry_run": row.dry_run,
                "attempts": row.attempts,
                "failure_meta": row.failure_meta,
                "similarity_warning": row.similarity_warning,
                "similar_to_book": row.similar_to_book,
                "distinctiveness_score": row.distinctiveness_score,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fit_overlay_path": fit_overlay_rel,
            }
        )
    return serialized


def _apply_style_edge_trim(
    *,
    results: list[image_generator.GenerationResult],
    trim_ratio: float = STYLE_EDGE_TRIM_RATIO,
) -> None:
    ratio = max(0.0, min(float(trim_ratio), 0.2))
    if ratio <= 0:
        return
    for row in results:
        prompt_text = " ".join(str(getattr(row, "prompt", "") or "").split()).strip().lower()
        style_token = next(
            (label for marker, label in STYLE_EDGE_TRIM_PROMPT_MARKERS.items() if marker in prompt_text),
            "",
        )
        image_path = getattr(row, "image_path", None)
        if not style_token:
            continue
        if not bool(getattr(row, "success", False)) or image_path is None:
            continue
        path = Path(image_path)
        if not path.exists():
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
                dx = max(1, int(width * ratio))
                dy = max(1, int(height * ratio))
                if (width - (2 * dx)) < 64 or (height - (2 * dy)) < 64:
                    continue
                trimmed = image.crop((dx, dy, width - dx, height - dy)).resize((width, height), Image.Resampling.LANCZOS)
                trimmed.save(path)
            logger.info(
                "Applied style edge trim to %s for %s (ratio=%.3f)",
                path,
                style_token,
                ratio,
            )
        except Exception as exc:
            logger.warning("Failed to apply style edge trim to %s: %s", path, exc)


def _generation_artifact_job_token(*, job_id: str = "", row: dict[str, Any] | None = None) -> str:
    explicit = re.sub(r"[^A-Za-z0-9_-]+", "", str(job_id or "").strip())[:64]
    if explicit:
        return explicit
    if isinstance(row, dict):
        raw_art_path = str(row.get("raw_art_path", "") or "").strip()
        if raw_art_path:
            stem = Path(raw_art_path).stem
            match = re.match(r"(?P<token>.+?)_variant_\d+_", stem)
            if match:
                token = re.sub(r"[^A-Za-z0-9_-]+", "", str(match.group("token") or "").strip())[:64]
                if token:
                    return token
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def _persist_composite_image(
    *,
    runtime: config.Config,
    book_number: int,
    variant: int,
    model_token: str,
    composite_source: Path,
    job_token: str,
    raw_art_source: Path | None = None,
    raw_art_path_token: str = "",
) -> str | None:
    if not composite_source.exists():
        return None
    composite_dir = runtime.output_dir / "saved_composites" / str(book_number)
    composite_dir.mkdir(parents=True, exist_ok=True)
    composite_dest = composite_dir / f"{job_token}_variant_{int(variant)}_{model_token}.jpg"
    try:
        shutil.copy2(str(composite_source), str(composite_dest))
        _write_saved_composite_manifest(
            composite_path=composite_dest,
            job_token=job_token,
            book_number=book_number,
            variant=variant,
            model_token=model_token,
            raw_art_source=raw_art_source,
            raw_art_path_token=raw_art_path_token,
        )
        logger.info("Persisted composite image to %s", composite_dest)
        return _to_project_relative(composite_dest)
    except Exception as exc:
        logger.warning("Failed to persist composite image: %s", exc)
        return None


def _saved_composite_manifest_path(composite_path: Path) -> Path:
    return Path(f"{composite_path}.manifest.json")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_saved_composite_manifest(
    *,
    composite_path: Path,
    job_token: str,
    book_number: int,
    variant: int,
    model_token: str,
    raw_art_source: Path | None,
    raw_art_path_token: str,
) -> None:
    safe_json.atomic_write_json(
        _saved_composite_manifest_path(composite_path),
        {
            "job_token": str(job_token or "").strip(),
            "book_number": int(book_number),
            "variant": int(variant),
            "model_token": str(model_token or "").strip(),
            "saved_composite_path": _to_project_relative(composite_path),
            "saved_composite_sha256": _file_sha256(composite_path),
            "raw_art_path": str(raw_art_path_token or "").strip(),
            "raw_art_sha256": _file_sha256(raw_art_source) if raw_art_source is not None and raw_art_source.exists() else "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _saved_composite_destination_for_row(*, runtime: config.Config, row: dict[str, Any]) -> Path | None:
    configured = _project_path_if_exists(row.get("saved_composited_path"))
    if configured is not None:
        return configured
    book_number = _safe_int(row.get("book_number"), 0)
    variant = _safe_int(row.get("variant"), 0)
    if book_number <= 0 or variant <= 0:
        return None
    composite_dir = runtime.output_dir / "saved_composites" / str(book_number)
    composite_dir.mkdir(parents=True, exist_ok=True)
    model_token = str(row.get("model", "unknown") or "unknown").replace("/", "_").replace(" ", "_")
    job_token = _generation_artifact_job_token(row=row)
    return composite_dir / f"{job_token}_variant_{int(variant)}_{model_token}.jpg"


def _saved_composite_manifest_matches_row(*, runtime: config.Config, row: dict[str, Any], composite_path: Path) -> bool:
    payload = _load_json(_saved_composite_manifest_path(composite_path), {})
    if not isinstance(payload, dict) or not payload:
        return False
    try:
        if str(payload.get("saved_composite_sha256", "") or "").strip() != _file_sha256(composite_path):
            return False
    except Exception:
        return False
    expected_job_token = _generation_artifact_job_token(row=row)
    if expected_job_token and str(payload.get("job_token", "") or "").strip() != expected_job_token:
        return False
    expected_variant = _safe_int(row.get("variant"), 0)
    if expected_variant > 0 and _safe_int(payload.get("variant"), 0) != expected_variant:
        return False
    expected_model = str(row.get("model", "") or "").strip().replace("/", "_").replace(" ", "_")
    if expected_model and str(payload.get("model_token", "") or "").strip() != expected_model:
        return False
    expected_raw_rel = str(row.get("raw_art_path", "") or "").strip()
    manifest_raw_rel = str(payload.get("raw_art_path", "") or "").strip()
    if expected_raw_rel and manifest_raw_rel != expected_raw_rel:
        return False
    raw_art = _resolve_durable_raw_image_path(runtime=runtime, row=row)
    if raw_art is not None and raw_art.exists():
        if str(payload.get("raw_art_sha256", "") or "").strip() != _file_sha256(raw_art):
            return False
    return True


def _rebuild_saved_composite_from_raw_art(*, runtime: config.Config, row: dict[str, Any], output_path: Path) -> Path | None:
    raw_art = _resolve_durable_raw_image_path(runtime=runtime, row=row)
    book_number = _safe_int(row.get("book_number"), 0)
    variant = _safe_int(row.get("variant"), 0)
    if raw_art is None or not raw_art.exists() or book_number <= 0 or variant <= 0:
        return None
    cover_path = _first_local_cover_path(runtime=runtime, book_number=book_number)
    if cover_path is None or not cover_path.exists():
        cover_path, _status, _meta = _resolve_cover_preview_source_path(
            runtime=runtime,
            book_number=book_number,
            source="catalog",
        )
    if cover_path is None or not cover_path.exists():
        return None
    regions = _load_json(config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir), {})
    region = cover_compositor._region_for_book(regions, book_number)  # type: ignore[attr-defined]
    source_pdf = pdf_compositor.find_source_pdf_for_book(
        input_dir=runtime.input_dir,
        book_number=book_number,
        catalog_path=runtime.book_catalog_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rebuilt = cover_compositor.composite_single(
        cover_path=cover_path,
        illustration_path=raw_art,
        region=region,
        output_path=output_path,
        source_pdf_path=source_pdf,
    )
    _write_saved_composite_manifest(
        composite_path=rebuilt,
        job_token=_generation_artifact_job_token(row=row),
        book_number=book_number,
        variant=variant,
        model_token=str(row.get("model", "unknown") or "unknown").replace("/", "_").replace(" ", "_"),
        raw_art_source=raw_art,
        raw_art_path_token=str(row.get("raw_art_path", "") or "").strip(),
    )
    return rebuilt


def _ensure_saved_composite_for_row(*, runtime: config.Config, row: dict[str, Any]) -> Path | None:
    composite_path = _project_path_if_exists(row.get("saved_composited_path"))
    if composite_path is not None and composite_path.exists():
        if _saved_composite_manifest_matches_row(runtime=runtime, row=row, composite_path=composite_path):
            return composite_path
        if _resolve_durable_raw_image_path(runtime=runtime, row=row) is None:
            return composite_path
    destination = composite_path or _saved_composite_destination_for_row(runtime=runtime, row=row)
    if destination is None:
        return composite_path if composite_path is not None and composite_path.exists() else None
    rebuilt = _rebuild_saved_composite_from_raw_art(runtime=runtime, row=row, output_path=destination)
    if rebuilt is not None and rebuilt.exists():
        row["saved_composited_path"] = _to_project_relative(rebuilt)
        return rebuilt
    if composite_path is not None and composite_path.exists() and _resolve_durable_raw_image_path(runtime=runtime, row=row) is None:
        return composite_path
    return None


def _hydrate_serialized_result_paths(*, runtime: config.Config, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hydrated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = dict(row)
        saved_composite = _ensure_saved_composite_for_row(runtime=runtime, row=payload)
        if saved_composite is not None and saved_composite.exists():
            payload["saved_composited_path"] = _to_project_relative(saved_composite)
            payload["composited_path"] = _to_project_relative(saved_composite)
        image_path_raw = str(payload.get("image_path", "")).strip()
        if image_path_raw:
            image_path = PROJECT_ROOT / image_path_raw
            candidate = _resolve_composited_candidate(image_path, runtime=runtime)
            if candidate and candidate.exists():
                if saved_composite is None or not saved_composite.exists():
                    payload["composited_path"] = _to_project_relative(candidate)
                pdf_candidate = _resolve_composited_companion(candidate, ".pdf")
                if pdf_candidate and pdf_candidate.exists():
                    payload["composited_pdf_path"] = _to_project_relative(pdf_candidate)
                ai_candidate = _resolve_composited_companion(candidate, ".ai")
                if ai_candidate and ai_candidate.exists():
                    payload["composited_ai_path"] = _to_project_relative(ai_candidate)
            else:
                existing_composite = _project_path_if_exists(payload.get("composited_path"))
                if existing_composite is not None:
                    if saved_composite is None or not saved_composite.exists():
                        payload["composited_path"] = _to_project_relative(existing_composite)
                    pdf_candidate = _resolve_composited_companion(existing_composite, ".pdf")
                    if pdf_candidate and pdf_candidate.exists():
                        payload["composited_pdf_path"] = _to_project_relative(pdf_candidate)
                    ai_candidate = _resolve_composited_companion(existing_composite, ".ai")
                    if ai_candidate and ai_candidate.exists():
                        payload["composited_ai_path"] = _to_project_relative(ai_candidate)
        hydrated.append(payload)
    return hydrated


def _current_run_generated_paths(*, runtime: config.Config, rows: list[dict[str, Any]]) -> set[Path]:
    keep: set[Path] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        token = str(row.get("image_path", "") or "").strip()
        if not token:
            continue
        candidate = _project_path_if_exists(token)
        if candidate is not None and candidate.exists():
            keep.add(candidate.resolve())
    return keep


def _prune_stale_generated_variants_for_book(*, runtime: config.Config, book_number: int, keep_paths: set[Path]) -> None:
    root = runtime.tmp_dir / "generated" / str(book_number)
    if not root.exists() or not root.is_dir():
        return
    image_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    keep = {path.resolve() for path in keep_paths}
    removed = 0
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in image_suffixes:
            continue
        try:
            resolved = file_path.resolve()
        except Exception:
            resolved = file_path
        if resolved in keep:
            continue
        try:
            file_path.unlink()
            removed += 1
        except Exception:
            continue
    if removed > 0:
        for directory in sorted([path for path in root.rglob("*") if path.is_dir()], key=lambda p: len(p.parts), reverse=True):
            try:
                next(directory.iterdir())
            except StopIteration:
                try:
                    directory.rmdir()
                except Exception:
                    continue
        logger.info(
            "Pruned stale generated variants before compositing",
            extra={"book_number": int(book_number), "removed_files": int(removed)},
        )


class JobStageError(RuntimeError):
    """Stage-scoped execution error for retry-aware async jobs."""

    def __init__(
        self,
        *,
        stage: str,
        message: str,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.stage = str(stage or "execute")
        self.retryable = bool(retryable)
        self.details = details if isinstance(details, dict) else {}


def _checkpoint_catalog_token(catalog_id: str) -> str:
    token = "".join(ch if (ch.isalnum() or ch in {"-", "_"}) else "_" for ch in str(catalog_id).strip().lower())
    token = token.strip("_-")
    return token or config.DEFAULT_CATALOG_ID


def _job_checkpoint_path(*, runtime: config.Config, job_id: str) -> Path:
    return runtime.data_dir / "job_checkpoints" / _checkpoint_catalog_token(runtime.catalog_id) / f"{job_id}.json"


def _default_job_checkpoint(*, runtime: config.Config, job_id: str, book: int, dry_run: bool) -> dict[str, Any]:
    return {
        "catalog": runtime.catalog_id,
        "job_id": str(job_id),
        "book": int(book),
        "dry_run": bool(dry_run),
        "results": [],
        "stages": {
            "generate": {"status": "pending"},
            "composite": {"status": "pending"},
            "persist": {"status": "pending"},
            "deliver": {"status": "pending"},
            "sync": {"status": "pending"},
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_job_checkpoint(*, runtime: config.Config, job_id: str, book: int, dry_run: bool) -> dict[str, Any]:
    default_payload = _default_job_checkpoint(runtime=runtime, job_id=job_id, book=book, dry_run=dry_run)
    path = _job_checkpoint_path(runtime=runtime, job_id=job_id)
    payload = safe_json.load_json(path, default_payload)
    if not isinstance(payload, dict):
        payload = dict(default_payload)
    if str(payload.get("catalog", "")).strip() != runtime.catalog_id:
        payload = dict(default_payload)
    if _safe_int(payload.get("book"), 0) != int(book):
        payload = dict(default_payload)
    if str(payload.get("job_id", "")).strip() != str(job_id):
        payload["job_id"] = str(job_id)
    if not isinstance(payload.get("results"), list):
        payload["results"] = []
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        stages = {}
    for stage_name in ("generate", "composite", "persist", "deliver", "sync"):
        entry = stages.get(stage_name)
        if not isinstance(entry, dict):
            stages[stage_name] = {"status": "pending"}
            continue
        entry["status"] = str(entry.get("status", "pending") or "pending").strip().lower()
        if entry["status"] not in {"pending", "completed", "failed", "skipped"}:
            entry["status"] = "pending"
        stages[stage_name] = entry
    payload["stages"] = stages
    payload["dry_run"] = bool(payload.get("dry_run", dry_run))
    return payload


def _save_job_checkpoint(*, runtime: config.Config, checkpoint: dict[str, Any]) -> None:
    job_id = str(checkpoint.get("job_id", "")).strip()
    if not job_id:
        return
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    safe_json.atomic_write_json(_job_checkpoint_path(runtime=runtime, job_id=job_id), checkpoint)


def _clear_job_checkpoint(*, runtime: config.Config, job_id: str) -> None:
    if not str(job_id).strip():
        return
    path = _job_checkpoint_path(runtime=runtime, job_id=job_id)
    if path.exists():
        path.unlink(missing_ok=True)


def _cleanup_stale_checkpoints(*, runtime: config.Config, max_age_hours: int = 24) -> int:
    """Remove stale checkpoint files to avoid orphaned resume state."""
    checkpoint_root = runtime.data_dir / "job_checkpoints" / _checkpoint_catalog_token(runtime.catalog_id)
    if not checkpoint_root.exists():
        return 0
    now_ts = time.time()
    max_age_seconds = max(1, int(max_age_hours)) * 3600
    removed = 0
    for row in checkpoint_root.glob("*.json"):
        try:
            age_seconds = now_ts - float(row.stat().st_mtime)
            if age_seconds <= max_age_seconds:
                continue
            row.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def _checkpoint_stage_completed(checkpoint: dict[str, Any], stage: str) -> bool:
    stages = checkpoint.get("stages", {})
    if not isinstance(stages, dict):
        return False
    entry = stages.get(stage, {})
    if not isinstance(entry, dict):
        return False
    return str(entry.get("status", "")).strip().lower() == "completed"


def _set_checkpoint_stage(
    checkpoint: dict[str, Any],
    *,
    stage: str,
    status: str,
    error: dict[str, Any] | None = None,
) -> None:
    stages = checkpoint.get("stages")
    if not isinstance(stages, dict):
        stages = {}
        checkpoint["stages"] = stages
    entry = stages.get(stage)
    if not isinstance(entry, dict):
        entry = {}
        stages[stage] = entry
    now = datetime.now(timezone.utc).isoformat()
    entry["status"] = str(status or "pending").strip().lower() or "pending"
    entry["updated_at"] = now
    if entry["status"] == "completed":
        entry["completed_at"] = now
        entry.pop("error", None)
    elif entry["status"] in {"failed", "pending"}:
        entry["failed_at"] = now if entry["status"] == "failed" else entry.get("failed_at", "")
        if error:
            entry["error"] = error
    elif entry["status"] == "skipped":
        entry["skipped_at"] = now
        entry.pop("error", None)


def _is_retryable_stage_error(*, stage: str, exc: Exception) -> bool:
    if isinstance(exc, (image_generator.RetryableGenerationError, requests.RequestException, TimeoutError)):
        return True
    if stage == "persist":
        return isinstance(exc, (OSError, sqlite3.Error))
    if stage == "composite":
        return isinstance(exc, OSError)
    return False


def _execute_generation_payload(
    payload: dict[str, Any],
    *,
    stage_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    catalog_id = str(payload.get("catalog", config.DEFAULT_CATALOG_ID))
    runtime = config.get_config(catalog_id)

    book = _safe_int(payload.get("book"), 0)
    models = payload.get("models", [])
    variants = _safe_int(payload.get("variants"), 5)
    requested_variant = max(1, _safe_int(payload.get("variant"), 1))
    prompt = str(payload.get("prompt", ""))
    prompt_source = str(payload.get("prompt_source", payload.get("promptSource", "template")) or "template").strip().lower() or "template"
    template_id = str(payload.get("template_id", payload.get("templateId", "")) or "").strip()
    compose_prompt = bool(payload.get("compose_prompt", True))
    preserve_prompt_text = bool(payload.get("preserve_prompt_text", False))
    scene_description = str(payload.get("scene_description", "") or "").strip()
    template_ok, _template_details = _validate_template_id(runtime=runtime, template_id=template_id)
    if not template_ok:
        raise ValueError(f"Unknown template_id: {template_id}")
    provider = str(payload.get("provider", "")).strip().lower()
    library_prompt_id = str(payload.get("library_prompt_id", "")).strip()
    cover_source = str(payload.get("cover_source", "catalog")).strip().lower() or "catalog"
    if cover_source not in {"catalog", "drive"}:
        cover_source = "catalog"
    selected_cover_id = str(payload.get("selected_cover_id", "")).strip()
    selected_cover = payload.get("selected_cover")
    if not selected_cover_id and isinstance(selected_cover, dict):
        selected_cover_id = str(selected_cover.get("id", "")).strip()
    drive_folder_id = str(payload.get("drive_folder_id", "")).strip()
    input_folder_id = str(payload.get("input_folder_id", "")).strip()
    credentials_override = str(payload.get("credentials_path", "")).strip()
    forced_dry_run = bool(payload.get("dry_run", False))

    if book <= 0:
        raise ValueError("book must be a positive integer")
    max_variants = _max_generation_variants(runtime)
    if variants < 1 or variants > max_variants:
        raise ValueError(f"variants must be between 1 and {max_variants}")
    if not isinstance(models, list):
        raise ValueError("models must be a list")
    models = [str(item).strip() for item in models if str(item).strip()]
    active_models = models or runtime.all_models
    if not active_models:
        raise ValueError("No models available for generation")

    composed_prompt_payload: dict[str, Any] = {}
    book_row = _book_row_for_number(runtime=runtime, book_number=book)
    raw_request_prompt = str(prompt or "").strip()
    precomposed_prompt = _should_use_resolved_frontend_prompt(
        raw_request_prompt,
        compose_prompt=compose_prompt,
        preserve_prompt_text=preserve_prompt_text,
    )
    if compose_prompt and book_row is not None:
        default_diversified_prompt = prompt_generator.build_diversified_prompt(
            book_title=str(book_row.get("title", "")),
            book_author=str(book_row.get("author", "")),
            book_number=book,
            variant_index=requested_variant,
        )
        if prompt_source == "custom" and raw_request_prompt:
            base_prompt_for_composer = raw_request_prompt
        else:
            base_prompt_for_composer = default_diversified_prompt
        if not base_prompt_for_composer:
            default_prompt = ""
            variants_payload = book_row.get("variants", [])
            if isinstance(variants_payload, list) and variants_payload:
                matching_variant = next(
                    (
                        row
                        for row in variants_payload
                        if isinstance(row, dict)
                        and _safe_int(row.get("variant_id", row.get("variant")), 0) == requested_variant
                    ),
                    None,
                )
                variant_row = matching_variant or variants_payload[0]
                if isinstance(variant_row, dict):
                    default_prompt = str(variant_row.get("prompt", "")).strip()
            base_prompt_for_composer = (
                default_prompt
                or (
                    f"Cinematic full-bleed narrative scene for {book_row.get('title', f'Book {book}')}, "
                    "single dominant focal subject, vivid painterly color, no text, no logos, no borders or frames"
                )
            )
        composed_prompt_payload = _compose_prompt_for_book(
            runtime=runtime,
            book=book_row,
            base_prompt=str(base_prompt_for_composer),
            template_id=template_id,
            variant_index=max(0, requested_variant - 1),
            scene_override=scene_description,
        )
        if prompt_source == "template" or not raw_request_prompt:
            prompt = str(composed_prompt_payload.get("prompt", base_prompt_for_composer)).strip()

    prompt_has_generic_lead = content_relevance.is_generic_text(str(prompt or "")[:320])
    prompt_has_unresolved_placeholders = content_relevance.prompt_contains_unresolved_placeholders(prompt)
    if precomposed_prompt:
        # Respect fully resolved frontend prompts, including Alexandria library prompts,
        # unless they still contain placeholders or generic fallback text.
        needs_backend_scene_anchor = prompt_has_generic_lead or prompt_has_unresolved_placeholders
    else:
        needs_backend_scene_anchor = (
            prompt_source != "custom"
            or not raw_request_prompt
            or prompt_has_generic_lead
            or prompt_has_unresolved_placeholders
        )
    if book_row is not None and (not precomposed_prompt or needs_backend_scene_anchor):
        prompt = _ensure_prompt_book_context(
            prompt=prompt,
            book=book_row,
            require_motif=needs_backend_scene_anchor,
            variant_index=max(0, requested_variant - 1),
            scene_override=scene_description,
        )
    if book_row is not None:
        if precomposed_prompt:
            prompt = " ".join(str(prompt or "").split()).strip()
        else:
            prompt = _sanitize_prompt_placeholders(
                prompt,
                book_row,
                variant_index=max(0, requested_variant - 1),
                scene_override=scene_description,
            )
            prompt = _ensure_enriched_prompt(
                prompt,
                book_row,
                variant_index=max(0, requested_variant - 1),
                scene_override=scene_description,
            )
    if book_row is not None:
        prompt_excerpt = prompt[:200].rstrip()
        if len(prompt) > 200:
            prompt_excerpt = f"{prompt_excerpt}..."
        logger.info(
            "Generation prompt for book %s variant %s (%s, prompt_processing=%s): %s",
            book,
            requested_variant,
            prompt_source,
            "frontend_resolved" if precomposed_prompt else "backend_enriched",
            prompt_excerpt,
        )
        _validate_prompt_before_generation(prompt, book_row)

    dry_run = forced_dry_run or (not runtime.has_any_api_key())
    job_id = str(payload.get("job_id", "")).strip()
    provider_override = provider if provider and provider != "all" else None

    def _emit_stage(stage: str, message: str, progress: float = 0.0) -> None:
        if stage_callback is None:
            return
        try:
            stage_callback(
                {
                    "stage": str(stage or "").strip() or "running",
                    "message": str(message or "").strip() or "Working...",
                    "progress": max(0.0, min(1.0, float(progress))),
                }
            )
        except Exception:
            return

    _cleanup_stale_checkpoints(runtime=runtime)

    checkpoint = (
        _load_job_checkpoint(runtime=runtime, job_id=job_id, book=book, dry_run=dry_run)
        if job_id
        else {}
    )
    resumed_from_checkpoint = bool(
        checkpoint
        and any(_checkpoint_stage_completed(checkpoint, stage) for stage in ("generate", "composite", "persist"))
    )

    serialized: list[dict[str, Any]] = []
    if checkpoint and _checkpoint_stage_completed(checkpoint, "generate"):
        cached_rows = checkpoint.get("results", [])
        serialized = [row for row in cached_rows if isinstance(row, dict)] if isinstance(cached_rows, list) else []
    else:
        def _cancel_checker(model_name: str, _variant: int) -> bool:
            if not job_id:
                return False
            return _is_job_model_cancelled(job_id=job_id, catalog_id=runtime.catalog_id, model=str(model_name))

        try:
            results = image_generator.generate_single_book(
                book_number=book,
                prompts_path=runtime.prompts_path,
                output_dir=runtime.tmp_dir / "generated",
                models=active_models,
                variants=variants,
                prompt_variant=requested_variant,
                prompt_text=prompt,
                library_prompt_id=library_prompt_id or None,
                provider_override=provider_override,
                resume=False,
                dry_run=dry_run,
                cancel_checker=_cancel_checker if job_id else None,
                preserve_prompt_text=preserve_prompt_text,
            )
            _apply_style_edge_trim(results=results)
            serialized = _serialize_generation_results(runtime=runtime, book=book, results=results, job_id=job_id)
            if library_prompt_id:
                for row in serialized:
                    if isinstance(row, dict):
                        row["library_prompt_id"] = library_prompt_id
            if not dry_run:
                successful_rows = [row for row in serialized if isinstance(row, dict) and bool(row.get("success"))]
                if not successful_rows:
                    summarized_failures = _summarize_generation_failures(serialized)
                    failure_details: list[str] = []
                    for row in summarized_failures:
                        model = str(row.get("model", "unknown"))
                        variant = _safe_int(row.get("variant"), 0)
                        error_text = str(row.get("error", "") or "unknown error").strip()
                        failure_details.append(f"{model} v{variant}: {error_text}")
                    detail_blob = "; ".join(failure_details[:4])
                    if len(failure_details) > 4:
                        detail_blob += f"; +{len(failure_details) - 4} more"
                    message = "All generation attempts failed; no successful variants."
                    if detail_blob:
                        message = f"{message} {detail_blob}"
                    raise JobStageError(
                        stage="generate",
                        message=message,
                        retryable=False,
                        details={"failures": summarized_failures},
                    )
        except Exception as exc:
            if checkpoint:
                _set_checkpoint_stage(
                    checkpoint,
                    stage="generate",
                    status="failed",
                    error={
                        "message": str(exc),
                        "type": exc.__class__.__name__,
                        "stage": "generate",
                        **({"details": exc.details} if isinstance(exc, JobStageError) and exc.details else {}),
                    },
                )
                _save_job_checkpoint(runtime=runtime, checkpoint=checkpoint)
            raise JobStageError(
                stage="generate",
                message=str(exc),
                retryable=_is_retryable_stage_error(stage="generate", exc=exc),
                details=exc.details if isinstance(exc, JobStageError) else None,
            ) from exc
        if checkpoint:
            checkpoint["results"] = serialized
            _set_checkpoint_stage(checkpoint, stage="generate", status="completed")
            _save_job_checkpoint(runtime=runtime, checkpoint=checkpoint)

    if not dry_run and not (checkpoint and _checkpoint_stage_completed(checkpoint, "composite")):
        regions = _load_json(config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir), {})
        try:
            keep_paths = _current_run_generated_paths(runtime=runtime, rows=serialized)
            _prune_stale_generated_variants_for_book(runtime=runtime, book_number=book, keep_paths=keep_paths)
            if cover_source == "drive":
                _emit_stage("download", "Downloading cover from Google Drive...", 0.03)
                effective_drive_folder_id = (
                    drive_folder_id
                    or runtime.gdrive_source_folder_id
                    or runtime.gdrive_input_folder_id
                    or runtime.gdrive_output_folder_id
                )
                effective_input_folder_id = (
                    input_folder_id
                    or runtime.gdrive_source_folder_id
                    or runtime.gdrive_input_folder_id
                )
                if not effective_drive_folder_id:
                    raise RuntimeError("Google Drive source folder is not configured.")
                credentials_path = Path(credentials_override) if credentials_override else _resolve_credentials_path(runtime)
                if not credentials_path.is_absolute():
                    credentials_path = PROJECT_ROOT / credentials_path
                ensure_result = drive_manager.ensure_local_input_cover(
                    drive_folder_id=effective_drive_folder_id,
                    input_folder_id=effective_input_folder_id,
                    credentials_path=credentials_path,
                    catalog_path=runtime.book_catalog_path,
                    input_root=runtime.input_dir,
                    book_number=book,
                    selected_cover_id=selected_cover_id,
                )
                if not bool(ensure_result.get("ok")):
                    raise RuntimeError(str(ensure_result.get("error") or "Failed to load input cover from Google Drive."))
                downloaded_now = bool(ensure_result.get("downloaded", False))
                source_label = str(ensure_result.get("source", "") or "google_drive")
                _emit_stage(
                    "download",
                    (
                        "Downloaded cover from Google Drive."
                        if downloaded_now
                        else f"Using cached local cover ({source_label})."
                    ),
                    0.15,
                )
            used_pdf_mode = False
            source_pdf = pdf_compositor.find_source_pdf_for_book(
                input_dir=runtime.input_dir,
                book_number=book,
                catalog_path=runtime.book_catalog_path,
            )
            if source_pdf is not None:
                _emit_stage("composite", "Compositing generated variants via source PDF...", 0.78)
                try:
                    pdf_compositor.composite_all_variants(
                        book_number=book,
                        input_dir=runtime.input_dir,
                        generated_dir=runtime.tmp_dir / "generated",
                        output_dir=runtime.tmp_dir / "composited",
                        catalog_path=runtime.book_catalog_path,
                    )
                    used_pdf_mode = True
                except Exception as pdf_exc:
                    logger.warning(
                        "PDF compositor failed for book %s; falling back to JPG compositor: %s",
                        book,
                        pdf_exc,
                    )

            if not used_pdf_mode:
                _emit_stage("composite", "Compositing generated variants via JPG fallback...", 0.78)
                cover_compositor.composite_all_variants(
                    book_number=book,
                    input_dir=runtime.input_dir,
                    generated_dir=runtime.tmp_dir / "generated",
                    output_dir=runtime.tmp_dir / "composited",
                    regions=regions,
                    catalog_path=runtime.book_catalog_path,
                )

            for row in serialized:
                if not isinstance(row, dict):
                    continue
                row["compositor_mode"] = "pdf" if used_pdf_mode else "jpg_fallback"
            _assert_composite_validation_within_limits(runtime=runtime, book_number=book)
        except Exception as exc:
            if checkpoint:
                _set_checkpoint_stage(
                    checkpoint,
                    stage="composite",
                    status="failed",
                    error={"message": str(exc), "type": exc.__class__.__name__, "stage": "composite"},
                )
                _save_job_checkpoint(runtime=runtime, checkpoint=checkpoint)
            raise JobStageError(
                stage="composite",
                message=str(exc),
                retryable=_is_retryable_stage_error(stage="composite", exc=exc),
            ) from exc
    if not dry_run:
        serialized = _hydrate_serialized_result_paths(runtime=runtime, rows=serialized)
        _attach_print_validation_to_rows(runtime=runtime, rows=serialized)
        _trigger_visual_qa_generation_async(runtime=runtime, book_number=book)
    if job_id:
        for row in serialized:
            if not isinstance(row, dict):
                continue
            row["job_id"] = str(job_id)
    if checkpoint and not dry_run:
        checkpoint["results"] = serialized
        _set_checkpoint_stage(checkpoint, stage="composite", status="completed")
        _save_job_checkpoint(runtime=runtime, checkpoint=checkpoint)
    elif checkpoint and dry_run:
        _set_checkpoint_stage(checkpoint, stage="composite", status="skipped")
        _save_job_checkpoint(runtime=runtime, checkpoint=checkpoint)

    if not (checkpoint and _checkpoint_stage_completed(checkpoint, "persist")):
        _emit_stage("persist", "Persisting generation results...", 0.92)
        try:
            _record_generation_costs(runtime=runtime, book_number=book, rows=serialized, job_id=job_id)
            if library_prompt_id and any(isinstance(row, dict) and bool(row.get("success")) for row in serialized):
                try:
                    _record_prompt_usage(runtime=runtime, prompt_id=library_prompt_id, won=False)
                except Exception:
                    pass
            with state_lock:
                history_payload: dict[str, Any]
                try:
                    state_db_store.append_generation_records(
                        catalog_id=runtime.catalog_id,
                        records=serialized,
                        job_id=job_id,
                    )
                    history_payload = state_db_store.export_history_payload(catalog_id=runtime.catalog_id, limit=5000)
                except Exception as exc:  # pragma: no cover - state DB is best effort, never block generation
                    logger.warning("State DB append failed; falling back to JSON history append: %s", exc)
                    history_payload = _build_generation_history_payload(_history_path_for_runtime(runtime), serialized)
                review_payload = _build_review_data_payload(runtime.output_dir, runtime=runtime)
                safe_json.atomic_write_many_json(
                    [
                        (_history_path_for_runtime(runtime), history_payload),
                        (_review_data_path_for_runtime(runtime), review_payload),
                    ]
                )
            _invalidate_cache(
                "/api/review-data",
                "/api/dashboard-data",
                "/api/analytics/",
                "/api/history",
                "/api/generation-history",
                "/api/similarity-",
                "/api/weak-books",
                catalog_id=runtime.catalog_id,
            )
        except Exception as exc:
            if checkpoint:
                _set_checkpoint_stage(
                    checkpoint,
                    stage="persist",
                    status="failed",
                    error={"message": str(exc), "type": exc.__class__.__name__, "stage": "persist"},
                )
                _save_job_checkpoint(runtime=runtime, checkpoint=checkpoint)
            raise JobStageError(
                stage="persist",
                message=str(exc),
                retryable=_is_retryable_stage_error(stage="persist", exc=exc),
            ) from exc
        if checkpoint:
            _set_checkpoint_stage(checkpoint, stage="persist", status="completed")
            for trailing_stage in ("deliver", "sync"):
                _set_checkpoint_stage(checkpoint, stage=trailing_stage, status="skipped")
            _save_job_checkpoint(runtime=runtime, checkpoint=checkpoint)

    stage_snapshot: dict[str, Any] = {}
    if checkpoint:
        raw_stages = checkpoint.get("stages", {})
        if isinstance(raw_stages, dict):
            stage_snapshot = json.loads(json.dumps(raw_stages))
        _clear_job_checkpoint(runtime=runtime, job_id=job_id)

    message = "Dry-run generation plan created (no API keys configured)." if dry_run else "Generation complete."
    if job_id:
        _clear_job_model_cancellations(job_id=job_id, catalog_id=runtime.catalog_id)
    return {
        "catalog": runtime.catalog_id,
        "book": book,
        "message": message,
        "results": serialized,
        "dry_run": dry_run,
        "resume_used": resumed_from_checkpoint,
        "stages": stage_snapshot,
        "prompt_source": prompt_source,
        "template_id": template_id or None,
        "composed_prompt": str(composed_prompt_payload.get("prompt", "")).strip() or None,
        "inferred_genre": str(composed_prompt_payload.get("genre", "")).strip() or None,
    }


def _winner_path_for_runtime(runtime: config.Config) -> Path:
    return config.winner_selections_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _review_data_path_for_runtime(runtime: config.Config) -> Path:
    return config.review_data_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _iterate_data_path_for_runtime(runtime: config.Config) -> Path:
    return config.iterate_data_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _iterate_books_data_path_for_runtime(runtime: config.Config) -> Path:
    iterate_path = _iterate_data_path_for_runtime(runtime)
    return iterate_path.with_name(f"{iterate_path.stem}.books{iterate_path.suffix}")


def _compare_data_path_for_runtime(runtime: config.Config) -> Path:
    return config.compare_data_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _selection_path_for_runtime(runtime: config.Config) -> Path:
    return config.variant_selections_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _review_stats_path_for_runtime(runtime: config.Config) -> Path:
    return config.review_stats_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _review_sessions_dir_for_runtime(runtime: config.Config) -> Path:
    token = str(runtime.catalog_id or config.DEFAULT_CATALOG_ID).strip().lower()
    if token == "classics":
        return REVIEW_SESSIONS_DIR
    return REVIEW_SESSIONS_DIR / token


def _similarity_hashes_path_for_runtime(runtime: config.Config) -> Path:
    return config.similarity_hashes_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _similarity_matrix_path_for_runtime(runtime: config.Config) -> Path:
    return config.similarity_matrix_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _similarity_clusters_path_for_runtime(runtime: config.Config) -> Path:
    return config.similarity_clusters_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _similarity_dismissed_path_for_runtime(runtime: config.Config) -> Path:
    return config.similarity_dismissed_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _history_path_for_runtime(runtime: config.Config) -> Path:
    return config.generation_history_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _quality_scores_path_for_runtime(runtime: config.Config) -> Path:
    return config.quality_scores_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _composite_validation_report_path(runtime: config.Config, book_number: int) -> Path:
    return runtime.tmp_dir / "composited" / str(int(book_number)) / "composite_validation.json"


def _rebuild_composite_validation_report(*, runtime: config.Config, book_number: int) -> dict[str, Any]:
    report_path = _composite_validation_report_path(runtime, book_number)
    book_dir = report_path.parent
    output_paths = sorted(path for path in book_dir.rglob("variant_*.jpg") if path.is_file())
    if not output_paths:
        return {}

    cover_path = cover_compositor._find_cover_jpg(  # type: ignore[attr-defined]
        runtime.input_dir,
        int(book_number),
        catalog_path=runtime.book_catalog_path,
    )
    regions = _load_json(config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir), {})
    region = cover_compositor._region_from_dict(  # type: ignore[attr-defined]
        cover_compositor._region_for_book(regions, int(book_number))  # type: ignore[attr-defined]
    )

    with Image.open(cover_path) as cover_image:
        cover_rgb = cover_image.convert("RGB")
        items: list[dict[str, Any]] = []
        for output_path in output_paths:
            with Image.open(output_path) as composited_image:
                validation = cover_compositor.validate_composite_output(
                    cover=cover_rgb,
                    composited=composited_image.convert("RGB"),
                    region=region,
                    output_path=output_path,
                )
            items.append(
                {
                    **validation.to_dict(),
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    report = {
        "book_number": int(book_number),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(items),
        "invalid": sum(1 for row in items if not bool(row.get("valid", False))),
        "items": items,
    }
    safe_json.atomic_write_json(report_path, report)
    return report


def _visual_qa_dir_for_runtime(runtime: config.Config) -> Path:
    return runtime.tmp_dir / "visual-qa"


def _visual_qa_index_path_for_runtime(runtime: config.Config) -> Path:
    return _visual_qa_dir_for_runtime(runtime) / "index.json"


def _qa_output_dir_for_runtime(runtime: config.Config) -> Path:
    return runtime.project_root / "qa_output" / runtime.catalog_id


def _qa_report_path_for_runtime(runtime: config.Config) -> Path:
    return _qa_output_dir_for_runtime(runtime) / "qa_report.json"


def _visual_qa_module():
    return importlib.import_module("scripts.generate_comparison")


def _visual_structural_qa_module():
    return importlib.import_module("scripts.visual_qa")


def _merge_visual_qa_payload(
    *,
    existing: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    existing_rows = [row for row in existing.get("comparisons", []) if isinstance(row, dict)]
    update_rows = [row for row in update.get("comparisons", []) if isinstance(row, dict)]
    existing_missing = [row for row in existing.get("missing", []) if isinstance(row, dict)]
    update_missing = [row for row in update.get("missing", []) if isinstance(row, dict)]

    touched_books = {
        _safe_int(row.get("book_number"), 0)
        for row in update_rows + update_missing
        if isinstance(row, dict) and _safe_int(row.get("book_number"), 0) > 0
    }

    merged_rows = [row for row in existing_rows if _safe_int(row.get("book_number"), 0) not in touched_books]
    merged_rows.extend(update_rows)
    merged_rows = _sort_visual_qa_rows(merged_rows)

    merged_missing = [row for row in existing_missing if _safe_int(row.get("book_number"), 0) not in touched_books]
    merged_missing.extend(update_missing)
    merged_missing.sort(key=lambda row: _safe_int(row.get("book_number"), 0))

    existing_summary = existing.get("summary", {}) if isinstance(existing.get("summary"), dict) else {}
    update_summary = update.get("summary", {}) if isinstance(update.get("summary"), dict) else {}
    total = max(
        _safe_int(existing_summary.get("total"), 0),
        _safe_int(update_summary.get("total"), 0),
        len(merged_rows) + len(merged_missing),
    )
    passed = sum(1 for row in merged_rows if str(row.get("verdict", "")).upper() == "PASS")
    failed = sum(1 for row in merged_rows if str(row.get("verdict", "")).upper() == "FAIL")
    not_compared = max(_safe_int(update_summary.get("not_compared"), 0), total - len(merged_rows), len(merged_missing))

    return {
        "generated_at": str(update.get("generated_at", datetime.now(timezone.utc).isoformat())),
        "comparisons": merged_rows,
        "missing": merged_missing,
        "summary": {
            "total": total,
            "generated": len(merged_rows),
            "passed": passed,
            "failed": failed,
            "not_compared": not_compared,
        },
    }


def _merge_structural_qa_payload(
    *,
    existing: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    existing_rows = [row for row in existing.get("results", []) if isinstance(row, dict)]
    update_rows = [row for row in update.get("results", []) if isinstance(row, dict)]
    existing_missing = [row for row in existing.get("missing", []) if isinstance(row, dict)]
    update_missing = [row for row in update.get("missing", []) if isinstance(row, dict)]

    touched_books = {
        _safe_int(row.get("book_number"), 0)
        for row in update_rows + update_missing
        if isinstance(row, dict) and _safe_int(row.get("book_number"), 0) > 0
    }

    merged_rows = [row for row in existing_rows if _safe_int(row.get("book_number"), 0) not in touched_books]
    merged_rows.extend(update_rows)
    merged_rows.sort(
        key=lambda row: (
            0 if not bool(row.get("passed")) else 1,
            -_safe_float((row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else {}).get("frame_changed_pct"), 0.0),
            _safe_int(row.get("book_number"), 0),
        )
    )

    merged_missing = [row for row in existing_missing if _safe_int(row.get("book_number"), 0) not in touched_books]
    merged_missing.extend(update_missing)
    merged_missing.sort(key=lambda row: _safe_int(row.get("book_number"), 0))

    existing_summary = existing.get("summary", {}) if isinstance(existing.get("summary"), dict) else {}
    update_summary = update.get("summary", {}) if isinstance(update.get("summary"), dict) else {}
    total = max(
        _safe_int(existing_summary.get("total"), 0),
        _safe_int(update_summary.get("total"), 0),
        len(merged_rows) + len(merged_missing),
    )
    passed = sum(1 for row in merged_rows if bool(row.get("passed")))
    failed = sum(1 for row in merged_rows if not bool(row.get("passed")))
    not_compared = max(_safe_int(update_summary.get("not_compared"), 0), total - len(merged_rows), len(merged_missing))

    return {
        "generated_at": str(update.get("generated_at", datetime.now(timezone.utc).isoformat())),
        "results": merged_rows,
        "missing": merged_missing,
        "summary": {
            "total": total,
            "verified": len(merged_rows),
            "passed": passed,
            "failed": failed,
            "not_compared": not_compared,
        },
    }


def _generate_structural_visual_qa(*, runtime: config.Config, book_number: int | None = None) -> dict[str, Any]:
    module = _visual_structural_qa_module()
    catalog_payload = _load_json(runtime.book_catalog_path, [])
    catalog_rows = catalog_payload if isinstance(catalog_payload, list) else []
    selected_books = [int(book_number)] if book_number is not None and int(book_number) > 0 else None
    result = module.run_batch_verification(  # type: ignore[attr-defined]
        input_covers_dir=runtime.input_dir,
        composited_dir=runtime.tmp_dir / "composited",
        output_dir=_qa_output_dir_for_runtime(runtime),
        golden_dir=_qa_output_dir_for_runtime(runtime) / "golden",
        catalog=catalog_rows,
        book_numbers=selected_books,
    )
    if not isinstance(result, dict):
        return {}
    if selected_books:
        existing = _load_json(_qa_report_path_for_runtime(runtime), {})
        if isinstance(existing, dict) and isinstance(existing.get("results"), list):
            result = _merge_structural_qa_payload(existing=existing, update=result)
            safe_json.atomic_write_json(_qa_report_path_for_runtime(runtime), result)
    return result


def _generate_visual_qa(*, runtime: config.Config, book_number: int | None = None) -> dict[str, Any]:
    module = _visual_qa_module()
    catalog_payload = _load_json(runtime.book_catalog_path, [])
    catalog_rows = catalog_payload if isinstance(catalog_payload, list) else []
    selected_books = [int(book_number)] if book_number is not None and int(book_number) > 0 else None
    result = module.generate_all_comparisons(  # type: ignore[attr-defined]
        input_covers_dir=runtime.input_dir,
        composited_dir=runtime.tmp_dir / "composited",
        output_dir=_visual_qa_dir_for_runtime(runtime),
        catalog=catalog_rows,
        book_numbers=selected_books,
    )
    if isinstance(result, dict) and selected_books:
        existing = _load_json(_visual_qa_index_path_for_runtime(runtime), {})
        if isinstance(existing, dict) and isinstance(existing.get("comparisons"), list):
            result = _merge_visual_qa_payload(existing=existing, update=result)
            safe_json.atomic_write_json(_visual_qa_index_path_for_runtime(runtime), result)
    try:
        structural = _generate_structural_visual_qa(runtime=runtime, book_number=book_number)
    except Exception as exc:  # pragma: no cover - diagnostics should not block generation
        logger.warning("Structural visual QA generation failed for book %s: %s", book_number, exc)
        structural = {}
    if isinstance(result, dict):
        result["structural_qa"] = structural if isinstance(structural, dict) else {}
        return result
    return result if isinstance(result, dict) else {}


def _sort_visual_qa_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [row for row in rows if isinstance(row, dict)]
    out.sort(
        key=lambda row: (
            0 if str(row.get("verdict", "")).upper() == "FAIL" else 1,
            -_safe_float(row.get("frame_changed_pct"), 0.0),
            -_safe_float(row.get("frame_mean_delta"), 0.0),
            _safe_int(row.get("book_number"), 0),
        )
    )
    return out


def _load_visual_qa_payload(
    *,
    runtime: config.Config,
    force_generate: bool = False,
    book_number: int | None = None,
) -> dict[str, Any]:
    index_path = _visual_qa_index_path_for_runtime(runtime)
    payload = _load_json(index_path, {})
    comparisons = payload.get("comparisons", []) if isinstance(payload, dict) else []
    if force_generate:
        payload = _generate_visual_qa(runtime=runtime, book_number=book_number if book_number and book_number > 0 else None)
        comparisons = payload.get("comparisons", []) if isinstance(payload, dict) else []

    rows = _sort_visual_qa_rows(comparisons if isinstance(comparisons, list) else [])
    structural_payload = payload.get("structural_qa", {}) if isinstance(payload, dict) and isinstance(payload.get("structural_qa"), dict) else {}
    if not structural_payload:
        structural_payload = _load_json(_qa_report_path_for_runtime(runtime), {})
        if force_generate and isinstance(structural_payload, dict):
            try:
                structural_payload = _generate_structural_visual_qa(runtime=runtime, book_number=book_number if book_number and book_number > 0 else None)
            except Exception as exc:  # pragma: no cover - diagnostics path
                logger.warning("Structural visual QA refresh failed: %s", exc)
    structural_rows = structural_payload.get("results", []) if isinstance(structural_payload, dict) else []
    structural_by_book: dict[int, dict[str, Any]] = {}
    if isinstance(structural_rows, list):
        for item in structural_rows:
            if not isinstance(item, dict):
                continue
            book_key = _safe_int(item.get("book_number"), 0)
            if book_key > 0:
                structural_by_book[book_key] = item

    normalized: list[dict[str, Any]] = []
    for row in rows:
        number = _safe_int(row.get("book_number"), 0)
        if number <= 0:
            continue
        if book_number is not None and int(book_number) > 0 and number != int(book_number):
            continue
        path_token = str(row.get("comparison_path", "")).strip()
        comparison_file = _project_path_if_exists(path_token)
        if comparison_file is None:
            abs_token = str(row.get("comparison_abs_path", "")).strip()
            if abs_token:
                abs_path = Path(abs_token)
                if abs_path.exists():
                    comparison_file = abs_path
                    path_token = _to_project_relative(abs_path)
        if comparison_file is None:
            fallback = _visual_qa_dir_for_runtime(runtime) / f"compare_{number:03d}.jpg"
            if fallback.exists():
                comparison_file = fallback
                path_token = _to_project_relative(fallback)
        structural_row = structural_by_book.get(number, {})
        structural_checks = structural_row.get("checks", []) if isinstance(structural_row, dict) else []
        if not isinstance(structural_checks, list):
            structural_checks = []
        failed_checks = structural_row.get("failed_checks", []) if isinstance(structural_row, dict) else []
        if not isinstance(failed_checks, list):
            failed_checks = []
        structural_report_path = ""
        if isinstance(structural_row, dict):
            token = str(structural_row.get("report_path", "")).strip()
            if token:
                structural_report_path = token
            else:
                fallback_report = _qa_output_dir_for_runtime(runtime) / f"qa_{number:03d}.json"
                if fallback_report.exists():
                    structural_report_path = _to_project_relative(fallback_report)

        normalized.append(
            {
                **row,
                "book_number": number,
                "book_title": str(row.get("book_title", f"Book {number}")),
                "comparison_path": path_token,
                "frame_changed_pct": _safe_float(row.get("frame_changed_pct"), 0.0),
                "frame_mean_delta": _safe_float(row.get("frame_mean_delta"), 0.0),
                "frame_max_delta": _safe_float(row.get("frame_max_delta"), 0.0),
                "verdict": str(row.get("verdict", "UNKNOWN")).upper() or "UNKNOWN",
                "image_url": f"/api/visual-qa/image/{number}",
                "comparison_url": f"/{path_token}" if path_token else "",
                "has_image": comparison_file is not None and comparison_file.exists(),
                "structural_passed": bool(structural_row.get("passed")) if isinstance(structural_row, dict) else None,
                "structural_failed_checks": [str(item) for item in failed_checks if str(item).strip()],
                "structural_checks": structural_checks,
                "structural_report_path": structural_report_path,
            }
        )

    summary_raw = payload.get("summary", {}) if isinstance(payload, dict) else {}
    structural_summary_raw = structural_payload.get("summary", {}) if isinstance(structural_payload, dict) else {}
    summary = {
        "total": len(normalized) if book_number else _safe_int(summary_raw.get("total"), len(normalized)),
        "passed": _safe_int(summary_raw.get("passed"), sum(1 for row in normalized if row.get("verdict") == "PASS")),
        "failed": _safe_int(summary_raw.get("failed"), sum(1 for row in normalized if row.get("verdict") == "FAIL")),
        "not_compared": 0 if book_number else _safe_int(summary_raw.get("not_compared"), max(0, _safe_int(summary_raw.get("total"), len(normalized)) - len(normalized))),
        "generated": _safe_int(summary_raw.get("generated"), len(normalized)),
        "structural_verified": _safe_int(structural_summary_raw.get("verified"), 0),
        "structural_passed": _safe_int(structural_summary_raw.get("passed"), 0),
        "structural_failed": _safe_int(structural_summary_raw.get("failed"), 0),
    }
    missing = payload.get("missing", []) if isinstance(payload, dict) and isinstance(payload.get("missing"), list) else []
    if book_number is not None and int(book_number) > 0:
        missing = [row for row in missing if isinstance(row, dict) and _safe_int(row.get("book_number"), 0) == int(book_number)]
    message = ""
    if book_number and not normalized:
        message = "No generated images available for this book. Generate covers first."
    elif not normalized:
        message = "No generated images available yet. Generate covers first, then run Visual QA."
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "generated_at": str((payload if isinstance(payload, dict) else {}).get("generated_at", datetime.now(timezone.utc).isoformat())),
        "comparisons": normalized,
        "summary": summary,
        "missing": missing,
        "structural_qa": structural_payload if isinstance(structural_payload, dict) else {},
        "message": message,
    }


def _visual_qa_image_path(*, runtime: config.Config, book_number: int) -> Path | None:
    if int(book_number) <= 0:
        return None
    payload = _load_json(_visual_qa_index_path_for_runtime(runtime), {})
    rows = payload.get("comparisons", []) if isinstance(payload, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _safe_int(row.get("book_number"), 0) != int(book_number):
                continue
            candidate = _project_path_if_exists(row.get("comparison_path"))
            if candidate is not None and candidate.exists():
                return candidate
    fallback = _visual_qa_dir_for_runtime(runtime) / f"compare_{int(book_number):03d}.jpg"
    if fallback.exists():
        return fallback
    return None


def _trigger_visual_qa_generation_async(*, runtime: config.Config, book_number: int) -> None:
    if int(book_number) <= 0:
        return
    token = f"{runtime.catalog_id}:{int(book_number)}"
    with _VISUAL_QA_RUNNING_LOCK:
        if token in _VISUAL_QA_RUNNING:
            return
        _VISUAL_QA_RUNNING.add(token)

    def _run() -> None:
        try:
            _generate_visual_qa(runtime=runtime, book_number=int(book_number))
            _invalidate_cache("/api/visual-qa", catalog_id=runtime.catalog_id)
        except Exception as exc:  # pragma: no cover - non-blocking diagnostic path
            logger.warning("Visual QA generation failed for book %s: %s", book_number, exc)
        finally:
            with _VISUAL_QA_RUNNING_LOCK:
                _VISUAL_QA_RUNNING.discard(token)

    threading.Thread(target=_run, name=f"visual-qa-{runtime.catalog_id}-{int(book_number)}", daemon=True).start()


def _assert_composite_validation_within_limits(*, runtime: config.Config, book_number: int) -> None:
    report_path = _composite_validation_report_path(runtime, book_number)
    report = _load_json(report_path, {})
    if not isinstance(report, dict):
        return
    total = _safe_int(report.get("total"), 0)
    invalid = _safe_int(report.get("invalid"), 0)
    if total <= 0:
        return
    max_invalid = max(0, _safe_int(getattr(runtime, "composite_max_invalid_variants", 0), 0))
    if invalid > max_invalid:
        try:
            rebuilt = _rebuild_composite_validation_report(runtime=runtime, book_number=book_number)
        except Exception as exc:
            logger.warning(
                "Composite validation recheck failed for book %s; using existing report: %s",
                book_number,
                exc,
            )
            rebuilt = {}
        if isinstance(rebuilt, dict) and rebuilt:
            report = rebuilt
            total = _safe_int(report.get("total"), 0)
            invalid = _safe_int(report.get("invalid"), 0)
        if invalid <= max_invalid:
            logger.info("Composite validation recheck passed for book %s", book_number)
            return
        items = report.get("items", [])
        blocking_invalid = 0
        evaluated_invalid_rows = 0
        if isinstance(items, list):
            for row in items:
                if not isinstance(row, dict):
                    continue
                if bool(row.get("valid", False)):
                    continue
                evaluated_invalid_rows += 1
                issues = [str(issue).strip() for issue in row.get("issues", []) if str(issue).strip()]
                non_soft = [issue for issue in issues if issue != "edge_artifact_risk"]
                if non_soft:
                    blocking_invalid += 1
        if evaluated_invalid_rows > 0 and blocking_invalid <= max_invalid:
            logger.warning(
                "Composite validation soft-failed for book %s; allowing run to continue",
                book_number,
                extra={"invalid": int(invalid), "blocking_invalid": int(blocking_invalid), "total": int(total)},
            )
            return
        raise ValueError(
            f"Composite validation failed for book {book_number}: "
            f"invalid variants {invalid}/{total} exceeds allowed {max_invalid}"
        )


def _regeneration_results_path_for_runtime(runtime: config.Config) -> Path:
    return config.regeneration_results_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _prompt_performance_path_for_runtime(runtime: config.Config) -> Path:
    return config.prompt_performance_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _llm_usage_path_for_runtime(runtime: config.Config) -> Path:
    return config.llm_usage_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _cost_ledger_path_for_runtime(runtime: config.Config) -> Path:
    return config.cost_ledger_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _budget_config_path_for_runtime(runtime: config.Config) -> Path:
    return config.budget_config_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _delivery_config_path_for_runtime(runtime: config.Config) -> Path:
    return config.delivery_config_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _delivery_tracking_path_for_runtime(runtime: config.Config) -> Path:
    return config.delivery_tracking_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _batch_runs_path_for_runtime(runtime: config.Config) -> Path:
    return config.batch_runs_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _report_schedules_path_for_runtime(runtime: config.Config) -> Path:
    return config.report_schedules_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _slo_metrics_path_for_runtime(runtime: config.Config) -> Path:
    return config.slo_metrics_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _slo_alert_state_path_for_runtime(runtime: config.Config) -> Path:
    return config.slo_alert_state_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _catalog_id_from_winner_path(path: Path) -> str:
    name = path.name
    if name == "winner_selections.json":
        return "classics"
    prefix = "winner_selections_"
    if name.startswith(prefix) and name.endswith(".json"):
        token = name[len(prefix) : -len(".json")].strip()
        if token:
            return token
    return config.DEFAULT_CATALOG_ID


def _book_metadata_path_for_runtime(runtime: config.Config) -> Path:
    return book_metadata.metadata_path(data_dir=runtime.data_dir, catalog_id=runtime.catalog_id)


def _batch_runs_default_payload() -> dict[str, Any]:
    return {"updated_at": "", "batches": {}}


def _load_batch_runs_payload(runtime: config.Config) -> dict[str, Any]:
    path = _batch_runs_path_for_runtime(runtime)
    payload = _load_json(path, _batch_runs_default_payload())
    if not isinstance(payload, dict):
        payload = _batch_runs_default_payload()
    batches = payload.get("batches", {})
    if not isinstance(batches, dict):
        batches = {}
    payload["batches"] = batches
    return payload


def _save_batch_runs_payload(runtime: config.Config, payload: dict[str, Any]) -> None:
    path = _batch_runs_path_for_runtime(runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    next_payload = dict(payload) if isinstance(payload, dict) else _batch_runs_default_payload()
    batches = next_payload.get("batches", {})
    if not isinstance(batches, dict):
        batches = {}
    next_payload["batches"] = batches
    next_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    safe_json.atomic_write_json(path, next_payload)


def _load_batch_entry(runtime: config.Config, batch_id: str) -> dict[str, Any] | None:
    payload = _load_batch_runs_payload(runtime)
    batches = payload.get("batches", {})
    if not isinstance(batches, dict):
        return None
    row = batches.get(str(batch_id), None)
    return dict(row) if isinstance(row, dict) else None


def _upsert_batch_entry(runtime: config.Config, entry: dict[str, Any]) -> None:
    batch_id = str(entry.get("id", "")).strip()
    if not batch_id:
        raise ValueError("batch entry must include id")
    with state_lock:
        payload = _load_batch_runs_payload(runtime)
        batches = payload.get("batches", {})
        if not isinstance(batches, dict):
            batches = {}
        next_entry = dict(entry)
        next_entry["id"] = batch_id
        next_entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        batches[batch_id] = next_entry
        payload["batches"] = batches
        _save_batch_runs_payload(runtime, payload)


def _catalog_book_title_map(runtime: config.Config) -> dict[int, str]:
    payload = _load_json(runtime.book_catalog_path, [])
    out: dict[int, str] = {}
    if not isinstance(payload, list):
        return out
    for row in payload:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        title = str(row.get("title", "")).strip()
        author = str(row.get("author", "")).strip()
        label = title
        if author:
            label = f"{title} — {author}" if title else author
        out[number] = label or f"Book {number}"
    return out


def _job_result_rows(job: job_store.JobRecord | None) -> list[dict[str, Any]]:
    if job is None or not isinstance(job.result, dict):
        return []
    rows = job.result.get("results", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


class SaveRawIntegrityError(RuntimeError):
    """Raised when Save Raw cannot safely map a UI selection to immutable artifacts."""

    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = str(code or "SAVE_RAW_INTEGRITY_ERROR")
        self.details = details if isinstance(details, dict) else {}


def _job_result_cost_total(job: job_store.JobRecord | None) -> float:
    total = 0.0
    for row in _job_result_rows(job):
        total += _safe_float(row.get("cost"), 0.0)
    return round(total, 6)


def _job_result_variant_count(job: job_store.JobRecord | None) -> int:
    rows = _job_result_rows(job)
    if not rows:
        return 0
    success_rows = [row for row in rows if bool(row.get("success", False))]
    return len(success_rows) if success_rows else len(rows)


def _job_result_preview(job: job_store.JobRecord | None) -> tuple[str, str]:
    for row in _job_result_rows(job):
        rel = str(row.get("composited_path") or row.get("image_path") or "").strip()
        if not rel:
            continue
        return rel, f"/api/thumbnail?path={quote(rel, safe='')}&size=small"
    return "", ""


def _normalize_runtime_relative_asset_token(raw: Any) -> str:
    token = str(raw or "").strip()
    if not token:
        return ""
    normalized = thumbnail_server.normalize_relative_path_token(token)
    return str(normalized or "").strip()


def _job_elapsed_seconds(job: job_store.JobRecord | None) -> float:
    if job is None:
        return 0.0
    started = _safe_iso_datetime(job.started_at)
    finished = _safe_iso_datetime(job.finished_at)
    if started is None or finished is None:
        return 0.0
    delta = (finished - started).total_seconds()
    return max(0.0, float(delta))


def _count_batch_statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"queued": 0, "running": 0, "retrying": 0, "paused": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for row in rows:
        status = str(row.get("status", "queued")).strip().lower()
        if status not in counts:
            status = "queued"
        counts[status] += 1
    return counts


def _reconcile_batch_entry(
    runtime: config.Config,
    batch_id: str,
    *,
    enforce_budget: bool = True,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    entry = _load_batch_entry(runtime, batch_id)
    if not isinstance(entry, dict):
        return None, [], {}

    raw_books = entry.get("books", [])
    if not isinstance(raw_books, list):
        raw_books = []

    quality_lookup = _load_quality_lookup(_quality_scores_path_for_runtime(runtime))
    quality_by_book: dict[int, float] = {}
    for (book_number, _variant), score in quality_lookup.items():
        quality_by_book[book_number] = max(quality_by_book.get(book_number, 0.0), _safe_float(score, 0.0))

    books_out: list[dict[str, Any]] = []
    quality_scores: list[float] = []
    durations: list[float] = []
    cost_so_far = 0.0
    now_iso = datetime.now(timezone.utc).isoformat()

    for row in raw_books:
        if not isinstance(row, dict):
            continue
        book_number = _safe_int(row.get("book_number"), 0)
        title = str(row.get("title", f"Book {book_number}")).strip() or f"Book {book_number}"
        job_id = str(row.get("job_id", "")).strip()
        job = job_db_store.get_job(job_id) if job_id else None

        status = str(row.get("status", "queued")).strip().lower() or "queued"
        if job is not None:
            status = str(job.status).strip().lower() or status
        if status not in {"queued", "running", "retrying", "paused", "completed", "failed", "cancelled"}:
            status = "queued"

        result_cost = _job_result_cost_total(job)
        cost_so_far += result_cost

        quality_score = _safe_float(row.get("quality_score"), 0.0)
        if quality_score <= 0 and book_number > 0:
            quality_score = _safe_float(quality_by_book.get(book_number), 0.0)
        if status == "completed" and quality_score > 0:
            quality_scores.append(quality_score)

        elapsed = _job_elapsed_seconds(job)
        if status == "completed" and elapsed > 0:
            durations.append(elapsed)

        preview_rel, preview_thumb = _job_result_preview(job)
        variants_generated = _job_result_variant_count(job)

        error_message = str(row.get("error", "")).strip()
        if job is not None and isinstance(job.error, dict):
            error_message = str(job.error.get("message", error_message)).strip()

        books_out.append(
            {
                "book_number": book_number,
                "title": title,
                "job_id": job_id,
                "status": status,
                "attempts": int(job.attempts) if job is not None else _safe_int(row.get("attempts"), 0),
                "max_attempts": int(job.max_attempts) if job is not None else _safe_int(row.get("max_attempts"), 0),
                "cost_usd": round(result_cost, 6),
                "quality_score": round(quality_score, 4),
                "variants_generated": variants_generated,
                "preview_path": preview_rel,
                "thumbnail_url": preview_thumb,
                "error": error_message,
                "started_at": str(job.started_at if job is not None else row.get("started_at", "") or ""),
                "finished_at": str(job.finished_at if job is not None else row.get("finished_at", "") or ""),
                "updated_at": str(job.updated_at if job is not None else row.get("updated_at", now_iso) or now_iso),
            }
        )

    counts = _count_batch_statuses(books_out)
    total = len(books_out)
    terminal = int(counts.get("completed", 0)) + int(counts.get("failed", 0)) + int(counts.get("cancelled", 0))
    remaining = max(0, total - terminal)

    settings = entry.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
        entry["settings"] = settings
    budget_usd = _safe_float(settings.get("budgetUsd"), 0.0)

    budget_pause_applied = False
    if enforce_budget and budget_usd > 0 and cost_so_far >= budget_usd and remaining > 0 and not bool(entry.get("pause_requested", False)):
        paused_jobs = 0
        for row in books_out:
            if str(row.get("status", "")).lower() not in {"queued", "retrying"}:
                continue
            job_id = str(row.get("job_id", "")).strip()
            if not job_id:
                continue
            updated = job_db_store.mark_paused(job_id, reason="Batch paused at budget limit")
            if updated is None:
                continue
            row["status"] = "paused"
            row["attempts"] = int(updated.attempts)
            row["max_attempts"] = int(updated.max_attempts)
            row["updated_at"] = str(updated.updated_at or now_iso)
            paused_jobs += 1
        if paused_jobs > 0:
            budget_pause_applied = True
            entry["pause_requested"] = True
            entry["paused_reason"] = "Budget limit reached"
            entry["status"] = "paused"
            counts = _count_batch_statuses(books_out)
            terminal = int(counts.get("completed", 0)) + int(counts.get("failed", 0)) + int(counts.get("cancelled", 0))
            remaining = max(0, total - terminal)

    worker_status = _worker_runtime_status()
    worker_rows = worker_status.get("workers", {})
    if not isinstance(worker_rows, dict):
        worker_rows = {}
    workers_active = sum(1 for row in worker_rows.values() if isinstance(row, dict) and str(row.get("state", "")).lower() == "running")
    workers_configured = max(
        1,
        _safe_int(worker_status.get("worker_count"), _safe_int(getattr(runtime, "job_workers", JOB_WORKER_COUNT), JOB_WORKER_COUNT)),
    )
    if workers_active <= 0 and _safe_int(counts.get("running"), 0) > 0:
        workers_active = min(workers_configured, _safe_int(counts.get("running"), 0))

    eta_seconds: int | None = None
    if remaining <= 0:
        eta_seconds = 0
    elif durations:
        avg_duration = sum(durations) / max(1, len(durations))
        parallelism = max(1, workers_active or workers_configured)
        eta_seconds = int(round((remaining * avg_duration) / parallelism))

    cancel_requested = bool(entry.get("cancel_requested", False))
    pause_requested = bool(entry.get("pause_requested", False))
    batch_status = str(entry.get("status", "queued")).strip().lower() or "queued"
    if cancel_requested and remaining <= 0:
        batch_status = "cancelled"
    elif total > 0 and terminal >= total:
        batch_status = "completed"
    elif pause_requested and _safe_int(counts.get("running"), 0) > 0:
        batch_status = "pausing"
    elif pause_requested:
        batch_status = "paused"
    elif _safe_int(counts.get("running"), 0) > 0:
        batch_status = "running"
    elif (_safe_int(counts.get("queued"), 0) + _safe_int(counts.get("retrying"), 0)) > 0:
        batch_status = "queued"
    elif _safe_int(counts.get("paused"), 0) > 0:
        batch_status = "paused"

    if batch_status in {"completed", "cancelled"} and not str(entry.get("finished_at", "")).strip():
        entry["finished_at"] = now_iso
    elif batch_status not in {"completed", "cancelled"}:
        entry["finished_at"] = ""

    summary = {
        "total": total,
        "completed": _safe_int(counts.get("completed"), 0),
        "failed": _safe_int(counts.get("failed"), 0),
        "cancelled": _safe_int(counts.get("cancelled"), 0),
        "running": _safe_int(counts.get("running"), 0),
        "queued": _safe_int(counts.get("queued"), 0),
        "retrying": _safe_int(counts.get("retrying"), 0),
        "paused": _safe_int(counts.get("paused"), 0),
        "remaining": remaining,
        "percent_complete": round(((_safe_int(counts.get("completed"), 0) / total) * 100.0), 2) if total > 0 else 0.0,
        "cost_so_far_usd": round(cost_so_far, 6),
        "budget_usd": round(budget_usd, 6),
        "average_quality_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0.0,
        "eta_seconds": eta_seconds,
        "workers_active": workers_active,
        "workers_configured": workers_configured,
    }

    next_books: list[dict[str, Any]] = []
    for row in books_out:
        next_books.append(
            {
                "book_number": _safe_int(row.get("book_number"), 0),
                "title": str(row.get("title", "")).strip(),
                "job_id": str(row.get("job_id", "")).strip(),
                "status": str(row.get("status", "queued")).strip().lower() or "queued",
                "cost_usd": round(_safe_float(row.get("cost_usd"), 0.0), 6),
                "quality_score": round(_safe_float(row.get("quality_score"), 0.0), 4),
                "attempts": _safe_int(row.get("attempts"), 0),
                "max_attempts": _safe_int(row.get("max_attempts"), 0),
                "error": str(row.get("error", "")).strip(),
                "started_at": str(row.get("started_at", "")),
                "finished_at": str(row.get("finished_at", "")),
                "updated_at": str(row.get("updated_at", now_iso)),
            }
        )

    changed = False
    if str(entry.get("status", "")).strip().lower() != batch_status:
        changed = True
    if _safe_float(entry.get("cost_so_far_usd"), -1.0) != summary["cost_so_far_usd"]:
        changed = True
    if entry.get("books") != next_books:
        changed = True
    if entry.get("summary") != summary:
        changed = True
    if budget_pause_applied:
        changed = True

    entry["status"] = batch_status
    entry["books"] = next_books
    entry["summary"] = summary
    entry["cost_so_far_usd"] = summary["cost_so_far_usd"]
    entry["updated_at"] = now_iso

    if changed:
        _upsert_batch_entry(runtime, entry)
    if budget_pause_applied:
        job_event_broker.publish(
            "batch_paused",
            {
                "batch_id": str(entry.get("id", batch_id)),
                "catalog_id": runtime.catalog_id,
                "status": str(entry.get("status", "paused")),
                "reason": "Budget limit reached",
                "costSoFar": _safe_float(summary.get("cost_so_far_usd"), 0.0),
                "budgetUsd": _safe_float(summary.get("budget_usd"), 0.0),
            },
        )
    return entry, books_out, summary


def _batch_status_payload(
    runtime: config.Config,
    batch_id: str,
    *,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any] | None:
    entry, rows, summary = _reconcile_batch_entry(runtime, batch_id, enforce_budget=True)
    if not isinstance(entry, dict):
        return None
    page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "batchId": str(entry.get("id", "")),
        "status": str(entry.get("status", "queued")),
        "created_at": str(entry.get("created_at", "")),
        "updated_at": str(entry.get("updated_at", "")),
        "started_at": str(entry.get("started_at", "")),
        "finished_at": str(entry.get("finished_at", "")),
        "settings": entry.get("settings", {}),
        "summary": summary,
        "progress": {
            "completed": summary.get("completed", 0),
            "total": summary.get("total", 0),
            "percent": summary.get("percent_complete", 0.0),
            "failed": summary.get("failed", 0),
            "cancelled": summary.get("cancelled", 0),
            "remaining": summary.get("remaining", 0),
        },
        "cost": {
            "so_far_usd": summary.get("cost_so_far_usd", 0.0),
            "budget_usd": summary.get("budget_usd", 0.0),
            "remaining_usd": round(
                max(0.0, _safe_float(summary.get("budget_usd"), 0.0) - _safe_float(summary.get("cost_so_far_usd"), 0.0)),
                6,
            ),
            "budget_exceeded": bool(
                _safe_float(summary.get("budget_usd"), 0.0) > 0
                and _safe_float(summary.get("cost_so_far_usd"), 0.0) >= _safe_float(summary.get("budget_usd"), 0.0)
            ),
        },
        "eta_seconds": summary.get("eta_seconds"),
        "workers": {
            "active": summary.get("workers_active", 0),
            "configured": summary.get("workers_configured", 0),
        },
        "books": page,
        "count": len(page),
        "pagination": pagination,
        "review_url": f"/review?catalog={quote(runtime.catalog_id, safe='')}",
    }


def _batch_list_payload(runtime: config.Config, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    payload = _load_batch_runs_payload(runtime)
    batches = payload.get("batches", {})
    if not isinstance(batches, dict):
        batches = {}
    rows: list[dict[str, Any]] = []
    for batch_id, item in batches.items():
        if not isinstance(item, dict):
            continue
        summary = item.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        rows.append(
            {
                "batchId": str(batch_id),
                "status": str(item.get("status", "queued")),
                "created_at": str(item.get("created_at", "")),
                "updated_at": str(item.get("updated_at", "")),
                "finished_at": str(item.get("finished_at", "")),
                "books_total": _safe_int(summary.get("total"), _safe_int(item.get("books_total"), 0)),
                "books_completed": _safe_int(summary.get("completed"), 0),
                "books_failed": _safe_int(summary.get("failed"), 0),
                "books_cancelled": _safe_int(summary.get("cancelled"), 0),
                "cost_so_far_usd": round(_safe_float(summary.get("cost_so_far_usd"), _safe_float(item.get("cost_so_far_usd"), 0.0)), 6),
            }
        )
    rows.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
    page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
    return {"ok": True, "catalog": runtime.catalog_id, "batches": page, "count": len(page), "pagination": pagination}


def _apply_batch_action(runtime: config.Config, *, batch_id: str, action: str, reason: str = "") -> dict[str, Any] | None:
    action_token = str(action or "").strip().lower()
    entry = _load_batch_entry(runtime, batch_id)
    if not isinstance(entry, dict):
        return None
    now_iso = datetime.now(timezone.utc).isoformat()
    books = entry.get("books", [])
    if not isinstance(books, list):
        books = []
    touched = 0

    if action_token == "pause":
        for row in books:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id", "")).strip()
            if not job_id:
                continue
            current = job_db_store.get_job(job_id)
            if current is None:
                continue
            if current.status not in {"queued", "retrying"}:
                continue
            updated = job_db_store.mark_paused(job_id, reason=reason or "batch paused")
            if updated is not None:
                touched += 1
        entry["pause_requested"] = True
        entry["paused_reason"] = str(reason or "batch paused")
    elif action_token == "cancel":
        for row in books:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id", "")).strip()
            if not job_id:
                continue
            current = job_db_store.get_job(job_id)
            if current is None:
                continue
            if current.status not in {"queued", "retrying", "paused"}:
                continue
            updated = job_db_store.mark_cancelled(job_id, reason=reason or "batch cancelled")
            if updated is not None:
                touched += 1
        entry["cancel_requested"] = True
    elif action_token == "resume":
        for row in books:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id", "")).strip()
            if not job_id:
                continue
            current = job_db_store.get_job(job_id)
            if current is None:
                continue
            if current.status != "paused":
                continue
            updated = job_db_store.resume_job(job_id)
            if updated is not None:
                touched += 1
        entry["pause_requested"] = False
        entry["paused_reason"] = ""
    else:
        raise ValueError(f"Unsupported batch action: {action}")

    entry["updated_at"] = now_iso
    _upsert_batch_entry(runtime, entry)
    snapshot = _batch_status_payload(runtime, batch_id, limit=25, offset=0)
    if snapshot is None:
        return None
    snapshot["action"] = action_token
    snapshot["jobs_touched"] = touched
    return snapshot


def _mark_batch_completion_emitted(runtime: config.Config, *, batch_id: str) -> None:
    entry = _load_batch_entry(runtime, batch_id)
    if not isinstance(entry, dict):
        return
    if bool(entry.get("completion_event_emitted", False)):
        return
    entry["completion_event_emitted"] = True
    _upsert_batch_entry(runtime, entry)


def _batch_publish_progress_for_job(job: job_store.JobRecord) -> None:
    payload_raw = getattr(job, "payload", {})
    payload = payload_raw if isinstance(payload_raw, dict) else {}
    batch_id = str(payload.get("batch_id", "")).strip()
    if not batch_id:
        return
    runtime = config.get_config(job.catalog_id)
    entry, rows, summary = _reconcile_batch_entry(runtime, batch_id, enforce_budget=True)
    if not isinstance(entry, dict):
        return
    row = next((item for item in rows if str(item.get("job_id", "")) == str(job.id)), None)
    if isinstance(row, dict):
        event_name = "book_complete" if str(job.status) == "completed" else "book_failed"
        job_event_broker.publish(
            event_name,
            {
                "batch_id": batch_id,
                "job_id": str(job.id),
                "catalog_id": runtime.catalog_id,
                "book": _safe_int(row.get("book_number"), 0),
                "title": str(row.get("title", "")),
                "status": str(row.get("status", "")),
                "variants": _safe_int(row.get("variants_generated"), 0),
                "qualityScore": _safe_float(row.get("quality_score"), 0.0),
                "cost": _safe_float(row.get("cost_usd"), 0.0),
                "elapsed": _job_elapsed_seconds(job),
                "error": str(row.get("error", "")),
            },
        )

    job_event_broker.publish(
        "batch_progress",
        {
            "batch_id": batch_id,
            "catalog_id": runtime.catalog_id,
            "status": str(entry.get("status", "queued")),
            "completed": _safe_int(summary.get("completed"), 0),
            "failed": _safe_int(summary.get("failed"), 0),
            "cancelled": _safe_int(summary.get("cancelled"), 0),
            "total": _safe_int(summary.get("total"), 0),
            "eta_seconds": summary.get("eta_seconds"),
            "costSoFar": _safe_float(summary.get("cost_so_far_usd"), 0.0),
            "budgetUsd": _safe_float(summary.get("budget_usd"), 0.0),
            "workersActive": _safe_int(summary.get("workers_active"), 0),
            "workersConfigured": _safe_int(summary.get("workers_configured"), 0),
        },
    )

    total = _safe_int(summary.get("total"), 0)
    completed_or_terminal = (
        _safe_int(summary.get("completed"), 0)
        + _safe_int(summary.get("failed"), 0)
        + _safe_int(summary.get("cancelled"), 0)
    )
    if total > 0 and completed_or_terminal >= total and not bool(entry.get("completion_event_emitted", False)):
        _mark_batch_completion_emitted(runtime, batch_id=batch_id)
        job_event_broker.publish(
            "batch_complete",
            {
                "batch_id": batch_id,
                "catalog_id": runtime.catalog_id,
                "status": str(entry.get("status", "completed")),
                "completed": _safe_int(summary.get("completed"), 0),
                "failed": _safe_int(summary.get("failed"), 0),
                "cancelled": _safe_int(summary.get("cancelled"), 0),
                "total": total,
                "totalCost": _safe_float(summary.get("cost_so_far_usd"), 0.0),
                "averageQuality": _safe_float(summary.get("average_quality_score"), 0.0),
            },
        )


def _create_snapshot_before_operation(runtime: config.Config, *, operation: str) -> dict[str, Any]:
    mode = str(os.getenv("DISASTER_SNAPSHOT_MODE", "async")).strip().lower()
    if mode not in {"sync", "blocking"}:
        def _background_snapshot() -> None:
            try:
                disaster_recovery.create_snapshot(runtime=runtime)
            except Exception as exc:
                logger.warning(
                    "Background snapshot failed",
                    extra={"operation": operation, "catalog": runtime.catalog_id, "error": str(exc)},
                )

        thread = threading.Thread(target=_background_snapshot, name=f"snapshot-{operation}", daemon=True)
        thread.start()
        return {"ok": True, "operation": operation, "scheduled": True, "mode": "async"}
    try:
        snapshot = disaster_recovery.create_snapshot(runtime=runtime)
        return {"ok": True, "operation": operation, **snapshot.to_dict()}
    except Exception as exc:
        return {"ok": False, "operation": operation, "error": str(exc)}


def _catalogs_payload_with_stats(*, active_catalog: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in catalog_registry.list_catalogs():
        row = item.to_dict()
        try:
            stats = catalog_registry.stats_for_catalog(item.catalog_id)
        except Exception:
            stats = {
                "book_count": item.book_count,
                "processed_count": 0,
                "winner_count": 0,
                "processed_percent": 0.0,
                "last_activity": item.updated_at,
            }
        row.update(
            {
                "processed_count": int(stats.get("processed_count", 0) or 0),
                "winner_count": int(stats.get("winner_count", 0) or 0),
                "processed_percent": float(stats.get("processed_percent", 0.0) or 0.0),
                "last_activity": str(stats.get("last_activity", item.updated_at)),
            }
        )
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("catalog_id", row.get("id", ""))))
    for row in rows:
        if "id" not in row:
            row["id"] = row.get("catalog_id")
    return {
        "catalogs": rows,
        "active_catalog": str(active_catalog),
        "default_catalog": catalog_registry.get_default_catalog_id(),
    }


def _compare_payload(*, runtime: config.Config, books: list[int]) -> dict[str, Any]:
    candidates = build_review_dataset(
        runtime.output_dir,
        input_dir=runtime.input_dir,
        catalog_path=runtime.book_catalog_path,
        quality_scores_path=_quality_scores_path_for_runtime(runtime),
    )
    wanted = {int(item) for item in books if int(item) > 0}
    if wanted:
        candidates = [row for row in candidates if _safe_int(row.get("number"), 0) in wanted]

    notes_lookup = book_metadata.list_books(_book_metadata_path_for_runtime(runtime))
    for row in candidates:
        key = str(_safe_int(row.get("number"), 0))
        meta = notes_lookup.get(key, {})
        row["tags"] = meta.get("tags", [])
        row["notes"] = meta.get("notes", "")
    payload = {
        "catalog": runtime.catalog_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "books": candidates,
        "count": len(candidates),
    }
    safe_json.atomic_write_json(_compare_data_path_for_runtime(runtime), payload)
    return payload


def _bootstrap_state_store_for_runtime(runtime: config.Config) -> dict[str, int]:
    winner_path = _winner_path_for_runtime(runtime)
    try:
        return state_db_store.bootstrap_from_json(
            catalog_id=runtime.catalog_id,
            history_path=_history_path_for_runtime(runtime),
            winner_path=winner_path,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("State DB bootstrap failed: %s", exc)
        return {"history_rows": 0, "winner_rows": 0}


def _catalog_outputs_for_runtime(runtime: config.Config) -> tuple[Path, Path, Path]:
    return (
        runtime.output_dir / "Alexandria_Cover_Catalog.pdf",
        runtime.output_dir / "Alexandria_Contact_Sheet.pdf",
        runtime.output_dir / "Alexandria_All_Variants_Catalog.pdf",
    )


def create_comparison_grid(original_path: Path, variants_dir: Path, output_path: Path) -> Path:
    """Create side-by-side image: original + up to 5 variants."""
    images = [Image.open(original_path).convert("RGB")]
    variant_images = sorted(variants_dir.glob("Variant-*/*.jpg"))[:5]

    for path in variant_images:
        images.append(Image.open(path).convert("RGB"))

    thumb_w = 640
    thumb_h = 470
    gap = 18
    width = (thumb_w * len(images)) + (gap * (len(images) + 1))
    height = thumb_h + 100

    canvas = Image.new("RGB", (width, height), "#f6f2e8")
    draw = ImageDraw.Draw(canvas)

    x = gap
    labels = ["Original"] + [f"Variant {i}" for i in range(1, len(images))]
    for img, label in zip(images, labels):
        resized = img.resize((thumb_w, thumb_h), Image.LANCZOS)
        canvas.paste(resized, (x, 40))
        draw.text((x, 16), label, fill="#223")
        x += thumb_w + gap

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=92)
    return output_path


def build_review_dataset(
    output_dir: Path,
    *,
    input_dir: Path = config.INPUT_DIR,
    catalog_path: Path = config.BOOK_CATALOG_PATH,
    quality_scores_path: Path = QUALITY_SCORES_PATH,
    books: list[int] | None = None,
    max_books: int | None = None,
) -> list[dict[str, Any]]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if books:
        wanted = set(books)
        catalog = [row for row in catalog if int(row.get("number", 0)) in wanted]
    catalog = sorted(catalog, key=lambda row: int(row.get("number", 0)))
    if max_books:
        catalog = catalog[:max_books]

    quality_lookup = _load_quality_lookup(quality_scores_path)
    rows: list[dict[str, Any]] = []

    for entry in catalog:
        number = int(entry.get("number", 0))
        folder_name = str(entry.get("folder_name", ""))
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]

        output_book = output_dir / folder_name
        input_book = input_dir / str(entry.get("folder_name", ""))
        original = _find_original_image(input_book)

        variants = []
        for variant_dir in sorted([p for p in output_book.glob("Variant-*") if p.is_dir()]):
            variant_num = _parse_variant_number(variant_dir.name)
            if variant_num is None:
                continue
            image = _find_first_jpg(variant_dir)
            if not image:
                continue
            variants.append(
                {
                    "variant": variant_num,
                    "label": f"Variant {variant_num}",
                    "image": _to_project_relative(image),
                    "quality_score": quality_lookup.get((number, variant_num)),
                }
            )

        rows.append(
            {
                "number": number,
                "title": entry.get("title", ""),
                "author": entry.get("author", ""),
                "folder": folder_name,
                "original": _to_project_relative(original) if original else "",
                "variants": sorted(variants, key=lambda item: item["variant"]),
                "best_quality_score": max(
                    [float(v["quality_score"]) for v in variants if isinstance(v.get("quality_score"), (int, float))],
                    default=0.0,
                ),
            }
        )

    return rows


def _build_review_data_payload(output_dir: Path, *, runtime: config.Config | None = None, max_books: int | None = None) -> dict[str, Any]:
    runtime = runtime or config.get_config()
    books = build_review_dataset(
        output_dir,
        input_dir=runtime.input_dir,
        catalog_path=runtime.book_catalog_path,
        quality_scores_path=_quality_scores_path_for_runtime(runtime),
        max_books=max_books,
    )
    winner_payload = _ensure_winner_payload(books, path=_winner_path_for_runtime(runtime))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog": runtime.catalog_id,
        "books": books,
        "winner_selections": winner_payload.get("selections", {}),
    }


def write_review_data(output_dir: Path, *, runtime: config.Config | None = None, max_books: int | None = None) -> Path:
    data = _build_review_data_payload(output_dir, runtime=runtime, max_books=max_books)
    runtime = runtime or config.get_config()
    review_data_path = _review_data_path_for_runtime(runtime)
    review_data_path.parent.mkdir(parents=True, exist_ok=True)
    safe_json.atomic_write_json(review_data_path, data)
    return review_data_path


def _catalog_folder_name_for_book(catalog_path: Path, book_number: int) -> str:
    entry = _json_list_rows_cache_entry(catalog_path).get("by_number", {}).get(int(book_number), {})
    return str(entry.get("folder_name", "")).strip() if isinstance(entry, dict) else ""


def _catalog_book_row(path: Path, book_number: int) -> dict[str, Any]:
    entry = _json_list_rows_cache_entry(path).get("by_number", {}).get(int(book_number), {})
    return entry if isinstance(entry, dict) else {}


def _local_cover_available(*, runtime: config.Config, book_number: int) -> bool:
    folder_name = _catalog_folder_name_for_book(runtime.book_catalog_path, int(book_number))
    if not folder_name:
        return False
    return _folder_has_local_cover(runtime.input_dir / folder_name)


def _folder_has_local_cover(folder: Path) -> bool:
    if not folder.exists() or not folder.is_dir():
        return False
    for suffix in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        if any(folder.glob(suffix)):
            return True
    return False


def _first_local_cover_path(*, runtime: config.Config, book_number: int) -> Path | None:
    folder_name = _catalog_folder_name_for_book(runtime.book_catalog_path, int(book_number))
    if not folder_name:
        return None
    folder = runtime.input_dir / folder_name
    if not folder.exists() or not folder.is_dir():
        return None
    candidates: list[Path] = []
    for suffix in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        candidates.extend(sorted(folder.glob(suffix)))
    return candidates[0] if candidates else None


def _resolve_cover_preview_source_path(
    *,
    runtime: config.Config,
    book_number: int,
    source: str,
    selected_cover_id: str = "",
    drive_folder_id: str = "",
    input_folder_id: str = "",
    credentials_path_token: str = "",
) -> tuple[Path | None, int, dict[str, Any]]:
    row = _catalog_book_row(runtime.book_catalog_path, int(book_number))
    if not row:
        return None, int(HTTPStatus.NOT_FOUND), {"error": f"Book {int(book_number)} not found in catalog."}

    local_path = _first_local_cover_path(runtime=runtime, book_number=int(book_number))
    if local_path is not None and local_path.exists():
        return local_path, int(HTTPStatus.OK), {"source": "local"}

    requested_source = str(source or "catalog").strip().lower() or "catalog"
    effective_drive_folder_id = (
        str(drive_folder_id or "").strip()
        or runtime.gdrive_source_folder_id
        or runtime.gdrive_input_folder_id
        or runtime.gdrive_output_folder_id
    )
    effective_input_folder_id = (
        str(input_folder_id or "").strip()
        or runtime.gdrive_source_folder_id
        or runtime.gdrive_input_folder_id
    )
    selected_id = (
        str(selected_cover_id or "").strip()
        or str(row.get("cover_jpg_id", "") or "").strip()
        or str(row.get("drive_cover_id", "") or "").strip()
    )
    if not effective_drive_folder_id:
        return (
            None,
            int(HTTPStatus.SERVICE_UNAVAILABLE),
            {"error": f"No source cover is available for book {int(book_number)}.", "source": requested_source},
        )

    credentials_path = Path(credentials_path_token) if str(credentials_path_token or "").strip() else _resolve_credentials_path(runtime)
    if not credentials_path.is_absolute():
        credentials_path = PROJECT_ROOT / credentials_path

    ensure_result = drive_manager.ensure_local_input_cover(
        drive_folder_id=effective_drive_folder_id,
        input_folder_id=effective_input_folder_id,
        credentials_path=credentials_path,
        catalog_path=runtime.book_catalog_path,
        input_root=runtime.input_dir,
        book_number=int(book_number),
        selected_cover_id=selected_id,
    )
    if not bool(ensure_result.get("ok")):
        return (
            None,
            int(HTTPStatus.SERVICE_UNAVAILABLE),
            {
                "error": str(ensure_result.get("error") or f"No source cover is available for book {int(book_number)}."),
                "source": requested_source,
            },
        )

    source_token = str(ensure_result.get("path", "")).strip()
    resolved_path = Path(source_token) if source_token else _first_local_cover_path(runtime=runtime, book_number=int(book_number))
    if resolved_path is None or not resolved_path.exists():
        return (
            None,
            int(HTTPStatus.SERVICE_UNAVAILABLE),
            {"error": f"No source cover is available for book {int(book_number)}.", "source": requested_source},
        )
    return resolved_path, int(HTTPStatus.OK), {"source": requested_source, "downloaded": bool(ensure_result.get("downloaded"))}


def _has_local_input_covers(*, runtime: config.Config, max_dirs: int = 250) -> bool:
    root = Path(runtime.input_dir)
    if not root.exists() or not root.is_dir():
        return False
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    checked = 0
    try:
        for child in root.iterdir():
            checked += 1
            if checked > max(10, int(max_dirs)):
                break
            if child.is_file() and child.suffix.lower() in image_suffixes:
                return True
            if not child.is_dir():
                continue
            for image_path in child.glob("*"):
                if image_path.is_file() and image_path.suffix.lower() in image_suffixes:
                    return True
    except OSError:
        return False
    return False


def _default_cover_source_for_runtime(runtime: config.Config) -> str:
    override = str(os.getenv("COVER_SOURCE_DEFAULT", "")).strip().lower()
    if override in {"catalog", "drive"}:
        return override
    return "catalog" if _has_local_input_covers(runtime=runtime) else "drive"


def _cover_preview_path_for_runtime(*, runtime: config.Config, book_number: int, source: str) -> Path:
    token = str(source or "catalog").strip().lower() or "catalog"
    if token not in {"catalog", "drive"}:
        token = "catalog"
    return runtime.tmp_dir / "cover_previews" / f"{runtime.catalog_id}_{int(book_number)}_{token}.jpg"


def _write_cover_preview(*, source_image: Path, preview_path: Path, max_size: int = 360) -> Path:
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_image) as img:
        rendered = img.convert("RGB")
        rendered.thumbnail((max(64, int(max_size)), max(64, int(max_size))))
        rendered.save(preview_path, format="JPEG", quality=85, optimize=True)
    return preview_path


def _iterate_data_dependency_paths(*, runtime: config.Config, prompts_path: Path) -> list[Path]:
    return [
        runtime.book_catalog_path,
        prompts_path,
        runtime.prompt_library_path,
        runtime.cover_templates_path,
        config.intelligent_prompts_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir),
        config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir),
        _prompt_performance_path_for_runtime(runtime),
        _winner_path_for_runtime(runtime),
        PROJECT_ROOT / "scripts" / "quality_review.py",
        PROJECT_ROOT / "src" / "config.py",
    ]


def _is_generated_payload_fresh(*, output_path: Path, sources: list[Path]) -> bool:
    if not output_path.exists():
        return False
    try:
        output_mtime = output_path.stat().st_mtime
    except OSError:
        return False
    for source in sources:
        try:
            if source.exists() and source.stat().st_mtime > output_mtime:
                return False
        except OSError:
            return False
    return True


def _compact_iterate_enrichment(enrichment: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(enrichment, dict):
        return {}
    keys = (
        "genre",
        "tags",
        "scene",
        "iconic_scenes",
        "emotional_tone",
        "mood",
        "tones",
        "era",
        "protagonist",
        "setting_primary",
        "setting_details",
        "visual_motifs",
        "symbolic_elements",
        "key_characters",
    )
    return {key: enrichment[key] for key in keys if key in enrichment}


def write_iterate_books_data(*, runtime: config.Config | None = None, prompts_path: Path | None = None, force: bool = False) -> Path:
    runtime = runtime or config.get_config()
    prompts_path = prompts_path or runtime.prompts_path
    output_path = _iterate_books_data_path_for_runtime(runtime)
    source_paths = _iterate_data_dependency_paths(runtime=runtime, prompts_path=prompts_path)
    if not force and _is_generated_payload_fresh(output_path=output_path, sources=source_paths):
        return output_path

    prompts = _load_json(prompts_path, {"books": []})
    enriched_catalog_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    enriched_catalog = _json_list_rows_cache_entry(enriched_catalog_path).get("rows", [])
    winners_payload = _load_winner_payload(_winner_path_for_runtime(runtime))
    winner_map = winners_payload.get("selections", {}) if isinstance(winners_payload, dict) else {}
    genre_prompts = _genre_prompt_payload(runtime=runtime)
    template_rows = _template_rows_for_runtime(runtime=runtime)
    default_template_id = str(template_rows[0].get("id", "")).strip() if template_rows else ""

    enriched_by_book: dict[int, dict[str, Any]] = {}
    if isinstance(enriched_catalog, list):
        for row in enriched_catalog:
            if not isinstance(row, dict):
                continue
            number = _safe_int(row.get("number"), 0)
            enrichment = row.get("enrichment", {})
            if number > 0 and isinstance(enrichment, dict):
                enriched_by_book[number] = _compact_iterate_enrichment(enrichment)

    prompt_rows = prompts.get("books", []) if isinstance(prompts, dict) else []
    if not isinstance(prompt_rows, list):
        prompt_rows = []
    prompt_by_book: dict[int, dict[str, Any]] = {}
    for row in prompt_rows:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number > 0:
            prompt_by_book[number] = row

    books: list[dict[str, Any]] = []
    for book in _catalog_books_payload(runtime.book_catalog_path):
        number = _safe_int(book.get("number"), 0)
        if number <= 0:
            continue
        prompt_row = prompt_by_book.get(number, {})
        prompt_variants = prompt_row.get("variants", []) if isinstance(prompt_row, dict) else []
        default_prompt = (
            prompt_variants[0].get("prompt", "")
            if isinstance(prompt_variants, list) and prompt_variants and isinstance(prompt_variants[0], dict)
            else ""
        )
        title = str(book.get("title", prompt_row.get("title", ""))).strip()
        author = str(book.get("author", prompt_row.get("author", ""))).strip()
        folder_name = str(book.get("folder_name", prompt_row.get("folder_name", ""))).strip()
        enrichment = enriched_by_book.get(number, {})
        inferred = genre_intelligence.infer_genre(
            title=title,
            author=author,
            metadata_genre=str(enrichment.get("genre", "") or book.get("genre", "")),
            prompts=genre_prompts,
        )
        composed = _compose_prompt_for_book(
            runtime=runtime,
            book={
                "number": number,
                "title": title,
                "author": author,
                "genre": book.get("genre", prompt_row.get("genre", "")),
                "enrichment": enrichment,
            },
            base_prompt=str(
                default_prompt
                or (
                    f'Cinematic full-bleed narrative scene for "{title}" by {author}, '
                    "single dominant focal subject, scene artwork only, no text, no logos, no borders or frames."
                )
            ),
            template_id=default_template_id,
        )
        winner_row = winner_map.get(str(number), {})
        winner_variant = _safe_int(winner_row.get("winner") if isinstance(winner_row, dict) else winner_row, 0)
        books.append(
            {
                "number": number,
                "title": title,
                "author": author,
                "folder_name": folder_name,
                "file_base": str(book.get("file_base", prompt_row.get("file_base", f"{title} - {author}".strip(" - ")))),
                "cover_jpg_id": str(book.get("cover_jpg_id", book.get("drive_cover_id", ""))).strip(),
                "cover_name": str(book.get("cover_name", book.get("drive_name", title))).strip(),
                "drive_kind": str(book.get("drive_kind", "")).strip(),
                "default_prompt": default_prompt,
                "genre": str(composed.get("genre", inferred.get("genre", "literary_fiction")) or "literary_fiction"),
                "composed_prompt": str(composed.get("prompt", default_prompt)).strip(),
                "prompt_components": {
                    "title_keywords": composed.get("title_keywords", genre_intelligence.extract_title_keywords(title=title, limit=6)),
                },
                "enrichment": enrichment,
                "local_cover_available": _folder_has_local_cover(runtime.input_dir / folder_name) or bool(book.get("cover_jpg_id")),
                "winner_variant": winner_variant,
                "winner_selected": bool(winner_variant > 0),
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog": runtime.catalog_id,
        "catalogs": [item.to_dict() for item in config.list_catalogs()],
        "books": books,
        "total_books": len(books),
        "enrichment_available": bool(enriched_by_book),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_json.atomic_write_json(output_path, payload)
    return output_path


def write_iterate_data(*, runtime: config.Config | None = None, prompts_path: Path | None = None, force: bool = False) -> Path:
    runtime = runtime or config.get_config()
    prompts_path = prompts_path or runtime.prompts_path
    iterate_path = _iterate_data_path_for_runtime(runtime)
    source_paths = _iterate_data_dependency_paths(runtime=runtime, prompts_path=prompts_path)
    if not force and _is_generated_payload_fresh(output_path=iterate_path, sources=source_paths):
        return iterate_path
    prompts = _load_json(prompts_path, {"books": []})
    library = PromptLibrary(runtime.prompt_library_path)

    intelligent_prompts_path = config.intelligent_prompts_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    enriched_catalog_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    smart_payload = _load_json(intelligent_prompts_path, {"books": []})
    enriched_catalog = _json_list_rows_cache_entry(enriched_catalog_path).get("rows", [])
    prompt_performance = _load_json(_prompt_performance_path_for_runtime(runtime), {"patterns": {}})
    template_rows = _template_rows_for_runtime(runtime=runtime)
    budget_presets = _budget_presets_for_runtime(runtime)
    default_template_id = str(template_rows[0].get("id", "heritage_classic")).strip() if template_rows else "heritage_classic"

    smart_by_book: dict[int, dict[str, Any]] = {}
    smart_books = smart_payload.get("books", []) if isinstance(smart_payload, dict) else []
    if isinstance(smart_books, list):
        for row in smart_books:
            if not isinstance(row, dict):
                continue
            number = _safe_int(row.get("number"), 0)
            if number > 0:
                smart_by_book[number] = row

    enriched_by_book: dict[int, dict[str, Any]] = {}
    if isinstance(enriched_catalog, list):
        for row in enriched_catalog:
            if not isinstance(row, dict):
                continue
            number = _safe_int(row.get("number"), 0)
            if number <= 0:
                continue
            enrichment = row.get("enrichment", {})
            if isinstance(enrichment, dict):
                enriched_by_book[number] = enrichment

    provider_models: dict[str, list[str]] = {}
    for model in runtime.all_models:
        provider = runtime.resolve_model_provider(model)
        provider_models.setdefault(provider, []).append(model)
    for provider in runtime.provider_keys.keys():
        provider_models.setdefault(provider, [])
    winners_payload = _load_winner_payload(_winner_path_for_runtime(runtime))
    winner_map = winners_payload.get("selections", {}) if isinstance(winners_payload, dict) else {}

    prompt_rows = prompts.get("books", []) if isinstance(prompts, dict) else []
    if not isinstance(prompt_rows, list):
        prompt_rows = []
    prompt_by_book: dict[int, dict[str, Any]] = {}
    for row in prompt_rows:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        prompt_by_book[number] = row

    catalog_rows = _catalog_books_payload(runtime.book_catalog_path)
    source_books = catalog_rows if catalog_rows else [row for row in prompt_rows if isinstance(row, dict)]

    books = []
    for book in source_books:
        number = int(book.get("number", 0))
        if number <= 0:
            continue
        prompt_row = prompt_by_book.get(number, {})
        prompt_variants = prompt_row.get("variants", []) if isinstance(prompt_row, dict) else []
        default_prompt = (
            prompt_variants[0].get("prompt", "")
            if isinstance(prompt_variants, list) and prompt_variants and isinstance(prompt_variants[0], dict)
            else ""
        )
        title = str(book.get("title", prompt_row.get("title", "")))
        author = str(book.get("author", prompt_row.get("author", "")))
        folder_name = str(book.get("folder_name", prompt_row.get("folder_name", "")))
        cover_jpg_id = str(book.get("cover_jpg_id", book.get("drive_cover_id", ""))).strip()
        cover_name = str(book.get("cover_name", book.get("drive_name", folder_name or title))).strip()
        smart_row = smart_by_book.get(number, {})
        smart_variants = smart_row.get("variants", []) if isinstance(smart_row, dict) else []
        winner_row = winner_map.get(str(number), {})
        winner_variant = _safe_int(winner_row.get("winner") if isinstance(winner_row, dict) else winner_row, 0)
        composed = _compose_prompt_for_book(
            runtime=runtime,
            book={
                "number": number,
                "title": title,
                "author": author,
                "genre": book.get("genre", prompt_row.get("genre", "")),
                "enrichment": enriched_by_book.get(number, {}),
            },
            base_prompt=str(
                default_prompt
                or (
                    f'Cinematic full-bleed narrative scene for "{title}" by {author}, '
                    "single dominant focal subject, scene artwork only, no text, no logos, no borders or frames."
                )
            ),
            template_id=default_template_id,
        )
        prompt_context = content_relevance.resolve_prompt_context(
            {
                "number": number,
                "title": title,
                "author": author,
                "genre": book.get("genre", prompt_row.get("genre", "")),
                "enrichment": enriched_by_book.get(number, {}),
            }
        )
        books.append(
            {
                "number": number,
                "title": title,
                "author": author,
                "folder_name": folder_name,
                "file_base": str(book.get("file_base", prompt_row.get("file_base", f"{title} - {author}".strip(" - ")))),
                "cover_jpg_id": cover_jpg_id,
                "cover_name": cover_name,
                "drive_kind": str(book.get("drive_kind", "")).strip(),
                "default_prompt": default_prompt,
                "default_template_id": default_template_id,
                "genre": composed.get("genre", "literary_fiction"),
                "inferred_genre_source": composed.get("genre_source", "default"),
                "composed_prompt": composed.get("prompt", default_prompt),
                "prompt_components": {
                    "base": composed.get("base", ""),
                    "template": composed.get("template", ""),
                    "genre_modifier": composed.get("genre_modifier", ""),
                    "genre": composed.get("genre", ""),
                    "title_keywords": composed.get("title_keywords", []),
                    "negative": composed.get("negative", ""),
                },
                "enrichment": enriched_by_book.get(number, {}),
                "prompt_context": prompt_context,
                "smart_prompts": smart_variants if isinstance(smart_variants, list) else [],
                "local_cover_available": _folder_has_local_cover(runtime.input_dir / folder_name) or bool(cover_jpg_id),
                "winner_variant": winner_variant,
                "winner_selected": bool(winner_variant > 0),
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog": runtime.catalog_id,
        "catalogs": [item.to_dict() for item in config.list_catalogs()],
        "models": runtime.all_models,
        "providers": sorted(runtime.provider_keys.keys()),
        "provider_models": provider_models,
        "default_provider": runtime.ai_provider,
        "books": books,
        "default_variants_per_model": runtime.variants_per_cover,
        "max_generation_variants": _max_generation_variants(runtime),
        "prompt_sources": ["template", "ai_generated", "library", "custom"],
        "intelligent_prompts_available": bool(smart_by_book),
        "enrichment_available": bool(enriched_by_book),
        "prompt_performance": prompt_performance.get("patterns", {}) if isinstance(prompt_performance, dict) else {},
        "style_anchors": [asdict(anchor) for anchor in library.get_style_anchors()],
        "prompt_library": [asdict(item) for item in library.get_prompts()],
        "model_costs": {model: runtime.get_model_cost(model) for model in runtime.all_models},
        "model_modalities": {model: runtime.get_model_modality(model) for model in runtime.all_models},
        "gdrive_output_folder_id": str(runtime.gdrive_output_folder_id or ""),
        "default_cover_source": _default_cover_source_for_runtime(runtime),
        "local_input_covers_available": _has_local_input_covers(runtime=runtime),
        "templates": template_rows,
        "default_template_id": default_template_id,
        "budget_presets": budget_presets,
    }

    iterate_path.parent.mkdir(parents=True, exist_ok=True)
    safe_json.atomic_write_json(iterate_path, payload)
    return iterate_path


def _catalog_books_payload(path: Path) -> list[dict[str, Any]]:
    return list(_json_list_rows_cache_entry(path).get("rows", []))


_KNOWN_DRIVE_COVER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".pdf", ".ai")


def _strip_known_drive_suffix(name: str) -> str:
    token = str(name or "").strip()
    lower = token.lower()
    for suffix in _KNOWN_DRIVE_COVER_SUFFIXES:
        if lower.endswith(suffix):
            return token[: -len(suffix)].strip()
    return token


def _title_author_from_drive_name(name: str) -> tuple[str, str]:
    token = _strip_known_drive_suffix(name)
    token = re.sub(r"^\s*\d+\s*[\.\-:)]*\s*", "", token).strip()
    token = token.replace("_", " ")
    token = re.sub(r"\s+", " ", token).strip()
    if not token:
        return "Untitled", ""
    for separator in (" - ", " — "):
        if separator not in token:
            continue
        left, right = token.rsplit(separator, 1)
        title = left.strip() or token
        author = right.strip()
        if 1 <= len(author.split()) <= 8:
            return title, author
    return token, ""


def _build_catalog_rows_from_drive_covers(*, covers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    used_numbers: set[int] = set()
    used_folders: set[str] = set()
    next_number = 1

    for entry in covers:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        parsed_title, parsed_author = _title_author_from_drive_name(name)
        mapped_title = str(entry.get("title", "")).strip()
        mapped_author = str(entry.get("author", "")).strip()
        normalized_parsed = parsed_title.strip().lower()
        normalized_mapped = mapped_title.strip().lower()
        title = parsed_title
        if not title or normalized_parsed == "untitled":
            title = mapped_title or title
        elif re.fullmatch(r"book\s+\d+", normalized_parsed) and mapped_title and normalized_mapped != "untitled":
            title = mapped_title
        author = parsed_author or mapped_author
        mapped_number = _safe_int(entry.get("book_number"), 0)
        number = 0
        if mapped_number > 0 and mapped_number not in used_numbers:
            number = mapped_number
        else:
            while next_number in used_numbers:
                next_number += 1
            number = next_number
        used_numbers.add(number)
        next_number = max(next_number, number + 1)

        folder_seed = f"{number}. {title}" + (f" - {author}" if author else "")
        folder_name = f"{folder_seed} copy"
        collision = 2
        while folder_name in used_folders:
            folder_name = f"{folder_seed} copy {collision}"
            collision += 1
        used_folders.add(folder_name)

        file_base = f"{title} - {author}".strip(" -") or title or f"Book {number}"
        rows.append(
            {
                "number": number,
                "title": title or f"Book {number}",
                "author": author,
                "folder_name": folder_name,
                "file_base": file_base,
                "formats": ["ai", "jpg", "pdf"],
                "cover_jpg_id": str(entry.get("id", "")).strip(),
                "cover_name": name,
                "drive_kind": str(entry.get("kind", "")).strip().lower(),
            }
        )

    rows.sort(key=lambda item: _safe_int(item.get("number"), 0))
    return rows


def _normalized_catalog_title_token(value: str) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9\s]+", " ", token)
    token = re.sub(r"\s+", " ", token).strip()
    return token


def _merge_catalog_rows_with_drive(
    *,
    existing_rows: list[dict[str, Any]],
    covers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Preserve catalog metadata, refresh Drive ids, and append newly discovered books."""
    rows_by_number: dict[int, dict[str, Any]] = {}
    title_to_number: dict[str, int] = {}
    used_folders: set[str] = set()
    existing_count = 0
    for row in existing_rows:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        copied = dict(row)
        rows_by_number[number] = copied
        existing_count += 1
        folder_name = str(copied.get("folder_name", "")).strip()
        if folder_name:
            used_folders.add(folder_name)
        title_key = _normalized_catalog_title_token(str(copied.get("title", "")))
        if title_key and title_key not in title_to_number:
            title_to_number[title_key] = number

    def _apply_drive_metadata(row: dict[str, Any], *, cover_id: str, cover_name: str, drive_kind: str) -> None:
        if cover_id:
            row["cover_jpg_id"] = cover_id
            row["drive_cover_id"] = cover_id
        if cover_name:
            row["cover_name"] = cover_name
        if drive_kind:
            row["drive_kind"] = drive_kind

    matched = 0
    unmatched = 0
    added = 0
    next_number = max(rows_by_number.keys(), default=0) + 1
    for entry in covers:
        if not isinstance(entry, dict):
            unmatched += 1
            continue
        cover_id = str(entry.get("id", "")).strip()
        cover_name = str(entry.get("name", "")).strip()
        drive_kind = str(entry.get("kind", "")).strip().lower()
        if not cover_name and not cover_id:
            unmatched += 1
            continue
        mapped_title = str(entry.get("title", "")).strip()
        mapped_author = str(entry.get("author", "")).strip()

        number = _safe_int(entry.get("book_number"), 0)
        parsed_title = ""
        parsed_author = ""
        if number <= 0 or number not in rows_by_number:
            number = 0
            if cover_name:
                prefix = re.match(r"^\s*(\d+)\b", cover_name)
                if prefix:
                    pref_number = _safe_int(prefix.group(1), 0)
                    if pref_number > 0:
                        number = pref_number
            if number <= 0 and cover_name:
                parsed_title, parsed_author = _title_author_from_drive_name(cover_name)
                title_key = _normalized_catalog_title_token(parsed_title)
                number = _safe_int(title_to_number.get(title_key), 0)
        if not parsed_title and cover_name:
            parsed_title, parsed_author = _title_author_from_drive_name(cover_name)
        title_key = _normalized_catalog_title_token(parsed_title)

        if number > 0 and number in rows_by_number:
            _apply_drive_metadata(rows_by_number[number], cover_id=cover_id, cover_name=cover_name, drive_kind=drive_kind)
            matched += 1
            continue

        # Add a new row for a newly discovered Drive item.
        normalized_parsed = parsed_title.strip().lower()
        normalized_mapped = mapped_title.strip().lower()
        title = parsed_title
        if not title or normalized_parsed == "untitled":
            title = mapped_title or title
        elif re.fullmatch(r"book\s+\d+", normalized_parsed) and mapped_title and normalized_mapped != "untitled":
            title = mapped_title
        title = (title or "").strip() or "Untitled"
        author = (parsed_author or mapped_author or "").strip()

        if number <= 0:
            while next_number in rows_by_number:
                next_number += 1
            number = next_number
        while number in rows_by_number:
            # If a numeric collision happens, keep rows unique and stable.
            number += 1
        next_number = max(next_number, number + 1)

        folder_seed = f"{number}. {title}" + (f" - {author}" if author else "")
        folder_name = f"{folder_seed} copy"
        suffix = 2
        while folder_name in used_folders:
            folder_name = f"{folder_seed} copy {suffix}"
            suffix += 1
        used_folders.add(folder_name)

        file_base = f"{title} - {author}".strip(" -") or title or f"Book {number}"
        row = {
            "number": number,
            "title": title or f"Book {number}",
            "author": author,
            "folder_name": folder_name,
            "file_base": file_base,
            "formats": ["ai", "jpg", "pdf"],
        }
        _apply_drive_metadata(row, cover_id=cover_id, cover_name=cover_name, drive_kind=drive_kind)
        rows_by_number[number] = row
        if title_key and title_key not in title_to_number:
            title_to_number[title_key] = number
        added += 1

    ordered_rows = [rows_by_number[key] for key in sorted(rows_by_number.keys())]
    return ordered_rows, {
        "matched": int(matched),
        "unmatched": int(unmatched),
        "existing": int(existing_count),
        "added": int(added),
    }


def _queue_catalog_enrichment(*, runtime: config.Config, books: list[int], reason: str) -> dict[str, Any]:
    target_books = sorted({int(book) for book in books if int(book) > 0})
    if not target_books:
        return {"queued": False, "reason": "no_books", "books": [], "count": 0}

    catalog_id = runtime.catalog_id
    enriched_path = config.enriched_catalog_path(catalog_id=catalog_id, config_dir=runtime.config_dir)
    usage_path = _llm_usage_path_for_runtime(runtime)
    descriptions_path = runtime.config_dir / "book_descriptions.json"

    with _CATALOG_ENRICHMENT_THREADS_LOCK:
        active = _CATALOG_ENRICHMENT_THREADS.get(catalog_id)
        if active is not None and active.is_alive():
            return {
                "queued": False,
                "reason": "already_running",
                "books": target_books,
                "count": len(target_books),
            }

        def _worker() -> None:
            try:
                worker_runtime = config.get_config(catalog_id)
                summary = book_enricher.enrich_catalog(
                    catalog_path=worker_runtime.book_catalog_path,
                    output_path=enriched_path,
                    books=target_books,
                    force_refresh=False,
                    provider=worker_runtime.llm_provider,
                    model=worker_runtime.llm_model,
                    max_tokens=worker_runtime.llm_max_tokens,
                    cost_per_1k_tokens=worker_runtime.llm_cost_per_1k_tokens,
                    usage_path=usage_path,
                    descriptions_path=descriptions_path,
                )
                write_iterate_data(runtime=worker_runtime)
                _invalidate_cache("/api/iterate-data", "/api/prompt-performance", "/api/dashboard-data", "/api/analytics/")
                logger.info(
                    "Background enrichment completed",
                    extra={
                        "catalog": catalog_id,
                        "reason": reason,
                        "books": len(target_books),
                        "validation": summary.get("validation", {}),
                    },
                )
            except Exception as exc:  # pragma: no cover - background guard
                logger.warning(
                    "Background enrichment failed for catalog %s (%s): %s",
                    catalog_id,
                    reason,
                    exc,
                )
            finally:
                with _CATALOG_ENRICHMENT_THREADS_LOCK:
                    if _CATALOG_ENRICHMENT_THREADS.get(catalog_id) is thread:
                        _CATALOG_ENRICHMENT_THREADS.pop(catalog_id, None)

        thread = threading.Thread(
            target=_worker,
            name=f"catalog-enrich-{catalog_id}",
            daemon=True,
        )
        _CATALOG_ENRICHMENT_THREADS[catalog_id] = thread
        thread.start()

    return {
        "queued": True,
        "reason": reason,
        "books": target_books,
        "count": len(target_books),
    }


def _sync_catalog_from_drive(*, runtime: config.Config, force: bool = False, limit: int = 5000) -> dict[str, Any]:
    source_default = (
        str(getattr(runtime, "gdrive_source_folder_id", "") or "").strip()
        or str(getattr(runtime, "gdrive_input_folder_id", "") or "").strip()
        or str(getattr(runtime, "gdrive_output_folder_id", "") or "").strip()
    )
    if not source_default:
        raise RuntimeError("Google Drive source folder is not configured.")

    input_folder_id = (
        str(getattr(runtime, "gdrive_source_folder_id", "") or "").strip()
        or str(getattr(runtime, "gdrive_input_folder_id", "") or "").strip()
    )

    credentials_path = _resolve_credentials_path(runtime)
    if not credentials_path.is_absolute():
        credentials_path = PROJECT_ROOT / credentials_path

    if force:
        try:
            drive_manager.clear_drive_cover_cache()
        except Exception:
            pass

    payload = drive_manager.list_input_covers(
        drive_folder_id=source_default,
        input_folder_id=input_folder_id,
        credentials_path=credentials_path,
        catalog_path=runtime.book_catalog_path,
        limit=max(1, min(50000, int(limit or 5000))),
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected Drive sync response.")
    error_text = str(payload.get("error", "")).strip()
    if error_text:
        raise RuntimeError(error_text)

    covers = payload.get("covers", [])
    if not isinstance(covers, list):
        covers = []
    rows = [row for row in covers if isinstance(row, dict)]
    if not rows:
        raise RuntimeError("No Drive titles found in source folder.")

    existing_catalog_rows = _catalog_books_payload(runtime.book_catalog_path)
    existing_numbers = {
        _safe_int(row.get("number"), 0)
        for row in existing_catalog_rows
        if isinstance(row, dict) and _safe_int(row.get("number"), 0) > 0
    }
    if existing_catalog_rows:
        catalog_rows, merge_stats = _merge_catalog_rows_with_drive(
            existing_rows=existing_catalog_rows,
            covers=rows,
        )
        if not catalog_rows:
            raise RuntimeError("Existing catalog is empty after merge.")
    else:
        catalog_rows = _build_catalog_rows_from_drive_covers(covers=rows)
        merge_stats = {
            "matched": int(len(catalog_rows)),
            "unmatched": max(0, int(len(rows) - len(catalog_rows))),
            "existing": int(len(catalog_rows)),
        }
        if not catalog_rows:
            raise RuntimeError("Unable to derive catalog rows from Drive entries.")

    runtime.book_catalog_path.parent.mkdir(parents=True, exist_ok=True)
    safe_json.atomic_write_json(runtime.book_catalog_path, catalog_rows)
    added_numbers = [
        _safe_int(row.get("number"), 0)
        for row in catalog_rows
        if isinstance(row, dict) and _safe_int(row.get("number"), 0) > 0 and _safe_int(row.get("number"), 0) not in existing_numbers
    ]
    auto_enrichment = _queue_catalog_enrichment(
        runtime=runtime,
        books=added_numbers,
        reason="drive_sync_new_books",
    )
    write_iterate_data(runtime=runtime)
    iterate_payload = _load_json(_iterate_data_path_for_runtime(runtime), {"books": []})
    iterate_rows = iterate_payload.get("books", []) if isinstance(iterate_payload, dict) else []
    cgi_books: list[dict[str, Any]] = []
    for row in iterate_rows:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        cgi_books.append(
            {
                "id": number,
                "number": number,
                "title": str(row.get("title", "")),
                "author": str(row.get("author", "")),
                "folder_name": str(row.get("folder_name", row.get("folder", ""))),
                "cover_jpg_id": str(row.get("cover_jpg_id", "")),
                "cover_name": str(row.get("cover_name", "")),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    try:
        CGI_CATALOG_CACHE_PATH.write_text(
            json.dumps(
                {
                    "books": cgi_books,
                    "count": len(cgi_books),
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    _invalidate_cache("/api/iterate-data", "/api/enrichment-health", "/cgi-bin/catalog.py", "/cgi-bin/catalog.py/status")
    added_books = [
        row for row in catalog_rows
        if isinstance(row, dict) and _safe_int(row.get("number"), 0) not in existing_numbers
    ]
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "count": len(catalog_rows),
        "drive_total": _safe_int(payload.get("total"), len(catalog_rows)),
        "source_count": len(rows),
        "matched_drive_entries": int(merge_stats.get("matched", 0)),
        "unmatched_drive_entries": int(merge_stats.get("unmatched", 0)),
        "added_drive_entries": int(merge_stats.get("added", 0)),
        "auto_enrichment": auto_enrichment,
        "added_books": added_books,
        "books": cgi_books,
    }


def _queue_auto_enrichment_for_books(*, runtime: config.Config, books: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(books, list) or not books:
        return {"queued": 0, "skipped": 0}

    enriched_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    queued = 0
    skipped = 0
    for row in books:
        if not isinstance(row, dict):
            continue
        result = book_enricher._maybe_enrich_async(
            book=row,
            output_path=enriched_path,
            descriptions_path=runtime.config_dir / "book_descriptions.json",
            provider=runtime.llm_provider,
            model=runtime.llm_model,
            max_tokens=runtime.llm_max_tokens,
            cost_per_1k_tokens=runtime.llm_cost_per_1k_tokens,
            usage_path=_llm_usage_path_for_runtime(runtime),
            delay_seconds=0.25,
        )
        if result.get("queued"):
            queued += 1
        else:
            skipped += 1
    return {"queued": queued, "skipped": skipped}


def _enrichment_run_state(catalog_id: str) -> dict[str, Any]:
    with _ENRICHMENT_RUN_LOCK:
        state = _ENRICHMENT_RUN_STATUS.get(str(catalog_id), {})
        return dict(state) if isinstance(state, dict) else {}


def _set_enrichment_run_state(catalog_id: str, state: dict[str, Any]) -> None:
    with _ENRICHMENT_RUN_LOCK:
        _ENRICHMENT_RUN_STATUS[str(catalog_id)] = dict(state)


def _start_generic_enrichment_background(
    *,
    runtime: config.Config,
    delay_seconds: float = 0.5,
    batch_size: int = 50,
) -> dict[str, Any]:
    catalog_id = str(runtime.catalog_id)
    current = _enrichment_run_state(catalog_id)
    if current.get("running"):
        return {"ok": True, "started": False, "status": current}

    started_at = datetime.now(timezone.utc).isoformat()
    _set_enrichment_run_state(
        catalog_id,
        {
            "running": True,
            "started_at": started_at,
            "delay_seconds": float(delay_seconds),
            "batch_size": int(batch_size),
            "summary": {},
            "error": "",
        },
    )

    def _run() -> None:
        try:
            enriched_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
            summary = book_enricher.enrich_catalog(
                catalog_path=runtime.book_catalog_path,
                output_path=enriched_path,
                replace_generic=True,
                provider=runtime.llm_provider,
                model=runtime.llm_model,
                max_tokens=runtime.llm_max_tokens,
                cost_per_1k_tokens=runtime.llm_cost_per_1k_tokens,
                usage_path=_llm_usage_path_for_runtime(runtime),
                descriptions_path=runtime.config_dir / "book_descriptions.json",
                delay_seconds=delay_seconds,
                batch_size=batch_size,
            )
            write_iterate_data(runtime=runtime)
            _invalidate_cache("/api/iterate-data", "/api/prompt-performance", "/api/enrichment-health")
            _set_enrichment_run_state(
                catalog_id,
                {
                    "running": False,
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "delay_seconds": float(delay_seconds),
                    "batch_size": int(batch_size),
                    "summary": summary,
                    "error": "",
                },
            )
        except Exception as exc:  # pragma: no cover - background path
            logger.warning("Background generic enrichment failed for %s: %s", catalog_id, exc)
            _set_enrichment_run_state(
                catalog_id,
                {
                    "running": False,
                    "started_at": started_at,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "delay_seconds": float(delay_seconds),
                    "batch_size": int(batch_size),
                    "summary": {},
                    "error": str(exc),
                },
            )

    thread = threading.Thread(
        target=_run,
        name=f"generic-enrichment-{catalog_id}",
        daemon=True,
    )
    thread.start()
    return {"ok": True, "started": True, "status": _enrichment_run_state(catalog_id)}


def _enrichment_health_payload(*, runtime: config.Config) -> dict[str, Any]:
    catalog_rows = _catalog_books_payload(runtime.book_catalog_path)
    enriched_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    enriched_rows = _load_json(enriched_path, [])
    enriched_by_number = {
        _safe_int(row.get("number"), 0): row
        for row in enriched_rows if isinstance(row, dict) and _safe_int(row.get("number"), 0) > 0
    } if isinstance(enriched_rows, list) else {}

    total_books = 0
    enriched_real = 0
    enriched_generic = 0
    no_enrichment = 0
    generic_books: list[dict[str, Any]] = []

    for row in catalog_rows:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        total_books += 1
        enriched_row = enriched_by_number.get(number, {})
        enrichment = enriched_row.get("enrichment") if isinstance(enriched_row, dict) else None
        if not isinstance(enrichment, dict) or not enrichment:
            no_enrichment += 1
            continue
        reasons = book_enricher._enrichment_generic_reasons(enrichment)
        if reasons:
            enriched_generic += 1
            generic_books.append(
                {
                    "number": number,
                    "title": str(row.get("title", "")),
                    "reason": ", ".join(reasons),
                }
            )
        else:
            enriched_real += 1

    generic_ratio = (enriched_generic / total_books) if total_books > 0 else 0.0
    if generic_ratio < 0.05 and no_enrichment == 0:
        health = "healthy"
    elif generic_ratio < 0.20:
        health = "warning"
    else:
        health = "critical"

    usage_payload = _load_json(_llm_usage_path_for_runtime(runtime), {})
    last_run = {}
    if isinstance(usage_payload, dict):
        candidate = usage_payload.get("last_run", {})
        last_run = candidate if isinstance(candidate, dict) else {}

    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "total_books": total_books,
        "enriched_real": enriched_real,
        "enriched_generic": enriched_generic,
        "no_enrichment": no_enrichment,
        "generic_books": generic_books[:50],
        "last_enrichment_run": str(last_run.get("timestamp", "")),
        "health": health,
        "run_status": _enrichment_run_state(runtime.catalog_id),
    }


def _template_rows_for_runtime(*, runtime: config.Config, genre: str = "") -> list[dict[str, Any]]:
    return template_registry.list_templates(
        genre=str(genre or "").strip().lower(),
        config_dir=runtime.config_dir,
    )


def _template_for_id(*, runtime: config.Config, template_id: str) -> dict[str, Any] | None:
    token = str(template_id or "").strip()
    if not token:
        return None
    return template_registry.get_template(template_id=token, config_dir=runtime.config_dir)


def _template_for_genre(*, runtime: config.Config, genre: str) -> dict[str, Any] | None:
    token = str(genre or "").strip().lower()
    if not token:
        return None
    templates = _template_rows_for_runtime(runtime=runtime)
    for row in templates:
        genres = row.get("genres", [])
        if not isinstance(genres, list):
            continue
        normalized = {str(item).strip().lower() for item in genres if str(item).strip()}
        if token in normalized:
            return row
    return None


def _validate_template_id(*, runtime: config.Config, template_id: str) -> tuple[bool, dict[str, Any]]:
    token = str(template_id or "").strip()
    if not token:
        return True, {}
    template = _template_for_id(runtime=runtime, template_id=token)
    if template is not None:
        return True, {"template": template}
    supported = [str(row.get("id", "")).strip() for row in _template_rows_for_runtime(runtime=runtime) if str(row.get("id", "")).strip()]
    return False, {"template_id": token, "supported_template_ids": supported}


def _genre_prompt_payload(*, runtime: config.Config) -> dict[str, Any]:
    return genre_intelligence.load_genre_prompts(config_dir=runtime.config_dir)


def _book_row_for_number(*, runtime: config.Config, book_number: int) -> dict[str, Any] | None:
    match: dict[str, Any] | None = None
    books = _catalog_books_payload(runtime.book_catalog_path)
    for row in books:
        if _safe_int(row.get("number"), 0) == int(book_number):
            match = dict(row)
            break
    if match is None:
        return None
    enriched_catalog_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    enriched_rows = _json_list_rows_cache_entry(enriched_catalog_path).get("rows", [])
    if isinstance(enriched_rows, list):
        for row in enriched_rows:
            if _safe_int((row or {}).get("number"), 0) != int(book_number):
                continue
            enrichment = row.get("enrichment", {}) if isinstance(row, dict) else {}
            if isinstance(enrichment, dict):
                match["enrichment"] = enrichment
            break
    return match


def _prompt_reference_tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(token) >= 4]


def _looks_like_scene_first_prompt(prompt: str) -> bool:
    text = " ".join(str(prompt or "").lower().split()).strip()
    if not text.startswith("book cover illustration only"):
        return False
    first_320 = text[:320]
    return "{scene}" in first_320 or (
        "this circular medallion illustration" in first_320
        and ("must depict" in first_320 or "scene:" in first_320 or "illustration must" in first_320)
    )


def _ensure_prompt_book_context(
    *,
    prompt: str,
    book: dict[str, Any],
    require_motif: bool = False,
    variant_index: int = 0,
    scene_override: str = "",
) -> str:
    text = " ".join(str(prompt or "").split()).strip()
    title = str(book.get("title", "") or "").strip()
    author = str(book.get("author", "") or "").strip()
    if not title:
        return text
    if _looks_like_scene_first_prompt(text):
        return text

    text_lower = text.lower()
    title_tokens = _prompt_reference_tokens(title)
    author_tokens = _prompt_reference_tokens(author)
    has_reference = any(token in text_lower for token in (title_tokens + author_tokens) if token)
    context = ""
    if not has_reference:
        context = f"Illustration for '{title}'"
        if author:
            context = f"{context} by {author}"
        text = f"{context}. {text}".strip()

    scene = ""
    enrichment = book.get("enrichment", {}) if isinstance(book.get("enrichment"), dict) else {}
    protagonist = _specific_protagonist(enrichment, book)
    if require_motif:
        scene = _scene_for_book_variant(
            book,
            variant_index=variant_index,
            scene_override=scene_override,
        )
        if not scene:
            scene = _motif_scene_for_book(book)
    constrained = prompt_generator.enforce_prompt_constraints(text)
    if context and context.lower() not in constrained.lower():
        constrained = f"{context}. {constrained}".strip()
    scene_anchor = _clean_enrichment_text(scene)
    if scene_anchor and scene_anchor.lower() not in constrained.lower():
        anchor_parts = [
            f"CRITICAL SCENE REQUIREMENT — the illustration must specifically depict: {scene_anchor.rstrip(' .!?')}."
        ]
        if protagonist and protagonist.lower() not in scene_anchor.lower():
            anchor_parts.append(f"The main character shown is {protagonist}.")
        constrained = f"{' '.join(anchor_parts)} {constrained}".strip()
    elif protagonist and protagonist.lower() not in constrained.lower():
        constrained = f"The main character shown is {protagonist}. {constrained}".strip()
    words = constrained.split()
    if len(words) > 92:
        constrained = " ".join(words[:92]).rstrip(",")
    return constrained.strip()


_PLACEHOLDER_PATTERN = re.compile(r"\{(SCENE|MOOD|ERA|TITLE|AUTHOR|SUBTITLE)\}", re.IGNORECASE)
_GENERIC_SCENE_PATTERN = re.compile(
    r'A pivotal dramatic moment from the literary work\s+"[^"]*"'
    r'(?:\s+by\s+[^,."]+)?'
    r'(?:,\s*depicting the central emotional conflict[^.]*\.?)?',
    re.IGNORECASE,
)
_GENERIC_MOOD_PATTERN = re.compile(r"classical,\s+timeless,\s+evocative", re.IGNORECASE)
_GENERIC_ENRICHMENT_MARKERS: tuple[str, ...] = (
    "iconic turning point",
    "central protagonist",
    "atmospheric setting moment",
    "defining confrontation involving",
    "historically grounded era",
    "classical dramatic tension",
    "period costume and historically grounded",
    "symbolic object tied to the story",
    "circular medallion-ready composition",
    "dramatic emotional conflict",
)
_GENERIC_ENRICHMENT_PATTERN = re.compile(
    "|".join(re.escape(marker) for marker in _GENERIC_ENRICHMENT_MARKERS),
    re.IGNORECASE,
)
_GENERIC_SCENE_FALLBACK_PATTERN = _GENERIC_ENRICHMENT_PATTERN
_PROMPT_VALIDATION_GENERIC_MARKERS: tuple[str, ...] = _GENERIC_ENRICHMENT_MARKERS + (
    "{scene}",
    "{mood}",
    "{era}",
    "{title}",
    "{author}",
)


def _clean_enrichment_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_generic_enrichment_text(value: Any) -> bool:
    text = _clean_enrichment_text(value)
    return bool(text) and bool(_GENERIC_ENRICHMENT_PATTERN.search(text))


def _specific_enrichment_text(value: Any, *, min_length: int = 1) -> str:
    text = _clean_enrichment_text(value)
    if not text or len(text) < int(min_length) or _is_generic_enrichment_text(text):
        return ""
    return text


def _specific_enrichment_list(values: Any, *, min_length: int = 1) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _specific_enrichment_text(value, min_length=min_length)
        if not text:
            continue
        token = text.lower()
        if token in seen:
            continue
        seen.add(token)
        cleaned.append(text)
    return cleaned


def _specific_era_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _specific_enrichment_text(item, min_length=6)
            if text:
                return text
        return ""
    return _specific_enrichment_text(value, min_length=6)


def _specific_protagonist(enrichment: dict[str, Any], book: dict[str, Any] | None = None) -> str:
    fallback = book.get("protagonist", "") if isinstance(book, dict) else ""
    return _specific_enrichment_text(enrichment.get("protagonist", "") or fallback, min_length=6)


def _filtered_enrichment_scenes(enrichment: dict[str, Any]) -> list[str]:
    return _specific_enrichment_list(enrichment.get("iconic_scenes", []), min_length=30)


def _motif_scene_for_book(book: dict[str, Any]) -> str:
    try:
        motif = prompt_generator._motif_for_book(book)  # type: ignore[attr-defined]
        return _clean_enrichment_text(getattr(motif, "iconic_scene", "") or "")
    except Exception:
        return ""


def _append_protagonist_to_scene(scene: str, protagonist: str, *, lead_in: str = "The main character is") -> str:
    base_scene = _clean_enrichment_text(scene)
    hero = _specific_enrichment_text(protagonist, min_length=6)
    if not base_scene or not hero:
        return base_scene
    if hero.lower() in base_scene.lower():
        return base_scene
    return f"{base_scene.rstrip(' .!?')}. {lead_in} {hero}"


def _is_generic_enrichment(enrichment: dict[str, Any]) -> bool:
    if not isinstance(enrichment, dict) or not enrichment:
        return True
    placeholder_hits = False
    for key in (
        "iconic_scenes",
        "scene",
        "protagonist",
        "setting_primary",
        "setting_details",
        "emotional_tone",
        "mood",
        "era",
        "visual_motifs",
        "symbolic_elements",
        "key_characters",
    ):
        value = enrichment.get(key)
        if isinstance(value, list):
            if any(_is_generic_enrichment_text(item) for item in value):
                placeholder_hits = True
                break
        elif _is_generic_enrichment_text(value):
            placeholder_hits = True
            break
    has_specific_data = any(
        (
            bool(_filtered_enrichment_scenes(enrichment)),
            bool(_specific_protagonist(enrichment)),
            bool(_specific_enrichment_text(enrichment.get("setting_primary", ""), min_length=8)),
            bool(_specific_enrichment_list(enrichment.get("visual_motifs", []), min_length=3)),
            bool(_specific_enrichment_list(enrichment.get("symbolic_elements", []), min_length=3)),
        )
    )
    return bool(placeholder_hits and not has_specific_data)


def _scene_pool_for_book(book: dict[str, Any], *, count: int = 1) -> list[str]:
    total = max(1, int(count or 1))
    enrichment = book.get("enrichment", {}) if isinstance(book.get("enrichment"), dict) else {}
    prompt_components = book.get("prompt_components", {}) if isinstance(book.get("prompt_components"), dict) else {}
    pool: list[str] = []
    seen: set[str] = set()
    generic_enrichment = _is_generic_enrichment(enrichment)
    motif_scene = _motif_scene_for_book(book)

    def _push_unique(value: Any) -> None:
        trimmed = _clean_enrichment_text(value)
        if not trimmed or len(trimmed) < 20 or _GENERIC_SCENE_FALLBACK_PATTERN.search(trimmed):
            return
        token = trimmed.lower()
        if token in seen:
            return
        seen.add(token)
        pool.append(trimmed)

    if generic_enrichment and motif_scene:
        _push_unique(motif_scene)

    for scene in _filtered_enrichment_scenes(enrichment):
        _push_unique(scene)

    protagonist = _specific_protagonist(enrichment, book)
    setting_primary = _specific_enrichment_text(enrichment.get("setting_primary", ""), min_length=8)
    raw_setting_details = enrichment.get("setting_details", "")
    if isinstance(raw_setting_details, list):
        detail_parts: list[str] = []
        for item in raw_setting_details:
            detail = _specific_enrichment_text(item, min_length=3)
            if detail:
                detail_parts.append(detail)
        setting_details = ", ".join(detail_parts)
    else:
        setting_details = _specific_enrichment_text(raw_setting_details, min_length=3)

    if protagonist:
        _push_unique(
            f"{protagonist} in a pivotal moment"
            f"{f' set in {setting_primary}' if setting_primary else ' from the story'}"
        )
    if setting_primary:
        _push_unique(
            f"{setting_primary}{f', {setting_details}' if setting_details else ''} — "
            "establishing atmosphere of the story's world"
        )

    motifs = _specific_enrichment_list(enrichment.get("visual_motifs", []), min_length=3)
    symbols = _specific_enrichment_list(enrichment.get("symbolic_elements", []), min_length=3)
    symbolic_pool = [*motifs, *symbols][:4]
    if len(symbolic_pool) >= 2:
        _push_unique(f"symbolic arrangement of {', '.join(symbolic_pool)} — visual metaphor for the story's themes")

    character_pool = _specific_enrichment_list(enrichment.get("key_characters", []), min_length=3)
    if len(character_pool) >= 2:
        _push_unique(f"{', '.join(character_pool[:3])} — a dramatic ensemble scene from the story")

    title_keywords = prompt_components.get("title_keywords", []) if isinstance(prompt_components.get("title_keywords"), list) else []
    keywords = [str(item or "").strip() for item in title_keywords if str(item or "").strip()]
    title = str(book.get("title", "the story") or "the story").strip()
    if keywords:
        _push_unique(f"narrative tableau shaped by {', '.join(keywords[:3])} — a defining moment from {title}")
        if len(keywords) >= 2:
            _push_unique(f"setting-focused scene built around {' and '.join(keywords[-2:])} with period atmosphere")
        if len(keywords) >= 3:
            _push_unique(f"symbolic arrangement of {', '.join(keywords[:4])} — thematic emblem for {title}")

    if not pool and motif_scene:
        _push_unique(motif_scene)
    if not pool:
        _push_unique(f'a scene from "{title}"')

    variation_prefixes = [
        "",
        "intimate close-up view of ",
        "wide panoramic establishing shot of ",
        "dramatic chiaroscuro lighting on ",
        "serene contemplative depiction of ",
        "dynamic action-filled moment of ",
    ]
    results: list[str] = []
    for index in range(total):
        if index < len(pool):
            results.append(pool[index])
            continue
        base_scene = pool[index % len(pool)] if pool else ""
        prefix = variation_prefixes[(index // max(1, len(pool))) % len(variation_prefixes)] if pool else ""
        results.append(f"{prefix}{base_scene}".strip())
    return [scene for scene in results if scene]


def _scene_for_book_variant(
    book: dict[str, Any],
    *,
    variant_index: int = 0,
    scene_override: str = "",
) -> str:
    override = re.sub(r"\s+", " ", str(scene_override or "")).strip()
    if override:
        return override
    pool = _scene_pool_for_book(book, count=max(1, int(variant_index) + 1))
    if not pool:
        return ""
    clamped_index = max(0, int(variant_index))
    return str(pool[clamped_index if clamped_index < len(pool) else 0] or "").strip()


def _alexandria_placeholder_replacements(
    book: dict[str, Any],
    *,
    variant_index: int = 0,
    scene_override: str = "",
) -> dict[str, str]:
    enrichment = book.get("enrichment", {}) if isinstance(book.get("enrichment"), dict) else {}
    title = str(book.get("title", "") or "").strip()
    author = str(book.get("author", "") or "").strip()
    subtitle = str(book.get("subtitle", "") or "").strip()
    protagonist = _specific_protagonist(enrichment, book)
    setting_primary = _specific_enrichment_text(
        enrichment.get("setting_primary", "") or book.get("setting_primary", "") or "",
        min_length=8,
    )
    raw_setting_details = enrichment.get("setting_details", "")
    if isinstance(raw_setting_details, list):
        detail_parts: list[str] = []
        for item in raw_setting_details:
            detail = _specific_enrichment_text(item, min_length=3)
            if detail:
                detail_parts.append(detail)
        setting_details = ", ".join(detail_parts)
    else:
        setting_details = _specific_enrichment_text(raw_setting_details, min_length=3)
    emotional_tone = _specific_enrichment_text(
        enrichment.get("emotional_tone", "")
        or enrichment.get("mood", "")
        or book.get("mood", "")
        or "",
        min_length=6,
    )
    era = _specific_era_text(enrichment.get("era", "") or book.get("era", "") or "")

    first_scene = _scene_for_book_variant(book, variant_index=variant_index, scene_override=scene_override)
    motif_scene = _motif_scene_for_book(book)
    motifs = _specific_enrichment_list(enrichment.get("visual_motifs", []), min_length=3)
    motif_text = ", ".join(motifs)

    if not first_scene:
        if motif_scene:
            first_scene = motif_scene
        elif protagonist and setting_primary:
            first_scene = f"{protagonist} in {setting_primary}"
            if setting_details:
                first_scene = f"{first_scene}, {setting_details}"
        elif protagonist and motif_text:
            first_scene = f"{protagonist} surrounded by {motif_text}"
        elif setting_primary and motif_text:
            first_scene = f"a defining moment in {setting_primary} with {motif_text}"
        elif setting_primary:
            first_scene = f"a defining moment in {setting_primary}"
        elif protagonist:
            label = title or "the story"
            first_scene = f"{protagonist} in a pivotal moment from \"{label}\""
        elif motif_text:
            label = title or "the story"
            first_scene = f"a defining image from \"{label}\" featuring {motif_text}"
        else:
            label = title or "the story"
            first_scene = f"a scene from \"{label}\""

    first_scene = _append_protagonist_to_scene(first_scene, protagonist)

    return {
        "SCENE": first_scene,
        "MOOD": emotional_tone or "dramatic, atmospheric",
        "ERA": era or "historically appropriate to the source text",
        "TITLE": title,
        "AUTHOR": author,
        "SUBTITLE": subtitle,
    }


def _resolve_alexandria_placeholders(
    prompt_text: str,
    book: dict[str, Any],
    *,
    variant_index: int = 0,
    scene_override: str = "",
) -> str:
    text = str(prompt_text or "").strip()
    if not text:
        return ""
    if not _PLACEHOLDER_PATTERN.search(text):
        return text
    replacements = _alexandria_placeholder_replacements(
        book,
        variant_index=variant_index,
        scene_override=scene_override,
    )

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).upper()
        return replacements.get(key, "")

    return _PLACEHOLDER_PATTERN.sub(_replace, text).strip()


def _sanitize_prompt_placeholders(
    prompt: str,
    book: dict[str, Any],
    *,
    variant_index: int = 0,
    scene_override: str = "",
) -> str:
    text = str(prompt or "").strip()
    if not text:
        return ""
    if not _PLACEHOLDER_PATTERN.search(text):
        return text
    replacements = _alexandria_placeholder_replacements(
        book,
        variant_index=variant_index,
        scene_override=scene_override,
    )

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).upper()
        logger.warning(
            "Sanitized unresolved placeholder {%s} in prompt for book '%s'",
            key,
            str(book.get("title", "?") or "?"),
        )
        return replacements.get(key, "")

    return _PLACEHOLDER_PATTERN.sub(_replace, text).strip()


def _validate_prompt_before_generation(prompt: str, book: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate final prompts before sending them to the image model."""
    text = str(prompt or "").strip()
    warnings: list[str] = []
    lowered = text.lower()
    for placeholder in ("{SCENE}", "{MOOD}", "{ERA}", "{title}", "{author}"):
        if placeholder.lower() in lowered:
            warnings.append(f"Unresolved placeholder: {placeholder}")
    first_300 = lowered[:300]
    generic_marker = next(
        (marker for marker in _PROMPT_VALIDATION_GENERIC_MARKERS if marker and marker in first_300),
        "",
    )
    if generic_marker:
        warnings.append(f"Generic content: '{generic_marker}'")
    if not any(needle in first_300 for needle in ("scene:", "must depict", "illustration must")):
        warnings.append("Scene content does not appear in first 300 characters")
    if len(text) < 200:
        warnings.append(f"Prompt too short ({len(text)} chars)")
    if warnings:
        logger.warning(
            "Prompt validation warnings for '%s': %s",
            str(book.get("title", "Unknown") or "Unknown"),
            warnings,
        )
    return (len(warnings) == 0, warnings)


def _ensure_enriched_prompt(
    prompt: str,
    book: dict[str, Any],
    *,
    variant_index: int = 0,
    scene_override: str = "",
) -> str:
    """Ensure the final prompt carries concrete book-specific enrichment."""
    text = str(prompt or "").strip()
    enrichment = book.get("enrichment", {}) if isinstance(book.get("enrichment"), dict) else {}
    protagonist = _specific_protagonist(enrichment, book)
    populated_scenes = [_append_protagonist_to_scene(scene, protagonist) for scene in _filtered_enrichment_scenes(enrichment)]
    first_scene = _append_protagonist_to_scene(
        _scene_for_book_variant(book, variant_index=variant_index, scene_override=scene_override),
        protagonist,
    )
    scene_sentence = first_scene.rstrip(" .!?")
    setting = _specific_enrichment_text(enrichment.get("setting_primary", ""), min_length=8)
    emotional_tone = _specific_enrichment_text(enrichment.get("emotional_tone", "") or enrichment.get("mood", ""), min_length=6)
    era = _specific_era_text(enrichment.get("era", ""))

    if emotional_tone and text:
        text = _GENERIC_MOOD_PATTERN.sub(emotional_tone, text)
    if not first_scene:
        return text

    result = _GENERIC_SCENE_PATTERN.sub(first_scene, text)
    lowered = result.lower()
    scene_present = bool(first_scene[:30].strip()) and first_scene[:30].lower() in lowered
    if not scene_present and populated_scenes:
        scene_present = any(scene[:30].lower() in lowered for scene in populated_scenes[:3] if scene[:30].strip())
    if not scene_present:
        enrichment_sentences = [f"The illustration must depict: {scene_sentence or first_scene}."]
        if protagonist and protagonist.lower() not in first_scene.lower():
            enrichment_sentences.append(f"Character: {protagonist}.")
        if setting:
            enrichment_sentences.append(f"Setting: {setting}.")
        if emotional_tone:
            enrichment_sentences.append(f"Mood: {emotional_tone}.")
        if era:
            enrichment_sentences.append(f"Era: {era}.")
        prefix = result.rstrip()
        if prefix and prefix[-1] not in ".!?":
            prefix = f"{prefix}."
        result = " ".join(part for part in [prefix, *enrichment_sentences] if part).strip()

    if emotional_tone and result:
        result = _GENERIC_MOOD_PATTERN.sub(emotional_tone, result)
    return result.strip()


def _should_use_resolved_frontend_prompt(
    prompt: str,
    *,
    compose_prompt: bool,
    preserve_prompt_text: bool,
) -> bool:
    """Trust fully resolved frontend prompts instead of rebuilding scenes server-side."""
    normalized = " ".join(str(prompt or "").split()).strip()
    if not normalized or compose_prompt:
        return False
    if _PLACEHOLDER_PATTERN.search(normalized):
        return False
    if preserve_prompt_text:
        return True
    lowered = normalized[:320].lower()
    has_scene_anchor = any(token in lowered for token in ("scene:", "must depict", "illustration must"))
    generic_marker = next(
        (marker for marker in _PROMPT_VALIDATION_GENERIC_MARKERS if marker and marker in lowered),
        "",
    )
    return len(normalized) >= 100 and has_scene_anchor and not generic_marker


def _compose_prompt_for_book(
    *,
    runtime: config.Config,
    book: dict[str, Any],
    base_prompt: str,
    template_id: str = "",
    variant_index: int = 0,
    scene_override: str = "",
) -> dict[str, Any]:
    prompts = _genre_prompt_payload(runtime=runtime)
    enrichment = book.get("enrichment", {}) if isinstance(book.get("enrichment"), dict) else {}
    inferred = genre_intelligence.infer_genre(
        title=str(book.get("title", "")),
        author=str(book.get("author", "")),
        metadata_genre=str(enrichment.get("genre", "") or book.get("genre", "")),
        prompts=prompts,
    )
    inferred_genre = str(inferred.get("genre", "literary_fiction") or "literary_fiction")
    templates = _template_rows_for_runtime(runtime=runtime)
    selected_template = None
    requested_template = str(template_id or "").strip()
    if requested_template:
        selected_template = _template_for_id(runtime=runtime, template_id=requested_template)
        if selected_template is None:
            raise ValueError(f"Unknown template_id: {requested_template}")
    if selected_template is None:
        selected_template = _template_for_genre(runtime=runtime, genre=inferred_genre)
    if selected_template is None and templates:
        selected_template = templates[0]

    positive, negative = genre_intelligence.genre_modifiers_for(inferred_genre, prompts=prompts)
    keywords = genre_intelligence.extract_title_keywords(title=str(book.get("title", "")), limit=6)
    constrained_base = prompt_generator.enforce_prompt_constraints(str(base_prompt or "").strip())
    composed = genre_intelligence.compose_prompt(
        base_style_prompt=constrained_base,
        template_modifier=str((selected_template or {}).get("prompt_modifier", "")).strip(),
        genre_modifier=positive,
        title_keywords=keywords,
        negative_prompt=(
            "text, letters, words, typography, logos, labels, watermark, signature, "
            "frame, border, decorative edge, ornamental border, ribbon banner, plaque, "
            "filigree, scrollwork, arabesque, ornamental curls, decorative flourishes, "
            "black ornamental silhouettes, lace-like cutout motifs"
        ),
        genre_negative_modifier=negative,
    )
    resolved_prompt = _resolve_alexandria_placeholders(
        str(composed.get("prompt", "")).strip(),
        book,
        variant_index=variant_index,
        scene_override=scene_override,
    )
    constrained_prompt = prompt_generator.enforce_prompt_constraints(resolved_prompt)
    composed["prompt"] = _ensure_enriched_prompt(
        constrained_prompt,
        book,
        variant_index=variant_index,
        scene_override=scene_override,
    )
    composed["genre_modifier"] = composed.get("genre", "")
    composed["genre"] = inferred_genre
    composed["genre_source"] = str(inferred.get("source", "default"))
    composed["genre_keywords"] = inferred.get("matched_keywords", [])
    composed["template_id"] = str((selected_template or {}).get("id", "")).strip()
    composed["template_name"] = str((selected_template or {}).get("name", "")).strip()
    return composed


_MODEL_LABEL_OVERRIDES: dict[str, str] = {
    "nano-banana-pro": "Nano Banana Pro",
    "openrouter/google/gemini-3-pro-image-preview": "Nano Banana Pro",
    "openrouter/google/gemini-2.5-flash-image": "Nano Banana (Gemini 2.5 Flash)",
    "google/gemini-3-pro-image-preview": "Nano Banana Pro (Google Direct)",
    "google/gemini-2.5-flash-image": "Gemini 2.5 Flash (Google Direct)",
}


def _friendly_model_label(model: str) -> str:
    token = str(model or "").strip()
    if not token:
        return "Model"
    override = _MODEL_LABEL_OVERRIDES.get(token)
    if override:
        return override
    leaf = token.split("/")[-1].strip() or token
    normalized = " ".join(part for part in leaf.replace("-", " ").replace("_", " ").replace(".", " ").split() if part)
    if not normalized:
        return token
    words: list[str] = []
    for part in normalized.split():
        lower = part.lower()
        if lower in {"ai", "gpt"}:
            words.append(lower.upper())
        elif lower.isdigit():
            words.append(lower)
        else:
            words.append(lower.capitalize())
    return " ".join(words) or token


def _recent_generation_failures_payload(*, runtime: config.Config, limit: int = 20) -> dict[str, Any]:
    target_limit = max(1, min(200, int(limit)))
    jobs = job_db_store.list_jobs(
        limit=max(50, target_limit * 5),
        statuses=["failed", "retrying"],
        catalog_id=runtime.catalog_id,
    )
    rows: list[dict[str, Any]] = []
    for job in jobs:
        if str(job.job_type or "").strip().lower() != "generate_cover":
            continue
        job_error = job.error if isinstance(job.error, dict) else {}
        attempts = job_db_store.list_attempts(job.id)
        latest_attempt = attempts[-1] if attempts else None
        latest_meta = latest_attempt.get("meta", {}) if isinstance(latest_attempt, dict) and isinstance(latest_attempt.get("meta"), dict) else {}
        failure_rows = job_error.get("failures", []) if isinstance(job_error.get("failures"), list) else []
        if not failure_rows and isinstance(latest_meta.get("failures"), list):
            failure_rows = latest_meta.get("failures", [])
        payload_models = job.payload.get("models", []) if isinstance(job.payload, dict) and isinstance(job.payload.get("models"), list) else []
        rows.append(
            {
                "job_id": str(job.id),
                "book_number": int(job.book_number or 0),
                "status": str(job.status or "").strip().lower(),
                "attempts": int(job.attempts or 0),
                "max_attempts": int(job.max_attempts or 0),
                "created_at": str(job.created_at or ""),
                "updated_at": str(job.updated_at or ""),
                "stage": str(job_error.get("stage", latest_meta.get("stage", ""))).strip(),
                "error": str(job_error.get("message", "") or (latest_attempt or {}).get("error_text", "")).strip(),
                "error_type": str(job_error.get("type", "") or latest_meta.get("error_type", "")).strip(),
                "models": [str(item).strip() for item in payload_models if str(item).strip()],
                "provider": str((job.payload or {}).get("provider", "")).strip().lower() if isinstance(job.payload, dict) else "",
                "failures": [row for row in failure_rows if isinstance(row, dict)],
                "latest_attempt": latest_attempt if isinstance(latest_attempt, dict) else None,
            }
        )
        if len(rows) >= target_limit:
            break
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "failures": rows,
        "count": len(rows),
    }


def _api_models_payload(*, runtime: config.Config) -> dict[str, Any]:
    quality_payload = _quality_by_model_payload(runtime=runtime)
    rows = quality_payload.get("models", []) if isinstance(quality_payload, dict) else []
    stats_by_model: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            token = str(row.get("model", "")).strip()
            if token:
                stats_by_model[token] = row

    active_models = [str(item).strip() for item in runtime.all_models if str(item).strip()]
    known_models = list(active_models)
    for key in runtime.model_provider_map.keys():
        token = str(key).strip()
        if not token or token in known_models:
            continue
        if "/" not in token:
            continue
        known_models.append(token)
    extras = sorted({token for token in known_models if token not in active_models})
    known_models = [*active_models, *extras]
    active_set = set(active_models)

    out: list[dict[str, Any]] = []
    for sort_order, model in enumerate(known_models):
        stats = stats_by_model.get(model, {})
        provider = str(stats.get("provider", runtime.resolve_model_provider(model))).strip() or runtime.resolve_model_provider(model)
        count = _safe_int(stats.get("count"), 0)
        failure_rate_percent = _safe_float(stats.get("failure_rate_percent"), 0.0)
        success_rate = max(0.0, min(1.0, 1.0 - (failure_rate_percent / 100.0 if count > 0 else 0.0)))
        runtime_cost = round(_safe_float(runtime.get_model_cost(model), 0.04), 6)
        historical_cost = round(_safe_float(stats.get("avg_cost_per_variant"), 0.0), 6)
        model_cost = historical_cost if count > 0 and historical_cost > 0 else runtime_cost
        out.append(
            {
                "id": model,
                "label": _friendly_model_label(model),
                "provider": provider,
                "status": "active" if model in active_set else "disabled",
                "sort_order": int(sort_order),
                "cost_per_image": model_cost,
                "avg_cost_usd": model_cost,
                "modality": runtime.get_model_modality(model),
                "avg_generation_time_s": round(_safe_float(stats.get("avg_generation_time_seconds"), 0.0), 4),
                "success_rate": round(success_rate, 6),
                "total_generations": int(count),
            }
        )
    return {"models": out, "total": len(out)}


def _api_providers_payload(*, runtime: config.Config) -> dict[str, Any]:
    runtime_rows = _provider_runtime_payload(runtime=runtime)
    records = _load_generation_records(runtime=runtime)
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    count_by_provider: dict[str, dict[str, int]] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        provider = str(row.get("provider", "")).strip().lower()
        if not provider:
            provider = runtime.resolve_model_provider(str(row.get("model", "")))
        ts = _safe_iso_datetime(str(row.get("timestamp", "")))
        if ts and ts < since:
            continue
        bucket = count_by_provider.setdefault(provider, {"requests": 0, "errors": 0})
        bucket["requests"] += 1
        status_token = str(row.get("status", "")).strip().lower()
        if status_token:
            failed = status_token not in {"success", "completed"}
        else:
            failed = not bool(row.get("success", True))
        if failed:
            bucket["errors"] += 1

    rows: list[dict[str, Any]] = []
    for provider in sorted(set(list(runtime.provider_keys.keys()) + list(runtime_rows.keys()))):
        runtime_row = runtime_rows.get(provider, {})
        model_list = [model for model in runtime.all_models if runtime.resolve_model_provider(model) == provider]
        counts = count_by_provider.get(provider, {})
        rows.append(
            {
                "name": provider,
                "status": str(runtime_row.get("status", "inactive")),
                "circuit_breaker": str(runtime_row.get("circuit_state", "closed")),
                "error_count_24h": int(counts.get("errors", runtime_row.get("errors_today", 0) or 0)),
                "request_count_24h": int(counts.get("requests", runtime_row.get("requests_today", 0) or 0)),
                "models": model_list,
            }
        )
    return {"providers": rows}


def _api_catalog_payload(*, runtime: config.Config) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total_books = 0
    for item in catalog_registry.list_catalogs():
        stats = catalog_registry.stats_for_catalog(item.catalog_id)
        book_count = _safe_int(stats.get("book_count", item.book_count), item.book_count)
        rows.append(
            {
                "name": item.catalog_id,
                "book_count": book_count,
                "covers_generated": _safe_int(stats.get("processed_count"), 0),
                "winners_selected": _safe_int(stats.get("winner_count"), 0),
            }
        )
        total_books += max(0, int(book_count))
    rows.sort(key=lambda row: str(row.get("name", "")))
    return {"catalogs": rows, "total_books": int(total_books), "active_catalog": runtime.catalog_id}


def _api_templates_payload(*, runtime: config.Config, genre: str = "") -> dict[str, Any]:
    rows = _template_rows_for_runtime(runtime=runtime, genre=genre)
    return {
        "templates": rows,
        "total": len(rows),
        "genre_filter": str(genre or "").strip().lower() or None,
    }


def _api_stats_payload(*, runtime: config.Config) -> dict[str, Any]:
    records = _load_generation_records(runtime=runtime)
    total_generations = len(records)
    total_cost_usd = round(sum(_safe_float(row.get("cost"), 0.0) for row in records if isinstance(row, dict)), 6)
    budget_status = _budget_status_for_runtime(runtime)
    avg_generation_time = (
        round(
            sum(
                _safe_float(
                    row.get("generation_time", row.get("duration", 0.0)),
                    0.0,
                )
                for row in records
                if isinstance(row, dict)
            )
            / max(1, total_generations),
            4,
        )
        if total_generations
        else 0.0
    )
    avg_quality = (
        round(
            sum(_safe_float(row.get("quality_score"), 0.0) for row in records if isinstance(row, dict)) / max(1, total_generations),
            6,
        )
        if total_generations
        else 0.0
    )
    models_used: dict[str, int] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model", "")).strip()
        if not model:
            continue
        models_used[model] = models_used.get(model, 0) + 1

    model_compare = _quality_by_model_payload(runtime=runtime)
    top_rated = str(model_compare.get("recommended_model", "")).strip() if isinstance(model_compare, dict) else ""
    return {
        "total_generations": int(total_generations),
        "total_cost_usd": total_cost_usd,
        "budget_remaining_usd": round(_safe_float(budget_status.get("remaining_usd"), runtime.max_cost_usd), 6),
        "budget_limit_usd": round(_safe_float(budget_status.get("limit_usd"), runtime.max_cost_usd), 6),
        "avg_generation_time_s": avg_generation_time,
        "avg_quality_score": avg_quality,
        "models_used": models_used,
        "top_rated_model": top_rated or None,
    }


def _api_config_payload(*, runtime: config.Config) -> dict[str, Any]:
    provider_runtime = _provider_runtime_payload(runtime=runtime)
    provider_status = {
        provider: {
            "status": str(row.get("status", "inactive")),
            "models": [model for model in runtime.all_models if runtime.resolve_model_provider(model) == provider],
        }
        for provider, row in provider_runtime.items()
    }
    return {
        "catalog": runtime.catalog_id,
        "active_models": runtime.all_models,
        "providers": provider_status,
        "budget": {
            "max_cost_usd": float(runtime.max_cost_usd),
            "state": _budget_status_for_runtime(runtime).get("state", "ok"),
        },
        "quality_thresholds": {
            "min_quality_score": float(runtime.min_quality_score),
            "composite_max_invalid_variants": int(runtime.composite_max_invalid_variants),
        },
        "drive": {
            "connected": bool(runtime.gdrive_source_folder_id and runtime.gdrive_output_folder_id),
            "source_folder_id": bool(str(runtime.gdrive_source_folder_id).strip()),
            "output_folder_id": bool(str(runtime.gdrive_output_folder_id).strip()),
            "default_cover_source": _default_cover_source_for_runtime(runtime),
        },
        "worker": _worker_runtime_status(),
        "feature_flags": {
            "sync_generation_allowed": _sync_generation_allowed(),
            "use_sqlite": bool(runtime.use_sqlite),
            "enrichment_enabled": True,
            "template_registry_enabled": True,
            "print_validation_enabled": True,
            "genre_intelligence_enabled": True,
            "budget_presets_enabled": True,
        },
    }


def _attach_print_validation_to_rows(*, runtime: config.Config, rows: list[dict[str, Any]]) -> None:
    validator = _print_validator_instance()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not bool(row.get("success", True)):
            continue
        composited_token = str(row.get("composited_path", "") or "").strip()
        image_token = str(row.get("image_path", "") or "").strip()
        source_path = _project_path_if_exists(composited_token) or _project_path_if_exists(image_token)
        if source_path is None:
            continue
        try:
            with Image.open(source_path) as image:
                validation = validator.validate_for_all_distributors(image, [], source_path)
            summary = {
                "passed_all": all(bool(item.get("passed")) for item in validation.values()),
                "errors_total": sum(len(item.get("errors", [])) for item in validation.values()),
                "warnings_total": sum(len(item.get("warnings", [])) for item in validation.values()),
            }
            row["print_validation"] = validation
            row["print_validation_summary"] = summary
        except Exception as exc:
            row["print_validation"] = {
                "error": str(exc),
            }
            row["print_validation_summary"] = {
                "passed_all": False,
                "errors_total": 1,
                "warnings_total": 0,
            }


def _ab_tests_path_for_runtime(runtime: config.Config) -> Path:
    return runtime.data_dir / ("ab_tests.json" if runtime.catalog_id == config.DEFAULT_CATALOG_ID else f"ab_tests_{runtime.catalog_id}.json")


def _load_ab_test_rows(*, runtime: config.Config) -> list[dict[str, Any]]:
    payload = _load_json(_ab_tests_path_for_runtime(runtime), {"items": []})
    rows = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _record_ab_test(*, runtime: config.Config, body: dict[str, Any]) -> dict[str, Any]:
    rows = _load_ab_test_rows(runtime=runtime)
    compared = body.get("models_compared", [])
    if not isinstance(compared, list):
        compared = []
    quality_scores = body.get("quality_scores", {})
    if not isinstance(quality_scores, dict):
        quality_scores = {}
    row = {
        "id": str(uuid.uuid4()),
        "catalog": runtime.catalog_id,
        "book_id": _safe_int(body.get("book_id"), 0),
        "models_compared": [str(item).strip() for item in compared if str(item).strip()],
        "winner": str(body.get("winner", "")).strip(),
        "quality_scores": {str(key): _safe_float(value, 0.0) for key, value in quality_scores.items()},
        "user_comment": str(body.get("user_comment", "")).strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    rows.append(row)
    rows = rows[-5000:]
    safe_json.atomic_write_json(_ab_tests_path_for_runtime(runtime), {"updated_at": datetime.now(timezone.utc).isoformat(), "items": rows})
    return {"ok": True, "item": row, "count": len(rows)}


def _prompt_library_payload(
    *,
    runtime: config.Config,
    query_text: str = "",
    category: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    prompts = library.search_prompts(query=query_text, tags=tags or [], min_quality=0.0)
    rows: list[dict[str, Any]] = []
    for prompt in prompts:
        payload = asdict(prompt)
        if category and str(payload.get("category", "")).strip().lower() != category:
            continue
        usage = _safe_int(payload.get("usage_count"), 0)
        wins = _safe_int(payload.get("win_count"), 0)
        payload["win_rate_percent"] = round((wins / usage) * 100.0, 3) if usage > 0 else 0.0
        payload["versions_count"] = len(library.get_versions(prompt.id))
        payload["best_model_pairing"] = str(payload.get("source_model", "")).strip() or "unknown"
        rows.append(payload)
    rows.sort(
        key=lambda item: (
            1 if "alexandria" in {str(tag).strip().lower() for tag in item.get("tags", []) if str(tag).strip()} else 0,
            1 if str(item.get("category", "")).strip().lower() == "builtin" else 0,
            _safe_float(item.get("quality_score"), 0.0),
            _safe_int(item.get("win_count"), 0),
            _safe_int(item.get("usage_count"), 0),
            str(item.get("created_at", "")),
        ),
        reverse=True,
    )
    return {"ok": True, "catalog": runtime.catalog_id, "prompts": rows, "count": len(rows)}


def _prompt_library_export_payload(*, runtime: config.Config) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    payload = {
        "ok": True,
        "catalog": runtime.catalog_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "style_anchors": [asdict(anchor) for anchor in library.get_style_anchors()],
        "prompts": [asdict(prompt) for prompt in library.get_prompts()],
        "versions": {prompt.id: library.get_versions(prompt.id) for prompt in library.get_prompts()},
    }
    return payload


def _prompt_versions_payload(*, runtime: config.Config, prompt_id: str) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    prompt = library.get_prompt(prompt_id)
    if prompt is None:
        raise KeyError(prompt_id)
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "prompt": asdict(prompt),
        "versions": library.get_versions(prompt_id),
    }


def _prompt_slug_token(value: str, *, fallback: str = "prompt") -> str:
    token = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return token or fallback


def _save_prompt_from_request(*, runtime: config.Config, body: dict[str, Any]) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    prompt_text = " ".join(str(body.get("prompt_text", body.get("prompt_template", "")) or "").split()).strip()
    if not prompt_text:
        raise ValueError("prompt_text is required")

    existing = library.find_prompt_by_template_text(prompt_text)
    if existing is not None:
        return {
            "ok": True,
            "already_exists": True,
            "prompt_id": existing.id,
            "message": "Prompt already exists in library",
            "prompt": asdict(existing),
        }

    book_id = _safe_int(body.get("book_id"), 0)
    book = _book_row_for_number(runtime=runtime, book_number=book_id) if book_id > 0 else None
    title = str((book or {}).get("title", f"Book {book_id or 'Unknown'}")).strip()
    author = str((book or {}).get("author", "Unknown")).strip()
    source_book = f"{title} — {author}".strip(" —")

    model_id = str(body.get("model_id", body.get("source_model", "")) or "").strip() or "manual"
    library_prompt_id = str(body.get("library_prompt_id", "") or "").strip()
    source_prompt = library.get_prompt(library_prompt_id) if library_prompt_id else None
    source_prompt_name = str(source_prompt.name if source_prompt is not None else body.get("prompt_name", "")).strip()
    source_prompt_slug = _prompt_slug_token(source_prompt_name or library_prompt_id or "manual")
    negative_prompt = str(body.get("negative_prompt", "") or "").strip()
    if not negative_prompt and source_prompt is not None:
        negative_prompt = str(source_prompt.negative_prompt or "").strip()
    if not negative_prompt and prompt_text.startswith("Book cover illustration only"):
        negative_prompt = image_generator.ALEXANDRIA_NEGATIVE_PROMPT

    scene_description = str(body.get("scene_description", "") or "").strip()
    mood = str(body.get("mood", "") or "").strip()
    era = str(body.get("era", "") or "").strip()
    notes = str(body.get("notes", "") or "").strip()
    note_parts = [notes] if notes else []
    if scene_description:
        note_parts.append(f"Scene: {scene_description}")
    if mood:
        note_parts.append(f"Mood: {mood}")
    if era:
        note_parts.append(f"Era: {era}")
    job_id = str(body.get("job_id", "") or "").strip()
    if job_id:
        note_parts.append(f"Job: {job_id}")
    notes_text = " | ".join(part for part in note_parts if part).strip()

    prompt = LibraryPrompt(
        id=str(uuid.uuid4()),
        name=f"Winner — {title} — {source_prompt_name or model_id}",
        prompt_template=prompt_text,
        style_anchors=[],
        negative_prompt=negative_prompt,
        source_book=source_book,
        source_model=model_id,
        quality_score=_safe_float(body.get("quality_score"), 0.0),
        saved_by="user",
        created_at=datetime.now(timezone.utc).isoformat(),
        notes=notes_text or "saved from iterate winner",
        tags=["winner", _prompt_slug_token(title, fallback="book"), source_prompt_slug],
        category="winner",
        usage_count=0,
        win_count=1,
    )
    library.save_prompt(prompt)
    saved_prompt = library.get_prompt(prompt.id)
    saved_prompt_payload = asdict(saved_prompt or prompt)
    drive_url = ""
    drive_warning = ""
    try:
        drive_url = _upload_saved_prompt_metadata_to_drive(
            runtime=runtime,
            prompt_payload=saved_prompt_payload,
            prompt_id=prompt.id,
        )
    except Exception as exc:
        drive_warning = f"Drive upload failed: {exc}"
        logger.warning(drive_warning)
    return {
        "ok": True,
        "already_exists": False,
        "prompt_id": prompt.id,
        "message": "Prompt saved to library",
        "prompt": saved_prompt_payload,
        "drive_url": drive_url or None,
        "drive_warning": drive_warning or None,
    }


def _create_prompt_from_request(*, runtime: config.Config, body: dict[str, Any]) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    prompt = LibraryPrompt(
        id=str(uuid.uuid4()),
        name=str(body.get("name", "Saved Prompt") or "Saved Prompt"),
        prompt_template=str(body.get("prompt_template", "{title}") or "{title}"),
        style_anchors=list(body.get("style_anchors", [])) if isinstance(body.get("style_anchors", []), list) else [],
        negative_prompt=str(body.get("negative_prompt", "")),
        source_book=str(body.get("source_book", "iteration")),
        source_model=str(body.get("source_model", body.get("model", "manual"))),
        quality_score=_safe_float(body.get("quality_score"), 0.75),
        saved_by=str(body.get("saved_by", "tim")),
        created_at=datetime.now(timezone.utc).isoformat(),
        notes=str(body.get("notes", "saved from iterate page")),
        tags=list(body.get("tags", [])) if isinstance(body.get("tags", []), list) else ["iterative"],
        category=str(body.get("category", "general") or "general"),
    )
    library.save_prompt(prompt)
    return {"ok": True, "prompt": asdict(library.get_prompt(prompt.id)), "prompt_id": prompt.id}


def _update_prompt_from_request(*, runtime: config.Config, prompt_id: str, body: dict[str, Any]) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    updates: dict[str, object] = {}
    for key in ("name", "prompt_template", "style_anchors", "negative_prompt", "notes", "tags", "category", "quality_score", "source_model"):
        if key in body:
            updates[key] = body.get(key)
    updated = library.update_prompt(prompt_id, **updates)
    return {"ok": True, "prompt": asdict(updated), "versions_count": len(library.get_versions(prompt_id))}


def _delete_prompt(*, runtime: config.Config, prompt_id: str) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    removed = library.delete_prompt(prompt_id)
    if not removed:
        raise KeyError(prompt_id)
    return {"ok": True, "prompt_id": prompt_id, "deleted": True}


def _record_prompt_usage(*, runtime: config.Config, prompt_id: str, won: bool = False) -> dict[str, Any]:
    library = PromptLibrary(runtime.prompt_library_path)
    updated = library.record_usage(prompt_id, won=won)
    return {"ok": True, "prompt": asdict(updated)}


def _import_prompt_payload(*, runtime: config.Config, body: dict[str, Any]) -> dict[str, Any]:
    prompts = body.get("prompts", body.get("items", []))
    if not isinstance(prompts, list):
        raise ValueError("prompts must be a list")
    library = PromptLibrary(runtime.prompt_library_path)
    imported = 0
    for row in prompts:
        if not isinstance(row, dict):
            continue
        template = str(row.get("prompt_template", "")).strip()
        if not template:
            continue
        prompt = LibraryPrompt(
            id=str(row.get("id", "") or str(uuid.uuid4())),
            name=str(row.get("name", "Imported Prompt")),
            prompt_template=template,
            style_anchors=list(row.get("style_anchors", [])) if isinstance(row.get("style_anchors", []), list) else [],
            negative_prompt=str(row.get("negative_prompt", "")),
            source_book=str(row.get("source_book", "import")),
            source_model=str(row.get("source_model", "import")),
            quality_score=_safe_float(row.get("quality_score"), 0.0),
            saved_by=str(row.get("saved_by", "import")),
            created_at=str(row.get("created_at", datetime.now(timezone.utc).isoformat())),
            notes=str(row.get("notes", "imported")),
            tags=list(row.get("tags", [])) if isinstance(row.get("tags", []), list) else [],
            category=str(row.get("category", "general") or "general"),
            usage_count=_safe_int(row.get("usage_count"), 0),
            win_count=_safe_int(row.get("win_count"), 0),
        )
        library.save_prompt(prompt)
        imported += 1
    return {"ok": True, "imported": imported}


def _builtin_prompt_seed_rows() -> list[dict[str, str]]:
    # PROMPT-26 retires the pre-Alexandria built-in prompt set. Keep the seed
    # pathway inert so startup and manual "seed builtins" actions cannot
    # repopulate legacy dropdown entries.
    return []


def _seed_builtin_prompts(*, runtime: config.Config, actor: str = "tim", overwrite: bool = False) -> dict[str, Any]:
    def _has_malformed_constraints(text: str) -> bool:
        token = str(text or "").strip().lower()
        if not token:
            return True
        malformed_patterns = (
            r"\bno\s*,\s*no\b",
            r"\bno\s+no\b",
            r",\s*,",
            r"\bavoid:\s*no\b",
        )
        return any(re.search(pattern, token, flags=re.IGNORECASE) for pattern in malformed_patterns)

    def _builtin_prompt_needs_repair(existing_prompt: LibraryPrompt) -> bool:
        template = str(existing_prompt.prompt_template or "")
        negative = str(existing_prompt.negative_prompt or "")
        if "{title}" not in template:
            return True
        if _has_malformed_constraints(template) or _has_malformed_constraints(negative):
            return True
        joined = f"{template} {negative}".lower()
        if "no text" not in joined:
            return True
        if "no border" not in joined and "no frame" not in joined:
            return True
        return False

    library = PromptLibrary(runtime.prompt_library_path)
    existing = library.get_prompts()
    by_name = {str(row.name).strip().lower(): row for row in existing}
    by_style_tag: dict[str, LibraryPrompt] = {}
    for row in existing:
        tags = [str(tag).strip().lower() for tag in row.tags if str(tag).strip()]
        for tag in tags:
            if tag.startswith("builtin_v2:"):
                by_style_tag[tag.split("builtin_v2:", 1)[1]] = row

    created = 0
    updated = 0
    skipped = 0
    repaired = 0
    now = datetime.now(timezone.utc).isoformat()
    rows = _builtin_prompt_seed_rows()

    for item in rows:
        style_id = str(item.get("style_id", "")).strip().lower()
        name = str(item.get("name", "")).strip()
        if not name or "{title}" not in str(item.get("prompt_template", "")):
            skipped += 1
            continue

        existing_prompt = by_style_tag.get(style_id) or by_name.get(name.lower())
        needs_repair = existing_prompt is not None and _builtin_prompt_needs_repair(existing_prompt)
        if existing_prompt and not overwrite and not needs_repair:
            skipped += 1
            continue
        if existing_prompt is not None and needs_repair and not overwrite:
            repaired += 1

        payload = {
            "name": name,
            "prompt_template": str(item.get("prompt_template", "")),
            "style_anchors": [style_id] if style_id else [],
            "negative_prompt": str(item.get("negative_prompt", "")),
            "notes": "Seeded from Alexandria models/prompt report (v2).",
            "tags": ["builtin", "builtin_v2", f"builtin_v2:{style_id}"] if style_id else ["builtin", "builtin_v2"],
            "category": "builtin",
            "quality_score": 0.82,
            "source_model": "openrouter/google/gemini-3-pro-image-preview",
        }
        if style_id == "sevastopol-conflict":
            payload["tags"].append("builtin_v2:sevastopol-dramatic-conflict")
        if style_id == "cossack-epic":
            payload["tags"].append("builtin_v2:cossack-epic-journey")

        if existing_prompt is None:
            prompt = LibraryPrompt(
                id=str(uuid.uuid4()),
                name=payload["name"],
                prompt_template=payload["prompt_template"],
                style_anchors=payload["style_anchors"],
                negative_prompt=payload["negative_prompt"],
                source_book="builtin",
                source_model=payload["source_model"],
                quality_score=float(payload["quality_score"]),
                saved_by=str(actor or "tim"),
                created_at=now,
                notes=payload["notes"],
                tags=payload["tags"],
                category=payload["category"],
            )
            library.save_prompt(prompt)
            created += 1
            if style_id:
                by_style_tag[style_id] = prompt
            by_name[name.lower()] = prompt
            continue

        library.update_prompt(
            existing_prompt.id,
            name=payload["name"],
            prompt_template=payload["prompt_template"],
            style_anchors=payload["style_anchors"],
            negative_prompt=payload["negative_prompt"],
            notes=payload["notes"],
            tags=payload["tags"],
            category=payload["category"],
            quality_score=float(payload["quality_score"]),
            source_model=payload["source_model"],
            saved_by=str(actor or "tim"),
        )
        updated += 1

    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "total_builtins": len(rows),
        "created": int(created),
        "updated": int(updated),
        "skipped": int(skipped),
        "repaired": int(repaired),
        "overwrite": bool(overwrite),
    }


def _ensure_builtin_prompts_seeded(*, runtime: config.Config, actor: str = "system") -> None:
    """Ensure v2 built-ins are available without requiring a manual seed click."""
    try:
        payload = _seed_builtin_prompts(runtime=runtime, actor=actor, overwrite=False)
        created = int(payload.get("created", 0) or 0)
        updated = int(payload.get("updated", 0) or 0)
        total = int(payload.get("total_builtins", 0) or 0)
        logger.info(
            "Builtin prompt seed ensured",
            extra={
                "catalog": runtime.catalog_id,
                "seed_created": created,
                "seed_updated": updated,
                "total_builtins": total,
            },
        )
    except Exception as exc:  # pragma: no cover - startup best-effort
        logger.warning("Failed to auto-seed built-in prompts: %s", exc)


def _model_recommendation_payload(*, runtime: config.Config, book_number: int | None = None) -> dict[str, Any]:
    rows = _load_generation_records(runtime=runtime)
    if book_number and int(book_number) > 0:
        scoped = [row for row in rows if _safe_int(row.get("book_number"), 0) == int(book_number)]
        if scoped:
            rows = scoped
    if not rows:
        compare = _quality_by_model_payload(runtime=runtime)
        recommendation = str(compare.get("recommended_model", "") or "")
        return {
            "catalog": runtime.catalog_id,
            "book_number": int(book_number or 0),
            "recommended_model": recommendation,
            "reason": "No generation history yet. Using global model comparison.",
            "sample_size": 0,
        }
    buckets: dict[str, dict[str, float]] = {}
    for row in rows:
        model = str(row.get("model", "unknown"))
        entry = buckets.setdefault(model, {"quality_total": 0.0, "cost_total": 0.0, "count": 0.0})
        entry["quality_total"] += _safe_float(row.get("quality_score"), 0.0) * 100.0
        entry["cost_total"] += max(0.000001, _safe_float(row.get("cost"), 0.0))
        entry["count"] += 1.0
    ranked: list[tuple[str, float, float, float]] = []
    for model, stats in buckets.items():
        count = max(1.0, stats["count"])
        avg_quality = stats["quality_total"] / count
        avg_cost = stats["cost_total"] / count
        score = avg_quality / avg_cost if avg_cost > 0 else avg_quality
        ranked.append((model, score, avg_quality, avg_cost))
    ranked.sort(key=lambda item: item[1], reverse=True)
    best = ranked[0] if ranked else ("", 0.0, 0.0, 0.0)
    return {
        "catalog": runtime.catalog_id,
        "book_number": int(book_number or 0),
        "recommended_model": best[0],
        "sample_size": len(rows),
        "avg_quality": round(best[2], 4),
        "avg_cost_per_variant": round(best[3], 6),
        "reason": (
            f"Based on {len(rows)} previous generation result(s), {best[0]} has the best quality-to-cost score "
            f"({best[2]:.1f}/100 quality at ${best[3]:.4f} average cost)."
            if best[0]
            else "No recommendation available."
        ),
    }


def generate_review_gallery(
    output_dir: Path,
    output_path: Path = FALLBACK_HTML_PATH,
    *,
    runtime: config.Config | None = None,
    max_books: int | None = None,
) -> Path:
    """Generate standalone fallback gallery with embedded data + localStorage."""
    runtime = runtime or config.get_config()
    data = {
        "books": build_review_dataset(
            output_dir,
            input_dir=runtime.input_dir,
            catalog_path=runtime.book_catalog_path,
            quality_scores_path=_quality_scores_path_for_runtime(runtime),
            max_books=max_books,
        ),
    }

    html = f"""<!doctype html>
<html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/><title>Review Gallery</title>
<style>
body{{font-family:Georgia,serif;background:#11274d;color:#f7ecd1;margin:0;padding:18px;}}
.grid{{display:grid;gap:14px;}}
.card{{background:#f8f3e5;color:#1b2740;border-radius:14px;padding:12px;}}
.images{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;}}
img{{width:100%;border-radius:8px;}}
</style></head><body>
<h1>Standalone Review Gallery</h1>
<button onclick='download()'>Export Selections JSON</button>
<div id='grid' class='grid'></div>
<script>
const data = {json.dumps(data, ensure_ascii=False)};
const selections = JSON.parse(localStorage.getItem('variantSelections') || '{{}}');
function render(){{
  const root=document.getElementById('grid');
  root.innerHTML='';
  data.books.forEach(book=>{{
    const card=document.createElement('section');
    card.className='card';
    card.innerHTML=`<h2>${{book.number}}. ${{book.title}}</h2><div>${{book.author}}</div><div class='images'></div>`;
    const images=card.querySelector('.images');
    const all=[{{variant:0,label:'Original',image:book.original}}, ...(book.variants||[])];
    all.forEach(item=>{{
      const checked = selections[String(book.number)]===item.variant ? 'checked' : '';
      const disabled = item.variant===0 ? 'disabled' : '';
      const box=`<label>${{item.label}} <input type='checkbox' data-book='${{book.number}}' data-variant='${{item.variant}}' ${{checked}} ${{disabled}} /></label>`;
      const el=document.createElement('div');
      el.innerHTML=`<img src='${{item.image}}'/>${{box}}`;
      images.appendChild(el);
    }});
    root.appendChild(card);
  }});
  document.querySelectorAll('input[data-book]').forEach(box=>{{
    box.onchange=()=>{{
      const b=box.dataset.book,v=Number(box.dataset.variant);
      if(box.checked) selections[b]=v;
      else if(selections[b]===v) selections[b]=0;
      localStorage.setItem('variantSelections', JSON.stringify(selections));
      render();
    }};
  }});
}}
function download(){{
  const blob=new Blob([JSON.stringify(selections,null,2)],{{type:'application/json'}});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download='variant_selections.json';a.click();URL.revokeObjectURL(url);
}}
render();
</script></body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def _provider_runtime_payload(*, runtime: config.Config) -> dict[str, Any]:
    provider_stats = image_generator.get_provider_runtime_stats()
    configured_keys = runtime.provider_keys
    providers = sorted((set(configured_keys.keys()) | set(provider_stats.keys())) - {"replicate"})
    payload: dict[str, Any] = {}
    for provider in providers:
        key = str(configured_keys.get(provider, "") or "")
        stats = provider_stats.get(provider, {})
        payload[provider] = {
            "status": "active" if key.strip() else "inactive",
            "reason": None if key.strip() else "no API key",
            "requests_today": int(stats.get("requests_today", 0) or 0),
            "errors_today": int(stats.get("errors_today", 0) or 0),
            "circuit_state": str(stats.get("state", "closed")),
            "circuit_consecutive_failures": int(stats.get("consecutive_failures", 0) or 0),
            "circuit_cooldown_remaining_seconds": float(stats.get("cooldown_remaining_seconds", 0.0) or 0.0),
            "circuit_open_events": int(stats.get("open_events", 0) or 0),
            "circuit_probe_in_flight": bool(stats.get("probe_in_flight", False)),
            "rate_limit_window_second": int(stats.get("rate_limit_window_second", 0) or 0),
            "rate_limit_window_minute": int(stats.get("rate_limit_window_minute", 0) or 0),
            "last_error": str(stats.get("last_error", "") or ""),
            "opened_until_utc": str(stats.get("opened_until_utc", "") or ""),
        }
    return payload


def _provider_connectivity_payload(*, runtime: config.Config, force: bool = False) -> dict[str, Any]:
    cache_key = str(getattr(runtime, "catalog_id", "default") or "default")
    now = time.time()
    if not force:
        with _provider_connectivity_cache_lock:
            cached = _provider_connectivity_cache.get(cache_key)
            if isinstance(cached, dict) and float(cached.get("expires_at", 0.0) or 0.0) > now:
                payload = dict(cached.get("payload", {})) if isinstance(cached.get("payload", {}), dict) else {}
                payload.setdefault("ok", True)
                payload["cached"] = True
                return payload

    provider_names = sorted(runtime.provider_keys.keys())
    model_counts: dict[str, int] = {name: 0 for name in provider_names}
    for model in runtime.all_models:
        provider = runtime.resolve_model_provider(model)
        if provider in model_counts:
            model_counts[provider] += 1

    report = pipeline_runner.test_api_keys(runtime=runtime, providers=provider_names)
    rows = report.get("providers", []) if isinstance(report, dict) else []
    by_provider: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            provider = str(row.get("provider", "")).strip().lower()
            if not provider:
                continue
            status_token = str(row.get("status", "")).strip().upper()
            detail = str(row.get("detail", "")).strip()
            connected = status_token == "KEY_VALID"
            by_provider[provider] = {
                "status": "connected" if connected else "error",
                "models": int(model_counts.get(provider, 0)),
                "error": None if connected else (detail or status_token or "Connectivity check failed"),
            }

    for provider in provider_names:
        by_provider.setdefault(
            provider,
            {
                "status": "error",
                "models": int(model_counts.get(provider, 0)),
                "error": "Connectivity check unavailable",
            },
        )

    connected_count = sum(1 for row in by_provider.values() if str(row.get("status", "")) == "connected")
    payload: dict[str, Any] = {
        "ok": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
        "connected": connected_count,
        "total": len(provider_names),
        "providers": by_provider,
    }
    with _provider_connectivity_cache_lock:
        _provider_connectivity_cache[cache_key] = {
            "expires_at": now + float(PROVIDER_CONNECTIVITY_CACHE_SECONDS),
            "payload": payload,
        }
    return payload


def _composite_validation_summary(*, runtime: config.Config) -> dict[str, Any]:
    root = runtime.tmp_dir / "composited"
    if not root.exists():
        return {"reports": 0, "books_with_invalid": 0, "invalid_variants": 0, "total_variants_checked": 0}

    reports = 0
    invalid_books = 0
    invalid_variants = 0
    total_variants = 0
    for report_path in root.glob("*/composite_validation.json"):
        report = _load_json(report_path, {})
        if not isinstance(report, dict):
            continue
        if "total" not in report and "invalid" not in report:
            continue
        reports += 1
        total = _safe_int(report.get("total"), 0)
        invalid = _safe_int(report.get("invalid"), 0)
        total_variants += max(0, total)
        invalid_variants += max(0, invalid)
        if invalid > 0:
            invalid_books += 1
    return {
        "reports": reports,
        "books_with_invalid": invalid_books,
        "invalid_variants": invalid_variants,
        "total_variants_checked": total_variants,
    }


def _backup_health_payload(*, runtime: config.Config) -> dict[str, Any]:
    root = runtime.data_dir / "snapshots"
    if not root.exists():
        return {"lastBackup": "", "backupCount": 0, "backupSizeTotalMb": 0.0}
    snapshot_dirs = [path for path in root.iterdir() if path.is_dir()]
    snapshot_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    total_size = 0
    for snap in snapshot_dirs:
        for file_path in snap.rglob("*"):
            if file_path.is_file():
                total_size += int(file_path.stat().st_size)
    last_backup = ""
    if snapshot_dirs:
        last_backup = datetime.fromtimestamp(snapshot_dirs[0].stat().st_mtime, timezone.utc).isoformat()
    return {
        "lastBackup": last_backup,
        "backupCount": len(snapshot_dirs),
        "backupSizeTotalMb": round(total_size / (1024 * 1024), 3),
    }


def _health_payload(*, runtime: config.Config | None = None) -> dict[str, Any]:
    runtime = runtime or config.get_config()
    startup_state = _startup_state_snapshot()
    if str(startup_state.get("status", "")).strip().lower() == "initializing":
        payload = _startup_healthz_payload(runtime=runtime)
        payload["status"] = "starting"
        payload["healthy"] = True
        payload["startup_checks"] = STARTUP_HEALTH if isinstance(STARTUP_HEALTH, dict) else {}
        payload["checks"] = {
            "api_keys": {"status": "pending", "providers_configured": []},
            "config": {"status": "pending", "files_valid": 0, "files_total": 0},
            "database": {"status": "pending"},
            "drive": {"status": "pending"},
            "storage": {"status": "pending"},
        }
        payload["runtime_issues"] = []
        payload["slo"] = {
            "window_days": int(getattr(runtime, "slo_window_days", 7) or 7),
            "targets": {},
        }
        payload["slo_alerting"] = {"checked": False, "sent": False, "reason": "startup_initializing", "alerts": []}
        payload["slo_monitor"] = _slo_background_monitor_snapshot()
        payload["jobs"] = {
            "status_counts": job_db_store.status_counts(),
            "workers_configured": JOB_WORKER_COUNT,
            "worker_mode": ACTIVE_WORKER_MODE,
            "worker_service_alive": False,
            "worker_service": {},
            "sync_generation_allowed": _sync_generation_allowed(),
            "slo": {},
        }
        payload["providers"] = {}
        payload["models_configured"] = runtime.all_models
        payload["quality_summary"] = {
            "average_score": 0.0,
            "books_above_threshold": 0,
            "books_below_threshold": 0,
            "composite_validation": {"reports": 0, "books_with_invalid": 0, "invalid_variants": 0, "total_variants_checked": 0},
        }
        payload["backup"] = {"lastBackup": "", "backupCount": 0, "backupSizeTotalMb": 0.0}
        payload["disk_usage"] = {"output_covers_mb": 0.0, "tmp_mb": 0.0, "archive_mb": 0.0, "free_gb": round(shutil.disk_usage(PROJECT_ROOT).free / (1024 ** 3), 3)}
        payload["stats"] = {
            "books": len(_catalog_books_payload(runtime.book_catalog_path)),
            "variants": 0,
            "winners": len(_winner_variant_map(runtime=runtime)),
            "tests_last_run": 0,
            "coverage_percent": 0.0,
        }
        return payload

    worker_status = _worker_runtime_status()
    book_count = len(_catalog_books_payload(runtime.book_catalog_path))

    dashboard = _build_dashboard_payload(_load_generation_records(runtime=runtime), runtime=runtime)
    summary = dashboard.get("summary", {})
    quality_payload = _load_json(_quality_scores_path_for_runtime(runtime), {"scores": []})
    quality_rows = quality_payload.get("scores", []) if isinstance(quality_payload, dict) else []
    quality_scores = [_safe_float(row.get("overall_score"), 0.0) for row in quality_rows if isinstance(row, dict)]
    books_above_threshold = len({int(row.get("book_number", 0)) for row in quality_rows if isinstance(row, dict) and _safe_float(row.get("overall_score"), 0.0) >= runtime.min_quality_score})
    books_below_threshold = max(0, int(summary.get("books_generated", 0)) - books_above_threshold)

    providers_payload = _provider_runtime_payload(runtime=runtime)

    history_rows = _load_json(_history_path_for_runtime(runtime), {"items": []}).get("items", [])
    last_generation = ""
    if isinstance(history_rows, list) and history_rows:
        last_generation = max((str(row.get("timestamp", "")) for row in history_rows if isinstance(row, dict)), default="")

    def _dir_size_mb(path: Path) -> float:
        if not path.exists():
            return 0.0
        total = 0
        for file_path in path.rglob("*"):
            if file_path.is_file():
                total += file_path.stat().st_size
        return round(total / (1024 * 1024), 3)

    output_dir = runtime.output_dir
    tmp_dir = runtime.tmp_dir
    archive_dir = output_dir / "Archive"
    output_files = [path for path in output_dir.rglob("*.jpg") if path.is_file()]

    api_slo, job_slo, slo_evaluation = _build_slo_evaluation(runtime=runtime)
    slo_alert = _slo_alert_manager_for_runtime(runtime).maybe_alert(runtime=runtime, slo_evaluation=slo_evaluation)
    budget_status = _budget_status_for_runtime(runtime)

    startup = STARTUP_HEALTH if isinstance(STARTUP_HEALTH, dict) else {"healthy": True, "issues": [], "warnings": [], "checks": []}
    startup_healthy = bool(startup.get("healthy", True))
    status_counts = job_db_store.status_counts()
    pending_jobs = int(status_counts.get("queued", 0) or 0) + int(status_counts.get("retrying", 0) or 0)
    worker_mode = str(worker_status.get("mode", "inline") or "inline")
    worker_alive = bool(worker_status.get("alive", False))
    worker_outage_blocking = worker_mode == "external" and (not worker_alive) and pending_jobs > 0
    runtime_issues: list[str] = []
    if worker_outage_blocking:
        runtime_issues.append(
            f"External worker heartbeat is stale/unavailable with {pending_jobs} pending jobs. "
            f"Start worker service or set JOB_WORKER_MODE=inline."
        )
    overall_healthy = startup_healthy and (not worker_outage_blocking)
    free_gb = round(shutil.disk_usage(PROJECT_ROOT).free / (1024 ** 3), 3)
    database_check: dict[str, Any] = {"status": "disabled", "reason": "USE_SQLITE=false"}
    if runtime.use_sqlite:
        start = time.time()
        try:
            import sqlite3

            conn = sqlite3.connect(str(runtime.sqlite_db_path), timeout=5)
            conn.execute("SELECT 1")
            conn.close()
            database_check = {"status": "ok", "latency_ms": round((time.time() - start) * 1000.0, 3), "path": str(runtime.sqlite_db_path)}
        except Exception as exc:
            database_check = {"status": "error", "error": str(exc), "path": str(runtime.sqlite_db_path)}
            overall_healthy = False
            runtime_issues.append(f"SQLite check failed: {exc}")

    config_files = list(runtime.config_dir.glob("*.json"))
    config_valid = sum(1 for row in startup.get("checks", []) if isinstance(row, dict) and row.get("ok", False))
    configured_providers = [name for name, key in runtime.provider_keys.items() if key.strip()]
    drive_credentials_path = _resolve_credentials_path(runtime)
    drive_mode, drive_mode_error = _drive_credentials_mode(runtime, credentials_path=drive_credentials_path)
    drive_source_folder = (
        str(getattr(runtime, "gdrive_source_folder_id", "") or "").strip()
        or str(getattr(runtime, "gdrive_input_folder_id", "") or "").strip()
        or str(getattr(runtime, "gdrive_output_folder_id", "") or "").strip()
    )
    drive_enabled = bool(drive_source_folder)
    drive_connected = False
    drive_check: dict[str, Any]
    if drive_enabled and drive_mode:
        try:
            auth_path = None if drive_mode == "service_account_env" else drive_credentials_path
            gdrive_sync.authenticate(auth_path)
            drive_connected = True
            drive_check = {
                "status": "ok",
                "mode": drive_mode,
                "credentials_path": str(drive_credentials_path),
            }
        except Exception as exc:
            drive_connected = False
            drive_check = {
                "status": "error",
                "mode": drive_mode,
                "credentials_path": str(drive_credentials_path),
                "reason": str(exc),
            }
    else:
        drive_check = {
            "status": "disabled",
            "mode": drive_mode,
            "reason": drive_mode_error if drive_enabled else "folder_not_configured",
        }
    active_jobs = (
        int(status_counts.get("queued", 0) or 0)
        + int(status_counts.get("running", 0) or 0)
        + int(status_counts.get("retrying", 0) or 0)
    )
    return {
        "status": "ok" if overall_healthy else "degraded",
        "healthy": overall_healthy,
        "version": "2.1.1",
        "uptime_seconds": int(max(0.0, time.time() - APP_STARTED_AT)),
        "database": "connected" if str(database_check.get("status", "")).strip().lower() == "ok" else "disconnected",
        "drive": {
            "connected": bool(drive_connected),
            "source_folder_id": str(drive_source_folder or ""),
            "credential_type": str(drive_mode or ""),
            "status": str(drive_check.get("status", "")),
            "error": str(drive_check.get("reason", "") or ""),
        },
        "drive_connection": "connected" if bool(drive_connected) else "disconnected",
        "disk_space_gb": free_gb,
        "active_jobs": active_jobs,
        "books_cataloged": book_count,
        "books_generated": int(summary.get("books_generated", 0)),
        "total_images": len(quality_rows) if quality_rows else len(output_files),
        "total_cost": round(_safe_float(summary.get("total_spent"), 0.0), 4),
        "budget_remaining": round(_safe_float(summary.get("budget_remaining"), runtime.max_cost_usd), 4),
        "budget": budget_status,
        "last_generation": last_generation,
        "providers": providers_payload,
        "disk_usage": {
            "output_covers_mb": _dir_size_mb(output_dir),
            "tmp_mb": _dir_size_mb(tmp_dir),
            "archive_mb": _dir_size_mb(archive_dir),
            "free_gb": round(shutil.disk_usage(PROJECT_ROOT).free / (1024 ** 3), 3),
        },
        "quality_summary": {
            "average_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0.0,
            "books_above_threshold": books_above_threshold,
            "books_below_threshold": books_below_threshold,
            "composite_validation": _composite_validation_summary(runtime=runtime),
        },
        "backup": _backup_health_payload(runtime=runtime),
        "jobs": {
            "status_counts": status_counts,
            "workers_configured": JOB_WORKER_COUNT,
            "worker_mode": worker_status.get("mode"),
            "worker_service_alive": bool(worker_status.get("alive", False)),
            "worker_service": worker_status,
            "sync_generation_allowed": _sync_generation_allowed(),
            "slo": job_slo,
        },
        "slo": slo_evaluation,
        "slo_alerting": slo_alert,
        "slo_monitor": _slo_background_monitor_snapshot(),
        "models_configured": runtime.all_models,
        "startup_checks": startup,
        "runtime_issues": runtime_issues,
        "checks": {
            "database": database_check,
            "config": {"status": "ok" if startup_healthy else "degraded", "files_valid": config_valid, "files_total": len(config_files)},
            "storage": {
                "status": "ok" if free_gb >= 10.0 else "warning",
                "free_gb": free_gb,
                "usage_percent": round((1 - (shutil.disk_usage(PROJECT_ROOT).free / max(1, shutil.disk_usage(PROJECT_ROOT).total))) * 100.0, 3),
            },
            "api_keys": {"status": "ok" if configured_providers else "warning", "providers_configured": configured_providers},
            "drive": drive_check,
        },
        "stats": {
            "books": book_count,
            "variants": len(quality_rows),
            "winners": len(_winner_variant_map(runtime=runtime)),
            "tests_last_run": 0,
            "coverage_percent": 0.0,
        },
    }


def _build_slo_evaluation(*, runtime: config.Config) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    api_slo = _slo_tracker_for_runtime(runtime).snapshot(window_days=runtime.slo_window_days, catalog_id=runtime.catalog_id)
    job_slo = job_db_store.slo_summary(window_days=runtime.slo_window_days, catalog_id=runtime.catalog_id)
    slo_targets = {
        "api_success_rate_7d": 0.995,
        "job_completion_without_manual_intervention": 0.98,
        "same_stage_retry_rate_max": 0.02,
    }

    def _slo_state_ge(actual: float, target: float, risk_band: float = 0.01) -> str:
        if actual >= target:
            return "met"
        if actual >= max(0.0, target - abs(risk_band)):
            return "at_risk"
        return "breached"

    def _slo_state_le(actual: float, target: float, risk_band: float = 0.01) -> str:
        if actual <= target:
            return "met"
        if actual <= (target + abs(risk_band)):
            return "at_risk"
        return "breached"

    slo_evaluation = {
        "window_days": int(runtime.slo_window_days),
        "targets": slo_targets,
        "api_success_rate_7d": {
            "actual": float(api_slo.get("success_rate", 1.0) or 1.0),
            "target": slo_targets["api_success_rate_7d"],
            "status": _slo_state_ge(float(api_slo.get("success_rate", 1.0) or 1.0), slo_targets["api_success_rate_7d"]),
            "requests": int(api_slo.get("total_requests", 0) or 0),
        },
        "job_completion_without_manual_intervention": {
            "actual": float(job_slo.get("completion_without_manual_intervention", 1.0) or 1.0),
            "target": slo_targets["job_completion_without_manual_intervention"],
            "status": _slo_state_ge(
                float(job_slo.get("completion_without_manual_intervention", 1.0) or 1.0),
                slo_targets["job_completion_without_manual_intervention"],
            ),
            "terminal_jobs": int(job_slo.get("terminal_total", 0) or 0),
        },
        "same_stage_retry_rate": {
            "actual": float(job_slo.get("same_stage_retry_rate", 0.0) or 0.0),
            "target": slo_targets["same_stage_retry_rate_max"],
            "status": _slo_state_le(
                float(job_slo.get("same_stage_retry_rate", 0.0) or 0.0),
                slo_targets["same_stage_retry_rate_max"],
            ),
            "retry_jobs": int(job_slo.get("retry_jobs", 0) or 0),
        },
    }
    return api_slo, job_slo, slo_evaluation


def _enrichment_coverage_payload(*, runtime: config.Config) -> dict[str, Any]:
    source_rows = _catalog_books_payload(runtime.book_catalog_path)
    total_books = len(source_rows)
    enriched_path = config.enriched_catalog_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    enriched_rows = _json_list_rows_cache_entry(enriched_path).get("rows", [])
    valid_numbers: set[int] = set()
    if isinstance(enriched_rows, list):
        for row in enriched_rows:
            if not isinstance(row, dict):
                continue
            number = _safe_int(row.get("number"), 0)
            enrichment = row.get("enrichment", {})
            if number <= 0 or not isinstance(enrichment, dict) or not enrichment:
                continue
            if book_enricher._has_generic_content(enrichment):  # type: ignore[attr-defined]
                continue
            valid_numbers.add(number)
    usable_books = sum(
        1
        for row in source_rows
        if isinstance(row, dict) and _safe_int(row.get("number"), 0) in valid_numbers
    )
    coverage_ratio = float(usable_books) / float(total_books) if total_books > 0 else 1.0
    return {
        "total_books": total_books,
        "usable_books": usable_books,
        "coverage_ratio": coverage_ratio,
        "enriched_path": str(enriched_path),
    }


def _probe_drive_write_access(*, service: Any, parent_folder_id: str) -> dict[str, Any]:
    fd, probe_name = tempfile.mkstemp(prefix="drive-write-probe-", suffix=".txt")
    os.close(fd)
    probe_path = Path(probe_name)
    probe_path.write_bytes(b"1")
    created_file_id = ""
    try:
        media = gdrive_sync.MediaFileUpload(str(probe_path), mimetype="text/plain")
        created = service.files().create(
            body={
                "name": f"alexandria-write-probe-{uuid.uuid4().hex[:8]}.txt",
                "parents": [str(parent_folder_id)],
            },
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        created_file_id = str(created.get("id", "") or "").strip()
        if not created_file_id:
            raise RuntimeError("Google Drive write probe did not return an id")
        last_delete_exc: Exception | None = None
        for attempt in range(1, SAVE_RAW_DRIVE_PROBE_DELETE_ATTEMPTS + 1):
            try:
                service.files().update(
                    fileId=created_file_id,
                    body={"trashed": True},
                    supportsAllDrives=True,
                ).execute()
                last_delete_exc = None
                break
            except Exception as exc:
                details = _drive_error_details(exc)
                message = str(details.get("message", "") or exc).lower()
                last_delete_exc = exc
                if "not found" not in message or attempt >= SAVE_RAW_DRIVE_PROBE_DELETE_ATTEMPTS:
                    raise
                time.sleep(SAVE_RAW_DRIVE_PROBE_DELETE_DELAY_SECONDS)
        if last_delete_exc is not None:
            raise last_delete_exc
        return {"ok": True, "error": "", "file_id": created_file_id}
    except Exception as exc:
        details = _drive_error_details(exc)
        return {"ok": False, "error": details["message"], "file_id": created_file_id}
    finally:
        probe_path.unlink(missing_ok=True)


def _probe_drive_write_access_with_timeout(
    *,
    service: Any,
    parent_folder_id: str,
    timeout_seconds: float = SAVE_RAW_DRIVE_PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    results: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

    def _run_probe() -> None:
        try:
            results.put(_probe_drive_write_access(service=service, parent_folder_id=parent_folder_id))
        except Exception as exc:  # pragma: no cover - defensive
            results.put({"ok": False, "error": str(exc), "file_id": ""})

    worker = threading.Thread(target=_run_probe, name="drive-write-probe", daemon=True)
    worker.start()
    worker.join(timeout=max(0.1, float(timeout_seconds)))
    if worker.is_alive():
        return {
            "ok": False,
            "error": f"timed out after {float(timeout_seconds):.1f}s",
            "file_id": "",
            "timed_out": True,
        }
    try:
        return results.get_nowait()
    except queue.Empty:
        return {"ok": False, "error": "probe returned no result", "file_id": ""}


def _run_startup_checks(runtime: config.Config) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    warnings: list[str] = []

    def _record(name: str, ok: bool, detail: str, *, level: str = "issue") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "level": level})
        if ok:
            return
        if level == "warning":
            warnings.append(f"{name}: {detail}")
        else:
            issues.append(f"{name}: {detail}")

    required_paths = {
        "input_dir": runtime.input_dir,
        "output_dir": runtime.output_dir,
        "tmp_dir": runtime.tmp_dir,
        "data_dir": runtime.data_dir,
        "book_catalog": runtime.book_catalog_path,
        "prompts": runtime.prompts_path,
        "prompt_library": runtime.prompt_library_path,
    }
    for label, path in required_paths.items():
        _record(label, path.exists(), str(path))

    writable_paths = {
        "output_dir_writable": runtime.output_dir,
        "tmp_dir_writable": runtime.tmp_dir,
        "data_dir_writable": runtime.data_dir,
        "jobs_db_dir_writable": JOBS_DB_PATH.parent,
        "state_db_dir_writable": STATE_DB_PATH.parent,
    }
    for label, path in writable_paths.items():
        ok = path.exists() and os.access(path, os.W_OK)
        _record(label, ok, str(path))

    worker_status = _worker_runtime_status()
    _record("worker_mode", bool(worker_status.get("mode")), str(worker_status.get("mode", "inline")), level="warning")
    if str(worker_status.get("mode")) == "external":
        _record(
            "external_worker_heartbeat",
            bool(worker_status.get("alive", False)),
            (
                "External worker heartbeat not detected at "
                f"{JOB_WORKER_HEARTBEAT_PATH} within {JOB_WORKER_HEARTBEAT_STALE_SECONDS}s"
            ),
            level="warning",
        )

    any_key = any(bool(v.strip()) for v in runtime.provider_keys.values())
    _record("provider_api_keys", any_key, "No provider API keys configured", level="warning")

    enrichment_coverage = _enrichment_coverage_payload(runtime=runtime)
    _record(
        "enrichment_coverage",
        float(enrichment_coverage.get("coverage_ratio", 0.0)) >= 0.90,
        (
            f"Only {int(enrichment_coverage.get('usable_books', 0))}/"
            f"{int(enrichment_coverage.get('total_books', 0))} books have usable enrichment data. "
            "Run 'python -m src.book_enricher --force --all' to refresh enrichment."
        ),
        level="warning",
    )

    drive_source_folder = (
        str(getattr(runtime, "gdrive_source_folder_id", "") or "").strip()
        or str(getattr(runtime, "gdrive_input_folder_id", "") or "").strip()
        or str(getattr(runtime, "gdrive_output_folder_id", "") or "").strip()
    )
    if drive_source_folder:
        service, _credentials_path, drive_mode, credentials_meta, drive_error = _drive_service_for_runtime(runtime)
        if drive_mode:
            if service is not None:
                _record(
                    "google_drive_auth",
                    True,
                    f"Google Drive connected. Covers will be downloaded on demand from folder {drive_source_folder}.",
                    level="warning",
                )
                logger.info(
                    "Google Drive connected. Covers will be downloaded on demand from folder %s.",
                    drive_source_folder,
                )
                write_probe = _probe_drive_write_access_with_timeout(
                    service=service,
                    parent_folder_id=SAVE_RAW_DRIVE_FOLDER_ID,
                )
                write_detail = "Drive upload: OK (Shared Drive)"
                if bool(write_probe.get("ok", False)):
                    logger.info("%s for folder %s.", write_detail, SAVE_RAW_DRIVE_FOLDER_ID)
                else:
                    write_detail = (
                        "Drive upload failed — check Shared Drive permissions for service account "
                        f"{str(credentials_meta.get('client_email', '') or '(unknown)')} on folder "
                        f"{SAVE_RAW_DRIVE_FOLDER_ID}. "
                        f"({str(write_probe.get('error', '') or 'write probe failed')})"
                    )
                _record(
                    "save_raw_drive_write_access",
                    bool(write_probe.get("ok", False)),
                    write_detail,
                    level="warning",
                )
                if not bool(write_probe.get("ok", False)):
                    logger.warning(write_detail)
            else:
                _record(
                    "google_drive_auth",
                    False,
                    str(drive_error or "Google Drive credentials are not configured."),
                    level="warning",
                )
                logger.warning(
                    "Google Drive credentials not configured. Set GOOGLE_CREDENTIALS_JSON env var. "
                    "Cover generation will only work with local files. (%s)",
                    drive_error,
                )
        else:
            _record(
                "google_drive_auth",
                False,
                str(drive_error or "Google Drive credentials are not configured."),
                level="warning",
            )
            logger.warning(
                "Google Drive credentials not configured. Set GOOGLE_CREDENTIALS_JSON env var. "
                "Cover generation will only work with local files."
            )
    else:
        _record(
            "google_drive_source_folder",
            False,
            "Google Drive source folder is not configured (set GDRIVE_SOURCE_FOLDER_ID).",
            level="warning",
        )

    try:
        catalog_rows = _catalog_books_payload(runtime.book_catalog_path)
        _record("book_catalog_json", bool(catalog_rows), str(runtime.book_catalog_path))
    except Exception as exc:
        _record("book_catalog_json", False, f"{runtime.book_catalog_path} ({exc})")

    try:
        prompt_payload = json.loads(runtime.prompts_path.read_text(encoding="utf-8"))
        _record("prompts_json", isinstance(prompt_payload, dict), str(runtime.prompts_path))
    except Exception as exc:
        _record("prompts_json", False, f"{runtime.prompts_path} ({exc})")

    summary = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "healthy": not issues,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
    }
    if issues:
        logger.error("Startup health checks found critical issues", extra={"issues": issues})
    elif warnings:
        logger.warning("Startup health checks found warnings", extra={"warnings": warnings})
    else:
        logger.info("Startup health checks passed")
    return summary


def serve_review_webapp(
    output_dir: Path,
    port: int = 8001,
    host: str | None = None,
    reviewer_default: str = "tim",
    worker_mode: str | None = None,
) -> None:
    """Serve Alexandria web pages and API endpoints."""
    mode = _normalize_worker_mode(worker_mode or JOB_WORKER_MODE)
    global ACTIVE_WORKER_MODE
    ACTIVE_WORKER_MODE = mode
    bind_host = (host or os.getenv("HOST", "0.0.0.0")).strip() or "0.0.0.0"
    default_runtime = config.get_config()
    default_runtime.model_cost_usd = config.runtime_model_costs_copy()
    default_runtime.cost_per_image_usd = default_runtime.get_model_cost(default_runtime.ai_model)
    _set_startup_health(
        {
            "checked_at": "",
            "healthy": True,
            "issues": [],
            "warnings": ["Startup initialization in progress."],
            "checks": [],
        }
    )
    _set_startup_state(status="initializing", started_at=datetime.now(timezone.utc).isoformat(), completed_at="", error="")
    server_runtime_state: dict[str, Any] = {
        "slo_monitor": None,
        "workers_started": False,
    }
    server_runtime_state_lock = threading.Lock()

    lock = threading.Lock()

    configured_reviewer = str(reviewer_default or "tim").strip() or "tim"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self._active_catalog_id = ""
            self._active_runtime: config.Config | None = None
            self._request_id = ""
            super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

        def setup(self):
            try:
                self.request.settimeout(REQUEST_HANDLER_TIMEOUT_SECONDS)
            except Exception:
                pass
            super().setup()

        def _set_active_catalog(self, catalog_id: str | None) -> None:
            self._active_catalog_id = str(catalog_id or "").strip()

        def _set_active_runtime(self, runtime: config.Config | None) -> None:
            self._active_runtime = runtime
            self._set_active_catalog(runtime.catalog_id if runtime is not None else "")

        def _current_catalog(self) -> str:
            return str(getattr(self, "_active_catalog_id", "") or "").strip()

        def _runtime_for_catalog_token(self, token: str | None) -> config.Config:
            raw = str(token or "").strip()
            if not raw:
                return config.get_config(default_runtime.catalog_id)
            try:
                catalog_id = security.validate_catalog_id(raw)
            except ValueError:
                catalog_id = default_runtime.catalog_id
            return config.get_config(catalog_id)

        def _current_runtime(self) -> config.Config:
            active = getattr(self, "_active_runtime", None)
            if isinstance(active, config.Config):
                return active
            if self._current_catalog():
                return self._runtime_for_catalog_token(self._current_catalog())
            try:
                token = str(parse_qs(urlparse(self.path).query).get("catalog", [""])[0] or "").strip()
            except Exception:
                token = ""
            return self._runtime_for_catalog_token(token)

        def _set_request_id(self, request_id: str | None) -> None:
            self._request_id = str(request_id or "").strip()

        def _current_request_id(self) -> str:
            token = str(getattr(self, "_request_id", "") or "").strip()
            if token:
                return token
            token = str(self.headers.get("X-Request-Id", "")).strip()
            if not token:
                token = str(uuid.uuid4())
            self._request_id = token
            return token

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-XSS-Protection", "1; mode=block")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.send_header(
                "Content-Security-Policy",
                (
                    "default-src 'self'; "
                    "img-src 'self' data: blob:; "
                    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
                    "font-src 'self' data: https://fonts.gstatic.com"
                ),
            )
            super().end_headers()

        def _serve_project_relative(
            self,
            request_path: str,
            *,
            allowed_roots: list[Path],
            cache_control: str = "public, max-age=86400",
        ):
            raw = unquote(str(request_path or "")).strip()
            normalized = raw.lstrip("/")
            if "\x00" in raw:
                return self._send_error(
                    code="INVALID_PATH",
                    message="Null bytes are not allowed in file paths",
                    details={"path": request_path},
                    status=HTTPStatus.BAD_REQUEST,
                    endpoint=self.path,
                )
            try:
                safe_path = security.sanitize_path(normalized, PROJECT_ROOT)
            except Exception:
                return self._send_error(
                    code="PATH_NOT_ALLOWED",
                    message="Requested file path is not allowed",
                    details={"path": request_path},
                    status=HTTPStatus.FORBIDDEN,
                    endpoint=self.path,
                )
            if not safe_path.is_file():
                return self._send_error(
                    code="FILE_NOT_FOUND",
                    message="Requested file was not found",
                    details={"path": str(safe_path)},
                    status=HTTPStatus.NOT_FOUND,
                    endpoint=self.path,
                )
            if not any(safe_path.is_relative_to(root.resolve()) for root in allowed_roots):
                return self._send_error(
                    code="PATH_NOT_ALLOWED",
                    message="Requested file path is not within an allowed directory",
                    details={"path": str(safe_path)},
                    status=HTTPStatus.FORBIDDEN,
                    endpoint=self.path,
                )
            content_type = mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream"
            return self._send_file(safe_path, content_type=content_type, cache_control=cache_control)

        def do_GET(self):
            self._request_started_at = time.perf_counter()
            self._request_method = "GET"
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            self._request_path = str(path)
            self._set_active_runtime(None)
            self._set_request_id(str(self.headers.get("X-Request-Id", "")).strip() or str(uuid.uuid4()))
            requested_catalog_raw = str(query.get("catalog", [default_runtime.catalog_id])[0]).strip()
            try:
                requested_catalog = security.validate_catalog_id(requested_catalog_raw) if requested_catalog_raw else default_runtime.catalog_id
            except ValueError:
                return self._send_error(
                    code="INVALID_CATALOG_ID",
                    message="Invalid catalog id",
                    details={"catalog": requested_catalog_raw},
                    status=HTTPStatus.BAD_REQUEST,
                    endpoint=path,
                )
            runtime_req = config.get_config(requested_catalog or default_runtime.catalog_id)
            self._set_active_runtime(runtime_req)
            client_ip = str(self.client_address[0] if self.client_address else "unknown")

            if path in {"/api/healthz", "/healthz"}:
                return self._send_json(_startup_healthz_payload(runtime=runtime_req), cache_control="no-store")

            if not read_rate_limiter.allow(f"{client_ip}:{path}"):
                return self._send_error(
                    code="RATE_LIMITED",
                    message="Too many read requests. Please retry shortly.",
                    details={"path": path, "limit_per_minute": READ_RATE_LIMIT_PER_MINUTE},
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                    endpoint=path,
                    headers={"Retry-After": "60"},
                )
            cacheable_paths = {
                "/api/review-data",
                "/api/iterate-data",
                "/api/config/cover-source-default",
                "/api/prompt-performance",
                "/api/health",
                "/api/history",
                "/api/generation-history",
                "/api/dashboard-data",
                "/api/weak-books",
                "/api/regeneration-results",
                "/api/similarity-matrix",
                "/api/similarity-alerts",
                "/api/similarity-clusters",
                "/api/review-queue",
                "/api/review-stats",
                "/api/mockup-status",
                "/api/compare",
                "/api/books",
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
                "/api/analytics/prompts/effectiveness",
                "/api/analytics/quality/breakdown",
                "/api/analytics/completion",
                "/api/analytics/audit",
                "/api/exports",
                "/api/delivery/status",
                "/api/delivery/tracking",
                "/api/drive/input-covers",
                "/api/archive/stats",
                "/api/storage/usage",
            }
            cache_key = _cache_key(path, query, runtime_req.catalog_id)
            should_cache = path in cacheable_paths or path.startswith("/api/analytics/reports")

            def _static_cache_control_for(request_path: str) -> str:
                lower = str(request_path or "").lower()
                if lower.endswith((".css", ".js", ".html")):
                    # Always fetch latest UI assets so deploys never render stale layouts.
                    return "no-store"
                if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".avif")):
                    return "public, max-age=3600"
                return "public, max-age=900"

            def _cache_and_send(payload: dict[str, Any]):
                if should_cache:
                    data_cache.set(cache_key, payload)
                return self._send_json(payload, headers={"X-Cache": "MISS" if should_cache else "BYPASS"})

            if should_cache:
                cached = data_cache.get(cache_key)
                if isinstance(cached, dict):
                    return self._send_json(cached, headers={"X-Cache": "HIT"})

            if path in {"", "/"}:
                path = "/iterate"

            def _build_cgi_catalog_payload() -> dict[str, Any]:
                write_iterate_data(runtime=runtime_req)
                iterate_payload = _load_json(_iterate_data_path_for_runtime(runtime_req), {"books": []})
                rows = iterate_payload.get("books", []) if isinstance(iterate_payload, dict) else []
                books: list[dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    number = _safe_int(row.get("number"), 0)
                    if number <= 0:
                        continue
                    books.append(
                        {
                            "id": number,
                            "number": number,
                            "title": str(row.get("title", "")),
                            "author": str(row.get("author", "")),
                            "folder_name": str(row.get("folder", row.get("folder_name", ""))),
                            "cover_jpg_id": str(row.get("cover_jpg_id", "")),
                            "cover_name": str(row.get("cover_name", "")),
                            "synced_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                books.sort(key=lambda item: _safe_int(item.get("number"), 0))
                payload = {
                    "books": books,
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "count": len(books),
                }
                try:
                    CGI_CATALOG_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                except Exception:
                    pass
                return payload

            if path == "/cgi-bin/settings.py":
                payload = _load_json(SETTINGS_STORE_PATH, {})
                if not isinstance(payload, dict):
                    payload = {}
                return self._send_json(payload)
            if path == "/cgi-bin/catalog.py/status":
                if CGI_CATALOG_CACHE_PATH.exists():
                    age = max(0.0, time.time() - CGI_CATALOG_CACHE_PATH.stat().st_mtime)
                    cache_payload = _load_json(CGI_CATALOG_CACHE_PATH, {})
                    books = cache_payload.get("books", []) if isinstance(cache_payload, dict) else []
                    return self._send_json(
                        {
                            "cached": True,
                            "age_seconds": age,
                            "count": len(books) if isinstance(books, list) else 0,
                            "synced_at": cache_payload.get("synced_at") if isinstance(cache_payload, dict) else None,
                            "stale": age > CGI_CATALOG_MAX_AGE_SECONDS,
                        }
                    )
                return self._send_json({"cached": False, "age_seconds": 0.0, "count": 0, "synced_at": None, "stale": False})
            if path == "/cgi-bin/catalog.py":
                if CGI_CATALOG_CACHE_PATH.exists():
                    payload = _load_json(CGI_CATALOG_CACHE_PATH, {})
                    if isinstance(payload, dict) and isinstance(payload.get("books"), list):
                        return self._send_json(payload)
                return self._send_json(_build_cgi_catalog_payload())

            spa_routes = {
                "/iterate",
                "/batch",
                "/jobs",
                "/review",
                "/visual-qa",
                "/compare",
                "/similarity",
                "/mockups",
                "/dashboard",
                "/history",
                "/analytics",
                "/analytics/models",
                "/catalogs",
                "/prompts",
                "/settings",
                "/catalog/settings",
                "/admin/performance",
                "/api-docs",
            }
            if path in spa_routes:
                return self._serve_project_relative(
                    "/src/static/index.html",
                    allowed_roots=[PROJECT_ROOT / "src" / "static"],
                    cache_control="no-store",
                )
            if path == "/favicon.ico":
                favicon_path = PROJECT_ROOT / "favicon.ico"
                if favicon_path.is_file():
                    return self._serve_project_relative(
                        "/favicon.ico",
                        allowed_roots=[PROJECT_ROOT],
                        cache_control="public, max-age=86400",
                    )
                return self._send_bytes(
                    FALLBACK_FAVICON_SVG,
                    content_type="image/svg+xml",
                    cache_control="public, max-age=86400",
                )
            if path.startswith("/css/") or path.startswith("/js/") or path.startswith("/img/"):
                return self._serve_project_relative(
                    f"/src/static{path}",
                    allowed_roots=[PROJECT_ROOT / "src" / "static"],
                    cache_control=_static_cache_control_for(path),
                )
            if path.startswith("/src/static/"):
                return self._serve_project_relative(
                    path,
                    allowed_roots=[PROJECT_ROOT / "src" / "static"],
                    cache_control=_static_cache_control_for(path),
                )
            if path.startswith("/static/"):
                static_rel = path.split("/static/", 1)[1]
                return self._serve_project_relative(
                    f"/src/static/{static_rel}",
                    allowed_roots=[PROJECT_ROOT / "src" / "static"],
                    cache_control=_static_cache_control_for(path),
                )
            if path.startswith("/tmp/visual-qa/"):
                return self._serve_project_relative(
                    path,
                    allowed_roots=[_visual_qa_dir_for_runtime(runtime_req)],
                    cache_control="no-store",
                )
            if path.startswith("/Output Covers/") or path.startswith("/tmp/"):
                return self._serve_project_relative(
                    path,
                    allowed_roots=[runtime_req.output_dir, runtime_req.tmp_dir],
                    cache_control="no-store",
                )
            if path in {"/api/docs", "/docs"}:
                html = _build_api_docs_html()
                data = html.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/api/version":
                return self._send_json({"ok": True, "version": "2.1.1"})
            if path == "/api/models":
                return _cache_and_send({"ok": True, **_api_models_payload(runtime=runtime_req)})
            if path == "/api/providers":
                return _cache_and_send({"ok": True, **_api_providers_payload(runtime=runtime_req)})
            if path == "/api/catalog":
                return _cache_and_send({"ok": True, **_api_catalog_payload(runtime=runtime_req)})
            if path == "/api/templates":
                genre_filter = str(query.get("genre", [""])[0] or "").strip().lower()
                return _cache_and_send({"ok": True, **_api_templates_payload(runtime=runtime_req, genre=genre_filter)})
            if path == "/api/stats":
                return _cache_and_send({"ok": True, **_api_stats_payload(runtime=runtime_req)})
            if path == "/api/config":
                return _cache_and_send({"ok": True, **_api_config_payload(runtime=runtime_req)})
            if path == "/api/catalogs":
                return _cache_and_send(_catalogs_payload_with_stats(active_catalog=runtime_req.catalog_id))
            if path.startswith("/api/catalogs/"):
                suffix = path.split("/api/catalogs/", 1)[1].strip("/")
                if not suffix:
                    return self._send_error(
                        code="CATALOG_ID_REQUIRED",
                        message="catalog id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                parts = suffix.split("/")
                catalog_id = parts[0]
                try:
                    if len(parts) == 1:
                        item = catalog_registry.get_catalog(catalog_id).to_dict()
                        item["id"] = item.get("catalog_id")
                        item["stats"] = catalog_registry.stats_for_catalog(catalog_id)
                        return _cache_and_send({"ok": True, "catalog": item})
                    if len(parts) == 2 and parts[1] == "settings":
                        settings = catalog_registry.get_settings(catalog_id)
                        return _cache_and_send({"ok": True, "catalog": catalog_id, "settings": settings})
                    if len(parts) == 2 and parts[1] == "export":
                        bundle = catalog_registry.export_catalog_bundle(catalog_id)
                        return _cache_and_send({"ok": True, "bundle": bundle})
                except KeyError:
                    return self._send_error(
                        code="CATALOG_NOT_FOUND",
                        message="Catalog not found",
                        details={"catalog": catalog_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="CATALOG_OPERATION_FAILED",
                        message=str(exc),
                        details={"catalog": catalog_id},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                return self._send_error(
                    code="CATALOG_ROUTE_NOT_FOUND",
                    message="Unsupported catalog route",
                    details={"path": path},
                    status=HTTPStatus.NOT_FOUND,
                    endpoint=path,
                )
            if path == "/api/cache/stats":
                worker_status = _worker_runtime_status()
                return self._send_json(
                    {
                        "ok": True,
                        "cache": data_cache.stats(),
                        "providers": _provider_runtime_payload(runtime=runtime_req),
                        "slo": _slo_tracker_for_runtime(runtime_req).snapshot(
                            window_days=runtime_req.slo_window_days,
                            catalog_id=runtime_req.catalog_id,
                        ),
                        "slo_monitor": _slo_background_monitor_snapshot(),
                        "in_flight_requests": request_tracker.active(),
                        "jobs": {
                            "status_counts": job_db_store.status_counts(),
                            "workers_configured": JOB_WORKER_COUNT,
                            "worker_mode": worker_status.get("mode"),
                            "worker_service": worker_status,
                            "sync_generation_allowed": _sync_generation_allowed(),
                        },
                    }
                )
            if path == "/api/metrics":
                api_slo, job_slo, slo_evaluation = _build_slo_evaluation(runtime=runtime_req)
                slo_alert = _slo_alert_manager_for_runtime(runtime_req).maybe_alert(runtime=runtime_req, slo_evaluation=slo_evaluation)
                worker_status = _worker_runtime_status()
                return self._send_json(
                    {
                        "ok": True,
                        "cache": data_cache.stats(),
                        "providers": _provider_runtime_payload(runtime=runtime_req),
                        "errors": error_metrics.get_metrics(catalog_id=runtime_req.catalog_id),
                        "slo": {
                            "api": api_slo,
                            "jobs": job_slo,
                            "evaluation": slo_evaluation,
                            "alerting": slo_alert,
                            "background_monitor": _slo_background_monitor_snapshot(),
                        },
                        "jobs": {
                            "db_path": str(JOBS_DB_PATH),
                            "state_db_path": str(STATE_DB_PATH),
                            "status_counts": job_db_store.status_counts(),
                            "workers_configured": JOB_WORKER_COUNT,
                            "worker_mode": worker_status.get("mode"),
                            "worker_service": worker_status,
                            "sync_generation_allowed": _sync_generation_allowed(),
                        },
                    }
                )
            if path == "/api/performance/summary":
                return self._send_json(_performance_summary_payload(runtime=runtime_req))
            if path == "/api/providers/runtime":
                return self._send_json(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "providers": _provider_runtime_payload(runtime=runtime_req),
                        "models_configured": runtime_req.all_models,
                    }
                )
            if path == "/api/providers/connectivity":
                force = str(query.get("force", ["0"])[0] or "0").strip().lower() in {"1", "true", "yes", "on"}
                payload = _provider_connectivity_payload(runtime=runtime_req, force=force)
                payload["catalog"] = runtime_req.catalog_id
                return self._send_json(payload)
            if path == "/api/workers":
                return self._send_json(
                    {
                        "ok": True,
                        "workers": _worker_runtime_status(),
                        "jobs": {
                            "status_counts": job_db_store.status_counts(),
                            "workers_configured": JOB_WORKER_COUNT,
                        },
                    }
                )
            if path == "/api/audit-log":
                limit = _safe_int(query.get("limit", ["100"])[0], 100)
                rows = audit_log.load_events(config.audit_log_path(catalog_id=runtime_req.catalog_id, data_dir=runtime_req.data_dir))
                rows = rows[-max(1, min(1000, limit)):]
                signed = sum(1 for row in rows if str(row.get("signature_status", "")) == "signed")
                unsigned = sum(1 for row in rows if str(row.get("signature_status", "")) != "signed")
                return self._send_json(
                    {
                        "ok": True,
                        "count": len(rows),
                        "signed": signed,
                        "unsigned": unsigned,
                        "items": rows,
                    }
                )
            if path == "/api/analytics/costs":
                period = _parse_period_token(query, default="7d")
                entries = _cost_entries_for_runtime(runtime=runtime_req, period=period)
                summary = cost_tracker.summarize(entries)
                summary["period"] = period
                summary["catalog"] = runtime_req.catalog_id
                summary["operations"] = cost_tracker.by_operation(entries)
                return _cache_and_send({"ok": True, "summary": summary})
            if path == "/api/analytics/costs/by-book":
                period = _parse_period_token(query, default="30d")
                entries = _cost_entries_for_runtime(runtime=runtime_req, period=period)
                rows = cost_tracker.by_book(entries)
                limit, offset = _parse_pagination(query, default_limit=50, max_limit=1000)
                page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
                return _cache_and_send(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "period": period,
                        "books": page,
                        "count": len(page),
                        "pagination": pagination,
                    }
                )
            if path == "/api/analytics/costs/by-model":
                period = _parse_period_token(query, default="30d")
                entries = _cost_entries_for_runtime(runtime=runtime_req, period=period)
                rows = cost_tracker.by_model(entries)
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "period": period, "models": rows, "count": len(rows)})
            if path == "/api/analytics/costs/by-operation":
                period = _parse_period_token(query, default="30d")
                entries = _cost_entries_for_runtime(runtime=runtime_req, period=period)
                rows = cost_tracker.by_operation(entries)
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "period": period, "operations": rows, "count": len(rows)})
            if path == "/api/analytics/costs/timeline":
                period = _parse_period_token(query, default="30d")
                granularity = str(query.get("granularity", ["daily"])[0] or "daily").strip().lower() or "daily"
                entries = _cost_entries_for_runtime(runtime=runtime_req, period=period)
                rows = cost_tracker.timeline(entries, granularity=granularity)
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "period": period, "granularity": granularity, "timeline": rows, "count": len(rows)})
            if path == "/api/analytics/budget":
                status = _budget_status_for_runtime(runtime_req)
                return _cache_and_send({"ok": True, "budget": status})
            if path == "/api/analytics/quality/trends":
                period = _parse_period_token(query, default="30d")
                payload = _quality_trends_payload(runtime=runtime_req, period=period)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/quality/by-model":
                payload = _quality_by_model_payload(runtime=runtime_req)
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "models": payload.get("models", [])})
            if path == "/api/analytics/quality/by-prompt-pattern":
                payload = _quality_prompt_pattern_payload(runtime=runtime_req)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/quality/distribution":
                payload = _quality_distribution_payload(runtime=runtime_req)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/models/compare":
                payload = _quality_by_model_payload(runtime=runtime_req)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/models/recommendation":
                book = _safe_int(query.get("book", ["0"])[0], 0)
                payload = _model_recommendation_payload(runtime=runtime_req, book_number=book if book > 0 else None)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/prompts/effectiveness":
                payload = _quality_prompt_pattern_payload(runtime=runtime_req)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/quality/breakdown":
                book = _safe_int(query.get("book", ["0"])[0], 0)
                payload = _quality_breakdown_payload(runtime=runtime_req, book=book)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/completion":
                payload = _completion_payload(runtime=runtime_req)
                return _cache_and_send({"ok": True, **payload})
            if path == "/api/analytics/cost-projection":
                books_count = max(1, min(100000, _safe_int(query.get("books", ["1"])[0], 1)))
                max_variants = _max_generation_variants(runtime_req)
                variants = max(1, min(max_variants, _safe_int(query.get("variants", [str(runtime_req.variants_per_cover)])[0], runtime_req.variants_per_cover)))
                models_raw = str(query.get("models", [""])[0] or "").strip()
                models = [token.strip() for token in models_raw.split(",") if token.strip()] if models_raw else []
                if not models:
                    models = runtime_req.all_models[:1] if runtime_req.all_models else [runtime_req.ai_model]
                model_quality = _quality_by_model_payload(runtime=runtime_req).get("models", [])
                model_stats: dict[str, dict[str, Any]] = {}
                if isinstance(model_quality, list):
                    for row in model_quality:
                        if not isinstance(row, dict):
                            continue
                        key = str(row.get("model", "")).strip()
                        if not key:
                            continue
                        model_stats[key] = row

                per_model_images = books_count * variants
                breakdown: dict[str, dict[str, Any]] = {}
                total_cost = 0.0
                total_images = 0
                weighted_seconds = 0.0
                per_model_cost_rows: list[tuple[str, float]] = []

                for model in models:
                    model_name = str(model).strip()
                    if not model_name:
                        continue
                    cost_per_image = _safe_float(runtime_req.get_model_cost(model_name), 0.04)
                    images = per_model_images
                    subtotal = round(images * cost_per_image, 6)
                    total_cost += subtotal
                    total_images += images
                    seconds_per_image = _safe_float(model_stats.get(model_name, {}).get("avg_generation_time_seconds"), 22.0)
                    if seconds_per_image <= 0:
                        seconds_per_image = 22.0
                    weighted_seconds += seconds_per_image * images
                    per_model_cost_rows.append((model_name, cost_per_image))
                    breakdown[model_name] = {
                        "images": images,
                        "costPerImage": round(cost_per_image, 6),
                        "total": subtotal,
                    }

                avg_seconds_per_image = (weighted_seconds / total_images) if total_images > 0 else 22.0
                configured_workers = max(1, _safe_int(getattr(runtime_req, "job_workers", JOB_WORKER_COUNT), JOB_WORKER_COUNT))
                model_parallel = max(1, min(len(models), max(1, _safe_int(getattr(runtime_req, "batch_concurrency", 1), 1))))
                effective_parallel = max(1, configured_workers * model_parallel)
                estimated_time_hours = round((total_images * avg_seconds_per_image) / (effective_parallel * 3600.0), 3) if total_images > 0 else 0.0
                estimated_storage_gb = round((total_images * 0.00018), 3)

                recommendations: list[str] = []
                if per_model_cost_rows:
                    sorted_by_cost = sorted(per_model_cost_rows, key=lambda item: item[1])
                    cheapest_model, cheapest_cost = sorted_by_cost[0]
                    recommendations.append(f"Cheapest selected model: {cheapest_model} (${cheapest_cost:.4f}/image).")
                    if len(sorted_by_cost) > 1:
                        priciest_model, priciest_cost = sorted_by_cost[-1]
                        ratio = (priciest_cost / cheapest_cost) if cheapest_cost > 0 else 0.0
                        if ratio > 1.0:
                            recommendations.append(
                                f"{cheapest_model} is about {ratio:.1f}x cheaper than {priciest_model} for this run."
                            )
                recommendations.append(
                    f"At {effective_parallel} effective workers, estimated completion is about {estimated_time_hours:.2f} hours."
                )
                suggested_budget = round(total_cost * 1.2, 2)
                warning_budget = round(suggested_budget * 0.8, 2)
                recommendations.append(
                    f"Suggested batch budget: ${suggested_budget:.2f} with warning threshold around ${warning_budget:.2f}."
                )

                return _cache_and_send(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "books": books_count,
                        "variants": variants,
                        "models": models,
                        "totalImages": total_images,
                        "estimatedCostUsd": round(total_cost, 6),
                        "breakdown": breakdown,
                        "estimatedTimeHours": estimated_time_hours,
                        "estimatedStorageGb": estimated_storage_gb,
                        "effectiveParallelWorkers": effective_parallel,
                        "recommendations": recommendations,
                    }
                )
            if path == "/api/analytics/audit":
                limit, offset = _parse_pagination(query, default_limit=100, max_limit=5000)
                action_filter = str(query.get("action", [""])[0] or "").strip().lower()
                rows = audit_log.load_events(config.audit_log_path(catalog_id=runtime_req.catalog_id, data_dir=runtime_req.data_dir))
                if action_filter:
                    rows = [row for row in rows if str(row.get("action", "")).strip().lower() == action_filter]
                # Keep newest-first ordering.
                rows = list(reversed(rows))
                page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
                return _cache_and_send({"ok": True, "count": len(page), "items": page, "pagination": pagination})
            if path == "/api/analytics/reports/schedule":
                schedules_path = _report_schedules_path_for_runtime(runtime_req)
                payload = _load_json(schedules_path, {"schedules": []})
                schedules = payload.get("schedules", []) if isinstance(payload, dict) else []
                if not isinstance(schedules, list):
                    schedules = []
                return _cache_and_send({"ok": True, "count": len(schedules), "schedules": schedules})
            if path == "/api/analytics/reports":
                reports_dir = runtime_req.data_dir / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                rows = []
                for file_path in sorted(reports_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
                    if not file_path.is_file():
                        continue
                    rows.append(
                        {
                            "id": file_path.name,
                            "name": file_path.name,
                            "size_bytes": file_path.stat().st_size,
                            "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                            "path": _to_project_relative(file_path),
                            "download_url": f"/api/analytics/reports/{file_path.name}",
                        }
                    )
                return _cache_and_send({"ok": True, "count": len(rows), "reports": rows})
            if path.startswith("/api/analytics/reports/"):
                report_id = path.split("/api/analytics/reports/", 1)[1].strip()
                if not report_id:
                    return self._send_error(
                        code="REPORT_ID_REQUIRED",
                        message="report id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                if "/" in report_id or "\\" in report_id or ".." in report_id:
                    return self._send_error(
                        code="INVALID_REPORT_ID",
                        message="Invalid report id",
                        details={"report_id": report_id},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                report_path = runtime_req.data_dir / "reports" / report_id
                if not report_path.exists() or not report_path.is_file():
                    return self._send_error(
                        code="REPORT_NOT_FOUND",
                        message="report not found",
                        details={"report_id": report_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                content_type = "application/pdf" if report_path.suffix.lower() == ".pdf" else "application/json"
                return self._send_file(report_path, content_type=content_type, cache_control="no-store")
            if path == "/api/drive-status":
                return _cache_and_send(
                    {
                        **_save_raw_drive_status_payload(runtime=runtime_req),
                        "catalog": runtime_req.catalog_id,
                        "endpoint": path,
                    }
                )
            if path == "/api/drive/status" or path == "/api/drive/sync-status":
                source_default = (
                    getattr(runtime_req, "gdrive_source_folder_id", "")
                    or getattr(runtime_req, "gdrive_input_folder_id", "")
                    or runtime_req.gdrive_output_folder_id
                )
                drive_folder_id = str(query.get("drive_folder_id", [source_default])[0] or source_default).strip()
                input_folder_id = str(
                    query.get("input_folder_id", [getattr(runtime_req, "gdrive_source_folder_id", "") or getattr(runtime_req, "gdrive_input_folder_id", "")])[0]
                    or (getattr(runtime_req, "gdrive_source_folder_id", "") or getattr(runtime_req, "gdrive_input_folder_id", ""))
                ).strip()
                credentials_override = str(query.get("credentials_path", [""])[0]).strip()
                credentials_path = Path(credentials_override) if credentials_override else _resolve_credentials_path(runtime_req)
                if not credentials_path.is_absolute():
                    credentials_path = PROJECT_ROOT / credentials_path
                mode_hint, mode_error = _drive_credentials_mode(runtime_req, credentials_path=credentials_path)

                connected = False
                connection_error = mode_error
                mode = mode_hint
                if mode:
                    try:
                        auth_path = None if mode == "service_account_env" else credentials_path
                        gdrive_sync.authenticate(auth_path)
                        connected = True
                        connection_error = None
                    except Exception as exc:
                        connected = False
                        connection_error = str(exc)

                log_payload = _load_json(_drive_sync_log_path(runtime_req), {"items": []})
                sync_log = log_payload.get("items", []) if isinstance(log_payload, dict) else []
                if not isinstance(sync_log, list):
                    sync_log = []
                last_sync = sync_log[-1] if sync_log else {}
                try:
                    status = drive_manager.get_status(
                        output_root=runtime_req.output_dir,
                        input_root=runtime_req.input_dir,
                        exports_root=EXPORTS_ROOT,
                        drive_folder_id=drive_folder_id,
                        credentials_path=credentials_path,
                        last_sync=last_sync if isinstance(last_sync, dict) else {},
                    )
                except Exception as exc:
                    status = {"mode": "unavailable", "error": str(exc)}
                return _cache_and_send(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "endpoint": path,
                        "connected": connected,
                        "mode": mode,
                        "source_folder_id": str(source_default or ""),
                        "output_folder_id": str(runtime_req.gdrive_output_folder_id or ""),
                        "error": connection_error,
                        "drive_folder_id": drive_folder_id,
                        "input_folder_id": input_folder_id,
                        "status": status,
                        "schedule": _load_drive_schedule(runtime_req),
                        "recent_syncs": sync_log[-20:],
                    }
                )
            if path == "/api/drive/input-covers":
                source_default = (
                    getattr(runtime_req, "gdrive_source_folder_id", "")
                    or getattr(runtime_req, "gdrive_input_folder_id", "")
                    or runtime_req.gdrive_output_folder_id
                )
                drive_folder_id = str(
                    query.get(
                        "drive_folder_id",
                        [source_default],
                    )[0]
                    or source_default
                ).strip()
                input_folder_id = str(
                    query.get(
                        "input_folder_id",
                        [getattr(runtime_req, "gdrive_source_folder_id", "") or getattr(runtime_req, "gdrive_input_folder_id", "")],
                    )[0]
                    or (getattr(runtime_req, "gdrive_source_folder_id", "") or getattr(runtime_req, "gdrive_input_folder_id", ""))
                ).strip()
                credentials_override = str(query.get("credentials_path", [""])[0]).strip()
                credentials_path = Path(credentials_override) if credentials_override else _resolve_credentials_path(runtime_req)
                if not credentials_path.is_absolute():
                    credentials_path = PROJECT_ROOT / credentials_path
                limit = _safe_int(query.get("limit", ["500"])[0], 500)
                force = str(query.get("force", ["0"])[0] or "0").strip().lower() in {"1", "true", "yes", "on"}
                if force:
                    try:
                        drive_manager.clear_drive_cover_cache()
                    except Exception:
                        pass
                payload = drive_manager.list_input_covers(
                    drive_folder_id=drive_folder_id,
                    input_folder_id=input_folder_id,
                    credentials_path=credentials_path,
                    catalog_path=runtime_req.book_catalog_path,
                    limit=max(1, min(5000, limit)),
                )
                payload["ok"] = True
                payload["catalog"] = runtime_req.catalog_id
                return _cache_and_send(payload)
            if path == "/api/drive/schedule":
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "schedule": _load_drive_schedule(runtime_req)})
            if path == "/api/variant-download":
                book_number = _safe_int(query.get("book", ["0"])[0], 0)
                variant = _safe_int(query.get("variant", ["0"])[0], 0)
                model = str(query.get("model", [""])[0] or "").strip()
                if book_number <= 0 or variant <= 0:
                    return self._send_error(
                        code="INVALID_DOWNLOAD_REQUEST",
                        message="book and variant must be positive integers",
                        details={"book": query.get("book", [""])[0], "variant": query.get("variant", [""])[0]},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    logger.info(
                        "Building variant download ZIP: book=%d variant=%d model=%s",
                        book_number,
                        variant,
                        model,
                    )
                    zip_path, filename = _build_variant_download_zip(
                        runtime=runtime_req,
                        book_number=book_number,
                        variant=variant,
                        model=model,
                    )
                except FileNotFoundError as exc:
                    logger.error("Variant download failed: %s", exc)
                    return self._send_error(
                        code="VARIANT_FILES_NOT_FOUND",
                        message=str(exc),
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except Exception as exc:
                    logger.exception("Unexpected error building variant download ZIP")
                    return self._send_error(
                        code="DOWNLOAD_BUILD_ERROR",
                        message=f"Failed to build download package: {exc}",
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                return self._send_file(
                    zip_path,
                    content_type="application/zip",
                    cache_control="no-store",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            if path == "/api/winner-download":
                book_number = _safe_int(query.get("book", ["0"])[0], 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_DOWNLOAD_REQUEST",
                        message="book must be a positive integer",
                        details={"book": query.get("book", [""])[0]},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    zip_path, filename = _build_winner_download_zip(
                        runtime=runtime_req,
                        book_number=book_number,
                    )
                except FileNotFoundError as exc:
                    return self._send_error(
                        code="WINNER_NOT_FOUND",
                        message=str(exc),
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return self._send_file(
                    zip_path,
                    content_type="application/zip",
                    cache_control="no-store",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            if path == "/api/source-download":
                book_number = _safe_int(query.get("book", ["0"])[0], 0)
                variant = _safe_int(query.get("variant", ["0"])[0], 0)
                model = str(query.get("model", [""])[0] or "").strip()
                if book_number <= 0 or variant <= 0:
                    return self._send_error(
                        code="INVALID_SOURCE_DOWNLOAD_REQUEST",
                        message="book and variant must be positive integers",
                        details={"book": query.get("book", [""])[0], "variant": query.get("variant", [""])[0]},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    source_file, filename = _build_source_download_file(
                        runtime=runtime_req,
                        book_number=book_number,
                        variant=variant,
                        model=model,
                    )
                except FileNotFoundError as exc:
                    return self._send_error(
                        code="SOURCE_IMAGE_NOT_FOUND",
                        message=str(exc),
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                content_type = "image/png"
                if source_file.suffix.lower() in {".jpg", ".jpeg"}:
                    content_type = "image/jpeg"
                elif source_file.suffix.lower() == ".webp":
                    content_type = "image/webp"
                return self._send_file(
                    source_file,
                    content_type=content_type,
                    cache_control="no-store",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            if path == "/api/download-book":
                book_number = _safe_int(query.get("book", ["0"])[0], 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_DOWNLOAD_REQUEST",
                        message="book must be a positive integer",
                        details={"book": query.get("book", [""])[0]},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    zip_path, filename = _build_book_download_zip(runtime=runtime_req, book_number=book_number)
                except FileNotFoundError as exc:
                    return self._send_error(
                        code="BOOK_VARIANTS_NOT_FOUND",
                        message=str(exc),
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return self._send_file(
                    zip_path,
                    content_type="application/zip",
                    cache_control="no-store",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            if path == "/api/download-approved":
                try:
                    zip_path, filename = _build_approved_download_zip(runtime=runtime_req)
                except FileNotFoundError as exc:
                    return self._send_error(
                        code="APPROVED_VARIANTS_NOT_FOUND",
                        message=str(exc),
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return self._send_file(
                    zip_path,
                    content_type="application/zip",
                    cache_control="no-store",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
            if path == "/api/exports":
                payload = _exports_listing_payload(runtime=runtime_req)
                limit, offset = _parse_pagination(query, default_limit=50, max_limit=1000)
                page, pagination = _paginate_rows(payload.get("exports", []), limit=limit, offset=offset)
                payload["exports"] = page
                payload["pagination"] = pagination
                payload["count"] = len(page)
                return _cache_and_send(payload)
            if path.startswith("/api/exports/") and path.endswith("/download"):
                token = path.split("/api/exports/", 1)[1].split("/download", 1)[0].strip()
                if not token:
                    return self._send_error(
                        code="EXPORT_ID_REQUIRED",
                        message="export id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    zip_path = _build_export_zip(export_id=token, runtime=runtime_req)
                except FileNotFoundError:
                    return self._send_error(
                        code="EXPORT_NOT_FOUND",
                        message="export not found",
                        details={"export_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return self._send_file(zip_path, content_type="application/zip", cache_control="no-store")
            if path == "/api/delivery/status":
                cfg = delivery_pipeline.get_config(
                    catalog_id=runtime_req.catalog_id,
                    config_path=_delivery_config_path_for_runtime(runtime_req),
                )
                tracking = delivery_pipeline.get_tracking(
                    catalog_id=runtime_req.catalog_id,
                    tracking_path=_delivery_tracking_path_for_runtime(runtime_req),
                )
                return _cache_and_send(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "enabled": cfg.enabled,
                        "auto_push_to_drive": cfg.auto_push_to_drive,
                        "platforms": cfg.platforms,
                        "updated_at": cfg.updated_at,
                        "tracked_books": len(tracking),
                        "fully_delivered": sum(1 for row in tracking if bool(row.get("fully_delivered", False))),
                    }
                )
            if path == "/api/delivery/tracking":
                rows = delivery_pipeline.get_tracking(
                    catalog_id=runtime_req.catalog_id,
                    tracking_path=_delivery_tracking_path_for_runtime(runtime_req),
                )
                export_map = _export_status_by_book(runtime=runtime_req)
                merged_rows: list[dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    book = _safe_int(row.get("book_number"), 0)
                    exports = export_map.get(book, {})
                    changed = any(bool(item.get("changed_since_last_export", False)) for item in exports.values() if isinstance(item, dict))
                    merged_rows.append({**row, "exports": exports, "changed_since_last_export": changed})
                limit, offset = _parse_pagination(query, default_limit=50, max_limit=1000)
                page, pagination = _paginate_rows(merged_rows, limit=limit, offset=offset)
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "items": page, "count": len(page), "pagination": pagination})
            if path == "/api/export/status":
                rows = _export_status_rows(runtime=runtime_req)
                limit, offset = _parse_pagination(query, default_limit=50, max_limit=1000)
                page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "items": page, "count": len(page), "pagination": pagination})
            if path == "/api/archive/stats":
                return _cache_and_send(_archive_stats_payload(runtime=runtime_req))
            if path == "/api/storage/usage":
                return _cache_and_send(_storage_usage_payload(runtime=runtime_req))
            if path == "/api/batch-generate":
                limit, offset = _parse_pagination(query, default_limit=25, max_limit=500)
                return self._send_json(_batch_list_payload(runtime_req, limit=limit, offset=offset))
            if path.startswith("/api/batch-generate/") and path.endswith("/status"):
                token = path.split("/api/batch-generate/", 1)[1].split("/status", 1)[0].strip("/")
                if not token:
                    return self._send_error(
                        code="BATCH_ID_REQUIRED",
                        message="batch id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                limit, offset = _parse_pagination(query, default_limit=25, max_limit=1000)
                payload = _batch_status_payload(runtime_req, token, limit=limit, offset=offset)
                if payload is None:
                    return self._send_error(
                        code="BATCH_NOT_FOUND",
                        message="batch not found",
                        details={"batch_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return self._send_json(payload)
            if path.startswith("/api/events/batch/"):
                token = path.split("/api/events/batch/", 1)[1].strip("/")
                if not token:
                    return self._send_error(
                        code="BATCH_ID_REQUIRED",
                        message="batch id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                return self._serve_job_events(catalog_id=runtime_req.catalog_id, batch_id=token)
            if path.startswith("/api/events/job/"):
                token = path.split("/api/events/job/", 1)[1].strip("/")
                if not token:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                return self._serve_job_events(catalog_id=runtime_req.catalog_id, job_id=token)
            if path == "/api/jobs":
                limit, offset = _parse_pagination(query, default_limit=20, max_limit=500)
                raw_status = str(query.get("status", [""])[0] or "").strip()
                statuses = [token.strip() for token in raw_status.split(",") if token.strip()] if raw_status else None
                raw_types = str(query.get("type", [""])[0] or "").strip()
                job_types = {token.strip().lower() for token in raw_types.split(",") if token.strip()} if raw_types else set()
                book_filter = _safe_int(query.get("book", ["0"])[0], 0)
                jobs = job_db_store.list_jobs(
                    limit=500,
                    statuses=statuses,
                    catalog_id=runtime_req.catalog_id,
                    book_number=book_filter if book_filter > 0 else None,
                )
                if job_types:
                    jobs = [row for row in jobs if str(row.job_type).strip().lower() in job_types]
                rows = [job.to_dict() for job in jobs]
                page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
                return self._send_json(
                    {
                        "ok": True,
                        "jobs": page,
                        "count": len(page),
                        "pagination": pagination,
                        "limits": {
                            "default_variants_per_model": runtime_req.variants_per_cover,
                            "max_generation_variants": _max_generation_variants(runtime_req),
                        },
                    }
                )
            if path == "/api/jobs/active":
                jobs = job_db_store.list_jobs(
                    limit=500,
                    statuses=["queued", "running", "retrying", "paused"],
                    catalog_id=runtime_req.catalog_id,
                )
                return self._send_json({"ok": True, "jobs": [job.to_dict() for job in jobs], "count": len(jobs)})
            if path == "/api/generation-failures":
                limit = _safe_int(query.get("limit", ["20"])[0], 20)
                return self._send_json(_recent_generation_failures_payload(runtime=runtime_req, limit=limit))
            if path == "/api/jobs/events":
                return self._serve_job_events(catalog_id=runtime_req.catalog_id)
            if path.startswith("/api/jobs/"):
                job_id = path.split("/api/jobs/", 1)[1].strip()
                if not job_id:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                row = job_db_store.get_job(job_id)
                if row is None:
                    return self._send_error(
                        code="JOB_NOT_FOUND",
                        message="job not found",
                        details={"job_id": job_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                attempts = job_db_store.list_attempts(job_id)
                return self._send_json({"ok": True, "job": row.to_dict(), "attempts": attempts})
            if path == "/api/thumbnail":
                rel = _normalize_runtime_relative_asset_token(query.get("path", [""])[0])
                size_name = str(query.get("size", ["medium"])[0]).strip().lower()
                rel_val = api_validation.validate_non_empty_text(rel, field="path")
                if not rel_val.valid:
                    return self._send_error(
                        code=rel_val.error.code,
                        message=rel_val.error.message,
                        details=rel_val.error.details,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                size_val = api_validation.validate_enum(size_name, field="size", valid_values=set(thumbnail_server.ThumbnailServer.SIZES.keys()))
                if not size_val.valid:
                    return self._send_error(
                        code=size_val.error.code,
                        message=size_val.error.message,
                        details=size_val.error.details,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                thumb_runtime = thumbnail_server.ThumbnailServer(
                    project_root=PROJECT_ROOT,
                    cache_dir=runtime_req.tmp_dir / "thumbnails",
                    allowed_roots=[runtime_req.output_dir, runtime_req.input_dir, runtime_req.tmp_dir],
                )
                thumb = thumb_runtime.thumbnail_for(relative_path=rel, size=size_name)
                if thumb is None:
                    try:
                        if not security.sanitize_path(rel, PROJECT_ROOT).exists():
                            status_code = HTTPStatus.NOT_FOUND
                            message = "Requested thumbnail source was not found"
                        else:
                            status_code = HTTPStatus.BAD_REQUEST
                            message = "Requested thumbnail source is not in an allowed image directory"
                    except Exception:
                        status_code = HTTPStatus.BAD_REQUEST
                        message = "Requested thumbnail source is invalid"
                    return self._send_error(
                        code="THUMBNAIL_SOURCE_NOT_FOUND",
                        message=message,
                        details={"path": rel, "size": size_name},
                        status=status_code,
                        endpoint=path,
                    )
                return self._send_file(
                    thumb,
                    content_type="image/jpeg",
                    cache_control="no-store",
                )
            if path == "/api/asset":
                rel = _normalize_runtime_relative_asset_token(query.get("path", [""])[0])
                rel_val = api_validation.validate_non_empty_text(rel, field="path")
                if not rel_val.valid:
                    return self._send_error(
                        code=rel_val.error.code,
                        message=rel_val.error.message,
                        details=rel_val.error.details,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                return self._serve_project_relative(
                    f"/{rel}",
                    allowed_roots=[runtime_req.output_dir, runtime_req.input_dir, runtime_req.tmp_dir],
                    cache_control="no-store",
                )

            if path == "/api/review-data":
                limit, offset = _parse_pagination(query, default_limit=25, max_limit=500)
                sort, order = _normalize_sort_order(query)
                filters = _books_filters_from_query(query)
                with lock:
                    books = build_review_dataset(
                        runtime_req.output_dir,
                        input_dir=runtime_req.input_dir,
                        catalog_path=runtime_req.book_catalog_path,
                        quality_scores_path=_quality_scores_path_for_runtime(runtime_req),
                    )
                    winner_payload = _ensure_winner_payload(books, path=_winner_path_for_runtime(runtime_req))
                    winner_map = winner_payload.get("selections", {}) if isinstance(winner_payload, dict) else {}
                    meta_by_book = book_metadata.list_books(_book_metadata_path_for_runtime(runtime_req))
                    rows: list[dict[str, Any]] = []
                    for row in books:
                        if not isinstance(row, dict):
                            continue
                        book = _safe_int(row.get("number"), 0)
                        if book <= 0:
                            continue
                        selection = winner_map.get(str(book), {})
                        winner_variant = _safe_int(selection.get("winner") if isinstance(selection, dict) else selection, 0)
                        tags = meta_by_book.get(str(book), {}).get("tags", [])
                        status = "processed" if winner_variant > 0 else "pending"
                        enriched = dict(row)
                        enriched["status"] = status
                        enriched["tags"] = tags if isinstance(tags, list) else []
                        enriched["winner_variant"] = winner_variant
                        rows.append(enriched)

                    search = str(filters.get("search", "") or "").strip().lower()
                    if search:
                        rows = [
                            row
                            for row in rows
                            if search in str(row.get("title", "")).lower()
                            or search in str(row.get("author", "")).lower()
                        ]
                    wanted_status = str(filters.get("status", "") or "").strip().lower()
                    if wanted_status:
                        rows = [row for row in rows if str(row.get("status", "")).lower() == wanted_status]
                    tags_raw = str(filters.get("tags", "") or "").strip()
                    if tags_raw:
                        wanted_tags = {token.strip().lower() for token in tags_raw.split(",") if token.strip()}
                        rows = [
                            row
                            for row in rows
                            if wanted_tags.issubset({str(tag).strip().lower() for tag in row.get("tags", []) if str(tag).strip()})
                        ]
                    reverse = order == "desc"
                    if sort in {"title", "author", "status"}:
                        rows.sort(key=lambda item: str(item.get(sort, "")).lower(), reverse=reverse)
                    elif sort in {"quality_score"}:
                        rows.sort(key=lambda item: _safe_float(item.get("quality_score"), 0.0), reverse=reverse)
                    else:
                        rows.sort(key=lambda item: _safe_int(item.get("number"), 0), reverse=reverse)

                    books_page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
                    payload = {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "catalog": runtime_req.catalog_id,
                        "books": books_page,
                        "total_books": len(rows),
                        "pagination": pagination,
                        "winner_selections": winner_payload.get("selections", {}),
                    }
                    persisted_payload = dict(payload)
                    persisted_payload["books"] = rows
                    persisted_payload["pagination"] = _pagination_payload(total=len(rows), limit=len(rows) or 1, offset=0)
                    review_data_path = _review_data_path_for_runtime(runtime_req)
                    review_data_path.parent.mkdir(parents=True, exist_ok=True)
                    safe_json.atomic_write_json(review_data_path, persisted_payload)
                return _cache_and_send(payload)
            if path == "/api/iterate-data":
                limit, offset = _parse_pagination(query, default_limit=25, max_limit=50000)
                sort, order = _normalize_sort_order(query)
                filters = _books_filters_from_query(query)
                view = str(query.get("view", [""])[0] or "").strip().lower()
                if view == "books":
                    write_iterate_books_data(runtime=runtime_req)
                    payload = _load_json(_iterate_books_data_path_for_runtime(runtime_req), {"books": []})
                else:
                    write_iterate_data(runtime=runtime_req)
                    payload = _load_json(_iterate_data_path_for_runtime(runtime_req), {"books": [], "models": []})
                books = payload.get("books", []) if isinstance(payload, dict) else []
                if not isinstance(books, list):
                    books = []
                rows = [dict(row) for row in books if isinstance(row, dict)]
                search = str(filters.get("search", "") or "").strip().lower()
                if search:
                    rows = [
                        row
                        for row in rows
                        if search in str(row.get("title", "")).lower()
                        or search in str(row.get("author", "")).lower()
                        or search in str(row.get("number", "")).lower()
                    ]
                status = str(filters.get("status", "") or "").strip().lower()
                if status:
                    rows = [row for row in rows if str(row.get("status", "")).strip().lower() == status]
                reverse = order == "desc"
                if sort in {"title", "author", "status"}:
                    rows.sort(key=lambda item: str(item.get(sort, "")).lower(), reverse=reverse)
                else:
                    rows.sort(key=lambda item: _safe_int(item.get("number"), 0), reverse=reverse)
                page, pagination = _paginate_rows(rows, limit=limit, offset=offset)
                if view == "books":
                    return _cache_and_send(
                        {
                            "generated_at": payload.get("generated_at"),
                            "catalog": runtime_req.catalog_id,
                            "catalogs": [item.to_dict() for item in config.list_catalogs()],
                            "books": page,
                            "total_books": len(rows),
                            "pagination": pagination,
                        }
                    )
                payload["books"] = page
                payload["total_books"] = len(rows)
                payload["pagination"] = pagination
                payload["catalog"] = runtime_req.catalog_id
                payload["catalogs"] = [item.to_dict() for item in config.list_catalogs()]
                return _cache_and_send(payload)
            if path == "/api/enrichment-health":
                return _cache_and_send(_enrichment_health_payload(runtime=runtime_req))
            if path == "/api/cover-regions":
                regions_path = config.cover_regions_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir)
                payload = _load_json(
                    regions_path,
                    {
                        "covers": [],
                        "consensus_region": {
                            "center_x": 2864,
                            "center_y": 1620,
                            "radius": 500,
                        },
                    },
                )
                if not isinstance(payload, dict):
                    payload = {
                        "covers": [],
                        "consensus_region": {
                            "center_x": 2864,
                            "center_y": 1620,
                            "radius": 500,
                        },
                    }
                payload["catalog"] = runtime_req.catalog_id
                return _cache_and_send(payload)
            if path == "/api/config/cover-source-default":
                default_source = _default_cover_source_for_runtime(runtime_req)
                return _cache_and_send(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "default": default_source,
                        "local_input_covers_available": _has_local_input_covers(runtime=runtime_req),
                    }
                )
            if path == "/api/prompt-performance":
                payload = _load_json(_prompt_performance_path_for_runtime(runtime_req), {"patterns": {}})
                if not isinstance(payload, dict):
                    payload = {"patterns": {}}
                return _cache_and_send(payload)
            if path == "/api/prompts":
                query_text = str(query.get("q", [""])[0] or "").strip()
                category = str(query.get("category", [""])[0] or "").strip().lower()
                tags = [token.strip() for token in str(query.get("tags", [""])[0] or "").split(",") if token.strip()]
                payload = _prompt_library_payload(runtime=runtime_req, query_text=query_text, category=category, tags=tags)
                return _cache_and_send(payload)
            if path == "/api/prompts/export":
                payload = _prompt_library_export_payload(runtime=runtime_req)
                return self._send_json(payload)
            if path.startswith("/api/prompts/") and path.endswith("/versions"):
                token = path.split("/api/prompts/", 1)[1].split("/versions", 1)[0].strip()
                if not token:
                    return self._send_error(
                        code="PROMPT_ID_REQUIRED",
                        message="prompt id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    payload = _prompt_versions_payload(runtime=runtime_req, prompt_id=token)
                except KeyError:
                    return self._send_error(
                        code="PROMPT_NOT_FOUND",
                        message="Prompt not found",
                        details={"prompt_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return _cache_and_send(payload)
            if path == "/api/analytics/ab-tests":
                limit = _safe_int(query.get("limit", ["200"])[0], 200)
                rows = _load_ab_test_rows(runtime=runtime_req)
                if limit > 0:
                    rows = rows[-max(1, min(2000, limit)) :]
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "items": rows, "count": len(rows)})
            if path == "/api/health":
                payload = _health_payload(runtime=runtime_req)
                payload["default_reviewer"] = configured_reviewer
                return _cache_and_send(payload)
            if path == "/api/history":
                book = int(query.get("book", ["0"])[0])
                history_payload = _load_json(_history_path_for_runtime(runtime_req), {"items": []})
                items = [item for item in history_payload.get("items", []) if int(item.get("book_number", 0)) == book]
                return _cache_and_send({"items": items[-200:]})
            if path == "/api/generation-history":
                limit, offset = _parse_pagination(query, default_limit=50, max_limit=1000)
                if runtime_req.use_sqlite:
                    repo = _repository_for_runtime(runtime_req)
                    rows, total = repo.list_generation_history(
                        catalog_id=runtime_req.catalog_id,
                        limit=limit,
                        offset=offset,
                        filters={
                            "book": query.get("book", [""])[0],
                            "model": query.get("model", [""])[0],
                            "provider": query.get("provider", [""])[0],
                            "status": query.get("status", [""])[0],
                        },
                    )
                    if rows or total > 0:
                        return _cache_and_send(
                            {
                                "items": rows,
                                "total": total,
                                "pagination": _pagination_payload(total=total, limit=limit, offset=offset),
                            }
                        )
                    # Fallback to state history if repository has no rows yet for this catalog.
                filters = query
                items = _load_generation_records(runtime=runtime_req)
                filtered = _filter_generation_records(items, filters=filters)
                page, pagination = _paginate_rows(filtered, limit=limit, offset=offset)
                return _cache_and_send({"items": page, "total": len(filtered), "pagination": pagination})
            if path == "/api/dashboard-data":
                payload = _build_dashboard_payload(_load_generation_records(runtime=runtime_req), runtime=runtime_req)
                return _cache_and_send(payload)
            if path == "/api/weak-books":
                threshold = _safe_float(query.get("threshold", ["0.75"])[0], 0.75)
                payload = _build_weak_books_payload(runtime=runtime_req, threshold=threshold)
                return _cache_and_send(payload)
            if path == "/api/regeneration-results":
                book = _safe_int(query.get("book", ["0"])[0], 0)
                payload = _load_json(_regeneration_results_path_for_runtime(runtime_req), {"details": []})
                details = payload.get("details", []) if isinstance(payload, dict) else []
                if book > 0 and isinstance(details, list):
                    details = [row for row in details if isinstance(row, dict) and _safe_int(row.get("book"), 0) == book]
                return _cache_and_send({"book": book if book > 0 else None, "results": details, "raw": payload})
            if path == "/api/similarity/recompute/status":
                status_payload = _similarity_recompute_snapshot(catalog_id=runtime_req.catalog_id)
                return _cache_and_send(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "recompute": status_payload,
                    }
                )
            if path == "/api/similarity-matrix":
                threshold = _safe_float(query.get("threshold", ["0.25"])[0], 0.25)
                matrix_payload = _load_similarity_matrix(runtime_req=runtime_req, threshold=threshold)
                pairs = matrix_payload.get("pairs", []) if isinstance(matrix_payload, dict) else []
                if not isinstance(pairs, list):
                    pairs = []
                limit, offset = _parse_pagination(query, default_limit=50, max_limit=1000)
                page, pagination = _paginate_rows([row for row in pairs if isinstance(row, dict)], limit=limit, offset=offset)
                output = dict(matrix_payload) if isinstance(matrix_payload, dict) else {"pairs": []}
                output["pairs"] = page
                output["pagination"] = pagination
                output["total_pairs"] = len(pairs)
                return _cache_and_send(output)
            if path == "/api/similarity-alerts":
                threshold = _safe_float(query.get("threshold", ["0.25"])[0], 0.25)
                matrix_payload = _load_similarity_matrix(runtime_req=runtime_req, threshold=threshold)
                dismissed = similarity_detector.load_dismissed_pairs(_similarity_dismissed_path_for_runtime(runtime_req))
                alerts = []
                for row in matrix_payload.get("pairs", []):
                    if not isinstance(row, dict):
                        continue
                    a = _safe_int(row.get("book_a"), 0)
                    b = _safe_int(row.get("book_b"), 0)
                    pair_key = f"{min(a, b)}-{max(a, b)}"
                    if pair_key in dismissed:
                        continue
                    similarity = _safe_float(row.get("similarity"), 1.0)
                    if similarity < threshold:
                        alerts.append(row)
                return _cache_and_send({"threshold": threshold, "alerts": alerts, "count": len(alerts)})
            if path == "/api/similarity-clusters":
                threshold = _safe_float(query.get("threshold", ["0.25"])[0], 0.25)
                _load_similarity_matrix(runtime_req=runtime_req, threshold=threshold)
                clusters = _load_json(_similarity_clusters_path_for_runtime(runtime_req), {"clusters": []})
                if not isinstance(clusters, dict):
                    clusters = {"clusters": []}
                return _cache_and_send(clusters)
            if path.startswith("/api/cover-hash/"):
                book = _safe_int(path.split("/api/cover-hash/", 1)[1], 0)
                if book <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="Book number must be a positive integer",
                        details={"received": path.split("/api/cover-hash/", 1)[1]},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                _load_similarity_matrix(runtime_req=runtime_req, threshold=0.25)
                payload = _load_json(_similarity_hashes_path_for_runtime(runtime_req), {"books": {}})
                books = payload.get("books", {}) if isinstance(payload, dict) else {}
                if not isinstance(books, dict):
                    books = {}
                row = books.get(f"book_{book}")
                if not isinstance(row, dict):
                    return self._send_error(
                        code="COVER_HASH_NOT_FOUND",
                        message=f"No hash for book {book}",
                        details={"book": book},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return _cache_and_send({"ok": True, "book": book, "hash": row})
            if path == "/api/review-queue":
                threshold = _safe_float(query.get("threshold", ["0.90"])[0], 0.90)
                payload = _build_review_queue(runtime=runtime_req, threshold=threshold)
                payload["default_reviewer"] = configured_reviewer
                return _cache_and_send(payload)
            if path.startswith("/api/books/") and path.endswith("/cover-preview"):
                token = path.split("/api/books/", 1)[1].rsplit("/cover-preview", 1)[0].strip("/")
                book_number = _safe_int(token, 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book number must be a positive integer",
                        details={"received": token},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                source = str(query.get("source", [_default_cover_source_for_runtime(runtime_req)])[0] or "").strip().lower()
                if source not in {"catalog", "drive"}:
                    source = _default_cover_source_for_runtime(runtime_req)
                selected_cover_id = str(query.get("selected_cover_id", [""])[0] or "").strip()
                source_path, resolve_status, resolve_meta = _resolve_cover_preview_source_path(
                    runtime=runtime_req,
                    book_number=book_number,
                    source=source,
                    selected_cover_id=selected_cover_id,
                    drive_folder_id=str(query.get("drive_folder_id", [""])[0] or "").strip(),
                    input_folder_id=str(query.get("input_folder_id", [""])[0] or "").strip(),
                    credentials_path_token=str(query.get("credentials_path", [""])[0] or "").strip(),
                )
                if source_path is None or not source_path.exists():
                    return self._send_error(
                        code="COVER_PREVIEW_NOT_AVAILABLE",
                        message=str(resolve_meta.get("error") or f"No source cover is available for book {book_number}."),
                        details={"book": int(book_number), "source": source},
                        status=HTTPStatus(resolve_status),
                        endpoint=path,
                    )
                preview_path = _cover_preview_path_for_runtime(runtime=runtime_req, book_number=book_number, source=source)
                try:
                    if (not preview_path.exists()) or (preview_path.stat().st_mtime < source_path.stat().st_mtime):
                        _write_cover_preview(source_image=source_path, preview_path=preview_path)
                except Exception as exc:
                    return self._send_error(
                        code="COVER_PREVIEW_FAILED",
                        message=f"Failed to build cover preview: {exc}",
                        details={"book": int(book_number), "source": source},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                return self._send_file(preview_path, content_type="image/jpeg", cache_control="no-store")
            if path == "/api/visual-qa":
                force = str(query.get("force", ["0"])[0] or "").strip().lower() in {"1", "true", "yes", "on"}
                book_filter = _safe_int(query.get("book_number", ["0"])[0], 0)
                payload = _load_visual_qa_payload(
                    runtime=runtime_req,
                    force_generate=force,
                    book_number=book_filter if book_filter > 0 else None,
                )
                return _cache_and_send(payload)
            if path.startswith("/api/visual-qa/image/"):
                token = path.split("/api/visual-qa/image/", 1)[1].strip().split("/", 1)[0]
                book_number = _safe_int(token, 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book number must be a positive integer",
                        details={"received": token},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    image_path = _visual_qa_image_path(runtime=runtime_req, book_number=book_number)
                except Exception as exc:
                    logger.exception("Failed to resolve visual QA image for book %s", book_number)
                    return self._send_error(
                        code="VISUAL_QA_IMAGE_ERROR",
                        message=f"Failed to load visual QA comparison image: {exc}",
                        details={"book_number": book_number},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                if image_path is None or not image_path.exists():
                    payload = _load_visual_qa_payload(runtime=runtime_req, book_number=book_number)
                    return self._send_error(
                        code="VISUAL_QA_IMAGE_NOT_FOUND",
                        message=str(payload.get("message") or "No generated images available for this book. Generate covers first."),
                        details={"book_number": book_number},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                try:
                    return self._send_file(image_path, content_type="image/jpeg", cache_control="no-store")
                except Exception as exc:
                    logger.exception("Failed to serve visual QA image for book %s", book_number)
                    return self._send_error(
                        code="VISUAL_QA_IMAGE_ERROR",
                        message=f"Failed to serve visual QA comparison image: {exc}",
                        details={"book_number": book_number},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
            if path == "/api/compare":
                books_raw = str(query.get("books", [""])[0]).strip()
                books = _parse_books(books_raw) or []
                books = books[:4]
                payload = _compare_payload(runtime=runtime_req, books=books)
                return _cache_and_send(payload)
            if path == "/api/books":
                limit, offset = _parse_pagination(query, default_limit=25, max_limit=500)
                sort, order = _normalize_sort_order(query)
                if runtime_req.use_sqlite:
                    repo = _repository_for_runtime(runtime_req)
                    rows, total = repo.list_books(
                        catalog_id=runtime_req.catalog_id,
                        limit=limit,
                        offset=offset,
                        filters=_books_filters_from_query(query),
                        sort=sort,
                        order=order,
                    )
                    return _cache_and_send(
                        {
                            "ok": True,
                            "catalog": runtime_req.catalog_id,
                            "books": rows,
                            "count": len(rows),
                            "pagination": _pagination_payload(total=total, limit=limit, offset=offset),
                        }
                    )
                tags_raw = str(query.get("tags", [""])[0]).strip()
                tags = [token.strip() for token in tags_raw.split(",") if token.strip()] if tags_raw else []
                search = str(query.get("search", [""])[0] or "").strip().lower()
                wanted_status = str(query.get("status", [""])[0] or "").strip().lower()
                quality_min = query.get("quality_min", [None])[0]
                quality_max = query.get("quality_max", [None])[0]
                review_rows = build_review_dataset(
                    runtime_req.output_dir,
                    input_dir=runtime_req.input_dir,
                    catalog_path=runtime_req.book_catalog_path,
                    quality_scores_path=_quality_scores_path_for_runtime(runtime_req),
                )
                meta_path = _book_metadata_path_for_runtime(runtime_req)
                metadata_rows = book_metadata.list_books(meta_path)
                out: list[dict[str, Any]] = []
                for row in review_rows:
                    book = _safe_int(row.get("number"), 0)
                    key = str(book)
                    meta = metadata_rows.get(key, {})
                    current_tags = meta.get("tags", []) if isinstance(meta.get("tags"), list) else []
                    if tags:
                        current_tag_set = {str(item).strip().lower() for item in current_tags if str(item).strip()}
                        wanted = {str(item).strip().lower() for item in tags if str(item).strip()}
                        if not wanted.issubset(current_tag_set):
                            continue
                    status = "processed" if bool(row.get("variants")) else "pending"
                    if wanted_status and status != wanted_status:
                        continue
                    if search and search not in str(row.get("title", "")).lower() and search not in str(row.get("author", "")).lower():
                        continue
                    best_quality = 0.0
                    for variant_row in row.get("variants", []):
                        if not isinstance(variant_row, dict):
                            continue
                        best_quality = max(best_quality, _safe_float(variant_row.get("quality_score"), 0.0))
                    if quality_min is not None and best_quality < _safe_float(quality_min, 0.0):
                        continue
                    if quality_max is not None and best_quality > _safe_float(quality_max, 1.0e9):
                        continue
                    out.append(
                        {
                            "book": book,
                            "title": row.get("title", ""),
                            "author": row.get("author", ""),
                            "tags": current_tags,
                            "notes": meta.get("notes", ""),
                            "status": status,
                            "quality_score": round(best_quality, 6),
                            "variants": row.get("variants", []),
                        }
                    )
                reverse = order == "desc"
                if sort in {"title", "author", "status"}:
                    out.sort(key=lambda item: str(item.get(sort, "")).lower(), reverse=reverse)
                elif sort in {"quality_score"}:
                    out.sort(key=lambda item: _safe_float(item.get("quality_score"), 0.0), reverse=reverse)
                else:
                    out.sort(key=lambda item: _safe_int(item.get("book"), 0), reverse=reverse)
                page, pagination = _paginate_rows(out, limit=limit, offset=offset)
                return _cache_and_send({"ok": True, "catalog": runtime_req.catalog_id, "books": page, "count": len(page), "pagination": pagination})
            if path.startswith("/api/books/") and path.endswith("/notes"):
                token = path.split("/api/books/", 1)[1].split("/notes", 1)[0].strip()
                book_number = _safe_int(token, 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book number must be positive",
                        details={"book": token},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                meta = book_metadata.get_book(_book_metadata_path_for_runtime(runtime_req), book_number)
                return _cache_and_send({"ok": True, "book": book_number, "notes": meta.get("notes", "")})
            if path.startswith("/api/review-session/"):
                session_id = path.split("/api/review-session/", 1)[1].strip()
                if not session_id:
                    return self._send_error(
                        code="SESSION_ID_REQUIRED",
                        message="session_id required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                session_path = _review_sessions_dir_for_runtime(runtime_req) / f"{session_id}.json"
                payload = _load_json(session_path, {})
                if not isinstance(payload, dict) or not payload:
                    return self._send_error(
                        code="SESSION_NOT_FOUND",
                        message="session not found",
                        details={"session_id": session_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                return _cache_and_send({"ok": True, "session": payload})
            if path == "/api/review-stats":
                payload = _load_json(_review_stats_path_for_runtime(runtime_req), {"sessions": []})
                if not isinstance(payload, dict):
                    payload = {"sessions": []}
                return _cache_and_send(payload)
            if path == "/api/mockup-status":
                payload = mockup_generator.mockup_status(output_dir=runtime_req.output_dir)
                payload["catalog"] = runtime_req.catalog_id
                # Paginate large book lists for scale-mode catalogs.
                books = payload.get("books", []) if isinstance(payload, dict) else []
                if isinstance(books, list):
                    limit, offset = _parse_pagination(query, default_limit=25, max_limit=500)
                    page, pagination = _paginate_rows([row for row in books if isinstance(row, dict)], limit=limit, offset=offset)
                    payload["books"] = page
                    payload["pagination"] = pagination
                    payload["total_books"] = len(books)
                return _cache_and_send(payload)
            if path.startswith("/api/mockup/"):
                suffix = path.split("/api/mockup/", 1)[1]
                if not suffix:
                    return self._send_json({"ok": False, "error": "book/template required"}, status=HTTPStatus.BAD_REQUEST)
                parts = [part for part in suffix.split("/") if part]
                if len(parts) < 2:
                    return self._send_json(
                        {"ok": False, "error": "Path must be /api/mockup/{book}/{template}"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                book = _safe_int(parts[0], 0)
                template = parts[1]
                if book <= 0 or not template:
                    return self._send_json({"ok": False, "error": "Invalid book/template"}, status=HTTPStatus.BAD_REQUEST)

                records = mockup_generator.load_book_records(runtime_req.book_catalog_path)
                record = records.get(book)
                if not record:
                    return self._send_json({"ok": False, "error": f"Book {book} not found"}, status=HTTPStatus.NOT_FOUND)

                image_path = runtime_req.output_dir / "Mockups" / record.folder_name / f"{template}.jpg"
                if not image_path.exists():
                    image_path = runtime_req.output_dir / "Mockups" / record.folder_name / f"{template}.png"
                if not image_path.exists():
                    return self._send_json(
                        {"ok": False, "error": f"Mockup not found for book {book} template {template}"},
                        status=HTTPStatus.NOT_FOUND,
                    )

                rel = _to_project_relative(image_path)
                return self._serve_project_relative(
                    f"/{rel}",
                    allowed_roots=[runtime_req.output_dir / "Mockups"],
                    cache_control="public, max-age=86400",
                )
            if path == "/api/mockup-zip":
                book = _safe_int(query.get("book", ["0"])[0], 0)
                if book <= 0:
                    return self._send_json({"ok": False, "error": "book query is required"}, status=HTTPStatus.BAD_REQUEST)
                try:
                    zip_path = mockup_generator.build_mockup_zip(book_number=book, output_dir=runtime_req.output_dir)
                except Exception as exc:
                    return self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                rel = _to_project_relative(zip_path)
                return self._send_json({"ok": True, "book": book, "path": rel, "url": f"/{rel}"})
            if path == "/api/generate-catalog":
                mode = str(query.get("mode", ["catalog"])[0]).strip().lower()
                if mode not in {"catalog", "contact_sheet", "all_variants"}:
                    return self._send_json(
                        {"ok": False, "error": "mode must be one of: catalog, contact_sheet, all_variants"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                catalog_out, contact_out, all_variants_out = _catalog_outputs_for_runtime(runtime_req)
                output_path = catalog_out
                cmd = [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "generate_catalog.py"),
                    "--catalog",
                    runtime_req.catalog_id,
                    "--output-dir",
                    str(runtime_req.output_dir),
                    "--selections",
                    str(_winner_path_for_runtime(runtime_req)),
                    "--quality-data",
                    str(_quality_scores_path_for_runtime(runtime_req)),
                ]
                if mode == "contact_sheet":
                    output_path = contact_out
                    cmd.append("--contact-sheet")
                elif mode == "all_variants":
                    output_path = all_variants_out
                    cmd.append("--all-variants")

                cmd.extend(["--catalog-output", str(output_path)])
                completed = subprocess.run(cmd, capture_output=True, text=True)
                if completed.returncode != 0:
                    return self._send_json(
                        {
                            "ok": False,
                            "error": (completed.stderr or completed.stdout or "Catalog generation failed").strip(),
                            "mode": mode,
                        },
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )

                exists = output_path.exists()
                rel_path = _to_project_relative(output_path) if exists else str(output_path)
                size_mb = round(output_path.stat().st_size / (1024 * 1024), 3) if exists else 0.0
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="catalog_pdf",
                    cost_usd=0.0,
                    model="generate_catalog",
                    provider="local",
                    book_number=0,
                    images_generated=0,
                    duration_seconds=0.0,
                    metadata={"mode": mode, "size_mb": size_mb, "output_path": rel_path},
                )
                return self._send_json(
                    {
                        "ok": exists,
                        "mode": mode,
                        "output_path": rel_path,
                        "download_url": f"/{rel_path}" if exists else None,
                        "size_mb": size_mb,
                        "stdout": completed.stdout.strip(),
                    }
                )

            return self._send_error(
                code="ENDPOINT_NOT_FOUND",
                message="Unknown endpoint",
                status=HTTPStatus.NOT_FOUND,
                endpoint=path,
            )

        def do_OPTIONS(self):
            self.send_response(HTTPStatus.OK)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Token, X-Request-Id")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            self._request_started_at = time.perf_counter()
            self._request_method = "POST"
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            self._request_path = str(path)
            self._set_active_runtime(None)
            self._set_request_id(str(self.headers.get("X-Request-Id", "")).strip() or str(uuid.uuid4()))
            size = int(self.headers.get("Content-Length", "0"))
            body_raw = self.rfile.read(size) if size > 0 else b""
            body: dict[str, Any] = {}
            if body_raw.strip():
                try:
                    parsed_body = json.loads(body_raw.decode("utf-8"))
                except json.JSONDecodeError:
                    return self._send_error(
                        code="INVALID_JSON_BODY",
                        message="Request body must be valid JSON",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                if not isinstance(parsed_body, dict):
                    return self._send_error(
                        code="INVALID_JSON_BODY",
                        message="Request JSON body must be an object",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                body = parsed_body
            requested_catalog_raw = str(body.get("catalog", query.get("catalog", [default_runtime.catalog_id])[0])).strip()
            try:
                requested_catalog = security.validate_catalog_id(requested_catalog_raw) if requested_catalog_raw else default_runtime.catalog_id
            except ValueError:
                return self._send_error(
                    code="INVALID_CATALOG_ID",
                    message="Invalid catalog id",
                    details={"catalog": requested_catalog_raw},
                    status=HTTPStatus.BAD_REQUEST,
                    endpoint=path,
                )
            runtime_req = config.get_config(requested_catalog or default_runtime.catalog_id)
            self._set_active_runtime(runtime_req)
            client_ip = str(self.client_address[0] if self.client_address else "unknown")

            if path == "/cgi-bin/settings.py":
                current = _load_json(SETTINGS_STORE_PATH, {})
                if not isinstance(current, dict):
                    current = {}
                current.update(body)
                SETTINGS_STORE_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
                return self._send_json(current)

            if path == "/cgi-bin/settings.py/reset":
                if SETTINGS_STORE_PATH.exists():
                    SETTINGS_STORE_PATH.unlink()
                return self._send_json({"status": "reset"})

            if path == "/cgi-bin/catalog.py/refresh":
                write_iterate_data(runtime=runtime_req)
                iterate_payload = _load_json(_iterate_data_path_for_runtime(runtime_req), {"books": []})
                rows = iterate_payload.get("books", []) if isinstance(iterate_payload, dict) else []
                books: list[dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    number = _safe_int(row.get("number"), 0)
                    if number <= 0:
                        continue
                    books.append(
                        {
                            "id": number,
                            "number": number,
                            "title": str(row.get("title", "")),
                            "author": str(row.get("author", "")),
                            "folder_name": str(row.get("folder", row.get("folder_name", ""))),
                            "cover_jpg_id": str(row.get("cover_jpg_id", "")),
                            "cover_name": str(row.get("cover_name", "")),
                            "synced_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                books.sort(key=lambda item: _safe_int(item.get("number"), 0))
                payload = {
                    "books": books,
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "count": len(books),
                }
                CGI_CATALOG_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                return self._send_json(payload)

            if path == "/api/drive/catalog-sync":
                force = bool(body.get("force", True))
                limit = _safe_int(body.get("limit", query.get("limit", ["5000"])[0]), 5000)
                try:
                    summary = _sync_catalog_from_drive(
                        runtime=runtime_req,
                        force=force,
                        limit=max(1, min(50000, limit)),
                    )
                except Exception as exc:
                    return self._send_error(
                        code="DRIVE_CATALOG_SYNC_FAILED",
                        message=str(exc),
                        details={"catalog": runtime_req.catalog_id},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                summary["auto_enrichment"] = _queue_auto_enrichment_for_books(
                    runtime=runtime_req,
                    books=summary.get("added_books", []) if isinstance(summary, dict) else [],
                )
                return self._send_json(summary)

            if MUTATION_API_TOKEN:
                supplied = str(self.headers.get("X-API-Token", "")).strip()
                if not supplied:
                    supplied = str(query.get("token", [""])[0]).strip()
                if supplied != MUTATION_API_TOKEN:
                    return self._send_error(
                        code="UNAUTHORIZED",
                        message="Valid API token required for mutation endpoints",
                        status=HTTPStatus.UNAUTHORIZED,
                        endpoint=path,
                    )

            limiter, limit_per_minute = _mutation_limiter(path, catalog_id=runtime_req.catalog_id)
            if not limiter.allow(f"{client_ip}:{path}"):
                return self._send_error(
                    code="RATE_LIMITED",
                    message="Too many write requests. Please retry shortly.",
                    details={"path": path, "limit_per_minute": limit_per_minute},
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                    endpoint=path,
                    headers={"Retry-After": "60"},
                )

            if path == "/api/visual-qa/generate":
                book_number = _safe_int(
                    body.get("book_number", body.get("book", query.get("book_number", ["0"])[0])),
                    0,
                )
                try:
                    payload = _generate_visual_qa(
                        runtime=runtime_req,
                        book_number=book_number if book_number > 0 else None,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="VISUAL_QA_GENERATION_FAILED",
                        message=str(exc),
                        details={"book_number": book_number if book_number > 0 else None},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                _invalidate_cache("/api/visual-qa", catalog_id=runtime_req.catalog_id)
                summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
                return self._send_json(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "generated_at": str(payload.get("generated_at", datetime.now(timezone.utc).isoformat())),
                        "generated": _safe_int(summary.get("generated"), 0),
                        "passed": _safe_int(summary.get("passed"), 0),
                        "failed": _safe_int(summary.get("failed"), 0),
                        "not_compared": _safe_int(summary.get("not_compared"), 0),
                        "summary": summary,
                    }
                )

            if path == "/api/catalogs/import":
                bundle = body.get("bundle", body if isinstance(body, dict) else {})
                if not isinstance(bundle, dict):
                    return self._send_error(
                        code="CATALOG_IMPORT_INVALID",
                        message="bundle payload must be an object",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                catalog_block = bundle.get("catalog", bundle)
                if not isinstance(catalog_block, dict):
                    catalog_block = {}
                catalog_name = str(catalog_block.get("name", bundle.get("name", ""))).strip()
                if not catalog_name:
                    return self._send_error(
                        code="CATALOG_NAME_REQUIRED",
                        message="Catalog name is required for import",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    created = catalog_registry.create_catalog(
                        name=catalog_name,
                        description=str(catalog_block.get("description", "")),
                        input_dir=str(catalog_block.get("input_dir", "Input Covers")),
                        output_dir=str(catalog_block.get("output_dir", "Output Covers")),
                        config_dir=str(catalog_block.get("config_dir", "config")),
                        catalog_id=str(catalog_block.get("id", catalog_block.get("catalog_id", ""))).strip() or None,
                    )
                    settings = bundle.get("settings", {})
                    if isinstance(settings, dict) and settings:
                        catalog_registry.update_settings(created.catalog_id, settings)
                except Exception as exc:
                    return self._send_error(
                        code="CATALOG_IMPORT_FAILED",
                        message=str(exc),
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                _invalidate_cache("/api/catalogs")
                return self._send_json({"ok": True, "catalog": created.to_dict(), "imported": True})

            if path == "/api/catalogs":
                name = str(body.get("name", "")).strip()
                if not name:
                    return self._send_error(
                        code="CATALOG_NAME_REQUIRED",
                        message="Catalog name is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    created = catalog_registry.create_catalog(
                        name=name,
                        description=str(body.get("description", "")),
                        input_dir=str(body.get("input_dir", "Input Covers")),
                        output_dir=str(body.get("output_dir", "Output Covers")),
                        config_dir=str(body.get("config_dir", "config")),
                        catalog_id=str(body.get("catalog_id", "")).strip() or None,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="CATALOG_CREATE_FAILED",
                        message=str(exc),
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                _invalidate_cache("/api/catalogs")
                return self._send_json({"ok": True, "catalog": created.to_dict()})

            if path.startswith("/api/catalogs/"):
                suffix = path.split("/api/catalogs/", 1)[1].strip("/")
                parts = suffix.split("/") if suffix else []
                if not parts:
                    return self._send_error(
                        code="CATALOG_ID_REQUIRED",
                        message="catalog id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                catalog_id = parts[0]
                action = parts[1] if len(parts) > 1 else ""
                try:
                    if action == "archive":
                        payload_out = catalog_registry.archive_catalog(catalog_id).to_dict()
                    elif action == "activate":
                        payload_out = catalog_registry.activate_catalog(catalog_id).to_dict()
                    elif action == "clone":
                        payload_out = catalog_registry.clone_catalog(
                            catalog_id,
                            new_id=str(body.get("new_id", "")).strip() or None,
                            name=str(body.get("name", "")).strip() or None,
                        ).to_dict()
                    elif action == "import-books":
                        summary = catalog_registry.import_books(
                            catalog_id,
                            source_dir=str(body.get("source_dir", "")).strip() or None,
                        )
                        _invalidate_cache("/api/catalogs", "/api/review-data", "/api/iterate-data", "/api/enrichment-health")
                        target_runtime = config.get_config(catalog_id)
                        summary["auto_enrichment"] = _queue_auto_enrichment_for_books(
                            runtime=target_runtime,
                            books=summary.get("imported_books", []) if isinstance(summary, dict) else [],
                        )
                        return self._send_json({"ok": True, "summary": summary})
                    elif action == "settings":
                        settings = body.get("settings", body)
                        if not isinstance(settings, dict):
                            settings = {}
                        updated_settings = catalog_registry.update_settings(catalog_id, settings)
                        _invalidate_cache("/api/catalogs")
                        return self._send_json({"ok": True, "catalog": catalog_id, "settings": updated_settings})
                    elif not action:
                        payload_out = catalog_registry.update_catalog(catalog_id, body if isinstance(body, dict) else {}).to_dict()
                    else:
                        return self._send_error(
                            code="CATALOG_ACTION_UNSUPPORTED",
                            message=f"Unsupported catalog action: {action}",
                            details={"path": path},
                            status=HTTPStatus.NOT_FOUND,
                            endpoint=path,
                        )
                except KeyError:
                    return self._send_error(
                        code="CATALOG_NOT_FOUND",
                        message="Catalog not found",
                        details={"catalog": catalog_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="CATALOG_ACTION_FAILED",
                        message=str(exc),
                        details={"catalog": catalog_id, "action": action or "update"},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                _invalidate_cache("/api/catalogs")
                return self._send_json({"ok": True, "catalog": payload_out})

            if path == "/api/batch-generate":
                if _is_generation_budget_blocked(runtime_req):
                    budget = _budget_status_for_runtime(runtime_req)
                    return self._send_error(
                        code="BUDGET_EXCEEDED",
                        message="Generation budget limit reached. Increase budget or apply override before starting a batch.",
                        details=budget,
                        status=HTTPStatus.PAYMENT_REQUIRED,
                        endpoint=path,
                    )

                catalog_title_map = _catalog_book_title_map(runtime_req)
                books_payload = body.get("books")
                parsed_books: list[int] = []
                if isinstance(books_payload, list):
                    parsed_books = [_safe_int(item, 0) for item in books_payload]
                elif isinstance(books_payload, str):
                    token = books_payload.strip().lower()
                    if token in {"all", "*"}:
                        parsed_books = sorted(catalog_title_map.keys())
                    else:
                        try:
                            parsed_books = _parse_books(books_payload) or []
                        except Exception:
                            parsed_books = []
                elif books_payload is None:
                    parsed_books = []

                books = sorted({book for book in parsed_books if book > 0 and (not catalog_title_map or book in catalog_title_map)})
                if not books:
                    return self._send_error(
                        code="BOOKS_REQUIRED",
                        message="Provide at least one valid book number in books[]",
                        details={"received": books_payload},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )

                models_raw = body.get("models", [])
                models = [str(item).strip() for item in models_raw if str(item).strip()] if isinstance(models_raw, list) else []
                if not models:
                    models = runtime_req.all_models[:]
                if not models:
                    return self._send_error(
                        code="MODELS_REQUIRED",
                        message="At least one model is required",
                        details={"models": models_raw},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )

                variants = _safe_int(body.get("variants"), runtime_req.variants_per_cover)
                max_variants = _max_generation_variants(runtime_req)
                if variants < 1 or variants > max_variants:
                    return self._send_error(
                        code="VARIANT_COUNT_OUT_OF_RANGE",
                        message=f"variants must be between 1 and {max_variants}",
                        details={"received": body.get("variants"), "max_variants": max_variants},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )

                prompt = str(body.get("prompt", "")).strip()
                prompt_source = str(body.get("promptSource", "template") or "template").strip().lower() or "template"
                provider = str(body.get("provider", "all") or "all").strip().lower() or "all"
                budget_usd = max(0.0, _safe_float(body.get("budgetUsd"), 0.0))
                max_attempts = max(1, _safe_int(body.get("max_attempts"), 3))
                requested_dry_run = bool(body.get("dry_run", False))
                cover_source = str(body.get("cover_source", "catalog") or "catalog").strip().lower() or "catalog"
                if cover_source != "catalog":
                    return self._send_error(
                        code="BATCH_COVER_SOURCE_UNSUPPORTED",
                        message="Batch generation currently supports catalog cover source only.",
                        details={"cover_source": cover_source},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )

                backup = _create_snapshot_before_operation(runtime_req, operation="batch_generate")
                batch_id = str(uuid.uuid4())
                created_at = datetime.now(timezone.utc).isoformat()
                queued_books: list[dict[str, Any]] = []
                job_ids: list[str] = []

                for book_number in books:
                    idempotency_key = (
                        f"batch:{runtime_req.catalog_id}:{batch_id}:{book_number}:"
                        f"{hashlib.sha1(json.dumps({'models': sorted(models), 'variants': variants, 'provider': provider}, sort_keys=True).encode('utf-8')).hexdigest()[:12]}"
                    )
                    try:
                        job, _created = job_worker_pool.enqueue_generate_job(
                            catalog_id=runtime_req.catalog_id,
                            book=book_number,
                            models=models,
                            variants=variants,
                            prompt=prompt,
                            provider=provider,
                            cover_source="catalog",
                            dry_run=requested_dry_run,
                            idempotency_key=idempotency_key,
                            max_attempts=max_attempts,
                            metadata={
                                "batch_id": batch_id,
                                "prompt_source": prompt_source,
                                "batch_budget_usd": budget_usd,
                            },
                        )
                    except job_store.IdempotencyConflictError as exc:
                        return self._send_error(
                            code="IDEMPOTENCY_CONFLICT",
                            message="idempotency conflict while creating batch jobs",
                            details=exc.to_dict(),
                            status=HTTPStatus.CONFLICT,
                            endpoint=path,
                        )
                    job_ids.append(str(job.id))
                    queued_books.append(
                        {
                            "book_number": int(book_number),
                            "title": str(catalog_title_map.get(book_number, f"Book {book_number}")),
                            "job_id": str(job.id),
                            "status": str(job.status),
                            "cost_usd": 0.0,
                            "quality_score": 0.0,
                            "attempts": int(job.attempts),
                            "max_attempts": int(job.max_attempts),
                            "error": "",
                            "started_at": "",
                            "finished_at": "",
                            "updated_at": str(job.updated_at or created_at),
                        }
                    )

                entry = {
                    "id": batch_id,
                    "catalog": runtime_req.catalog_id,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "started_at": created_at,
                    "finished_at": "",
                    "status": "queued",
                    "pause_requested": False,
                    "cancel_requested": False,
                    "paused_reason": "",
                    "completion_event_emitted": False,
                    "settings": {
                        "models": sorted({str(item).strip() for item in models if str(item).strip()}),
                        "variants": int(variants),
                        "promptSource": prompt_source,
                        "prompt": prompt,
                        "provider": provider,
                        "budgetUsd": round(budget_usd, 6),
                        "dryRun": requested_dry_run,
                        "maxAttempts": max_attempts,
                        "coverSource": "catalog",
                    },
                    "books": queued_books,
                    "job_ids": job_ids,
                    "books_total": len(queued_books),
                    "cost_so_far_usd": 0.0,
                }
                _upsert_batch_entry(runtime_req, entry)
                snapshot = _batch_status_payload(runtime_req, batch_id, limit=25, offset=0) or {"ok": True}
                job_event_broker.publish(
                    "batch_started",
                    {
                        "batch_id": batch_id,
                        "catalog_id": runtime_req.catalog_id,
                        "books_total": len(queued_books),
                        "models": entry["settings"].get("models", []),
                        "variants": variants,
                        "budget_usd": budget_usd,
                    },
                )
                return self._send_json(
                    {
                        "ok": True,
                        "batchId": batch_id,
                        "booksQueued": len(queued_books),
                        "jobIds": job_ids,
                        "backup": backup,
                        "status_url": f"/api/batch-generate/{batch_id}/status",
                        "event_url": f"/api/events/batch/{batch_id}",
                        "snapshot": snapshot,
                    }
                )

            if path.startswith("/api/batch-generate/") and (
                path.endswith("/pause") or path.endswith("/resume") or path.endswith("/cancel")
            ):
                token = path.split("/api/batch-generate/", 1)[1].split("/", 1)[0].strip("/")
                action = path.rsplit("/", 1)[1].strip().lower()
                if not token:
                    return self._send_error(
                        code="BATCH_ID_REQUIRED",
                        message="batch id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                reason = str(body.get("reason", f"batch {action}")).strip()
                snapshot = _apply_batch_action(runtime_req, batch_id=token, action=action, reason=reason)
                if snapshot is None:
                    return self._send_error(
                        code="BATCH_NOT_FOUND",
                        message="batch not found",
                        details={"batch_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                job_event_broker.publish(
                    f"batch_{action}",
                    {
                        "batch_id": token,
                        "catalog_id": runtime_req.catalog_id,
                        "action": action,
                        "reason": reason,
                        "status": snapshot.get("status", ""),
                        "jobs_touched": snapshot.get("jobs_touched", 0),
                    },
                )
                return self._send_json(snapshot)

            if path == "/api/jobs":
                job_type = str(body.get("job_type", "generate")).strip().lower() or "generate"
                if job_type != "generate":
                    return self._send_error(
                        code="JOB_TYPE_UNSUPPORTED",
                        message="Only generate jobs are supported in this release",
                        details={"job_type": job_type},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                if _is_generation_budget_blocked(runtime_req):
                    budget = _budget_status_for_runtime(runtime_req)
                    return self._send_error(
                        code="BUDGET_EXCEEDED",
                        message="Generation budget limit reached. Increase budget or apply override before queuing jobs.",
                        details=budget,
                        status=HTTPStatus.PAYMENT_REQUIRED,
                        endpoint=path,
                    )
                book = _safe_int(body.get("book"), 0)
                if book <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book must be a positive integer",
                        details={"book": body.get("book")},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                models = body.get("models", [])
                active_models = [str(item).strip() for item in models if str(item).strip()] if isinstance(models, list) else []
                if not active_models:
                    active_models = runtime_req.all_models[:]
                max_variants = _max_generation_variants(runtime_req)
                variants = _safe_int(body.get("variants"), runtime_req.variants_per_cover)
                requested_variant = max(1, _safe_int(body.get("variant"), 1))
                if variants < 1 or variants > max_variants:
                    return self._send_error(
                        code="VARIANT_COUNT_OUT_OF_RANGE",
                        message=f"variants must be between 1 and {max_variants}",
                        details={"received": body.get("variants"), "max_variants": max_variants},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                prompt = str(body.get("prompt", ""))
                prompt_source = str(body.get("promptSource", body.get("prompt_source", "template")) or "template").strip().lower() or "template"
                template_id = str(body.get("template_id", body.get("templateId", "")) or "").strip()
                compose_prompt = bool(body.get("compose_prompt", True))
                preserve_prompt_text = bool(body.get("preserve_prompt_text", False))
                scene_description = str(body.get("scene_description", "") or "").strip()
                template_ok, template_details = _validate_template_id(runtime=runtime_req, template_id=template_id)
                if not template_ok:
                    return self._send_error(
                        code="INVALID_TEMPLATE_ID",
                        message=f"Unknown template_id: {template_id}",
                        details=template_details,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                provider = str(body.get("provider", "all")).strip().lower() or "all"
                cover_source = str(body.get("cover_source", "catalog")).strip().lower() or "catalog"
                if cover_source not in {"catalog", "drive"}:
                    cover_source = "catalog"
                selected_cover = body.get("selected_cover")
                selected_cover_id = str(body.get("selected_cover_id", "")).strip()
                if not selected_cover_id and isinstance(selected_cover, dict):
                    selected_cover_id = str(selected_cover.get("id", "")).strip()
                selected_cover_book_number = _safe_int(body.get("selected_cover_book_number"), 0)
                if selected_cover_book_number <= 0 and isinstance(selected_cover, dict):
                    selected_cover_book_number = _safe_int(selected_cover.get("book_number"), 0)
                drive_folder_id = str(body.get("drive_folder_id", "")).strip()
                input_folder_id = str(body.get("input_folder_id", "")).strip()
                credentials_path = str(body.get("credentials_path", "")).strip()
                valid_drive_selection, drive_selection_error, resolved_selected_cover_id = _validate_drive_cover_request(
                    runtime=runtime_req,
                    book=book,
                    cover_source=cover_source,
                    selected_cover_id=selected_cover_id,
                    selected_cover=selected_cover,
                    selected_cover_book_number=selected_cover_book_number,
                    drive_folder_id=drive_folder_id,
                    input_folder_id=input_folder_id,
                    credentials_path_token=credentials_path,
                )
                if not valid_drive_selection:
                    return self._send_error(
                        code="INVALID_DRIVE_COVER_SELECTION",
                        message=drive_selection_error or "Invalid Drive cover selection.",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                selected_cover_id = str(resolved_selected_cover_id or "").strip()
                composed_prompt_payload: dict[str, Any] = {}
                book_row = _book_row_for_number(runtime=runtime_req, book_number=book)
                precomposed_prompt = _should_use_resolved_frontend_prompt(
                    str(prompt or "").strip(),
                    compose_prompt=compose_prompt,
                    preserve_prompt_text=preserve_prompt_text,
                )
                if compose_prompt:
                    if book_row is not None:
                        default_prompt = ""
                        variants_payload = book_row.get("variants", [])
                        if isinstance(variants_payload, list) and variants_payload:
                            matching_variant = next(
                                (
                                    row
                                    for row in variants_payload
                                    if isinstance(row, dict)
                                    and _safe_int(row.get("variant_id", row.get("variant")), 0) == requested_variant
                                ),
                                None,
                            )
                            variant_row = matching_variant or variants_payload[0]
                            if isinstance(variant_row, dict):
                                default_prompt = str(variant_row.get("prompt", "")).strip()
                        composed_prompt_payload = _compose_prompt_for_book(
                            runtime=runtime_req,
                            book=book_row,
                            base_prompt=str(
                                prompt
                                or default_prompt
                                or (
                                    f"Cinematic full-bleed narrative scene for {book_row.get('title', f'Book {book}')}, "
                                    "single dominant focal subject, vivid painterly color, no text, no logos, no borders or frames"
                                )
                            ),
                            template_id=template_id,
                            variant_index=max(0, requested_variant - 1),
                            scene_override=scene_description,
                        )
                        if prompt_source == "template" or not str(prompt).strip():
                            prompt = str(composed_prompt_payload.get("prompt", prompt)).strip()
                if book_row is not None:
                    if precomposed_prompt:
                        prompt = " ".join(str(prompt or "").split()).strip()
                    else:
                        prompt = _sanitize_prompt_placeholders(
                            prompt,
                            book_row,
                            variant_index=max(0, requested_variant - 1),
                            scene_override=scene_description,
                        )
                        prompt = _ensure_enriched_prompt(
                            prompt,
                            book_row,
                            variant_index=max(0, requested_variant - 1),
                            scene_override=scene_description,
                        )
                    _validate_prompt_before_generation(prompt, book_row)
                idempotency_key = str(body.get("idempotency_key", "")).strip() or _generation_idempotency_key(
                    catalog_id=runtime_req.catalog_id,
                    book=book,
                    models=active_models,
                    variants=variants,
                    prompt=prompt,
                    provider=provider,
                    cover_source=cover_source,
                    selected_cover_id=selected_cover_id,
                    dry_run=bool(body.get("dry_run", False)),
                )
                try:
                    job, created = job_worker_pool.enqueue_generate_job(
                        catalog_id=runtime_req.catalog_id,
                        book=book,
                        models=active_models,
                        variants=variants,
                        prompt=prompt,
                        provider=provider,
                        compose_prompt=compose_prompt,
                        preserve_prompt_text=preserve_prompt_text,
                        cover_source=cover_source,
                        selected_cover_id=selected_cover_id,
                        drive_folder_id=drive_folder_id,
                        input_folder_id=input_folder_id,
                        credentials_path=credentials_path,
                        dry_run=bool(body.get("dry_run", False)),
                        idempotency_key=idempotency_key,
                        max_attempts=max(1, _safe_int(body.get("max_attempts"), 3)),
                        metadata={
                            "prompt_source": prompt_source,
                            "template_id": template_id,
                            **({"preserve_prompt_text": True} if preserve_prompt_text else {}),
                            "variant": requested_variant,
                            "scene_description": scene_description,
                            "composed_prompt": str(composed_prompt_payload.get("prompt", "")).strip(),
                            "prompt_components": composed_prompt_payload,
                            "inferred_genre": str(composed_prompt_payload.get("genre", "")).strip(),
                            "prompt_processing": "frontend_resolved" if precomposed_prompt else "backend_enriched",
                        },
                    )
                except job_store.IdempotencyConflictError as exc:
                    return self._send_error(
                        code="IDEMPOTENCY_CONFLICT",
                        message="idempotency_key already exists for a different job request",
                        details=exc.to_dict(),
                        status=HTTPStatus.CONFLICT,
                        endpoint=path,
                    )
                job_event_broker.publish(
                    "job_queued",
                    {
                        "job_id": job.id,
                        "catalog_id": runtime_req.catalog_id,
                        "status": job.status,
                        "job_type": job.job_type,
                        "created": created,
                    },
                )
                return self._send_json(
                    {
                        "ok": True,
                        "created": created,
                        "job": job.to_dict(),
                        "poll_url": f"/api/jobs/{job.id}",
                        "event_url": f"/api/events/job/{job.id}",
                        "prompt_source": prompt_source,
                        "template_id": template_id or None,
                        "composed_prompt": str(composed_prompt_payload.get("prompt", "")).strip() or None,
                        "inferred_genre": str(composed_prompt_payload.get("genre", "")).strip() or None,
                    }
                )

            if path == "/api/cache/clear":
                pattern = str(body.get("pattern", query.get("pattern", [""])[0])).strip()
                removed = (
                    _invalidate_cache(pattern, catalog_id=runtime_req.catalog_id)
                    if pattern
                    else _invalidate_cache("*", catalog_id=runtime_req.catalog_id)
                )
                return self._send_json(
                    {
                        "ok": True,
                        "pattern": pattern or "*",
                        "removed": removed,
                        "cache": data_cache.stats(),
                    }
                )
            if path == "/api/providers/reset":
                provider_raw = str(body.get("provider", "all") or "all").strip().lower()
                provider_token: str | None
                if provider_raw in {"", "all", "*"}:
                    provider_token = None
                    provider_label = "all"
                elif provider_raw in runtime_req.provider_keys:
                    provider_token = provider_raw
                    provider_label = provider_raw
                else:
                    return self._send_error(
                        code="INVALID_PROVIDER",
                        message="provider must be one of configured providers or 'all'",
                        details={"provider": provider_raw, "valid_providers": sorted(runtime_req.provider_keys.keys())},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                image_generator.reset_provider_runtime_state(provider_token)
                with _provider_connectivity_cache_lock:
                    _provider_connectivity_cache.pop(str(runtime_req.catalog_id), None)
                _record_audit_event(
                    action="provider_runtime_reset",
                    impact="operations",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={"provider": provider_label},
                )
                _invalidate_cache("/api/cache/stats", "/api/metrics", "/api/health", "/api/providers/runtime")
                return self._send_json(
                    {
                        "ok": True,
                        "catalog": runtime_req.catalog_id,
                        "provider": provider_label,
                        "providers": _provider_runtime_payload(runtime=runtime_req),
                    }
                )
            if path == "/api/admin/migrate-to-sqlite":
                db_path_token = str(body.get("db_path", runtime_req.sqlite_db_path)).strip() or str(runtime_req.sqlite_db_path)
                db_path = Path(db_path_token)
                if not db_path.is_absolute():
                    db_path = PROJECT_ROOT / db_path
                backup = _create_snapshot_before_operation(runtime_req, operation="migrate_to_sqlite")
                try:
                    from scripts import migrate_to_sqlite as migrate_script  # local import to avoid startup side effects

                    summary = migrate_script.migrate_to_sqlite(
                        catalog_id=runtime_req.catalog_id,
                        db_path=db_path,
                        runtime=runtime_req,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="SQLITE_MIGRATION_FAILED",
                        message=str(exc),
                        details={"db_path": str(db_path)},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                _invalidate_cache("*", catalog_id=runtime_req.catalog_id)
                return self._send_json({"ok": True, "summary": summary, "backup": backup})
            if path == "/api/analytics/budget":
                limit_usd = _safe_float(body.get("limit_usd"), runtime_req.max_cost_usd)
                warning_threshold = _safe_float(body.get("warning_threshold"), 0.8)
                catalog_id = str(body.get("catalog", runtime_req.catalog_id)).strip()
                hard_stop = bool(body.get("hard_stop", True))
                payload = cost_tracker.set_budget(
                    path=_budget_config_path_for_runtime(runtime_req),
                    catalog_id=catalog_id,
                    limit_usd=limit_usd,
                    warning_threshold=warning_threshold,
                    hard_stop=hard_stop,
                )
                _invalidate_cache("/api/analytics/budget", "/api/dashboard-data")
                status = cost_tracker.budget_status(
                    spent_usd=_safe_float(cost_tracker.summarize(_cost_entries_for_runtime(runtime=runtime_req, period="all")).get("total_cost_usd"), 0.0),
                    catalog_id=catalog_id,
                    budget_payload=payload,
                )
                return self._send_json({"ok": True, "budget": status})

            if path == "/api/analytics/budget/override":
                catalog_id = str(body.get("catalog", runtime_req.catalog_id)).strip() or runtime_req.catalog_id
                extra_limit_usd = _safe_float(body.get("extra_limit_usd"), 0.0)
                duration_hours = max(1, _safe_int(body.get("duration_hours"), 24))
                reason = str(body.get("reason", "manual override"))
                payload = cost_tracker.set_override(
                    path=_budget_config_path_for_runtime(runtime_req),
                    catalog_id=catalog_id,
                    extra_limit_usd=extra_limit_usd,
                    duration_hours=duration_hours,
                    reason=reason,
                )
                status = cost_tracker.budget_status(
                    spent_usd=_safe_float(cost_tracker.summarize(_cost_entries_for_runtime(runtime=runtime_req, period="all")).get("total_cost_usd"), 0.0),
                    catalog_id=catalog_id,
                    budget_payload=payload,
                )
                _invalidate_cache("/api/analytics/budget")
                return self._send_json({"ok": True, "budget": status})

            if path == "/api/analytics/export-report":
                period = str(body.get("period", "30d") or "30d").strip().lower()
                entries = _cost_entries_for_runtime(runtime=runtime_req, period=period)
                summary = cost_tracker.summarize(entries)
                model_compare = _quality_by_model_payload(runtime=runtime_req)
                quality_dist = _quality_distribution_payload(runtime=runtime_req)
                completion = _completion_payload(runtime=runtime_req)
                report_payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "catalog": runtime_req.catalog_id,
                    "period": period,
                    "cost_summary": summary,
                    "cost_by_model": cost_tracker.by_model(entries),
                    "quality_by_model": model_compare.get("models", []),
                    "quality_distribution": quality_dist,
                    "completion": completion,
                }
                reports_dir = runtime_req.data_dir / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                report_name = f"report-{runtime_req.catalog_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
                report_path = reports_dir / report_name
                safe_json.atomic_write_json(report_path, report_payload)
                return self._send_json(
                    {
                        "ok": True,
                        "report_id": report_name,
                        "report_path": _to_project_relative(report_path),
                        "download_url": f"/api/analytics/reports/{report_name}",
                    }
                )

            if path == "/api/analytics/reports/schedule":
                schedules_path = _report_schedules_path_for_runtime(runtime_req)
                schedules_payload = _load_json(schedules_path, {"schedules": []})
                schedules = schedules_payload.get("schedules", []) if isinstance(schedules_payload, dict) else []
                if not isinstance(schedules, list):
                    schedules = []
                row = {
                    "id": str(uuid.uuid4()),
                    "name": str(body.get("name", "Scheduled report")).strip() or "Scheduled report",
                    "schedule": str(body.get("schedule", "weekly")).strip().lower() or "weekly",
                    "catalog": str(body.get("catalog", runtime_req.catalog_id)).strip() or runtime_req.catalog_id,
                    "format": str(body.get("format", "json")).strip().lower() or "json",
                    "include": body.get("include", ["costs", "quality", "models", "activity"]) if isinstance(body.get("include"), list) else ["costs", "quality", "models", "activity"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "enabled": bool(body.get("enabled", True)),
                }
                schedules.append(row)
                schedules_payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "schedules": schedules[-500:]}
                safe_json.atomic_write_json(schedules_path, schedules_payload)
                return self._send_json({"ok": True, "schedule": row, "count": len(schedules_payload["schedules"])})

            if path == "/api/drive/schedule":
                payload = _save_drive_schedule(runtime_req, body if isinstance(body, dict) else {})
                _invalidate_cache("/api/drive/schedule", "/api/drive/status")
                return self._send_json({"ok": True, "catalog": runtime_req.catalog_id, "schedule": payload})

            if path.startswith("/api/jobs/") and path.endswith("/cancel-model"):
                token = path.rsplit("/", 1)[0].split("/api/jobs/", 1)[1].strip()
                model_name = str(body.get("model", "")).strip()
                if not token:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                if not model_name:
                    return self._send_error(
                        code="MODEL_REQUIRED",
                        message="model is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                _mark_job_model_cancelled(job_id=token, catalog_id=runtime_req.catalog_id, model=model_name)
                job_event_broker.publish(
                    "job_model_cancelled",
                    {"job_id": token, "catalog_id": runtime_req.catalog_id, "model": model_name, "status": "cancelled"},
                )
                return self._send_json({"ok": True, "job_id": token, "model": model_name, "status": "cancelled"})

            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                token = path.rsplit("/", 1)[0].split("/api/jobs/", 1)[1].strip()
                if not token:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                row = job_db_store.mark_cancelled(token, reason=str(body.get("reason", "cancelled")))
                if row is None:
                    return self._send_error(
                        code="JOB_NOT_FOUND",
                        message="job not found",
                        details={"job_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                _clear_job_checkpoint(runtime=runtime_req, job_id=token)
                _record_audit_event(
                    action="job_cancel",
                    impact="destructive",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={"job_id": token, "reason": str(body.get("reason", "cancelled"))},
                )
                job_event_broker.publish(
                    "job_cancelled",
                    {"job_id": token, "catalog_id": runtime_req.catalog_id, "status": row.status},
                )
                return self._send_json({"ok": True, "job": row.to_dict()})

            if path.startswith("/api/jobs/") and (path.endswith("/pause") or path.endswith("/resume") or path.endswith("/retry")):
                token = path.split("/api/jobs/", 1)[1].split("/", 1)[0].strip()
                action = path.rsplit("/", 1)[1].strip().lower()
                if not token:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                if action == "pause":
                    row = job_db_store.mark_paused(token, reason=str(body.get("reason", "paused")))
                elif action == "resume":
                    row = job_db_store.resume_job(token)
                else:
                    row = job_db_store.retry_job(token)
                if row is None:
                    return self._send_error(
                        code="JOB_NOT_FOUND",
                        message="job not found",
                        details={"job_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                job_event_broker.publish(
                    f"job_{action}",
                    {"job_id": token, "catalog_id": runtime_req.catalog_id, "status": row.status},
                )
                return self._send_json({"ok": True, "job": row.to_dict(), "action": action})

            if path.startswith("/api/books/") and path.endswith("/tags"):
                token = path.split("/api/books/", 1)[1].split("/tags", 1)[0].strip()
                book_number = _safe_int(token, 0)
                tags = body.get("tags", [])
                if isinstance(tags, str):
                    tags = [item.strip() for item in tags.split(",") if item.strip()]
                if book_number <= 0 or not isinstance(tags, list):
                    return self._send_error(
                        code="INVALID_BOOK_TAG_PAYLOAD",
                        message="book must be positive and tags must be a list",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                updated = book_metadata.add_tags(_book_metadata_path_for_runtime(runtime_req), book_number, tags)
                _invalidate_cache("/api/books", "/api/compare")
                return self._send_json({"ok": True, "book": book_number, "tags": updated.get("tags", [])})

            if path.startswith("/api/books/") and path.endswith("/notes"):
                token = path.split("/api/books/", 1)[1].split("/notes", 1)[0].strip()
                book_number = _safe_int(token, 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book must be positive",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                notes = str(body.get("notes", ""))
                updated = book_metadata.set_book(
                    _book_metadata_path_for_runtime(runtime_req),
                    book_number,
                    notes=notes,
                )
                _invalidate_cache("/api/books", "/api/compare")
                return self._send_json({"ok": True, "book": book_number, "notes": updated.get("notes", "")})

            if path == "/api/save-selections":
                with lock:
                    books = build_review_dataset(
                        runtime_req.output_dir,
                        input_dir=runtime_req.input_dir,
                        catalog_path=runtime_req.book_catalog_path,
                        quality_scores_path=_quality_scores_path_for_runtime(runtime_req),
                    )
                    winner_path = _winner_path_for_runtime(runtime_req)
                    existing_payload = _ensure_winner_payload(books, path=winner_path)
                    existing = existing_payload.get("selections", {})
                    incoming = body.get("selections", body) if isinstance(body, dict) else {}
                    if not isinstance(incoming, dict):
                        return self._send_json(
                            {"ok": False, "error": "Selections payload must be an object."},
                            status=HTTPStatus.BAD_REQUEST,
                        )

                    by_book_quality: dict[str, dict[int, float]] = {}
                    for row in books:
                        key = str(int(row.get("number", 0)))
                        quality_map: dict[int, float] = {}
                        for item in row.get("variants", []):
                            try:
                                variant = int(item.get("variant", 0))
                                score = float(item.get("quality_score", 0.0) or 0.0)
                            except (TypeError, ValueError):
                                continue
                            quality_map[variant] = score
                        by_book_quality[key] = quality_map

                    merged: dict[str, Any] = {}
                    for row in books:
                        key = str(int(row.get("number", 0)))
                        current = existing.get(key, {})
                        raw = incoming.get(key, current)

                        if isinstance(raw, dict):
                            winner_raw = raw.get("winner", current.get("winner", 0))
                            score_raw = raw.get("score", current.get("score", 0.0))
                            auto_selected = bool(raw.get("auto_selected", current.get("auto_selected", True)))
                            confirmed = bool(raw.get("confirmed", current.get("confirmed", False)))
                        else:
                            winner_raw = raw
                            score_raw = 0.0
                            auto_selected = False
                            confirmed = True

                        try:
                            winner = int(winner_raw or 0)
                        except (TypeError, ValueError):
                            winner = 0
                        if winner <= 0:
                            continue

                        try:
                            score = float(score_raw or 0.0)
                        except (TypeError, ValueError):
                            score = 0.0
                        if score <= 0:
                            score = float(by_book_quality.get(key, {}).get(winner, 0.0))

                        merged[key] = {
                            "winner": winner,
                            "score": round(score, 4),
                            "auto_selected": auto_selected,
                            "confirmed": confirmed,
                            "selected_by": str(current.get("selected_by", configured_reviewer) or configured_reviewer),
                            "selection_date": str(current.get("selection_date", datetime.now(timezone.utc).isoformat())),
                            "reviewer": str(current.get("reviewer", configured_reviewer) or configured_reviewer),
                            "review_mode": str(current.get("review_mode", "grid") or "grid"),
                            "overrode_auto": bool(current.get("overrode_auto", False)),
                            "conflict_requires_resolution": bool(current.get("conflict_requires_resolution", False)),
                            "conflict": current.get("conflict", {}),
                        }

                    saved_payload = _save_winner_payload(winner_path, merged, total_books=len(books))
                _invalidate_cache("/api/review-data", "/api/review-queue", "/api/review-stats", "/api/dashboard-data")
                auto_delivery = _maybe_auto_delivery_for_books(
                    runtime=runtime_req,
                    book_numbers=[_safe_int(key, 0) for key in saved_payload.get("selections", {}).keys() if _safe_int(key, 0) > 0],
                    source="save_selections",
                )

                return self._send_json(
                    {
                        "ok": True,
                        "path": str(winner_path),
                        "plain_path": str(_selection_path_for_runtime(runtime_req)),
                        "saved_books": len(saved_payload.get("selections", {})),
                        "auto_delivery": auto_delivery,
                    }
                )

            if path == "/api/batch-approve":
                threshold = _safe_float(body.get("threshold"), 0.90)
                reviewer = str(body.get("reviewer", configured_reviewer) or configured_reviewer).strip() or configured_reviewer
                summary = _apply_batch_approve(runtime=runtime_req, threshold=threshold, reviewer=reviewer)
                write_review_data(runtime_req.output_dir, runtime=runtime_req)
                _invalidate_cache("/api/review-data", "/api/review-queue", "/api/review-stats", "/api/dashboard-data")
                return self._send_json({"ok": True, "summary": summary})

            if path == "/api/review-selection":
                book = _safe_int(body.get("book"), 0)
                variant = _safe_int(body.get("variant"), 0)
                reviewer = str(body.get("reviewer", configured_reviewer) or configured_reviewer).strip() or configured_reviewer
                if book <= 0 or variant <= 0:
                    return self._send_json(
                        {"ok": False, "error": "book and variant must be positive integers"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                books = build_review_dataset(
                    runtime_req.output_dir,
                    input_dir=runtime_req.input_dir,
                    catalog_path=runtime_req.book_catalog_path,
                    quality_scores_path=_quality_scores_path_for_runtime(runtime_req),
                )
                score = 0.0
                target_book = next((row for row in books if _safe_int(row.get("number"), 0) == book), None)
                if isinstance(target_book, dict):
                    for row in target_book.get("variants", []):
                        if _safe_int(row.get("variant"), 0) == variant:
                            score = _safe_float(row.get("quality_score"), 0.0)
                            break

                winner_path = _winner_path_for_runtime(runtime_req)
                payload = _ensure_winner_payload(books, path=winner_path)
                selections = payload.get("selections", {})
                if not isinstance(selections, dict):
                    selections = {}
                existing = selections.get(str(book), {}) if isinstance(selections.get(str(book), {}), dict) else {}
                existing_winner = _safe_int(existing.get("winner"), 0)
                existing_reviewer = str(existing.get("selected_by") or existing.get("reviewer") or "").strip()
                conflict_required = (
                    existing_winner > 0
                    and existing_winner != variant
                    and existing_reviewer
                    and existing_reviewer.lower() != reviewer.lower()
                )
                conflict_payload: dict[str, Any] = {}
                if conflict_required:
                    conflict_payload = {
                        "requires_resolution": True,
                        "previous_reviewer": existing_reviewer,
                        "previous_variant": existing_winner,
                        "new_reviewer": reviewer,
                        "new_variant": variant,
                        "flagged_at": datetime.now(timezone.utc).isoformat(),
                    }
                elif isinstance(existing.get("conflict"), dict):
                    conflict_payload = dict(existing.get("conflict", {}))
                    if conflict_payload:
                        conflict_payload["requires_resolution"] = False
                        conflict_payload["resolved_at"] = datetime.now(timezone.utc).isoformat()
                selections[str(book)] = {
                    "winner": variant,
                    "score": round(score, 4),
                    "auto_selected": False,
                    "confirmed": True,
                    "selected_by": reviewer,
                    "selection_date": datetime.now(timezone.utc).isoformat(),
                    "reviewer": reviewer,
                    "review_mode": str(body.get("review_mode", "speed") or "speed"),
                    "overrode_auto": bool(existing.get("winner") and _safe_int(existing.get("winner"), 0) != variant),
                    "conflict_requires_resolution": conflict_required,
                    "conflict": conflict_payload,
                }
                saved_payload = _save_winner_payload(winner_path, selections, total_books=len(books))
                write_review_data(runtime_req.output_dir, runtime=runtime_req)
                _invalidate_cache("/api/review-data", "/api/review-queue", "/api/review-stats", "/api/dashboard-data")
                auto_delivery = _maybe_auto_delivery_for_books(runtime=runtime_req, book_numbers=[book], source="review_selection")
                return self._send_json({"ok": True, "saved": saved_payload.get("selections", {}).get(str(book), {}), "auto_delivery": auto_delivery})

            if path == "/api/save-review-session":
                session_id = str(body.get("session_id") or f"review_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}").strip()
                payload = {
                    "session_id": session_id,
                    "catalog": runtime_req.catalog_id,
                    "started_at": str(body.get("started_at") or datetime.now(timezone.utc).isoformat()),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "books_reviewed": _safe_int(body.get("books_reviewed"), 0),
                    "books_remaining": _safe_int(body.get("books_remaining"), 0),
                    "auto_approved": _safe_int(body.get("auto_approved"), 0),
                    "manually_selected": _safe_int(body.get("manually_selected"), 0),
                    "skipped": _safe_int(body.get("skipped"), 0),
                    "skipped_books": body.get("skipped_books", []) if isinstance(body.get("skipped_books"), list) else [],
                    "avg_time_per_book_seconds": _safe_float(body.get("avg_time_per_book_seconds"), 0.0),
                    "selections": body.get("selections", {}) if isinstance(body.get("selections"), dict) else {},
                    "selection_details": body.get("selection_details", {}) if isinstance(body.get("selection_details"), dict) else {},
                    "reviewer": str(body.get("reviewer", configured_reviewer) or configured_reviewer),
                    "mode": str(body.get("mode", "speed") or "speed"),
                    "completed": bool(body.get("completed", False)),
                }
                review_sessions_dir = _review_sessions_dir_for_runtime(runtime_req)
                review_sessions_dir.mkdir(parents=True, exist_ok=True)
                session_path = review_sessions_dir / f"{session_id}.json"
                safe_json.atomic_write_json(session_path, payload)

                if payload["completed"]:
                    _append_review_stats(runtime=runtime_req, payload=payload)
                _invalidate_cache("/api/review-session/", "/api/review-stats")

                return self._send_json({"ok": True, "session_id": session_id, "path": str(session_path)})

            if path == "/api/enrich-book":
                book_number = _safe_int(body.get("book"), 0)
                if book_number <= 0:
                    return self._send_json(
                        {"ok": False, "error": "book must be a positive integer"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                enriched_path = config.enriched_catalog_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir)
                book_row = _book_row_for_number(runtime=runtime_req, book_number=book_number)
                if not isinstance(book_row, dict):
                    return self._send_json(
                        {"ok": False, "error": "book not found"},
                        status=HTTPStatus.NOT_FOUND,
                    )

                summary = book_enricher.enrich_single_book(
                    book=book_row,
                    output_path=enriched_path,
                    provider=runtime_req.llm_provider,
                    model=runtime_req.llm_model,
                    max_tokens=runtime_req.llm_max_tokens,
                    cost_per_1k_tokens=runtime_req.llm_cost_per_1k_tokens,
                    usage_path=_llm_usage_path_for_runtime(runtime_req),
                    descriptions_path=runtime_req.config_dir / "book_descriptions.json",
                )
                enriched_payload = _load_json(enriched_path, [])
                enriched_row = None
                if isinstance(enriched_payload, list):
                    enriched_row = next(
                        (
                            row
                            for row in enriched_payload
                            if isinstance(row, dict) and _safe_int(row.get("number"), 0) == book_number
                        ),
                        None,
                )
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/iterate-data", "/api/prompt-performance", "/api/enrichment-health")
                usage_last = summary.get("usage", {}).get("last_run", {}) if isinstance(summary.get("usage"), dict) else {}
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="enrich",
                    cost_usd=_safe_float(usage_last.get("cost_usd"), 0.0),
                    model=str(summary.get("model", runtime_req.llm_model)),
                    provider=str(summary.get("provider", runtime_req.llm_provider)),
                    book_number=book_number,
                    tokens_in=_safe_int(usage_last.get("input_tokens"), 0),
                    tokens_out=_safe_int(usage_last.get("output_tokens"), 0),
                    images_generated=0,
                    duration_seconds=0.0,
                    metadata={"books_enriched": 1, "source": str(summary.get("source", ""))},
                )
                _invalidate_cache("/api/analytics/", "/api/dashboard-data")
                return self._send_json({"ok": True, "summary": summary, "book": enriched_row})

            if path == "/api/enrich-all":
                enriched_path = config.enriched_catalog_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir)
                force = bool(body.get("force", False))
                replace_generic = bool(body.get("replace_generic", False))
                delay_seconds = max(0.0, _safe_float(body.get("delay"), 0.5))
                batch_size = max(1, _safe_int(body.get("batch_size"), 50))
                summary = book_enricher.enrich_catalog(
                    catalog_path=runtime_req.book_catalog_path,
                    output_path=enriched_path,
                    books=None,
                    force_refresh=force,
                    replace_generic=replace_generic,
                    provider=runtime_req.llm_provider,
                    model=runtime_req.llm_model,
                    max_tokens=runtime_req.llm_max_tokens,
                    cost_per_1k_tokens=runtime_req.llm_cost_per_1k_tokens,
                    usage_path=_llm_usage_path_for_runtime(runtime_req),
                    descriptions_path=runtime_req.config_dir / "book_descriptions.json",
                    delay_seconds=delay_seconds,
                    batch_size=batch_size,
                )
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/iterate-data", "/api/prompt-performance", "/api/enrichment-health")
                usage_last = summary.get("usage", {}).get("last_run", {}) if isinstance(summary.get("usage"), dict) else {}
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="enrich",
                    cost_usd=_safe_float(usage_last.get("cost_usd"), 0.0),
                    model=str(summary.get("model", runtime_req.llm_model)),
                    provider=str(summary.get("provider", runtime_req.llm_provider)),
                    book_number=0,
                    tokens_in=_safe_int(usage_last.get("input_tokens"), 0),
                    tokens_out=_safe_int(usage_last.get("output_tokens"), 0),
                    images_generated=0,
                    duration_seconds=0.0,
                    metadata={"books_enriched": _safe_int(summary.get("books_enriched_in_run"), 0)},
                )
                _invalidate_cache("/api/analytics/", "/api/dashboard-data")
                return self._send_json({"ok": True, "summary": summary})

            if path == "/api/enrich-generic":
                delay_seconds = max(0.0, _safe_float(body.get("delay"), 0.5))
                batch_size = max(1, _safe_int(body.get("batch_size"), 50))
                payload = _start_generic_enrichment_background(
                    runtime=runtime_req,
                    delay_seconds=delay_seconds,
                    batch_size=batch_size,
                )
                _invalidate_cache("/api/enrichment-health")
                return self._send_json(payload)

            if path == "/api/generate-smart-prompts":
                book_number = _safe_int(body.get("book"), 0)
                count = max(1, min(_safe_int(body.get("count"), 5), 5))

                enriched_path = config.enriched_catalog_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir)
                if not enriched_path.exists():
                    book_enricher.enrich_catalog(
                        catalog_path=runtime_req.book_catalog_path,
                        output_path=enriched_path,
                        books=[book_number] if book_number > 0 else None,
                        force_refresh=False,
                        provider=runtime_req.llm_provider,
                        model=runtime_req.llm_model,
                        max_tokens=runtime_req.llm_max_tokens,
                        cost_per_1k_tokens=runtime_req.llm_cost_per_1k_tokens,
                        usage_path=_llm_usage_path_for_runtime(runtime_req),
                        descriptions_path=runtime_req.config_dir / "book_descriptions.json",
                    )

                prompt_output = config.intelligent_prompts_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir)
                summary = intelligent_prompter.generate_prompts(
                    catalog_path=enriched_path if enriched_path.exists() else runtime_req.book_catalog_path,
                    output_path=prompt_output,
                    books=[book_number] if book_number > 0 else None,
                    count=count,
                    provider=runtime_req.llm_provider,
                    model=runtime_req.llm_model,
                    max_tokens=runtime_req.llm_max_tokens,
                    genre_presets_path=runtime_req.config_dir / "genre_presets.json",
                    performance_path=_prompt_performance_path_for_runtime(runtime_req),
                    prompt_library_path=runtime_req.prompt_library_path,
                )

                smart_payload = _load_json(prompt_output, {"books": []})
                selected_book = None
                if book_number > 0 and isinstance(smart_payload, dict):
                    rows = smart_payload.get("books", [])
                    if isinstance(rows, list):
                        selected_book = next(
                            (
                                row
                                for row in rows
                                if isinstance(row, dict) and _safe_int(row.get("number"), 0) == book_number
                            ),
                            None,
                )
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/iterate-data", "/api/prompt-performance")
                return self._send_json({"ok": True, "summary": summary, "book": selected_book})

            if path == "/api/generate-mockup":
                book = _safe_int(body.get("book"), 0)
                template_id = str(body.get("template", "")).strip()
                spine_width = max(40, _safe_int(body.get("spine_width"), 100))
                if book <= 0 or not template_id:
                    return self._send_json(
                        {"ok": False, "error": "book and template are required"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                templates = mockup_generator.template_map(runtime_req.config_dir / "mockup_templates.json")
                template = templates.get(template_id)
                if not template:
                    return self._send_json(
                        {"ok": False, "error": f"Unknown template: {template_id}"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                catalog = mockup_generator.load_book_records(runtime_req.book_catalog_path)
                winners = mockup_generator.load_winner_map(_winner_path_for_runtime(runtime_req))
                record = catalog.get(book)
                if not record:
                    return self._send_json({"ok": False, "error": f"Book {book} not found"}, status=HTTPStatus.NOT_FOUND)

                try:
                    cover_path = mockup_generator.winner_cover_path(
                        book_number=book,
                        output_root=runtime_req.output_dir,
                        catalog=catalog,
                        winner_map=winners,
                    )
                    out_path = runtime_req.output_dir / "Mockups" / record.folder_name / f"{template_id}.jpg"
                    saved = mockup_generator.generate_mockup(
                        cover_image_path=str(cover_path),
                        template_id=template_id,
                        output_path=str(out_path),
                        spine_width_px=spine_width,
                        book_title=record.title,
                        book_author=record.author,
                    )
                except Exception as exc:
                    return self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

                rel = _to_project_relative(Path(saved))
                return self._send_json(
                    {
                        "ok": True,
                        "book": book,
                        "template": template_id,
                        "path": rel,
                        "url": f"/{rel}",
                        "catalog": runtime_req.catalog_id,
                    }
                )

            if path == "/api/generate-all-mockups":
                book = _safe_int(body.get("book"), 0)
                all_books = bool(body.get("all_books", False))
                template_ids = body.get("templates")
                if isinstance(template_ids, str):
                    template_ids = [item.strip() for item in template_ids.split(",") if item.strip()]
                if not isinstance(template_ids, list):
                    template_ids = None
                spine_width = max(40, _safe_int(body.get("spine_width"), 100))

                books = None
                if book > 0:
                    books = [book]
                elif not all_books:
                    return self._send_json(
                        {"ok": False, "error": "Provide book or set all_books=true"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                try:
                    summary = mockup_generator.generate_all_mockups(
                        output_dir=str(runtime_req.output_dir),
                        selections_path=str(_winner_path_for_runtime(runtime_req)),
                        templates=template_ids,
                        books=books,
                        spine_width_px=spine_width,
                    )
                except Exception as exc:
                    return self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

                summary["ok"] = True
                summary["catalog"] = runtime_req.catalog_id
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="mockup",
                    cost_usd=0.0,
                    model="mockup_generator",
                    provider="local",
                    book_number=book if book > 0 else 0,
                    images_generated=_safe_int(summary.get("generated"), 0),
                    duration_seconds=0.0,
                    metadata={"all_books": all_books, "templates": template_ids or []},
                )
                _invalidate_cache("/api/analytics/", "/api/dashboard-data")
                _record_audit_event(
                    action="generate_all_mockups",
                    impact="cost",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={
                        "book": book if book > 0 else None,
                        "all_books": all_books,
                        "templates": template_ids or [],
                        "generated": summary.get("generated", 0),
                        "failed": summary.get("failed", 0),
                    },
                )
                return self._send_json(summary)

            if path == "/api/generate-amazon-set":
                book = _safe_int(body.get("book"), 0)
                all_books = bool(body.get("all_books", False))
                spine_width = max(40, _safe_int(body.get("spine_width"), 100))
                books = [book] if book > 0 else None
                if books is None and not all_books:
                    return self._send_json(
                        {"ok": False, "error": "Provide book or set all_books=true"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                try:
                    summary = mockup_generator.generate_amazon_sets(
                        output_dir=str(runtime_req.output_dir),
                        selections_path=str(_winner_path_for_runtime(runtime_req)),
                        books=books,
                        spine_width_px=spine_width,
                    )
                except Exception as exc:
                    return self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

                summary["ok"] = True
                summary["catalog"] = runtime_req.catalog_id
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="amazon_export",
                    cost_usd=0.0,
                    model="mockup_generator",
                    provider="local",
                    book_number=book if book > 0 else 0,
                    images_generated=_safe_int(summary.get("generated", summary.get("books", 0)), 0),
                    duration_seconds=0.0,
                    metadata={"all_books": all_books},
                )
                _invalidate_cache("/api/analytics/", "/api/dashboard-data")
                _record_audit_event(
                    action="generate_amazon_set",
                    impact="cost",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={
                        "book": book if book > 0 else None,
                        "all_books": all_books,
                        "books_generated": summary.get("books", 0),
                        "failed": summary.get("failed", 0),
                    },
                )
                return self._send_json(summary)

            if path == "/api/generate-social-cards":
                book = _safe_int(body.get("book"), 0)
                all_books = bool(body.get("all_books", False))
                formats = body.get("formats")
                if isinstance(formats, str):
                    formats = [item.strip() for item in formats.split(",") if item.strip()]
                if not isinstance(formats, list):
                    formats = ["instagram", "facebook", "twitter", "story", "pinterest"]
                if book <= 0 and not all_books:
                    return self._send_json(
                        {"ok": False, "error": "Provide book or set all_books=true"},
                        status=HTTPStatus.BAD_REQUEST,
                    )

                try:
                    summary = social_card_generator.generate_social_cards(
                        output_dir=str(runtime_req.output_dir),
                        selections_path=str(_winner_path_for_runtime(runtime_req)),
                        book=book if book > 0 else None,
                        all_books=all_books,
                        formats=formats,
                    )
                except Exception as exc:
                    return self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

                summary["ok"] = True
                summary["catalog"] = runtime_req.catalog_id
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="social_export",
                    cost_usd=0.0,
                    model="social_card_generator",
                    provider="local",
                    book_number=book if book > 0 else 0,
                    images_generated=_safe_int(summary.get("generated"), 0),
                    duration_seconds=0.0,
                    metadata={"all_books": all_books, "formats": formats},
                )
                _invalidate_cache("/api/analytics/", "/api/dashboard-data")
                _record_audit_event(
                    action="generate_social_cards",
                    impact="cost",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={
                        "book": book if book > 0 else None,
                        "all_books": all_books,
                        "formats": formats,
                        "generated": summary.get("generated", 0),
                        "failed": summary.get("failed", 0),
                    },
                )
                return self._send_json(summary)

            if path == "/api/export/all":
                books_payload = body.get("books", "all")
                books: list[int] | None
                if isinstance(books_payload, list):
                    books = sorted({_safe_int(item, 0) for item in books_payload if _safe_int(item, 0) > 0}) or None
                else:
                    books_token = str(books_payload or "all").strip().lower()
                    books = None if books_token in {"all", "*", ""} else (_parse_books(books_token) or None)

                platforms_raw = body.get("platforms", ["amazon", "ingram", "social", "web"])
                if isinstance(platforms_raw, str):
                    platforms = [token.strip().lower() for token in platforms_raw.split(",") if token.strip()]
                elif isinstance(platforms_raw, list):
                    platforms = [str(token).strip().lower() for token in platforms_raw if str(token).strip()]
                else:
                    platforms = []
                valid_platforms = [token for token in platforms if token in {"amazon", "ingram", "social", "web"}]
                if not valid_platforms:
                    valid_platforms = ["amazon", "ingram", "social", "web"]

                platform_results: dict[str, dict[str, Any]] = {}
                export_ids: dict[str, str] = {}
                failures: list[dict[str, Any]] = []

                for platform in valid_platforms:
                    try:
                        if platform == "amazon":
                            summary = export_amazon.export_catalog(
                                catalog_id=runtime_req.catalog_id,
                                catalog_path=runtime_req.book_catalog_path,
                                output_root=runtime_req.output_dir,
                                selections_path=_winner_path_for_runtime(runtime_req),
                                quality_path=_quality_scores_path_for_runtime(runtime_req),
                                exports_root=EXPORTS_ROOT,
                                books=books,
                            )
                        elif platform == "ingram":
                            summary = export_ingram.export_catalog(
                                catalog_id=runtime_req.catalog_id,
                                catalog_path=runtime_req.book_catalog_path,
                                output_root=runtime_req.output_dir,
                                selections_path=_winner_path_for_runtime(runtime_req),
                                quality_path=_quality_scores_path_for_runtime(runtime_req),
                                exports_root=EXPORTS_ROOT,
                                books=books,
                            )
                        elif platform == "social":
                            summary = export_social.export_catalog(
                                catalog_id=runtime_req.catalog_id,
                                catalog_path=runtime_req.book_catalog_path,
                                output_root=runtime_req.output_dir,
                                selections_path=_winner_path_for_runtime(runtime_req),
                                quality_path=_quality_scores_path_for_runtime(runtime_req),
                                exports_root=EXPORTS_ROOT,
                                books=books,
                                platforms=body.get("social_platforms", "all"),
                                watermark=bool(body.get("watermark", True)),
                            )
                        else:
                            summary = export_web.export_catalog(
                                catalog_id=runtime_req.catalog_id,
                                catalog_path=runtime_req.book_catalog_path,
                                output_root=runtime_req.output_dir,
                                selections_path=_winner_path_for_runtime(runtime_req),
                                quality_path=_quality_scores_path_for_runtime(runtime_req),
                                exports_root=EXPORTS_ROOT,
                                books=books,
                            )
                        export_id = _register_export_result(runtime=runtime_req, export_type=platform, summary=summary)
                        summary["ok"] = bool(summary.get("ok", True))
                        summary["export_id"] = export_id
                        platform_results[platform] = summary
                        export_ids[platform] = export_id
                    except Exception as exc:
                        failures.append({"platform": platform, "error": str(exc)})
                        platform_results[platform] = {"ok": False, "error": str(exc), "results": []}

                batch_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                combined_root = EXPORTS_ROOT / "all" / runtime_req.catalog_id / f"bundle-{batch_stamp}"
                combined_root.mkdir(parents=True, exist_ok=True)
                if books:
                    selected_books = sorted(set(books))
                else:
                    selected_books = sorted(
                        {
                            _safe_int(item.get("book_number"), 0)
                            for summary in platform_results.values()
                            for item in (summary.get("results", []) if isinstance(summary, dict) else [])
                            if isinstance(item, dict)
                            and _safe_int(item.get("book_number"), 0) > 0
                        }
                    )
                for platform in valid_platforms:
                    source_root = EXPORTS_ROOT / platform / runtime_req.catalog_id
                    if not source_root.exists():
                        continue
                    destination_root = combined_root / platform
                    destination_root.mkdir(parents=True, exist_ok=True)
                    if selected_books:
                        for book in selected_books:
                            src = source_root / str(book)
                            if not src.exists():
                                continue
                            dst = destination_root / str(book)
                            if dst.exists():
                                shutil.rmtree(dst)
                            shutil.copytree(src, dst)
                    else:
                        for child in sorted(source_root.iterdir()):
                            dst = destination_root / child.name
                            if child.is_dir():
                                if dst.exists():
                                    shutil.rmtree(dst)
                                shutil.copytree(child, dst)
                            elif child.is_file():
                                shutil.copy2(child, dst)

                combined_summary = {
                    "ok": len(failures) == 0 and all(bool(row.get("ok", False)) for row in platform_results.values()),
                    "catalog": runtime_req.catalog_id,
                    "export_type": "all",
                    "books_requested": len(selected_books),
                    "books_exported": len(selected_books),
                    "file_count": _file_count(combined_root),
                    "export_path": str(combined_root),
                    "platforms": valid_platforms,
                    "platform_results": platform_results,
                    "errors": failures,
                }
                combined_export_id = _register_export_result(runtime=runtime_req, export_type="all", summary=combined_summary)
                _invalidate_cache("/api/exports", "/api/storage/usage", "/api/delivery/tracking", "/api/export/status")
                return self._send_json(
                    {
                        "ok": combined_summary["ok"],
                        "catalog": runtime_req.catalog_id,
                        "platforms": valid_platforms,
                        "export_ids": export_ids,
                        "combined_export_id": combined_export_id,
                        "combined_download_url": f"/api/exports/{combined_export_id}/download",
                        "combined_path": _to_project_relative(combined_root),
                        "summary": combined_summary,
                    }
                )

            if path.startswith("/api/export/validate/"):
                token = path.split("/api/export/validate/", 1)[1].strip("/")
                book_number = _safe_int(token, 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book number must be a positive integer",
                        details={"book": token},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                try:
                    validation = _validate_export_readiness_for_book(runtime=runtime_req, book_number=book_number)
                except Exception as exc:
                    return self._send_error(
                        code="EXPORT_VALIDATION_FAILED",
                        message=str(exc),
                        details={"book": book_number},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                return self._send_json(validation, status=HTTPStatus.OK if bool(validation.get("ok", False)) else HTTPStatus.UNPROCESSABLE_ENTITY)

            if path == "/api/export/amazon" or path.startswith("/api/export/amazon/"):
                book = 0
                if path.startswith("/api/export/amazon/"):
                    token = path.split("/api/export/amazon/", 1)[1].strip("/")
                    book = _safe_int(token, 0)
                    if book <= 0:
                        return self._send_error(
                            code="INVALID_BOOK_NUMBER",
                            message="book number must be a positive integer",
                            details={"book": token},
                            status=HTTPStatus.BAD_REQUEST,
                            endpoint=path,
                        )
                books = [book] if book > 0 else (_parse_books(str(body.get("books", ""))) or None)
                try:
                    summary = export_amazon.export_catalog(
                        catalog_id=runtime_req.catalog_id,
                        catalog_path=runtime_req.book_catalog_path,
                        output_root=runtime_req.output_dir,
                        selections_path=_winner_path_for_runtime(runtime_req),
                        quality_path=_quality_scores_path_for_runtime(runtime_req),
                        exports_root=EXPORTS_ROOT,
                        books=books,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="AMAZON_EXPORT_FAILED",
                        message=str(exc),
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                export_id = _register_export_result(runtime=runtime_req, export_type="amazon", summary=summary)
                summary["ok"] = summary.get("ok", True)
                summary["export_id"] = export_id
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="amazon_export",
                    cost_usd=0.0,
                    model="export_amazon",
                    provider="local",
                    book_number=book if book > 0 else 0,
                    images_generated=_safe_int(summary.get("file_count"), 0),
                    duration_seconds=0.0,
                    metadata={"books_requested": summary.get("books_requested", 0), "export_id": export_id},
                )
                _invalidate_cache("/api/exports", "/api/export/status", "/api/delivery/tracking", "/api/storage/usage")
                return self._send_json(summary)

            if path == "/api/export/ingram" or path.startswith("/api/export/ingram/"):
                book = 0
                if path.startswith("/api/export/ingram/"):
                    token = path.split("/api/export/ingram/", 1)[1].strip("/")
                    book = _safe_int(token, 0)
                    if book <= 0:
                        return self._send_error(
                            code="INVALID_BOOK_NUMBER",
                            message="book number must be a positive integer",
                            details={"book": token},
                            status=HTTPStatus.BAD_REQUEST,
                            endpoint=path,
                        )
                books = [book] if book > 0 else (_parse_books(str(body.get("books", ""))) or None)
                try:
                    summary = export_ingram.export_catalog(
                        catalog_id=runtime_req.catalog_id,
                        catalog_path=runtime_req.book_catalog_path,
                        output_root=runtime_req.output_dir,
                        selections_path=_winner_path_for_runtime(runtime_req),
                        quality_path=_quality_scores_path_for_runtime(runtime_req),
                        exports_root=EXPORTS_ROOT,
                        books=books,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="INGRAM_EXPORT_FAILED",
                        message=str(exc),
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                export_id = _register_export_result(runtime=runtime_req, export_type="ingram", summary=summary)
                summary["ok"] = summary.get("ok", True)
                summary["export_id"] = export_id
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="ingram_export",
                    cost_usd=0.0,
                    model="export_ingram",
                    provider="local",
                    book_number=book if book > 0 else 0,
                    images_generated=_safe_int(summary.get("file_count"), 0),
                    duration_seconds=0.0,
                    metadata={"books_requested": summary.get("books_requested", 0), "export_id": export_id},
                )
                _invalidate_cache("/api/exports", "/api/export/status", "/api/delivery/tracking", "/api/storage/usage")
                return self._send_json(summary)

            if path == "/api/export/social" or path.startswith("/api/export/social/"):
                book = 0
                if path.startswith("/api/export/social/"):
                    token = path.split("/api/export/social/", 1)[1].strip("/")
                    book = _safe_int(token, 0)
                    if book <= 0:
                        return self._send_error(
                            code="INVALID_BOOK_NUMBER",
                            message="book number must be a positive integer",
                            details={"book": token},
                            status=HTTPStatus.BAD_REQUEST,
                            endpoint=path,
                        )
                platforms_token = str(query.get("platforms", [body.get("platforms", "all")])[0] or body.get("platforms", "all"))
                books = [book] if book > 0 else (_parse_books(str(body.get("books", ""))) or None)
                try:
                    summary = export_social.export_catalog(
                        catalog_id=runtime_req.catalog_id,
                        catalog_path=runtime_req.book_catalog_path,
                        output_root=runtime_req.output_dir,
                        selections_path=_winner_path_for_runtime(runtime_req),
                        quality_path=_quality_scores_path_for_runtime(runtime_req),
                        exports_root=EXPORTS_ROOT,
                        books=books,
                        platforms=platforms_token,
                        watermark=bool(body.get("watermark", True)),
                    )
                except Exception as exc:
                    return self._send_error(
                        code="SOCIAL_EXPORT_FAILED",
                        message=str(exc),
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                export_id = _register_export_result(runtime=runtime_req, export_type="social", summary=summary)
                summary["ok"] = summary.get("ok", True)
                summary["export_id"] = export_id
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="social_export",
                    cost_usd=0.0,
                    model="export_social",
                    provider="local",
                    book_number=book if book > 0 else 0,
                    images_generated=_safe_int(summary.get("file_count"), 0),
                    duration_seconds=0.0,
                    metadata={"books_requested": summary.get("books_requested", 0), "platforms": platforms_token, "export_id": export_id},
                )
                _invalidate_cache("/api/exports", "/api/export/status", "/api/delivery/tracking", "/api/storage/usage")
                return self._send_json(summary)

            if path == "/api/export/web":
                books = _parse_books(str(body.get("books", ""))) or None
                try:
                    summary = export_web.export_catalog(
                        catalog_id=runtime_req.catalog_id,
                        catalog_path=runtime_req.book_catalog_path,
                        output_root=runtime_req.output_dir,
                        selections_path=_winner_path_for_runtime(runtime_req),
                        quality_path=_quality_scores_path_for_runtime(runtime_req),
                        exports_root=EXPORTS_ROOT,
                        books=books,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="WEB_EXPORT_FAILED",
                        message=str(exc),
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )
                export_id = _register_export_result(runtime=runtime_req, export_type="web", summary=summary)
                summary["ok"] = summary.get("ok", True)
                summary["export_id"] = export_id
                _record_cost_entry(
                    runtime=runtime_req,
                    operation="web_export",
                    cost_usd=0.0,
                    model="export_web",
                    provider="local",
                    book_number=0,
                    images_generated=_safe_int(summary.get("file_count"), 0),
                    duration_seconds=0.0,
                    metadata={"books_requested": summary.get("books_requested", 0), "export_id": export_id},
                )
                _invalidate_cache("/api/exports", "/api/export/status", "/api/delivery/tracking", "/api/storage/usage")
                return self._send_json(summary)

            if path == "/api/delivery/enable":
                cfg = delivery_pipeline.set_enabled(
                    catalog_id=runtime_req.catalog_id,
                    enabled=True,
                    config_path=_delivery_config_path_for_runtime(runtime_req),
                )
                return self._send_json({"ok": True, "catalog": runtime_req.catalog_id, "enabled": cfg.enabled, "updated_at": cfg.updated_at})

            if path == "/api/delivery/disable":
                cfg = delivery_pipeline.set_enabled(
                    catalog_id=runtime_req.catalog_id,
                    enabled=False,
                    config_path=_delivery_config_path_for_runtime(runtime_req),
                )
                return self._send_json({"ok": True, "catalog": runtime_req.catalog_id, "enabled": cfg.enabled, "updated_at": cfg.updated_at})

            if path == "/api/delivery/batch":
                platforms_token = str(query.get("platforms", [body.get("platforms", "")])[0] or body.get("platforms", ""))
                platforms = [token.strip().lower() for token in platforms_token.split(",") if token.strip()] if platforms_token else None
                if platforms:
                    valid_platforms = set(delivery_pipeline.DEFAULT_PLATFORMS)
                    invalid_platforms = sorted({token for token in platforms if token not in valid_platforms})
                    if invalid_platforms:
                        return self._send_error(
                            code="INVALID_DELIVERY_PLATFORMS",
                            message="One or more delivery platforms are invalid.",
                            details={"invalid": invalid_platforms, "valid": sorted(valid_platforms)},
                            status=HTTPStatus.BAD_REQUEST,
                            endpoint=path,
                        )
                books_param = str(query.get("books", [body.get("books", "")])[0] or body.get("books", ""))
                books = _parse_books(books_param)
                if not books:
                    winners_payload = _load_winner_payload(_winner_path_for_runtime(runtime_req))
                    selection_rows = winners_payload.get("selections", {}) if isinstance(winners_payload, dict) else {}
                    books = sorted(_safe_int(key, 0) for key in selection_rows.keys() if _safe_int(key, 0) > 0)
                if not books:
                    return self._send_error(
                        code="NO_READY_BOOKS",
                        message="No winner-selected books are ready for delivery",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                events: list[dict[str, Any]] = []
                summary = delivery_pipeline.deliver_batch(
                    catalog_id=runtime_req.catalog_id,
                    book_numbers=books,
                    catalog_path=runtime_req.book_catalog_path,
                    output_root=runtime_req.output_dir,
                    selections_path=_winner_path_for_runtime(runtime_req),
                    quality_path=_quality_scores_path_for_runtime(runtime_req),
                    exports_root=EXPORTS_ROOT,
                    delivery_config_path=_delivery_config_path_for_runtime(runtime_req),
                    delivery_tracking_path=_delivery_tracking_path_for_runtime(runtime_req),
                    drive_folder_id=runtime_req.gdrive_output_folder_id,
                    credentials_path=_resolve_credentials_path(runtime_req),
                    platforms=platforms,
                    progress_callback=events.append,
                )
                for event in events:
                    if isinstance(event, dict):
                        event_name = str(event.get("event", "job_progress") or "job_progress")
                        job_event_broker.publish(
                            event_name,
                            {"catalog_id": runtime_req.catalog_id, **event},
                        )
                _invalidate_cache("/api/delivery/status", "/api/delivery/tracking", "/api/exports", "/api/storage/usage")
                return self._send_json({"ok": bool(summary.get("ok", False)), "summary": summary})

            if path == "/api/save-raw":
                job_id = str(body.get("job_id", "") or body.get("backend_job_id", "")).strip()
                if not job_id:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job_id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                job = job_db_store.get_job(job_id)
                if job is None:
                    return self._send_error(
                        code="JOB_NOT_FOUND",
                        message="job not found",
                        details={"job_id": job_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                expected_selection = _save_raw_expectation_from_payload(body)
                try:
                    payload = _save_raw_payload_for_job(runtime=runtime_req, job=job, expected=expected_selection)
                except LookupError:
                    return self._send_error(
                        code="BOOK_NOT_FOUND",
                        message="book not found for job",
                        details={"job_id": job_id, "book_number": int(job.book_number or 0)},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except FileNotFoundError:
                    return self._send_error(
                        code="JOB_OUTPUTS_NOT_FOUND",
                        message="No raw or composite image found for job",
                        details={"job_id": job_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except SaveRawIntegrityError as exc:
                    return self._send_error(
                        code=exc.code,
                        message=str(exc),
                        details=exc.details,
                        status=HTTPStatus.CONFLICT,
                        endpoint=path,
                    )
                return self._send_json(payload)

            if path == "/api/save-result":
                job_id = str(body.get("job_id", "") or body.get("backend_job_id", "")).strip()
                if not job_id:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job_id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                job = job_db_store.get_job(job_id)
                if job is None:
                    return self._send_error(
                        code="JOB_NOT_FOUND",
                        message="job not found",
                        details={"job_id": job_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                expected_selection = _save_raw_expectation_from_payload(body)
                style_label = str(body.get("style_label", "") or "").strip()
                try:
                    payload = _save_result_payload_for_job(
                        runtime=runtime_req,
                        job=job,
                        expected=expected_selection,
                        style_label=style_label,
                    )
                except LookupError:
                    return self._send_error(
                        code="BOOK_NOT_FOUND",
                        message="book not found for job",
                        details={"job_id": job_id, "book_number": int(job.book_number or 0)},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except FileNotFoundError:
                    return self._send_error(
                        code="JOB_OUTPUTS_NOT_FOUND",
                        message="No composite image found for job",
                        details={"job_id": job_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except SaveRawIntegrityError as exc:
                    return self._send_error(
                        code=exc.code,
                        message=str(exc),
                        details=exc.details,
                        status=HTTPStatus.CONFLICT,
                        endpoint=path,
                    )
                return self._send_json(payload)

            if path == "/api/retry-drive-upload":
                job_id = str(body.get("job_id", "") or body.get("backend_job_id", "")).strip()
                if not job_id:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job_id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                job = job_db_store.get_job(job_id)
                if job is None:
                    return self._send_error(
                        code="JOB_NOT_FOUND",
                        message="job not found",
                        details={"job_id": job_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                expected_selection = _save_raw_expectation_from_payload(body)
                try:
                    payload = _save_raw_payload_for_job(runtime=runtime_req, job=job, expected=expected_selection)
                except LookupError:
                    return self._send_error(
                        code="BOOK_NOT_FOUND",
                        message="book not found for job",
                        details={"job_id": job_id, "book_number": int(job.book_number or 0)},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except FileNotFoundError:
                    return self._send_error(
                        code="JOB_OUTPUTS_NOT_FOUND",
                        message="No raw or composite image found for job",
                        details={"job_id": job_id},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except SaveRawIntegrityError as exc:
                    return self._send_error(
                        code=exc.code,
                        message=str(exc),
                        details=exc.details,
                        status=HTTPStatus.CONFLICT,
                        endpoint=path,
                    )
                payload["retried"] = True
                return self._send_json(payload)

            if path == "/api/save-prompt":
                try:
                    with lock:
                        payload = _save_prompt_from_request(runtime=runtime_req, body=body)
                except ValueError as exc:
                    return self._send_error(
                        code="PROMPT_SAVE_INVALID",
                        message=str(exc),
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/prompts", "/api/iterate-data")
                return self._send_json(payload)

            if path == "/api/prompts":
                payload = _create_prompt_from_request(runtime=runtime_req, body=body)
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/prompts", "/api/iterate-data")
                return self._send_json(payload)

            if path == "/api/prompts/seed-builtins":
                payload = _seed_builtin_prompts(
                    runtime=runtime_req,
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    overwrite=bool(body.get("overwrite", False)),
                )
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/prompts", "/api/iterate-data", "/api/prompt-performance")
                return self._send_json(payload)

            if path == "/api/prompts/import":
                imported = _import_prompt_payload(runtime=runtime_req, body=body)
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/prompts", "/api/iterate-data")
                return self._send_json(imported)

            if path.startswith("/api/prompts/"):
                token = path.split("/api/prompts/", 1)[1].strip("/")
                if not token:
                    return self._send_error(
                        code="PROMPT_ID_REQUIRED",
                        message="prompt id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                action = str(body.get("action", "update")).strip().lower()
                try:
                    if action == "delete":
                        payload = _delete_prompt(runtime=runtime_req, prompt_id=token)
                    elif action == "record_usage":
                        payload = _record_prompt_usage(runtime=runtime_req, prompt_id=token, won=bool(body.get("won", False)))
                    else:
                        payload = _update_prompt_from_request(runtime=runtime_req, prompt_id=token, body=body)
                except KeyError:
                    return self._send_error(
                        code="PROMPT_NOT_FOUND",
                        message="Prompt not found",
                        details={"prompt_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                except ValueError as exc:
                    return self._send_error(
                        code="PROMPT_UPDATE_INVALID",
                        message=str(exc),
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                write_iterate_data(runtime=runtime_req)
                _invalidate_cache("/api/prompts", "/api/iterate-data")
                return self._send_json(payload)

            if path == "/api/analytics/ab-tests":
                payload = _record_ab_test(runtime=runtime_req, body=body)
                return self._send_json(payload)

            if path == "/api/test-connection":
                provider = str(body.get("provider", "")).strip().lower()
                selected = [provider] if provider and provider != "all" else None
                report = pipeline_runner.test_api_keys(runtime=runtime_req, providers=selected)
                with _provider_connectivity_cache_lock:
                    _provider_connectivity_cache.pop(str(runtime_req.catalog_id), None)
                return self._send_json({"ok": True, "report": report})

            if path == "/api/validate/cover":
                distributor = str(body.get("distributor", "ingram_spark") or "ingram_spark").strip().lower()
                file_token = str(body.get("file_path", body.get("image_path", "")) or "").strip()
                text_elements = body.get("text_elements", [])
                if not isinstance(text_elements, list):
                    text_elements = []

                if not file_token:
                    return self._send_error(
                        code="FILE_PATH_REQUIRED",
                        message="file_path is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )

                file_path = Path(file_token)
                if not file_path.is_absolute():
                    file_path = PROJECT_ROOT / file_path
                try:
                    safe_path = security.sanitize_path(file_path, PROJECT_ROOT)
                except Exception:
                    return self._send_error(
                        code="PATH_NOT_ALLOWED",
                        message="Requested file path is not allowed",
                        details={"file_path": file_token},
                        status=HTTPStatus.FORBIDDEN,
                        endpoint=path,
                    )

                if not safe_path.exists() or not safe_path.is_file():
                    return self._send_error(
                        code="FILE_NOT_FOUND",
                        message="cover file not found",
                        details={"file_path": str(safe_path)},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )

                validator = _print_validator_instance()
                try:
                    with Image.open(safe_path) as cover_image:
                        if distributor == "all":
                            payload = validator.validate_for_all_distributors(cover_image, text_elements, safe_path)
                            return self._send_json(
                                {
                                    "ok": True,
                                    "file_path": _to_project_relative(safe_path),
                                    "distributor": "all",
                                    "results": payload,
                                    "passed": all(bool(row.get("passed")) for row in payload.values() if isinstance(row, dict)),
                                }
                            )
                        result = validator.validate_all(cover_image, text_elements, safe_path, distributor)
                        return self._send_json(
                            {
                                "ok": True,
                                "file_path": _to_project_relative(safe_path),
                                **result,
                            }
                        )
                except KeyError:
                    return self._send_error(
                        code="UNKNOWN_DISTRIBUTOR",
                        message=f"Unknown distributor: {distributor}",
                        details={"supported": sorted(_print_validator_instance().specs.keys())},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                except Exception as exc:
                    return self._send_error(
                        code="PRINT_VALIDATION_FAILED",
                        message=str(exc),
                        details={"file_path": str(safe_path), "distributor": distributor},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )

            if path == "/api/generate":
                book = int(body.get("book", 0))
                models = list(body.get("models", [])) if isinstance(body.get("models", []), list) else []
                variants = int(body.get("variants", 5))
                requested_variant = max(1, _safe_int(body.get("variant"), 1))
                prompt = str(body.get("prompt", ""))
                prompt_source = str(body.get("promptSource", body.get("prompt_source", "template")) or "template").strip().lower() or "template"
                template_id = str(body.get("template_id", body.get("templateId", "")) or "").strip()
                compose_prompt = bool(body.get("compose_prompt", True))
                preserve_prompt_text = bool(body.get("preserve_prompt_text", False))
                scene_description = str(body.get("scene_description", "") or "").strip()
                template_ok, template_details = _validate_template_id(runtime=runtime_req, template_id=template_id)
                if not template_ok:
                    return self._send_error(
                        code="INVALID_TEMPLATE_ID",
                        message=f"Unknown template_id: {template_id}",
                        details=template_details,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                provider = str(body.get("provider", "")).strip().lower()
                cover_source = str(body.get("cover_source", "catalog")).strip().lower() or "catalog"
                if cover_source not in {"catalog", "drive"}:
                    cover_source = "catalog"
                selected_cover = body.get("selected_cover")
                selected_cover_id = str(body.get("selected_cover_id", "")).strip()
                if not selected_cover_id and isinstance(selected_cover, dict):
                    selected_cover_id = str(selected_cover.get("id", "")).strip()
                selected_cover_book_number = _safe_int(body.get("selected_cover_book_number"), 0)
                if selected_cover_book_number <= 0 and isinstance(selected_cover, dict):
                    selected_cover_book_number = _safe_int(selected_cover.get("book_number"), 0)
                drive_folder_id = str(body.get("drive_folder_id", "")).strip()
                input_folder_id = str(body.get("input_folder_id", "")).strip()
                credentials_path = str(body.get("credentials_path", "")).strip()
                library_prompt_id = str(body.get("library_prompt_id", "")).strip()
                async_mode = bool(body.get("async", True))
                worker_mode = _normalize_worker_mode(body.get("worker_mode", ACTIVE_WORKER_MODE))
                if _is_generation_budget_blocked(runtime_req):
                    budget = _budget_status_for_runtime(runtime_req)
                    return self._send_error(
                        code="BUDGET_EXCEEDED",
                        message="Generation budget limit reached. Increase budget or apply override before generating.",
                        details=budget,
                        status=HTTPStatus.PAYMENT_REQUIRED,
                        endpoint=path,
                    )
                book_validation = api_validation.validate_book_number(book)
                if not book_validation.valid:
                    return self._send_error(
                        code=book_validation.error.code,
                        message=book_validation.error.message,
                        details=book_validation.error.details,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                variant_validation = api_validation.validate_positive_int(variants, field="variants")
                if not variant_validation.valid:
                    return self._send_error(
                        code=variant_validation.error.code,
                        message=variant_validation.error.message,
                        details=variant_validation.error.details,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                max_variants = _max_generation_variants(runtime_req)
                if variants > max_variants:
                    return self._send_error(
                        code="VARIANT_COUNT_OUT_OF_RANGE",
                        message=f"variants must be between 1 and {max_variants}",
                        details={"received": variants, "max_variants": max_variants},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                valid_drive_selection, drive_selection_error, resolved_selected_cover_id = _validate_drive_cover_request(
                    runtime=runtime_req,
                    book=book,
                    cover_source=cover_source,
                    selected_cover_id=selected_cover_id,
                    selected_cover=selected_cover,
                    selected_cover_book_number=selected_cover_book_number,
                    drive_folder_id=drive_folder_id,
                    input_folder_id=input_folder_id,
                    credentials_path_token=credentials_path,
                )
                if not valid_drive_selection:
                    return self._send_error(
                        code="INVALID_DRIVE_COVER_SELECTION",
                        message=drive_selection_error or "Invalid Drive cover selection.",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                selected_cover_id = str(resolved_selected_cover_id or "").strip()
                composed_prompt_payload: dict[str, Any] = {}
                book_row = _book_row_for_number(runtime=runtime_req, book_number=book)
                precomposed_prompt = _should_use_resolved_frontend_prompt(
                    str(prompt or "").strip(),
                    compose_prompt=compose_prompt,
                    preserve_prompt_text=preserve_prompt_text,
                )
                if compose_prompt:
                    if book_row is not None:
                        default_prompt = ""
                        variants_payload = book_row.get("variants", [])
                        if isinstance(variants_payload, list) and variants_payload:
                            matching_variant = next(
                                (
                                    row
                                    for row in variants_payload
                                    if isinstance(row, dict)
                                    and _safe_int(row.get("variant_id", row.get("variant")), 0) == requested_variant
                                ),
                                None,
                            )
                            variant_row = matching_variant or variants_payload[0]
                            if isinstance(variant_row, dict):
                                default_prompt = str(variant_row.get("prompt", "")).strip()
                        composed_prompt_payload = _compose_prompt_for_book(
                            runtime=runtime_req,
                            book=book_row,
                            base_prompt=str(
                                prompt
                                or default_prompt
                                or (
                                    f"Cinematic full-bleed narrative scene for {book_row.get('title', f'Book {book}')}, "
                                    "single dominant focal subject, vivid painterly color, no text, no logos, no borders or frames"
                                )
                            )
                            .strip(),
                            template_id=template_id,
                            variant_index=max(0, requested_variant - 1),
                            scene_override=scene_description,
                        )
                        if prompt_source == "template" or not str(prompt).strip():
                            prompt = str(composed_prompt_payload.get("prompt", prompt)).strip()
                if book_row is not None:
                    if precomposed_prompt:
                        prompt = " ".join(str(prompt or "").split()).strip()
                    else:
                        prompt = _sanitize_prompt_placeholders(
                            prompt,
                            book_row,
                            variant_index=max(0, requested_variant - 1),
                            scene_override=scene_description,
                        )
                        prompt = _ensure_enriched_prompt(
                            prompt,
                            book_row,
                            variant_index=max(0, requested_variant - 1),
                            scene_override=scene_description,
                        )
                    _validate_prompt_before_generation(prompt, book_row)
                active_models = [str(item).strip() for item in models if str(item).strip()]
                if not active_models:
                    return self._send_error(
                        code="MODELS_REQUIRED",
                        message="Select at least one model before generating.",
                        details={"models": models},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                valid_catalog_source, catalog_source_error = _validate_catalog_cover_request(
                    runtime=runtime_req,
                    book=book,
                    cover_source=cover_source,
                )
                if not valid_catalog_source:
                    return self._send_error(
                        code="MISSING_LOCAL_COVER",
                        message=catalog_source_error or "No local catalog cover is available for this title.",
                        details={
                            "book": int(book),
                            "cover_source": cover_source,
                            "suggested_cover_source": "drive",
                        },
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )

                if async_mode:
                    requested_dry_run = bool(body.get("dry_run", False))
                    idempotency_key = str(body.get("idempotency_key", "")).strip() or _generation_idempotency_key(
                        catalog_id=runtime_req.catalog_id,
                        book=book,
                        models=active_models,
                        variants=variants,
                        prompt=prompt,
                        provider=provider or "all",
                        cover_source=cover_source,
                        selected_cover_id=selected_cover_id,
                        dry_run=requested_dry_run,
                    )
                    try:
                        job, created = job_worker_pool.enqueue_generate_job(
                            catalog_id=runtime_req.catalog_id,
                            book=book,
                            models=active_models,
                            variants=variants,
                            prompt=prompt,
                            provider=provider or "all",
                            compose_prompt=compose_prompt,
                            preserve_prompt_text=preserve_prompt_text,
                            cover_source=cover_source,
                            selected_cover_id=selected_cover_id,
                            library_prompt_id=library_prompt_id,
                            drive_folder_id=drive_folder_id,
                            input_folder_id=input_folder_id,
                            credentials_path=credentials_path,
                            dry_run=requested_dry_run,
                            idempotency_key=idempotency_key,
                            max_attempts=max(1, int(body.get("max_attempts", 3))),
                            metadata={
                                "prompt_source": prompt_source,
                                "template_id": template_id,
                                **({"preserve_prompt_text": True} if preserve_prompt_text else {}),
                                "variant": requested_variant,
                                "scene_description": scene_description,
                                "composed_prompt": str(composed_prompt_payload.get("prompt", "")).strip(),
                                "prompt_components": composed_prompt_payload,
                                "inferred_genre": str(composed_prompt_payload.get("genre", "")).strip(),
                                "prompt_processing": "frontend_resolved" if precomposed_prompt else "backend_enriched",
                            },
                        )
                    except job_store.IdempotencyConflictError as exc:
                        return self._send_error(
                            code="IDEMPOTENCY_CONFLICT",
                            message="idempotency_key already exists for a different job request",
                            details=exc.to_dict(),
                            status=HTTPStatus.CONFLICT,
                            endpoint=path,
                        )
                    payload: dict[str, Any] = {
                        "ok": True,
                        "created": created,
                        "job": job.to_dict(),
                        "idempotency_key": idempotency_key,
                        "poll_url": f"/api/jobs/{job.id}",
                        "event_url": f"/api/events/job/{job.id}",
                        "prompt_source": prompt_source,
                        "template_id": template_id or None,
                        "composed_prompt": str(composed_prompt_payload.get("prompt", "")).strip() or None,
                        "inferred_genre": str(composed_prompt_payload.get("genre", "")).strip() or None,
                    }
                    batch_token = str((job.payload or {}).get("batch_id", "")).strip() if isinstance(job.payload, dict) else ""
                    if batch_token:
                        payload["batch_id"] = batch_token
                        payload["batch_event_url"] = f"/api/events/batch/{batch_token}"
                    if job.status == "completed" and job.result:
                        payload.update(job.result)
                    _record_audit_event(
                        action="generate_async",
                        impact="cost",
                        actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                        source_ip=client_ip,
                        endpoint=path,
                        catalog_id=runtime_req.catalog_id,
                        status="ok",
                        data_dir=runtime_req.data_dir,
                        details={
                            "book": book,
                            "models": active_models,
                            "variants": variants,
                            "dry_run": requested_dry_run,
                            "created": created,
                            "job_id": job.id,
                            "idempotency_key": idempotency_key,
                        },
                    )
                    return self._send_json(payload)

                if not _sync_generation_allowed(worker_mode=worker_mode):
                    return self._send_error(
                        code="SYNC_GENERATION_DISABLED",
                        message="Synchronous generation is disabled in queue-only mode. Submit async jobs and poll /api/jobs/{id}.",
                        details={
                            "worker_mode": worker_mode,
                            "allow_sync_generation": ALLOW_SYNC_GENERATION,
                            "hint": "Set ALLOW_SYNC_GENERATION=1 only for controlled debugging.",
                        },
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )

                request_id = f"generate:{runtime_req.catalog_id}:{book}"
                if not request_tracker.start(request_id):
                    return self._send_error(
                        code="GENERATION_IN_PROGRESS",
                        message=f"Generation already in progress for book {book}",
                        details={"book": book},
                        status=HTTPStatus.CONFLICT,
                        endpoint=path,
                    )
                try:
                    result = _execute_generation_payload(
                        {
                            "catalog": runtime_req.catalog_id,
                            "book": book,
                            "models": active_models,
                            "variants": variants,
                            "prompt": prompt,
                            "provider": provider or "all",
                            "cover_source": cover_source,
                            "selected_cover_id": selected_cover_id,
                            "template_id": template_id,
                            "prompt_source": prompt_source,
                            "library_prompt_id": library_prompt_id,
                            "drive_folder_id": drive_folder_id,
                            "input_folder_id": input_folder_id,
                            "credentials_path": credentials_path,
                            "dry_run": bool(body.get("dry_run", False)),
                        }
                    )
                finally:
                    request_tracker.finish(request_id)
                _record_audit_event(
                    action="generate_sync",
                    impact="cost",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={
                        "book": book,
                        "models": active_models,
                        "variants": variants,
                        "dry_run": bool(body.get("dry_run", False)),
                        "result_count": len(result.get("results", [])),
                    },
                )
                return self._send_json({"ok": True, **result})

            if path == "/api/regenerate":
                book = _safe_int(body.get("book"), 0)
                variants = _safe_int(body.get("variants"), 5)
                threshold = _safe_float(body.get("threshold"), 0.75)
                use_library = bool(body.get("use_library", True))
                auto_accept = bool(body.get("auto_accept", False))

                cmd = [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "regenerate_weak.py"),
                    "--catalog",
                    runtime_req.catalog_id,
                    "--threshold",
                    str(threshold),
                    "--variants",
                    str(max(1, variants)),
                ]
                if use_library:
                    cmd.append("--use-library")
                if auto_accept:
                    cmd.append("--auto-accept")
                if book > 0:
                    cmd.extend(["--book", str(book)])

                completed = subprocess.run(cmd, capture_output=True, text=True)
                if completed.returncode != 0:
                    return self._send_json(
                        {
                            "ok": False,
                            "error": (completed.stderr or completed.stdout or "Regeneration failed").strip(),
                        },
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )

                payload = _load_json(_regeneration_results_path_for_runtime(runtime_req), {"details": []})
                write_review_data(runtime_req.output_dir, runtime=runtime_req)
                _invalidate_cache("/api/review-data", "/api/dashboard-data", "/api/history", "/api/generation-history", "/api/similarity-", "/api/weak-books", "/api/regeneration-results")
                _record_audit_event(
                    action="regenerate_weak",
                    impact="cost",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={
                        "book": book if book > 0 else None,
                        "variants": variants,
                        "threshold": threshold,
                        "use_library": use_library,
                        "auto_accept": auto_accept,
                    },
                )
                return self._send_json({"ok": True, "summary": payload, "stdout": completed.stdout.strip()})

            if path in {"/api/sync-to-drive", "/api/drive/sync", "/api/drive/push", "/api/drive/pull"}:
                runtime = runtime_req
                requested_mode = str(body.get("mode", "")).strip().lower()
                if path.endswith("/push"):
                    requested_mode = "push"
                elif path.endswith("/pull"):
                    requested_mode = "pull"
                elif path.endswith("/sync"):
                    requested_mode = requested_mode or "bidirectional"
                else:
                    requested_mode = requested_mode or "push"
                drive_folder_id = str(body.get("drive_folder_id", runtime.gdrive_output_folder_id)).strip()
                credentials_override = str(body.get("credentials_path", "")).strip()
                credentials_path = Path(credentials_override) if credentials_override else _resolve_credentials_path(runtime)
                if not credentials_path.is_absolute():
                    credentials_path = PROJECT_ROOT / credentials_path

                selected_files: list[str] = []
                if requested_mode in {"push", "bidirectional", "sync"}:
                    selections = body.get("selections")
                    if not isinstance(selections, dict):
                        selections = _load_json(_selection_path_for_runtime(runtime), {})
                    selected_files = _collect_selected_variant_files(
                        output_dir=runtime.output_dir,
                        selections=selections,
                        catalog_path=runtime.book_catalog_path,
                    )

                try:
                    if requested_mode in {"pull"}:
                        pull_summary = drive_manager.pull_from_drive(
                            input_root=runtime.input_dir,
                            drive_folder_id=drive_folder_id,
                            credentials_path=credentials_path,
                        )
                        push_summary = None
                        combined = {
                            "mode": pull_summary.get("mode"),
                            "direction": "pull",
                            "pull": pull_summary,
                            "push": None,
                            "failed": pull_summary.get("failed", 0),
                        }
                    elif requested_mode in {"bidirectional", "sync"}:
                        combined = drive_manager.sync_bidirectional(
                            output_root=runtime.output_dir,
                            input_root=runtime.input_dir,
                            exports_root=EXPORTS_ROOT,
                            drive_folder_id=drive_folder_id,
                            credentials_path=credentials_path,
                            sync_state_path=_gdrive_sync_state_path(runtime),
                            selected_relative_files=selected_files,
                        )
                        push_summary = combined.get("push")
                        pull_summary = combined.get("pull")
                    else:
                        push_summary = drive_manager.push_to_drive(
                            output_root=runtime.output_dir,
                            input_root=runtime.input_dir,
                            exports_root=EXPORTS_ROOT,
                            drive_folder_id=drive_folder_id,
                            credentials_path=credentials_path,
                            sync_state_path=_gdrive_sync_state_path(runtime),
                            selected_relative_files=selected_files,
                        )
                        pull_summary = None
                        combined = {
                            "mode": push_summary.get("mode"),
                            "direction": "push",
                            "pull": None,
                            "push": push_summary,
                            "failed": push_summary.get("failed", 0),
                        }
                except Exception as exc:
                    return self._send_error(
                        code="DRIVE_SYNC_FAILED",
                        message=str(exc),
                        details={"mode": requested_mode, "drive_folder_id": drive_folder_id},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        endpoint=path,
                    )

                final_failed = _safe_int(combined.get("failed"), 0)

                _append_drive_sync_log(
                    runtime=runtime_req,
                    entry={
                        "mode": requested_mode,
                        "catalog": runtime_req.catalog_id,
                        "drive_folder_id": drive_folder_id,
                        "selected_files": len(selected_files),
                        "push": push_summary or {},
                        "pull": pull_summary or {},
                        "summary": combined,
                    },
                )
                _record_audit_event(
                    action="sync_to_drive",
                    impact="destructive",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok" if final_failed == 0 else "partial",
                    data_dir=runtime_req.data_dir,
                    details={
                        "mode": requested_mode,
                        "selected_files": len(selected_files),
                        "drive_folder_id": drive_folder_id,
                        "push": push_summary or {},
                        "pull": pull_summary or {},
                    },
                )
                _invalidate_cache("/api/drive/status", "/api/drive/input-covers")
                return self._send_json(
                    {
                        "ok": final_failed == 0,
                        "mode": requested_mode,
                        "summary": combined,
                        "selected_files": len(selected_files),
                        "push": push_summary,
                        "pull": pull_summary,
                    }
                )

            if path == "/api/archive/old-exports":
                days = max(1, _safe_int(body.get("days", query.get("days", ["30"])[0]), 30))
                archived = _archive_old_exports(days=days, runtime=runtime_req)
                _invalidate_cache("/api/archive/stats", "/api/storage/usage", "/api/exports", "/api/export/status", "/api/delivery/tracking")
                return self._send_json({"ok": True, "summary": archived})

            if path.startswith("/api/archive/restore/"):
                token = path.split("/api/archive/restore/", 1)[1].strip("/")
                book_number = _safe_int(token, 0)
                if book_number <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book number must be a positive integer",
                        details={"book": token},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                restored = _restore_archived_book(book_number=book_number, runtime=runtime_req)
                _invalidate_cache("/api/archive/stats", "/api/storage/usage", "/api/review-data")
                return self._send_json({"ok": True, "summary": restored})

            if path in {"/api/archive-non-winners", "/api/archive/non-winners"}:
                dry_run = bool(body.get("dry_run", False))
                include_unconfirmed = bool(body.get("include_unconfirmed", False))
                selections_path = Path(str(body.get("selections_path", _winner_path_for_runtime(runtime_req))))
                if not selections_path.is_absolute():
                    selections_path = PROJECT_ROOT / selections_path
                backup = _create_snapshot_before_operation(runtime_req, operation="archive_non_winners") if not dry_run else {"ok": False, "skipped": True, "reason": "dry_run"}

                cmd = [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "archive_non_winners.py"),
                    "--catalog",
                    runtime_req.catalog_id,
                    "--selections",
                    str(selections_path),
                    "--output-dir",
                    str(runtime_req.output_dir),
                    "--archive-dir",
                    str(runtime_req.output_dir / "Archive"),
                    "--log-path",
                    str(config.archive_log_path(catalog_id=runtime_req.catalog_id, data_dir=runtime_req.data_dir)),
                ]
                if dry_run:
                    cmd.append("--dry-run")
                if include_unconfirmed:
                    cmd.append("--include-unconfirmed")

                completed = subprocess.run(cmd, capture_output=True, text=True)
                if completed.returncode != 0:
                    return self._send_json(
                        {
                            "ok": False,
                            "error": (completed.stderr or completed.stdout or "Archive command failed").strip(),
                        },
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )

                summary_text = completed.stdout.strip()
                try:
                    summary = json.loads(summary_text) if summary_text else {}
                except json.JSONDecodeError:
                    summary = {"raw_output": summary_text}

                if not dry_run:
                    write_review_data(runtime_req.output_dir, runtime=runtime_req)
                    _invalidate_cache("/api/review-data", "/api/dashboard-data", "/api/history", "/api/generation-history", "/api/archive/stats", "/api/storage/usage")
                _record_audit_event(
                    action="archive_non_winners",
                    impact="destructive",
                    actor=str(body.get("actor") or body.get("reviewer") or configured_reviewer),
                    source_ip=client_ip,
                    endpoint=path,
                    catalog_id=runtime_req.catalog_id,
                    status="ok",
                    data_dir=runtime_req.data_dir,
                    details={
                        "dry_run": dry_run,
                        "include_unconfirmed": include_unconfirmed,
                        "summary": summary,
                    },
                )
                return self._send_json({"ok": True, "summary": summary, "dry_run": dry_run, "backup": backup})

            if path == "/api/similarity/recompute":
                threshold = _safe_float(
                    body.get(
                        "threshold",
                        query.get("threshold", ["0.25"])[0] if isinstance(query.get("threshold"), list) else 0.25,
                    ),
                    0.25,
                )
                force = bool(body.get("force", False))
                started = _start_similarity_recompute(
                    runtime_req=runtime_req,
                    threshold=threshold,
                    reason=str(body.get("reason", "manual")).strip() or "manual",
                    force=force,
                )
                _invalidate_cache("/api/similarity-matrix", "/api/similarity-alerts", "/api/similarity-clusters")
                return self._send_json({"ok": True, **started})

            if path == "/api/similarity/update":
                book = _safe_int(
                    body.get(
                        "book",
                        query.get("book", ["0"])[0] if isinstance(query.get("book"), list) else 0,
                    ),
                    0,
                )
                if book <= 0:
                    return self._send_error(
                        code="INVALID_BOOK_NUMBER",
                        message="book must be a positive integer",
                        details={"book": body.get("book", query.get("book", [""])[0] if isinstance(query.get("book"), list) else "")},
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                threshold = _safe_float(
                    body.get(
                        "threshold",
                        query.get("threshold", ["0.25"])[0] if isinstance(query.get("threshold"), list) else 0.25,
                    ),
                    0.25,
                )
                payload = similarity_detector.update_similarity_for_book(
                    output_dir=runtime_req.output_dir,
                    book_number=book,
                    threshold=threshold,
                    catalog_path=runtime_req.book_catalog_path,
                    winner_selections_path=_winner_path_for_runtime(runtime_req),
                    regions_path=config.cover_regions_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir),
                    hashes_path=_similarity_hashes_path_for_runtime(runtime_req),
                    matrix_path=_similarity_matrix_path_for_runtime(runtime_req),
                    clusters_path=_similarity_clusters_path_for_runtime(runtime_req),
                )
                if not bool(payload.get("ok", False)):
                    return self._send_error(
                        code="SIMILARITY_UPDATE_FAILED",
                        message=str(payload.get("error", "Failed to update similarity data for book")),
                        details=payload,
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                _invalidate_cache("/api/similarity-matrix", "/api/similarity-alerts", "/api/similarity-clusters", "/api/review-data")
                return self._send_json({"ok": True, **payload})

            if path == "/api/dismiss-similarity":
                book_a = _safe_int(body.get("book_a"), 0)
                book_b = _safe_int(body.get("book_b"), 0)
                if book_a <= 0 or book_b <= 0:
                    return self._send_json(
                        {"ok": False, "error": "book_a and book_b must be positive integers"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                payload = similarity_detector.dismiss_similarity_pair(
                    book_a=book_a,
                    book_b=book_b,
                    dismissed_path=_similarity_dismissed_path_for_runtime(runtime_req),
                )
                _invalidate_cache("/api/similarity-", "/api/review-data")
                return self._send_json({"ok": True, "dismissed": payload})

            return self._send_json({"ok": False, "error": "Unknown endpoint"}, status=HTTPStatus.NOT_FOUND)

        def do_PUT(self):
            return self.do_POST()

        def do_DELETE(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            self._set_active_runtime(None)
            self._set_request_id(str(self.headers.get("X-Request-Id", "")).strip() or str(uuid.uuid4()))
            requested_catalog_raw = str(query.get("catalog", [default_runtime.catalog_id])[0]).strip()
            try:
                requested_catalog = security.validate_catalog_id(requested_catalog_raw) if requested_catalog_raw else default_runtime.catalog_id
            except ValueError:
                return self._send_error(
                    code="INVALID_CATALOG_ID",
                    message="Invalid catalog id",
                    details={"catalog": requested_catalog_raw},
                    status=HTTPStatus.BAD_REQUEST,
                    endpoint=path,
                )
            runtime_req = config.get_config(requested_catalog or default_runtime.catalog_id)
            self._set_active_runtime(runtime_req)
            client_ip = str(self.client_address[0] if self.client_address else "unknown")

            if MUTATION_API_TOKEN:
                supplied = str(self.headers.get("X-API-Token", "")).strip()
                if not supplied:
                    supplied = str(query.get("token", [""])[0]).strip()
                if supplied != MUTATION_API_TOKEN:
                    return self._send_error(
                        code="UNAUTHORIZED",
                        message="Valid API token required for mutation endpoints",
                        status=HTTPStatus.UNAUTHORIZED,
                        endpoint=path,
                    )

            limiter, limit_per_minute = _mutation_limiter(path, catalog_id=runtime_req.catalog_id)
            if not limiter.allow(f"{client_ip}:{path}"):
                return self._send_error(
                    code="RATE_LIMITED",
                    message="Too many write requests. Please retry shortly.",
                    details={"path": path, "limit_per_minute": limit_per_minute},
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                    endpoint=path,
                    headers={"Retry-After": "60"},
                )

            if path.startswith("/api/exports/"):
                token = path.split("/api/exports/", 1)[1].strip().strip("/")
                if not token:
                    return self._send_error(
                        code="EXPORT_ID_REQUIRED",
                        message="export id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                removed = _delete_export(export_id=token, runtime=runtime_req)
                if not removed:
                    return self._send_error(
                        code="EXPORT_NOT_FOUND",
                        message="export not found",
                        details={"export_id": token},
                        status=HTTPStatus.NOT_FOUND,
                        endpoint=path,
                    )
                _invalidate_cache("/api/exports", "/api/export/status", "/api/delivery/tracking", "/api/archive/stats", "/api/storage/usage")
                return self._send_json({"ok": True, "export_id": token, "deleted": True})

            if path.startswith("/api/jobs/"):
                token = path.split("/api/jobs/", 1)[1].strip().split("/", 1)[0]
                if not token:
                    return self._send_error(
                        code="JOB_ID_REQUIRED",
                        message="job id is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                deleted = job_db_store.delete_job(token)
                if not deleted:
                    existing = job_db_store.get_job(token)
                    if existing is None:
                        return self._send_error(
                            code="JOB_NOT_FOUND",
                            message="job not found",
                            details={"job_id": token},
                            status=HTTPStatus.NOT_FOUND,
                            endpoint=path,
                        )
                    return self._send_error(
                        code="JOB_DELETE_BLOCKED",
                        message="Only completed, failed, or cancelled jobs can be deleted",
                        details={"job_id": token, "status": existing.status},
                        status=HTTPStatus.CONFLICT,
                        endpoint=path,
                    )
                job_event_broker.publish(
                    "job_deleted",
                    {"job_id": token, "catalog_id": runtime_req.catalog_id},
                )
                return self._send_json({"ok": True, "job_id": token, "deleted": True})

            if path.startswith("/api/books/") and "/tags/" in path:
                token = path.split("/api/books/", 1)[1]
                book_token, tag_token = token.split("/tags/", 1)
                book_number = _safe_int(book_token, 0)
                tag = tag_token.strip()
                if book_number <= 0 or not tag:
                    return self._send_error(
                        code="INVALID_BOOK_TAG_PAYLOAD",
                        message="book must be positive and tag is required",
                        status=HTTPStatus.BAD_REQUEST,
                        endpoint=path,
                    )
                updated = book_metadata.remove_tag(_book_metadata_path_for_runtime(runtime_req), book_number, tag)
                _invalidate_cache("/api/books", "/api/compare")
                return self._send_json({"ok": True, "book": book_number, "tags": updated.get("tags", [])})

            if path == "/api/drive/schedule":
                payload = {
                    "enabled": False,
                    "interval_hours": 0,
                    "mode": "disabled",
                    "catalogs": [runtime_req.catalog_id],
                }
                saved = _save_drive_schedule(runtime_req, payload)
                _invalidate_cache("/api/drive/schedule", "/api/drive/status")
                return self._send_json({"ok": True, "catalog": runtime_req.catalog_id, "schedule": saved})

            return self._send_error(
                code="ENDPOINT_NOT_FOUND",
                message="Unknown endpoint",
                status=HTTPStatus.NOT_FOUND,
                endpoint=path,
            )

        def log_message(self, fmt: str, *args):
            logger.info("%s", fmt % args)

        def _send_json(
            self,
            payload: dict[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
            *,
            headers: dict[str, str] | None = None,
            cache_control: str = "no-store",
            catalog_id: str | None = None,
        ):
            normalized = dict(payload)
            request_id = self._current_request_id()
            normalized["request_id"] = request_id

            is_error_response = int(status) >= 400 or bool(normalized.get("ok") is False)
            if is_error_response:
                normalized["ok"] = False
                message = ""
                if isinstance(normalized.get("error"), str) and str(normalized.get("error", "")).strip():
                    message = str(normalized.get("error", "")).strip()
                elif isinstance(normalized.get("error_message"), str) and str(normalized.get("error_message", "")).strip():
                    message = str(normalized.get("error_message", "")).strip()
                elif isinstance(normalized.get("message"), str) and str(normalized.get("message", "")).strip():
                    message = str(normalized.get("message", "")).strip()
                else:
                    message = "Request failed"
                normalized["error"] = message
                normalized["error_message"] = message
                if "error_code" not in normalized:
                    normalized["error_code"] = str(normalized.get("code", "REQUEST_FAILED"))

            if "success" not in normalized:
                if "ok" in normalized:
                    normalized["success"] = bool(normalized.get("ok"))
                elif isinstance(normalized.get("error"), bool):
                    normalized["success"] = not bool(normalized.get("error"))
                else:
                    normalized["success"] = int(status) < 400
            raw = json.dumps(normalized, ensure_ascii=False).encode("utf-8")
            use_gzip = "gzip" in str(self.headers.get("Accept-Encoding", "")).lower() and len(raw) >= 1200
            data = gzip.compress(raw) if use_gzip else raw
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Request-Id", request_id)
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            if headers:
                for key, value in headers.items():
                    self.send_header(str(key), str(value))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            try:
                started = float(getattr(self, "_request_started_at", 0.0) or 0.0)
                if started > 0:
                    _record_slow_request(
                        method=str(getattr(self, "_request_method", "GET")),
                        path=str(getattr(self, "_request_path", self.path)),
                        duration_seconds=time.perf_counter() - started,
                        status_code=int(status),
                        catalog_id=str(catalog_id or self._current_catalog() or ""),
                    )
            except Exception:
                pass
            try:
                runtime_for_slo = self._runtime_for_catalog_token(str(catalog_id or "").strip() or self._current_catalog())
                _slo_tracker_for_runtime(runtime_for_slo).record_response(
                    int(status),
                    catalog_id=runtime_for_slo.catalog_id,
                )
            except Exception:  # pragma: no cover - best effort
                pass

        def _send_file(
            self,
            file_path: Path,
            *,
            content_type: str = "application/octet-stream",
            cache_control: str = "public, max-age=86400",
            headers: dict[str, str] | None = None,
            catalog_id: str | None = None,
        ):
            try:
                safe_path = security.sanitize_path(file_path, PROJECT_ROOT)
            except Exception:
                return self._send_error(
                    code="PATH_NOT_ALLOWED",
                    message="Requested file path is not allowed",
                    details={"path": str(file_path)},
                    status=HTTPStatus.FORBIDDEN,
                    endpoint=self.path,
                )
            try:
                content = safe_path.read_bytes()
            except OSError:
                return self._send_error(
                    code="FILE_READ_ERROR",
                    message="Failed to read requested file",
                    details={"path": str(safe_path)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    endpoint=self.path,
                )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Request-Id", self._current_request_id())
            if headers:
                for key, value in headers.items():
                    self.send_header(str(key), str(value))
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            try:
                started = float(getattr(self, "_request_started_at", 0.0) or 0.0)
                if started > 0:
                    _record_slow_request(
                        method=str(getattr(self, "_request_method", "GET")),
                        path=str(getattr(self, "_request_path", self.path)),
                        duration_seconds=time.perf_counter() - started,
                        status_code=int(HTTPStatus.OK),
                        catalog_id=str(catalog_id or self._current_catalog() or ""),
                    )
            except Exception:
                pass
            try:
                runtime_for_slo = self._runtime_for_catalog_token(str(catalog_id or "").strip() or self._current_catalog())
                _slo_tracker_for_runtime(runtime_for_slo).record_response(
                    int(HTTPStatus.OK),
                    catalog_id=runtime_for_slo.catalog_id,
                )
            except Exception:  # pragma: no cover - best effort
                pass

        def _send_bytes(
            self,
            content: bytes,
            *,
            content_type: str = "application/octet-stream",
            cache_control: str = "public, max-age=86400",
            headers: dict[str, str] | None = None,
            catalog_id: str | None = None,
        ):
            payload = bytes(content or b"")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Request-Id", self._current_request_id())
            if headers:
                for key, value in headers.items():
                    self.send_header(str(key), str(value))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            try:
                started = float(getattr(self, "_request_started_at", 0.0) or 0.0)
                if started > 0:
                    _record_slow_request(
                        method=str(getattr(self, "_request_method", "GET")),
                        path=str(getattr(self, "_request_path", self.path)),
                        duration_seconds=time.perf_counter() - started,
                        status_code=int(HTTPStatus.OK),
                        catalog_id=str(catalog_id or self._current_catalog() or ""),
                    )
            except Exception:
                pass
            try:
                runtime_for_slo = self._runtime_for_catalog_token(str(catalog_id or "").strip() or self._current_catalog())
                _slo_tracker_for_runtime(runtime_for_slo).record_response(
                    int(HTTPStatus.OK),
                    catalog_id=runtime_for_slo.catalog_id,
                )
            except Exception:  # pragma: no cover - best effort
                pass

        def _serve_job_events(
            self,
            *,
            catalog_id: str | None = None,
            job_id: str | None = None,
            batch_id: str | None = None,
        ):
            scoped_job_id = str(job_id or "").strip()
            scoped_batch_id = str(batch_id or "").strip()
            client_ip = str(self.client_address[0] if self.client_address else "unknown")
            sse_key = f"{client_ip}:{str(catalog_id or '*').strip().lower() or '*'}"
            if not sse_connection_limiter.start(sse_key):
                return self._send_error(
                    code="SSE_CONNECTION_LIMIT",
                    message="Too many active event streams for this client/catalog. Close an existing stream and retry.",
                    details={"limit_per_client": SSE_MAX_CONNECTIONS_PER_CLIENT},
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                    endpoint=self.path,
                    headers={"Retry-After": "10"},
                )
            token = ""
            client_queue: queue.Queue[dict[str, Any]] | None = None
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            try:
                token, client_queue = job_event_broker.subscribe()
                bootstrap = {
                    "event": "ready",
                    "catalog_id": str(catalog_id or ""),
                    "job_id": scoped_job_id,
                    "batch_id": scoped_batch_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self.wfile.write(f"event: ready\ndata: {json.dumps(bootstrap, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
                while True:
                    try:
                        event = client_queue.get(timeout=20.0) if client_queue is not None else {}
                    except queue.Empty:
                        keepalive = f": ping {datetime.now(timezone.utc).isoformat()}\n\n".encode("utf-8")
                        self.wfile.write(keepalive)
                        self.wfile.flush()
                        continue

                    if catalog_id:
                        event_catalog = str(event.get("catalog_id", "") or "")
                        if event_catalog and event_catalog != str(catalog_id):
                            continue
                    if scoped_job_id:
                        event_job = str(event.get("job_id", "") or "")
                        if event_job != scoped_job_id:
                            continue
                    if scoped_batch_id:
                        event_batch = str(event.get("batch_id", "") or "")
                        if event_batch != scoped_batch_id:
                            continue
                    event_name = str(event.get("event", "message") or "message")
                    payload = json.dumps(event, ensure_ascii=False)
                    chunk = f"event: {event_name}\ndata: {payload}\n\n".encode("utf-8")
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                return
            finally:
                if token:
                    job_event_broker.unsubscribe(token)
                sse_connection_limiter.finish(sse_key)

        def _send_error(
            self,
            *,
            code: str,
            message: str,
            details: dict[str, Any] | None = None,
            status: HTTPStatus = HTTPStatus.BAD_REQUEST,
            endpoint: str = "",
            headers: dict[str, str] | None = None,
        ):
            runtime_for_error = self._current_runtime()
            try:
                catalog_token = self._current_catalog()
                if not catalog_token:
                    try:
                        catalog_token = str(parse_qs(urlparse(self.path).query).get("catalog", [""])[0] or "").strip()
                    except Exception:
                        catalog_token = ""
                runtime_for_error = self._runtime_for_catalog_token(catalog_token)
                error_metrics.record_error(
                    code,
                    endpoint=endpoint or self.path,
                    details=details or {},
                    catalog_id=runtime_for_error.catalog_id,
                )
            except Exception:  # pragma: no cover - best effort
                pass
            safe_message = str(message or "Request failed").strip() or "Request failed"
            for pattern in (
                r"\bsk-[A-Za-z0-9_-]{12,}\b",
                r"\bsk-proj-[A-Za-z0-9_-]{12,}\b",
                r"\bsk-or-v1-[A-Za-z0-9_-]{12,}\b",
                r"\bAIza[0-9A-Za-z_-]{20,}\b",
            ):
                safe_message = re.sub(pattern, lambda m: security.mask_api_key(m.group(0)), safe_message)
            raw_details = details if isinstance(details, dict) else {}
            safe_details = security.scrub_sensitive(raw_details)
            if "idempotency_key" in raw_details:
                safe_details["idempotency_key"] = str(raw_details.get("idempotency_key", ""))
            payload = {
                "ok": False,
                "error": safe_message,
                "error_message": safe_message,
                "error_code": str(code or "REQUEST_FAILED"),
                "code": str(code or "REQUEST_FAILED"),
                "message": safe_message,
                "details": safe_details,
                "request_id": self._current_request_id(),
            }
            return self._send_json(payload, status=status, headers=headers, catalog_id=runtime_for_error.catalog_id)

    class StableThreadingHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 128

    server = StableThreadingHTTPServer((bind_host, port), Handler)
    shutdown_requested = threading.Event()
    previous_sigint_handler = None
    previous_sigterm_handler = None

    def _background_startup() -> None:
        local_slo_monitor: SLOBackgroundMonitor | None = None
        local_workers_started = False
        try:
            _bootstrap_state_store_for_runtime(default_runtime)
            _prime_catalog_file_caches(default_runtime)
            try:
                config.sync_openrouter_pricing(api_key=default_runtime.openrouter_api_key)
            except Exception as exc:
                logger.warning("OpenRouter pricing sync skipped during startup: %s", exc)
            config.start_openrouter_pricing_sync(api_key=default_runtime.openrouter_api_key)
            default_runtime.model_cost_usd = config.runtime_model_costs_copy()
            default_runtime.cost_per_image_usd = default_runtime.get_model_cost(default_runtime.ai_model)
            _set_startup_health(_run_startup_checks(default_runtime))
            _ensure_builtin_prompts_seeded(runtime=default_runtime, actor="startup")
            stale_after_seconds, retry_delay_seconds = _job_stale_recovery_config(default_runtime)
            recovered = job_db_store.recover_stale_running_jobs(
                stale_after_seconds=stale_after_seconds,
                retry_delay_seconds=retry_delay_seconds,
            )
            if recovered:
                logger.warning("Recovered stale jobs on startup", extra={"recovered_jobs": recovered})

            slo_monitor_interval_seconds = _slo_monitor_interval_seconds(default_runtime)
            if slo_monitor_interval_seconds > 0:
                local_slo_monitor = SLOBackgroundMonitor(interval_seconds=slo_monitor_interval_seconds)
                local_slo_monitor.start()
                _set_slo_background_monitor(local_slo_monitor)
                logger.info(
                    "Background SLO monitor started",
                    extra={"interval_seconds": slo_monitor_interval_seconds},
                )
            else:
                _set_slo_background_monitor(None)
                logger.info("Background SLO monitor disabled", extra={"interval_seconds": slo_monitor_interval_seconds})

            if mode == "inline":
                job_worker_pool.start()
                local_workers_started = True
            elif mode == "external":
                logger.info("Web server running in external worker mode (enqueue/poll only)")
            else:
                logger.warning("Web server running with workers disabled")

            with server_runtime_state_lock:
                server_runtime_state["slo_monitor"] = local_slo_monitor
                server_runtime_state["workers_started"] = local_workers_started
            _set_startup_state(status="ready")
        except Exception as exc:
            logger.exception("Background startup initialization failed")
            _set_startup_health(
                {
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "healthy": False,
                    "issues": [f"startup_initialization_failed: {exc}"],
                    "warnings": [],
                    "checks": [],
                }
            )
            _set_startup_state(status="failed", error=str(exc))

    def _request_shutdown(signum: int, _frame: Any) -> None:
        if shutdown_requested.is_set():
            return
        shutdown_requested.set()
        logger.info("Shutdown signal received", extra={"signal": int(signum)})
        threading.Thread(target=server.shutdown, name="server-shutdown", daemon=True).start()

    try:
        previous_sigint_handler = signal.getsignal(signal.SIGINT)
        previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _request_shutdown)
        signal.signal(signal.SIGTERM, _request_shutdown)
    except Exception:
        previous_sigint_handler = None
        previous_sigterm_handler = None

    shown_host = bind_host if bind_host not in {"0.0.0.0", "::"} else "127.0.0.1"
    threading.Thread(target=_background_startup, name="startup-init", daemon=True).start()
    logger.info("Review webapp running at http://%s:%d/review", shown_host, port)
    logger.info("Iteration page running at http://%s:%d/iterate", shown_host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested, stopping review webapp")
    finally:
        try:
            if previous_sigint_handler is not None:
                signal.signal(signal.SIGINT, previous_sigint_handler)
            if previous_sigterm_handler is not None:
                signal.signal(signal.SIGTERM, previous_sigterm_handler)
        except Exception:
            pass
        try:
            _flush_all_slo_trackers()
        except Exception:  # pragma: no cover - best effort
            pass
        with server_runtime_state_lock:
            slo_monitor = server_runtime_state.get("slo_monitor")
            workers_started = bool(server_runtime_state.get("workers_started"))
        if isinstance(slo_monitor, SLOBackgroundMonitor):
            slo_monitor.stop(timeout_seconds=1.5)
            _set_slo_background_monitor(None)
        if workers_started:
            job_worker_pool.stop(timeout_seconds=2.5)
        server.server_close()


def _resolve_composited_candidate(image_path: Path, *, runtime: config.Config | None = None) -> Path | None:
    runtime_cfg = runtime or config.get_config()
    if len(image_path.parts) < 2:
        return None

    variant = _parse_variant(image_path.stem)
    if variant <= 0:
        return None

    # Structure A: tmp/generated/{book}/variant_n.png
    if image_path.parent.name.isdigit():
        book = image_path.parent.name
        return runtime_cfg.tmp_dir / "composited" / book / f"variant_{variant}.jpg"

    # Structure B: tmp/generated/{book}/{model}/variant_n.png
    if image_path.parent.parent.name.isdigit():
        book = image_path.parent.parent.name
        model = image_path.parent.name
        return runtime_cfg.tmp_dir / "composited" / book / model / f"variant_{variant}.jpg"

    return None


def _resolve_composited_companion(composite_path: Path, suffix: str) -> Path | None:
    token = str(suffix or "").strip().lower()
    if token not in {".pdf", ".ai"}:
        return None
    return composite_path.with_suffix(token)


def _parse_variant(stem: str) -> int:
    if "variant_" not in stem:
        return 0
    token = stem.split("variant_", 1)[1].split("_", 1)[0]
    try:
        return int(token)
    except ValueError:
        return 0


def _find_original_image(input_book: Path) -> Path | None:
    if not input_book.exists():
        return None
    jpgs = sorted(input_book.glob("*.jpg"))
    return jpgs[0] if jpgs else None


def _find_first_jpg(folder: Path) -> Path | None:
    jpgs = sorted(folder.glob("*.jpg"))
    return jpgs[0] if jpgs else None


def _parse_variant_number(name: str) -> int | None:
    if not name.startswith("Variant-"):
        return None
    try:
        return int(name.split("-", 1)[1])
    except ValueError:
        return None


def _load_quality_lookup(path: Path) -> dict[tuple[int, int], float]:
    payload = _load_json(path, {"scores": []})
    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    lookup: dict[tuple[int, int], float] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            book = int(row.get("book_number", 0))
            variant = int(row.get("variant_id", 0))
            score = float(row.get("overall_score", 0.0))
        except (TypeError, ValueError):
            continue
        key = (book, variant)
        lookup[key] = max(lookup.get(key, 0.0), score)

    return lookup


def _variant_priority(variant: int) -> int:
    return 0 if variant in {1, 2, 3} else 1


def _auto_pick_winner(book: dict[str, Any]) -> tuple[int, float]:
    candidates: list[tuple[int, float]] = []
    for item in book.get("variants", []):
        try:
            variant = int(item.get("variant", 0))
            score = float(item.get("quality_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if variant <= 0:
            continue
        candidates.append((variant, score))

    if not candidates:
        return 1, 0.0

    winner, score = sorted(
        candidates,
        key=lambda row: (
            -row[1],  # higher score first
            _variant_priority(row[0]),  # sketch variants first on ties
            row[0],  # stable tie-break
        ),
    )[0]
    return winner, score


def _load_winner_payload(path: Path) -> dict[str, Any]:
    catalog_id = _catalog_id_from_winner_path(path)
    try:
        selections = state_db_store.load_winner_selections(catalog_id=catalog_id)
        if selections:
            scores = []
            for value in selections.values():
                if isinstance(value, dict):
                    try:
                        scores.append(float(value.get("score", 0.0) or 0.0))
                    except (TypeError, ValueError):
                        pass
            return {
                "selections": selections,
                "selection_date": datetime.now(timezone.utc).isoformat(),
                "total_books": len(selections),
                "average_winner_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
                "min_winner_score": round(min(scores), 4) if scores else 0.0,
                "max_winner_score": round(max(scores), 4) if scores else 0.0,
            }
    except Exception as exc:  # pragma: no cover - fallback to JSON
        logger.warning("State DB winner load failed for catalog %s: %s", catalog_id, exc)

    if not path.exists():
        return {"selections": {}}
    payload = safe_json.load_json(path, {"selections": {}})

    if isinstance(payload, dict) and isinstance(payload.get("selections"), dict):
        return payload
    if isinstance(payload, dict):
        # Backward compatibility: plain map.
        return {"selections": payload}
    return {"selections": {}}


def _winner_map_to_plain(selections: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in selections.items():
        try:
            book = str(int(str(key).strip()))
        except ValueError:
            continue
        try:
            if isinstance(value, dict):
                winner = int(value.get("winner", 0) or 0)
            else:
                winner = int(value or 0)
        except (TypeError, ValueError):
            continue
        if winner > 0:
            out[book] = winner
    return out


def _selection_path_for_winner_path(path: Path) -> Path:
    catalog_id = _catalog_id_from_winner_path(path)
    return config.variant_selections_path(catalog_id=catalog_id, data_dir=path.parent)


def _save_winner_payload(path: Path, selections: dict[str, Any], total_books: int) -> dict[str, Any]:
    scores = []
    for value in selections.values():
        if isinstance(value, dict):
            try:
                scores.append(float(value.get("score", 0.0) or 0.0))
            except (TypeError, ValueError):
                pass

    payload = {
        "selections": selections,
        "selection_date": datetime.now(timezone.utc).isoformat(),
        "total_books": int(total_books),
        "average_winner_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "min_winner_score": round(min(scores), 4) if scores else 0.0,
        "max_winner_score": round(max(scores), 4) if scores else 0.0,
    }
    catalog_id = _catalog_id_from_winner_path(path)
    try:
        state_db_store.upsert_winner_selections(catalog_id=catalog_id, selections=selections, replace=True)
    except Exception as exc:  # pragma: no cover - fallback to JSON
        logger.warning("State DB winner save failed for catalog %s: %s", catalog_id, exc)
    selection_path = _selection_path_for_winner_path(path)
    safe_json.atomic_write_many_json(
        [
            (path, payload),
            (selection_path, _winner_map_to_plain(selections)),
        ]
    )
    return payload


def _ensure_winner_payload(books: list[dict[str, Any]], *, path: Path = WINNER_SELECTIONS_PATH) -> dict[str, Any]:
    payload = _load_winner_payload(path)
    selections = payload.get("selections", {})
    if not isinstance(selections, dict):
        selections = {}

    changed = False
    for book in books:
        number = str(int(book.get("number", 0)))
        existing = selections.get(number)

        auto_variant, auto_score = _auto_pick_winner(book)
        if not isinstance(existing, dict):
            selections[number] = {
                "winner": auto_variant,
                "score": round(auto_score, 4),
                "auto_selected": True,
                "confirmed": False,
            }
            changed = True
            continue

        try:
            winner = int(existing.get("winner", 0) or 0)
        except (TypeError, ValueError):
            winner = 0
        if winner <= 0:
            winner = auto_variant
            changed = True

        try:
            score = float(existing.get("score", auto_score) or auto_score)
        except (TypeError, ValueError):
            score = auto_score

        merged = dict(existing)
        merged["winner"] = winner
        merged["score"] = round(score if score > 0 else auto_score, 4)
        merged["auto_selected"] = bool(existing.get("auto_selected", True))
        merged["confirmed"] = bool(existing.get("confirmed", False))
        selections[number] = merged

    persisted = False
    if changed or not path.exists():
        payload = _save_winner_payload(path, selections, total_books=len(books))
        persisted = True
    else:
        payload["selections"] = selections

    # Maintain legacy plain variant map for compatibility.
    if not persisted:
        selection_path = _selection_path_for_winner_path(path)
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        safe_json.atomic_write_json(selection_path, _winner_map_to_plain(selections))
    return payload


def _load_json(path: Path, default: Any) -> Any:
    payload = safe_json.load_json(path, default)
    if isinstance(default, dict) and isinstance(payload, dict):
        return payload
    if isinstance(default, list) and isinstance(payload, list):
        return payload
    if not isinstance(default, (dict, list)):
        return payload
    return default


def _append_generation_history(path: Path, items: list[dict[str, Any]]) -> None:
    output = _build_generation_history_payload(path, items)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_json.atomic_write_json(path, output)


def _history_row_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    job_id = str(row.get("job_id", "") or "").strip()
    if job_id:
        return (
            "job",
            job_id,
            _safe_int(row.get("book_number"), 0),
            _safe_int(row.get("variant"), _safe_int(row.get("variant_id"), 0)),
            str(row.get("model", "")),
            str(row.get("provider", "")),
            bool(row.get("dry_run", False)),
        )
    return (
        "legacy",
        str(row.get("timestamp", "")),
        _safe_int(row.get("book_number"), 0),
        _safe_int(row.get("variant"), _safe_int(row.get("variant_id"), 0)),
        str(row.get("model", "")),
        str(row.get("provider", "")),
        str(row.get("image_path", "")),
        bool(row.get("success", True)),
        str(row.get("prompt", "")),
    )


def _build_generation_history_payload(path: Path, items: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_json(path, {"items": []})
    history = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(history, list):
        history = []
    existing_keys = {
        _history_row_identity(row)
        for row in history
        if isinstance(row, dict)
    }
    deduped_new: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        key = _history_row_identity(row)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        deduped_new.append(row)
    history.extend(deduped_new)
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": history[-5000:],
    }


def _resolve_credentials_path(runtime: config.Config) -> Path:
    token = runtime.google_credentials_path.strip()
    if token:
        return Path(token)
    return runtime.config_dir / "credentials.json"


def _validate_drive_cover_request(
    *,
    runtime: config.Config,
    book: int,
    cover_source: str,
    selected_cover_id: str,
    selected_cover: Any,
    selected_cover_book_number: int,
    drive_folder_id: str,
    input_folder_id: str,
    credentials_path_token: str,
) -> tuple[bool, str, str]:
    source = str(cover_source or "catalog").strip().lower() or "catalog"
    if source != "drive":
        return True, "", ""

    selected_id = str(selected_cover_id or "").strip()
    if not selected_id and isinstance(selected_cover, dict):
        selected_id = str(selected_cover.get("id", "")).strip()

    mapped_book = int(selected_cover_book_number or 0)
    if mapped_book <= 0 and isinstance(selected_cover, dict):
        mapped_book = _safe_int(selected_cover.get("book_number"), 0)
    if mapped_book > 0 and mapped_book != int(book):
        # Treat stale UI hints as non-fatal and fall back to book-based resolution.
        selected_id = ""

    if not selected_id:
        # Drive-first mode auto-resolves the source cover in the execution pipeline.
        return True, "", ""

    effective_drive_folder_id = (
        str(drive_folder_id or "").strip()
        or runtime.gdrive_source_folder_id
        or runtime.gdrive_input_folder_id
        or runtime.gdrive_output_folder_id
    )
    effective_input_folder_id = (
        str(input_folder_id or "").strip()
        or runtime.gdrive_source_folder_id
        or runtime.gdrive_input_folder_id
    )
    if not effective_drive_folder_id:
        return False, "Google Drive source folder is not configured.", ""

    credentials_path = Path(credentials_path_token) if str(credentials_path_token or "").strip() else _resolve_credentials_path(runtime)
    if not credentials_path.is_absolute():
        credentials_path = PROJECT_ROOT / credentials_path

    payload = drive_manager.list_input_covers(
        drive_folder_id=effective_drive_folder_id,
        input_folder_id=effective_input_folder_id,
        credentials_path=credentials_path,
        catalog_path=runtime.book_catalog_path,
        limit=2000,
    )
    if not isinstance(payload, dict):
        return False, "Unable to validate selected Drive cover.", ""
    error_text = str(payload.get("error", "")).strip()
    if error_text:
        return False, f"Drive cover validation failed: {error_text}", ""

    rows = payload.get("covers", [])
    if not isinstance(rows, list):
        rows = []
    candidate = next(
        (
            row for row in rows
            if isinstance(row, dict) and str(row.get("id", "")).strip() == selected_id
        ),
        None,
    )
    if isinstance(candidate, dict):
        resolved_book = _safe_int(candidate.get("book_number"), 0)
        if resolved_book == int(book):
            return True, "", str(candidate.get("id", "")).strip()

    fallback = next(
        (
            row for row in rows
            if isinstance(row, dict) and _safe_int(row.get("book_number"), 0) == int(book)
        ),
        None,
    )
    if isinstance(fallback, dict):
        return True, "", str(fallback.get("id", "")).strip()

    return False, f"No cover found in Google Drive for book #{int(book)}.", ""


def _validate_catalog_cover_request(
    *,
    runtime: config.Config,
    book: int,
    cover_source: str,
) -> tuple[bool, str]:
    source = str(cover_source or "catalog").strip().lower() or "catalog"
    if source != "catalog":
        return True, ""
    if _local_cover_available(runtime=runtime, book_number=int(book)):
        return True, ""
    return (
        False,
        f"No local cover is available for book {int(book)}. "
        "Switch Cover Source to Google Drive for automatic cover download.",
    )


def _drive_credentials_mode(
    runtime: config.Config,
    *,
    credentials_path: Path | None = None,
) -> tuple[str | None, str | None]:
    creds_json = str(getattr(runtime, "google_credentials_json", "") or "").strip()
    if creds_json:
        return "service_account_env", None

    path = credentials_path or _resolve_credentials_path(runtime)
    if path.exists():
        payload = _load_json(path, {})
        if isinstance(payload, dict):
            if payload.get("type") == "service_account":
                return "service_account_file", None
            return "oauth_file", None
        return "credentials_file", None

    return None, "No Google credentials found. Set GOOGLE_CREDENTIALS_JSON environment variable."


def _save_raw_drive_status_payload(*, runtime: config.Config) -> dict[str, Any]:
    service, credentials_path, mode, credentials_meta, connection_error = _drive_service_for_runtime(runtime)
    payload: dict[str, Any] = {
        "ok": True,
        "connected": False,
        "mode": mode,
        "error": connection_error,
        "credentials_path": str(credentials_path),
        "credentials": credentials_meta,
        "service_account_email": str(credentials_meta.get("client_email", "") or ""),
        "parent_folder_id": SAVE_RAW_DRIVE_FOLDER_ID,
        "parent_folder_access": False,
        "parent_folder_name": "",
        "parent_folder_url": f"https://drive.google.com/drive/folders/{SAVE_RAW_DRIVE_FOLDER_ID}",
        "write_access": False,
        "write_probe_error": "",
        "retry_supported": False,
    }
    if service is None:
        return payload

    payload["connected"] = True
    try:
        parent = service.files().get(
            fileId=SAVE_RAW_DRIVE_FOLDER_ID,
            fields="id,name,webViewLink",
            supportsAllDrives=True,
        ).execute()
    except Exception as exc:
        details = _drive_error_details(exc)
        payload["error"] = details["message"]
        return payload

    payload["parent_folder_access"] = bool(str(parent.get("id", "") or "").strip())
    payload["parent_folder_name"] = str(parent.get("name", "") or "")
    payload["parent_folder_url"] = str(parent.get("webViewLink", "") or payload["parent_folder_url"])
    write_probe = _probe_drive_write_access(service=service, parent_folder_id=SAVE_RAW_DRIVE_FOLDER_ID)
    payload["write_access"] = bool(write_probe.get("ok", False))
    payload["write_probe_error"] = str(write_probe.get("error", "") or "")
    payload["retry_supported"] = payload["connected"] and payload["parent_folder_access"] and payload["write_access"]
    return payload


def _collect_selected_variant_files(output_dir: Path, selections: dict[str, Any], *, catalog_path: Path = config.BOOK_CATALOG_PATH) -> list[str]:
    if not selections:
        return []

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    folder_by_book: dict[int, str] = {}
    for row in catalog:
        try:
            number = int(row.get("number", 0))
        except (TypeError, ValueError):
            continue
        folder_name = str(row.get("folder_name", ""))
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]
        folder_by_book[number] = folder_name

    files: list[str] = []
    for key, value in selections.items():
        try:
            book_number = int(str(key).strip())
            if isinstance(value, dict):
                variant = int(value.get("winner", 0) or 0)
            else:
                variant = int(value)
        except (TypeError, ValueError):
            continue
        if variant <= 0:
            continue
        folder_name = folder_by_book.get(book_number)
        if not folder_name:
            continue
        variant_dir = output_dir / folder_name / f"Variant-{variant}"
        if not variant_dir.exists():
            continue
        for file_path in sorted(variant_dir.glob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in {".jpg", ".pdf", ".ai"}:
                continue
            files.append(str(file_path.relative_to(output_dir)))

    # Preserve order but remove duplicates.
    deduped = list(dict.fromkeys(files))
    return deduped


def _drive_sync_log_path(runtime: config.Config) -> Path:
    return config.drive_sync_log_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _gdrive_sync_state_path(runtime: config.Config) -> Path:
    return config.gdrive_sync_state_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _append_drive_sync_log(*, runtime: config.Config, entry: dict[str, Any]) -> None:
    path = _drive_sync_log_path(runtime)
    payload = _load_json(path, {"updated_at": "", "items": []})
    items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []
    items.append({"timestamp": datetime.now(timezone.utc).isoformat(), **(entry if isinstance(entry, dict) else {})})
    safe_json.atomic_write_json(path, {"updated_at": datetime.now(timezone.utc).isoformat(), "items": items[-500:]})


def _drive_schedule_path(runtime: config.Config) -> Path:
    return config.drive_schedule_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _default_drive_schedules(catalog_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "push-6h",
            "name": "Push new winners",
            "enabled": True,
            "interval_hours": 6,
            "mode": "push",
            "catalogs": [catalog_id],
        },
        {
            "id": "full-24h",
            "name": "Full bidirectional sync",
            "enabled": True,
            "interval_hours": 24,
            "mode": "bidirectional",
            "catalogs": [catalog_id],
        },
    ]


def _normalize_drive_schedule_rows(rows: list[dict[str, Any]], *, catalog_id: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows):
        if not isinstance(raw, dict):
            continue
        requested_interval = max(1, _safe_int(raw.get("interval_hours"), 6))
        allowed = [1, 4, 6, 12, 24]
        interval_hours = min(allowed, key=lambda value: abs(value - requested_interval))
        mode_token = str(raw.get("mode", "push")).strip().lower() or "push"
        if mode_token not in {"push", "pull", "bidirectional", "sync"}:
            mode_token = "push"
        name = str(raw.get("name", "")).strip() or ("Push new winners" if mode_token == "push" else "Full bidirectional sync")
        schedule_id = str(raw.get("id", "")).strip() or f"schedule-{idx + 1}"
        catalogs = raw.get("catalogs")
        if not isinstance(catalogs, list) or not catalogs:
            catalogs = [catalog_id]
        normalized.append(
            {
                "id": schedule_id,
                "name": name,
                "enabled": bool(raw.get("enabled", True)),
                "interval_hours": interval_hours,
                "mode": mode_token,
                "catalogs": [str(item).strip() for item in catalogs if str(item).strip()] or [catalog_id],
            }
        )
    return normalized


def _load_drive_schedule(runtime: config.Config) -> dict[str, Any]:
    payload = _load_json(_drive_schedule_path(runtime), {})
    if not isinstance(payload, dict):
        payload = {}
    raw_schedules = payload.get("schedules")
    schedules: list[dict[str, Any]]
    if isinstance(raw_schedules, list) and raw_schedules:
        schedules = _normalize_drive_schedule_rows([row for row in raw_schedules if isinstance(row, dict)], catalog_id=runtime.catalog_id)
    else:
        legacy = {
            "enabled": bool(payload.get("enabled", True)),
            "interval_hours": _safe_int(payload.get("interval_hours"), 6),
            "mode": str(payload.get("mode", "push")).strip().lower() or "push",
            "catalogs": payload.get("catalogs", [runtime.catalog_id]) if isinstance(payload.get("catalogs"), list) else [runtime.catalog_id],
        }
        schedules = _normalize_drive_schedule_rows([legacy], catalog_id=runtime.catalog_id)
        if not schedules:
            schedules = _default_drive_schedules(runtime.catalog_id)

    if not schedules:
        schedules = _default_drive_schedules(runtime.catalog_id)

    primary = schedules[0]
    return {
        "enabled": any(bool(row.get("enabled", False)) for row in schedules),
        "interval_hours": _safe_int(primary.get("interval_hours"), 6),
        "mode": str(primary.get("mode", "push")),
        "catalogs": primary.get("catalogs", [runtime.catalog_id]),
        "schedules": schedules,
        "updated_at": str(payload.get("updated_at", datetime.now(timezone.utc).isoformat())),
    }


def _save_drive_schedule(runtime: config.Config, payload: dict[str, Any]) -> dict[str, Any]:
    requested_rows = payload.get("schedules")
    if isinstance(requested_rows, list) and requested_rows:
        schedules = _normalize_drive_schedule_rows([row for row in requested_rows if isinstance(row, dict)], catalog_id=runtime.catalog_id)
    else:
        legacy = {
            "id": str(payload.get("id", "manual")).strip() or "manual",
            "name": str(payload.get("name", "Manual schedule")).strip() or "Manual schedule",
            "enabled": bool(payload.get("enabled", True)),
            "interval_hours": _safe_int(payload.get("interval_hours"), 6),
            "mode": str(payload.get("mode", "bidirectional")).strip().lower() or "bidirectional",
            "catalogs": payload.get("catalogs", [runtime.catalog_id]) if isinstance(payload.get("catalogs"), list) else [runtime.catalog_id],
        }
        schedules = _normalize_drive_schedule_rows([legacy], catalog_id=runtime.catalog_id)
    if not schedules:
        schedules = _default_drive_schedules(runtime.catalog_id)

    primary = schedules[0]
    output = {
        "enabled": any(bool(row.get("enabled", False)) for row in schedules),
        "interval_hours": _safe_int(primary.get("interval_hours"), 6),
        "mode": str(primary.get("mode", "push")),
        "catalogs": primary.get("catalogs", [runtime.catalog_id]),
        "schedules": schedules,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    safe_json.atomic_write_json(_drive_schedule_path(runtime), output)
    return output


def _export_manifest_path(runtime: config.Config) -> Path:
    return config.exports_manifest_path(catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _export_tracking_path(runtime: config.Config) -> Path:
    return config.catalog_scoped_data_path("export_tracking.json", catalog_id=runtime.catalog_id, data_dir=runtime.data_dir)


def _load_export_tracking(runtime: config.Config) -> dict[str, Any]:
    payload = _load_json(_export_tracking_path(runtime), {"updated_at": "", "items": []})
    if not isinstance(payload, dict):
        payload = {"updated_at": "", "items": []}
    rows = payload.get("items", [])
    if not isinstance(rows, list):
        rows = []
    payload["items"] = [row for row in rows if isinstance(row, dict)]
    return payload


def _save_export_tracking(runtime: config.Config, payload: dict[str, Any]) -> None:
    rows = payload.get("items", [])
    if not isinstance(rows, list):
        rows = []
    safe_json.atomic_write_json(
        _export_tracking_path(runtime),
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": rows[-10000:],
        },
    )


def _winner_signature_map(*, runtime: config.Config) -> dict[int, str]:
    titles, folder_by_book = _catalog_maps(catalog_path=runtime.book_catalog_path)
    winners_payload = _load_winner_payload(_winner_path_for_runtime(runtime))
    selections = winners_payload.get("selections", {}) if isinstance(winners_payload, dict) else {}
    if not isinstance(selections, dict):
        selections = {}
    out: dict[int, str] = {}
    for key, value in selections.items():
        book = _safe_int(key, 0)
        if book <= 0:
            continue
        winner_variant = _safe_int(value.get("winner") if isinstance(value, dict) else value, 0)
        if winner_variant <= 0:
            continue
        folder = folder_by_book.get(book, "")
        image = _find_first_jpg(runtime.output_dir / folder / f"Variant-{winner_variant}") if folder else None
        signature = f"missing:{winner_variant}:{titles.get(book, f'Book {book}')}"
        if image and image.exists():
            stat = image.stat()
            signature = hashlib.sha1(
                f"{winner_variant}:{int(stat.st_size)}:{int(stat.st_mtime)}:{_to_project_relative(image)}".encode("utf-8")
            ).hexdigest()
        out[book] = signature
    return out


def _record_export_tracking(
    *,
    runtime: config.Config,
    export_type: str,
    summary: dict[str, Any],
    export_id: str,
) -> None:
    export_token = str(export_type or "").strip().lower()
    if export_token not in {"amazon", "ingram", "social", "web"}:
        return
    payload = _load_export_tracking(runtime)
    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []

    index_map: dict[tuple[int, str], dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        book = _safe_int(row.get("book_number"), 0)
        platform = str(row.get("platform", "")).strip().lower()
        if book > 0 and platform:
            index_map[(book, platform)] = row

    signature_map = _winner_signature_map(runtime=runtime)
    now = datetime.now(timezone.utc).isoformat()
    results = summary.get("results", []) if isinstance(summary.get("results"), list) else []
    errors = summary.get("errors", []) if isinstance(summary.get("errors"), list) else []
    error_books = {_safe_int(row.get("book_number"), 0) for row in errors if isinstance(row, dict)}

    for row in results:
        if not isinstance(row, dict):
            continue
        book = _safe_int(row.get("book_number"), 0)
        if book <= 0:
            continue
        key = (book, export_token)
        current = index_map.get(key, {"book_number": book, "platform": export_token})
        current.update(
            {
                "book_number": book,
                "platform": export_token,
                "catalog": runtime.catalog_id,
                "status": "failed" if book in error_books else "exported",
                "last_exported_at": now,
                "export_id": export_id,
                "file_count": _safe_int(row.get("file_count"), 0),
                "export_path": str(row.get("export_path", "")).strip(),
                "source_signature": signature_map.get(book, ""),
                "updated_at": now,
            }
        )
        index_map[key] = current

    items = sorted(index_map.values(), key=lambda row: (_safe_int(row.get("book_number"), 0), str(row.get("platform", ""))))
    payload["items"] = items
    _save_export_tracking(runtime, payload)


def _export_status_rows(*, runtime: config.Config) -> list[dict[str, Any]]:
    payload = _load_export_tracking(runtime)
    rows = payload.get("items", [])
    if not isinstance(rows, list):
        rows = []
    signature_map = _winner_signature_map(runtime=runtime)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        book = _safe_int(row.get("book_number"), 0)
        if book <= 0:
            continue
        current_sig = signature_map.get(book, "")
        stored_sig = str(row.get("source_signature", "")).strip()
        changed = bool(current_sig and stored_sig and current_sig != stored_sig)
        out.append(
            {
                **row,
                "book_number": book,
                "platform": str(row.get("platform", "")).strip().lower(),
                "changed_since_last_export": changed,
                "current_source_signature": current_sig,
            }
        )
    out.sort(key=lambda row: (_safe_int(row.get("book_number"), 0), str(row.get("platform", ""))))
    return out


def _export_status_by_book(*, runtime: config.Config) -> dict[int, dict[str, Any]]:
    rows = _export_status_rows(runtime=runtime)
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        book = _safe_int(row.get("book_number"), 0)
        if book <= 0:
            continue
        platform = str(row.get("platform", "")).strip().lower()
        if not platform:
            continue
        out.setdefault(book, {})[platform] = row
    return out


def _validate_export_readiness_for_book(*, runtime: config.Config, book_number: int) -> dict[str, Any]:
    winners = export_utils.load_winner_books(
        catalog_path=runtime.book_catalog_path,
        output_root=runtime.output_dir,
        selections_path=_winner_path_for_runtime(runtime),
        quality_path=_quality_scores_path_for_runtime(runtime),
    )
    winner = winners.get(int(book_number))
    if winner is None:
        return {
            "ok": False,
            "book_number": int(book_number),
            "catalog": runtime.catalog_id,
            "error": f"Winner not available for book {book_number}",
            "platforms": {
                "amazon": {"ready": False, "status": "failed", "reasons": ["missing_winner_selection"]},
                "ingram": {"ready": False, "status": "failed", "reasons": ["missing_winner_selection"]},
                "social": {"ready": False, "status": "failed", "reasons": ["missing_winner_selection"]},
                "web": {"ready": False, "status": "failed", "reasons": ["missing_winner_selection"]},
            },
        }

    cover_path = Path(winner.cover_path)
    if not cover_path.exists():
        return {
            "ok": False,
            "book_number": int(book_number),
            "catalog": runtime.catalog_id,
            "error": f"Winner cover file not found: {cover_path}",
            "platforms": {
                "amazon": {"ready": False, "status": "failed", "reasons": ["missing_cover_file"]},
                "ingram": {"ready": False, "status": "failed", "reasons": ["missing_cover_file"]},
                "social": {"ready": False, "status": "failed", "reasons": ["missing_cover_file"]},
                "web": {"ready": False, "status": "failed", "reasons": ["missing_cover_file"]},
            },
        }

    with Image.open(cover_path) as cover:
        source_mode = str(cover.mode or "").upper()
        source_width, source_height = cover.size
        source_dpi = cover.info.get("dpi", ())
        front, _spine, _back, _detail = export_utils.crop_cover_regions(cover.convert("RGB"))

    front_width, front_height = front.size
    front_ratio = float(front_height) / float(max(1, front_width))
    front_file_size_mb = round(float(cover_path.stat().st_size) / (1024.0 * 1024.0), 4)
    dpi_value = tuple(source_dpi) if isinstance(source_dpi, tuple) else ()
    dpi_x = _safe_int(dpi_value[0] if len(dpi_value) > 0 else 0, 0)
    dpi_y = _safe_int(dpi_value[1] if len(dpi_value) > 1 else 0, 0)

    amazon_reasons: list[str] = []
    if front_width < 625 or front_height < 1000:
        amazon_reasons.append("front_cover_too_small_for_kdp")
    if front_ratio < 1.45 or front_ratio > 1.75:
        amazon_reasons.append("front_cover_aspect_ratio_out_of_range")
    if source_mode not in {"RGB", "RGBA", "CMYK"}:
        amazon_reasons.append("unsupported_source_color_mode")

    ingram_reasons: list[str] = []
    if source_width < 1200 or source_height < 1800:
        ingram_reasons.append("cover_resolution_too_small_for_print")
    if source_mode not in {"RGB", "RGBA", "CMYK"}:
        ingram_reasons.append("unsupported_source_color_mode")
    if int(getattr(winner, "page_count", 0) or 0) <= 0:
        ingram_reasons.append("missing_page_count")

    social_reasons: list[str] = []
    if source_width < 1080 or source_height < 1080:
        social_reasons.append("cover_too_small_for_social_derivatives")

    web_reasons: list[str] = []
    if source_width < 600 or source_height < 900:
        web_reasons.append("cover_too_small_for_web_derivatives")

    platforms = {
        "amazon": {
            "ready": len(amazon_reasons) == 0,
            "status": "completed" if len(amazon_reasons) == 0 else "failed",
            "reasons": amazon_reasons,
            "checks": {
                "front_size": [front_width, front_height],
                "target_size": [1600, 2560],
                "front_ratio": round(front_ratio, 6),
                "source_mode": source_mode,
                "source_dpi": [dpi_x, dpi_y],
                "source_file_size_mb": front_file_size_mb,
            },
        },
        "ingram": {
            "ready": len(ingram_reasons) == 0,
            "status": "completed" if len(ingram_reasons) == 0 else "failed",
            "reasons": ingram_reasons,
            "checks": {
                "cover_size": [source_width, source_height],
                "source_mode": source_mode,
                "expected_mode": "CMYK (converted during export)",
                "source_dpi": [dpi_x, dpi_y],
                "page_count": int(getattr(winner, "page_count", 0) or 0),
            },
        },
        "social": {
            "ready": len(social_reasons) == 0,
            "status": "completed" if len(social_reasons) == 0 else "failed",
            "reasons": social_reasons,
            "checks": {"cover_size": [source_width, source_height]},
        },
        "web": {
            "ready": len(web_reasons) == 0,
            "status": "completed" if len(web_reasons) == 0 else "failed",
            "reasons": web_reasons,
            "checks": {"cover_size": [source_width, source_height]},
        },
    }
    return {
        "ok": all(bool(row.get("ready")) for row in platforms.values()),
        "book_number": int(book_number),
        "catalog": runtime.catalog_id,
        "winner_variant": int(getattr(winner, "winner_variant", 0) or 0),
        "winner_cover_path": _to_project_relative(cover_path),
        "platforms": platforms,
    }


def _load_export_manifest(runtime: config.Config) -> dict[str, Any]:
    payload = _load_json(_export_manifest_path(runtime), {"updated_at": "", "exports": []})
    if not isinstance(payload, dict):
        payload = {"updated_at": "", "exports": []}
    rows = payload.get("exports", [])
    if not isinstance(rows, list):
        rows = []
    payload["exports"] = [row for row in rows if isinstance(row, dict)]
    return payload


def _save_export_manifest(runtime: config.Config, payload: dict[str, Any]) -> None:
    rows = payload.get("exports", [])
    if not isinstance(rows, list):
        rows = []
    safe_json.atomic_write_json(
        _export_manifest_path(runtime),
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "exports": rows[-2000:],
        },
    )


def _directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    return int(total)


def _file_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.rglob("*") if p.is_file())


def _register_export_result(*, runtime: config.Config, export_type: str, summary: dict[str, Any]) -> str:
    token = f"{str(export_type).strip().lower()}-{runtime.catalog_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    export_path = EXPORTS_ROOT / str(export_type).strip().lower() / runtime.catalog_id
    reported = str(summary.get("export_path", "") or summary.get("output", "")).strip()
    if reported:
        candidate = Path(reported)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.exists():
            export_path = candidate
    row = {
        "id": token,
        "catalog": runtime.catalog_id,
        "type": str(export_type).strip().lower(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "path": _to_project_relative(export_path),
        "size_bytes": _directory_size_bytes(export_path),
        "file_count": _safe_int(summary.get("file_count"), _file_count(export_path)),
        "books_exported": _safe_int(summary.get("books_exported"), 0),
    }
    manifest = _load_export_manifest(runtime)
    exports = manifest.get("exports", [])
    if not isinstance(exports, list):
        exports = []
    exports.append(row)
    manifest["exports"] = exports
    _save_export_manifest(runtime, manifest)
    _record_export_tracking(runtime=runtime, export_type=export_type, summary=summary, export_id=token)
    return token


def _summarize_generation_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or bool(row.get("success")):
            continue
        failure_meta = row.get("failure_meta", {}) if isinstance(row.get("failure_meta"), dict) else {}
        status_code = _safe_int(failure_meta.get("status_code"), 0)
        failures.append(
            {
                "model": str(row.get("model", "")).strip(),
                "variant": _safe_int(row.get("variant", row.get("variant_id", 0)), 0),
                "provider": str(row.get("provider", failure_meta.get("provider", ""))).strip(),
                "attempts": _safe_int(row.get("attempts"), 0),
                "status_code": status_code if status_code > 0 else None,
                "error": str(row.get("error", "") or failure_meta.get("error", "") or "unknown error").strip(),
                "retry_count": _safe_int(failure_meta.get("retry_count"), _safe_int(row.get("attempts"), 0)),
                "error_type": str(failure_meta.get("error_type", "")).strip(),
            }
        )
    return failures


def _exports_listing_payload(*, runtime: config.Config) -> dict[str, Any]:
    manifest = _load_export_manifest(runtime)
    rows = manifest.get("exports", [])
    if not isinstance(rows, list):
        rows = []
    fresh: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path_token = str(row.get("path", "")).strip()
        path_obj = PROJECT_ROOT / path_token if path_token else Path("")
        if path_token and path_obj.exists():
            updated = dict(row)
            updated["size_bytes"] = _directory_size_bytes(path_obj)
            updated["file_count"] = _file_count(path_obj)
            updated["updated_at"] = datetime.fromtimestamp(path_obj.stat().st_mtime, tz=timezone.utc).isoformat()
            fresh.append(updated)
    manifest["exports"] = fresh
    _save_export_manifest(runtime, manifest)
    return {"ok": True, "catalog": runtime.catalog_id, "exports": list(reversed(fresh)), "count": len(fresh)}


def _resolve_export_row(*, runtime: config.Config, export_id: str) -> dict[str, Any] | None:
    payload = _load_export_manifest(runtime)
    rows = payload.get("exports", [])
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("id", "")).strip() == str(export_id).strip():
            return row
    return None


def _build_export_zip(*, export_id: str, runtime: config.Config) -> Path:
    row = _resolve_export_row(runtime=runtime, export_id=export_id)
    if row is None:
        raise FileNotFoundError(export_id)
    rel_path = str(row.get("path", "")).strip()
    source = PROJECT_ROOT / rel_path
    if not source.exists():
        raise FileNotFoundError(export_id)
    zip_path = runtime.tmp_dir / "exports" / f"{export_id}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=str(source))
    return zip_path


def _delete_export(*, export_id: str, runtime: config.Config) -> bool:
    manifest = _load_export_manifest(runtime)
    rows = manifest.get("exports", [])
    if not isinstance(rows, list):
        rows = []
    kept: list[dict[str, Any]] = []
    removed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("id", "")).strip() != str(export_id).strip():
            kept.append(row)
            continue
        rel_path = str(row.get("path", "")).strip()
        target = PROJECT_ROOT / rel_path if rel_path else Path("")
        if target.exists():
            try:
                if target.is_file():
                    target.unlink()
                else:
                    shutil.rmtree(target)
            except Exception:
                pass
        removed = True
    manifest["exports"] = kept
    _save_export_manifest(runtime, manifest)
    return removed


def _archive_old_exports(*, days: int, runtime: config.Config) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    archive_root = EXPORTS_ROOT / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)
    moved = 0
    bytes_moved = 0
    for export_type_dir in sorted(EXPORTS_ROOT.glob("*")):
        if not export_type_dir.is_dir():
            continue
        if export_type_dir.name == "archive":
            continue
        for catalog_dir in sorted(export_type_dir.glob("*")):
            if not catalog_dir.is_dir():
                continue
            if catalog_dir.name != runtime.catalog_id:
                continue
            for child in sorted(catalog_dir.glob("*")):
                try:
                    modified = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if modified >= cutoff:
                    continue
                target = archive_root / export_type_dir.name / catalog_dir.name / child.name
                target.parent.mkdir(parents=True, exist_ok=True)
                size_before = _directory_size_bytes(child) if child.is_dir() else int(child.stat().st_size)
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(child), str(target))
                moved += 1
                bytes_moved += size_before
    return {
        "catalog": runtime.catalog_id,
        "days": int(days),
        "moved_items": moved,
        "freed_gb": round(bytes_moved / (1024 ** 3), 6),
        "archive_root": str(archive_root),
    }


def _restore_archived_book(*, book_number: int, runtime: config.Config) -> dict[str, Any]:
    archive_root = EXPORTS_ROOT / "archive"
    restored = 0
    # Restore non-winner variants from output archive tree.
    output_archive_book = runtime.output_dir / "Archive"
    if output_archive_book.exists():
        for candidate in sorted(output_archive_book.glob(f"{book_number}.*")):
            target = runtime.output_dir / candidate.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(candidate), str(target))
            restored += 1
    # Restore export assets for book.
    for candidate in archive_root.rglob(str(book_number)):
        if not candidate.exists():
            continue
        parts = list(candidate.parts)
        if "archive" not in parts:
            continue
        idx = parts.index("archive")
        rel = Path(*parts[idx + 1 :])
        target = EXPORTS_ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(candidate), str(target))
        restored += 1
    return {"catalog": runtime.catalog_id, "book_number": int(book_number), "restored_items": restored}


def _archive_stats_payload(*, runtime: config.Config) -> dict[str, Any]:
    roots = [runtime.output_dir / "Archive", EXPORTS_ROOT / "archive"]
    file_count = 0
    total_bytes = 0
    mtimes: list[float] = []
    for root in roots:
        if not root.exists():
            continue
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            file_count += 1
            try:
                total_bytes += file_path.stat().st_size
                mtimes.append(file_path.stat().st_mtime)
            except OSError:
                continue
    date_range = {
        "oldest": datetime.fromtimestamp(min(mtimes), tz=timezone.utc).isoformat() if mtimes else None,
        "newest": datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat() if mtimes else None,
    }
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "archive_size_gb": round(total_bytes / (1024 ** 3), 6),
        "file_count": file_count,
        "date_range": date_range,
    }


def _storage_usage_payload(*, runtime: config.Config) -> dict[str, Any]:
    source_covers = _directory_size_bytes(runtime.input_dir)
    output_variants = _directory_size_bytes(runtime.output_dir) - _directory_size_bytes(runtime.output_dir / "Mockups")
    mockups = _directory_size_bytes(runtime.output_dir / "Mockups")
    social_cards = _directory_size_bytes(runtime.output_dir / "Social") + _directory_size_bytes(EXPORTS_ROOT / "social" / runtime.catalog_id)
    exports_size = _directory_size_bytes(EXPORTS_ROOT / runtime.catalog_id) + _directory_size_bytes(EXPORTS_ROOT / "amazon" / runtime.catalog_id) + _directory_size_bytes(EXPORTS_ROOT / "ingram" / runtime.catalog_id) + _directory_size_bytes(EXPORTS_ROOT / "web" / runtime.catalog_id)
    thumbnails = _directory_size_bytes(runtime.tmp_dir / "thumbnails")
    archive_size = _directory_size_bytes(runtime.output_dir / "Archive") + _directory_size_bytes(EXPORTS_ROOT / "archive")
    breakdown_bytes = {
        "source_covers": max(0, source_covers),
        "output_variants": max(0, output_variants),
        "mockups": max(0, mockups),
        "social_cards": max(0, social_cards),
        "exports": max(0, exports_size),
        "thumbnails": max(0, thumbnails),
        "archive": max(0, archive_size),
    }
    total_bytes = sum(breakdown_bytes.values())
    breakdown_human = {key: f"{(value / (1024 ** 3)):.3f} GB" for key, value in breakdown_bytes.items()}
    reclaimable_gb = (breakdown_bytes["output_variants"] * 0.4 + breakdown_bytes["archive"] * 0.8) / (1024 ** 3)
    return {
        "ok": True,
        "catalog": runtime.catalog_id,
        "total_gb": round(total_bytes / (1024 ** 3), 6),
        "breakdown": breakdown_human,
        "suggested_cleanup": f"Archive non-winners to free approximately {reclaimable_gb:.2f} GB",
    }


def _maybe_auto_delivery_for_books(*, runtime: config.Config, book_numbers: list[int], source: str) -> dict[str, Any]:
    cfg = delivery_pipeline.get_config(
        catalog_id=runtime.catalog_id,
        config_path=_delivery_config_path_for_runtime(runtime),
    )
    unique_books = sorted({int(book) for book in book_numbers if int(book) > 0})
    if not cfg.enabled:
        return {"enabled": False, "reason": "delivery_pipeline_disabled", "books": unique_books}
    if not unique_books:
        return {"enabled": True, "reason": "no_books", "books": []}
    credentials_path = _resolve_credentials_path(runtime)
    if not credentials_path.is_absolute():
        credentials_path = PROJECT_ROOT / credentials_path
    try:
        summary = delivery_pipeline.deliver_batch(
            catalog_id=runtime.catalog_id,
            book_numbers=unique_books,
            catalog_path=runtime.book_catalog_path,
            output_root=runtime.output_dir,
            selections_path=_winner_path_for_runtime(runtime),
            quality_path=_quality_scores_path_for_runtime(runtime),
            exports_root=EXPORTS_ROOT,
            delivery_config_path=_delivery_config_path_for_runtime(runtime),
            delivery_tracking_path=_delivery_tracking_path_for_runtime(runtime),
            drive_folder_id=runtime.gdrive_output_folder_id,
            credentials_path=credentials_path,
            platforms=None,
            progress_callback=None,
        )
        _invalidate_cache("/api/delivery/status", "/api/delivery/tracking", "/api/exports")
        return {"enabled": True, "trigger": source, "summary": summary}
    except Exception as exc:
        return {"enabled": True, "trigger": source, "error": str(exc)}


def _pull_from_local_mirror(*, mirror_dir: Path, input_dir: Path, incremental: bool = True) -> dict[str, Any]:
    if not mirror_dir.exists():
        raise FileNotFoundError(f"Local mirror path not found: {mirror_dir}")
    copied = 0
    skipped = 0
    failed = 0
    errors: list[dict[str, Any]] = []
    for source in sorted(mirror_dir.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(mirror_dir)
        target = input_dir / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if incremental and target.exists() and target.stat().st_size == source.stat().st_size:
                skipped += 1
                continue
            shutil.copy2(source, target)
            copied += 1
        except Exception as exc:  # pragma: no cover - filesystem edge cases
            failed += 1
            errors.append({"file": str(rel), "error": str(exc)})
    return {
        "mode": "local_mirror_pull",
        "mirror_dir": str(mirror_dir),
        "input_dir": str(input_dir),
        "copied": copied,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
    }


def _to_project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _safe_iso_datetime(token: str | None) -> datetime | None:
    if not token:
        return None
    raw = str(token).strip()
    if not raw:
        return None
    try:
        if "T" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromisoformat(f"{raw}T00:00:00+00:00")
    except ValueError:
        return None


def _normalize_model_name(model: str) -> str:
    text = str(model or "").strip()
    if "__" in text and "/" not in text:
        return text.replace("__", "/")
    return text


def _catalog_maps(*, catalog_path: Path = config.BOOK_CATALOG_PATH) -> tuple[dict[int, str], dict[int, str]]:
    payload = _load_json(catalog_path, [])
    rows = payload if isinstance(payload, list) else []
    title_by_book: dict[int, str] = {}
    folder_by_book: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        title_by_book[number] = str(row.get("title", f"Book {number}"))
        folder_name = str(row.get("folder_name", ""))
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]
        folder_by_book[number] = folder_name
    return title_by_book, folder_by_book


def _safe_file_stem(text: str) -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in str(text or "").strip())
    while "__" in token:
        token = token.replace("__", "_")
    token = token.strip("_")
    return (token[:120] or "book")


def _descriptive_download_filename(
    *,
    book_number: int,
    title: str,
    edition: str,
    model: str,
    variant: int,
    ext: str,
    source: bool = False,
) -> str:
    safe_title = _safe_file_stem(title)
    safe_model = _safe_file_stem(_normalize_model_name(model or "unknown"))
    safe_edition = _safe_file_stem(edition or "standard")
    suffix = "source" if source else "cover"
    return f"Book{int(book_number):03d}_{safe_title}_{safe_edition}_{safe_model}_{suffix}_v{int(variant)}.{ext.lstrip('.')}"


def _book_title_and_edition(*, runtime: config.Config, book_number: int) -> tuple[str, str]:
    payload = _load_json(runtime.book_catalog_path, [])
    rows = payload if isinstance(payload, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _safe_int(row.get("number"), 0) != int(book_number):
            continue
        title = str(row.get("title", f"Book {book_number}"))
        edition = str(row.get("edition", row.get("format", "paperback")) or "paperback").strip() or "paperback"
        return title, edition
    return f"Book {book_number}", "paperback"


def _source_image_for_variant(
    *,
    runtime: config.Config,
    book_number: int,
    variant: int,
    model: str = "",
    record: dict[str, Any] | None = None,
) -> Path | None:
    # 1) Most reliable: persisted raw-art path from generation record.
    if isinstance(record, dict):
        raw_art = _project_path_if_exists(record.get("raw_art_path"))
        if raw_art is not None and raw_art.exists():
            return raw_art
    # 2) Original generated image path from generation record.
    if isinstance(record, dict):
        medallion_png = _project_path_if_exists(record.get("image_path"))
        if medallion_png is not None and medallion_png.exists():
            return medallion_png
    # 3) Durable output directory fallback.
    raw_art_dir = runtime.output_dir / "raw_art" / str(int(book_number))
    if raw_art_dir.exists():
        candidates = sorted(raw_art_dir.glob(f"*variant_{int(variant)}_*.png"))
        if candidates:
            return candidates[-1]
    # 4) Legacy/generated tmp directory fallback.
    generated_dir = runtime.tmp_dir / "generated" / str(int(book_number))
    if model:
        model_dir = generated_dir / image_generator._model_to_directory(model)  # type: ignore[attr-defined]
        candidate = model_dir / f"variant_{int(variant)}.png"
        if candidate.exists():
            return candidate
    candidate = next(iter(sorted(generated_dir.glob(f"*/variant_{int(variant)}.png"))), None)
    if candidate and candidate.exists():
        return candidate
    return None


def _project_path_if_exists(path_token: str | Path | None) -> Path | None:
    if path_token is None:
        return None
    token = str(path_token).strip()
    if not token:
        return None
    path = Path(token)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
        token_lstrip = token.lstrip("/")
        if token_lstrip:
            candidates.append(PROJECT_ROOT / token_lstrip)
    else:
        candidates.append(PROJECT_ROOT / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _latest_variant_record(
    *,
    runtime: config.Config,
    book_number: int,
    variant: int,
    model: str = "",
) -> dict[str, Any] | None:
    model_token = str(model or "").strip().lower()
    rows = [
        row
        for row in _load_generation_records(runtime=runtime)
        if isinstance(row, dict)
        and _safe_int(row.get("book_number"), 0) == int(book_number)
        and _safe_int(row.get("variant"), _safe_int(row.get("variant_id"), 0)) == int(variant)
    ]
    if model_token:
        filtered = [row for row in rows if str(row.get("model", "")).strip().lower() == model_token]
        if filtered:
            rows = filtered
    if not rows:
        return None
    rows.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
    return rows[0]


def _variant_output_dir(*, runtime: config.Config, book_number: int, variant: int) -> Path | None:
    _, folder_by_book = _catalog_maps(catalog_path=runtime.book_catalog_path)
    folder_name = folder_by_book.get(int(book_number), "")
    if not folder_name:
        return None
    path = runtime.output_dir / folder_name / f"Variant-{int(variant)}"
    return path if path.exists() else None


def _jpg_to_pdf_bytes(jpg_path: Path) -> bytes:
    with Image.open(jpg_path).convert("RGB") as image:
        buffer = io.BytesIO()
        image.save(buffer, format="PDF", resolution=300.0)
        return buffer.getvalue()


def _build_variant_download_zip(
    *,
    runtime: config.Config,
    book_number: int,
    variant: int,
    model: str = "",
) -> tuple[Path, str]:
    record = _latest_variant_record(runtime=runtime, book_number=book_number, variant=variant, model=model)
    variant_dir = _variant_output_dir(runtime=runtime, book_number=book_number, variant=variant)
    if record is None and variant_dir is None:
        raise FileNotFoundError(f"No variant data found for book {book_number} variant {variant}")

    cover_jpg: Path | None = None
    cover_pdf: Path | None = None
    cover_ai: Path | None = None
    generated_raw_image: Path | None = None
    source_raw_image: Path | None = _first_local_cover_path(runtime=runtime, book_number=book_number)

    if variant_dir is not None:
        jpg_rows = sorted(variant_dir.glob("*.jpg"))
        pdf_rows = sorted(variant_dir.glob("*.pdf"))
        ai_rows = sorted(variant_dir.glob("*.ai"))
        cover_jpg = jpg_rows[0] if jpg_rows else None
        cover_pdf = pdf_rows[0] if pdf_rows else None
        cover_ai = ai_rows[0] if ai_rows else None

    if cover_jpg is None and isinstance(record, dict):
        cover_jpg = _project_path_if_exists(record.get("composited_path"))
        if cover_jpg is None:
            source_image = _project_path_if_exists(record.get("image_path"))
            if source_image is not None:
                candidate = _resolve_composited_candidate(source_image, runtime=runtime)
                if candidate is not None and candidate.exists():
                    cover_jpg = candidate
    if cover_jpg is None:
        raise FileNotFoundError(f"Missing composited JPG for book {book_number} variant {variant}")

    generated_raw_image = _source_image_for_variant(
        runtime=runtime,
        book_number=book_number,
        variant=variant,
        model=model,
        record=record,
    )
    # Avoid duplicate raw payloads when both references point to the source cover.
    if (
        generated_raw_image is not None
        and source_raw_image is not None
        and generated_raw_image.resolve() == source_raw_image.resolve()
    ):
        generated_raw_image = None

    if cover_ai is None and isinstance(record, dict):
        for key in ("composited_ai_path", "composite_ai_url", "ai_path"):
            candidate = _project_path_if_exists(record.get(key))
            if candidate is not None and candidate.exists():
                cover_ai = candidate
                break

    _, folder_by_book = _catalog_maps(catalog_path=runtime.book_catalog_path)
    folder_name = folder_by_book.get(int(book_number), "")
    book_title, edition = _book_title_and_edition(runtime=runtime, book_number=book_number)
    model_name = str((record or {}).get("model", model or "unknown"))
    cover_jpg_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=variant,
        ext="jpg",
        source=False,
    )
    cover_pdf_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=variant,
        ext="pdf",
        source=False,
    )
    cover_ai_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=variant,
        ext="ai",
        source=False,
    )
    generated_raw_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=variant,
        ext=(generated_raw_image.suffix.lstrip(".") if generated_raw_image is not None else "png"),
        source=True,
    ).replace("_source_", "_generated_raw_")
    source_raw_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=variant,
        ext=(source_raw_image.suffix.lstrip(".") if source_raw_image is not None else "png"),
        source=True,
    ).replace("_source_", "_source_raw_")

    composite_jpg_arc = f"composites/{cover_jpg_name}"
    composite_pdf_arc = f"composites/{cover_pdf_name}"
    composite_ai_arc = f"composites/{cover_ai_name}" if cover_ai is not None else ""
    generated_raw_arc = f"source_images/{generated_raw_name}" if generated_raw_image is not None else ""
    source_raw_arc = f"source_files/{source_raw_name}" if source_raw_image is not None else ""

    metadata = {
        "book_number": int(book_number),
        "book_title": book_title,
        "variant_number": int(variant),
        "model": model_name,
        "prompt": str((record or {}).get("prompt", "")),
        "quality_score": _safe_float((record or {}).get("quality_score"), 0.0),
        "generation_timestamp": str((record or {}).get("timestamp", "")),
        "catalog": runtime.catalog_id,
        "folder_name": folder_name,
        "composite_jpg": composite_jpg_arc,
        "composite_pdf": composite_pdf_arc,
        "composite_ai": composite_ai_arc,
        "generated_raw_image": generated_raw_arc,
        "source_raw_image": source_raw_arc,
    }

    downloads_dir = runtime.tmp_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="variant-", suffix=".zip", dir=str(downloads_dir), delete=False) as handle:
        zip_path = Path(handle.name)

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(cover_jpg, arcname=composite_jpg_arc)
        if cover_pdf is not None and cover_pdf.exists():
            archive.write(cover_pdf, arcname=composite_pdf_arc)
        else:
            archive.writestr(composite_pdf_arc, _jpg_to_pdf_bytes(cover_jpg))
        if cover_ai is not None and cover_ai.exists():
            archive.write(cover_ai, arcname=composite_ai_arc)
        if generated_raw_image is not None and generated_raw_image.exists():
            archive.write(generated_raw_image, arcname=generated_raw_arc)
        if source_raw_image is not None and source_raw_image.exists():
            archive.write(source_raw_image, arcname=source_raw_arc)
        manifest_csv = (
            "book_number,title,edition,model,variant,composite_jpg,composite_pdf,composite_ai,generated_raw_image,source_raw_image,quality_score\n"
            f"{int(book_number)},\"{book_title}\",\"{edition}\",\"{model_name}\",{int(variant)},\"{composite_jpg_arc}\",\"{composite_pdf_arc}\",\"{composite_ai_arc}\",\"{generated_raw_arc}\",\"{source_raw_arc}\",{_safe_float((record or {}).get('quality_score'), 0.0):.4f}\n"
        )
        archive.writestr("manifest.csv", manifest_csv)
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    zip_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=variant,
        ext="zip",
        source=False,
    ).replace("_cover_", "_package_")
    return zip_path, zip_name


def _build_winner_download_zip(*, runtime: config.Config, book_number: int) -> tuple[Path, str]:
    winners_payload = _load_winner_payload(_winner_path_for_runtime(runtime))
    selections = winners_payload.get("selections", {}) if isinstance(winners_payload, dict) else {}
    selected = selections.get(str(int(book_number)))
    if isinstance(selected, dict):
        winner_variant = _safe_int(selected.get("winner"), 0)
        selected_at = str(selected.get("selected_at", ""))
        reviewer = str(selected.get("reviewer", ""))
        winner_score = _safe_float(selected.get("score"), 0.0)
    else:
        winner_variant = _safe_int(selected, 0)
        selected_at = ""
        reviewer = ""
        winner_score = 0.0
    if winner_variant <= 0:
        raise FileNotFoundError(f"No winner selected for book {book_number}")

    variant_record = _latest_variant_record(
        runtime=runtime,
        book_number=int(book_number),
        variant=int(winner_variant),
    )
    variant_dir = _variant_output_dir(runtime=runtime, book_number=int(book_number), variant=int(winner_variant))
    if variant_dir is None:
        raise FileNotFoundError(f"Winner output folder missing for book {book_number} variant {winner_variant}")

    title_by_book, _ = _catalog_maps(catalog_path=runtime.book_catalog_path)
    book_title = str(title_by_book.get(int(book_number), f"Book {book_number}"))
    safe_title = _safe_file_stem(book_title)
    _, edition = _book_title_and_edition(runtime=runtime, book_number=book_number)
    model_name = str((variant_record or {}).get("model", "unknown"))

    cover_jpg = next(iter(sorted(variant_dir.glob("*.jpg"))), None)
    if cover_jpg is None:
        raise FileNotFoundError(f"Winner JPG missing for book {book_number} variant {winner_variant}")
    cover_pdf = next(iter(sorted(variant_dir.glob("*.pdf"))), None)
    cmyk_pdf = next(iter(sorted(variant_dir.glob("*CMYK*.pdf"))), None)
    if cmyk_pdf is None:
        cmyk_pdf = next(iter(sorted(variant_dir.glob("*cmyk*.pdf"))), None)

    medallion_png = _source_image_for_variant(
        runtime=runtime,
        book_number=int(book_number),
        variant=int(winner_variant),
        model=model_name,
        record=variant_record,
    )

    cover_jpg_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=winner_variant,
        ext="jpg",
        source=False,
    )
    cover_pdf_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=winner_variant,
        ext="pdf",
        source=False,
    )
    source_png_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=winner_variant,
        ext="png",
        source=True,
    )

    metadata = {
        "book_number": int(book_number),
        "book_title": book_title,
        "winner_variant": int(winner_variant),
        "model": model_name,
        "prompt": str((variant_record or {}).get("prompt", "")),
        "quality_score": _safe_float((variant_record or {}).get("quality_score"), winner_score),
        "generation_timestamp": str((variant_record or {}).get("timestamp", "")),
        "selection_date": selected_at,
        "reviewer": reviewer,
        "catalog": runtime.catalog_id,
    }

    downloads_dir = runtime.tmp_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="winner-", suffix=".zip", dir=str(downloads_dir), delete=False) as handle:
        zip_path = Path(handle.name)

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(cover_jpg, arcname=f"composites/{cover_jpg_name}")
        if cover_pdf is not None and cover_pdf.exists():
            archive.write(cover_pdf, arcname=f"composites/{cover_pdf_name}")
        else:
            archive.writestr(f"composites/{cover_pdf_name}", _jpg_to_pdf_bytes(cover_jpg))
        if medallion_png is not None and medallion_png.exists():
            archive.write(medallion_png, arcname=f"source_images/{source_png_name}")
        if cmyk_pdf is not None and cmyk_pdf.exists():
            cmyk_name = _descriptive_download_filename(
                book_number=book_number,
                title=book_title,
                edition=edition,
                model=model_name,
                variant=winner_variant,
                ext="pdf",
                source=False,
            ).replace(".pdf", "_CMYK.pdf")
            archive.write(cmyk_pdf, arcname=f"composites/{cmyk_name}")
        manifest_csv = (
            "book_number,title,edition,model,variant,composite_jpg,composite_pdf,source_image,quality_score\n"
            f"{int(book_number)},\"{book_title}\",\"{edition}\",\"{model_name}\",{int(winner_variant)},\"composites/{cover_jpg_name}\",\"composites/{cover_pdf_name}\",\"source_images/{source_png_name}\",{_safe_float((variant_record or {}).get('quality_score'), winner_score):.4f}\n"
        )
        archive.writestr("manifest.csv", manifest_csv)
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    zip_name = _descriptive_download_filename(
        book_number=book_number,
        title=book_title,
        edition=edition,
        model=model_name,
        variant=winner_variant,
        ext="zip",
        source=False,
    ).replace("_cover_", "_winner_")
    return zip_path, zip_name


def _latest_rows_for_book(*, runtime: config.Config, book_number: int) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _load_generation_records(runtime=runtime)
        if isinstance(row, dict) and _safe_int(row.get("book_number"), 0) == int(book_number)
    ]
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        model = str(row.get("model", "unknown"))
        variant = _safe_int(row.get("variant", row.get("variant_id", 0)), 0)
        if variant <= 0:
            continue
        key = (model, variant)
        current = latest.get(key)
        if current is None or str(row.get("timestamp", "")) > str(current.get("timestamp", "")):
            latest[key] = row
    out = list(latest.values())
    out.sort(key=lambda item: (str(item.get("model", "")), _safe_int(item.get("variant"), 0)))
    return out


def _build_source_download_file(
    *,
    runtime: config.Config,
    book_number: int,
    variant: int,
    model: str = "",
) -> tuple[Path, str]:
    record = _latest_variant_record(runtime=runtime, book_number=book_number, variant=variant, model=model)
    source = _source_image_for_variant(
        runtime=runtime,
        book_number=book_number,
        variant=variant,
        model=str(model),
        record=record,
    )
    if source is None or not source.exists():
        raise FileNotFoundError(f"Source image not found for book {book_number} variant {variant}")
    title, edition = _book_title_and_edition(runtime=runtime, book_number=book_number)
    model_name = str((record or {}).get("model", model or "unknown"))
    filename = _descriptive_download_filename(
        book_number=book_number,
        title=title,
        edition=edition,
        model=model_name,
        variant=variant,
        ext=source.suffix.lstrip(".") or "png",
        source=True,
    )
    return source, filename


def _primary_job_result_row(job: job_store.JobRecord | None) -> dict[str, Any] | None:
    rows = _job_result_rows(job)
    if not rows:
        return None
    for row in rows:
        if bool(row.get("success", False)):
            return row
    return rows[0]


def _row_variant_number(row: dict[str, Any] | None) -> int:
    if not isinstance(row, dict):
        return 0
    return _safe_int(row.get("variant"), _safe_int(row.get("variant_id"), 0))


def _save_raw_expectation_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    variant_value = source.get("expected_variant", source.get("variant", 0))
    display_variant_value = source.get("display_variant", 0)
    model_value = source.get("expected_model", source.get("model", ""))
    raw_art_value = source.get("expected_raw_art_path", source.get("raw_art_path", ""))
    saved_composited_value = source.get("expected_saved_composited_path", source.get("saved_composited_path", ""))
    return {
        "variant": max(0, _safe_int(variant_value, 0)),
        "display_variant": max(0, _safe_int(display_variant_value, 0)),
        "style_label": str(source.get("style_label", "") or "").strip(),
        "model": str(model_value or "").strip(),
        "raw_art_path": str(raw_art_value or "").strip(),
        "saved_composited_path": str(saved_composited_value or "").strip(),
    }


def _row_matches_save_raw_expectation(row: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    variant = _safe_int(expected.get("variant"), 0)
    if variant > 0 and _row_variant_number(row) != variant:
        return False
    model = str(expected.get("model", "") or "").strip()
    if model and str(row.get("model", "") or "").strip() != model:
        return False
    raw_art_path = str(expected.get("raw_art_path", "") or "").strip()
    if raw_art_path and str(row.get("raw_art_path", "") or "").strip() != raw_art_path:
        return False
    saved_composited_path = str(expected.get("saved_composited_path", "") or "").strip()
    if saved_composited_path:
        row_composite_paths = {
            str(row.get("saved_composited_path", "") or "").strip(),
            str(row.get("composited_path", "") or "").strip(),
        }
        row_composite_paths.discard("")
        if saved_composited_path not in row_composite_paths:
            return False
    return True


def _row_for_save_raw(*, job: job_store.JobRecord, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = _job_result_rows(job)
    if not rows:
        raise FileNotFoundError("No job results found")
    success_rows = [row for row in rows if bool(row.get("success", False))]
    pool = success_rows or rows
    normalized_expected = _save_raw_expectation_from_payload(expected)
    has_selector = any(
        [
            int(normalized_expected.get("variant", 0)) > 0,
            bool(str(normalized_expected.get("model", "") or "").strip()),
            bool(str(normalized_expected.get("raw_art_path", "") or "").strip()),
            bool(str(normalized_expected.get("saved_composited_path", "") or "").strip()),
        ]
    )
    if has_selector:
        matches = [row for row in pool if _row_matches_save_raw_expectation(row, normalized_expected)]
        if len(matches) == 1:
            return matches[0]
        details = {
            "job_id": str(job.id or "").strip(),
            "result_count": len(pool),
            "expected": normalized_expected,
            "available": [
                {
                    "variant": _row_variant_number(row),
                    "model": str(row.get("model", "") or "").strip(),
                    "raw_art_path": str(row.get("raw_art_path", "") or "").strip(),
                    "saved_composited_path": str(row.get("saved_composited_path", "") or "").strip(),
                }
                for row in pool
            ],
        }
        if not matches:
            raise SaveRawIntegrityError(
                "Save Raw refused because the selected result card does not match the backend job artifacts.",
                code="SAVE_RAW_SELECTION_MISMATCH",
                details=details,
            )
        raise SaveRawIntegrityError(
            "Save Raw refused because the backend job selection is ambiguous.",
            code="SAVE_RAW_SELECTION_AMBIGUOUS",
            details=details,
        )
    if len(pool) == 1:
        return pool[0]
    raise SaveRawIntegrityError(
        "Save Raw refused because this backend job contains multiple results and no exact selector was provided.",
        code="SAVE_RAW_SELECTION_REQUIRED",
        details={
            "job_id": str(job.id or "").strip(),
            "result_count": len(pool),
        },
    )


def _is_descendant_path(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _resolve_durable_raw_image_path(*, runtime: config.Config, row: dict[str, Any]) -> Path | None:
    raw_root = runtime.output_dir / "raw_art"
    for token in (row.get("raw_art_path"), row.get("image_path")):
        candidate = _project_path_if_exists(token)
        if candidate is None or not candidate.exists():
            continue
        if _is_descendant_path(candidate, raw_root):
            return candidate
    return None


def _resolve_durable_composite_image_path(*, runtime: config.Config, row: dict[str, Any]) -> Path | None:
    composite_root = runtime.output_dir / "saved_composites"
    candidate = _ensure_saved_composite_for_row(runtime=runtime, row=row)
    if candidate is not None and candidate.exists() and _is_descendant_path(candidate, composite_root):
        return candidate
    return None


def _save_raw_package_folder_name(
    *,
    job: job_store.JobRecord,
    row: dict[str, Any],
    display_variant: int | None = None,
) -> str:
    job_token = _generation_artifact_job_token(job_id=str(job.id or "").strip(), row=row)
    variant = max(1, int(display_variant or 0) or _row_variant_number(row))
    model_token = image_generator._model_to_directory(str(row.get("model", "") or "unknown"))  # type: ignore[attr-defined]
    safe_model_token = _display_filename_token(model_token, allow_en_dash=False).replace(" ", "_")
    return f"save-raw__{job_token}__variant-{variant}__{safe_model_token}"


def _resolve_raw_image_path_for_job(*, runtime: config.Config, job: job_store.JobRecord) -> Path | None:
    del runtime
    row = _primary_job_result_row(job)
    if not isinstance(row, dict):
        return None
    candidate = _project_path_if_exists(row.get("raw_art_path"))
    if candidate is not None and candidate.exists():
        return candidate
    candidate = _project_path_if_exists(row.get("image_path"))
    if candidate is not None and candidate.exists():
        return candidate
    return None


def _resolve_composite_image_path_for_job(*, runtime: config.Config, job: job_store.JobRecord) -> Path | None:
    row = _primary_job_result_row(job)
    if not isinstance(row, dict):
        return None
    candidate = _ensure_saved_composite_for_row(runtime=runtime, row=row)
    if candidate is not None and candidate.exists():
        return candidate
    candidate = _project_path_if_exists(row.get("composited_path"))
    if candidate is not None and candidate.exists():
        return candidate
    source_image = _project_path_if_exists(row.get("image_path"))
    if source_image is not None:
        derived = _resolve_composited_candidate(source_image, runtime=runtime)
        if derived is not None and derived.exists():
            return derived
    return None


def _display_filename_token(text: str, *, allow_en_dash: bool = True) -> str:
    token = str(text or "").strip()
    if not token:
        return "Untitled"
    token = re.sub(r"[\\/:*?\"<>|]", " ", token)
    if not allow_en_dash:
        token = token.replace("–", "-")
    token = re.sub(r"\s+", " ", token).strip()
    return token or "Untitled"


def _save_raw_display_variant(*, expected: dict[str, Any] | None, row: dict[str, Any]) -> int:
    requested = max(0, _safe_int((expected or {}).get("display_variant"), 0))
    if requested > 0:
        return requested
    return max(1, _row_variant_number(row))


def _save_raw_style_label(
    *,
    expected: dict[str, Any] | None,
    job: job_store.JobRecord,
    row: dict[str, Any],
) -> str:
    if isinstance(expected, dict):
        requested = str(expected.get("style_label", "") or "").strip()
        if requested:
            return requested
    payload_style = ""
    if isinstance(job.payload, dict):
        payload_style = str(job.payload.get("style_label", "") or "").strip()
    return str(
        payload_style
        or row.get("style_label")
        or row.get("prompt_name")
        or "Saved Cover"
    ).strip()


def _save_raw_filename_prefix(*, title: str, variant: int, style_label: str) -> str:
    title_token = _safe_filename_component(title)
    style_token = _safe_filename_component(style_label or "Saved Cover")
    return f"{title_token}_V{max(1, int(variant))}_{style_token}"


def _export_png_asset(
    *,
    source_image: Path | None,
    local_folder: Path,
    file_name: str,
) -> str | None:
    if source_image is None or not source_image.exists():
        return None
    destination = local_folder / file_name
    _copy_image_with_format(source_image, destination, format_name="PNG")
    return str(destination)


def _copy_image_with_format(source: Path, destination: Path, *, format_name: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_ext = source.suffix.lower().lstrip(".")
    expected_ext = destination.suffix.lower().lstrip(".")
    if source_ext == expected_ext and format_name.upper() in {"PNG", "JPEG"}:
        shutil.copy2(source, destination)
        return destination
    with Image.open(source) as img:
        rendered = img.convert("RGBA" if format_name.upper() == "PNG" else "RGB")
        rendered.save(destination, format=format_name)
    return destination


def _copy_pdf_bytes_as_ai(source_pdf: Path, destination_ai: Path) -> Path:
    destination_ai.parent.mkdir(parents=True, exist_ok=True)
    destination_ai.write_bytes(source_pdf.read_bytes())
    return destination_ai


def _resolve_composite_companion_for_job(
    *,
    job: job_store.JobRecord,
    suffix: str,
) -> Path | None:
    row = _primary_job_result_row(job)
    if not isinstance(row, dict):
        return None
    key = "composited_pdf_path" if suffix == ".pdf" else "composited_ai_path"
    candidate = _project_path_if_exists(row.get(key))
    if candidate is not None and candidate.exists():
        return candidate
    composite_path = _project_path_if_exists(row.get("saved_composited_path")) or _project_path_if_exists(row.get("composited_path"))
    if composite_path is None or not composite_path.exists():
        return None
    companion = _resolve_composited_companion(composite_path, suffix)
    if companion is not None and companion.exists():
        return companion
    return None


def _export_asset_triplet(
    *,
    source_image: Path | None,
    existing_pdf: Path | None,
    existing_ai: Path | None,
    local_folder: Path,
    base_filename: str,
) -> list[str]:
    if source_image is None or not source_image.exists():
        return []

    saved: list[str] = []
    jpg_target = local_folder / f"{base_filename}.jpg"
    pdf_target = local_folder / f"{base_filename}.pdf"
    ai_target = local_folder / f"{base_filename}.ai"

    saved.append(str(_copy_image_with_format(source_image, jpg_target, format_name="JPEG")))
    if existing_pdf is not None and existing_pdf.exists():
        shutil.copy2(existing_pdf, pdf_target)
    else:
        output_exporter.export_pdf(source_image, pdf_target)
    saved.append(str(pdf_target))

    if existing_ai is not None and existing_ai.exists():
        shutil.copy2(existing_ai, ai_target)
    elif pdf_target.exists():
        _copy_pdf_bytes_as_ai(pdf_target, ai_target)
    else:
        output_exporter.export_ai(source_image, ai_target)
    saved.append(str(ai_target))
    return saved


def _local_save_raw_root(*, runtime: config.Config) -> Path:
    return runtime.output_dir / SAVE_RAW_LOCAL_DIRNAME


def _escape_drive_query_value(token: str) -> str:
    return str(token or "").replace("\\", "\\\\").replace("'", "\\'")


def _drive_error_details(exc: Exception) -> dict[str, Any]:
    message = str(exc).strip() or exc.__class__.__name__
    error_code = ""
    http_status = 0
    content = getattr(exc, "content", None)
    if isinstance(content, (bytes, bytearray)):
        try:
            payload = json.loads(content.decode("utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            error_payload = payload.get("error", payload)
            if isinstance(error_payload, dict):
                nested_message = str(error_payload.get("message", "") or "").strip()
                if nested_message:
                    message = nested_message
                error_code = str(error_payload.get("status", "") or error_payload.get("code", "") or "").strip()
                detail_rows = error_payload.get("errors", [])
                if not error_code and isinstance(detail_rows, list) and detail_rows:
                    first = detail_rows[0]
                    if isinstance(first, dict):
                        error_code = str(first.get("reason", "") or first.get("domain", "") or "").strip()
    resp = getattr(exc, "resp", None)
    if resp is not None:
        try:
            http_status = int(getattr(resp, "status", 0) or 0)
        except Exception:
            http_status = 0
    if not error_code and "storageQuotaExceeded" in message:
        error_code = "storageQuotaExceeded"
    return {
        "message": message,
        "code": error_code,
        "http_status": http_status,
    }


def _drive_service_for_runtime(runtime: config.Config) -> tuple[Any | None, Path, str | None, dict[str, Any], str | None]:
    credentials_path = _resolve_credentials_path(runtime)
    if not credentials_path.is_absolute():
        credentials_path = PROJECT_ROOT / credentials_path
    mode, mode_error = _drive_credentials_mode(runtime, credentials_path=credentials_path)
    credentials_meta = gdrive_sync.credential_details(credentials_path)
    if not mode:
        return None, credentials_path, None, credentials_meta, mode_error or "Google Drive credentials are not configured."
    auth_path = None if mode == "service_account_env" else credentials_path
    try:
        service = gdrive_sync.authenticate(auth_path)
    except Exception as exc:
        return None, credentials_path, mode, credentials_meta, _drive_error_details(exc)["message"]
    return service, credentials_path, mode, credentials_meta, None


def _find_existing_drive_file_id(*, service: Any, parent_folder_id: str, file_name: str) -> str:
    file_name_query = _escape_drive_query_value(file_name)
    query = (
        f"name='{file_name_query}' and "
        f"'{str(parent_folder_id)}' in parents and "
        "trashed=false"
    )
    existing = service.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    if not existing:
        return ""
    return str(existing[0].get("id", "")).strip()


def _upload_single_file_to_drive(*, service: Any, parent_folder_id: str, file_path: Path) -> dict[str, Any]:
    max_attempts = SAVE_RAW_DRIVE_RETRY_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            existing_file_id = _find_existing_drive_file_id(
                service=service,
                parent_folder_id=parent_folder_id,
                file_name=file_path.name,
            )
            mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            media = gdrive_sync.MediaFileUpload(str(file_path), mimetype=mime_type)
            if existing_file_id:
                updated = service.files().update(
                    fileId=existing_file_id,
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                ).execute()
                file_id = str(updated.get("id", existing_file_id) or existing_file_id).strip()
                return {
                    "ok": True,
                    "name": file_path.name,
                    "path": str(file_path),
                    "file_id": file_id,
                    "drive_url": f"https://drive.google.com/file/d/{file_id}/view",
                    "action": "updated",
                    "attempts": attempt,
                }
            created = service.files().create(
                body={"name": file_path.name, "parents": [str(parent_folder_id)]},
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            file_id = str(created.get("id", "")).strip()
            if not file_id:
                raise RuntimeError("Google Drive file upload did not return an id")
            return {
                "ok": True,
                "name": file_path.name,
                "path": str(file_path),
                "file_id": file_id,
                "drive_url": f"https://drive.google.com/file/d/{file_id}/view",
                "action": "created",
                "attempts": attempt,
            }
        except Exception as exc:
            details = _drive_error_details(exc)
            if attempt < max_attempts and SAVE_RAW_DRIVE_RETRY_DELAY_SECONDS > 0:
                time.sleep(SAVE_RAW_DRIVE_RETRY_DELAY_SECONDS)
                continue
            return {
                "ok": False,
                "name": file_path.name,
                "path": str(file_path),
                "file_id": "",
                "drive_url": "",
                "action": "failed",
                "attempts": attempt,
                "error": details["message"],
                "error_code": details["code"],
                "http_status": details["http_status"],
            }


def _upload_folder_to_drive(
    *,
    runtime: config.Config,
    local_folder: Path,
    folder_name: str = "",
    folder_parts: list[str] | None = None,
    parent_folder_id: str,
) -> dict[str, Any]:
    local_files = [file_path for file_path in sorted(local_folder.iterdir()) if file_path.is_file()]
    normalized_parts = [
        str(part or "").strip()
        for part in (folder_parts if isinstance(folder_parts, list) and folder_parts else [folder_name])
        if str(part or "").strip()
    ]
    leaf_folder_name = normalized_parts[-1] if normalized_parts else str(folder_name or "").strip()
    service, credentials_path, mode, credentials_meta, connection_error = _drive_service_for_runtime(runtime)
    result: dict[str, Any] = {
        "ok": False,
        "mode": mode,
        "folder_name": leaf_folder_name,
        "folder_parts": normalized_parts,
        "parent_folder_id": str(parent_folder_id),
        "folder_id": "",
        "drive_url": None,
        "uploaded": [],
        "failed": [],
        "uploaded_count": 0,
        "failed_count": 0,
        "credentials_path": str(credentials_path),
        "credentials": credentials_meta,
        "warning": None,
        "error": connection_error,
    }
    if service is None:
        result["warning"] = connection_error or "Google Drive is unavailable."
        result["failed"] = [
            {
                "ok": False,
                "name": file_path.name,
                "path": str(file_path),
                "file_id": "",
                "action": "failed",
                "attempts": 0,
                "error": result["warning"],
                "error_code": "",
                "http_status": 0,
            }
            for file_path in local_files
        ]
        result["failed_count"] = len(result["failed"])
        return result

    try:
        current_parent_folder_id = str(parent_folder_id)
        for part in normalized_parts:
            current_parent_folder_id = _ensure_drive_child_folder(
                service=service,
                parent_folder_id=current_parent_folder_id,
                folder_name=part,
            )
        child_folder_id = current_parent_folder_id
    except Exception as exc:
        details = _drive_error_details(exc)
        result["error"] = details["message"]
        result["warning"] = (
            "Files could not be saved to Google Drive. "
            f"The destination folder could not be prepared. Error: {details['message']}"
        )
        result["failed"] = [
            {
                "ok": False,
                "name": file_path.name,
                "path": str(file_path),
                "file_id": "",
                "action": "failed",
                "attempts": 0,
                "error": details["message"],
                "error_code": details["code"],
                "http_status": details["http_status"],
            }
            for file_path in local_files
        ]
        result["failed_count"] = len(result["failed"])
        return result

    result["folder_id"] = child_folder_id
    result["drive_url"] = f"https://drive.google.com/drive/folders/{child_folder_id}"

    for file_path in local_files:
        upload_row = _upload_single_file_to_drive(
            service=service,
            parent_folder_id=child_folder_id,
            file_path=file_path,
        )
        if bool(upload_row.get("ok", False)):
            result["uploaded"].append(upload_row)
        else:
            result["failed"].append(upload_row)

    result["uploaded_count"] = len(result["uploaded"])
    result["failed_count"] = len(result["failed"])
    result["ok"] = bool(child_folder_id) and result["failed_count"] == 0
    if result["failed_count"] > 0:
        result["error"] = str(result["failed"][0].get("error", "") or "Drive upload failed.")
        result["warning"] = (
            "Files could not be saved to Google Drive. "
            f"The folder was created but {result['failed_count']} file(s) failed to upload. "
            f"Error: {result['error']}"
        )
    return result


def _save_raw_context_for_job(
    *,
    runtime: config.Config,
    job: job_store.JobRecord,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    book = _book_row_for_number(runtime=runtime, book_number=int(job.book_number or 0))
    if not isinstance(book, dict):
        raise LookupError("book not found for job")

    selected_row = _row_for_save_raw(job=job, expected=expected)
    title = _display_filename_token(str(book.get("title", f"Book {int(job.book_number or 0)}")))
    author = _display_filename_token(str(book.get("author", "Unknown")))
    catalog_number = str(
        book.get("catalog_number")
        or book.get("number")
        or job.book_number
        or "0"
    ).strip()
    book_folder_name = f"{catalog_number}. {title} - {author}"
    display_variant = _save_raw_display_variant(expected=expected, row=selected_row)
    style_label = _save_raw_style_label(expected=expected, job=job, row=selected_row)
    file_prefix = _save_raw_filename_prefix(
        title=str(book.get("title", f"Book {int(job.book_number or 0)}")),
        variant=display_variant,
        style_label=style_label,
    )
    package_folder_name = _save_raw_package_folder_name(
        job=job,
        row=selected_row,
        display_variant=display_variant,
    )
    raw_source = _resolve_durable_raw_image_path(runtime=runtime, row=selected_row)
    comp_source = _resolve_durable_composite_image_path(runtime=runtime, row=selected_row)
    if raw_source is None and comp_source is None:
        raise SaveRawIntegrityError(
            "Save Raw refused because this result does not have immutable job-scoped artifacts. Regenerate the result before saving.",
            code="SAVE_RAW_IMMUTABLE_ARTIFACTS_REQUIRED",
            details={
                "job_id": str(job.id or "").strip(),
                "variant": _row_variant_number(selected_row),
                "model": str(selected_row.get("model", "") or "").strip(),
                "raw_art_path": str(selected_row.get("raw_art_path", "") or "").strip(),
                "saved_composited_path": str(selected_row.get("saved_composited_path", "") or "").strip(),
            },
        )
    return {
        "job_id": str(job.id or "").strip(),
        "book_number": int(job.book_number or 0),
        "book_folder_name": book_folder_name,
        "package_folder_name": package_folder_name,
        "folder_name": package_folder_name,
        "local_folder": _local_save_raw_root(runtime=runtime) / book_folder_name / package_folder_name,
        "raw_source": raw_source,
        "raw_file_name": f"{file_prefix}_raw.png",
        "comp_source": comp_source,
        "comp_file_name": f"{file_prefix}_composite.png",
        "variant": display_variant,
        "model": str(selected_row.get("model", "") or "").strip(),
        "style_label": style_label,
        "selected_row": selected_row,
    }


def _materialize_save_raw_package(
    *,
    runtime: config.Config,
    job: job_store.JobRecord,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _save_raw_context_for_job(runtime=runtime, job=job, expected=expected)
    local_folder = Path(context["local_folder"])
    local_folder.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    missing_files: list[str] = []
    saved_files: list[str] = []

    raw_source = context["raw_source"]
    raw_file_name = str(context["raw_file_name"])
    if isinstance(raw_source, Path) and raw_source.exists():
        saved_path = _export_png_asset(
            source_image=raw_source,
            local_folder=local_folder,
            file_name=raw_file_name,
        )
        if saved_path:
            saved_files.append(saved_path)
    else:
        missing_files.append(raw_file_name)
        warnings.append("Generated raw image not found.")

    comp_source = context["comp_source"]
    comp_file_name = str(context["comp_file_name"])
    if isinstance(comp_source, Path) and comp_source.exists():
        saved_path = _export_png_asset(
            source_image=comp_source,
            local_folder=local_folder,
            file_name=comp_file_name,
        )
        if saved_path:
            saved_files.append(saved_path)
    else:
        missing_files.append(comp_file_name)
        warnings.append("Composite image not found.")

    if not saved_files:
        raise FileNotFoundError("No raw or composite image found for job")

    return {
        "job_id": context["job_id"],
        "book_number": context["book_number"],
        "book_folder_name": context["book_folder_name"],
        "package_folder_name": context["package_folder_name"],
        "folder_name": context["folder_name"],
        "local_folder": str(local_folder),
        "saved_files": saved_files,
        "missing_files": missing_files,
        "warning": " ".join(warnings).strip() or None,
        "variant": context["variant"],
        "model": context["model"],
        "style_label": context["style_label"],
        "raw_file_name": raw_file_name,
        "composite_file_name": comp_file_name,
    }


def _save_raw_payload_for_job(
    *,
    runtime: config.Config,
    job: job_store.JobRecord,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_payload = _materialize_save_raw_package(runtime=runtime, job=job, expected=expected)
    drive_payload = _upload_folder_to_drive(
        runtime=runtime,
        local_folder=Path(local_payload["local_folder"]),
        folder_parts=[
            str(local_payload.get("book_folder_name", "") or "").strip(),
            str(local_payload.get("package_folder_name", "") or "").strip(),
        ],
        parent_folder_id=SAVE_RAW_DRIVE_FOLDER_ID,
    )
    warnings = [
        token
        for token in [
            str(local_payload.get("warning", "") or "").strip(),
            str(drive_payload.get("warning", "") or "").strip(),
        ]
        if token
    ]
    saved_status = "saved" if bool(drive_payload.get("ok", False)) else "partial"
    return {
        "ok": True,
        "job_id": local_payload["job_id"],
        "book_number": local_payload["book_number"],
        "book_folder_name": local_payload["book_folder_name"],
        "package_folder_name": local_payload["package_folder_name"],
        "folder_name": local_payload["folder_name"],
        "local_folder": local_payload["local_folder"],
        "saved_files": local_payload["saved_files"],
        "missing_files": local_payload["missing_files"],
        "variant": local_payload["variant"],
        "model": local_payload["model"],
        "style_label": local_payload["style_label"],
        "raw_file_name": local_payload["raw_file_name"],
        "composite_file_name": local_payload["composite_file_name"],
        "status": saved_status,
        "drive_ok": bool(drive_payload.get("ok", False)),
        "drive_url": drive_payload.get("drive_url"),
        "drive_folder_id": str(drive_payload.get("folder_id", "") or ""),
        "drive_uploaded": drive_payload.get("uploaded", []),
        "drive_failed": drive_payload.get("failed", []),
        "drive_warning": drive_payload.get("warning"),
        "retry_available": not bool(drive_payload.get("ok", False)),
        "warning": " ".join(warnings).strip() or None,
        "drive": drive_payload,
    }


def _local_save_result_root(*, runtime: config.Config) -> Path:
    return _local_save_raw_root(runtime=runtime) / "_iterate_results"


def _safe_filename_component(text: str) -> str:
    token = _display_filename_token(text, allow_en_dash=False)
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", token).strip("._")
    return token or "Untitled"


def _save_result_filename(*, title: str, variant: int, style_label: str, stamp: datetime | None = None) -> str:
    current = stamp or datetime.now(timezone.utc)
    date_token = current.strftime("%Y%m%d-%H%M%S")
    title_token = _safe_filename_component(title)
    style_token = _safe_filename_component(style_label or "Saved Cover")
    return f"{title_token}_V{max(1, int(variant))}_{style_token}_{date_token}.png"


def _save_result_context_for_job(
    *,
    runtime: config.Config,
    job: job_store.JobRecord,
    expected: dict[str, Any] | None = None,
    style_label: str = "",
) -> dict[str, Any]:
    book = _book_row_for_number(runtime=runtime, book_number=int(job.book_number or 0))
    if not isinstance(book, dict):
        raise LookupError("book not found for job")

    selected_row = _row_for_save_raw(job=job, expected=expected)
    composite_source = _resolve_durable_composite_image_path(runtime=runtime, row=selected_row)
    if composite_source is None or not composite_source.exists():
        raise FileNotFoundError("No composite image found for job")

    variant = _row_variant_number(selected_row)
    title_display = _display_filename_token(str(book.get("title", f"Book {int(job.book_number or 0)}")))
    author_display = _display_filename_token(str(book.get("author", "Unknown")))
    catalog_number = str(
        book.get("catalog_number")
        or book.get("number")
        or job.book_number
        or "0"
    ).strip()
    book_folder_name = f"{catalog_number}. {title_display} - {author_display}"
    resolved_style_label = str(
        style_label
        or (job.payload.get("style_label") if isinstance(job.payload, dict) else "")
        or selected_row.get("style_label")
        or selected_row.get("prompt_name")
        or "Saved Cover"
    ).strip()
    file_name = _save_result_filename(
        title=str(book.get("title", f"Book {int(job.book_number or 0)}")),
        variant=variant,
        style_label=resolved_style_label,
    )
    local_folder = _local_save_result_root(runtime=runtime) / book_folder_name
    return {
        "job_id": str(job.id or "").strip(),
        "book_number": int(job.book_number or 0),
        "book_folder_name": book_folder_name,
        "local_folder": local_folder,
        "local_path": local_folder / file_name,
        "file_name": file_name,
        "variant": variant,
        "model": str(selected_row.get("model", "") or "").strip(),
        "style_label": resolved_style_label,
        "composite_source": composite_source,
    }


def _materialize_saved_result_file(
    *,
    runtime: config.Config,
    job: job_store.JobRecord,
    expected: dict[str, Any] | None = None,
    style_label: str = "",
) -> dict[str, Any]:
    context = _save_result_context_for_job(
        runtime=runtime,
        job=job,
        expected=expected,
        style_label=style_label,
    )
    local_folder = Path(context["local_folder"])
    local_path = Path(context["local_path"])
    local_folder.mkdir(parents=True, exist_ok=True)
    _copy_image_with_format(
        Path(context["composite_source"]),
        local_path,
        format_name="PNG",
    )
    return {
        "job_id": context["job_id"],
        "book_number": context["book_number"],
        "book_folder_name": context["book_folder_name"],
        "local_folder": str(local_folder),
        "local_path": str(local_path),
        "file_name": context["file_name"],
        "variant": context["variant"],
        "model": context["model"],
        "style_label": context["style_label"],
    }


def _upload_saved_result_to_drive(
    *,
    runtime: config.Config,
    local_path: Path,
    parent_folder_id: str,
) -> dict[str, Any]:
    service, credentials_path, mode, credentials_meta, connection_error = _drive_service_for_runtime(runtime)
    payload: dict[str, Any] = {
        "ok": False,
        "mode": mode,
        "parent_folder_id": str(parent_folder_id),
        "drive_url": None,
        "drive_file_id": "",
        "upload": None,
        "warning": None,
        "error": connection_error,
        "credentials_path": str(credentials_path),
        "credentials": credentials_meta,
    }
    if service is None:
        payload["warning"] = connection_error or "Google Drive is unavailable."
        return payload

    upload_row = _upload_single_file_to_drive(
        service=service,
        parent_folder_id=parent_folder_id,
        file_path=local_path,
    )
    payload["upload"] = upload_row
    payload["ok"] = bool(upload_row.get("ok", False))
    payload["drive_file_id"] = str(upload_row.get("file_id", "") or "").strip()
    payload["drive_url"] = str(upload_row.get("drive_url", "") or "").strip() or None
    if not payload["ok"]:
        payload["error"] = str(upload_row.get("error", "") or connection_error or "Drive upload failed.")
        payload["warning"] = (
            "The cover was saved locally but could not be uploaded to Google Drive. "
            f"Error: {payload['error']}"
        )
    return payload


def _save_result_payload_for_job(
    *,
    runtime: config.Config,
    job: job_store.JobRecord,
    expected: dict[str, Any] | None = None,
    style_label: str = "",
) -> dict[str, Any]:
    local_payload = _materialize_saved_result_file(
        runtime=runtime,
        job=job,
        expected=expected,
        style_label=style_label,
    )
    drive_payload = _upload_saved_result_to_drive(
        runtime=runtime,
        local_path=Path(local_payload["local_path"]),
        parent_folder_id=SAVE_RESULT_DRIVE_FOLDER_ID,
    )
    warnings = [
        token
        for token in [
            str(drive_payload.get("warning", "") or "").strip(),
        ]
        if token
    ]
    return {
        "ok": True,
        "job_id": local_payload["job_id"],
        "book_number": local_payload["book_number"],
        "book_folder_name": local_payload["book_folder_name"],
        "local_folder": local_payload["local_folder"],
        "local_path": local_payload["local_path"],
        "file_name": local_payload["file_name"],
        "variant": local_payload["variant"],
        "model": local_payload["model"],
        "style_label": local_payload["style_label"],
        "status": "saved" if bool(drive_payload.get("ok", False)) else "partial",
        "drive_ok": bool(drive_payload.get("ok", False)),
        "drive_url": drive_payload.get("drive_url"),
        "drive_file_id": str(drive_payload.get("drive_file_id", "") or ""),
        "drive_warning": drive_payload.get("warning"),
        "retry_available": not bool(drive_payload.get("ok", False)),
        "warning": " ".join(warnings).strip() or None,
        "drive": drive_payload,
    }


def _ensure_drive_child_folder(*, service: Any, parent_folder_id: str, folder_name: str) -> str:
    folder_name_query = str(folder_name).replace("'", "\\'")
    query = (
        f"name='{folder_name_query}' and "
        f"'{str(parent_folder_id)}' in parents and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    existing = service.files().list(
        q=query,
        fields="files(id, name)",
        pageSize=1,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute().get("files", [])
    if existing:
        folder_id = str(existing[0].get("id", "")).strip()
        if folder_id:
            return folder_id

    created = service.files().create(
        body={
            "name": str(folder_name),
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [str(parent_folder_id)],
        },
        fields="id",
        supportsAllDrives=True,
    ).execute()
    folder_id = str(created.get("id", "")).strip()
    if not folder_id:
        raise RuntimeError("Google Drive folder creation did not return an id")
    return folder_id


def _upload_saved_prompt_metadata_to_drive(
    *,
    runtime: config.Config,
    prompt_payload: dict[str, Any],
    prompt_id: str,
    parent_folder_id: str = SAVE_RAW_DRIVE_FOLDER_ID,
) -> str:
    drive_mode, drive_error = _drive_credentials_mode(runtime)
    if not drive_mode:
        raise RuntimeError(drive_error or "Google Drive credentials are not configured.")

    credentials_path = _resolve_credentials_path(runtime)
    if not credentials_path.is_absolute():
        credentials_path = PROJECT_ROOT / credentials_path
    service = gdrive_sync.authenticate(credentials_path if credentials_path.exists() else None)
    child_folder_id = _ensure_drive_child_folder(
        service=service,
        parent_folder_id=parent_folder_id,
        folder_name=SAVE_PROMPT_DRIVE_SUBDIR,
    )

    file_name = f"winner_prompt_{_prompt_slug_token(prompt_id, fallback='winner-prompt')}.json"
    temp_path = Path(tempfile.mkstemp(prefix="winner-prompt-", suffix=".json")[1])
    try:
        temp_path.write_text(json.dumps(prompt_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        file_name_query = file_name.replace("'", "\\'")
        query = (
            f"name='{file_name_query}' and "
            f"'{str(child_folder_id)}' in parents and trashed=false"
        )
        existing = service.files().list(
            q=query,
            fields="files(id, name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute().get("files", [])
        media = gdrive_sync.MediaFileUpload(str(temp_path), mimetype="application/json")
        if existing:
            file_id = str(existing[0].get("id", "")).strip()
            if not file_id:
                raise RuntimeError("Google Drive file update target is missing an id")
            service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        else:
            created = service.files().create(
                body={"name": file_name, "parents": [child_folder_id]},
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            file_id = str(created.get("id", "")).strip()
            if not file_id:
                raise RuntimeError("Google Drive file creation did not return an id")
        return f"https://drive.google.com/file/d/{file_id}/view"
    finally:
        temp_path.unlink(missing_ok=True)


def _build_book_download_zip(*, runtime: config.Config, book_number: int) -> tuple[Path, str]:
    rows = _latest_rows_for_book(runtime=runtime, book_number=book_number)
    if not rows:
        raise FileNotFoundError(f"No generated variants found for book {book_number}")
    title, edition = _book_title_and_edition(runtime=runtime, book_number=book_number)
    book_dir = f"Book{int(book_number):03d}_{_safe_file_stem(title)}"
    manifest_lines = ["book_number,title,edition,model,variant,composite_file,source_file,quality_score"]

    downloads_dir = runtime.tmp_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="book-", suffix=".zip", dir=str(downloads_dir), delete=False) as handle:
        zip_path = Path(handle.name)

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            model_name = str(row.get("model", "unknown"))
            variant = _safe_int(row.get("variant", row.get("variant_id", 0)), 0)
            if variant <= 0:
                continue
            composite = _project_path_if_exists(row.get("composited_path"))
            if composite is None:
                image_source = _project_path_if_exists(row.get("image_path"))
                if image_source is not None:
                    candidate = _resolve_composited_candidate(image_source, runtime=runtime)
                    if candidate is not None and candidate.exists():
                        composite = candidate
            source = _source_image_for_variant(
                runtime=runtime,
                book_number=book_number,
                variant=variant,
                model=model_name,
                record=row,
            )
            composite_name = _descriptive_download_filename(
                book_number=book_number,
                title=title,
                edition=edition,
                model=model_name,
                variant=variant,
                ext="jpg",
                source=False,
            )
            source_name = _descriptive_download_filename(
                book_number=book_number,
                title=title,
                edition=edition,
                model=model_name,
                variant=variant,
                ext="png",
                source=True,
            )
            composite_arc = f"{book_dir}/composites/{composite_name}"
            source_arc = f"{book_dir}/source_images/{source_name}"
            if composite is not None and composite.exists():
                archive.write(composite, arcname=composite_arc)
            if source is not None and source.exists():
                archive.write(source, arcname=source_arc)
            manifest_lines.append(
                f"{int(book_number)},\"{title}\",\"{edition}\",\"{model_name}\",{int(variant)},\"{composite_arc}\",\"{source_arc}\",{_safe_float(row.get('quality_score'), 0.0):.4f}"
            )
        archive.writestr("manifest.csv", "\n".join(manifest_lines) + "\n")

    return zip_path, f"{book_dir}_all_variants.zip"


def _build_approved_download_zip(*, runtime: config.Config) -> tuple[Path, str]:
    winners_payload = _load_winner_payload(_winner_path_for_runtime(runtime))
    selections = winners_payload.get("selections", {}) if isinstance(winners_payload, dict) else {}
    if not isinstance(selections, dict) or not selections:
        raise FileNotFoundError("No approved winners available for download")
    downloads_dir = runtime.tmp_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="approved-", suffix=".zip", dir=str(downloads_dir), delete=False) as handle:
        zip_path = Path(handle.name)
    manifest_lines = ["book_number,title,edition,model,variant,composite_file,source_file,quality_score"]

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for key, selection in sorted(selections.items(), key=lambda item: _safe_int(item[0], 0)):
            book_number = _safe_int(key, 0)
            if book_number <= 0:
                continue
            if isinstance(selection, dict):
                winner_variant = _safe_int(selection.get("winner"), 0)
                score = _safe_float(selection.get("score"), 0.0)
            else:
                winner_variant = _safe_int(selection, 0)
                score = 0.0
            if winner_variant <= 0:
                continue
            record = _latest_variant_record(runtime=runtime, book_number=book_number, variant=winner_variant)
            model_name = str((record or {}).get("model", "unknown"))
            title, edition = _book_title_and_edition(runtime=runtime, book_number=book_number)
            book_dir = f"Book{int(book_number):03d}_{_safe_file_stem(title)}"
            composite = None
            variant_dir = _variant_output_dir(runtime=runtime, book_number=book_number, variant=winner_variant)
            if variant_dir is not None:
                composite = next(iter(sorted(variant_dir.glob("*.jpg"))), None)
            if composite is None and isinstance(record, dict):
                composite = _project_path_if_exists(record.get("composited_path"))
            source = _source_image_for_variant(
                runtime=runtime,
                book_number=book_number,
                variant=winner_variant,
                model=model_name,
                record=record,
            )
            composite_name = _descriptive_download_filename(
                book_number=book_number,
                title=title,
                edition=edition,
                model=model_name,
                variant=winner_variant,
                ext="jpg",
                source=False,
            )
            source_name = _descriptive_download_filename(
                book_number=book_number,
                title=title,
                edition=edition,
                model=model_name,
                variant=winner_variant,
                ext="png",
                source=True,
            )
            composite_arc = f"{book_dir}/composites/{composite_name}"
            source_arc = f"{book_dir}/source_images/{source_name}"
            if composite is not None and composite.exists():
                archive.write(composite, arcname=composite_arc)
            if source is not None and source.exists():
                archive.write(source, arcname=source_arc)
            manifest_lines.append(
                f"{int(book_number)},\"{title}\",\"{edition}\",\"{model_name}\",{int(winner_variant)},\"{composite_arc}\",\"{source_arc}\",{_safe_float((record or {}).get('quality_score'), score):.4f}"
            )
        archive.writestr("manifest.csv", "\n".join(manifest_lines) + "\n")

    return zip_path, f"approved_covers_{_safe_file_stem(runtime.catalog_id)}.zip"


def _load_generation_records(*, runtime: config.Config | None = None) -> list[dict[str, Any]]:
    runtime = runtime or config.get_config()
    title_by_book, _ = _catalog_maps(catalog_path=runtime.book_catalog_path)
    quality_path = _quality_scores_path_for_runtime(runtime)
    quality_lookup = _load_quality_lookup(quality_path)
    quality_payload = _load_json(quality_path, {"scores": []})
    quality_rows = quality_payload.get("scores", []) if isinstance(quality_payload, dict) else []
    history_rows: list[dict[str, Any]] = []
    try:
        history_rows = state_db_store.list_generation_records(catalog_id=runtime.catalog_id, limit=5000)
    except Exception as exc:  # pragma: no cover - fallback to JSON
        logger.warning("State DB history read failed for catalog %s: %s", runtime.catalog_id, exc)
    if not history_rows:
        history_payload = _load_json(_history_path_for_runtime(runtime), {"items": []})
        rows = history_payload.get("items", []) if isinstance(history_payload, dict) else []
        history_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    records: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, int, str, str]] = set()

    for row in history_rows:
        if not isinstance(row, dict):
            continue
        book = _safe_int(row.get("book_number"), 0)
        variant = _safe_int(row.get("variant"), _safe_int(row.get("variant_id"), 0))
        model = str(row.get("model", "unknown"))
        model_norm = _normalize_model_name(model)
        provider = str(row.get("provider", "")).strip() or runtime.resolve_model_provider(model_norm)
        quality = _safe_float(row.get("quality_score"), quality_lookup.get((book, variant), 0.0))
        cost = _safe_float(row.get("cost"), runtime.get_model_cost(model_norm))
        timestamp = str(row.get("timestamp", "")) or datetime.now(timezone.utc).isoformat()
        key = (book, variant, model, timestamp)
        seen_keys.add(key)
        records.append(
            {
                "timestamp": timestamp,
                "book_number": book,
                "book_title": title_by_book.get(book, f"Book {book}"),
                "model": model,
                "provider": provider,
                "variant": variant,
                "quality_score": quality,
                "cost": round(cost, 4),
                "status": "success" if bool(row.get("success", True)) else "fail",
                "duration": _safe_float(row.get("generation_time"), 0.0),
                "prompt": str(row.get("prompt", "")),
                "image_path": row.get("image_path"),
                "composited_path": row.get("composited_path"),
                "distinctiveness_score": _safe_float(row.get("distinctiveness_score"), 0.0),
                "similar_to_book": _safe_int(row.get("similar_to_book"), 0),
                "similarity_warning": str(row.get("similarity_warning", "")),
                "error": row.get("error"),
                "print_validation": row.get("print_validation", {}) if isinstance(row.get("print_validation"), dict) else {},
            }
        )

    quality_mtime = (
        datetime.fromtimestamp(quality_path.stat().st_mtime, tz=timezone.utc).isoformat()
        if quality_path.exists()
        else datetime.now(timezone.utc).isoformat()
    )
    for row in quality_rows:
        if not isinstance(row, dict):
            continue
        book = _safe_int(row.get("book_number"), 0)
        variant = _safe_int(row.get("variant_id"), 0)
        model = str(row.get("model", "unknown"))
        key = (book, variant, model, quality_mtime)
        if key in seen_keys:
            continue
        model_norm = _normalize_model_name(model)
        provider = runtime.resolve_model_provider(model_norm)
        records.append(
            {
                "timestamp": quality_mtime,
                "book_number": book,
                "book_title": title_by_book.get(book, f"Book {book}"),
                "model": model,
                "provider": provider,
                "variant": variant,
                "quality_score": _safe_float(row.get("overall_score"), 0.0),
                "cost": round(runtime.get_model_cost(model_norm), 4),
                "status": "success",
                "duration": 0.0,
                "prompt": "",
                "image_path": row.get("image_path"),
                "composited_path": None,
                "distinctiveness_score": _safe_float(row.get("distinctiveness_score"), 0.0),
                "similar_to_book": 0,
                "similarity_warning": "",
                "error": None,
                "print_validation": {},
            }
        )

    records.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return records


def _filter_generation_records(items: list[dict[str, Any]], *, filters: dict[str, list[str]]) -> list[dict[str, Any]]:
    selected = items

    def _first(name: str) -> str:
        return (filters.get(name, [""])[0] or "").strip()

    book_filter = _first("book")
    model_filter = _first("model").lower()
    provider_filter = _first("provider").lower()
    status_filter = _first("status").lower()
    date_from = _safe_iso_datetime(_first("date_from"))
    date_to = _safe_iso_datetime(_first("date_to"))
    quality_min = _safe_float(_first("quality_min"), float("-inf"))
    quality_max = _safe_float(_first("quality_max"), float("inf"))

    if book_filter:
        wanted = _parse_books(book_filter) or []
        selected = [row for row in selected if _safe_int(row.get("book_number"), 0) in set(wanted)]
    if model_filter:
        selected = [row for row in selected if model_filter in str(row.get("model", "")).lower()]
    if provider_filter:
        selected = [row for row in selected if provider_filter == str(row.get("provider", "")).lower()]
    if status_filter and status_filter != "all":
        selected = [row for row in selected if status_filter == str(row.get("status", "")).lower()]

    filtered_by_date: list[dict[str, Any]] = []
    for row in selected:
        item_dt = _safe_iso_datetime(str(row.get("timestamp", "")))
        if date_from and item_dt and item_dt < date_from:
            continue
        if date_to and item_dt and item_dt > date_to:
            continue
        q = _safe_float(row.get("quality_score"), 0.0)
        if q < quality_min or q > quality_max:
            continue
        filtered_by_date.append(row)

    return filtered_by_date


def _build_weak_books_payload(*, runtime: config.Config, threshold: float) -> dict[str, Any]:
    winner_path = _winner_path_for_runtime(runtime)
    winner_payload = _load_winner_payload(winner_path)
    selections = winner_payload.get("selections", {}) if isinstance(winner_payload, dict) else {}
    if not isinstance(selections, dict):
        selections = {}

    quality_lookup = _load_quality_lookup(_quality_scores_path_for_runtime(runtime))
    title_by_book, folder_by_book = _catalog_maps(catalog_path=runtime.book_catalog_path)

    rows: list[dict[str, Any]] = []
    for key, value in selections.items():
        book = _safe_int(key, 0)
        if book <= 0:
            continue

        winner_variant = 0
        score = 0.0
        confirmed = False
        if isinstance(value, dict):
            winner_variant = _safe_int(value.get("winner"), 0)
            score = _safe_float(value.get("score"), 0.0)
            confirmed = bool(value.get("confirmed", False))
        else:
            winner_variant = _safe_int(value, 0)

        if winner_variant > 0 and score <= 0:
            score = quality_lookup.get((book, winner_variant), 0.0)

        if score >= threshold:
            continue

        image_rel = None
        folder = folder_by_book.get(book, "")
        if folder:
            variant_dir = runtime.output_dir / folder / f"Variant-{winner_variant}"
            jpg = sorted(variant_dir.glob("*.jpg")) if variant_dir.exists() else []
            if jpg:
                image_rel = _to_project_relative(jpg[0])

        rows.append(
            {
                "book": book,
                "title": title_by_book.get(book, f"Book {book}"),
                "winner_variant": winner_variant,
                "winner_score": round(score, 4),
                "confirmed": confirmed,
                "image": image_rel,
            }
        )

    rows.sort(key=lambda row: row["winner_score"])
    return {
        "catalog": runtime.catalog_id,
        "threshold": threshold,
        "count": len(rows),
        "books": rows,
    }


def _confidence_for_book(book: dict[str, Any], winner_score: float) -> float:
    scores = []
    for row in book.get("variants", []):
        if not isinstance(row, dict):
            continue
        scores.append(_safe_float(row.get("quality_score"), 0.0))
    scores = sorted([value for value in scores if value >= 0], reverse=True)
    if not scores:
        return 0.0
    top = scores[0]
    second = scores[1] if len(scores) > 1 else 0.0
    if top <= 0:
        return 0.0
    confidence = (top - second) / top
    if winner_score > 0 and winner_score < top:
        confidence *= 0.85
    return max(0.0, min(1.0, confidence))


def _build_review_queue(*, runtime: config.Config, threshold: float) -> dict[str, Any]:
    books = build_review_dataset(
        runtime.output_dir,
        input_dir=runtime.input_dir,
        catalog_path=runtime.book_catalog_path,
        quality_scores_path=_quality_scores_path_for_runtime(runtime),
    )
    winner_payload = _ensure_winner_payload(books, path=_winner_path_for_runtime(runtime))
    selections = winner_payload.get("selections", {}) if isinstance(winner_payload, dict) else {}
    if not isinstance(selections, dict):
        selections = {}

    similarity = _load_similarity_matrix(runtime_req=runtime, threshold=0.25)
    flagged_books: set[int] = set()
    for row in similarity.get("pairs", []):
        if not isinstance(row, dict):
            continue
        if _safe_float(row.get("similarity"), 1.0) >= 0.25:
            continue
        a = _safe_int(row.get("book_a"), 0)
        b = _safe_int(row.get("book_b"), 0)
        if a > 0:
            flagged_books.add(a)
        if b > 0:
            flagged_books.add(b)

    queue: list[dict[str, Any]] = []
    auto_approve = 0
    needs_review = 0
    needs_attention = 0
    conflicts_pending = 0

    for book in books:
        number = _safe_int(book.get("number"), 0)
        if number <= 0:
            continue
        selection = selections.get(str(number), {}) if isinstance(selections.get(str(number), {}), dict) else {}
        winner = _safe_int(selection.get("winner"), 0)
        winner_score = _safe_float(selection.get("score"), 0.0)
        confidence = _confidence_for_book(book, winner_score)
        flagged_similarity = number in flagged_books
        conflict_payload = selection.get("conflict", {}) if isinstance(selection.get("conflict"), dict) else {}
        conflict_required = bool(selection.get("conflict_requires_resolution", False)) or bool(
            conflict_payload.get("requires_resolution", False)
        )
        if conflict_required:
            conflicts_pending += 1
        top_variant_score = max(
            [
                _safe_float(variant.get("quality_score"), 0.0)
                for variant in book.get("variants", [])
                if isinstance(variant, dict)
            ],
            default=0.0,
        )

        if winner_score >= threshold:
            auto_approve += 1
        if winner_score < 0.70:
            needs_attention += 1
        elif winner_score < threshold:
            needs_review += 1

        if confidence < 0.05:
            priority = 0
        elif conflict_required:
            priority = 1
        elif flagged_similarity:
            priority = 2
        elif winner_score < 0.75:
            priority = 3
        elif top_variant_score >= 0.90:
            priority = 5
        else:
            priority = 4

        queue.append(
            {
                "book": number,
                "title": str(book.get("title", "")),
                "author": str(book.get("author", "")),
                "winner": winner,
                "winner_score": round(winner_score, 4),
                "top_variant_score": round(top_variant_score, 4),
                "confidence": round(confidence, 4),
                "similarity_flag": flagged_similarity,
                "selected_by": str(selection.get("selected_by", selection.get("reviewer", ""))),
                "reviewer": str(selection.get("reviewer", "")),
                "conflict_requires_resolution": conflict_required,
                "conflict": conflict_payload,
                "priority": priority,
                "variants": book.get("variants", []),
                "original": book.get("original", ""),
                "confirmed": bool(selection.get("confirmed", False)),
            }
        )

    queue.sort(key=lambda row: (row["priority"], row["confidence"], row["winner_score"], row["book"]))
    remaining_after_auto = max(0, len(queue) - auto_approve)
    estimated_minutes = int(math.ceil((remaining_after_auto * 18) / 60.0))

    return {
        "catalog": runtime.catalog_id,
        "threshold": threshold,
        "total_books": len(queue),
        "auto_approve": auto_approve,
        "needs_review": needs_review,
        "needs_attention": needs_attention,
        "similarity_alert_books": len(flagged_books),
        "conflict_alert_books": conflicts_pending,
        "estimated_review_minutes": estimated_minutes,
        "queue": queue,
    }


def _apply_batch_approve(*, runtime: config.Config, threshold: float, reviewer: str) -> dict[str, Any]:
    books = build_review_dataset(
        runtime.output_dir,
        input_dir=runtime.input_dir,
        catalog_path=runtime.book_catalog_path,
        quality_scores_path=_quality_scores_path_for_runtime(runtime),
    )
    winner_path = _winner_path_for_runtime(runtime)
    payload = _ensure_winner_payload(books, path=winner_path)
    selections = payload.get("selections", {}) if isinstance(payload, dict) else {}
    if not isinstance(selections, dict):
        selections = {}

    approved = 0
    for book in books:
        key = str(_safe_int(book.get("number"), 0))
        if key not in selections:
            continue
        row = selections.get(key, {})
        if not isinstance(row, dict):
            continue
        score = _safe_float(row.get("score"), 0.0)
        if score < threshold:
            continue
        row["confirmed"] = True
        row["auto_selected"] = True
        row["selected_by"] = reviewer
        row["selection_date"] = datetime.now(timezone.utc).isoformat()
        row["review_mode"] = "speed_batch"
        selections[key] = row
        approved += 1

    _save_winner_payload(winner_path, selections, total_books=len(books))
    return {
        "approved_books": approved,
        "threshold": threshold,
        "reviewer": reviewer,
        "total_books": len(books),
    }


def _append_review_stats(*, runtime: config.Config, payload: dict[str, Any]) -> None:
    review_stats_path = _review_stats_path_for_runtime(runtime)
    current = _load_json(review_stats_path, {"sessions": []})
    if not isinstance(current, dict):
        current = {"sessions": []}
    sessions = current.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []

    selections = payload.get("selections", {})
    if not isinstance(selections, dict):
        selections = {}
    details = payload.get("selection_details", {})
    if not isinstance(details, dict):
        details = {}

    variant_distribution: dict[str, int] = {}
    overrides = 0
    lower_score_picks = 0
    for key, row in selections.items():
        detail = details.get(str(key), {}) if isinstance(details.get(str(key), {}), dict) else {}
        if isinstance(row, dict):
            variant_value = _safe_int(row.get("winner"), 0)
            overrode = bool(detail.get("overrode_auto", row.get("overrode_auto")))
            score_value = _safe_float(detail.get("score", row.get("score")), 0.0)
        else:
            variant_value = _safe_int(row, 0)
            overrode = bool(detail.get("overrode_auto", False))
            score_value = _safe_float(detail.get("score"), 0.0)
        if variant_value <= 0:
            continue
        variant = str(variant_value)
        variant_distribution[variant] = variant_distribution.get(variant, 0) + 1
        if overrode:
            overrides += 1
        if score_value > 0 and score_value < 0.7:
            lower_score_picks += 1

    stats_row = {
        "session_id": payload.get("session_id"),
        "catalog": payload.get("catalog"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "books_reviewed": _safe_int(payload.get("books_reviewed"), 0),
        "books_remaining": _safe_int(payload.get("books_remaining"), 0),
        "auto_approved": _safe_int(payload.get("auto_approved"), 0),
        "manually_selected": _safe_int(payload.get("manually_selected"), 0),
        "avg_time_per_book_seconds": _safe_float(payload.get("avg_time_per_book_seconds"), 0.0),
        "auto_overrides": overrides,
        "lower_scoring_variant_picks": lower_score_picks,
        "variant_distribution": variant_distribution,
        "reviewer": payload.get("reviewer", "tim"),
    }
    sessions.append(stats_row)
    current["sessions"] = sessions[-200:]
    review_stats_path.parent.mkdir(parents=True, exist_ok=True)
    safe_json.atomic_write_json(review_stats_path, current)


def _winner_variant_map(*, runtime: config.Config) -> dict[int, int]:
    payload = _load_winner_payload(_winner_path_for_runtime(runtime))
    selections = payload.get("selections", {}) if isinstance(payload, dict) else {}
    if not isinstance(selections, dict):
        selections = {}

    out: dict[int, int] = {}
    for key, value in selections.items():
        book = _safe_int(key, 0)
        if book <= 0:
            continue
        variant = _safe_int(value.get("winner") if isinstance(value, dict) else value, 0)
        if variant <= 0:
            continue
        out[book] = variant
    return out


def _winner_image_map(*, runtime: config.Config) -> dict[int, str]:
    _, folder_by_book = _catalog_maps(catalog_path=runtime.book_catalog_path)
    variant_by_book = _winner_variant_map(runtime=runtime)
    out: dict[int, str] = {}
    for book, variant in variant_by_book.items():
        folder = folder_by_book.get(book)
        if not folder:
            continue
        variant_dir = runtime.output_dir / folder / f"Variant-{variant}"
        image = _find_first_jpg(variant_dir)
        if not image:
            continue
        out[book] = _to_project_relative(image)
    return out


def _similarity_recompute_snapshot(*, catalog_id: str) -> dict[str, Any]:
    with _similarity_recompute_lock:
        row = _similarity_recompute_jobs.get(str(catalog_id), {})
    if not isinstance(row, dict) or not row:
        return {"status": "idle", "catalog": str(catalog_id)}
    return dict(row)


def _start_similarity_recompute(
    *,
    runtime_req: config.Config,
    threshold: float,
    reason: str,
    force: bool = False,
) -> dict[str, Any]:
    catalog_id = str(runtime_req.catalog_id)
    with _similarity_recompute_lock:
        current = _similarity_recompute_jobs.get(catalog_id, {})
        if not force and str(current.get("status", "")).lower() == "running":
            return {"ok": True, "started": False, "job": dict(current)}
        job_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        state = {
            "job_id": job_id,
            "catalog": catalog_id,
            "status": "running",
            "threshold": float(threshold),
            "reason": str(reason or "manual"),
            "started_at": started_at,
            "updated_at": started_at,
        }
        _similarity_recompute_jobs[catalog_id] = state

    def _runner() -> None:
        started_ts = time.time()
        try:
            summary = similarity_detector.run_similarity_analysis(
                output_dir=runtime_req.output_dir,
                threshold=threshold,
                catalog_path=runtime_req.book_catalog_path,
                winner_selections_path=_winner_path_for_runtime(runtime_req),
                regions_path=config.cover_regions_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir),
                hashes_path=_similarity_hashes_path_for_runtime(runtime_req),
                matrix_path=_similarity_matrix_path_for_runtime(runtime_req),
                clusters_path=_similarity_clusters_path_for_runtime(runtime_req),
            )
            status = "completed"
            error_text = ""
        except Exception as exc:  # pragma: no cover - background hardening
            summary = {}
            status = "failed"
            error_text = str(exc)
            logger.error("Similarity recompute failed", extra={"catalog": catalog_id, "error": error_text})
        finished_at = datetime.now(timezone.utc).isoformat()
        with _similarity_recompute_lock:
            existing = _similarity_recompute_jobs.get(catalog_id, {})
            if str(existing.get("job_id", "")) != job_id:
                return
            existing.update(
                {
                    "status": status,
                    "updated_at": finished_at,
                    "finished_at": finished_at,
                    "duration_seconds": round(max(0.0, time.time() - started_ts), 3),
                    "summary": summary if isinstance(summary, dict) else {},
                    "error": error_text,
                }
            )
            _similarity_recompute_jobs[catalog_id] = existing
        _invalidate_cache("/api/similarity-matrix", "/api/similarity-alerts", "/api/similarity-clusters")

    thread = threading.Thread(
        target=_runner,
        name=f"similarity-recompute-{catalog_id}",
        daemon=True,
    )
    thread.start()
    return {"ok": True, "started": True, "job": _similarity_recompute_snapshot(catalog_id=catalog_id)}


def _load_similarity_matrix(*, runtime_req: config.Config, threshold: float) -> dict[str, Any]:
    matrix_path = _similarity_matrix_path_for_runtime(runtime_req)
    payload = _load_json(matrix_path, {})
    if not isinstance(payload, dict):
        payload = {}

    pairs = payload.get("pairs", [])
    if not isinstance(pairs, list):
        pairs = []

    # Cache-first policy: avoid synchronous recompute on hot read paths.
    if not pairs:
        winners_count = len(_winner_image_map(runtime=runtime_req))
        if winners_count > 0 and winners_count <= similarity_detector.EXHAUSTIVE_PAIR_LIMIT:
            # Small catalogs can refresh quickly inline.
            try:
                similarity_detector.run_similarity_analysis(
                    output_dir=runtime_req.output_dir,
                    threshold=threshold,
                    catalog_path=runtime_req.book_catalog_path,
                    winner_selections_path=_winner_path_for_runtime(runtime_req),
                    regions_path=config.cover_regions_path(catalog_id=runtime_req.catalog_id, config_dir=runtime_req.config_dir),
                    hashes_path=_similarity_hashes_path_for_runtime(runtime_req),
                    matrix_path=matrix_path,
                    clusters_path=_similarity_clusters_path_for_runtime(runtime_req),
                )
                payload = _load_json(matrix_path, {})
                if not isinstance(payload, dict):
                    payload = {}
                pairs = payload.get("pairs", [])
                if not isinstance(pairs, list):
                    pairs = []
            except Exception:
                pairs = []
        elif winners_count > 0:
            _start_similarity_recompute(runtime_req=runtime_req, threshold=threshold, reason="cache_miss", force=False)

    normalized_pairs: list[dict[str, Any]] = []
    for row in pairs:
        if not isinstance(row, dict):
            continue
        similarity = _safe_float(row.get("similarity"), 1.0)
        updated = dict(row)
        updated["alert"] = similarity < threshold
        normalized_pairs.append(updated)

    alerts = sum(1 for row in normalized_pairs if bool(row.get("alert", False)))
    output = dict(payload)
    output["pairs"] = normalized_pairs
    output["total_pairs"] = len(normalized_pairs)
    output["alerts"] = alerts
    output["alert_threshold"] = threshold
    output["recompute"] = _similarity_recompute_snapshot(catalog_id=runtime_req.catalog_id)

    titles, _ = _catalog_maps(catalog_path=runtime_req.book_catalog_path)
    images = _winner_image_map(runtime=runtime_req)
    output["books"] = {
        str(book): {
            "book_number": book,
            "title": titles.get(book, f"Book {book}"),
            "image": images.get(book),
        }
        for book in sorted(set(titles.keys()).union(images.keys()))
    }
    return output


def _load_quality_trend_series(*, runtime: config.Config) -> list[dict[str, Any]]:
    payload = _load_json(_quality_scores_path_for_runtime(runtime), {"scores": []})
    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list) or not rows:
        return []

    current_avg = sum(_safe_float(row.get("overall_score"), 0.0) for row in rows if isinstance(row, dict)) / max(1, len(rows))
    series = [
        {
            "label": "Current",
            "average_quality": round(current_avg, 4),
        }
    ]

    by_round: dict[str, list[float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        history = row.get("history")
        if not isinstance(history, list):
            continue
        for event in history:
            if not isinstance(event, dict):
                continue
            label = str(event.get("date") or event.get("action") or "round")
            by_round.setdefault(label, []).append(_safe_float(event.get("best_score"), 0.0))

    for label in sorted(by_round.keys()):
        values = by_round[label]
        if values:
            series.append({"label": label, "average_quality": round(sum(values) / len(values), 4)})

    return series


def _style_tags_from_prompt(prompt: str) -> list[str]:
    text = str(prompt or "").strip().lower()
    if not text:
        return []
    mapping: list[tuple[str, str]] = [
        ("sevastopol", "Sevastopol"),
        ("cossack", "Cossack"),
        ("art nouveau", "Art Nouveau"),
        ("ukiyo", "Ukiyo-e"),
        ("woodblock", "Ukiyo-e"),
        ("noir", "Noir"),
        ("botanical", "Botanical"),
        ("gothic", "Gothic"),
        ("stained glass", "Stained Glass"),
        ("impression", "Impressionist"),
        ("expression", "Expressionist"),
        ("baroque", "Baroque"),
        ("watercolour", "Watercolour"),
        ("watercolor", "Watercolour"),
        ("symbolist", "Symbolist"),
        ("renaissance", "Renaissance"),
        ("realist", "Realist"),
        ("oil painting", "Classical Oil"),
        ("romantic", "Romantic"),
    ]
    out: list[str] = []
    for needle, label in mapping:
        if needle in text and label not in out:
            out.append(label)
    return out[:3]


def _discover_recent_cover_files(*, runtime: config.Config, title_by_book: dict[int, str], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def _append_row(*, path: Path, book: int, variant: int, model: str) -> None:
        if book <= 0 or variant <= 0:
            return
        rows.append(
            {
                "timestamp": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                "book_number": int(book),
                "book_title": title_by_book.get(int(book), f"Book {int(book)}"),
                "model": str(model or "composited"),
                "provider": runtime.resolve_model_provider(str(model or "composited")),
                "variant": int(variant),
                "quality_score": 0.0,
                "cost": round(runtime.get_model_cost(str(model or "")), 4),
                "status": "success",
                "duration": 0.0,
                "prompt": "",
                "image_path": None,
                "composited_path": str(path),
                "distinctiveness_score": 0.0,
                "similar_to_book": 0,
                "similarity_warning": "",
                "error": None,
                "print_validation": {},
            }
        )

    composited_root = runtime.tmp_dir / "composited"
    if composited_root.exists():
        for path in composited_root.rglob("variant_*.jpg"):
            rel = path.relative_to(composited_root)
            parts = list(rel.parts)
            if not parts:
                continue
            book = _safe_int(parts[0], 0)
            variant = _parse_variant(path.stem)
            model = parts[1] if len(parts) >= 3 else "composited"
            _append_row(path=path, book=book, variant=variant, model=model)

    if rows:
        rows.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
        return rows[: max(1, int(limit))]

    output_root = runtime.output_dir
    if output_root.exists():
        for path in output_root.rglob("Variant-*/*.jpg"):
            if len(path.parts) < 3:
                continue
            variant_folder = path.parent.name
            variant = _safe_int(variant_folder.split("-", 1)[1] if "-" in variant_folder else "", 0)
            book_folder = path.parent.parent.name
            book = _safe_int(book_folder.split(".", 1)[0], 0)
            _append_row(path=path, book=book, variant=variant, model="composited")

    rows.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
    return rows[: max(1, int(limit))]


def _dashboard_recent_results(*, items: list[dict[str, Any]], runtime: config.Config, limit: int = 24) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    title_by_book, _folder_map = _catalog_maps(catalog_path=runtime.book_catalog_path)
    max_rows = max(1, int(limit))

    def _timestamp_sort_value(payload: dict[str, Any]) -> float:
        token = str(payload.get("timestamp", "")).strip()
        if not token:
            return float("-inf")
        parsed = _safe_iso_datetime(token)
        if parsed is None:
            return float("-inf")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return float(parsed.timestamp())

    def _append_rows_from_candidates(source_rows: list[dict[str, Any]]) -> None:
        for row in sorted(source_rows, key=_timestamp_sort_value, reverse=True):
            if not isinstance(row, dict):
                continue
            book = _safe_int(row.get("book_number"), 0)
            variant = _safe_int(row.get("variant"), 0)
            model = str(row.get("model", "")).strip()
            if book <= 0 or variant <= 0 or not model:
                continue
            key = (book, variant, model)
            if key in seen:
                continue

            composed_token = str(row.get("composited_path", "") or "").strip()
            image_token = str(row.get("image_path", "") or "").strip()
            candidate = _project_path_if_exists(composed_token)
            if candidate is None and image_token:
                source_path = _project_path_if_exists(image_token)
                if source_path is not None:
                    derived = _resolve_composited_candidate(source_path, runtime=runtime)
                    if derived is not None and derived.exists():
                        candidate = derived
                    elif "/generated/" not in image_token.replace("\\", "/"):
                        # Non-generated artifacts (for example legacy merged assets) may be directly displayable.
                        candidate = source_path
            if candidate is None:
                continue

            seen.add(key)
            rel = _to_project_relative(candidate)
            quality = _safe_float(row.get("quality_score"), 0.0)
            cost = _safe_float(row.get("cost"), runtime.get_model_cost(model))
            prompt = str(row.get("prompt", "")).strip()
            rows.append(
                {
                    "timestamp": str(row.get("timestamp", "")),
                    "book_number": int(book),
                    "book_title": str(row.get("book_title", f"Book {book}")),
                    "variant": int(variant),
                    "model": model,
                    "provider": str(row.get("provider", runtime.resolve_model_provider(model))),
                    "quality_score": round(quality, 4),
                    "cost": round(cost, 6),
                    "prompt": prompt,
                    "style_tags": (
                        [str(tag).strip() for tag in row.get("style_tags", []) if str(tag).strip()]
                        if isinstance(row.get("style_tags"), list)
                        else _style_tags_from_prompt(prompt)
                    ),
                    "image_path": rel,
                    "image_url": f"/{rel}",
                    "thumbnail_url": f"/api/thumbnail?path={quote(rel, safe='')}&size=small",
                }
            )
            if len(rows) >= max_rows:
                return

    candidate_items: list[dict[str, Any]] = [row for row in items if isinstance(row, dict)]
    if not candidate_items:
        try:
            jobs = job_db_store.list_jobs(
                limit=max(50, int(limit) * 8),
                statuses=["completed"],
                catalog_id=runtime.catalog_id,
            )
        except Exception:
            jobs = []
        for job in jobs:
            for job_row in _job_result_rows(job):
                enriched = dict(job_row)
                if not str(enriched.get("timestamp", "")).strip():
                    enriched["timestamp"] = str(job.finished_at or job.updated_at or job.created_at or "")
                book_number = _safe_int(enriched.get("book_number"), 0)
                if book_number > 0 and not str(enriched.get("book_title", "")).strip():
                    enriched["book_title"] = title_by_book.get(book_number, f"Book {book_number}")
                candidate_items.append(enriched)
    _append_rows_from_candidates(candidate_items)
    if not rows:
        discovered = _discover_recent_cover_files(runtime=runtime, title_by_book=title_by_book, limit=max(24, int(limit) * 4))
        _append_rows_from_candidates(discovered)
    return rows[:max_rows]


def _build_dashboard_payload(items: list[dict[str, Any]], *, runtime: config.Config | None = None) -> dict[str, Any]:
    runtime = runtime or config.get_config()
    title_by_book, _ = _catalog_maps(catalog_path=runtime.book_catalog_path)
    books_cataloged = len(title_by_book)

    total_spent = round(sum(_safe_float(row.get("cost"), 0.0) for row in items), 4)
    unique_books = sorted({_safe_int(row.get("book_number"), 0) for row in items if _safe_int(row.get("book_number"), 0) > 0})
    books_generated = len(unique_books)
    avg_cost_per_book = round(total_spent / books_generated, 4) if books_generated else 0.0

    by_book: dict[int, float] = {}
    by_model: dict[str, float] = {}
    scatter: list[dict[str, Any]] = []

    for row in items:
        book = _safe_int(row.get("book_number"), 0)
        model = str(row.get("model", "unknown"))
        cost = _safe_float(row.get("cost"), 0.0)
        quality = _safe_float(row.get("quality_score"), 0.0)
        by_book[book] = by_book.get(book, 0.0) + cost
        by_model[model] = by_model.get(model, 0.0) + cost
        scatter.append(
            {
                "cost": round(cost, 4),
                "quality": round(quality, 4),
                "model": model,
                "book_number": book,
                "variant": _safe_int(row.get("variant"), 0),
            }
        )

    budget_remaining = round(runtime.max_cost_usd - total_spent, 4)
    remaining_books = max(0, books_cataloged - books_generated)
    projected_remaining_cost = round(remaining_books * avg_cost_per_book, 4)

    chronological = sorted(items, key=lambda row: row.get("timestamp", ""))
    cumulative: list[dict[str, Any]] = []
    running = 0.0
    for row in chronological:
        running += _safe_float(row.get("cost"), 0.0)
        cumulative.append({"timestamp": row.get("timestamp"), "cumulative_cost": round(running, 4)})

    cost_per_quality_point = []
    for model, total_cost in sorted(by_model.items(), key=lambda item: item[1], reverse=True):
        model_rows = [row for row in items if str(row.get("model", "")) == model]
        avg_quality = (
            sum(_safe_float(row.get("quality_score"), 0.0) for row in model_rows) / max(1, len(model_rows))
            if model_rows
            else 0.0
        )
        efficiency = (total_cost / avg_quality) if avg_quality > 0 else math.inf
        cost_per_quality_point.append(
            {
                "model": model,
                "average_quality": round(avg_quality, 4),
                "total_cost": round(total_cost, 4),
                "cost_per_quality_point": round(efficiency, 4) if math.isfinite(efficiency) else None,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_spent": total_spent,
            "budget_total": runtime.max_cost_usd,
            "budget_remaining": budget_remaining,
            "books_cataloged": books_cataloged,
            "books_generated": books_generated,
            "remaining_books": remaining_books,
            "projected_remaining_cost": projected_remaining_cost,
            "average_cost_per_book": avg_cost_per_book,
        },
        "cost_per_model": [
            {"model": model, "cost": round(cost, 4)}
            for model, cost in sorted(by_model.items(), key=lambda item: item[1], reverse=True)
        ],
        "cost_per_book": [
            {"book_number": book, "cost": round(cost, 4)}
            for book, cost in sorted(by_book.items(), key=lambda item: item[0])
        ],
        "cost_per_quality_point": cost_per_quality_point,
        "cumulative_cost": cumulative,
        "scatter_cost_vs_quality": scatter[-2000:],
        "quality_trend": _load_quality_trend_series(runtime=runtime),
        "recent_results": _dashboard_recent_results(items=items, runtime=runtime, limit=24),
    }


def _record_cost_entry(
    *,
    runtime: config.Config,
    operation: str,
    cost_usd: float,
    model: str = "",
    provider: str = "",
    book_number: int = 0,
    job_id: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    images_generated: int = 0,
    duration_seconds: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        cost_tracker.record_entry(
            _cost_ledger_path_for_runtime(runtime),
            entry={
                "catalog": runtime.catalog_id,
                "book_number": int(book_number),
                "job_id": str(job_id or ""),
                "model": str(model or ""),
                "provider": str(provider or ""),
                "operation": str(operation or "generate"),
                "tokens_in": int(tokens_in),
                "tokens_out": int(tokens_out),
                "images_generated": int(images_generated),
                "cost_usd": float(cost_usd),
                "duration_seconds": float(duration_seconds),
                "metadata": metadata or {},
            },
        )
    except Exception as exc:  # pragma: no cover - analytics write failures should not break requests
        logger.warning("Cost ledger write failed: %s", exc)


def _record_generation_costs(
    *,
    runtime: config.Config,
    book_number: int,
    rows: list[dict[str, Any]],
    job_id: str = "",
) -> None:
    entries: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model", "") or "")
        provider = str(row.get("provider", "") or runtime.resolve_model_provider(model))
        entries.append(
            {
                "catalog": runtime.catalog_id,
                "book_number": int(book_number),
                "job_id": str(job_id or ""),
                "model": model,
                "provider": provider,
                "operation": "generate",
                "tokens_in": 0,
                "tokens_out": 0,
                "images_generated": 1 if bool(row.get("success", True)) else 0,
                "cost_usd": _safe_float(row.get("cost"), 0.0),
                "duration_seconds": _safe_float(row.get("generation_time"), 0.0),
                "timestamp": str(row.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                "metadata": {
                    "variant": _safe_int(row.get("variant"), 0),
                    "success": bool(row.get("success", True)),
                },
            }
        )
    if not entries:
        return
    try:
        cost_tracker.record_entries(_cost_ledger_path_for_runtime(runtime), entries=entries)
    except Exception as exc:  # pragma: no cover
        logger.warning("Cost ledger batch write failed: %s", exc)


def _cost_entries_for_runtime(
    *,
    runtime: config.Config,
    period: str | None,
) -> list[dict[str, Any]]:
    return cost_tracker.list_entries(
        _cost_ledger_path_for_runtime(runtime),
        catalog_id=runtime.catalog_id,
        period=period,
    )


def _budget_status_for_runtime(runtime: config.Config) -> dict[str, Any]:
    entries = _cost_entries_for_runtime(runtime=runtime, period="all")
    summary = cost_tracker.summarize(entries)
    budget_payload = cost_tracker.load_budget(_budget_config_path_for_runtime(runtime))
    status = cost_tracker.budget_status(
        spent_usd=_safe_float(summary.get("total_cost_usd"), 0.0),
        catalog_id=runtime.catalog_id,
        budget_payload=budget_payload,
    )
    # 30d spend-run-rate projection.
    recent = _cost_entries_for_runtime(runtime=runtime, period="30d")
    recent_spend = _safe_float(cost_tracker.summarize(recent).get("total_cost_usd"), 0.0)
    projected_30d = recent_spend
    status["projected_30d_spend_usd"] = round(projected_30d, 6)
    status["budget"] = {
        "global": budget_payload.get("global", {}),
        "catalog": budget_payload.get("catalogs", {}).get(runtime.catalog_id, {}) if isinstance(budget_payload.get("catalogs"), dict) else {},
    }
    return status


def _is_generation_budget_blocked(runtime: config.Config) -> bool:
    status = _budget_status_for_runtime(runtime)
    return bool(status.get("hard_stop", True)) and str(status.get("state", "ok")) == "blocked"


def _parse_period_token(query: dict[str, list[str]], *, default: str = "7d") -> str:
    return str(query.get("period", [default])[0] or default).strip().lower() or default


def _quality_distribution_payload(*, runtime: config.Config) -> dict[str, Any]:
    payload = _load_json(_quality_scores_path_for_runtime(runtime), {"scores": []})
    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    bins = [
        {"label": "0-20", "min": 0, "max": 20, "count": 0},
        {"label": "20-40", "min": 20, "max": 40, "count": 0},
        {"label": "40-60", "min": 40, "max": 60, "count": 0},
        {"label": "60-80", "min": 60, "max": 80, "count": 0},
        {"label": "80-100", "min": 80, "max": 100, "count": 0},
    ]
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        score = _safe_float(row.get("overall_score"), 0.0) * 100.0
        for bucket in bins:
            upper = float(bucket["max"])
            lower = float(bucket["min"])
            if score >= lower and (score < upper or (upper == 100 and score <= 100)):
                bucket["count"] = int(bucket.get("count", 0) or 0) + 1
                break
    return {"catalog": runtime.catalog_id, "bins": bins, "total": sum(int(row["count"]) for row in bins)}


def _quality_by_model_payload(*, runtime: config.Config) -> dict[str, Any]:
    rows = _load_generation_records(runtime=runtime)
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model = str(row.get("model", "unknown"))
        provider = str(row.get("provider", runtime.resolve_model_provider(model)))
        bucket = stats.setdefault(
            model,
            {
                "model": model,
                "provider": provider,
                "count": 0,
                "avg_quality": 0.0,
                "avg_cost_per_variant": 0.0,
                "avg_generation_time_seconds": 0.0,
                "failure_rate_percent": 0.0,
                "winner_rate_percent": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["avg_quality"] += _safe_float(row.get("quality_score"), 0.0) * 100.0
        bucket["avg_cost_per_variant"] += _safe_float(row.get("cost"), 0.0)
        bucket["avg_generation_time_seconds"] += _safe_float(row.get("duration"), 0.0)
        if str(row.get("status", "success")).lower() not in {"success", "completed"}:
            bucket["failure_rate_percent"] += 1

    winners = _winner_variant_map(runtime=runtime)
    winner_hits: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        book = _safe_int(row.get("book_number"), 0)
        if book <= 0:
            continue
        winner_variant = winners.get(book)
        if winner_variant is None:
            continue
        if _safe_int(row.get("variant"), 0) == winner_variant:
            model = str(row.get("model", "unknown"))
            winner_hits[model] = winner_hits.get(model, 0) + 1

    out = list(stats.values())
    for row in out:
        count = max(1, _safe_int(row.get("count"), 1))
        model = str(row.get("model", "unknown"))
        row["avg_quality"] = round(_safe_float(row.get("avg_quality"), 0.0) / count, 4)
        row["avg_cost_per_variant"] = round(_safe_float(row.get("avg_cost_per_variant"), 0.0) / count, 6)
        row["avg_generation_time_seconds"] = round(_safe_float(row.get("avg_generation_time_seconds"), 0.0) / count, 4)
        row["failure_rate_percent"] = round((_safe_float(row.get("failure_rate_percent"), 0.0) / count) * 100.0, 4)
        row["winner_rate_percent"] = round((winner_hits.get(model, 0) / count) * 100.0, 4)
        denom = _safe_float(row.get("avg_cost_per_variant"), 0.0)
        row["quality_per_dollar"] = round((_safe_float(row.get("avg_quality"), 0.0) / denom), 4) if denom > 0 else None
    out.sort(key=lambda item: (_safe_float(item.get("quality_per_dollar"), 0.0), _safe_float(item.get("avg_quality"), 0.0)), reverse=True)
    best = out[0]["model"] if out else None
    return {"catalog": runtime.catalog_id, "models": out, "recommended_model": best}


def _quality_trends_payload(*, runtime: config.Config, period: str) -> dict[str, Any]:
    payload = _load_json(_quality_scores_path_for_runtime(runtime), {"scores": []})
    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    since = cost_tracker._period_start(period)  # type: ignore[attr-defined]
    buckets: dict[str, list[float]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        history = row.get("history", [])
        if isinstance(history, list) and history:
            for event in history:
                if not isinstance(event, dict):
                    continue
                label = str(event.get("date") or event.get("action") or "")
                dt = _safe_iso_datetime(label)
                if since and dt and dt < since:
                    continue
                score = _safe_float(event.get("best_score"), 0.0) * (100.0 if _safe_float(event.get("best_score"), 0.0) <= 1.0 else 1.0)
                buckets.setdefault(label or "unknown", []).append(score)
        else:
            score = _safe_float(row.get("overall_score"), 0.0) * 100.0
            label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            buckets.setdefault(label, []).append(score)
    trend = []
    for label in sorted(buckets.keys()):
        vals = buckets[label]
        trend.append(
            {
                "label": label,
                "avg_quality": round(sum(vals) / len(vals), 4),
                "count": len(vals),
            }
        )
    return {"catalog": runtime.catalog_id, "period": period, "trend": trend}


def _quality_prompt_pattern_payload(*, runtime: config.Config) -> dict[str, Any]:
    payload = _load_json(_prompt_performance_path_for_runtime(runtime), {"patterns": {}})
    patterns = payload.get("patterns", {}) if isinstance(payload, dict) else {}
    rows: list[dict[str, Any]] = []
    if isinstance(patterns, dict):
        for name, row in patterns.items():
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "pattern": str(name),
                    "avg_quality": round(_safe_float(row.get("avg_score"), 0.0) * 100.0, 4),
                    "count": _safe_int(row.get("count"), 0),
                }
            )
    rows.sort(key=lambda item: (_safe_float(item.get("avg_quality"), 0.0), _safe_int(item.get("count"), 0)), reverse=True)
    return {"catalog": runtime.catalog_id, "patterns": rows}


def _quality_breakdown_payload(*, runtime: config.Config, book: int) -> dict[str, Any]:
    payload = _load_json(_quality_scores_path_for_runtime(runtime), {"scores": []})
    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    filtered = [
        row
        for row in rows
        if isinstance(row, dict) and (book <= 0 or _safe_int(row.get("book_number"), 0) == int(book))
    ]
    components = {
        "technical": 0.0,
        "color": 0.0,
        "artifact": 0.0,
        "style_consistency": 0.0,
        "composition": 0.0,
    }
    for row in filtered:
        components["technical"] += _safe_float(row.get("technical_score"), 0.0)
        components["color"] += _safe_float(row.get("color_score"), 0.0)
        components["artifact"] += _safe_float(row.get("artifact_score"), 0.0)
        components["style_consistency"] += _safe_float(row.get("distinctiveness_score"), 0.0)
        components["composition"] += _safe_float(row.get("diversity_score"), 0.0)
    count = max(1, len(filtered))
    for key in list(components.keys()):
        components[key] = round((components[key] / count) * 100.0, 4)
    return {"catalog": runtime.catalog_id, "book": book if book > 0 else None, "count": len(filtered), "breakdown": components}


def _completion_payload(*, runtime: config.Config) -> dict[str, Any]:
    review_rows = build_review_dataset(
        runtime.output_dir,
        input_dir=runtime.input_dir,
        catalog_path=runtime.book_catalog_path,
        quality_scores_path=_quality_scores_path_for_runtime(runtime),
    )
    winners_payload = _load_winner_payload(_winner_path_for_runtime(runtime))
    selections = winners_payload.get("selections", {}) if isinstance(winners_payload, dict) else {}
    if not isinstance(selections, dict):
        selections = {}
    total_books = len(review_rows)
    winners_selected = len({key for key, value in selections.items() if _safe_int(value.get("winner") if isinstance(value, dict) else value, 0) > 0})
    winners_pending = max(0, total_books - winners_selected)
    variants_generated = sum(len(row.get("variants", [])) for row in review_rows if isinstance(row, dict))
    mockup_status = mockup_generator.mockup_status(output_dir=runtime.output_dir)
    mockup_total = sum(_safe_int(row.get("generated"), 0) for row in mockup_status.get("books", []) if isinstance(row, dict))
    completion_percent = (winners_selected / total_books * 100.0) if total_books else 0.0
    # Simple velocity projection from available winners.
    days_remaining = math.ceil((winners_pending / max(1, winners_selected)) * 7) if winners_selected else None
    estimated_completion = (
        (datetime.now(timezone.utc) + timedelta(days=max(0, int(days_remaining or 0)))).date().isoformat()
        if days_remaining is not None
        else None
    )
    return {
        "catalog": runtime.catalog_id,
        "total_books": total_books,
        "variants_generated": variants_generated,
        "winners_selected": winners_selected,
        "winners_pending": winners_pending,
        "mockups_generated": mockup_total,
        "social_cards_generated": 0,
        "catalog_pdfs_generated": int((runtime.output_dir / "Alexandria_Cover_Catalog.pdf").exists()),
        "ready_for_production": winners_selected,
        "needs_regeneration": max(0, total_books - winners_selected),
        "estimated_completion": estimated_completion,
        "completion_percent": round(completion_percent, 4),
    }


def _build_api_docs_html() -> str:
    endpoints = [
        ("GET", "/iterate", "Iteration UI", "-", "-", "Interactive single-cover generation page."),
        ("GET", "/review", "Winner review UI", "-", "-", "Winner review and archive page."),
        ("GET", "/visual-qa", "Visual QA UI", "-", "-", "Visual compositor QA dashboard with PASS/FAIL comparisons."),
        ("GET", "/catalogs", "Catalog UI", "-", "-", "Generate winner catalogs/contact sheets/all-variants PDFs."),
        ("GET", "/history", "History UI", "-", "-", "Generation history viewer with filters."),
        ("GET", "/dashboard", "Dashboard UI", "-", "-", "Cost/quality dashboard."),
        ("GET", "/analytics/models", "Model analytics UI", "-", "-", "Model performance, recommendation, and cross-catalog analytics dashboard."),
        ("GET", "/prompts", "Prompt library UI", "-", "-", "Prompt CRUD/versioning and prompt performance workspace."),
        ("GET", "/catalog/settings", "Catalog settings UI", "-", "-", "Create/switch/configure catalogs and import/export catalog bundles."),
        ("GET", "/admin/performance", "Performance UI", "-", "-", "Request latency/error/cache/slow-endpoint monitoring page."),
        ("GET", "/batch", "Batch UI", "-", "-", "Batch generation planning and live progress page."),
        ("GET", "/similarity", "Similarity UI", "-", "-", "Cross-book similarity heatmap, alerts, and clusters."),
        ("GET", "/mockups", "Mockup UI", "-", "-", "Mockup gallery and generation controls."),
        ("GET", "/api/version", "API version", "-", "{\"version\":\"2.1.1\"}", "Current application version."),
        ("GET", "/api/models", "Model registry", "-", "{\"models\":[...],\"total\":13}", "List all known models with provider, cost, speed, and success stats."),
        ("GET", "/api/providers", "Provider health", "-", "{\"providers\":[...]}", "Provider-level health, circuit state, and 24h request/error counters."),
        ("GET", "/api/catalog", "Catalog overview", "-", "{\"catalogs\":[...],\"total_books\":2397}", "Catalog list with generated/winner counts."),
        ("GET", "/api/templates", "Template registry", "genre", "{\"templates\":[...],\"total\":10}", "List style templates with optional genre filtering."),
        ("GET", "/api/stats", "Usage stats", "-", "{\"total_generations\":150,...}", "Aggregate generation/cost/quality usage statistics."),
        ("GET", "/api/config", "Runtime config", "-", "{\"active_models\":[...],\"drive\":{...}}", "Non-sensitive runtime config and feature flags."),
        ("GET", "/api/catalogs", "Catalog list", "-", "{\"catalogs\":[...],\"active_catalog\":\"classics\"}", "Available catalogs for selector dropdowns."),
        ("GET", "/api/health", "Health check", "-", "{\"status\":\"ok\",...}", "Runtime health and config status."),
        ("GET", "/api/metrics", "Runtime metrics", "-", "{\"cache\":{...},\"errors\":{...},\"jobs\":{...}}", "Operational counters, error metrics, queue state, and worker service telemetry."),
        ("GET", "/api/performance/summary", "Performance summary", "catalog", "{\"response_time\":{...},\"slow_requests\":{...}}", "Slow-request response-time quantiles, endpoint rollups, and latest slow request samples."),
        ("GET", "/api/providers/runtime", "Provider runtime", "-", "{\"providers\":{...}}", "Provider request/error counters, circuit breaker, and rate-limit windows."),
        ("GET", "/api/workers", "Worker service status", "-", "{\"workers\":{...}}", "Worker mode + heartbeat status for inline/external workers."),
        ("GET", "/api/audit-log?limit=100", "Audit log", "limit", "{\"items\":[...]}", "Signed audit entries for cost/destructive operations."),
        ("GET", "/api/analytics/costs?period=7d", "Cost summary", "period,catalog", "{\"summary\":{...}}", "Cost totals and operation mix from cost ledger."),
        ("GET", "/api/analytics/costs/by-book", "Cost by book", "period,catalog", "{\"books\":[...]}", "Book-level cost breakdown."),
        ("GET", "/api/analytics/costs/by-model", "Cost by model", "period,catalog", "{\"models\":[...]}", "Model/provider cost breakdown."),
        ("GET", "/api/analytics/costs/timeline?period=30d&granularity=daily", "Cost timeline", "period,granularity,catalog", "{\"timeline\":[...]}", "Cost trend with cumulative totals."),
        ("GET", "/api/analytics/budget", "Budget status", "catalog", "{\"budget\":{...}}", "Budget limit, warning/blocked state, and projected spend."),
        ("POST", "/api/analytics/budget", "Set budget", "{\"catalog\":\"...\",\"limit_usd\":100,\"warning_threshold\":0.8}", "{\"ok\":true}", "Set budget limit/threshold."),
        ("POST", "/api/analytics/budget/override", "Override budget", "{\"catalog\":\"...\",\"extra_limit_usd\":25,\"duration_hours\":24}", "{\"ok\":true}", "Temporary budget increase."),
        ("GET", "/api/analytics/quality/trends?period=30d", "Quality trends", "period,catalog", "{\"trend\":[...]}", "Quality evolution over time."),
        ("GET", "/api/analytics/quality/distribution", "Quality distribution", "catalog", "{\"bins\":[...]}", "Quality score histogram."),
        ("GET", "/api/analytics/models/compare", "Model compare", "catalog", "{\"models\":[...],\"recommended_model\":\"...\"}", "Quality/cost/speed/failure comparison."),
        ("GET", "/api/analytics/models/recommendation", "Model recommendation", "catalog,book", "{\"recommended_model\":\"...\",\"reason\":\"...\"}", "Per-book or catalog-level model recommendation summary."),
        ("GET", "/api/analytics/ab-tests", "A/B test log", "catalog,limit", "{\"items\":[...]}", "Recent winner selections and compared model sets."),
        ("POST", "/api/analytics/ab-tests", "Record A/B winner", "{\"book_id\":42,\"models_compared\":[...],\"winner\":\"...\"}", "{\"ok\":true}", "Store winner decisions for model comparison analytics."),
        ("GET", "/api/analytics/completion", "Catalog completion", "catalog", "{\"completion_percent\":85.8}", "Winner completion and production-readiness summary."),
        ("GET", "/api/analytics/cost-projection?books=100&variants=5&models=openrouter/google/gemini-2.5-flash-image", "Cost projection", "books,variants,models,catalog", "{\"estimatedCostUsd\":1.48,...}", "Estimate total cost/time/storage before starting large runs."),
        ("POST", "/api/analytics/export-report", "Export analytics report", "{\"period\":\"30d\"}", "{\"report_id\":\"...\"}", "Generate report artifact in data/reports."),
        ("GET", "/api/analytics/reports", "List reports", "-", "{\"reports\":[...]}", "List generated analytics report files."),
        ("POST", "/api/admin/migrate-to-sqlite", "Migrate JSON -> SQLite", "{\"db_path\":\"data/alexandria.db\"}", "{\"ok\":true,\"summary\":{...}}", "One-shot migration command for scale mode."),
        ("GET", "/api/jobs?status=queued,running&limit=50", "List async jobs", "status,limit,book,catalog", "{\"jobs\":[...],\"count\":12}", "List persisted async generation jobs."),
        ("GET", "/api/jobs/{id}", "Get async job", "job_id", "{\"job\":{...},\"attempts\":[...]}", "Inspect one async job including attempt history."),
        ("GET", "/api/generation-failures?catalog=classics&limit=20", "Generation failures", "catalog,limit", "{\"failures\":[...]}", "Inspect recent failed or retrying generation jobs with attempt diagnostics."),
        ("GET", "/api/batch-generate", "List batches", "catalog,limit,offset", "{\"batches\":[...],\"pagination\":{...}}", "List recent batch generation runs."),
        ("GET", "/api/batch-generate/{batchId}/status", "Batch status", "batchId,catalog,limit,offset", "{\"status\":\"running\",\"books\":[...]}", "Get live per-book batch progress with pagination."),
        ("GET", "/api/events/job/{id}", "Job SSE stream", "id,catalog", "event-stream", "Real-time stream for one async job."),
        ("GET", "/api/events/batch/{batchId}", "Batch SSE stream", "batchId,catalog", "event-stream", "Real-time stream for one batch run."),
        ("GET", "/api/review-data?catalog=classics&limit=25&offset=0", "Review data", "catalog,limit,offset,sort,order,search,status,tags", "{\"books\":[...],\"pagination\":{...}}", "Paginated review books, winners, and filters."),
        ("GET", "/api/iterate-data?catalog=classics&limit=25&offset=0", "Iterate data", "catalog,limit,offset,sort,order,search,status", "{\"books\":[...],\"pagination\":{...}}", "Paginated iterate books + model configuration."),
        ("GET", "/api/enrichment-health", "Enrichment health", "catalog", "{\"health\":\"warning\",...}", "Catalog-wide enrichment quality summary with generic/missing counts."),
        ("GET", "/api/config/cover-source-default", "Default cover source", "catalog", "{\"default\":\"drive\"}", "Return server-selected default cover source based on environment."),
        ("GET", "/api/prompts", "Prompt library list", "catalog,q,category,tags", "{\"prompts\":[...]}", "Search/list prompt library with usage, win rate, and version counts."),
        ("POST", "/api/prompts", "Create prompt", "{\"name\":\"...\",\"prompt_template\":\"...\"}", "{\"ok\":true,\"prompt\":{...}}", "Create a prompt-library entry."),
        ("POST", "/api/prompts/{id}", "Update/delete/usage", "{\"action\":\"update|delete|record_usage\"}", "{\"ok\":true}", "Update prompt fields, delete prompt, or record usage/win counters."),
        ("GET", "/api/prompts/{id}/versions", "Prompt version history", "catalog", "{\"versions\":[...]}", "List historical prompt versions for rollback."),
        ("GET", "/api/prompts/export", "Export prompt library", "catalog", "{\"prompts\":[...],\"versions\":{...}}", "Export prompt library payload as JSON."),
        ("POST", "/api/prompts/import", "Import prompts", "{\"prompts\":[...]}", "{\"ok\":true,\"imported\":12}", "Bulk import prompt library entries."),
        ("GET", "/api/prompt-performance", "Prompt pattern stats", "-", "{\"patterns\":{...}}", "Prompt performance breakdown for intelligent prompting."),
        ("GET", "/api/history?book=2", "Book history", "book", "{\"items\":[...]}", "History subset for one book."),
        ("GET", "/api/generation-history?book=2&model=flux&status=success&limit=50&offset=0", "Filtered generation history", "book,model,provider,status,date_from,date_to,quality_min,quality_max,limit,offset", "{\"items\":[...],\"total\":123,\"pagination\":{...}}", "Global sortable/filterable generation records."),
        ("GET", "/api/dashboard-data", "Dashboard metrics", "-", "{\"summary\":{...},...}", "Cost and quality analytics for charts."),
        ("GET", "/api/visual-qa", "Visual QA index", "catalog,book_number,force", "{\"comparisons\":[...],\"summary\":{...}}", "List generated comparison grids with PASS/FAIL verdicts."),
        ("GET", "/api/visual-qa/image/{book_number}", "Visual QA image", "book_number,catalog", "binary image", "Serve one visual comparison JPG."),
        ("GET", "/api/weak-books?threshold=0.75", "Weak books", "threshold,catalog", "{\"books\":[...]}", "Books below a quality threshold."),
        ("GET", "/api/regeneration-results?book=15", "Regeneration results", "book", "{\"results\":[...]}", "Read saved re-generation comparison results."),
        ("GET", "/api/review-queue?threshold=0.90", "Speed review queue", "threshold", "{\"queue\":[...],\"auto_approve\":34}", "Ordered speed-review queue with confidence and summary buckets."),
        ("GET", "/api/review-session/{id}", "Review session", "session_id", "{\"session\":{...}}", "Load a saved speed-review session state."),
        ("GET", "/api/review-stats", "Review stats", "-", "{\"sessions\":[...]}", "Aggregate completed review session metrics."),
        ("GET", "/api/similarity-matrix?threshold=0.25&limit=50&offset=0", "Similarity matrix", "threshold,limit,offset", "{\"pairs\":[...],\"pagination\":{...}}", "Paginated similarity pairs for large catalogs."),
        ("GET", "/api/similarity/recompute/status", "Similarity recompute status", "catalog", "{\"recompute\":{...}}", "Background recompute status for full similarity cache refresh."),
        ("GET", "/api/similarity-alerts?threshold=0.25", "Similarity alerts", "threshold", "{\"alerts\":[...]}", "Pairs below similarity threshold."),
        ("GET", "/api/similarity-clusters", "Similarity clusters", "-", "{\"clusters\":[...]}", "Connected clusters of visually similar covers."),
        ("GET", "/api/cover-hash/15", "Single cover hash", "-", "{\"hash\":{...}}", "pHash/dHash/histogram values for one winner."),
        ("GET", "/api/mockup-status?limit=25&offset=0", "Mockup status", "limit,offset", "{\"books\":[...],\"pagination\":{...}}", "Paginated per-book mockup completion status."),
        ("GET", "/api/providers/connectivity?force=0", "Provider connectivity", "force,catalog", "{\"providers\":{...}}", "Cached provider connectivity checks used by iterate auto-status."),
        ("GET", "/api/drive-status", "Save Raw drive status", "catalog", "{\"connected\":true,...}", "Focused Save Raw Google Drive diagnostics including credential identity and parent folder access."),
        ("GET", "/api/drive/status", "Drive status", "catalog,drive_folder_id,input_folder_id", "{\"connected\":true,...}", "Drive credentials/source/output status and sync summary."),
        ("GET", "/api/drive/sync-status", "Drive sync status", "catalog,drive_folder_id,input_folder_id", "{\"status\":{...}}", "Alias for drive status focused on sync/pending/error summary."),
        ("GET", "/api/drive/input-covers", "Drive input covers", "catalog,drive_folder_id,input_folder_id,limit,force", "{\"covers\":[...]}", "List top-level source covers/folders from Google Drive for iterate selection."),
        ("GET", "/api/books/{book}/cover-preview?source=drive", "Book cover preview", "book,source,selected_cover_id,catalog", "binary image", "Build/return a thumbnail preview from local or Drive-backed source cover."),
        ("GET", "/api/variant-download?book=15&variant=2", "Variant ZIP download", "book,variant,model,catalog", "binary zip", "Download one generated variant package (JPG/PDF/medallion/metadata)."),
        ("GET", "/api/winner-download?book=15", "Winner ZIP download", "book,catalog", "binary zip", "Download selected winner package for one book."),
        ("GET", "/api/source-download?book=15&variant=2&model=openrouter/google/gemini-2.5-flash-image", "Source image download", "book,variant,model,catalog", "binary image", "Download raw source image for one generated variant."),
        ("GET", "/api/download-book?book=15", "Book variants ZIP", "book,catalog", "binary zip", "Download all generated variants (composited + source) for one book."),
        ("GET", "/api/download-approved", "Approved variants ZIP", "catalog", "binary zip", "Download all approved winner variants (composited + source)."),
        ("GET", "/api/exports", "List exports", "catalog,limit,offset", "{\"exports\":[...],\"pagination\":{...}}", "Export artifacts with size and file counts."),
        ("GET", "/api/export/status", "Export status tracking", "catalog,limit,offset", "{\"items\":[...]}", "Per-book/per-platform export status including changed-since-last-export flags."),
        ("GET", "/api/exports/{id}/download", "Download export ZIP", "id", "binary zip", "Build and stream a ZIP for a single export artifact."),
        ("GET", "/api/delivery/status", "Delivery status", "catalog", "{\"enabled\":true,...}", "Delivery automation settings and completion summary."),
        ("GET", "/api/delivery/tracking", "Delivery tracking grid", "catalog,limit,offset", "{\"items\":[...]}", "Per-book delivery status across platforms."),
        ("GET", "/api/archive/stats", "Archive stats", "catalog", "{\"archive_size_gb\":...}", "Archive size, count, and date range."),
        ("GET", "/api/storage/usage", "Storage usage", "catalog", "{\"total_gb\":...}", "Storage breakdown + cleanup suggestion."),
        ("GET", "/api/mockup/{book}/{template}", "Mockup image", "book,template", "binary image", "Serve one generated mockup image."),
        ("GET", "/api/mockup-zip?book=15", "Mockup ZIP", "book", "{\"url\":\"/...zip\"}", "Bundle all mockups for one book as ZIP."),
        ("POST", "/api/save-selections", "Save winners", "{\"selections\":{...}}", "{\"ok\":true}", "Persist winner selections with metadata."),
        ("POST", "/api/enrich-book", "Enrich one book", "{\"book\":15}", "{\"ok\":true,\"book\":{...}}", "Generate/refresh LLM enrichment metadata for one title."),
        ("POST", "/api/enrich-all", "Enrich all books", "{}", "{\"ok\":true,\"summary\":{...}}", "Generate enrichment metadata across the full catalog."),
        ("POST", "/api/enrich-generic", "Re-enrich generic books", "{\"delay\":0.5,\"batch_size\":50}", "{\"ok\":true,\"started\":true}", "Start a background run that only re-enriches generic placeholder rows."),
        ("POST", "/api/generate-smart-prompts", "Generate intelligent prompts", "{\"book\":15,\"count\":5}", "{\"ok\":true,\"book\":{...}}", "Generate AI-authored prompts plus quality scores."),
        ("POST", "/api/generate-mockup", "Generate one mockup", "{\"book\":15,\"template\":\"desk_scene\"}", "{\"ok\":true}", "Generate one mockup template for one book."),
        ("POST", "/api/generate-all-mockups", "Generate mockup batch", "{\"book\":15}|{\"all_books\":true}", "{\"ok\":true}", "Generate all selected templates for one/all books."),
        ("POST", "/api/generate-amazon-set", "Generate Amazon set", "{\"book\":15}|{\"all_books\":true}", "{\"ok\":true}", "Generate 7-image Amazon listing set."),
        ("POST", "/api/generate-social-cards", "Generate social cards", "{\"book\":15,\"formats\":[\"instagram\",\"facebook\"]}", "{\"ok\":true}", "Generate marketing cards for social platforms."),
        ("POST", "/api/visual-qa/generate", "Generate visual QA", "{\"book_number\":15}", "{\"ok\":true,\"generated\":99,\"passed\":95,\"failed\":4}", "Generate visual comparison grids for one/all books."),
        ("POST", "/api/save-raw", "Save raw package", "{\"job_id\":\"...\"}", "{\"ok\":true,\"status\":\"saved|partial\",...}", "Copy raw/composited winner files locally and upload them to Google Drive with structured per-file status."),
        ("POST", "/api/retry-drive-upload", "Retry save raw Drive upload", "{\"job_id\":\"...\"}", "{\"ok\":true,\"retried\":true,...}", "Retry the Google Drive upload for an already saved raw package without surfacing a hard client error."),
        ("POST", "/api/save-prompt", "Save prompt", "{\"name\":\"...\",\"prompt_template\":\"...\"}", "{\"ok\":true,\"prompt_id\":\"...\"}", "Save prompt into prompt library."),
        ("POST", "/api/providers/reset", "Reset provider runtime", "{\"provider\":\"all|openai|...\"}", "{\"ok\":true}", "Reset provider circuit/rate-limit/runtime counters."),
        ("POST", "/api/test-connection", "Test provider keys", "{\"provider\":\"all|openai|...\"}", "{\"ok\":true,\"report\":{...}}", "Validate provider connectivity."),
        ("POST", "/api/validate/cover", "Validate print readiness", "{\"file_path\":\"Output Covers/.../cover.jpg\",\"distributor\":\"ingram_spark\"}", "{\"ok\":true,\"passed\":true}", "Validate one cover against distributor print specs."),
        ("POST", "/api/generate", "Generate variants", "{\"book\":2,\"models\":[...],\"variants\":5,\"prompt\":\"...\",\"async\":true,\"dry_run\":false}", "{\"ok\":true,\"job\":{...}}", "Queue async generation job (idempotent). Sync mode (async=false) is disabled by default unless ALLOW_SYNC_GENERATION=1."),
        ("POST", "/api/batch-generate", "Create batch generation", "{\"books\":[1,2,3],\"models\":[...],\"variants\":5,\"budgetUsd\":25}", "{\"ok\":true,\"batchId\":\"...\"}", "Queue multiple book jobs under one batch id with budget controls."),
        ("POST", "/api/batch-generate/{batchId}/pause", "Pause batch", "{\"reason\":\"manual\"}", "{\"ok\":true,\"status\":\"paused\"}", "Pause queued jobs in a batch."),
        ("POST", "/api/batch-generate/{batchId}/resume", "Resume batch", "{}", "{\"ok\":true,\"status\":\"queued\"}", "Resume paused jobs in a batch."),
        ("POST", "/api/batch-generate/{batchId}/cancel", "Cancel batch", "{\"reason\":\"manual\"}", "{\"ok\":true,\"status\":\"cancelled\"}", "Cancel queued jobs in a batch."),
        ("POST", "/api/jobs/{id}/cancel", "Cancel async job", "{\"reason\":\"...\"}", "{\"ok\":true,\"job\":{...}}", "Cancel queued/retrying/running async job."),
        ("POST", "/api/jobs/{id}/cancel-model", "Cancel one model in job", "{\"model\":\"...\",\"reason\":\"...\"}", "{\"ok\":true}", "Cancel one model stream while leaving the rest of the generation job running."),
        ("POST", "/api/regenerate", "Re-generate weak book(s)", "{\"book\":15,\"variants\":5,\"use_library\":true}", "{\"ok\":true,\"summary\":{...}}", "Run targeted re-generation workflow."),
        ("POST", "/api/similarity/recompute", "Recompute similarity cache", "{\"threshold\":0.25}", "{\"ok\":true,\"job\":{...}}", "Trigger background full similarity recompute."),
        ("POST", "/api/similarity/update", "Incremental similarity update", "{\"book\":15}", "{\"ok\":true}", "Recompute similarity pairs for one book only."),
        ("POST", "/api/export/validate/{book_number}", "Validate export readiness", "-", "{\"ok\":true,\"platforms\":{...}}", "Validate winner cover readiness for Amazon/Ingram/Social/Web without writing exports."),
        ("POST", "/api/export/amazon", "Amazon export", "{\"books\":\"1-20\"}", "{\"ok\":true,\"export_id\":\"...\"}", "Generate Amazon listing assets for winners."),
        ("POST", "/api/export/amazon/{book_number}", "Amazon export (single)", "-", "{\"ok\":true}", "Generate Amazon assets for one title."),
        ("POST", "/api/export/ingram", "Ingram export", "{\"books\":\"1-20\"}", "{\"ok\":true}", "Generate IngramSpark print package."),
        ("POST", "/api/export/social?platforms=instagram,facebook", "Social export", "{\"books\":\"1-20\"}", "{\"ok\":true}", "Generate multi-platform social cards."),
        ("POST", "/api/export/web", "Web export", "{\"books\":\"1-20\"}", "{\"ok\":true}", "Generate web-optimized cover sizes + manifest."),
        ("POST", "/api/export/all", "Export all pipelines", "{\"books\":\"all\",\"platforms\":[\"amazon\",\"ingram\",\"social\",\"web\"]}", "{\"ok\":true,\"combined_export_id\":\"...\"}", "Run all export pipelines and produce one combined bundle."),
        ("POST", "/api/delivery/enable", "Enable delivery", "-", "{\"ok\":true}", "Enable automatic delivery pipeline for catalog."),
        ("POST", "/api/delivery/disable", "Disable delivery", "-", "{\"ok\":true}", "Disable automatic delivery pipeline for catalog."),
        ("POST", "/api/delivery/batch?platforms=amazon,social", "Batch delivery", "{\"books\":\"1-20\"}", "{\"ok\":true}", "Deliver selected/all winner books across configured platforms."),
        ("POST", "/api/sync-to-drive", "Sync selected winners", "{\"selections\":{...}}", "{\"ok\":true,\"summary\":{...}}", "Sync selected winner files to Google Drive."),
        ("POST", "/api/drive/push", "Drive push", "{\"mode\":\"push\"}", "{\"ok\":true}", "Push local winners/mockups/exports to Drive layout."),
        ("POST", "/api/drive/pull", "Drive pull", "{\"mode\":\"pull\"}", "{\"ok\":true}", "Pull new source covers from Drive input folder."),
        ("POST", "/api/drive/sync", "Drive full sync", "{\"mode\":\"bidirectional\"}", "{\"ok\":true}", "Run pull + push with conflict resolution."),
        ("POST", "/api/archive-non-winners", "Archive non-winners", "{\"dry_run\":true}", "{\"ok\":true,\"summary\":{...}}", "Move non-winning variants to Archive/ (never delete)."),
        ("POST", "/api/archive/old-exports?days=30", "Archive old exports", "days", "{\"ok\":true}", "Archive export packages older than N days."),
        ("POST", "/api/archive/restore/{book_number}", "Restore archived book", "-", "{\"ok\":true}", "Restore archived assets for a title."),
        ("POST", "/api/dismiss-similarity", "Dismiss similarity alert", "{\"book_a\":1,\"book_b\":47}", "{\"ok\":true}", "Mark a similarity pair as reviewed/acceptable."),
        ("POST", "/api/batch-approve", "Batch approve winners", "{\"threshold\":0.90}", "{\"ok\":true,\"summary\":{...}}", "Confirm all winners above threshold for speed review."),
        ("POST", "/api/review-selection", "Save one speed selection", "{\"book\":15,\"variant\":3,\"reviewer\":\"tim\"}", "{\"ok\":true}", "Persist a single manual speed-review selection."),
        ("POST", "/api/save-review-session", "Save speed session", "{\"session_id\":\"...\",\"books_reviewed\":42}", "{\"ok\":true}", "Save or complete a speed-review session snapshot."),
        ("DELETE", "/api/exports/{id}", "Delete export", "id", "{\"ok\":true}", "Delete export artifact and remove it from manifest."),
        ("GET", "/api/generate-catalog?mode=catalog|contact_sheet|all_variants", "Generate PDFs", "mode", "{\"ok\":true,\"download_url\":\"/...pdf\"}", "Generate catalog/contact/all-variants PDF outputs."),
        ("GET", "/api/docs", "API docs", "-", "HTML", "This documentation page."),
    ]

    rows = []
    for method, route, title, params, example, desc in endpoints:
        rows.append(
            f"<tr><td><code>{method}</code></td><td><code>{route}</code></td><td>{title}</td><td><code>{params}</code></td><td><code>{example}</code></td><td>{desc}</td></tr>"
        )

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<title>Alexandria API Docs</title>"
        "<style>"
        "body{margin:0;font-family:Georgia,serif;background:#1a2744;color:#f5e6c8;padding:20px;}"
        "h1{color:#c4a352;margin:0 0 10px;}"
        "table{width:100%;border-collapse:collapse;background:#243454;}"
        "th,td{border:1px solid rgba(245,230,200,.25);padding:10px;vertical-align:top;font-size:13px;}"
        "th{background:#1f2f52;color:#c4a352;text-align:left;}"
        "code{color:#f5e6c8;}a{color:#c4a352;} .nav a{margin-right:12px;}"
        "</style></head><body>"
        "<div class='nav'><a href='/iterate'>Iterate</a><a href='/review'>Review</a><a href='/visual-qa'>Visual QA</a><a href='/batch'>Batch</a><a href='/catalogs'>Catalogs</a><a href='/jobs'>Jobs</a><a href='/compare'>Compare</a><a href='/history'>History</a><a href='/dashboard'>Dashboard</a><a href='/similarity'>Similarity</a><a href='/mockups'>Mockups</a></div>"
        "<h1>Alexandria API Documentation</h1>"
        "<p>Auto-generated endpoint summary from <code>scripts/quality_review.py</code>.</p>"
        "<table><thead><tr><th>Method</th><th>URL</th><th>Name</th><th>Parameters</th><th>Example Response</th><th>Description</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def run_worker_service(
    *,
    catalog_id: str | None = None,
    worker_count: int | None = None,
) -> None:
    """Run queue workers without starting the web server."""
    global ACTIVE_WORKER_MODE
    ACTIVE_WORKER_MODE = "external"
    runtime = config.get_config(catalog_id)
    _bootstrap_state_store_for_runtime(runtime)
    stale_after_seconds, retry_delay_seconds = _job_stale_recovery_config(runtime)
    recovered = job_db_store.recover_stale_running_jobs(
        stale_after_seconds=stale_after_seconds,
        retry_delay_seconds=retry_delay_seconds,
    )
    if recovered:
        logger.warning("Recovered stale jobs on worker startup", extra={"recovered_jobs": recovered})

    effective_worker_count = max(1, int(worker_count or getattr(runtime, "job_workers", JOB_WORKER_COUNT)))
    heartbeat_path = Path(getattr(runtime, "job_worker_heartbeat_path", JOB_WORKER_HEARTBEAT_PATH))
    pool = JobWorkerPool(
        job_db_store,
        worker_count=effective_worker_count,
        heartbeat_path=heartbeat_path,
        service_name="external",
    )
    slo_monitor: SLOBackgroundMonitor | None = None
    slo_monitor_interval_seconds = _slo_monitor_interval_seconds(runtime)
    if slo_monitor_interval_seconds > 0:
        slo_monitor = SLOBackgroundMonitor(
            interval_seconds=slo_monitor_interval_seconds,
            runtime_loader=lambda _catalog=None: config.get_config(runtime.catalog_id),
            catalog_ids_loader=lambda: [runtime.catalog_id],
        )
        slo_monitor.start()
        _set_slo_background_monitor(slo_monitor)
        logger.info(
            "Worker background SLO monitor started",
            extra={"interval_seconds": slo_monitor_interval_seconds, "catalog_id": runtime.catalog_id},
        )
    else:
        _set_slo_background_monitor(None)
    pool.start()
    logger.info(
        "External worker service started",
        extra={
            "workers": pool.worker_count,
            "heartbeat_path": str(heartbeat_path),
        },
    )
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Worker shutdown requested")
    finally:
        if slo_monitor is not None:
            slo_monitor.stop()
            _set_slo_background_monitor(None)
        pool.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 5 review and iteration tooling")
    parser.add_argument("--catalog", type=str, default=config.DEFAULT_CATALOG_ID, help="Catalog id from config/catalogs.json")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--books", type=str, default=None)
    parser.add_argument("--max-books", type=int, default=None)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--workers-only", action="store_true", help="Run queue workers without web server")
    parser.add_argument(
        "--worker-mode",
        type=str,
        default=JOB_WORKER_MODE,
        help="Worker mode for web server: inline|external|disabled (default from JOB_WORKER_MODE)",
    )
    parser.add_argument("--workers", type=int, default=JOB_WORKER_COUNT, help="Worker thread count")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", type=str, default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--reviewer", type=str, default=os.getenv("REVIEWER", "tim"), help="Default reviewer name")
    parser.add_argument("--grid", type=Path, default=None, help="Create one comparison grid image")
    parser.add_argument("--book", type=int, default=None, help="Book number for comparison grid")

    args = parser.parse_args()
    runtime = config.get_config(args.catalog)
    _bootstrap_state_store_for_runtime(runtime)
    output_dir = args.output_dir or runtime.output_dir
    reviewer = str(args.reviewer or "tim").strip() or "tim"

    if args.workers_only:
        run_worker_service(catalog_id=runtime.catalog_id, worker_count=args.workers)
        return 0

    if args.grid and args.book:
        catalog = json.loads(runtime.book_catalog_path.read_text(encoding="utf-8"))
        entry = next((row for row in catalog if int(row.get("number", 0)) == args.book), None)
        if not entry:
            raise KeyError(f"Book {args.book} not in catalog")

        folder_name = str(entry["folder_name"])
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]

        original = _find_original_image(runtime.input_dir / str(entry["folder_name"]))
        variants_dir = output_dir / folder_name
        if not original:
            raise FileNotFoundError("Original cover not found")
        create_comparison_grid(original, variants_dir, args.grid)
        logger.info("Wrote comparison grid to %s", args.grid)
        return 0

    if args.serve:
        serve_review_webapp(
            output_dir,
            port=args.port,
            host=args.host,
            reviewer_default=reviewer,
            worker_mode=_normalize_worker_mode(args.worker_mode),
        )
        return 0

    books = _parse_books(args.books)
    review_books = build_review_dataset(
        output_dir,
        input_dir=runtime.input_dir,
        catalog_path=runtime.book_catalog_path,
        quality_scores_path=_quality_scores_path_for_runtime(runtime),
        books=books,
        max_books=args.max_books,
    )
    winner_payload = _ensure_winner_payload(review_books, path=_winner_path_for_runtime(runtime))
    review_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog": runtime.catalog_id,
        "books": review_books,
        "winner_selections": winner_payload.get("selections", {}),
    }
    review_data_path = _review_data_path_for_runtime(runtime)
    review_data_path.parent.mkdir(parents=True, exist_ok=True)
    safe_json.atomic_write_json(review_data_path, review_data)
    iterate_data_path = write_iterate_data(runtime=runtime)
    generate_review_gallery(output_dir, runtime=runtime, max_books=args.max_books)

    logger.info("Wrote review data: %s", review_data_path)
    logger.info("Wrote iterate data: %s", iterate_data_path)
    logger.info("Wrote fallback gallery: %s", FALLBACK_HTML_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
