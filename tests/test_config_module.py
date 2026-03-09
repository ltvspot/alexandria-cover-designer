from __future__ import annotations

import json
import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import config


def test_catalog_config_to_dict_and_path_helpers(tmp_path: Path):
    cfg = config.CatalogConfig(
        id="demo",
        name="Demo",
        book_count=12,
        catalog_file=tmp_path / "catalog.json",
        prompts_file=tmp_path / "prompts.json",
        input_covers_dir=tmp_path / "in",
        output_covers_dir=tmp_path / "out",
        cover_style="style",
        status="active",
    )
    payload = cfg.to_dict()
    assert payload["id"] == "demo"
    assert payload["book_count"] == 12

    assert config._load_json(tmp_path / "missing.json") is None
    abs_path = tmp_path / "absolute.txt"
    assert config._resolve_project_path(abs_path) == abs_path
    assert config._resolve_project_path("config/book_catalog.json") == config.PROJECT_ROOT / "config/book_catalog.json"


def test_load_catalogs_payload_normalizes_dict_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalogs_path = tmp_path / "catalogs.json"
    catalogs_path.write_text(
        json.dumps(
            {
                "catalogs": {
                    "classics": {"name": "Classics", "book_count": 20},
                    "invalid": "skip",
                },
                "default_catalog": "classics",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CATALOGS_PATH", catalogs_path)
    payload = config._load_catalogs_payload()
    assert isinstance(payload.get("catalogs"), list)
    assert payload["catalogs"][0]["id"] == "classics"


def test_list_catalogs_filters_invalid_rows_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalogs_path = tmp_path / "catalogs.json"
    catalogs_path.write_text(
        json.dumps(
            {
                "catalogs": [
                    "bad",
                    {"id": "", "name": "empty"},
                    {"id": "demo", "name": "Demo", "book_count": 5},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CATALOGS_PATH", catalogs_path)
    rows = config.list_catalogs()
    assert len(rows) == 1
    assert rows[0].id == "demo"

    # Empty payload should return built-in fallback catalog.
    catalogs_path.write_text(json.dumps({"catalogs": []}), encoding="utf-8")
    fallback = config.list_catalogs()
    assert len(fallback) == 1
    assert fallback[0].id == "classics"


def test_get_catalog_and_resolve_catalog_paths(monkeypatch: pytest.MonkeyPatch):
    rows = [
        config.CatalogConfig(
            id="classics",
            name="Classics",
            book_count=99,
            catalog_file=config.PROJECT_ROOT / "config/book_catalog.json",
            prompts_file=config.PROJECT_ROOT / "config/book_prompts.json",
            input_covers_dir=config.PROJECT_ROOT / "Input Covers",
            output_covers_dir=config.PROJECT_ROOT / "Output Covers",
        ),
        config.CatalogConfig(
            id="demo",
            name="Demo",
            book_count=5,
            catalog_file=config.PROJECT_ROOT / "config/book_catalog.json",
            prompts_file=config.PROJECT_ROOT / "config/book_prompts.json",
            input_covers_dir=config.PROJECT_ROOT / "Input Covers",
            output_covers_dir=config.PROJECT_ROOT / "Output Covers",
        ),
    ]
    monkeypatch.setattr(config, "list_catalogs", lambda: rows)

    with pytest.raises(KeyError):
        config.get_catalog("")
    assert config.get_catalog("DEMO").id == "demo"
    with pytest.raises(KeyError):
        config.get_catalog("missing")

    assert config.resolve_catalog("classics").id == "classics"
    assert config.resolve_catalog("missing").id == "classics"


def test_load_cover_templates_and_initial_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    templates_path = tmp_path / "cover_templates.json"
    templates_path.write_text(json.dumps({"templates": [{"id": "x"}]}), encoding="utf-8")
    loaded = config.load_cover_templates(templates_path)
    assert loaded["templates"][0]["id"] == "x"

    templates_path.write_text("{bad", encoding="utf-8")
    fallback = config.load_cover_templates(templates_path)
    assert fallback["templates"][0]["id"] == "navy_gold_medallion"

    catalog_path = tmp_path / "book_catalog.json"
    catalog_path.write_text(
        json.dumps([{"number": 1}, {"number": "2"}, {"number": "bad"}, {"number": 3}]),
        encoding="utf-8",
    )
    catalog_cfg = config.CatalogConfig(
        id="scope",
        name="Scope",
        book_count=4,
        catalog_file=catalog_path,
        prompts_file=tmp_path / "book_prompts.json",
        input_covers_dir=tmp_path / "Input Covers",
        output_covers_dir=tmp_path / "Output Covers",
    )
    monkeypatch.setattr(config, "resolve_catalog", lambda _catalog_id=None: catalog_cfg)
    assert config.get_initial_scope_book_numbers(limit=2, catalog_id="scope") == [1, 2]

    catalog_path.write_text(json.dumps({"bad": True}), encoding="utf-8")
    assert config.get_initial_scope_book_numbers(limit=2, catalog_id="scope") == []


def test_catalog_scoped_path_helpers(tmp_path: Path):
    assert config.catalog_scoped_config_path("cover_regions.json", catalog_id="classics", config_dir=tmp_path) == tmp_path / "cover_regions.json"
    assert config.catalog_scoped_config_path("cover_regions.json", catalog_id="SciFi", config_dir=tmp_path) == tmp_path / "cover_regions_scifi.json"
    assert config.catalog_scoped_data_path("safe.json", catalog_id="../Demo/..//", data_dir=tmp_path) == tmp_path / "safe_demo.json"
    assert config.cover_regions_path(catalog_id="demo", config_dir=tmp_path) == tmp_path / "cover_regions_demo.json"
    assert config.enriched_catalog_path(catalog_id="demo", config_dir=tmp_path) == tmp_path / "book_catalog_enriched_demo.json"
    assert config.intelligent_prompts_path(catalog_id="demo", config_dir=tmp_path) == tmp_path / "book_prompts_intelligent_demo.json"
    assert config.winner_selections_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "winner_selections.json"
    assert config.winner_selections_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "winner_selections_demo.json"
    assert config.archive_log_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "archive_log.json"
    assert config.archive_log_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "archive_log_demo.json"
    assert config.quality_scores_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "quality_scores.json"
    assert config.quality_scores_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "quality_scores_demo.json"
    assert config.generation_history_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "generation_history.json"
    assert config.generation_history_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "generation_history_demo.json"
    assert config.regeneration_results_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "regeneration_results.json"
    assert config.regeneration_results_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "regeneration_results_demo.json"
    assert config.prompt_performance_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "prompt_performance.json"
    assert config.prompt_performance_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "prompt_performance_demo.json"
    assert config.llm_usage_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "llm_usage.json"
    assert config.llm_usage_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "llm_usage_demo.json"
    assert config.audit_log_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "audit_log.json"
    assert config.audit_log_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "audit_log_demo.json"
    assert config.error_metrics_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "error_metrics.json"
    assert config.error_metrics_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "error_metrics_demo.json"
    assert config.cost_ledger_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "cost_ledger.json"
    assert config.cost_ledger_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "cost_ledger_demo.json"
    assert config.budget_config_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "budget_config.json"
    assert config.budget_config_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "budget_config_demo.json"
    assert config.delivery_config_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "delivery_pipeline.json"
    assert config.delivery_config_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "delivery_pipeline_demo.json"
    assert config.delivery_tracking_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "delivery_tracking.json"
    assert config.delivery_tracking_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "delivery_tracking_demo.json"
    assert config.report_schedules_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "report_schedules.json"
    assert config.report_schedules_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "report_schedules_demo.json"
    assert config.slo_metrics_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "slo_metrics.json"
    assert config.slo_metrics_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "slo_metrics_demo.json"
    assert config.slo_alert_state_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "slo_alert_state.json"
    assert config.slo_alert_state_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "slo_alert_state_demo.json"
    assert config.review_data_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "review_data.json"
    assert config.review_data_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "review_data_demo.json"
    assert config.iterate_data_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "iterate_data.json"
    assert config.iterate_data_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "iterate_data_demo.json"
    assert config.compare_data_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "compare_data.json"
    assert config.compare_data_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "compare_data_demo.json"
    assert config.variant_selections_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "variant_selections.json"
    assert config.variant_selections_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "variant_selections_demo.json"
    assert config.review_stats_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "review_stats.json"
    assert config.review_stats_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "review_stats_demo.json"
    assert config.similarity_hashes_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "cover_hashes.json"
    assert config.similarity_hashes_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "cover_hashes_demo.json"
    assert config.similarity_matrix_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "similarity_matrix.json"
    assert config.similarity_matrix_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "similarity_matrix_demo.json"
    assert config.similarity_clusters_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "similarity_clusters.json"
    assert config.similarity_clusters_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "similarity_clusters_demo.json"
    assert config.similarity_dismissed_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "similarity_dismissed.json"
    assert config.similarity_dismissed_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "similarity_dismissed_demo.json"
    assert config.drive_sync_log_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "drive_sync_log.json"
    assert config.drive_sync_log_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "drive_sync_log_demo.json"
    assert config.drive_schedule_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "drive_schedule.json"
    assert config.drive_schedule_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "drive_schedule_demo.json"
    assert config.exports_manifest_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "exports_manifest.json"
    assert config.exports_manifest_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "exports_manifest_demo.json"
    assert config.pipeline_state_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "pipeline_state.json"
    assert config.pipeline_state_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "pipeline_state_demo.json"
    assert config.pipeline_summary_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "pipeline_summary.json"
    assert config.pipeline_summary_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "pipeline_summary_demo.json"
    assert config.pipeline_summary_markdown_path(catalog_id="classics", data_dir=tmp_path) == tmp_path / "pipeline_summary.md"
    assert config.pipeline_summary_markdown_path(catalog_id="demo", data_dir=tmp_path) == tmp_path / "pipeline_summary_demo.md"


def test_config_runtime_methods_and_get_config_fallback(monkeypatch: pytest.MonkeyPatch):
    runtime = config.Config(openai_api_key="k", openrouter_api_key="")
    assert runtime.has_any_api_key() is True
    assert runtime.get_api_key("OPENAI") == "k"
    assert runtime.resolve_model_provider("openai/gpt-image-1") == "openai"
    assert runtime.resolve_model_provider("unknown-model", default_provider="google") == "google"
    assert runtime.resolve_model_alias("nano-banana-pro") == "openrouter/google/gemini-3-pro-image-preview"
    assert runtime.get_model_cost("nano-banana-pro") == pytest.approx(0.02)
    assert runtime.get_model_cost("openai/gpt-image-1") >= 0.0
    assert runtime.slo_monitor_interval_seconds >= 0
    assert runtime.composite_max_invalid_variants >= 0

    calls: list[str] = []
    monkeypatch.setattr(config, "ensure_runtime_dirs", lambda: calls.append("dirs"))
    monkeypatch.setattr(config, "resolve_catalog", lambda _catalog_id=None: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(config.logger, "warning", lambda *_args, **_kwargs: calls.append("warn"))
    cfg = config.get_config("broken-catalog")
    assert isinstance(cfg, config.Config)
    assert "dirs" in calls
    assert "warn" in calls


def test_get_config_always_includes_all_gemini_models():
    cfg = config.get_config("classics")
    required = {
        "openrouter/google/gemini-3-pro-image-preview",
        "openrouter/google/gemini-3.1-flash-image-preview",
        "openrouter/google/gemini-2.5-flash-image",
        "google/gemini-3-pro-image-preview",
        "google/gemini-3.1-flash-image-preview",
        "google/gemini-2.5-flash-image",
    }
    assert required.issubset(set(cfg.all_models))


def test_runtime_model_costs_include_prompt29_riverflow_fix():
    assert config.runtime_model_costs_copy()["sourceful/riverflow-v2-fast"] == pytest.approx(0.02)
    assert config.get_config("classics").get_model_cost("openrouter/sourceful/riverflow-v2-fast") == pytest.approx(0.02)


def test_sync_openrouter_pricing_updates_runtime_costs_and_get_config(monkeypatch: pytest.MonkeyPatch):
    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self):  # type: ignore[no-untyped-def]
            return {
                "data": [
                    {"id": "sourceful/riverflow-v2-fast", "pricing": {"image": "0.021"}},
                    {"id": "google/gemini-3-pro-image-preview", "pricing": {"per_image": "0.024"}},
                ]
            }

    original_costs = config.runtime_model_costs_copy()
    original_state = config.openrouter_pricing_sync_status()

    try:
        session = SimpleNamespace(get=lambda *args, **kwargs: _FakeResponse())
        status = config.sync_openrouter_pricing(api_key="test-key", session=session)
        assert status["ok"] is True
        assert status["updated"] >= 2

        runtime_costs = config.runtime_model_costs_copy()
        assert runtime_costs["sourceful/riverflow-v2-fast"] == pytest.approx(0.021)
        assert runtime_costs["openrouter/sourceful/riverflow-v2-fast"] == pytest.approx(0.021)
        assert runtime_costs["nano-banana-pro"] == pytest.approx(0.024)

        cfg = config.get_config("classics")
        assert cfg.get_model_cost("nano-banana-pro") == pytest.approx(0.024)
        assert cfg.cost_per_image_usd == pytest.approx(runtime_costs.get(cfg.ai_model, 0.04))
    finally:
        with config._RUNTIME_MODEL_COST_LOCK:
            config._RUNTIME_MODEL_COST_USD.clear()
            config._RUNTIME_MODEL_COST_USD.update(original_costs)
            config._OPENROUTER_PRICING_SYNC_STATE.clear()
            config._OPENROUTER_PRICING_SYNC_STATE.update(original_state)


def test_sync_openrouter_pricing_ignores_suspiciously_tiny_image_prices():
    class _FakeResponse:
        status_code = 200
        text = ""

        def json(self):  # type: ignore[no-untyped-def]
            return {
                "data": [
                    {"id": "google/gemini-3-pro-image-preview", "pricing": {"per_image": "0.000002"}},
                ]
            }

    original_costs = config.runtime_model_costs_copy()
    original_state = config.openrouter_pricing_sync_status()

    try:
        session = SimpleNamespace(get=lambda *args, **kwargs: _FakeResponse())
        status = config.sync_openrouter_pricing(api_key="test-key", session=session)
        assert status["ok"] is True

        runtime_costs = config.runtime_model_costs_copy()
        assert runtime_costs["nano-banana-pro"] == pytest.approx(original_costs["nano-banana-pro"])
        assert runtime_costs["openrouter/google/gemini-3-pro-image-preview"] == pytest.approx(
            original_costs["openrouter/google/gemini-3-pro-image-preview"]
        )
        assert runtime_costs["google/gemini-3-pro-image-preview"] == pytest.approx(
            original_costs["google/gemini-3-pro-image-preview"]
        )
    finally:
        with config._RUNTIME_MODEL_COST_LOCK:
            config._RUNTIME_MODEL_COST_USD.clear()
            config._RUNTIME_MODEL_COST_USD.update(original_costs)
            config._OPENROUTER_PRICING_SYNC_STATE.clear()
            config._OPENROUTER_PRICING_SYNC_STATE.update(original_state)


def test_sync_openrouter_pricing_skips_without_api_key():
    original_state = config.openrouter_pricing_sync_status()
    try:
        status = config.sync_openrouter_pricing(api_key="", session=SimpleNamespace(get=lambda *_args, **_kwargs: None))
        assert status["ok"] is False
        assert status["skipped"] is True
        assert status["reason"] == "missing_api_key"
    finally:
        with config._RUNTIME_MODEL_COST_LOCK:
            config._OPENROUTER_PRICING_SYNC_STATE.clear()
            config._OPENROUTER_PRICING_SYNC_STATE.update(original_state)


def test_drive_and_budget_alias_env_vars_are_honored(monkeypatch: pytest.MonkeyPatch):
    old_source = os.environ.get("DRIVE_SOURCE_FOLDER_ID")
    old_output = os.environ.get("DRIVE_OUTPUT_FOLDER_ID")
    old_budget = os.environ.get("BUDGET_LIMIT_USD")
    old_max_cost = os.environ.get("MAX_COST_USD")
    monkeypatch.setenv("DRIVE_SOURCE_FOLDER_ID", "source-alias-folder")
    monkeypatch.setenv("DRIVE_OUTPUT_FOLDER_ID", "output-alias-folder")
    monkeypatch.setenv("BUDGET_LIMIT_USD", "321.5")
    monkeypatch.setenv("MAX_COST_USD", "1.0")
    reloaded = importlib.reload(config)
    try:
        cfg = reloaded.get_config("classics")
        assert cfg.gdrive_source_folder_id == "source-alias-folder"
        assert cfg.gdrive_output_folder_id == "output-alias-folder"
        assert cfg.max_cost_usd == pytest.approx(321.5)
    finally:
        if old_source is None:
            os.environ.pop("DRIVE_SOURCE_FOLDER_ID", None)
        else:
            os.environ["DRIVE_SOURCE_FOLDER_ID"] = old_source
        if old_output is None:
            os.environ.pop("DRIVE_OUTPUT_FOLDER_ID", None)
        else:
            os.environ["DRIVE_OUTPUT_FOLDER_ID"] = old_output
        if old_budget is None:
            os.environ.pop("BUDGET_LIMIT_USD", None)
        else:
            os.environ["BUDGET_LIMIT_USD"] = old_budget
        if old_max_cost is None:
            os.environ.pop("MAX_COST_USD", None)
        else:
            os.environ["MAX_COST_USD"] = old_max_cost
        importlib.reload(reloaded)
