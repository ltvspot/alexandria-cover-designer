# VISUAL PROOF REPORT

Date: 2026-03-10

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
