# Alexandria Cover Designer — QA Checklist (Current)

Last updated: `2026-03-01`

## 1. Blocking Visual Checks
- [x] Iterate page renders the new sidebar shell (no legacy layout fallback).
- [x] Dashboard renders `Latest Generated Covers` cards from persisted data.
- [ ] Fresh live-provider generation visually confirmed in this session (blocked locally: provider credentials unavailable).
- [ ] Manual visual signoff on at least 10 newly generated outputs (must be done per deploy environment).

## 2. Compositor Safety Checks
- [x] `src/cover_compositor.py` conservative constants are intact.
- [x] `MIN_OPENING_MARGIN_PX = 72` guard is present.
- [x] `config/compositing_mask.png` exists and is strict-inner-opening.
- [x] compositor regression tests pass.

## 3. Prompt + Generation Hardening Checks
- [x] Prompt guardrail enforces no-text/no-frame/no-banner/no-seal directives.
- [x] Prompt cleanup removes malformed residual fragments (e.g., `", no,"`).
- [x] Model signature formatting no longer duplicates provider prefixes.
- [x] OpenRouter 429 path respects `Retry-After` backoff.
- [x] Artifact-heavy outputs trigger guardrail rejection paths.

## 4. UX/Model Coverage Checks
- [x] Asset revision token `?v=20260302-designlock` is present across static pages.
- [x] HTML/CSS/JS routes serve with `Cache-Control: no-store`.
- [x] Iterate model set includes configured Gemini image IDs.
- [x] Prompt text is visible under dashboard generated cards.
- [x] Prompt save/display workflow remains visible in iterate controls.

## 5. API/Health Checks (Local Snapshot)
- [x] `GET /api/health` returns ok payload.
- [x] `GET /api/iterate-data?catalog=classics` returns model/book payload.
- [x] `GET /api/dashboard-data?catalog=classics` returns populated `recent_results`.

## 6. Test Suite
- [x] Full `pytest` passes after latest code/doc updates.
- [x] Focused regression suites pass:
  - `tests/test_image_generator_module.py`
  - `tests/test_prompt_generator_module.py`
  - `tests/test_cover_compositor_module.py`
  - `tests/test_quality_review_utils.py`

## 7. Proof Paths (Current Session)
- `tmp/proof-local-iterate-ui-20260301-v211.png`
- `tmp/proof-local-dashboard-ui-20260301-v211.png`

## 8. Pre-Handoff Rule
Do not claim production-complete visual quality unless section 1 items for fresh live-provider output are checked in the target deployed environment.

## 9. Mandatory User Delivery Rule
- [ ] Direct deployed webapp link included in the message.
- [ ] Visual proof report path(s) included in the message.
- [ ] Both items provided together every time (no exceptions).
- [ ] `VISUAL-PROOF-REPORT.md` updated for this deployment.
