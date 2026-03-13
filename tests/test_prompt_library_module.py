from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import prompt_library as pl


def _templates_payload() -> dict:
    return {
        "negative_prompt": "text, watermark",
        "style_groups": {
            "sketch_style": {"style_anchors": "sketch anchor"},
            "oil_painting_style": {"style_anchors": "oil anchor"},
            "alternative_style": {"style_anchors": "alt anchor"},
        },
    }


def _library_prompt(prompt_id: str = "p1") -> pl.LibraryPrompt:
    return pl.LibraryPrompt(
        id=prompt_id,
        name="Prompt 1",
        prompt_template="Scene for {title}",
        style_anchors=["warm_sepia_sketch"],
        negative_prompt="text",
        source_book="book",
        source_model="model",
        quality_score=0.8,
        saved_by="tester",
        created_at="2026-02-21T00:00:00+00:00",
        notes="good",
        tags=["iconic", "sketch"],
    )


def test_seed_and_basic_accessors(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    lib_path = tmp_path / "prompt_library.json"
    library = pl.PromptLibrary(lib_path)
    anchors = library.get_style_anchors()
    prompts = library.get_prompts()
    assert len(anchors) >= 3
    assert len(prompts) >= 1
    assert lib_path.exists()


def test_save_prompt_and_filters(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    library = pl.PromptLibrary(tmp_path / "prompt_library.json")
    prompt = _library_prompt("custom-1")
    library.save_prompt(prompt)

    all_prompts = library.get_prompts()
    assert any(p.id == "custom-1" for p in all_prompts)

    filtered = library.get_prompts(tags=["iconic"])
    assert any(p.id == "custom-1" for p in filtered)

    searched = library.search_prompts(query="scene", tags=["sketch"], min_quality=0.7)
    assert any(p.id == "custom-1" for p in searched)


def test_save_prompt_requires_supported_placeholder(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    library = pl.PromptLibrary(tmp_path / "prompt_library.json")
    invalid = pl.LibraryPrompt(
        id="bad",
        name="Bad",
        prompt_template="No placeholder here",
        style_anchors=["warm_sepia_sketch"],
        negative_prompt="text",
        source_book="b",
        source_model="m",
        quality_score=0.5,
        saved_by="t",
        created_at="2026-02-21T00:00:00+00:00",
        notes="",
        tags=[],
    )
    with pytest.raises(ValueError):
        library.save_prompt(invalid)


def test_save_winner_prompt_allows_fully_resolved_text_and_lookup_by_text(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    library = pl.PromptLibrary(tmp_path / "prompt_library.json")
    winner = pl.LibraryPrompt(
        id="winner-1",
        name="Winner Prompt",
        prompt_template="Book cover illustration only — Lucy Honeychurch embracing George Emerson on a Florentine hillside at sunset.",
        style_anchors=[],
        negative_prompt="no text",
        source_book="A Room with a View — E. M. Forster",
        source_model="openrouter/google/gemini-3-pro-image-preview",
        quality_score=0.0,
        saved_by="user",
        created_at="2026-03-08T00:00:00+00:00",
        notes="saved winner",
        tags=["winner", "a-room-with-a-view", "base-4-romantic-realism"],
        category="winner",
        win_count=1,
    )

    library.save_prompt(winner)
    saved = library.get_prompt("winner-1")
    assert saved is not None
    assert saved.category == "winner"
    assert library.find_prompt_by_template_text(winner.prompt_template) is not None


def test_alexandria_prompts_seeded_first_and_scene_placeholders_allowed(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    library = pl.PromptLibrary(tmp_path / "prompt_library.json")
    prompts = library.get_prompts()
    alexandria = [prompt for prompt in prompts if prompt.id.startswith("alexandria-")]
    assert len(alexandria) >= 10
    assert prompts[0].id.startswith("alexandria-")

    scene_prompt = pl.LibraryPrompt(
        id="scene-based",
        name="Scene Based",
        prompt_template="Book cover illustration only — {SCENE} with mood {MOOD}.",
        style_anchors=[],
        negative_prompt="text",
        source_book="book",
        source_model="model",
        quality_score=0.9,
        saved_by="tester",
        created_at="2026-03-08T00:00:00+00:00",
        notes="scene prompt",
        tags=["alexandria"],
        category="builtin",
    )
    library.save_prompt(scene_prompt)
    saved = library.get_prompt("scene-based")
    assert saved is not None
    assert "{SCENE}" in saved.prompt_template


def test_seeded_alexandria_builtins_are_scene_first(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    library = pl.PromptLibrary(tmp_path / "prompt_library.json")
    prompts = {
        prompt.id: prompt
        for prompt in library.get_prompts()
        if prompt.id.startswith("alexandria-")
    }

    assert len(prompts) == 37
    wildcard_prompts = [
        prompt
        for prompt in prompts.values()
        if str(prompt.category or "").strip().lower() == "wildcard"
    ]
    assert len(wildcard_prompts) == 32
    for prompt_id, prompt in prompts.items():
        template = prompt.prompt_template
        assert template.startswith("Book cover illustration only")
        assert "{SCENE}" in template
        assert template.index("{SCENE}") < 250, prompt_id
        assert "{MOOD}" in template
        assert "{ERA}" in template

    storybook = prompts["alexandria-wildcard-painterly-storybook"]
    atmospheric = prompts["alexandria-wildcard-painterly-atmospheric"]

    assert "HAND-PAINTED" in storybook.prompt_template
    assert "brushwork" in storybook.prompt_template
    assert "NO photorealism" in storybook.prompt_template
    assert "NO 3D rendering" in storybook.prompt_template
    assert "no medallion" in storybook.prompt_template.lower()

    assert "HAND-PAINTED" in atmospheric.prompt_template
    assert "brushwork" in atmospheric.prompt_template
    assert "NO photorealism" in atmospheric.prompt_template
    assert "NO 3D rendering" in atmospheric.prompt_template
    assert "no medallion" in atmospheric.prompt_template.lower()


def test_seeded_alexandria_base_prompts_use_full_canvas_no_medallion_language(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    library = pl.PromptLibrary(tmp_path / "prompt_library.json")
    prompts = {
        prompt.id: prompt
        for prompt in library.get_prompts()
        if prompt.id.startswith("alexandria-base-")
    }

    assert set(prompts) == {
        "alexandria-base-classical-devotion",
        "alexandria-base-philosophical-gravitas",
        "alexandria-base-gothic-atmosphere",
        "alexandria-base-romantic-realism",
        "alexandria-base-esoteric-mysticism",
    }

    for prompt in prompts.values():
        assert "No border, no frame, no ornamental elements, no medallion, no decorative edges." in prompt.prompt_template
        assert "This illustration MUST depict the following specific scene: {SCENE}." in prompt.prompt_template
        assert "Full scene composition filling the entire canvas, no circular framing." in prompt.prompt_template
        assert "This circular medallion illustration" not in prompt.prompt_template
        assert "Circular vignette composition with soft edges." not in prompt.prompt_template
        assert (
            "No circular vignette, no medallion composition, no ornamental frame, no decorative border, "
            "no floral border frame, no scrollwork frame."
        ) in prompt.negative_prompt

    classical = prompts["alexandria-base-classical-devotion"].prompt_template
    romantic = prompts["alexandria-base-romantic-realism"].prompt_template

    assert "Alphonse Mucha and Edward Burne-Jones" in classical
    assert "#0a1628" in classical
    assert "#c5941a" in classical
    assert "visible gold leaf effect" in classical

    assert "Dante Gabriel Rossetti and William Morris" in romantic
    assert "#0e1f3d" in romantic
    assert "#d4a017" in romantic
    assert "Victorian botanical plate" in romantic


def test_build_prompt_best_prompts_add_anchor(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    library = pl.PromptLibrary(tmp_path / "prompt_library.json")
    built = library.build_prompt("Moby Dick", ["warm_sepia_sketch"], custom_text="stormy sea")
    assert "Moby Dick" in built
    assert "stormy sea" in built

    with pytest.raises(ValueError):
        library.build_prompt("Moby Dick", ["missing-anchor"])

    library.add_style_anchor(
        pl.StyleAnchor(
            name="new_anchor",
            description="x",
            style_text="new style",
            tags=["new"],
        )
    )
    assert any(a.name == "new_anchor" for a in library.get_style_anchors())

    top = library.get_best_prompts_for_bulk(top_n=3)
    assert len(top) >= 1


def test_reload_existing_library(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    lib_path = tmp_path / "prompt_library.json"
    first = pl.PromptLibrary(lib_path)
    first.save_prompt(_library_prompt("reload-1"))

    second = pl.PromptLibrary(lib_path)
    assert any(p.id == "reload-1" for p in second.get_prompts())


def test_load_or_seed_recovers_from_invalid_library_json(tmp_path: Path, monkeypatch):
    templates_path = tmp_path / "prompt_templates.json"
    templates_path.write_text(json.dumps(_templates_payload()), encoding="utf-8")
    monkeypatch.setattr(pl.config, "PROMPT_TEMPLATES_PATH", templates_path)

    lib_path = tmp_path / "prompt_library.json"
    lib_path.write_text("{bad", encoding="utf-8")
    library = pl.PromptLibrary(lib_path)

    assert library.get_style_anchors()
    assert library.get_prompts()
    payload = json.loads(lib_path.read_text(encoding="utf-8"))
    assert payload.get("version") == 2
