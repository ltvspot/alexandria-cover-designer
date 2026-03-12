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


def _run_iterate_variant_payloads(payload: dict, prompts: list[dict] | None = None) -> dict:
    return _run_iterate_hook(function_name="buildVariantPromptPayloads", payload=payload, prompts=prompts)


def _run_iterate_variant_summary_lines(entries: list[dict]) -> list[str]:
    return _run_iterate_hook(function_name="formatVariantSummaryLines", payload={"entries": entries})


def _run_iterate_ui_defaults() -> dict:
    return _run_iterate_hook(function_name="iterateUiDefaults", payload={})


def _run_iterate_variant_options_html(selected_variant_count: int) -> str:
    return _run_iterate_hook(
        function_name="variantCountOptionsHtml",
        payload={"selectedVariantCount": selected_variant_count},
    )


def _run_iterate_enrichment_badge_state(payload: dict) -> dict:
    return _run_iterate_hook(function_name="buildEnrichmentBadgeState", payload=payload)


def _run_iterate_enrichment_retryable(error: dict) -> bool:
    return _run_iterate_hook(function_name="isRetryableEnrichmentHealthError", payload={"error": error})


def _run_iterate_generation_jobs(payload: dict) -> dict:
    return _run_iterate_hook(function_name="buildIterateGenerationJobs", payload=payload)


def _run_iterate_result_sort(jobs: list[dict], sort_mode: str) -> list[dict]:
    return _run_iterate_hook(function_name="sortIterateResultJobs", payload={"jobs": jobs, "sortMode": sort_mode})


def _run_save_raw_request_payload(job: dict) -> dict:
    return _run_iterate_hook(function_name="saveRawRequestPayloadForJob", payload={"job": job})


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


def test_iterate_ui_defaults_use_ten_variants_and_auto_rotate_label():
    result = _run_iterate_ui_defaults()

    assert result["defaultVariantCount"] == 10
    assert result["autoRotateLabel"] == "Auto-Rotate (Recommended)"
    assert result["enrichmentRetryDelaysMs"] == [2000, 4000, 8000]
    assert 'value="10" selected' in result["variantOptionsHtml"]
    assert 'value="4" selected' not in result["variantOptionsHtml"]


def test_iterate_variant_option_html_preserves_selected_count():
    html = _run_iterate_variant_options_html(7)

    assert 'value="7" selected' in html
    assert 'value="10" selected' not in html


def test_iterate_enrichment_badge_state_uses_real_counts_and_failure_copy():
    healthy = _run_iterate_enrichment_badge_state(
        {
            "payload": {
                "health": "healthy",
                "enriched_real": 2397,
                "total_books": 2397,
                "enriched_generic": 0,
                "no_enrichment": 0,
                "run_status": {},
            }
        }
    )
    failed = _run_iterate_enrichment_badge_state({"isFailure": True})

    assert healthy["badgeText"] == "Enrichment: Healthy (2397/2397 real)"
    assert healthy["summaryText"] == "Real: 2397/2397. Generic: 0. Missing: 0."
    assert failed["badgeText"] == "Unable to check enrichment"
    assert failed["summaryText"] == "Unable to check enrichment right now."


def test_iterate_enrichment_retry_policy_only_retries_cold_start_failures():
    assert _run_iterate_enrichment_retryable({"status": 502}) is True
    assert _run_iterate_enrichment_retryable({"status": 503}) is True
    assert _run_iterate_enrichment_retryable({"status": 504}) is True
    assert _run_iterate_enrichment_retryable({"retryable": True}) is True
    assert _run_iterate_enrichment_retryable({"status": 500}) is False


def test_iterate_variant_summary_lines_are_single_line_and_compact():
    lines = _run_iterate_variant_summary_lines(
        [
            {
                "variant": 1,
                "assignedTemplate": {"name": "BASE 4 — Romantic Realism"},
                "assignedScene": "Gulliver wakes on the beach in Lilliput.",
            }
        ]
    )

    assert lines == ["Variant 1: Romantic Realism — Gulliver wakes on the beach in Lilliput."]
    assert "\n" not in lines[0]


def test_iterate_generation_jobs_expand_variants_across_multiple_models():
    result = _run_iterate_generation_jobs(
        {
            "bookId": 7,
            "book": {
                "title": "Gulliver's Travels",
                "author": "Jonathan Swift",
            },
            "selectedModels": [
                "nano-banana-pro",
                "google/gemini-2.5-flash-image",
            ],
            "selectedCoverId": "cover-7",
            "selectedCoverBookNumber": 7,
            "variantEntries": [
                {
                    "variant": 1,
                    "assignedScene": "Gulliver waking up on the beach in Lilliput.",
                    "assignedMood": "astonished",
                    "assignedEra": "18th century",
                    "promptPayload": {
                        "prompt": "Book cover illustration only - no text. Gulliver waking up on the beach in Lilliput.",
                        "styleId": "romantic-realism",
                        "styleLabel": "Romantic Realism",
                        "promptSource": "library",
                        "backendPromptSource": "custom",
                        "composePrompt": False,
                        "preservePromptText": True,
                        "libraryPromptId": "alexandria-base-romantic-realism",
                    },
                },
                {
                    "variant": 2,
                    "assignedScene": "Gulliver standing in the grand palace.",
                    "assignedMood": "wry",
                    "assignedEra": "18th century",
                    "promptPayload": {
                        "prompt": "Book cover illustration only - no text. Gulliver standing in the grand palace.",
                        "styleId": "romantic-realism",
                        "styleLabel": "Romantic Realism",
                        "promptSource": "library",
                        "backendPromptSource": "custom",
                        "composePrompt": False,
                        "preservePromptText": True,
                        "libraryPromptId": "alexandria-base-romantic-realism",
                    },
                },
            ],
        }
    )

    jobs = result["jobs"]
    assert result["validationError"] == ""
    assert len(jobs) == 4
    assert [job["variant"] for job in jobs] == [1, 1, 2, 2]
    assert [job["model"] for job in jobs] == [
        "nano-banana-pro",
        "google/gemini-2.5-flash-image",
        "nano-banana-pro",
        "google/gemini-2.5-flash-image",
    ]


def test_iterate_result_sort_groups_cards_by_model_then_variant():
    jobs = _run_iterate_result_sort(
        [
            {"id": "c", "model": "nano-banana-pro", "variant": 2, "created_at": "2026-03-11T10:00:03Z"},
            {"id": "a", "model": "google/gemini-2.5-flash-image", "variant": 2, "created_at": "2026-03-11T10:00:01Z"},
            {"id": "d", "model": "nano-banana-pro", "variant": 1, "created_at": "2026-03-11T10:00:04Z"},
            {"id": "b", "model": "google/gemini-2.5-flash-image", "variant": 1, "created_at": "2026-03-11T10:00:02Z"},
        ],
        "model",
    )

    assert [job["id"] for job in jobs] == ["b", "a", "d", "c"]


def test_save_raw_request_payload_uses_display_variant_without_selector_variant():
    payload = _run_save_raw_request_payload(
        {
            "variant": 3,
            "style_label": "Romantic Realism",
            "model": "nano-banana-pro",
            "results_json": json.dumps(
                {
                    "result": {
                        "job_id": "backend-job-7",
                        "variant": 1,
                        "raw_art_path": "output/raw_art/7/job-7_variant_1.png",
                        "saved_composited_path": "output/saved_composites/7/job-7_variant_1.jpg",
                    }
                }
            ),
        }
    )

    assert payload["job_id"] == "backend-job-7"
    assert payload["display_variant"] == 3
    assert payload["style_label"] == "Romantic Realism"
    assert payload["expected_model"] == "nano-banana-pro"
    assert "expected_variant" not in payload


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


def test_iterate_expanded_scene_pool_reaches_ten_unique_scenes_for_sparse_books():
    result = _run_iterate_hook(
        function_name="buildExpandedScenePool",
        payload={
            "book": {
                "title": "The Island Voyage",
                "author": "Anon",
                "prompt_context": {
                    "setting": "a wind-beaten island observatory",
                },
                "enrichment": {
                    "iconic_scenes": [
                        "The navigator enters the wind-beaten island observatory",
                    ],
                    "setting_primary": "a wind-beaten island observatory",
                    "emotional_tone": "storm-charged wonder",
                },
            },
            "minimumCount": 10,
        },
    )

    assert len(result) == 10
    assert len(set(result)) == 10
    assert all("wind-beaten island observatory" in scene.lower() for scene in result[1:])


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


def test_iterate_variant_prompt_plan_uses_base_then_rotating_wildcards():
    prompts = [
        {"id": "alexandria-base-romantic-realism", "name": "BASE 4 — Romantic Realism", "tags": ["alexandria", "base"]},
        {"id": "alexandria-wildcard-pre-raphaelite-garden", "name": "WILDCARD 2 — Pre-Raphaelite Garden", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-impressionist-plein-air", "name": "WILDCARD 8 — Impressionist Plein Air", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-romantic-landscape", "name": "WILDCARD 10 — Romantic Landscape", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-art-nouveau-poster", "name": "WILDCARD 11 — Art Nouveau Poster", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-pre-raphaelite-dream", "name": "WILDCARD 23 — Pre-Raphaelite Dream", "tags": ["alexandria", "wildcard"]},
    ]
    assignments = _run_iterate_hook(
        function_name="buildVariantPromptAssignments",
        payload={
            "book": {"title": "Emma", "author": "Jane Austen", "genre": "literature"},
            "variantCount": 4,
            "referenceDate": "2026-03-11T00:00:00.000Z",
        },
        prompts=prompts,
    )

    assert assignments[0]["promptId"] == "alexandria-base-romantic-realism"
    assert [row["variant"] for row in assignments] == [1, 2, 3, 4]
    assert all(row["promptId"] != "alexandria-base-romantic-realism" for row in assignments[1:])
    assert len({row["promptId"] for row in assignments[1:]}) == 3


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


def test_iterate_variant_prompt_plan_uses_all_five_bases_and_five_wildcards_for_ten_variants():
    prompts = [
        {"id": "alexandria-base-romantic-realism", "name": "BASE 4 — Romantic Realism", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-classical-devotion", "name": "BASE 1 — Classical Devotion", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-gothic-atmosphere", "name": "BASE 2 — Gothic Atmosphere", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-esoteric-mysticism", "name": "BASE 5 — Esoteric Mysticism", "tags": ["alexandria", "base"]},
        {"id": "alexandria-base-philosophical-gravitas", "name": "BASE 3 — Philosophical Gravitas", "tags": ["alexandria", "base"]},
        {"id": "alexandria-wildcard-pre-raphaelite-garden", "name": "WILDCARD 2 — Pre-Raphaelite Garden", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-antique-map", "name": "WILDCARD 7 — Antique Map", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-maritime-chart", "name": "WILDCARD 9 — Maritime Chart", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-vintage-pulp-cover", "name": "WILDCARD 14 — Vintage Pulp Cover", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-edo-meets-alexandria", "name": "WILDCARD 18 — Edo Meets Alexandria", "tags": ["alexandria", "wildcard"]},
    ]
    assignments = _run_iterate_hook(
        function_name="buildVariantPromptAssignments",
        payload={
            "book": {"title": "Gulliver's Travels", "author": "Jonathan Swift", "genre": "adventure"},
            "variantCount": 10,
            "referenceDate": "2026-03-11T00:00:00.000Z",
        },
        prompts=prompts,
    )

    prompt_ids = [row["promptId"] for row in assignments]
    assert len(prompt_ids) == 10
    assert len(set(prompt_ids)) == 10
    assert {
        "alexandria-base-romantic-realism",
        "alexandria-base-classical-devotion",
        "alexandria-base-gothic-atmosphere",
        "alexandria-base-esoteric-mysticism",
        "alexandria-base-philosophical-gravitas",
    }.issubset(set(prompt_ids))
    assert {
        "alexandria-wildcard-pre-raphaelite-garden",
        "alexandria-wildcard-antique-map",
        "alexandria-wildcard-maritime-chart",
        "alexandria-wildcard-vintage-pulp-cover",
        "alexandria-wildcard-edo-meets-alexandria",
    }.issubset(set(prompt_ids))


def test_iterate_variant_payloads_auto_rotate_assign_distinct_scenes():
    prompts = [
        {"id": "alexandria-base-romantic-realism", "name": "BASE 4 — Romantic Realism", "prompt_template": "Book cover illustration only - no text. Scene: {SCENE}. Mood: {MOOD}. Era: {ERA}.", "tags": ["alexandria", "base"]},
        {"id": "alexandria-wildcard-pre-raphaelite-garden", "name": "WILDCARD 2 — Pre-Raphaelite Garden", "prompt_template": "Book cover illustration only - no text. Scene: {SCENE}. Mood: {MOOD}. Era: {ERA}.", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-impressionist-plein-air", "name": "WILDCARD 8 — Impressionist Plein Air", "prompt_template": "Book cover illustration only - no text. Scene: {SCENE}. Mood: {MOOD}. Era: {ERA}.", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-romantic-landscape", "name": "WILDCARD 10 — Romantic Landscape", "prompt_template": "Book cover illustration only - no text. Scene: {SCENE}. Mood: {MOOD}. Era: {ERA}.", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-art-nouveau-poster", "name": "WILDCARD 11 — Art Nouveau Poster", "prompt_template": "Book cover illustration only - no text. Scene: {SCENE}. Mood: {MOOD}. Era: {ERA}.", "tags": ["alexandria", "wildcard"]},
        {"id": "alexandria-wildcard-pre-raphaelite-dream", "name": "WILDCARD 23 — Pre-Raphaelite Dream", "prompt_template": "Book cover illustration only - no text. Scene: {SCENE}. Mood: {MOOD}. Era: {ERA}.", "tags": ["alexandria", "wildcard"]},
    ]
    result = _run_iterate_variant_payloads(
        {
            "book": {
                "title": "Gulliver's Travels",
                "author": "Jonathan Swift",
                "genre": "adventure",
                "enrichment": {
                    "iconic_scenes": [
                        "Gulliver wakes on the beach bound by hundreds of tiny ropes while Lilliputians climb over him",
                        "Gulliver stands in the grand palace of the Emperor of Lilliput while courtiers stare upward",
                        "Gulliver is carried by Glumdalclitch through the fields of Brobdingnag",
                        "Gulliver converses with the King of Brobdingnag on a massive throne",
                    ],
                    "emotional_tone": "satirical wonder with unease",
                    "era": "18th-century voyage literature",
                },
            },
            "variantCount": 4,
            "promptId": "",
            "customPrompt": "",
            "sceneVal": "",
            "moodVal": "",
            "eraVal": "",
        },
        prompts=prompts,
    )

    scenes = [str(entry["assignedScene"]) for entry in result["entries"]]
    assert len(scenes) == 4
    assert len(set(scenes)) == 4


def test_iterate_variant_payloads_resolve_legacy_prompt_id_aliases():
    prompts = [
        {
            "id": "alexandria-wildcard-antique-map",
            "name": "Antique Map",
            "prompt_template": "Book cover illustration only - no text. Scene: {SCENE}. Mood: {MOOD}. Era: {ERA}.",
            "tags": ["alexandria", "wildcard"],
        },
    ]
    result = _run_iterate_variant_payloads(
        {
            "book": {
                "title": "Gulliver's Travels",
                "author": "Jonathan Swift",
                "genre": "adventure",
            },
            "variantCount": 1,
            "promptId": "alexandria-wildcard-antique-map-illustration",
            "customPrompt": "",
            "sceneVal": "Gulliver wakes on the beach bound by hundreds of tiny ropes while Lilliputians climb over him",
            "moodVal": "satirical wonder with unease",
            "eraVal": "18th-century voyage literature",
        },
        prompts=prompts,
    )

    assert result["missingPromptIds"] == []
    assert result["entries"][0]["assignedPromptId"] == "alexandria-wildcard-antique-map"
    assert result["entries"][0]["assignedTemplate"]["id"] == "alexandria-wildcard-antique-map"
    assert result["entries"][0]["promptPayload"]["libraryPromptId"] == "alexandria-wildcard-antique-map"


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
