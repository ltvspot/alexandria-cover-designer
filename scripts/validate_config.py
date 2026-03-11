#!/usr/bin/env python3
"""Validate environment/config prerequisites for Alexandria pipeline."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src import config
    from src import pipeline
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    from src import config  # type: ignore
    from src import pipeline  # type: ignore
    from src.logger import get_logger  # type: ignore

logger = get_logger(__name__)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _count_book_folders(path: Path) -> int:
    if not path.exists():
        return 0
    return len([p for p in path.iterdir() if p.is_dir() and p.name != "Archive"])


def _requirement_packages(requirements_path: Path) -> list[str]:
    packages: list[str] = []
    if not requirements_path.exists():
        return packages
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if not token or token.startswith("#"):
            continue
        name = token.split(";", 1)[0].split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0].strip()
        if name:
            packages.append(name)
    return packages


def run_checks() -> list[dict[str, Any]]:
    runtime = config.get_config()
    checks: list[dict[str, Any]] = []
    expected_catalog_count = 0
    try:
        expected_catalog_count = max(0, int(config.resolve_catalog(runtime.catalog_id).book_count or 0))
    except Exception:
        expected_catalog_count = 0

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    env_path = runtime.project_root / ".env"
    add(".env exists", env_path.exists(), str(env_path))

    # API key validation
    providers_with_keys = [provider for provider, key in runtime.provider_keys.items() if key.strip()]
    if providers_with_keys:
        report = pipeline.test_api_keys(runtime=runtime, providers=providers_with_keys)
        failed = [row for row in report.get("providers", []) if row.get("status") != "KEY_VALID"]
        add("API keys valid (configured providers)", len(failed) == 0, json.dumps(report.get("providers", []), ensure_ascii=False))
    else:
        add("API keys valid (configured providers)", False, "No provider keys configured")

    # Catalog count
    try:
        catalog = _load_json(runtime.book_catalog_path)
        catalog_count = len(catalog) if isinstance(catalog, list) else 0
        count_ok = catalog_count > 0 if expected_catalog_count <= 0 else catalog_count == expected_catalog_count
        expected_label = f"expected={expected_catalog_count}" if expected_catalog_count > 0 else "expected=>0"
        add(
            "book_catalog entry count matches catalog config",
            isinstance(catalog, list) and count_ok,
            f"count={catalog_count}; {expected_label}",
        )
    except Exception as exc:
        add("book_catalog entry count matches catalog config", False, str(exc))
        catalog = []

    try:
        prompts_payload = _load_json(runtime.prompts_path)
        prompt_books = prompts_payload.get("books", []) if isinstance(prompts_payload, dict) else []
        add("book_prompts has prompts for all books", isinstance(prompt_books, list) and len(prompt_books) >= len(catalog), f"prompt_books={len(prompt_books)}")
    except Exception as exc:
        add("book_prompts has prompts for all books", False, str(exc))

    try:
        regions_path = config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
        regions = _load_json(regions_path)
        covers = regions.get("covers", []) if isinstance(regions, dict) else []
        add(
            "cover_regions has regions for all covers",
            isinstance(covers, list) and len(covers) >= len(catalog),
            f"regions={len(covers)} path={regions_path}",
        )
    except Exception as exc:
        add("cover_regions has regions for all covers", False, str(exc))

    mask_path = runtime.config_dir / "compositing_mask.png"
    add("compositing_mask exists", mask_path.exists(), str(mask_path))

    try:
        _load_json(runtime.prompt_library_path)
        add("prompt_library is valid JSON", True, str(runtime.prompt_library_path))
    except Exception as exc:
        add("prompt_library is valid JSON", False, str(exc))

    input_dir_exists = runtime.input_dir.exists() and runtime.input_dir.is_dir()
    input_count = _count_book_folders(runtime.input_dir) if input_dir_exists else 0
    add("Input Covers exists with expected folder count", input_dir_exists and input_count >= len(catalog), f"input_count={input_count}")

    py_ok = sys.version_info >= (3, 11)
    add("Python version >= 3.11", py_ok, platform.python_version())

    requirements = _requirement_packages(runtime.project_root / "requirements.txt")
    missing = []
    module_overrides = {
        "Pillow": "PIL",
        "opencv-python-headless": "cv2",
        "python-dotenv": "dotenv",
        "google-api-python-client": "googleapiclient",
        "google-auth-oauthlib": "google_auth_oauthlib",
        "google-auth-httplib2": "google_auth_httplib2",
        "pypdf": "pypdf",
    }
    for package in requirements:
        if package == "pathlib2" and sys.version_info >= (3, 6):
            continue
        module_name = module_overrides.get(package, package.replace("-", "_"))
        if importlib.util.find_spec(module_name) is None:
            missing.append(package)
    add("Required packages installed", len(missing) == 0, f"missing={missing}")

    disk = shutil.disk_usage(runtime.project_root)
    add("Disk space > 5GB free", disk.free >= (5 * 1024 ** 3), f"free_gb={round(disk.free / (1024 ** 3), 3)}")

    output_writable = os.access(runtime.output_dir, os.W_OK) or (runtime.output_dir.exists() and os.access(runtime.output_dir, os.W_OK))
    tmp_writable = os.access(runtime.tmp_dir, os.W_OK) or (runtime.tmp_dir.exists() and os.access(runtime.tmp_dir, os.W_OK))
    add("Write permissions on Output Covers and tmp", output_writable and tmp_writable, f"output={output_writable}, tmp={tmp_writable}")

    return checks


def main() -> int:
    checks = run_checks()
    lines = ["Configuration Validation"]
    failures = 0
    for row in checks:
        lines.append(f"- [{row['status']}] {row['check']}: {row['detail']}")
        if row["status"] == "FAIL":
            failures += 1
    logger.info("\n%s", "\n".join(lines))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
