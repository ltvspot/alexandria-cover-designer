# VISUAL PROOF REPORT

Date: 2026-03-13

Last updated: `2026-03-13`
Deployment URL: `https://web-production-900a7.up.railway.app`
Deployment ID: `eadfdb91-df90-4715-9dd9-f9b4218d4412`

## 1.9 PROMPT-49 Save Result Shared Drive + Remove Medallion Fallback (2026-03-13)
- Git commit:
  - `4f99e45` — `Fix save-result drive target and remove medallion fallback`
- Railway deploy:
  - `eadfdb91-df90-4715-9dd9-f9b4218d4412` (`SUCCESS`)
- Local validation before deploy:
  - `python3 -m py_compile scripts/quality_review.py` -> `PASS`
  - `node --check src/static/js/pages/iterate.js` -> `PASS`
  - `python3 -m compileall scripts src` -> `PASS`
  - `pytest -q tests/test_iterate_prompt_builder.py -k 'fallback or default_auto'` -> `PASS`
  - note: `tests/test_quality_review_utils.py` under system Python is blocked by missing `pikepdf`; Prompt 49 validation used the project venv plus direct live production verification instead
- Live production verification:
  - `GET /api/health` returned `ok=true`, `healthy=true`
  - deployed JS check:
    - `curl -s https://web-production-900a7.up.railway.app/static/js/pages/iterate.js | grep -c "circular medallion"` -> `0`
  - real browser generation on deployed app:
    - page: `/iterate`
    - book: `4. Emma`
    - variants: `1`
    - model: `Nano Banana Pro`
    - live job id: `862843c2-785e-4b63-8aff-13c3a094560f`
    - result: `1/1 completed · 0 failed · $0.020`
  - `POST /api/save-result` verification:
    - request job id: `862843c2-785e-4b63-8aff-13c3a094560f`
    - response: `drive_ok=true`
    - `drive_url=https://drive.google.com/file/d/13c7RaD4VfdN2eQEkKl1VOyiJturLqQH0/view`
    - `drive.parent_folder_id=0ABLZWLOVzq-qUk9PVA`
    - no service-account storage quota error
- Visual proof artifacts:
  - live iterate completed run: `/var/folders/_l/b6_b807n6j38l2dkrxc48qbr0000gn/T/playwright-mcp-output/1773390542839/page-2026-03-13T08-32-28-407Z.png`
- Honest remaining unrelated issue:
  - iterate still logs non-fatal thumbnail `404` fallback noise from `/Output Covers/...jpg` before resolving to `/api/asset`; this did not block Prompt 49 acceptance

## 1.8 PROMPT-48C Enrichment Badge + Default Variants (2026-03-12)
- Git commit:
  - `9388657` — `Fix iterate enrichment badge retries`
- Railway deploy:
  - `e18bdf07-0352-463d-9371-7d9322d5ed2e` (`SUCCESS`)
- Local validation before deploy:
  - `node --check src/static/js/pages/iterate.js` -> `PASS`
  - `python3 -m pytest -q tests/test_iterate_prompt_builder.py -k 'ui_defaults or variant_option_html or enrichment_badge_state or enrichment_retry_policy'` -> `PASS`
  - note: the broader `tests/test_iterate_prompt_builder.py` file still has an unrelated pre-existing `science` wildcard mapping failure outside Prompt 48C scope
- Live health after rollout:
  - `GET /api/health` -> `status=ok`
  - `healthy=true`
  - `books_cataloged=2397`
  - `uptime_seconds=124`
- Live route/header proof:
  - `GET /iterate` returned `HTTP/2 200`
  - `Cache-Control: no-store` present
- Live Iterate verification:
  - fresh production load showed `Enrichment: Healthy (2397/2397 real)`
  - enrichment summary showed `Real: 2397/2397. Generic: 0. Missing: 0.`
  - fresh production load showed `Variants = 10`
  - after selecting `3. Gulliver’s Travels into Several Remote Regions of the World`, setting `Variants = 7`, and changing `Style` to `BASE 4 — Romantic Realism`, the page still showed `Variants = 7`
  - browser-side state proof after style change:
    - `variantValue = "7"`
    - `styleValue = "alexandria-base-romantic-realism"`
    - `enrichmentBadge = "Enrichment: Healthy (2397/2397 real)"`
- Visual proof artifacts:
  - fresh live iterate load: `/private/tmp/alexandria-prompt48c/output/playwright/prompt48c/live-iterate-fresh-healthy-10.png`
  - live style-change persistence proof: `/private/tmp/alexandria-prompt48c/output/playwright/prompt48c/live-iterate-style-change-variant-7.png`

## 1.7 PROMPT-22 Model Routing + Prompt Library + Save Raw (2026-03-08)
- Git commits:
  - `7fcd7e6` — preserve prompt text across retries
  - `4874799` — fix raw artifact persistence
  - `fb0edd4` — persist composite artifacts after hydration
  - `7b618c3` — persist Save Raw button state across iterate refreshes
  - deployed/pushed release tip: `a2d106a`
- Railway deploy:
  - `87ac4e06-68e7-4089-82b0-18a810c5c0cb` (`SUCCESS`)
- Live health after rollout:
  - `status: ok`
  - `healthy: true`
  - `uptime_seconds: 1`
  - `books_cataloged: 99`
- Live model inventory proof (`GET /api/models`):
  - `openrouter/google/gemini-3-pro-image-preview` -> `Nano Banana Pro`
  - `openrouter/google/gemini-2.5-flash-image` -> `Nano Banana (Gemini 2.5 Flash)`
  - `google/gemini-3-pro-image-preview` -> `Nano Banana Pro (Google Direct)`
  - `google/gemini-2.5-flash-image` -> `Gemini 2.5 Flash (Google Direct)`
- Live base prompt generation proof:
  - API job: `b163eca0-b49c-4e1b-ac3c-6ea7b4978706`
  - `library_prompt_id` in request/result: `alexandria-base-romantic-realism`
  - prompt prefix: `Book cover illustration only`
  - legacy prompt text present: `false`
  - compositor mode: `pdf`
  - raw art path: `Output Covers/raw_art/1/b163eca0-b49c-4e1b-ac3c-_variant_1_openrouter_google_gemini-3-pro-image-preview.png`
  - saved composite path: `Output Covers/saved_composites/1/b163eca0-b49c-4e1b-ac3c-_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg`
- Live wildcard prompt generation proof:
  - API job: `35d22a12-6b5a-4288-aa64-5afa6d66249d`
  - `library_prompt_id` in request/result: `alexandria-wildcard-edo-meets-alexandria`
  - prompt prefix: `Book cover illustration only`
  - legacy prompt text present: `false`
  - compositor mode: `pdf`
  - raw art path: `Output Covers/raw_art/1/35d22a12-6b5a-4288-aa64-_variant_1_openrouter_google_gemini-3-pro-image-preview.png`
  - saved composite path: `Output Covers/saved_composites/1/35d22a12-6b5a-4288-aa64-_variant_1_openrouter_google_gemini-3-pro-image-preview.jpg`
- Distinct artifact-path proof:
  - base vs wildcard raw paths unique: `true`
  - base vs wildcard saved composite paths unique: `true`
- Live Save Raw proof:
  - `POST /api/save-raw` for job `35d22a12-6b5a-4288-aa64-5afa6d66249d` returned `200`
  - response: `ok=true`, `drive_url=null`
  - local save succeeded under `/app/Output Covers/Chosen Winner Generated Covers/1. A Room with a View - E. M. Forster/...`
  - Drive upload warning reports service-account quota failure (`storageQuotaExceeded`)
  - Iterate UI persists amber state: `✓ Saved (Drive unavailable)` after list refresh
- Visual proof artifacts:
  - live iterate page: `/tmp/alexandria-proof-live-prompt22-final/live-iterate-prompt22-final.png`
  - live results section: `/tmp/alexandria-proof-live-prompt22-final/live-iterate-results-prompt22-final.png`
  - live wildcard result card with persisted save state: `/tmp/alexandria-proof-live-prompt22-final/live-wildcard-card-prompt22-final.png`
  - live dashboard page: `/tmp/alexandria-proof-live-prompt22-final/live-dashboard-prompt22-final.png`
  - live composited cover proof: `/tmp/alexandria-proof-live-prompt22-final/live-cover-wildcard-prompt22.jpg`

## 1.6 PROMPT-20/21 PDF Swap + Guardrail Deployment (2026-03-06)
- Git commit (master):
  - `e55e53d` — Add PDF swap compositor and prompt21 guardrails
- Railway deploy:
  - `dbeb6051-5b97-4717-8e0a-067386db5099` (`SUCCESS`)
- Local validation before deploy:
  - `.venv/bin/pytest -q` -> `PASS`
  - strict PDF verifier on PROMPT-21 QA artifact -> `ALL CHECKS PASSED`
- Live health after rollout:
  - `status: ok`
  - `healthy: true`
  - `uptime_seconds: 1`
  - `books_cataloged: 99` (`/api/health`)
- Live iterate-data check:
  - `GET /api/iterate-data?catalog=classics` returned `22` models
  - includes `openrouter/google/gemini-2.5-flash-image`
- Live generation proof (deployed backend):
  - API job: `5047d7ad-a170-400e-916e-5604693c7390` (`completed`)
  - book: `1`
  - model: `openrouter/google/gemini-2.5-flash-image`
  - cover source: `drive`
  - compositor mode: `pdf`
  - output composite: `tmp/composited/1/openrouter__google__gemini-2.5-flash-image/variant_1.jpg`
  - output PDF: `tmp/composited/1/openrouter__google__gemini-2.5-flash-image/variant_1.pdf`
  - raw generated art: `tmp/generated/1/openrouter__google__gemini-2.5-flash-image/variant_1.png`
- Visual proof artifacts:
  - live iterate page: `/tmp/alexandria-proof-live/live-iterate-prompt21.png`
  - live dashboard page: `/tmp/alexandria-proof-live/live-dashboard-prompt21.png`
  - live composited cover proof: `/tmp/alexandria-proof-live/live-cover-book1-prompt21.jpg`

Prompts:

- `PROMPT-39-WILDCARD-EXPANSION-30-PLUS`
- `PROMPT-40-DAILY-ROTATION-AND-PROMPT-VALIDATION`
- `MANUSCRIPT-Prompt-Relevance-Strategy.pdf`

Release branch/worktree: `/private/tmp/alexandria-prompt40-relevance`

Functional release commit: `758ce1d`

Live app:

- [https://web-production-900a7.up.railway.app](https://web-production-900a7.up.railway.app)

Functional Railway deployment:

- `9a0d4ef5-49ed-4dca-b468-0045bc126335`
- status: `SUCCESS`

## What was implemented

1. Expanded Alexandria builtins from `10` total prompts to `35` total prompts:
   - `5` base prompts
   - `30` wildcard prompts
2. Converted the Alexandria prompt catalog to shared scene-first templates aligned with the manuscript strategy.
3. Added deterministic daily wildcard rotation in the Iterate frontend so the same book gets a stable day-based wildcard pick and genre-aware wildcard pool.
4. Added frontend prompt validation before queueing and backend prompt validation before generation execution.
5. Hardened both backend prompt-normalization paths so they do not silently destroy scene-first ordering.
6. Hardened startup prompt seeding so Alexandria prompt rows are repaired if names, templates, tags, or metadata drift.

## Scale validation

1. `scripts/validate_prompt_resolution.py --input config/book_catalog_enriched.json`
   - passed for all `2397` books
2. `scripts/validate_alexandria_prompt_relevance.py`
   - passed for all `35` Alexandria prompts
   - passed across `2397` books
   - checked `344050` resolved prompt combinations
   - issues: `0`
3. `config/prompt_library.json`
   - `45` total prompts
   - `35` Alexandria prompts
   - `30` Alexandria wildcards

## Targeted test verification

Passed:

- `python3 -m py_compile src/prompt_library.py src/image_generator.py scripts/quality_review.py scripts/validate_alexandria_prompt_relevance.py`
- `node --check src/static/js/pages/iterate.js`
- `pytest tests/test_prompt_library_module.py -q`
- `pytest tests/test_iterate_prompt_builder.py -q`
- `pytest tests/test_quality_review_utils.py -q -k 'prompt or placeholder or enrichment'`
- `pytest tests/test_quality_review_utils.py tests/test_image_generator_module.py -q -k 'scene_first or validate_prompt_relevance or ensure_prompt_book_context'`
- `pytest tests/test_quality_review_server_smoke.py -q -k 'generate_dry_run_resolves_placeholder_prompt_from_enrichment or iterate_books_view_filters_by_number'`

Full-suite honesty check:

- `pytest tests/ --maxfail=3 -q`
- still stops on `3` unrelated pre-existing failures in:
  - `tests/test_api_docs_route_matrix.py`
  - `tests/test_review_workflow.py`

## Live verification

1. `GET /api/health` returned:
   - `status=ok`
   - `healthy=true`
   - `books_cataloged=2397`
2. The deployed Iterate UI for book `4` (`Emma`) shows:
   - enriched scene text
   - enriched mood text
   - enriched era text
3. The deployed Iterate UI shows the new smart-rotation helper:
   - `Each variant uses the best prompt for this book's genre with a different scene`
   - `Today's pick: William Morris Textile`
4. The deployed resolved prompt preview shows a scene-first prompt with:
   - specific Emma scene text at the front
   - no unresolved placeholders
   - positive validation banner: `Resolved prompt looks specific and ready.`
5. A real live production run was queued and observed in the deployed UI for book `4`.
6. During visual proof capture, the deployed results grid reached `3 completed · 10 total`.

## Visual artifacts

Daily rotation picker:

- [`live-daily-rotation-picker-prompt40.png`](/private/tmp/alexandria-prompt40-release-20260310/live-daily-rotation-picker-prompt40.png)

Resolved prompt preview:

- [`live-resolved-prompt-preview-prompt40.png`](/private/tmp/alexandria-prompt40-release-20260310/live-resolved-prompt-preview-prompt40.png)

Iterate runtime screenshot:

- [`live-iterate-runtime-prompt40.png`](/private/tmp/alexandria-prompt40-release-20260310/live-iterate-runtime-prompt40.png)

Results grid screenshot:

- [`live-results-grid-prompt40.png`](/private/tmp/alexandria-prompt40-release-20260310/live-results-grid-prompt40.png)

## Honest residual issue observed during proof

The prompt-system goals are working, but the live browser proof surfaced an older artifact-delivery problem that is not fixed by PROMPT-39/40:

1. Result-card preview images still hit repeated `404` responses for some saved composite / thumbnail paths.
2. Because of that, several live result cards show blank preview placeholders even when result metadata and action buttons are present.

That is a real runtime artifact-preview issue. It does not invalidate the prompt-catalog expansion, daily rotation, or prompt-validation work, but it should not be misrepresented as fixed by this release.

---

# Hotfix Update: Result-card preview hardening

Date: `2026-03-10`

Hotfix commit:

- `c1f36bb` — `Harden asset and thumbnail preview delivery`

Hotfix Railway deployment:

- `eaf38c15-b08b-4174-8127-557b5682c7c4`
- status: `SUCCESS`

## What changed

1. Added server-side normalization for asset and thumbnail `path` tokens so encoded local paths and stale cache-buster suffixes no longer break lookup.
2. Added `/api/asset?path=...` as the safe full-resolution file endpoint for runtime artifacts.
3. Reworked Iterate preview/download/full-view URL generation so project-relative paths resolve through `/api/thumbnail` and `/api/asset` without double-encoding or leaking `?v=...` into the `path` payload.
4. Added regression coverage for:
   - encoded `path` tokens with cache-busters
   - Iterate preview source ordering
   - full-resolution asset resolution in the app shell
   - server smoke for `/api/asset` and `/api/thumbnail`

## Hotfix verification

Passed:

- `node --check src/static/js/app.js`
- `node --check src/static/js/pages/iterate.js`
- `pytest tests/test_thumbnail_server.py tests/test_app_asset_helpers.py tests/test_iterate_prompt_builder.py -q`
- `pytest tests/test_quality_review_server_smoke.py -q -k 'thumbnail_endpoint_rejects_non_image_and_disallowed_paths or asset_and_thumbnail_endpoints_accept_encoded_cachebuster_paths'`

Live verification on the deployed app:

1. `GET /api/health` returned:
   - `status=ok`
   - `healthy=true`
   - `books_cataloged=2397`
2. A real live Iterate run was queued and completed for book `4` (`Emma`) on the hotfix deployment.
3. The live result card rendered a real image preview instead of the previous empty fallback placeholder.
4. Opening the live result card rendered the full cover in the preview modal.
5. Captured network log shows:
   - `GET /api/asset?...saved_composites... => [200]`
   - no captured `404`, `500`, `502`, or `403` requests in the proof session
6. `Save Raw` still works after the hotfix:
   - live `POST /api/save-raw => [200]`
   - button state rerendered to `✓ Saved`
   - Google Drive folder link was present on the saved button state

## Hotfix visual artifacts

Live result card with restored preview:

- [`live-result-card-preview-fixed.png`](/private/tmp/alexandria-prompt40-relevance/output/playwright/preview-hardening/live-result-card-preview-fixed.png)

Live full-preview modal:

- [`live-full-preview-modal.png`](/private/tmp/alexandria-prompt40-relevance/output/playwright/preview-hardening/live-full-preview-modal.png)

Live result card after `Save Raw`:

- [`live-result-card-saved-state.png`](/private/tmp/alexandria-prompt40-relevance/output/playwright/preview-hardening/live-result-card-saved-state.png)

Supporting logs:

- [`live-network-preview.log`](/private/tmp/alexandria-prompt40-relevance/output/playwright/preview-hardening/live-network-preview.log)
- [`live-console-preview.log`](/private/tmp/alexandria-prompt40-relevance/output/playwright/preview-hardening/live-console-preview.log)

## Resolution status

The specific live issue called out above is resolved by this hotfix. Result-card preview delivery is now working on the deployed app, and the proof session did not reproduce the prior blank-card failure.
