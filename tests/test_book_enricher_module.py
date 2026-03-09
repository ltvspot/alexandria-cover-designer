from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import book_enricher as be


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload)

    def json(self):  # type: ignore[no-untyped-def]
        return self._payload


def _catalog_rows() -> list[dict]:
    return [
        {"number": 1, "title": "Moby Dick", "author": "Herman Melville", "folder_name": "1. Moby Dick", "file_base": "Moby Dick"},
        {"number": 2, "title": "Dracula", "author": "Bram Stoker", "folder_name": "2. Dracula", "file_base": "Dracula"},
    ]


def test_usage_counter_and_guess_helpers():
    usage = be.UsageCounters()
    usage.add(120, 80, 0.01)
    assert usage.total_calls == 1
    assert usage.total_input_tokens == 120
    assert usage.total_output_tokens == 80
    assert usage.total_cost_usd > 0

    assert be._guess_genre(title_lower="white whale", author="") == "Adventure / Gothic Classic"
    assert be._guess_setting(title_lower="dracula") == "Castle interiors and moonlit European landscapes"
    assert "Renaissance" in be._guess_era(title_lower="hamlet")


def test_parse_and_normalize_helpers():
    wrapped = "```json\n{\"genre\": \"Adventure\"}\n```"
    assert be._parse_json_object(wrapped)["genre"] == "Adventure"
    assert be._parse_json_object("not-json") == {}

    row = {"title": "Title", "author": "Author"}
    normalized = be._normalize_enrichment(
        {
            "genre": "Novel",
            "iconic_scenes": "one, two",
            "key_characters": ["A"],
        },
        row,
    )
    assert normalized["genre"] == "Novel"
    assert len(normalized["iconic_scenes"]) >= 3
    assert len(normalized["key_characters"]) >= 3


def test_generate_enrichment_fallback_modes(monkeypatch):
    runtime = SimpleNamespace(anthropic_api_key="", openai_api_key="")
    row = {"number": 1, "title": "Moby Dick", "author": "Herman Melville"}

    out, in_tok, out_tok, source = be._generate_enrichment(
        row=row,
        description="",
        provider="anthropic",
        model="x",
        max_tokens=50,
        runtime=runtime,
    )
    assert source == "fallback"
    assert in_tok == 0 and out_tok == 0
    assert out["protagonist"]

    out2, *_ = be._generate_enrichment(
        row=row,
        description="",
        provider="unsupported",
        model="x",
        max_tokens=50,
        runtime=runtime,
    )
    assert out2["genre"]

    runtime2 = SimpleNamespace(anthropic_api_key="k", openai_api_key="k")
    monkeypatch.setattr(be, "_call_anthropic", lambda **_kwargs: {"enrichment": {"genre": "A"}, "input_tokens": 1, "output_tokens": 2})
    out3, in3, out3t, src3 = be._generate_enrichment(
        row=row,
        description="",
        provider="anthropic",
        model="x",
        max_tokens=50,
        runtime=runtime2,
    )
    assert src3 == "llm"
    assert in3 == 1 and out3t == 2
    assert out3["genre"] == "A"


def test_call_openai_and_anthropic(monkeypatch):
    def _fake_post(_url, headers=None, json=None, timeout=None):  # type: ignore[no-untyped-def]
        if "Authorization" in (headers or {}):
            return _FakeResponse(
                200,
                {
                    "choices": [{"message": {"content": "{\"genre\": \"X\"}"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                },
            )
        return _FakeResponse(
            200,
            {
                "content": [{"type": "text", "text": "{\"genre\": \"Y\"}"}],
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        )

    monkeypatch.setattr(be.requests, "post", _fake_post)
    row = {"number": 1, "title": "T", "author": "A"}

    out_openai = be._call_openai(api_key="k", model="m", max_tokens=20, row=row, description="")
    assert out_openai["enrichment"]["genre"] == "X"
    assert out_openai["input_tokens"] == 11

    out_anthropic = be._call_anthropic(api_key="k", model="m", max_tokens=20, row=row, description="")
    assert out_anthropic["enrichment"]["genre"] == "Y"
    assert out_anthropic["output_tokens"] == 3


def test_call_openai_and_anthropic_errors(monkeypatch):
    monkeypatch.setattr(be.requests, "post", lambda *_args, **_kwargs: _FakeResponse(500, {}, "error"))
    row = {"number": 1, "title": "T", "author": "A"}
    with pytest.raises(RuntimeError):
        be._call_openai(api_key="k", model="m", max_tokens=20, row=row, description="")
    with pytest.raises(RuntimeError):
        be._call_anthropic(api_key="k", model="m", max_tokens=20, row=row, description="")


def test_enrich_catalog_and_main(tmp_path: Path, monkeypatch):
    catalog_path = tmp_path / "catalog.json"
    output_path = tmp_path / "enriched.json"
    usage_path = tmp_path / "usage.json"
    desc_path = tmp_path / "descriptions.json"

    catalog_path.write_text(json.dumps(_catalog_rows()), encoding="utf-8")
    desc_path.write_text(json.dumps({"1": "ocean voyage"}), encoding="utf-8")
    output_path.write_text(
        json.dumps(
            [
                {
                    "number": 2,
                    "title": "Dracula",
                    "author": "Bram Stoker",
                    "enrichment": {"genre": "Existing", "iconic_scenes": ["s1", "s2", "s3"]},
                }
            ]
        ),
        encoding="utf-8",
    )

    runtime = SimpleNamespace(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_max_tokens=200,
        llm_cost_per_1k_tokens=0.01,
    )
    monkeypatch.setattr(be.config, "get_config", lambda: runtime)
    monkeypatch.setattr(
        be,
        "_generate_enrichment",
        lambda **_kwargs: ({"genre": "Generated", "iconic_scenes": ["a", "b", "c"]}, 10, 5, "llm"),
    )

    summary = be.enrich_catalog(
        catalog_path=catalog_path,
        output_path=output_path,
        books=[1],
        force_refresh=False,
        usage_path=usage_path,
        descriptions_path=desc_path,
    )
    assert summary["books_total"] == 2
    assert summary["books_enriched_in_run"] == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert any(row.get("enrichment", {}).get("genre") == "Generated" for row in payload)
    usage_payload = json.loads(usage_path.read_text(encoding="utf-8"))
    assert usage_payload["total_calls"] >= 1

    args = SimpleNamespace(
        catalog=catalog_path,
        output=output_path,
        books="1",
        all=False,
        force=False,
        provider=None,
        model=None,
        max_tokens=None,
        cost_per_1k=None,
        usage_path=usage_path,
        descriptions=desc_path,
        delay=0.0,
        batch_size=50,
        batch_pause=0.0,
        validate=False,
    )
    monkeypatch.setattr(be.argparse.ArgumentParser, "parse_args", lambda self: args)
    monkeypatch.setattr(be, "enrich_catalog", lambda **_kwargs: {"ok": True})
    assert be.main() == 0


def test_enrich_catalog_writes_output_and_usage_in_single_staged_write(tmp_path: Path, monkeypatch):
    catalog_path = tmp_path / "catalog.json"
    output_path = tmp_path / "enriched.json"
    usage_path = tmp_path / "usage.json"
    desc_path = tmp_path / "descriptions.json"
    catalog_path.write_text(json.dumps(_catalog_rows()), encoding="utf-8")
    desc_path.write_text(json.dumps({"1": "ocean voyage"}), encoding="utf-8")

    runtime = SimpleNamespace(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_max_tokens=200,
        llm_cost_per_1k_tokens=0.01,
    )
    monkeypatch.setattr(be.config, "get_config", lambda: runtime)
    monkeypatch.setattr(
        be,
        "_generate_enrichment",
        lambda **_kwargs: ({"genre": "Generated", "iconic_scenes": ["a", "b", "c"]}, 10, 5, "llm"),
    )

    writes: list[list[Path]] = []

    def _fake_atomic_many(items):  # type: ignore[no-untyped-def]
        writes.append([path for path, _ in items])
        for path, payload in items:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setattr(be.safe_json, "atomic_write_many_json", _fake_atomic_many)

    be.enrich_catalog(
        catalog_path=catalog_path,
        output_path=output_path,
        books=[1],
        force_refresh=False,
        usage_path=usage_path,
        descriptions_path=desc_path,
    )

    assert len(writes) == 1
    assert writes[0] == [output_path, usage_path]
    assert output_path.exists()
    assert usage_path.exists()


def test_enrich_catalog_skips_invalid_rows_and_force_refresh(tmp_path: Path, monkeypatch):
    catalog_path = tmp_path / "catalog.json"
    output_path = tmp_path / "enriched.json"
    usage_path = tmp_path / "usage.json"
    desc_path = tmp_path / "descriptions.json"
    desc_path.write_text("{}", encoding="utf-8")
    catalog_path.write_text(
        json.dumps(
            [
                "bad-row",
                {"number": 0, "title": "Bad", "author": "Bad"},
                {"number": 1, "title": "Alice in Wonderland", "author": "Lewis Carroll"},
            ]
        ),
        encoding="utf-8",
    )
    output_path.write_text(
        json.dumps(
            [
                {
                    "number": 1,
                    "title": "Alice in Wonderland",
                    "author": "Lewis Carroll",
                    "enrichment": {"genre": "Existing"},
                }
            ]
        ),
        encoding="utf-8",
    )

    runtime = SimpleNamespace(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_max_tokens=100,
        llm_cost_per_1k_tokens=0.01,
    )
    monkeypatch.setattr(be.config, "get_config", lambda: runtime)
    monkeypatch.setattr(be, "_generate_enrichment", lambda **_kwargs: ({"genre": "Generated"}, 0, 0, "fallback"))

    summary = be.enrich_catalog(
        catalog_path=catalog_path,
        output_path=output_path,
        force_refresh=True,
        usage_path=usage_path,
        descriptions_path=desc_path,
    )
    assert summary["books_total"] == 1
    assert summary["books_enriched_in_run"] == 1


def test_generate_enrichment_openai_missing_key_and_failure(monkeypatch):
    row = {"number": 1, "title": "Book", "author": "Author"}
    runtime_missing = SimpleNamespace(openai_api_key="")
    out_missing, in_tok, out_tok, source = be._generate_enrichment(
        row=row,
        description="",
        provider="openai",
        model="x",
        max_tokens=20,
        runtime=runtime_missing,
    )
    assert source == "fallback"
    assert in_tok == 0 and out_tok == 0
    assert out_missing["genre"]

    runtime_key = SimpleNamespace(openai_api_key="k")
    monkeypatch.setattr(be, "_call_openai", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    out_fail, in2, out2, source2 = be._generate_enrichment(
        row=row,
        description="",
        provider="openai",
        model="x",
        max_tokens=20,
        runtime=runtime_key,
    )
    assert source2 == "fallback"
    assert in2 == 0 and out2 == 0
    assert out_fail["genre"]


def test_generate_enrichment_anthropic_failure_path(monkeypatch):
    row = {"number": 1, "title": "Book", "author": "Author"}
    runtime = SimpleNamespace(anthropic_api_key="k")
    monkeypatch.setattr(be, "_call_anthropic", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    out, in_tok, out_tok, source = be._generate_enrichment(
        row=row,
        description="",
        provider="anthropic",
        model="x",
        max_tokens=20,
        runtime=runtime,
    )
    assert source == "fallback"
    assert in_tok == 0 and out_tok == 0
    assert out["genre"]


def test_prompt_build_guess_and_normalize_edge_branches():
    prompt = be._build_enrichment_prompt(row={"number": 1, "title": "T", "author": "A"}, description="Deep sea voyage")
    assert "Description: Deep sea voyage" in prompt

    fallback = be._fallback_enrichment(row={"title": "Alice in Wonderland", "author": "Lewis Carroll"}, description="curious rabbit hole")
    assert fallback["protagonist"] == "The main character of Alice in Wonderland"
    assert "curious" in fallback["iconic_scenes"][0].lower()

    assert be._guess_genre(title_lower="pride and prejudice", author="") == "Literary Fiction / Social Novel"
    assert be._guess_genre(title_lower="hamlet", author="") == "Classical Tragedy"
    assert be._guess_genre(title_lower="plain", author="Franz Kafka") == "Psychological / Philosophical Fiction"
    assert be._guess_genre(title_lower="the time machine", author="") == "Speculative / Science Fiction Classic"
    assert be._guess_setting(title_lower="room with a view") == "English estates and European travel settings"
    assert be._guess_setting(title_lower="jungle tales") == "Wilderness landscapes and frontier environments"

    normalized = be._normalize_enrichment(
        {
            "key_characters": "",
            "iconic_scenes": [],
            "visual_motifs": "x, y",
            "symbolic_elements": "one",
        },
        {"title": "Book", "author": "Author"},
    )
    assert len(normalized["key_characters"]) >= 3
    assert len(normalized["iconic_scenes"]) >= 3
    assert len(normalized["symbolic_elements"]) >= 2

    normalized2 = be._normalize_enrichment(
        {"key_characters": 123},
        {"title": "Book", "author": "Author"},
    )
    assert len(normalized2["key_characters"]) >= 3


def test_generate_enrichment_retries_generic_response_and_accumulates_tokens(monkeypatch):
    runtime = SimpleNamespace(openai_api_key="k")
    row = {"number": 1, "title": "Alice in Wonderland", "author": "Lewis Carroll"}
    seen_retry_guidance: list[str] = []
    responses = [
        {
            "enrichment": {
                "genre": "Fantasy",
                "protagonist": "Central protagonist",
                "iconic_scenes": ["a", "b", "c"],
            },
            "input_tokens": 7,
            "output_tokens": 3,
        },
        {
            "enrichment": {
                "genre": "Fantasy",
                "protagonist": "Alice — curious Victorian child in a blue dress",
                "iconic_scenes": [
                    "Alice tumbling down the rabbit hole past floating furniture and shelves.",
                    "Alice at the Mad Tea Party with the Hatter and March Hare in a cluttered garden.",
                    "Alice confronting the Queen of Hearts in the surreal croquet ground.",
                ],
            },
            "input_tokens": 5,
            "output_tokens": 2,
        },
    ]

    def _fake_openai(**kwargs):  # type: ignore[no-untyped-def]
        seen_retry_guidance.append(str(kwargs.get("retry_guidance", "")))
        return responses.pop(0)

    monkeypatch.setattr(be, "_call_openai", _fake_openai)

    out, in_tok, out_tok, source = be._generate_enrichment(
        row=row,
        description="",
        provider="openai",
        model="x",
        max_tokens=20,
        runtime=runtime,
    )

    assert source == "llm"
    assert in_tok == 12
    assert out_tok == 5
    assert out["protagonist"].startswith("Alice")
    assert len(seen_retry_guidance) == 2
    assert seen_retry_guidance[0] == ""
    assert "generic language" in seen_retry_guidance[1]


def test_generate_enrichment_falls_back_after_two_generic_responses_and_keeps_token_usage(monkeypatch):
    runtime = SimpleNamespace(openai_api_key="k")
    row = {"number": 1, "title": "Book", "author": "Author"}
    responses = [
        {
            "enrichment": {
                "protagonist": "Central protagonist",
                "iconic_scenes": ["a", "b", "c"],
            },
            "input_tokens": 4,
            "output_tokens": 2,
        },
        {
            "enrichment": {
                "protagonist": "Central protagonist",
                "iconic_scenes": ["a", "b", "c"],
            },
            "input_tokens": 6,
            "output_tokens": 1,
        },
    ]
    monkeypatch.setattr(be, "_call_openai", lambda **_kwargs: responses.pop(0))

    out, in_tok, out_tok, source = be._generate_enrichment(
        row=row,
        description="",
        provider="openai",
        model="x",
        max_tokens=20,
        runtime=runtime,
    )

    assert source == "fallback"
    assert in_tok == 10
    assert out_tok == 3
    assert out["protagonist"] == "The main character of Book"


def test_validate_enrichment_rows_flags_generic_and_missing_entries():
    summary = be.validate_enrichment_rows(
        [
            {
                "number": 1,
                "enrichment": {
                    "protagonist": "Alice",
                    "iconic_scenes": ["one", "two", "three"],
                },
            },
            {
                "number": 2,
                "enrichment": {
                    "protagonist": "Central protagonist",
                    "iconic_scenes": ["one", "two", "three"],
                },
            },
            {"number": 3, "enrichment": {}},
        ]
    )

    assert summary["total_books"] == 3
    assert summary["usable_books"] == 1
    assert summary["generic_rows"] == 1
    assert summary["books_missing_enrichment"] == 1
    assert summary["passed"] is False


def test_resolve_llm_provider_model_switches_to_available_provider():
    runtime = SimpleNamespace(
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-5-20250929",
        anthropic_api_key="",
        openai_api_key="k",
    )

    provider, model = be._resolve_llm_provider_model(runtime=runtime, provider="anthropic", model="claude-sonnet-4-5-20250929")

    assert provider == "openai"
    assert model == "gpt-4o-mini"


def test_enrich_catalog_uses_effective_provider_and_model(tmp_path: Path, monkeypatch):
    catalog_path = tmp_path / "catalog.json"
    output_path = tmp_path / "enriched.json"
    usage_path = tmp_path / "usage.json"
    desc_path = tmp_path / "descriptions.json"
    catalog_path.write_text(json.dumps(_catalog_rows()[:1]), encoding="utf-8")
    desc_path.write_text("{}", encoding="utf-8")

    runtime = SimpleNamespace(
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-5-20250929",
        llm_max_tokens=200,
        llm_cost_per_1k_tokens=0.01,
        anthropic_api_key="",
        openai_api_key="k",
    )
    captured: dict[str, str] = {}
    monkeypatch.setattr(be.config, "get_config", lambda: runtime)

    def _fake_generate_enrichment(**kwargs):  # type: ignore[no-untyped-def]
        captured["provider"] = kwargs["provider"]
        captured["model"] = kwargs["model"]
        return (
            {
                "genre": "Generated",
                "protagonist": "Alice",
                "iconic_scenes": ["a", "b", "c"],
            },
            1,
            1,
            "llm",
        )

    monkeypatch.setattr(be, "_generate_enrichment", _fake_generate_enrichment)

    summary = be.enrich_catalog(
        catalog_path=catalog_path,
        output_path=output_path,
        usage_path=usage_path,
        descriptions_path=desc_path,
        books=[1],
        force_refresh=True,
    )

    assert captured["provider"] == "openai"
    assert captured["model"] == "gpt-4o-mini"
    assert summary["provider"] == "openai"
    assert summary["model"] == "gpt-4o-mini"


def test_parse_json_and_loaders_and_parse_books_edges(tmp_path: Path):
    assert be._parse_json_object("") == {}
    assert be._parse_json_object("prefix {bad} suffix") == {}

    list_path = tmp_path / "list.json"
    dict_path = tmp_path / "dict.json"
    missing = tmp_path / "missing.json"
    assert be._load_json_list(missing) == []
    assert be._load_json_dict(missing) == {}

    list_path.write_text("{bad", encoding="utf-8")
    assert be._load_json_list(list_path) == []
    list_path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert be._load_json_list(list_path) == []

    dict_path.write_text("{bad", encoding="utf-8")
    assert be._load_json_dict(dict_path) == {}

    assert be._parse_books(None) is None
    assert be._parse_books("1-3, ,5,bad") == [1, 2, 3, 5]
    assert be._safe_int("bad", 9) == 9
