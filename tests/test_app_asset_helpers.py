from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import textwrap
from urllib.parse import parse_qs, urlparse

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_app_hook(hook_name: str, payload):
    if shutil.which("node") is None:
        pytest.skip("node not installed")

    node_script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const payload = {json.dumps(payload)};

        global.window = {{
          Pages: {{}},
          __APP_TEST_HOOKS__: {{}},
          __INITIAL_PAGE__: 'iterate',
          innerWidth: 1280,
          location: {{ hash: '#iterate', origin: 'https://example.test' }},
          addEventListener: () => {{}},
        }};
        global.location = global.window.location;
        global.document = {{
          getElementById: () => null,
          querySelectorAll: () => [],
          createElement: () => ({{
            appendChild() {{}},
            addEventListener() {{}},
            remove() {{}},
            click() {{}},
            classList: {{ add() {{}}, remove() {{}}, toggle() {{}} }},
            style: {{}},
          }}),
          head: {{ appendChild() {{}} }},
          body: {{ appendChild() {{}} }},
        }};
        global.DB = {{
          getSetting: () => 0,
          dbPut: () => {{}},
          dbCount: () => 0,
          openDB: async () => {{}},
          initDefaults: async () => {{}},
          loadPrompts: async () => {{}},
        }};
        global.Drive = {{
          downloadCoverForBook: async () => ({{ img: null }}),
          validateCoverTemplate: () => null,
          catalogCacheStatus: async () => ({{ cached: false }}),
          syncCatalog: async () => {{}},
          loadCachedCatalog: async () => {{}},
          refreshCatalogCache: async () => {{}},
        }};
        global.OpenRouter = {{ init: async () => {{}}, MODEL_COSTS: {{}} }};
        global.Quality = {{ getDetailedScores: async () => ({{ overall: 1 }}) }};
        global.fetch = async () => ({{
          ok: true,
          headers: {{ get: () => 'image/jpeg' }},
          blob: async () => new Blob([], {{ type: 'image/jpeg' }}),
        }});
        global.Image = class {{
          set src(_value) {{
            if (this.onload) this.onload();
          }}
        }};
        global.URL = URL;
        global.URL.createObjectURL = () => 'blob:test';
        global.URL.revokeObjectURL = () => {{}};
        global.crypto = {{ randomUUID: () => 'uuid-test-1' }};
        global.setTimeout = () => 0;
        global.setInterval = () => 0;

        const source = fs.readFileSync('src/static/js/app.js', 'utf8');
        vm.runInThisContext(source, {{ filename: 'app.js' }});
        const fn = window.__APP_TEST_HOOKS__[{json.dumps(hook_name)}];
        const result = Array.isArray(payload) ? fn(...payload) : fn(payload);
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


def test_project_relative_asset_path_strips_encoding_and_cachebuster_query():
    result = _run_app_hook(
        "projectRelativeAssetPath",
        "/Output%20Covers/saved_composites/4/cover%20image.jpg?v=2026-03-10T18%3A40%3A00Z",
    )

    assert result == "Output Covers/saved_composites/4/cover image.jpg"


def test_build_project_asset_url_normalizes_encoded_local_path():
    result = _run_app_hook(
        "buildProjectAssetUrl",
        ["/Output%20Covers/saved_composites/4/cover%20image.jpg?v=1", "2026-03-10T18:40:00Z"],
    )

    parsed = urlparse(result)
    query = parse_qs(parsed.query)
    assert parsed.path == "/api/asset"
    assert query["path"] == ["Output Covers/saved_composites/4/cover image.jpg"]
    assert query["v"] == ["2026-03-10T18:40:00Z"]


def test_resolve_full_resolution_composite_source_rewrites_thumbnail_url_to_asset_endpoint():
    result = _run_app_hook(
        "resolveFullResolutionCompositeSource",
        "/api/thumbnail?path=Output%20Covers%2Fsaved_composites%2F4%2Fcover%20image.jpg%3Fv%3Dold&size=large&v=current",
    )

    assert result == "/api/asset?path=Output%20Covers%2Fsaved_composites%2F4%2Fcover%20image.jpg"


def test_get_blob_url_rewrites_project_relative_string_to_asset_endpoint():
    result = _run_app_hook(
        "getBlobUrl",
        "/Output%20Covers/saved_composites/4/cover%20image.jpg?v=2026-03-11T06%3A33%3A58.279Z",
    )

    parsed = urlparse(result)
    query = parse_qs(parsed.query)
    assert parsed.path == "/api/asset"
    assert query["path"] == ["Output Covers/saved_composites/4/cover image.jpg"]
