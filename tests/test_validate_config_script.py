from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from scripts import validate_config as vc
from src import config


def _runtime(tmp_path: Path) -> config.Config:
    base = tmp_path / "runtime"
    input_dir = base / "Input Covers"
    output_dir = base / "Output Covers"
    tmp_dir = base / "tmp"
    data_dir = base / "data"
    config_dir = base / "config"

    for path in (input_dir, output_dir, tmp_dir, data_dir, config_dir):
        path.mkdir(parents=True, exist_ok=True)

    for idx in (1, 2, 3):
        (input_dir / f"{idx}. Book {idx} - Author").mkdir(parents=True, exist_ok=True)

    catalog_path = config_dir / "book_catalog_demo.json"
    prompts_path = config_dir / "book_prompts_demo.json"
    library_path = config_dir / "prompt_library.json"
    regions_path = config.cover_regions_path(catalog_id="demo", config_dir=config_dir)

    catalog_rows = [
        {"number": 1, "title": "Book 1", "author": "Author"},
        {"number": 2, "title": "Book 2", "author": "Author"},
        {"number": 3, "title": "Book 3", "author": "Author"},
    ]
    catalog_path.write_text(json.dumps(catalog_rows), encoding="utf-8")
    prompts_path.write_text(json.dumps({"books": catalog_rows}), encoding="utf-8")
    library_path.write_text(json.dumps({"prompts": [], "style_anchors": []}), encoding="utf-8")
    regions_path.write_text(json.dumps({"covers": [{"cover_id": 1}, {"cover_id": 2}, {"cover_id": 3}]}), encoding="utf-8")

    (config_dir / "compositing_mask.png").write_bytes(b"x")
    (base / ".env").write_text("OPENROUTER_API_KEY=test-key\n", encoding="utf-8")

    cfg = config.get_config()
    return replace(
        cfg,
        project_root=base,
        input_dir=input_dir,
        output_dir=output_dir,
        tmp_dir=tmp_dir,
        data_dir=data_dir,
        config_dir=config_dir,
        book_catalog_path=catalog_path,
        prompts_path=prompts_path,
        prompt_library_path=library_path,
        catalog_id="demo",
        openrouter_api_key="test-key",
        openai_api_key="",
        google_api_key="",
        fal_api_key="",
        replicate_api_token="",
    )


def test_run_checks_uses_dynamic_catalog_count_and_catalog_scoped_regions(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(vc.config, "get_config", lambda: runtime)
    monkeypatch.setattr(
        vc.config,
        "resolve_catalog",
        lambda _catalog_id: config.CatalogConfig(
            id="demo",
            name="Demo",
            book_count=3,
            catalog_file=runtime.book_catalog_path,
            prompts_file=runtime.prompts_path,
            input_covers_dir=runtime.input_dir,
            output_covers_dir=runtime.output_dir,
        ),
    )
    monkeypatch.setattr(
        vc.pipeline,
        "test_api_keys",
        lambda **_kwargs: {"providers": [{"provider": "openrouter", "status": "KEY_VALID"}]},
    )

    checks = vc.run_checks()
    by_name = {row["check"]: row for row in checks}

    assert by_name["book_catalog entry count matches catalog config"]["status"] == "PASS"
    region_row = by_name["cover_regions has regions for all covers"]
    assert region_row["status"] == "PASS"
    assert "cover_regions_demo.json" in region_row["detail"]


def test_run_checks_rebuilds_prompt_library_when_missing(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path)
    runtime.prompt_library_path.unlink()
    monkeypatch.setattr(vc.config, "get_config", lambda: runtime)
    monkeypatch.setattr(
        vc.config,
        "resolve_catalog",
        lambda _catalog_id: config.CatalogConfig(
            id="demo",
            name="Demo",
            book_count=3,
            catalog_file=runtime.book_catalog_path,
            prompts_file=runtime.prompts_path,
            input_covers_dir=runtime.input_dir,
            output_covers_dir=runtime.output_dir,
        ),
    )
    monkeypatch.setattr(
        vc.pipeline,
        "test_api_keys",
        lambda **_kwargs: {"providers": [{"provider": "openrouter", "status": "KEY_VALID"}]},
    )

    checks = vc.run_checks()
    by_name = {row["check"]: row for row in checks}
    assert by_name["prompt_library is valid JSON"]["status"] == "PASS"
    assert runtime.prompt_library_path.exists()
