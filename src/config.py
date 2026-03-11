"""Central runtime configuration for Alexandria Cover Designer."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests

try:
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from logger import get_logger  # type: ignore

load_dotenv()
logger = get_logger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / os.getenv("INPUT_DIR", "Input Covers")
OUTPUT_DIR = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "Output Covers")
TMP_DIR = PROJECT_ROOT / os.getenv("TMP_DIR", "tmp")
DATA_DIR = PROJECT_ROOT / os.getenv("DATA_DIR", "data")
CONFIG_DIR = PROJECT_ROOT / os.getenv("CONFIG_DIR", "config")

PROMPTS_PATH = CONFIG_DIR / os.getenv("PROMPTS_FILE", "book_prompts.json")
BOOK_CATALOG_PATH = CONFIG_DIR / os.getenv("BOOK_CATALOG_FILE", "book_catalog.json")
PROMPT_TEMPLATES_PATH = CONFIG_DIR / os.getenv("PROMPT_TEMPLATES_FILE", "prompt_templates.json")
PROMPT_LIBRARY_PATH = CONFIG_DIR / os.getenv("PROMPT_LIBRARY_FILE", "prompt_library.json")
CATALOGS_PATH = CONFIG_DIR / os.getenv("CATALOGS_FILE", "catalogs.json")
COVER_TEMPLATES_PATH = CONFIG_DIR / os.getenv("COVER_TEMPLATES_FILE", "cover_templates.json")
MODEL_PROMPT_OVERRIDES_PATH = CONFIG_DIR / os.getenv("MODEL_PROMPT_OVERRIDES_FILE", "model_prompt_overrides.json")
DEFAULT_CATALOG_ID = os.getenv("CATALOG_ID", "classics").strip() or "classics"

# Provider defaults
DEFAULT_MODEL = "openrouter/google/gemini-3-pro-image-preview"
DEFAULT_MODEL_DISPLAY_NAME = "Nano Banana Pro"
AI_PROVIDER = os.getenv("AI_PROVIDER", "openrouter").strip().lower()
AI_MODEL = os.getenv("AI_MODEL", DEFAULT_MODEL).strip()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
FAL_API_KEY = os.getenv("FAL_API_KEY", "")
# Deprecated/inactive provider (kept for compatibility only).
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-5-20250929").strip()
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))
LLM_COST_PER_1K_TOKENS = float(os.getenv("LLM_COST_PER_1K_TOKENS", "0.003"))
# Prefer DRIVE_* env vars, keep GDRIVE_* aliases for backwards compatibility.
GDRIVE_OUTPUT_FOLDER_ID = os.getenv(
    "DRIVE_OUTPUT_FOLDER_ID",
    os.getenv("GDRIVE_OUTPUT_FOLDER_ID", "1CWxCE3dP2AmQRy-w9MowP0J7AWNuAYdW"),
)
GDRIVE_SOURCE_FOLDER_ID = os.getenv(
    "DRIVE_SOURCE_FOLDER_ID",
    os.getenv("GDRIVE_SOURCE_FOLDER_ID", "1ybFYDJk7Y3VlbsEjRAh1LOfdyVsHM_cS"),
).strip()
GDRIVE_INPUT_FOLDER_ID = os.getenv("GDRIVE_INPUT_FOLDER_ID", GDRIVE_SOURCE_FOLDER_ID).strip()
GDRIVE_MOCKUPS_FOLDER_ID = os.getenv("GDRIVE_MOCKUPS_FOLDER_ID", "")
GDRIVE_AMAZON_FOLDER_ID = os.getenv("GDRIVE_AMAZON_FOLDER_ID", "")
GDRIVE_SOCIAL_FOLDER_ID = os.getenv("GDRIVE_SOCIAL_FOLDER_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "")
OPENROUTER_PRICING_SYNC_INTERVAL_SECONDS = int(os.getenv("OPENROUTER_PRICING_SYNC_INTERVAL_SECONDS", "21600"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_EVENTS = [token.strip() for token in os.getenv("WEBHOOK_EVENTS", "batch_complete,batch_error,milestone").split(",") if token.strip()]
OUTBOUND_ALLOWLIST_DOMAINS = [
    token.strip().lower()
    for token in os.getenv(
        "OUTBOUND_ALLOWLIST_DOMAINS",
        "api.openai.com,openrouter.ai,fal.run,generativelanguage.googleapis.com",
    ).split(",")
    if token.strip()
]

ALL_MODELS = [
    m.strip()
    for m in os.getenv(
        "ALL_MODELS",
        (
            "openrouter/openai/gpt-5-image,"
            "openrouter/sourceful/riverflow-v2-pro,"
            "openrouter/sourceful/riverflow-v2-max-preview,"
            "openrouter/black-forest-labs/flux.2-max,"
            "openrouter/black-forest-labs/flux.2-flex,"
            "openrouter/bytedance-seed/seedream-4.5,"
            "openrouter/sourceful/riverflow-v2-standard-preview,"
            "openrouter/black-forest-labs/flux.2-pro,"
            "openrouter/sourceful/riverflow-v2-fast-preview,"
            "openrouter/google/gemini-3-pro-image-preview,"
            "openrouter/black-forest-labs/flux.2-klein-4b,"
            "openrouter/openai/gpt-5-image-mini,"
            "openrouter/google/gemini-3.1-flash-image-preview,"
            "openrouter/sourceful/riverflow-v2-fast,"
            "openrouter/google/gemini-2.5-flash-image,"
            "fal/fal-ai/flux-2/klein/4b,"
            "fal/fal-ai/flux-2-pro,"
            "openai/gpt-image-1-mini,"
            "openai/gpt-image-1,"
            "google/gemini-3-pro-image-preview,"
            "google/gemini-3.1-flash-image-preview,"
            "google/gemini-2.5-flash-image"
        ),
    ).split(",")
    if m.strip()
]

# These models are required regardless of ALL_MODELS env overrides.
REQUIRED_OPENROUTER_MODELS: list[str] = [
    "openrouter/openai/gpt-5-image",
    "openrouter/sourceful/riverflow-v2-pro",
    "openrouter/sourceful/riverflow-v2-max-preview",
    "openrouter/black-forest-labs/flux.2-max",
    "openrouter/black-forest-labs/flux.2-flex",
    "openrouter/bytedance-seed/seedream-4.5",
    "openrouter/sourceful/riverflow-v2-standard-preview",
    "openrouter/black-forest-labs/flux.2-pro",
    "openrouter/sourceful/riverflow-v2-fast-preview",
    "openrouter/google/gemini-3-pro-image-preview",
    "openrouter/black-forest-labs/flux.2-klein-4b",
    "openrouter/openai/gpt-5-image-mini",
    "openrouter/google/gemini-3.1-flash-image-preview",
    "openrouter/sourceful/riverflow-v2-fast",
    "openrouter/google/gemini-2.5-flash-image",
]

REQUIRED_GEMINI_MODELS: list[str] = [
    "google/gemini-3-pro-image-preview",
    "google/gemini-3.1-flash-image-preview",
    "google/gemini-2.5-flash-image",
]

REQUIRED_MODELS_ORDER: list[str] = [*REQUIRED_OPENROUTER_MODELS, *REQUIRED_GEMINI_MODELS]

MODEL_PROVIDER_MAP: dict[str, str] = {
    "flux-2-pro": "openrouter",
    "flux-2-schnell": "openrouter",
    "gpt-image-1-high": "openai",
    "gpt-image-1-medium": "openai",
    "imagen-4-ultra": "google",
    "imagen-4-fast": "google",
    "nano-banana-pro": "openrouter",
    "openrouter/google/gemini-2.5-flash-image": "openrouter",
    "openrouter/google/gemini-3-pro-image-preview": "openrouter",
    "openrouter/google/gemini-3.1-flash-image-preview": "openrouter",
    "openrouter/openai/gpt-5-image-mini": "openrouter",
    "openrouter/openai/gpt-5-image": "openrouter",
    "openrouter/sourceful/riverflow-v2-pro": "openrouter",
    "openrouter/sourceful/riverflow-v2-max-preview": "openrouter",
    "openrouter/sourceful/riverflow-v2-standard-preview": "openrouter",
    "openrouter/sourceful/riverflow-v2-fast-preview": "openrouter",
    "openrouter/sourceful/riverflow-v2-fast": "openrouter",
    "openrouter/bytedance-seed/seedream-4.5": "openrouter",
    "openrouter/black-forest-labs/flux.2-max": "openrouter",
    "openrouter/black-forest-labs/flux.2-flex": "openrouter",
    "openrouter/black-forest-labs/flux.2-pro": "openrouter",
    "openrouter/black-forest-labs/flux.2-klein-4b": "openrouter",
    "fal/fal-ai/flux-2/klein/4b": "fal",
    "fal/fal-ai/flux-2": "fal",
    "fal/fal-ai/flux-2-pro": "fal",
    "openai/gpt-image-1-mini": "openai",
    "openai/gpt-image-1": "openai",
    "openai/gpt-image-1.5": "openai",
    "google/gemini-3-pro-image-preview": "google",
    "google/gemini-3.1-flash-image-preview": "google",
    "google/gemini-2.5-flash-image": "google",
    "google/imagen-4.0-fast-generate-001": "google",
    "google/imagen-4.0-generate-001": "google",
    "google/imagen-4.0-ultra-generate-001": "google",
}

MODEL_ALIAS_MAP: dict[str, str] = {
    "nano-banana-pro": "openrouter/google/gemini-3-pro-image-preview",
}

MODEL_COST_USD: dict[str, float] = {
    "flux-2-pro": 0.055,
    "flux-2-schnell": 0.003,
    "gpt-image-1-high": 0.167,
    "gpt-image-1-medium": 0.040,
    "imagen-4-ultra": 0.060,
    "imagen-4-fast": 0.030,
    "nano-banana-pro": 0.02,
    "openrouter/google/gemini-3-pro-image-preview": 0.02,
    "google/gemini-2.5-flash-image": 0.003,
    "google/gemini-3-pro-image-preview": 0.02,
    "google/gemini-3.1-flash-image-preview": 0.006,
    "openai/gpt-5-image-mini": 0.012,
    "openai/gpt-5-image": 0.04,
    "sourceful/riverflow-v2-pro": 0.05,
    "sourceful/riverflow-v2-max-preview": 0.06,
    "sourceful/riverflow-v2-standard-preview": 0.04,
    "sourceful/riverflow-v2-fast-preview": 0.03,
    "sourceful/riverflow-v2-fast": 0.02,
    "bytedance-seed/seedream-4.5": 0.04,
    "black-forest-labs/flux.2-max": 0.06,
    "black-forest-labs/flux.2-flex": 0.025,
    "black-forest-labs/flux.2-pro": 0.03,
    "black-forest-labs/flux.2-klein-4b": 0.014,
    "fal-ai/flux-2/klein/4b": 0.0025,
    "fal-ai/flux-2": 0.012,
    "fal-ai/flux-2-pro": 0.045,
    "gpt-image-1-mini": 0.01,
    "gpt-image-1": 0.04,
    "gpt-image-1.5": 0.06,
    "imagen-4.0-fast-generate-001": 0.03,
    "imagen-4.0-generate-001": 0.06,
    "imagen-4.0-ultra-generate-001": 0.08,
}

_RUNTIME_MODEL_COST_USD: dict[str, float] = MODEL_COST_USD.copy()
_RUNTIME_MODEL_COST_LOCK = threading.Lock()
_OPENROUTER_PRICING_SYNC_THREAD: threading.Thread | None = None
_OPENROUTER_PRICING_SYNC_STARTED = False
_OPENROUTER_PRICING_SYNC_STATE: dict[str, Any] = {
    "ok": False,
    "skipped": True,
    "reason": "not_started",
    "updated": 0,
    "last_synced_at": "",
    "error": "",
}

MODEL_MODALITY: dict[str, str] = {
    "openrouter/openai/gpt-5-image": "both",
    "openrouter/sourceful/riverflow-v2-pro": "image",
    "openrouter/sourceful/riverflow-v2-max-preview": "image",
    "openrouter/black-forest-labs/flux.2-max": "image",
    "openrouter/black-forest-labs/flux.2-flex": "image",
    "openrouter/bytedance-seed/seedream-4.5": "image",
    "openrouter/sourceful/riverflow-v2-standard-preview": "image",
    "openrouter/black-forest-labs/flux.2-pro": "image",
    "openrouter/sourceful/riverflow-v2-fast-preview": "image",
    "openrouter/google/gemini-3-pro-image-preview": "both",
    "openrouter/black-forest-labs/flux.2-klein-4b": "image",
    "openrouter/openai/gpt-5-image-mini": "both",
    "openrouter/google/gemini-3.1-flash-image-preview": "both",
    "openrouter/sourceful/riverflow-v2-fast": "image",
    "openrouter/google/gemini-2.5-flash-image": "both",
    # Normalized provider model ids.
    "openai/gpt-5-image": "both",
    "sourceful/riverflow-v2-pro": "image",
    "sourceful/riverflow-v2-max-preview": "image",
    "black-forest-labs/flux.2-max": "image",
    "black-forest-labs/flux.2-flex": "image",
    "bytedance-seed/seedream-4.5": "image",
    "sourceful/riverflow-v2-standard-preview": "image",
    "black-forest-labs/flux.2-pro": "image",
    "sourceful/riverflow-v2-fast-preview": "image",
    "google/gemini-3-pro-image-preview": "both",
    "black-forest-labs/flux.2-klein-4b": "image",
    "openai/gpt-5-image-mini": "both",
    "google/gemini-3.1-flash-image-preview": "both",
    "sourceful/riverflow-v2-fast": "image",
    "google/gemini-2.5-flash-image": "both",
}

VARIANTS_PER_COVER = int(os.getenv("VARIANTS_PER_COVER", "5"))
MAX_GENERATION_VARIANTS = int(os.getenv("MAX_GENERATION_VARIANTS", "50"))
BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "5"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
PROVIDER_CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("PROVIDER_CIRCUIT_FAILURE_THRESHOLD", "3"))
PROVIDER_CIRCUIT_COOLDOWN_SECONDS = float(os.getenv("PROVIDER_CIRCUIT_COOLDOWN_SECONDS", "90"))

PROVIDER_REQUEST_DELAY = {
    "openrouter": float(os.getenv("OPENROUTER_REQUEST_DELAY", str(REQUEST_DELAY))),
    "fal": float(os.getenv("FAL_REQUEST_DELAY", str(REQUEST_DELAY))),
    "replicate": float(os.getenv("REPLICATE_REQUEST_DELAY", str(REQUEST_DELAY))),
    "openai": float(os.getenv("OPENAI_REQUEST_DELAY", str(REQUEST_DELAY))),
    "google": float(os.getenv("GOOGLE_REQUEST_DELAY", str(REQUEST_DELAY))),
}

RATE_LIMITS_PER_SECOND = {
    "openrouter": int(os.getenv("RATE_LIMIT_OPENROUTER", "10")),
    "fal": int(os.getenv("RATE_LIMIT_FAL", "5")),
    "replicate": int(os.getenv("RATE_LIMIT_REPLICATE", "10")),
    "google": int(os.getenv("RATE_LIMIT_GOOGLE", "5")),
    # OpenAI image generation is mainly minute-bounded in this project.
    "openai": int(os.getenv("RATE_LIMIT_OPENAI_PER_SECOND", "0")),
}

RATE_LIMITS_PER_MINUTE = {
    "openrouter": int(os.getenv("RATE_LIMIT_OPENROUTER_PER_MIN", "200")),
    "openai": int(os.getenv("RATE_LIMIT_OPENAI", "5")),
    "fal": int(os.getenv("RATE_LIMIT_FAL_PER_MIN", "0")),
    "replicate": int(os.getenv("RATE_LIMIT_REPLICATE_PER_MIN", "0")),
    "google": int(os.getenv("RATE_LIMIT_GOOGLE_PER_MIN", "0")),
}

GEN_WIDTH = int(os.getenv("GEN_WIDTH", "1024"))
GEN_HEIGHT = int(os.getenv("GEN_HEIGHT", "1024"))
GEN_OUTPUT_FORMAT = os.getenv("GEN_OUTPUT_FORMAT", "png").strip().lower()

MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "0.6"))
MAX_COST_USD = float(os.getenv("BUDGET_LIMIT_USD", os.getenv("MAX_COST_USD", "200.00")))

BOOK_SCOPE_LIMIT = int(os.getenv("BOOK_SCOPE_LIMIT", "20"))
MAX_EXPORT_VARIANTS = int(os.getenv("MAX_EXPORT_VARIANTS", "20"))
COMPOSITE_MAX_INVALID_VARIANTS = int(os.getenv("COMPOSITE_MAX_INVALID_VARIANTS", "0"))
BORDER_STRIP_PERCENT = float(os.getenv("BORDER_STRIP_PERCENT", "0.05"))
SLO_WINDOW_DAYS = int(os.getenv("SLO_WINDOW_DAYS", "7"))
SLO_ALERT_COOLDOWN_SECONDS = int(os.getenv("SLO_ALERT_COOLDOWN_SECONDS", "900"))
SLO_ALERT_LEVELS = [
    token.strip().lower() for token in os.getenv("SLO_ALERT_LEVELS", "breached,at_risk").split(",") if token.strip()
]
SLO_MONITOR_INTERVAL_SECONDS = int(os.getenv("SLO_MONITOR_INTERVAL_SECONDS", "300"))
JOB_WORKERS = int(os.getenv("JOB_WORKERS", "2"))
JOB_WORKER_MODE = os.getenv("JOB_WORKER_MODE", "inline").strip().lower() or "inline"
JOB_WORKER_HEARTBEAT_PATH = PROJECT_ROOT / os.getenv("JOB_WORKER_HEARTBEAT_PATH", "data/worker_heartbeat.json")
JOB_WORKER_HEARTBEAT_STALE_SECONDS = int(os.getenv("JOB_WORKER_HEARTBEAT_STALE_SECONDS", "120"))
ALLOW_SYNC_GENERATION = os.getenv("ALLOW_SYNC_GENERATION", "0").strip().lower() in {"1", "true", "yes", "on"}
JOB_STALE_RECOVERY_SECONDS = int(os.getenv("JOB_STALE_RECOVERY_SECONDS", "900"))
JOB_STALE_RECOVERY_RETRY_DELAY_SECONDS = float(os.getenv("JOB_STALE_RECOVERY_RETRY_DELAY_SECONDS", "2.0"))

FAILURES_PATH = DATA_DIR / "generation_failures.json"
GENERATION_PLAN_PATH = DATA_DIR / "generation_plan.json"
GENERATION_STATE_PATH = DATA_DIR / "generation_state.json"
STATE_DB_PATH = DATA_DIR / os.getenv("STATE_DB_PATH", "state.sqlite3")
USE_SQLITE = os.getenv("USE_SQLITE", "0").strip().lower() in {"1", "true", "yes", "on"}
SQLITE_DB_PATH = DATA_DIR / os.getenv("SQLITE_DB_PATH", "alexandria.db")


@dataclass(slots=True)
class CatalogConfig:
    id: str
    name: str
    book_count: int
    catalog_file: Path
    prompts_file: Path
    input_covers_dir: Path
    output_covers_dir: Path
    cover_style: str = "navy_gold_medallion"
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "book_count": self.book_count,
            "catalog_file": str(self.catalog_file),
            "prompts_file": str(self.prompts_file),
            "input_covers_dir": str(self.input_covers_dir),
            "output_covers_dir": str(self.output_covers_dir),
            "cover_style": self.cover_style,
            "status": self.status,
        }


def ensure_runtime_dirs() -> None:
    """Ensure runtime directories exist."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(
        "Ensured runtime directories",
        extra={"tmp_dir": str(TMP_DIR), "data_dir": str(DATA_DIR), "config_dir": str(CONFIG_DIR)},
    )


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_project_path(token: str | Path) -> Path:
    path = Path(token)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _catalog_book_count(token: str | Path) -> int:
    payload = _load_json(_resolve_project_path(token))
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        rows = payload.get("books")
        if isinstance(rows, list):
            return len(rows)
    return 0


def _sanitize_all_models(models: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in models:
        token = str(raw or "").strip()
        if not token:
            continue
        if token.lower().startswith("replicate/"):
            continue
        if token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def _default_catalog_payload() -> dict[str, Any]:
    default_catalog_file = "config/book_catalog.json"
    return {
        "catalogs": [
            {
                "id": "classics",
                "name": "Alexandria Classics",
                "book_count": _catalog_book_count(default_catalog_file),
                "catalog_file": default_catalog_file,
                "prompts_file": "config/book_prompts.json",
                "input_covers_dir": "Input Covers",
                "output_covers_dir": "Output Covers",
                "cover_style": "navy_gold_medallion",
                "status": "complete",
            }
        ]
    }


def _load_catalogs_payload() -> dict[str, Any]:
    payload = _load_json(CATALOGS_PATH)
    if isinstance(payload, dict):
        rows = payload.get("catalogs")
        if isinstance(rows, list):
            return payload
        if isinstance(rows, dict):
            normalized_rows: list[dict[str, Any]] = []
            for key, value in rows.items():
                if not isinstance(value, dict):
                    continue
                entry = dict(value)
                entry.setdefault("id", str(key))
                normalized_rows.append(entry)
            return {
                "catalogs": normalized_rows,
                "default_catalog": str(payload.get("default_catalog", DEFAULT_CATALOG_ID)),
            }
    return _default_catalog_payload()


def list_catalogs() -> list[CatalogConfig]:
    payload = _load_catalogs_payload()
    rows = payload.get("catalogs", []) if isinstance(payload, dict) else []
    catalogs: list[CatalogConfig] = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        catalog_id = str(row.get("id", "")).strip()
        if not catalog_id:
            continue

        catalog_file = _resolve_project_path(str(row.get("catalog_file", "config/book_catalog.json")))
        prompts_file = _resolve_project_path(str(row.get("prompts_file", "config/book_prompts.json")))
        input_covers_dir = _resolve_project_path(str(row.get("input_covers_dir", "Input Covers")))
        output_covers_dir = _resolve_project_path(str(row.get("output_covers_dir", "Output Covers")))
        book_count = _catalog_book_count(catalog_file)
        if book_count <= 0:
            book_count = int(row.get("book_count", 0) or 0)

        catalogs.append(
            CatalogConfig(
                id=catalog_id,
                name=str(row.get("name", catalog_id)),
                book_count=book_count,
                catalog_file=catalog_file,
                prompts_file=prompts_file,
                input_covers_dir=input_covers_dir,
                output_covers_dir=output_covers_dir,
                cover_style=str(row.get("cover_style", "navy_gold_medallion") or "navy_gold_medallion"),
                status=str(row.get("status", "active") or "active"),
            )
        )

    if catalogs:
        return catalogs

    fallback = _default_catalog_payload()["catalogs"][0]
    return [
        CatalogConfig(
            id=str(fallback["id"]),
            name=str(fallback["name"]),
            book_count=int(fallback["book_count"]),
            catalog_file=_resolve_project_path(str(fallback["catalog_file"])),
            prompts_file=_resolve_project_path(str(fallback["prompts_file"])),
            input_covers_dir=_resolve_project_path(str(fallback["input_covers_dir"])),
            output_covers_dir=_resolve_project_path(str(fallback["output_covers_dir"])),
            cover_style=str(fallback["cover_style"]),
            status=str(fallback["status"]),
        )
    ]


def get_catalog(catalog_id: str) -> CatalogConfig:
    wanted = str(catalog_id or "").strip().lower()
    if not wanted:
        raise KeyError("catalog_id is empty")

    for catalog in list_catalogs():
        if catalog.id.lower() == wanted:
            return catalog

    available = ", ".join(sorted(catalog.id for catalog in list_catalogs()))
    raise KeyError(f"Catalog '{catalog_id}' not found. Available: {available}")


def resolve_catalog(catalog_id: str | None = None) -> CatalogConfig:
    wanted = (catalog_id or DEFAULT_CATALOG_ID).strip() if catalog_id is not None else DEFAULT_CATALOG_ID
    catalogs = list_catalogs()
    if wanted:
        for catalog in catalogs:
            if catalog.id.lower() == wanted.lower():
                return catalog
    return catalogs[0]


def load_cover_templates(path: Path | None = None) -> dict[str, Any]:
    templates_path = path or COVER_TEMPLATES_PATH
    payload = _load_json(templates_path)
    if isinstance(payload, dict) and isinstance(payload.get("templates"), list):
        return payload
    return {
        "templates": [
            {
                "id": "navy_gold_medallion",
                "description": "Navy background, gold ornaments, circular medallion center-right",
                "region_type": "circle",
                "compositing": "raster_first",
            }
        ]
    }


def _catalog_token(catalog_id: str | None) -> str:
    token = str(catalog_id or DEFAULT_CATALOG_ID).strip().lower()
    if token:
        token = re.sub(r"[^a-z0-9_-]+", "-", token).strip("-_")
        token = token[:120]
    return token or DEFAULT_CATALOG_ID


def catalog_scoped_config_path(filename: str, *, catalog_id: str | None = None, config_dir: Path | None = None) -> Path:
    """Return a catalog-scoped config path (classics keeps unsuffixed legacy name)."""
    root = config_dir or CONFIG_DIR
    name = Path(filename).name
    token = _catalog_token(catalog_id)
    if token == "classics":
        return root / name
    stem = Path(name).stem
    suffix = Path(name).suffix
    return root / f"{stem}_{token}{suffix}"


def catalog_scoped_data_path(filename: str, *, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    """Return a catalog-scoped data path (classics keeps unsuffixed legacy name)."""
    root = data_dir or DATA_DIR
    name = Path(filename).name
    token = _catalog_token(catalog_id)
    if token == "classics":
        return root / name
    stem = Path(name).stem
    suffix = Path(name).suffix
    return root / f"{stem}_{token}{suffix}"


def cover_regions_path(*, catalog_id: str | None = None, config_dir: Path | None = None) -> Path:
    return catalog_scoped_config_path("cover_regions.json", catalog_id=catalog_id, config_dir=config_dir)


def enriched_catalog_path(*, catalog_id: str | None = None, config_dir: Path | None = None) -> Path:
    return catalog_scoped_config_path("book_catalog_enriched.json", catalog_id=catalog_id, config_dir=config_dir)


def intelligent_prompts_path(*, catalog_id: str | None = None, config_dir: Path | None = None) -> Path:
    return catalog_scoped_config_path("book_prompts_intelligent.json", catalog_id=catalog_id, config_dir=config_dir)


def winner_selections_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("winner_selections.json", catalog_id=catalog_id, data_dir=data_dir)


def archive_log_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("archive_log.json", catalog_id=catalog_id, data_dir=data_dir)


def quality_scores_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("quality_scores.json", catalog_id=catalog_id, data_dir=data_dir)


def generation_history_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("generation_history.json", catalog_id=catalog_id, data_dir=data_dir)


def regeneration_results_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("regeneration_results.json", catalog_id=catalog_id, data_dir=data_dir)


def prompt_performance_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("prompt_performance.json", catalog_id=catalog_id, data_dir=data_dir)


def llm_usage_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("llm_usage.json", catalog_id=catalog_id, data_dir=data_dir)


def audit_log_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("audit_log.json", catalog_id=catalog_id, data_dir=data_dir)


def error_metrics_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("error_metrics.json", catalog_id=catalog_id, data_dir=data_dir)


def cost_ledger_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("cost_ledger.json", catalog_id=catalog_id, data_dir=data_dir)


def budget_config_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("budget_config.json", catalog_id=catalog_id, data_dir=data_dir)


def delivery_config_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("delivery_pipeline.json", catalog_id=catalog_id, data_dir=data_dir)


def delivery_tracking_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("delivery_tracking.json", catalog_id=catalog_id, data_dir=data_dir)


def report_schedules_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("report_schedules.json", catalog_id=catalog_id, data_dir=data_dir)


def slo_metrics_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("slo_metrics.json", catalog_id=catalog_id, data_dir=data_dir)


def slo_alert_state_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("slo_alert_state.json", catalog_id=catalog_id, data_dir=data_dir)


def review_data_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("review_data.json", catalog_id=catalog_id, data_dir=data_dir)


def iterate_data_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("iterate_data.json", catalog_id=catalog_id, data_dir=data_dir)


def compare_data_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("compare_data.json", catalog_id=catalog_id, data_dir=data_dir)


def variant_selections_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("variant_selections.json", catalog_id=catalog_id, data_dir=data_dir)


def review_stats_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("review_stats.json", catalog_id=catalog_id, data_dir=data_dir)


def similarity_hashes_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("cover_hashes.json", catalog_id=catalog_id, data_dir=data_dir)


def similarity_matrix_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("similarity_matrix.json", catalog_id=catalog_id, data_dir=data_dir)


def similarity_clusters_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("similarity_clusters.json", catalog_id=catalog_id, data_dir=data_dir)


def similarity_dismissed_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("similarity_dismissed.json", catalog_id=catalog_id, data_dir=data_dir)


def drive_sync_log_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("drive_sync_log.json", catalog_id=catalog_id, data_dir=data_dir)


def drive_schedule_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("drive_schedule.json", catalog_id=catalog_id, data_dir=data_dir)


def batch_runs_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("batch_runs.json", catalog_id=catalog_id, data_dir=data_dir)


def exports_manifest_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("exports_manifest.json", catalog_id=catalog_id, data_dir=data_dir)


def pipeline_state_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("pipeline_state.json", catalog_id=catalog_id, data_dir=data_dir)


def pipeline_summary_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("pipeline_summary.json", catalog_id=catalog_id, data_dir=data_dir)


def pipeline_summary_markdown_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("pipeline_summary.md", catalog_id=catalog_id, data_dir=data_dir)


def gdrive_sync_state_path(*, catalog_id: str | None = None, data_dir: Path | None = None) -> Path:
    return catalog_scoped_data_path("gdrive_sync_state.json", catalog_id=catalog_id, data_dir=data_dir)


def get_initial_scope_book_numbers(limit: int | None = None, *, catalog_id: str | None = None) -> list[int]:
    """Return the first N book numbers from catalog for D23 scope."""
    catalog_cfg = resolve_catalog(catalog_id)
    payload = _load_json(catalog_cfg.catalog_file)
    if not isinstance(payload, list):
        return []

    max_items = limit if limit is not None else BOOK_SCOPE_LIMIT
    values: list[int] = []
    for entry in payload:
        number = entry.get("number")
        if isinstance(number, int):
            values.append(number)
        elif isinstance(number, str) and number.isdigit():
            values.append(int(number))
        if len(values) >= max_items:
            break
    return values


@dataclass(slots=True)
class Config:
    """Typed runtime configuration snapshot."""

    project_root: Path = PROJECT_ROOT
    input_dir: Path = INPUT_DIR
    output_dir: Path = OUTPUT_DIR
    tmp_dir: Path = TMP_DIR
    data_dir: Path = DATA_DIR
    config_dir: Path = CONFIG_DIR

    prompts_path: Path = PROMPTS_PATH
    book_catalog_path: Path = BOOK_CATALOG_PATH
    prompt_templates_path: Path = PROMPT_TEMPLATES_PATH
    prompt_library_path: Path = PROMPT_LIBRARY_PATH
    catalogs_path: Path = CATALOGS_PATH
    cover_templates_path: Path = COVER_TEMPLATES_PATH
    model_prompt_overrides_path: Path = MODEL_PROMPT_OVERRIDES_PATH

    catalog_id: str = DEFAULT_CATALOG_ID
    catalog_name: str = "Alexandria Classics"
    cover_style: str = "navy_gold_medallion"

    ai_provider: str = AI_PROVIDER
    ai_model: str = AI_MODEL
    all_models: list[str] = field(default_factory=lambda: ALL_MODELS.copy())

    openrouter_api_key: str = OPENROUTER_API_KEY
    fal_api_key: str = FAL_API_KEY
    replicate_api_token: str = REPLICATE_API_TOKEN
    openai_api_key: str = OPENAI_API_KEY
    google_api_key: str = GOOGLE_API_KEY
    google_credentials_json: str = GOOGLE_CREDENTIALS_JSON
    anthropic_api_key: str = ANTHROPIC_API_KEY
    llm_provider: str = LLM_PROVIDER
    llm_model: str = LLM_MODEL
    llm_max_tokens: int = LLM_MAX_TOKENS
    llm_cost_per_1k_tokens: float = LLM_COST_PER_1K_TOKENS
    gdrive_output_folder_id: str = GDRIVE_OUTPUT_FOLDER_ID
    gdrive_source_folder_id: str = GDRIVE_SOURCE_FOLDER_ID
    gdrive_input_folder_id: str = GDRIVE_INPUT_FOLDER_ID
    gdrive_mockups_folder_id: str = GDRIVE_MOCKUPS_FOLDER_ID
    gdrive_amazon_folder_id: str = GDRIVE_AMAZON_FOLDER_ID
    gdrive_social_folder_id: str = GDRIVE_SOCIAL_FOLDER_ID
    google_credentials_path: str = GOOGLE_CREDENTIALS_PATH

    webhook_url: str = WEBHOOK_URL
    webhook_events: list[str] = field(default_factory=lambda: WEBHOOK_EVENTS.copy())
    outbound_allowlist_domains: list[str] = field(default_factory=lambda: OUTBOUND_ALLOWLIST_DOMAINS.copy())

    request_delay: float = REQUEST_DELAY
    max_retries: int = MAX_RETRIES
    provider_circuit_failure_threshold: int = PROVIDER_CIRCUIT_FAILURE_THRESHOLD
    provider_circuit_cooldown_seconds: float = PROVIDER_CIRCUIT_COOLDOWN_SECONDS
    batch_concurrency: int = BATCH_CONCURRENCY
    variants_per_cover: int = VARIANTS_PER_COVER
    max_generation_variants: int = MAX_GENERATION_VARIANTS
    provider_request_delay: dict[str, float] = field(default_factory=lambda: PROVIDER_REQUEST_DELAY.copy())
    provider_rate_limit_per_second: dict[str, int] = field(default_factory=lambda: RATE_LIMITS_PER_SECOND.copy())
    provider_rate_limit_per_minute: dict[str, int] = field(default_factory=lambda: RATE_LIMITS_PER_MINUTE.copy())

    image_width: int = GEN_WIDTH
    image_height: int = GEN_HEIGHT
    image_output_format: str = GEN_OUTPUT_FORMAT

    min_quality_score: float = MIN_QUALITY_SCORE
    max_cost_usd: float = MAX_COST_USD

    model_provider_map: dict[str, str] = field(default_factory=lambda: MODEL_PROVIDER_MAP.copy())
    model_alias_map: dict[str, str] = field(default_factory=lambda: MODEL_ALIAS_MAP.copy())
    model_cost_usd: dict[str, float] = field(default_factory=lambda: runtime_model_costs_copy())
    model_modality: dict[str, str] = field(default_factory=lambda: MODEL_MODALITY.copy())

    failures_path: Path = FAILURES_PATH
    generation_plan_path: Path = GENERATION_PLAN_PATH
    generation_state_path: Path = GENERATION_STATE_PATH
    state_db_path: Path = STATE_DB_PATH
    use_sqlite: bool = USE_SQLITE
    sqlite_db_path: Path = SQLITE_DB_PATH

    book_scope_limit: int = BOOK_SCOPE_LIMIT
    max_export_variants: int = MAX_EXPORT_VARIANTS
    composite_max_invalid_variants: int = COMPOSITE_MAX_INVALID_VARIANTS
    border_strip_percent: float = BORDER_STRIP_PERCENT
    slo_window_days: int = SLO_WINDOW_DAYS
    slo_alert_cooldown_seconds: int = SLO_ALERT_COOLDOWN_SECONDS
    slo_alert_levels: list[str] = field(default_factory=lambda: SLO_ALERT_LEVELS.copy())
    slo_monitor_interval_seconds: int = SLO_MONITOR_INTERVAL_SECONDS
    job_workers: int = JOB_WORKERS
    job_worker_mode: str = JOB_WORKER_MODE
    job_worker_heartbeat_path: Path = JOB_WORKER_HEARTBEAT_PATH
    job_worker_heartbeat_stale_seconds: int = JOB_WORKER_HEARTBEAT_STALE_SECONDS
    allow_sync_generation: bool = ALLOW_SYNC_GENERATION
    job_stale_recovery_seconds: int = JOB_STALE_RECOVERY_SECONDS
    job_stale_recovery_retry_delay_seconds: float = JOB_STALE_RECOVERY_RETRY_DELAY_SECONDS

    # Compatibility aliases
    input_covers_dir: Path = INPUT_DIR
    output_covers_dir: Path = OUTPUT_DIR
    cost_per_image_usd: float = field(default_factory=lambda: runtime_model_costs_copy().get(AI_MODEL, 0.04))

    @property
    def provider_keys(self) -> dict[str, str]:
        return {
            "openrouter": self.openrouter_api_key,
            "fal": self.fal_api_key,
            "openai": self.openai_api_key,
            "google": self.google_api_key,
        }

    def has_any_api_key(self) -> bool:
        return any(bool(v.strip()) for v in self.provider_keys.values())

    def get_api_key(self, provider: str) -> str:
        return self.provider_keys.get(provider.lower(), "")

    def resolve_model_provider(self, model: str, default_provider: str | None = None) -> str:
        """Resolve provider for a model, supporting provider/model notation."""
        alias = self.model_alias_map.get(str(model or "").strip(), str(model or "").strip())
        model = alias or model
        if "/" in model:
            prefix = model.split("/", 1)[0].strip().lower()
            if prefix in self.provider_keys:
                return prefix
        return self.model_provider_map.get(model, (default_provider or self.ai_provider).lower())

    def resolve_model_alias(self, model: str) -> str:
        token = str(model or "").strip()
        if not token:
            return ""
        return str(self.model_alias_map.get(token, token)).strip()

    def get_model_cost(self, model: str) -> float:
        normalized = model.split("/", 1)[-1] if "/" in model else model
        return float(self.model_cost_usd.get(normalized, self.model_cost_usd.get(model, 0.04)))

    def get_model_modality(self, model: str) -> str:
        token = str(model or "").strip()
        normalized = token.split("/", 1)[-1] if "/" in token else token
        values = [
            self.model_modality.get(token),
            self.model_modality.get(normalized),
            self.model_modality.get(f"openrouter/{normalized}"),
        ]
        for item in values:
            if str(item or "").strip().lower() in {"both", "image"}:
                return str(item).strip().lower()
        return "image"


RuntimeConfig = Config


def runtime_model_costs_copy() -> dict[str, float]:
    with _RUNTIME_MODEL_COST_LOCK:
        return dict(_RUNTIME_MODEL_COST_USD)


def openrouter_pricing_sync_status() -> dict[str, Any]:
    with _RUNTIME_MODEL_COST_LOCK:
        return dict(_OPENROUTER_PRICING_SYNC_STATE)


def _coerce_price_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _extract_openrouter_image_price(model_payload: dict[str, Any]) -> float | None:
    pricing = model_payload.get("pricing", {})
    if isinstance(pricing, dict):
        for key in ("image", "per_image"):
            parsed = _coerce_price_value(pricing.get(key))
            if parsed is not None:
                return parsed
        for key in ("per_megapixel", "megapixel", "image_per_megapixel"):
            parsed = _coerce_price_value(pricing.get(key))
            if parsed is not None:
                return parsed
    for key in ("per_image", "image_price", "price_per_image", "price_per_megapixel"):
        parsed = _coerce_price_value(model_payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _openrouter_cost_keys(model_id: str) -> set[str]:
    token = str(model_id or "").strip()
    if not token:
        return set()
    keys = {token, f"openrouter/{token}"}
    for alias, resolved in MODEL_ALIAS_MAP.items():
        if str(resolved).strip() == f"openrouter/{token}":
            keys.add(str(alias).strip())
    return {key for key in keys if key}


def sync_openrouter_pricing(*, api_key: str | None = None, session: Any = requests) -> dict[str, Any]:
    key = str(api_key or OPENROUTER_API_KEY or "").strip()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not key:
        state = {
            "ok": False,
            "skipped": True,
            "reason": "missing_api_key",
            "updated": 0,
            "last_synced_at": now,
            "error": "",
        }
        with _RUNTIME_MODEL_COST_LOCK:
            _OPENROUTER_PRICING_SYNC_STATE.update(state)
        return dict(state)

    try:
        response = session.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover - network failure
        message = f"OpenRouter pricing sync error: {exc}"
        logger.warning(message)
        state = {
            "ok": False,
            "skipped": False,
            "reason": "request_error",
            "updated": 0,
            "last_synced_at": now,
            "error": str(exc),
        }
        with _RUNTIME_MODEL_COST_LOCK:
            _OPENROUTER_PRICING_SYNC_STATE.update(state)
        return dict(state)

    if getattr(response, "status_code", 0) != 200:
        message = getattr(response, "text", "") or f"HTTP {getattr(response, 'status_code', 0)}"
        logger.warning("OpenRouter pricing sync failed: %s", message[:240])
        state = {
            "ok": False,
            "skipped": False,
            "reason": "http_error",
            "updated": 0,
            "last_synced_at": now,
            "error": message[:240],
        }
        with _RUNTIME_MODEL_COST_LOCK:
            _OPENROUTER_PRICING_SYNC_STATE.update(state)
        return dict(state)

    payload = response.json()
    models = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(models, list):
        models = []

    canonical_updates: dict[str, tuple[float, float]] = {}
    with _RUNTIME_MODEL_COST_LOCK:
        runtime_costs = dict(_RUNTIME_MODEL_COST_USD)
        for row in models:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id", "") or "").strip()
            if not model_id:
                continue
            price = _extract_openrouter_image_price(row)
            if price is None:
                continue
            keys = _openrouter_cost_keys(model_id)
            if not any(key in runtime_costs or key in MODEL_COST_USD for key in keys):
                continue
            baseline_candidates = [
                float(runtime_costs.get(key, 0.0) or 0.0)
                for key in keys
                if float(runtime_costs.get(key, 0.0) or 0.0) > 0
            ]
            baseline_candidates.extend(
                float(MODEL_COST_USD.get(key, 0.0) or 0.0)
                for key in keys
                if float(MODEL_COST_USD.get(key, 0.0) or 0.0) > 0
            )
            baseline = max(baseline_candidates) if baseline_candidates else 0.0
            if baseline >= 0.001 and price < (baseline * 0.1):
                logger.warning(
                    "Ignoring suspiciously low OpenRouter image price for %s: %.6f (baseline %.6f)",
                    model_id,
                    price,
                    baseline,
                )
                continue
            for key in keys:
                old = runtime_costs.get(key, MODEL_COST_USD.get(key))
                runtime_costs[key] = price
                if old is not None and abs(float(old) - price) >= 1e-9 and key in {model_id, f"openrouter/{model_id}"}:
                    canonical_updates[key] = (float(old), price)
        _RUNTIME_MODEL_COST_USD.clear()
        _RUNTIME_MODEL_COST_USD.update(runtime_costs)
        _OPENROUTER_PRICING_SYNC_STATE.update(
            {
                "ok": True,
                "skipped": False,
                "reason": "",
                "updated": len(canonical_updates),
                "last_synced_at": now,
                "error": "",
            }
        )

    for model_name, values in sorted(canonical_updates.items()):
        old, new = values
        logger.info("Price update: %s changed from $%.3f to $%.3f per image", model_name, old, new)
    return openrouter_pricing_sync_status()


def start_openrouter_pricing_sync(*, api_key: str | None = None, interval_seconds: int = OPENROUTER_PRICING_SYNC_INTERVAL_SECONDS) -> bool:
    global _OPENROUTER_PRICING_SYNC_THREAD, _OPENROUTER_PRICING_SYNC_STARTED
    key = str(api_key or OPENROUTER_API_KEY or "").strip()
    if not key or _OPENROUTER_PRICING_SYNC_STARTED:
        return False

    period = max(300, int(interval_seconds or OPENROUTER_PRICING_SYNC_INTERVAL_SECONDS))

    def _worker() -> None:
        while True:
            try:
                sync_openrouter_pricing(api_key=key)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("OpenRouter pricing background sync crashed: %s", exc)
            time.sleep(period)

    _OPENROUTER_PRICING_SYNC_THREAD = threading.Thread(
        target=_worker,
        name="openrouter-pricing-sync",
        daemon=True,
    )
    _OPENROUTER_PRICING_SYNC_THREAD.start()
    _OPENROUTER_PRICING_SYNC_STARTED = True
    return True


def get_config(catalog_id: str | None = None) -> Config:
    ensure_runtime_dirs()
    cfg = Config()
    cfg.model_cost_usd = runtime_model_costs_copy()
    cfg.all_models = _sanitize_all_models(cfg.all_models)
    for model in REQUIRED_MODELS_ORDER:
        if model not in cfg.all_models:
            cfg.all_models.append(model)
    ordered_models: list[str] = []
    seen_models: set[str] = set()
    for model in [*REQUIRED_MODELS_ORDER, *cfg.all_models]:
        token = str(model or "").strip()
        if not token or token in seen_models:
            continue
        seen_models.add(token)
        ordered_models.append(token)
    cfg.all_models = ordered_models
    if str(cfg.ai_model or "").strip().lower().startswith("replicate/"):
        cfg.ai_model = cfg.all_models[0] if cfg.all_models else ""
    cfg.cost_per_image_usd = cfg.get_model_cost(cfg.ai_model)
    cfg.variants_per_cover = max(1, int(cfg.variants_per_cover or 1))
    cfg.max_generation_variants = max(cfg.variants_per_cover, int(cfg.max_generation_variants or cfg.variants_per_cover))
    cfg.max_export_variants = max(1, int(cfg.max_export_variants or 1))
    cfg.composite_max_invalid_variants = max(0, int(cfg.composite_max_invalid_variants or 0))
    cfg.border_strip_percent = max(0.0, min(0.20, float(cfg.border_strip_percent or 0.0)))

    try:
        catalog = resolve_catalog(catalog_id)
        cfg.catalog_id = catalog.id
        cfg.catalog_name = catalog.name
        cfg.cover_style = catalog.cover_style
        cfg.book_catalog_path = catalog.catalog_file
        cfg.prompts_path = catalog.prompts_file
        cfg.input_dir = catalog.input_covers_dir
        cfg.output_dir = catalog.output_covers_dir
        cfg.input_covers_dir = catalog.input_covers_dir
        cfg.output_covers_dir = catalog.output_covers_dir
    except Exception as exc:
        logger.warning("Falling back to default catalog paths: %s", exc)

    logger.debug(
        "Loaded runtime configuration snapshot",
        extra={
            "provider": cfg.ai_provider,
            "model": cfg.ai_model,
            "models": cfg.all_models,
            "catalog_id": cfg.catalog_id,
            "catalog": cfg.catalog_name,
        },
    )
    return cfg
