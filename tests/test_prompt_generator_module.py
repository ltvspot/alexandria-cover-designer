from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from src import prompt_generator as pg


def _templates() -> dict:
    return {
        "negative_prompt": "bad, low quality",
        "style_groups": {
            "sketch": {"style_anchors": "classical pen and ink sketch with crosshatching and sepia tones"},
            "oil": {"style_anchors": "dramatic classical oil painting with chiaroscuro"},
            "symbolic": {"style_anchors": "symbolic allegorical illustration with period texture"},
        },
        "variants": {
            "1_iconic_scene_sketch": {
                "name": "Iconic Scene",
                "style_group": "sketch",
                "template": "{scene_description}, {style_anchors}, {style_specific_prefix}",
            },
            "2_character_portrait_sketch": {
                "name": "Character Portrait",
                "style_group": "sketch",
                "template": "{character_description}, {style_anchors}, {style_specific_prefix}",
            },
            "3_setting_landscape_sketch": {
                "name": "Setting Landscape",
                "style_group": "sketch",
                "template": "{setting_description}, {style_anchors}, {style_specific_prefix}",
            },
            "4_dramatic_oil_painting": {
                "name": "Dramatic Oil",
                "style_group": "oil",
                "template": "{moment_description}, {style_anchors}, {style_specific_prefix}",
            },
            "5_symbolic_alternative": {
                "name": "Symbolic",
                "style_group": "symbolic",
                "template": "{theme_description}, {style_anchors}, {style_specific_prefix}",
            },
        },
    }


def _book(number: int = 1, title: str = "Moby Dick", author: str = "Herman Melville") -> dict:
    return {"number": number, "title": title, "author": author, "folder_name": f"{number}. {title} - {author}", "file_base": title}


def test_text_helpers():
    assert pg._normalize("A! B?") == "a b"
    assert pg._word_count("a b c") == 3
    assert pg._limit_words("one two three", max_words=2) == "one two"
    stripped = pg._strip_forbidden("Moby Dick by Herman Melville", "Moby Dick", "Herman Melville")
    assert "Moby Dick" not in stripped
    assert "Herman Melville" not in stripped


def test_ensure_prompt_constraints_enforces_length_and_phrases():
    prompt = pg._ensure_prompt_constraints("short prompt")
    low = prompt.lower()
    assert "full-bleed narrative scene" in low
    assert "no text, no letters, no words, no typography" in low
    assert "vivid, high-saturation painterly color palette" in low
    assert 44 <= len(prompt.split()) <= 92

    long_prompt = "word " * 120
    clipped = pg._ensure_prompt_constraints(long_prompt)
    assert len(clipped.split()) <= 92


def test_motif_for_known_and_fallback_books():
    moby = pg._motif_for_book(_book())
    assert "ahab" in moby.iconic_scene.lower() or "whale" in moby.iconic_scene.lower()

    fallback = pg._motif_for_book(_book(9, "Unknown Title", "Unknown Author"))
    assert len(fallback.iconic_scene) > 0


def test_generate_prompts_for_book_shape():
    prompts = pg.generate_prompts_for_book(_book(), _templates())
    assert len(prompts) == 5
    as_dicts = [p.to_dict() for p in prompts]
    assert len({row["variant_id"] for row in as_dicts}) == 5
    for row in as_dicts:
        assert 44 <= row["word_count"] <= 92
        assert "full-bleed narrative scene" in row["prompt"].lower()
        assert "no text, no letters, no words, no typography" in row["prompt"].lower()


def test_prompt_constraints_strip_typography_and_frame_directions():
    raw = "Typography-led poster layout, circular vignette composition, gilt ornament language, text-safe spacing"
    constrained = pg._ensure_prompt_constraints(raw).lower()
    assert "typography-led" not in constrained
    assert "gilt ornament language" not in constrained
    assert "circular vignette composition" not in constrained
    assert "filigree" in constrained
    assert "scrollwork" in constrained
    assert "full-bleed narrative scene" in constrained


def test_generate_all_prompts_and_save(tmp_path: Path):
    catalog_path = tmp_path / "catalog.json"
    templates_path = tmp_path / "templates.json"
    output_path = tmp_path / "book_prompts.json"

    catalog = [_book(1, "Moby Dick", "Herman Melville"), _book(2, "Alice in Wonderland", "Lewis Carroll")]
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    templates_path.write_text(json.dumps(_templates()), encoding="utf-8")

    rows = pg.generate_all_prompts(catalog_path, templates_path)
    assert len(rows) == 2
    assert all(len(row["variants"]) == 5 for row in rows)

    pg.save_prompts(rows, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["book_count"] == 2
    assert payload["total_prompts"] == 10


@pytest.mark.parametrize(
    ("title", "author", "needle"),
    [
        ("Dracula", "Bram Stoker", "transylvanian"),
        ("Pride and Prejudice", "Jane Austen", "regency"),
        ("Frankenstein", "Mary Shelley", "creature"),
        ("Crime and Punishment", "Fyodor Dostoevsky", "petersburg"),
        ("Journey to the Centre of the Earth", "Jules Verne", "caverns"),
        ("The Prince and the Pauper", "Mark Twain", "tudor"),
        ("The Time Machine", "H. G. Wells", "victorian"),
        ("Les Miserables", "Victor Hugo", "barricade"),
        ("We", "Yevgeny Zamyatin", "uniform citizens"),
        ("Unknown Story", "Jane Austen", "regency watercolor etching"),
        ("Unknown Story", "Charles Dickens", "victorian narrative engraving"),
        ("Unknown Story", "William Shakespeare", "theatrical chiaroscuro woodcut"),
    ],
)
def test_motif_for_known_title_and_author_branches(title: str, author: str, needle: str):
    motif = pg._motif_for_book(_book(42, title, author))
    text = " ".join(
        [
            motif.iconic_scene,
            motif.character_portrait,
            motif.setting_landscape,
            motif.dramatic_moment,
            motif.symbolic_theme,
            motif.style_specific_prefix,
        ]
    ).lower()
    assert needle in text


def test_limit_words_drops_trailing_connector_tokens():
    text = "one two three four and"
    assert pg._limit_words(text, max_words=4) == "one two three four"
    assert pg._limit_words("one two and three", max_words=3) == "one two"


def test_strip_forbidden_ignores_tiny_title_or_author_tokens():
    prompt = "abc hero defeats foe by xy"
    stripped = pg._strip_forbidden(prompt, "abc", "xy")
    assert stripped == prompt


def test_main_wires_generation_and_save(monkeypatch):
    args = SimpleNamespace(
        catalog_path=Path("catalog.json"),
        templates_path=Path("templates.json"),
        output_path=Path("book_prompts.json"),
    )
    monkeypatch.setattr(pg.argparse.ArgumentParser, "parse_args", lambda self: args)

    captured: dict[str, object] = {}
    rows = [{"number": 1, "variants": []}]
    monkeypatch.setattr(pg, "generate_all_prompts", lambda *_args, **_kwargs: rows)

    def _fake_save(prompts, output_path):
        captured["prompts"] = prompts
        captured["output_path"] = output_path

    monkeypatch.setattr(pg, "save_prompts", _fake_save)

    assert pg.main() == 0
    assert captured["prompts"] == rows
    assert captured["output_path"] == args.output_path


@pytest.mark.parametrize(
    ("title", "author", "needle"),
    [
        ("A Christmas Carol", "Charles Dickens", "victorian streets"),
        ("Romeo and Juliet", "William Shakespeare", "verona"),
        ("Twenty Thousand Leagues Under the Seas", "Jules Verne", "submarine"),
        ("The Invisible Man", "H. G. Wells", "faceless man"),
        ("The Prince and the Pauper", "Mark Twain", "tudor"),
        ("The Jungle Book", "Rudyard Kipling", "moonlit jungle"),
        ("Robinson Crusoe", "Daniel Defoe", "shipwreck survivor"),
        ("Hamlet", "William Shakespeare", "torchlit hall"),
        ("Oedipus Rex", "Sophocles", "theban"),
        ("The Picture of Dorian Gray", "Oscar Wilde", "candlelit studio"),
        ("The Sign of the Four", "Arthur Conan Doyle", "detective"),
        ("The Call of the Wild", "Jack London", "sled dog"),
        ("Around the World in Eighty Days", "Jules Verne", "steam train"),
        ("Unknown Story", "Mark Twain", "americana ink-wash engraving"),
        ("Unknown Story", "Jules Verne", "scientific adventure lithograph"),
        ("Unknown Story", "Fyodor Dostoyevsky", "psychological monochrome engraving"),
    ],
)
def test_additional_motif_branches(title: str, author: str, needle: str):
    motif = pg._motif_for_book(_book(77, title, author))
    text = " ".join(
        [
            motif.iconic_scene,
            motif.character_portrait,
            motif.setting_landscape,
            motif.dramatic_moment,
            motif.symbolic_theme,
            motif.style_specific_prefix,
        ]
    ).lower()
    assert needle in text


@pytest.mark.filterwarnings("ignore:'src.prompt_generator' found in sys.modules:RuntimeWarning")
def test_module_main_entrypoint_runs(monkeypatch, tmp_path: Path):
    catalog = [_book(1, "Moby Dick", "Herman Melville")]
    templates = _templates()
    catalog_path = tmp_path / "catalog.json"
    templates_path = tmp_path / "templates.json"
    output_path = tmp_path / "out.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    templates_path.write_text(json.dumps(templates), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prompt_generator",
            "--catalog-path",
            str(catalog_path),
            "--templates-path",
            str(templates_path),
            "--output-path",
            str(output_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("src.prompt_generator", run_name="__main__", alter_sys=True)
    assert exc.value.code == 0
    assert output_path.exists()


def test_select_diverse_styles_prioritizes_sevastopol_cossack_and_cycles():
    first_ten = pg.select_diverse_styles(10, seed_token="moby")
    assert len(first_ten) == 10
    ids = [row["id"] for row in first_ten]
    assert ids[:2] == pg.FIXED_VARIANT_STYLE_IDS
    assert len(set(ids[2:5])) == 3
    assert all(style_id in set(pg.CURATED_VARIANT_STYLE_IDS) for style_id in ids[2:5])
    reserved = set(pg.FIXED_VARIANT_STYLE_IDS) | set(pg.CURATED_VARIANT_STYLE_IDS)
    assert len(set(ids[5:10])) == 5
    assert all(style_id not in reserved for style_id in ids[5:10])
    assert len(set(ids)) == 10

    extended = pg.select_diverse_styles(20, seed_token="moby")
    assert len(extended) == 20
    assert [row["id"] for row in extended[:10]] == ids
    assert all(isinstance(row.get("label"), str) and row.get("label") for row in extended)


def test_build_diversified_prompt_applies_scene_only_constraints():
    style = {
        "id": "sevastopol-dramatic-conflict",
        "label": "Sevastopol / Dramatic Conflict",
        "modifier": "Use vivid conflict storytelling and saturated color contrast.",
    }
    prompt = pg.build_diversified_prompt("Moby Dick", "Herman Melville", style).lower()
    assert "moby dick" in prompt
    assert "herman melville" in prompt
    assert "sevastopol / dramatic conflict" in prompt
    assert "no text" in prompt
    assert "no frame" in prompt


def test_diversify_prompt_strips_ornamental_style_instructions(monkeypatch):
    base = pg._ensure_prompt_constraints("scene-first prompt with vivid details")
    monkeypatch.setattr(
        pg,
        "select_diverse_styles",
        lambda _count, seed_token="": [
            {
                "id": "ornamental-style",
                "label": "Ornamental Style",
                "modifier": "The subject is framed by ornamental arches with filigree, arabesques, and scrollwork.",
            }
        ],
    )
    diversified = pg.diversify_prompt(base, 1).lower()
    assert "ornamental arches" not in diversified
    assert "filigree" in diversified
    assert "scrollwork" in diversified
    assert "arabesque" in diversified
    assert "no border" in diversified
    assert "no frame" in diversified
