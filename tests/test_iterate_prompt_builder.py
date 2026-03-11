from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import textwrap
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_iterate_hook(*, function_name: str, payload: dict, prompts: list[dict] | None = None) -> Any:
    if shutil.which("node") is None:
        pytest.skip("node not installed")

    node_script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        global.window = {{ Pages: {{}}, __ITERATE_TEST_HOOKS__: {{}} }};
        global.document = {{}};
        global.console = {{ log: () => {{}}, warn: () => {{}}, error: () => {{}} }};
        const promptRows = {json.dumps(prompts or [])};
        global.DB = {{
          dbGetAll: (table) => table === 'prompts' ? promptRows : [],
          dbGet: (table, key) => table === 'prompts' ? (promptRows.find((row) => String(row.id) === String(key)) || null) : null,
        }};
        global.OpenRouter = {{ MODELS: [] }};
        global.Toast = {{}};
        global.JobQueue = {{}};
        global.escapeHtml = (value) => String(value ?? '');
        global.getBlobUrl = () => '';
        global.fetchDownloadBlob = async () => {{ throw new Error('unused'); }};
        global.ensureJSZip = async () => {{ throw new Error('unused'); }};
        global.uuid = () => 'job-1';
        global.StyleDiversifier = {{
          buildDiversifiedPrompt: () => 'Create a breathtaking legacy prompt.',
          selectDiverseStyles: () => [{{ id: 'romantic-sublime', label: 'Romantic Sublime' }}],
        }};

        const source = fs.readFileSync('src/static/js/pages/iterate.js', 'utf8');
        vm.runInThisContext(source, {{ filename: 'iterate.js' }});
        const fn = window.__ITERATE_TEST_HOOKS__[{json.dumps(function_name)}];
        const result = fn({json.dumps(payload)});
        process.stdout.write(JSON.stringify(result));
        """
    )
    proc = subprocess.run(
        ["node", "-e", node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def _run_iterate_prompt_builder(payload: dict) -> dict:
    return _run_iterate_hook(function_name="buildGenerationJobPrompt", payload=payload)


def test_iterate_prompt_builder_keeps_library_prompt_precomposed():
    result = _run_iterate_prompt_builder(
        {
            "book": {
                "title": "A Room with a View",
                "author": "E. M. Forster",
                "default_prompt": "A scene from the piazza",
            },
            "templateObj": {
                "id": "alexandria-base-romantic-realism",
                "name": "BASE 4 Romantic Realism",
                "prompt_template": (
                    "Book cover illustration only - no text. "
                    "Centered medallion illustration: {SCENE}. "
                    "The mood is {MOOD}. Era reference: {ERA}."
                ),
            },
            "promptId": "alexandria-base-romantic-realism",
            "customPrompt": (
                "Book cover illustration only - no text. "
                "Centered medallion illustration: {SCENE}. "
                "The mood is {MOOD}. Era reference: {ERA}."
            ),
            "sceneVal": "Lucy Honeychurch on a Florentine terrace",
            "moodVal": "classical, timeless, evocative",
            "eraVal": "Edwardian Italy",
            "style": {"id": "romantic-sublime", "label": "Romantic Sublime"},
        }
    )

    assert "Create a breathtaking legacy prompt." not in result["prompt"]
    assert "Lucy Honeychurch on a Florentine terrace" in result["prompt"]
    assert "Edwardian Italy" in result["prompt"]
    assert result["styleLabel"] == "BASE 4 Romantic Realism"
    assert result["styleId"] == "none"
    assert result["preservePromptText"] is True
    assert result["libraryPromptId"] == "alexandria-base-romantic-realism"
    assert result["composePrompt"] is False
    assert result["backendPromptSource"] == "custom"


def test_iterate_prompt_builder_keeps_legacy_style_diversifier_for_default_auto():
    result = _run_iterate_prompt_builder(
        {
            "book": {
                "title": "A Room with a View",
                "author": "E. M. Forster",
            },
            "templateObj": None,
            "promptId": "",
            "customPrompt": "",
            "sceneVal": "",
            "moodVal": "",
            "eraVal": "",
            "style": {"id": "romantic-sublime", "label": "Romantic Sublime"},
        }
    )

    assert result["prompt"].startswith("Create a breathtaking legacy prompt.")
    assert 'Create a colorful circular medallion illustration for "A Room with a View" by E. M. Forster.' in result["prompt"]
    assert result["styleLabel"] == "Romantic Sublime"
    assert result["styleId"] == "romantic-sublime"
    assert result["preservePromptText"] is False
    assert result["libraryPromptId"] == ""


def test_iterate_scene_pool_filters_generic_enrichment_and_uses_prompt_context():
    result = _run_iterate_hook(
        function_name="buildScenePool",
        payload={
            "title": "Emma",
            "author": "Jane Austen",
            "enrichment": {
                "iconic_scenes": [
                    "Iconic turning point from Emma",
                    "Emma Woodhouse insulting Miss Bates during the Box Hill picnic",
                ],
            },
            "prompt_context": {
                "scene_pool": [
                    "Emma Woodhouse standing in Hartfield's drawing room overlooking Highbury",
                ],
            },
        },
    )

    assert "Iconic turning point from Emma" not in result
    assert result[0].startswith("Emma Woodhouse standing in Hartfield")


def test_iterate_wildcard_rotation_changes_across_days():
    prompts = [
        {"id": "alexandria-wildcard-illuminated-manuscript", "name": "WILDCARD 3 — Illuminated Manuscript", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-celtic-knotwork", "name": "WILDCARD 24 — Celtic Knotwork", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-temple-of-knowledge", "name": "WILDCARD 5 — Temple of Knowledge", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-venetian-renaissance", "name": "WILDCARD 6 — Venetian Renaissance", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-klimt-gold-leaf", "name": "WILDCARD 26 — Klimt Gold Leaf", "tags": ["alexandria", "wildcard"]},
    ]
    book = {"title": "The Gospel of Thomas", "author": "Unknown", "genre": "religious"}

    first = _run_iterate_hook(
        function_name="suggestedWildcardPromptForBookAtDate",
        payload={"book": book, "referenceDate": "2026-03-10T00:00:00.000Z"},
        prompts=prompts,
    )
    second = _run_iterate_hook(
        function_name="suggestedWildcardPromptForBookAtDate",
        payload={"book": book, "referenceDate": "2026-03-11T00:00:00.000Z"},
        prompts=prompts,
    )

    assert first["id"] != second["id"]


def test_iterate_variant_prompt_plan_interleaves_base_rotation_and_wildcards():
    prompts = [
        {"id": "alexandria-base-classical-devotion", "name": "BASE 1 — Classical Devotion", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-philosophical-gravitas", "name": "BASE 2 — Philosophical Gravitas", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-gothic-atmosphere", "name": "BASE 3 — Gothic Atmosphere", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-romantic-realism", "name": "BASE 4 — Romantic Realism", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-esoteric-mysticism", "name": "BASE 5 — Esoteric Mysticism", "tags": ["alexandria", "base"]},
        {"id": "alexandria-wildcard-pre-raphaelite-garden", "name": "WILDCARD 2 — Pre-Raphaelite Garden", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-impressionist-plein-air", "name": "WILDCARD 8 — Impressionist Plein Air", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-romantic-landscape", "name": "WILDCARD 10 — Romantic Landscape", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-art-nouveau-poster", "name": "WILDCARD 11 — Art Nouveau Poster", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-pre-raphaelite-dream", "name": "WILDCARD 23 — Pre-Raphaelite Dream", "tags": ["alexandria", "wildcard"]},
    ]
    assignments = _run_iterate_hook(
        function_name="buildVariantPromptAssignments",
        payload={
            "book": {
                "title": "Emma",
                "author": "Jane Austen",
                "genre": "literature",
                "enrichment": {
                    "iconic_scenes": [
                        "Emma Woodhouse scolding Harriet in the Hartfield drawing room",
                        "The Box Hill picnic where Emma insults Miss Bates",
                        "Mr. Knightley confronting Emma on the walk back from Box Hill",
                    ],
                },
            },
            "variantCount": 6,
            "referenceDate": "2026-03-11T00:00:00.000Z",
        },
        prompts=prompts,
    )

    assert [row["variant"] for row in assignments] == [1, 2, 3, 4, 5, 6]
    assert [assignments[0]["promptId"], assignments[2]["promptId"], assignments[4]["promptId"]] == [
        "alexandria-base-romantic-realism",
        "alexandria-base-classical-devotion",
        "alexandria-base-philosophical-gravitas",
    ]
    assert all(row["promptType"] == "wildcard" for row in [assignments[1], assignments[3], assignments[5]])
    assert len({row["promptId"] for row in [assignments[1], assignments[3], assignments[5]]}) == 3
    assert len({row["scene"] for row in assignments[:3]}) == 3


def test_iterate_variant_prompt_plan_falls_back_to_literature_defaults_for_unknown_genre():
    assignments = _run_iterate_hook(
        function_name="buildVariantPromptAssignments",
        payload={
            "book": {"title": "Unknown Treatise", "author": "Anon", "genre": "uncategorized"},
            "variantCount": 3,
            "referenceDate": "2026-03-11T00:00:00.000Z",
        },
        prompts=[],
    )

    assert assignments[0]["promptId"] == "alexandria-base-romantic-realism"
    assert assignments[1]["promptId"] in {
        "alexandria-wildcard-pre-raphaelite-garden",
        "alexandria-wildcard-impressionist-plein-air",
        "alexandria-wildcard-romantic-landscape",
        "alexandria-wildcard-art-nouveau-poster",
        "alexandria-wildcard-pre-raphaelite-dream",
    }
    assert assignments[2]["promptId"] == "alexandria-base-classical-devotion"


def test_iterate_science_genre_maps_to_scientific_wildcards():
    prompts = [
        {"id": "alexandria-wildcard-scientific-diagram", "name": "Scientific Diagram", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-celestial-cartography", "name": "Celestial Cartography", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-naturalist-field-study", "name": "Naturalist Field Study", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-botanical-plate", "name": "Botanical Plate", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-antique-map-illustration", "name": "Antique Map Illustration", "tags": ["alexandria", "wildcard"]},
    ]
    book = {"title": "On the Origin of Species", "author": "Charles Darwin", "genre": "science"}

    selected = _run_iterate_hook(
        function_name="suggestedWildcardPromptForBookAtDate",
        payload={"book": book, "referenceDate": "2026-03-11T00:00:00.000Z"},
        prompts=prompts,
    )

    assert selected["id"] in {prompt["id"] for prompt in prompts}


def test_iterate_short_real_name_is_not_generic():
    result = _run_iterate_hook(function_name="isGenericContent", payload="Eve")
    assert result is False


def test_iterate_default_selected_model_keeps_nano_even_when_google_is_down():
    result = _run_iterate_hook(
        function_name="defaultSelectedModelIds",
        payload={
            "models": [
                {"id": "openrouter/google/gemini-3-pro-image-preview", "status": "active"},
                {"id": "openai/gpt-image-1-mini", "status": "active"},
                {"id": "google/gemini-3-pro-image-preview", "status": "active"},
            ],
            "providerConnectivity": {
                "openrouter": {"status": "connected", "error": None},
                "openai": {"status": "connected", "error": None},
                "google": {"status": "error", "error": "Google key leaked"},
            },
            "providerRuntime": {
                "openrouter": {"last_error": "OpenRouter error 402: This request requires more credits"},
                "google": {"last_error": "Google error 403: leaked"},
            },
        },
    )

    assert result == ["openrouter/google/gemini-3-pro-image-preview"]


def test_iterate_model_availability_disables_direct_google_model_when_connectivity_fails():
    result = _run_iterate_hook(
        function_name="modelAvailability",
        payload={
            "model": {"id": "google/gemini-3-pro-image-preview", "status": "active"},
            "providerConnectivity": {
                "google": {"status": "error", "error": "Google error 403: leaked"},
            },
            "providerRuntime": {},
        },
    )

    assert result["selectable"] is False
    assert result["degraded"] is False
    assert "leaked" in result["reason"].lower()


def test_iterate_default_selected_model_still_prefers_nano_before_runtime_failures():
    result = _run_iterate_hook(
        function_name="defaultSelectedModelIds",
        payload={
            "models": [
                {"id": "openrouter/google/gemini-3-pro-image-preview", "status": "active"},
                {"id": "openai/gpt-image-1-mini", "status": "active"},
                {"id": "openrouter/openai/gpt-5-image", "status": "active"},
            ],
            "providerConnectivity": {
                "openrouter": {"status": "connected", "error": None},
                "openai": {"status": "connected", "error": None},
                "google": {"status": "error", "error": "Google error 403: leaked"},
            },
            "providerRuntime": {},
        },
    )

    assert result == ["openrouter/google/gemini-3-pro-image-preview"]


def test_iterate_variant_jobs_create_exactly_one_job_per_variant_with_rotating_metadata():
    result = _run_iterate_hook(
        function_name="buildVariantJobs",
        payload={
            "book": {
                "title": "Gulliver's Travels",
                "author": "Jonathan Swift",
                "genre": "adventure",
                "enrichment": {
                    "iconic_scenes": [
                        "Lemuel Gulliver bound by the Lilliputians on the shore",
                        "Gulliver towering over the tiny palace in Lilliput",
                        "Gulliver standing among the giants of Brobdingnag",
                        "Gulliver facing the Houyhnhnms across a windswept plain",
                    ],
                    "emotional_tone": "satirical, adventurous, absurd",
                    "era": "Georgian era",
                },
            },
            "bookId": 3,
            "modelId": "openrouter/google/gemini-3-pro-image-preview",
            "variantCount": 4,
            "variantPromptPlan": [
                {
                    "variant": 1,
                    "autoPromptId": "alexandria-base-romantic-realism",
                    "autoScene": "Lemuel Gulliver bound by the Lilliputians on the shore",
                    "usesAutoAssignment": True,
                    "usesAutoScene": True,
                    "promptId": "alexandria-base-romantic-realism",
                    "customPrompt": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text.",
                    "sceneVal": "Lemuel Gulliver bound by the Lilliputians on the shore",
                    "moodVal": "satirical, adventurous, absurd",
                    "eraVal": "Georgian era",
                },
                {
                    "variant": 2,
                    "autoPromptId": "alexandria-wildcard-antique-map-illustration",
                    "autoScene": "Gulliver towering over the tiny palace in Lilliput",
                    "usesAutoAssignment": True,
                    "usesAutoScene": True,
                    "promptId": "alexandria-wildcard-antique-map-illustration",
                    "customPrompt": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text.",
                    "sceneVal": "Gulliver towering over the tiny palace in Lilliput",
                    "moodVal": "satirical, adventurous, absurd",
                    "eraVal": "Georgian era",
                },
                {
                    "variant": 3,
                    "autoPromptId": "alexandria-base-classical-devotion",
                    "autoScene": "Gulliver standing among the giants of Brobdingnag",
                    "usesAutoAssignment": True,
                    "usesAutoScene": True,
                    "promptId": "alexandria-base-classical-devotion",
                    "customPrompt": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text.",
                    "sceneVal": "Gulliver standing among the giants of Brobdingnag",
                    "moodVal": "satirical, adventurous, absurd",
                    "eraVal": "Georgian era",
                },
                {
                    "variant": 4,
                    "autoPromptId": "alexandria-wildcard-maritime-chart",
                    "autoScene": "Gulliver facing the Houyhnhnms across a windswept plain",
                    "usesAutoAssignment": True,
                    "usesAutoScene": True,
                    "promptId": "alexandria-wildcard-maritime-chart",
                    "customPrompt": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text.",
                    "sceneVal": "Gulliver facing the Houyhnhnms across a windswept plain",
                    "moodVal": "satirical, adventurous, absurd",
                    "eraVal": "Georgian era",
                },
            ],
        },
        prompts=[
            {"id": "alexandria-base-romantic-realism", "name": "BASE 4 — Romantic Realism", "prompt_template": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text."},
            {"id": "alexandria-base-classical-devotion", "name": "BASE 1 — Classical Devotion", "prompt_template": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text."},
            {"id": "alexandria-wildcard-antique-map-illustration", "name": "WILDCARD 27 — Antique Map Illustration", "prompt_template": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text."},
            {"id": "alexandria-wildcard-maritime-chart", "name": "WILDCARD 29 — Maritime Chart", "prompt_template": "Book cover illustration only. {SCENE}. Mood: {MOOD}. Era: {ERA}. No text."},
        ],
    )

    assert result["validationError"] == ""
    assert len(result["jobs"]) == 4
    assert {job["model"] for job in result["jobs"]} == {"openrouter/google/gemini-3-pro-image-preview"}
    assert {job["variant"] for job in result["jobs"]} == {1, 2, 3, 4}
    assert len({job["prompt_template_id"] for job in result["jobs"]}) == 4
    assert len({job["scene_description"] for job in result["jobs"]}) == 4
