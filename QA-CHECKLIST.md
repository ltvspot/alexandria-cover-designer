# Alexandria Cover Designer — QA Checklist (Current)

Last updated: `2026-03-05`

## 1. Blocking Visual Checks
- [x] Iterate page renders the new sidebar shell (no legacy layout fallback).
- [x] Dashboard renders `Latest Generated Covers` cards from persisted data.
- [ ] Fresh live-provider generation visually confirmed in this session (blocked locally: provider credentials unavailable).
- [ ] Manual visual signoff on at least 10 newly generated outputs (must be done per deploy environment).
- [ ] PROMPT-20 Im0 layer swap compositor implemented and visually verified by Tim.

## 2. Compositor Safety Checks (PROMPT-20 — Im0 Layer Swap)
- [x] `src/pdf_swap_compositor.py` created with Im0 layer swap logic.
- [x] PDF swap path integrated into `composite_single()` as try-first approach.
- [ ] ~~Blend radius ~950 from Im0 center preserves frame ring.~~ **FAILED** — r=938 covers the entire frame. See PROMPT-21.
- [x] SMask preserved unchanged (never modified).
- [x] Falls back to legacy three-layer approach when PDF swap fails.
- [ ] Visual comparison grids committed to `qa_output/` for books 1/2/10/25/50/75.
- [ ] Tim visually confirms composites look correct.

## 2b. PROMPT-21 Fixes (Blend Radius & Guardrail)
- [x] `detect_blend_radius_from_smask()` returns hardcoded 840 (not SMask-based 938). Verified at line 150.
- [x] `min()` clamping on `effective_outer_radius` removed. Verified.
- [x] `hard_frame_artifact` threshold raised from 0.22 to 0.35. Verified at line 1275.
- [x] Individual `ring_penalty`/`frame_penalty` thresholds raised from 0.14 to 0.22. Verified at lines 2425/2427.
- [x] Test composites generated for books 1/2/10/25/50/75 — frame fully intact in all. Visually confirmed.
- [x] Comparison images saved to `qa_output/classics/`. 6 sheets present.
- [ ] Tim visually confirms frame is clean and no art overlaps ornaments.
- [x] ~~`config/compositing_mask.png` exists~~ (bypassed by Im0 swap — no longer used).
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
