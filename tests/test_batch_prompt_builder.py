from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_batch_hook(hook_name: str, payload) -> dict | str:
    if shutil.which("node") is None:
        pytest.skip("node not installed")

    node_script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        global.window = {{ Pages: {{}}, __BATCH_TEST_HOOKS__: {{}} }};
        global.document = {{}};
        global.DB = {{}};
        global.OpenRouter = {{ MODELS: [] }};
        global.Toast = {{}};
        global.JobQueue = {{}};
        global.uuid = () => 'job-1';
        global.formatDate = () => 'now';

        const source = fs.readFileSync('src/static/js/pages/batch.js', 'utf8');
        vm.runInThisContext(source, {{ filename: 'batch.js' }});
        const fn = window.__BATCH_TEST_HOOKS__[{json.dumps(hook_name)}];
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


def test_default_batch_prompt_uses_enrichment_scene_mood_and_era():
    prompt = _run_batch_hook(
        "defaultBatchPrompt",
        {
            "book": {
                "id": 52,
                "title": "Gulliver's Travels",
                "author": "Jonathan Swift",
                "enrichment": {
                    "iconic_scenes": [
                        "Gulliver bound by tiny ropes in Lilliput",
                        "Gulliver stands in the court of Brobdingnag while giant courtiers gather around him",
                    ],
                    "emotional_tone": "satirical wonder with unease",
                    "era": "18th-century voyage literature",
                    "protagonist": "Lemuel Gulliver",
                    "setting_primary": "the shores of Lilliput",
                },
            },
            "variant": 2,
            "variantCount": 2,
        },
    )

    assert "Brobdingnag" in prompt
    assert "satirical wonder with unease" in prompt
    assert "18th-century voyage literature" in prompt
    assert "No text, no letters, no words." in prompt


def test_build_batch_job_marks_prompt_as_precomposed_custom():
    job = _run_batch_hook(
        "buildBatchJob",
        {
            "book": {
                "id": 52,
                "title": "Gulliver's Travels",
                "author": "Jonathan Swift",
                "enrichment": {
                    "iconic_scenes": [
                        "Gulliver bound by tiny ropes in Lilliput",
                        "Gulliver stands in the court of Brobdingnag while giant courtiers gather around him",
                    ],
                    "emotional_tone": "satirical wonder with unease",
                },
            },
            "model": "openrouter/google/gemini-3-pro-image-preview",
            "variant": 2,
            "variantCount": 2,
        },
    )

    assert job["book_id"] == 52
    assert job["prompt_source"] == "custom"
    assert job["backend_prompt_source"] == "custom"
    assert job["compose_prompt"] is False
    assert "Brobdingnag" in job["prompt"]
