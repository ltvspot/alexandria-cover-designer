from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import textwrap

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_openrouter_generate(*, config_payload: dict, generate_payload: dict) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not installed")

    node_script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');

        const fetchCalls = [];
        const configPayload = {json.dumps(config_payload)};
        const generatePayload = {json.dumps(generate_payload)};

        global.window = {{}};
        global.console = {{ warn: () => {{}}, log: () => {{}} }};
        global.DOMException = class DOMException extends Error {{
          constructor(message, name) {{
            super(message);
            this.name = name;
          }}
        }};
        global.fetch = async (url, options = {{}}) => {{
          fetchCalls.push({{
            url,
            method: options.method || 'GET',
            body: options.body ? JSON.parse(options.body) : null,
          }});
          if (url === '/api/config') {{
            return {{
              ok: true,
              status: 200,
              json: async () => configPayload,
              text: async () => JSON.stringify(configPayload),
              headers: {{ get: () => null }},
            }};
          }}
          if (url === '/api/generate') {{
            return {{
              ok: true,
              status: 200,
              json: async () => generatePayload,
              text: async () => JSON.stringify(generatePayload),
              headers: {{ get: () => null }},
            }};
          }}
          throw new Error(`Unexpected fetch: ${{url}}`);
        }};

        const source = fs.readFileSync('src/static/js/openrouter.js', 'utf8');
        vm.runInThisContext(source, {{ filename: 'openrouter.js' }});

        (async () => {{
          const result = await window.OpenRouter.generateImage(
            'Prompt',
            'openrouter/google/gemini-2.5-flash-image',
            '',
            null,
            120000,
            {{
              book_id: 4,
              catalog: 'classics',
              variant: 1,
              variants: 1,
              prompt_source: 'custom',
              cover_source: 'drive',
            }}
          );
          process.stdout.write(JSON.stringify({{ result, fetchCalls }}));
        }})().catch((err) => {{
          console.error(err);
          process.exit(1);
        }});
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


def test_openrouter_generate_uses_sync_when_worker_is_stale():
    result = _run_openrouter_generate(
        config_payload={
            "feature_flags": {"sync_generation_allowed": True},
            "worker": {"alive": False},
        },
        generate_payload={
            "ok": True,
            "results": [
                {
                    "variant": 1,
                    "image_path": "tmp/generated/4/nano2.png",
                    "composited_path": "tmp/composited/4/nano2.jpg",
                }
            ],
        },
    )

    config_call = next(call for call in result["fetchCalls"] if call["url"] == "/api/config")
    generate_call = next(call for call in result["fetchCalls"] if call["url"] == "/api/generate")
    assert config_call["method"] == "GET"
    assert generate_call["body"]["async"] is False
    assert result["result"]["status"] == "completed"
    assert result["result"]["job"] is None
    assert result["result"]["result"]["image_path"] == "tmp/generated/4/nano2.png"


def test_openrouter_generate_keeps_async_when_worker_is_healthy():
    result = _run_openrouter_generate(
        config_payload={
            "feature_flags": {"sync_generation_allowed": True},
            "worker": {"alive": True},
        },
        generate_payload={
            "ok": True,
            "job": {
                "id": "job-1",
                "status": "completed",
                "result": {
                    "results": [
                        {
                            "variant": 1,
                            "image_path": "tmp/generated/4/async.png",
                            "composited_path": "tmp/composited/4/async.jpg",
                        }
                    ]
                },
            },
        },
    )

    generate_call = next(call for call in result["fetchCalls"] if call["url"] == "/api/generate")
    assert generate_call["body"]["async"] is True
    assert result["result"]["status"] == "completed"
    assert result["result"]["job"]["id"] == "job-1"
    assert result["result"]["result"]["composited_path"] == "tmp/composited/4/async.jpg"
