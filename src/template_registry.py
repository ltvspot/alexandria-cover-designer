"""Template registry loading and validation for iterate generation styles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src import config, safe_json


REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "genres",
    "font_pairing",
    "color_palette",
    "element_positioning",
    "prompt_modifier",
}


def _default_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "heritage_classic",
            "name": "Heritage Classic",
            "description": "Traditional navy and gold medallion style with ornate flourishes and serif hierarchy.",
            "genres": ["historical", "literary_fiction", "philosophy", "classics"],
            "font_pairing": {"title": "Garamond", "author": "Trajan Pro"},
            "color_palette": {"primary": "#1a2744", "secondary": "#c5a55a", "accent": "#f4d889", "text": "#f6e5b8"},
            "element_positioning": {
                "title": "top-right",
                "author": "bottom-right",
                "medallion": "center-right",
                "ornaments": "corners-and-spine",
            },
            "prompt_modifier": "classical engraved illustration, museum-grade heritage cover styling, scene-first composition",
        }
    ]


def template_registry_path(*, config_dir: Path | None = None) -> Path:
    root = config_dir or config.CONFIG_DIR
    return root / "template_registry.json"


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(entry)
    normalized["id"] = str(entry.get("id", "")).strip()
    normalized["name"] = str(entry.get("name", "")).strip() or normalized["id"]
    normalized["description"] = str(entry.get("description", "")).strip()

    genres = entry.get("genres", [])
    if not isinstance(genres, list):
        genres = []
    normalized["genres"] = [str(item).strip().lower() for item in genres if str(item).strip()]

    font_pairing = entry.get("font_pairing", {})
    normalized["font_pairing"] = dict(font_pairing) if isinstance(font_pairing, dict) else {}

    color_palette = entry.get("color_palette", {})
    normalized["color_palette"] = dict(color_palette) if isinstance(color_palette, dict) else {}

    element_positioning = entry.get("element_positioning", {})
    normalized["element_positioning"] = dict(element_positioning) if isinstance(element_positioning, dict) else {}

    normalized["prompt_modifier"] = str(entry.get("prompt_modifier", "")).strip()
    return normalized


def validate_entry(entry: dict[str, Any]) -> tuple[bool, str]:
    missing = [field for field in sorted(REQUIRED_FIELDS) if field not in entry]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    entry_id = str(entry.get("id", "")).strip()
    if not entry_id:
        return False, "Template id is required"
    if not str(entry.get("prompt_modifier", "")).strip():
        return False, "Template prompt_modifier is required"
    genres = entry.get("genres", [])
    if not isinstance(genres, list) or not genres:
        return False, "Template genres must be a non-empty list"
    return True, ""


def load_registry(*, path: Path | None = None, config_dir: Path | None = None) -> list[dict[str, Any]]:
    registry_path = path or template_registry_path(config_dir=config_dir)
    payload = safe_json.load_json(registry_path, _default_registry())
    rows = payload if isinstance(payload, list) else []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = _normalize_entry(row)
        ok, _err = validate_entry(normalized)
        if not ok:
            continue
        token = str(normalized.get("id", "")).strip().lower()
        if token in seen:
            continue
        seen.add(token)
        out.append(normalized)
    if out:
        return out
    return _default_registry()


def get_template(*, template_id: str, path: Path | None = None, config_dir: Path | None = None) -> dict[str, Any] | None:
    token = str(template_id or "").strip().lower()
    if not token:
        return None
    for row in load_registry(path=path, config_dir=config_dir):
        if str(row.get("id", "")).strip().lower() == token:
            return row
    return None


def list_templates(
    *,
    genre: str | None = None,
    path: Path | None = None,
    config_dir: Path | None = None,
) -> list[dict[str, Any]]:
    rows = load_registry(path=path, config_dir=config_dir)
    token = str(genre or "").strip().lower()
    if not token:
        return rows
    filtered = [
        row
        for row in rows
        if token in {str(item).strip().lower() for item in row.get("genres", []) if str(item).strip()}
    ]
    return filtered if filtered else rows
