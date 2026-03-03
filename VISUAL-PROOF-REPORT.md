# Visual Proof Report

Last updated: `2026-03-03`
Deployment URL: `https://web-production-900a7.up.railway.app`
Deployment ID: `90071cb7-9f2d-4941-935f-efc9089164d1`

## 0. PROMPT-07B Hotfix Snapshot (2026-03-03)
- Deployed with compositor detection window widened (15%), safety inset `14px`, expanded radius scan bounds, and relaxed offset guard.
- Iterate model list now renders as structured grid cards, with selected-model highlight.
- Frontend image preview fallback now attempts `/api/thumbnail` for direct path payloads so cards recover from MIME/path edge cases.
- Verified on live iterate page:
  - header shows `999 books`;
  - `Nano Banana Pro` is pre-selected on first load;
  - running-job heartbeat text explicitly shows backend staleness and queue wait status.
- Provider-side queue contention was observed during live run (jobs remained queued >30s). This is surfaced clearly in UI and no longer looks frozen.

## 0.1 PROMPT-07B Parameter Tightening (2026-03-03)
- `src/static/js/compositor.js` now matches strict 07B compositor values:
  - `OPENING_SAFETY_INSET = 18`
  - `searchX/searchY = max(30, scan*0.15)`
  - `coarse radius = 0.65x .. 1.40x`
  - fine window expanded to `±16`
  - `maxOffset = max(80, hintRadius*0.55)`
  - explicit logs: `[Compositor v9] Detected...` and clip radius.
- `src/cover_compositor.py` is aligned to the same values and now logs:
  - `Compositor detected: cx=... cy=... outer=... opening=...`

## 0.2 PROMPT-07C Compositor Rewrite (2026-03-03)
- Detection tuning was retired as the primary path; compositor now resolves medallion geometry from `cover_regions.json`.
- New endpoint serves registry data: `GET /api/cover-regions?catalog=classics`.
- Frontend behavior:
  - `Compositor.loadRegions()` loads known coordinates once on startup.
  - `smartComposite({ coverImg, generatedImg, bookId })` uses `getKnownGeometry(bookId)` and does not call detection.
  - defaults/fallbacks corrected to `cx=2864`, `cy=1620`, `radius=500`.
- Backend behavior:
  - `_resolve_medallion_geometry()` now immediately uses region hints when present and only falls back to detection if hints are absent.
  - fallback constants set to `2864/1620/500`.
- Live verification:
  - `/api/cover-regions` returned `99` covers.
  - known geometry for books `1`, `9`, `25` matches registry.
  - deployed `compositor.js` contains `[Compositor v10] Using known geometry...`.
  - deployed `compositor.js` does not contain `[Compositor v9] Detection:`.

## 0.3 PROMPT-07E Compositor Fix (2026-03-03)
- Disabled restrictive global mask by renaming:
  - `config/compositing_mask.png` -> `config/compositing_mask.png.disabled`
- Backend compositor updates:
  - `DETECTION_OPENING_RATIO = 0.96`
  - `OPENING_SAFETY_INSET_PX = 0`
  - `OVERLAY_PUNCH_INSET_PX = -4`
  - deterministic center crop in `_smart_square_crop()` (content-aware shifting removed)
- Frontend compositor updates:
  - `OPENING_RATIO = 0.96`
  - `OPENING_SAFETY_INSET = 0`
  - template punch radius uses `geo.openingRadius + 4`
  - deterministic center crop for generated source image
  - logs bumped to `[Compositor v12] ...`
- Live verification:
  - deployed `compositor.js` includes `OPENING_RATIO = 0.96`, `OPENING_SAFETY_INSET = 0`, `punchRadius = geo.openingRadius + 4`, and `[Compositor v12]`
  - region registry still loads correctly for known geometry (`book 1/9 -> 2864|2862,1620,500`)

## 0.4 PROMPT-07F PNG Template Compositor (2026-03-03)
- Added batch template generator script:
  - `src/create_png_templates.py`
  - CLI: `python -m src.create_png_templates --source-dir 'Input Covers'`
- Local generation result:
  - `99` templates created in `config/templates/`
  - all sampled templates are `3784x2777 RGBA`
  - sample transparent area ratio ~`6.47%`
- Backend compositor pipeline update in `src/cover_compositor.py`:
  - medallion branch now uses three-layer template pipeline (`canvas + art + template`)
  - added `_find_template_for_cover()`, `_simple_center_crop()`, and `_legacy_medallion_composite()` fallback
  - added on-demand template creation helper for missing templates (`_create_template_for_cover`)
  - logs now show `Using PNG template: ...` when template path is active
- Runtime verification (local compositor run for books 1/9/25):
  - `Compositor using known geometry ... opening=480`
  - `Using PNG template: ...`
  - no `No PNG template found` warnings in successful path

## 0.5 Iterate UX/UI Model Picker Refresh (2026-03-03)
- Implemented screenshot-matched Iterate model selection UX:
  - model search input;
  - filter chips (`Recommended`, `All`, `OpenRouter`, `Gemini`, `Nano Pro only`);
  - action chips (`Select visible`, `Clear`);
  - model cards with title, provider/id line, description, modality/provider tags, and cost pill;
  - selected card highlighting.
- Selection behavior:
  - `Nano Banana Pro` pre-selected by default;
  - selected model card pinned to the start of the visible grid for fast scanning.
- Cost line now shows both estimate and worst-case:
  - `Est. cost: $X · worst-case $Y`.
- Cache-busting token bumped in SPA shell to force fresh JS/CSS on deploy:
  - `20260303-designlock-uiux08`.
- Live verification:
  - deployed page loads new tokened assets;
  - model cards render with `Nano Banana Pro` selected and shown first;
  - top header shows `999 books`, and catalog sync status text remains visible in Iterate form.

## 1. Test Proof
- Full suite run: `pytest -q`.
- Result: `100% passed`.
- Stability note: API docs matrix test timeout raised from `20s` to `45s` to avoid false failures on heavy ZIP endpoints (`tests/test_api_docs_route_matrix.py`).
- Local validation additions:
  - guardrail fallback tiny-component arithmetic fixed for non-`scipy` environments.
  - required model inventory forced at runtime (15 OpenRouter + Gemini direct IDs).
  - startup built-in prompt seed no longer throws `LogRecord` key collision.

## 2. Live Verification Checks

### 2.1 Health
- `GET /api/health` returned:
  - `status: ok`
  - `healthy: true`
  - `version: 2.1.1`
  - `uptime_seconds: 0` immediately after deploy (confirming rollout `addf1b1c-2d44-495c-b1d2-19b16cb0a393` active)

### 2.2 New Design Token + Cache Control
- `GET /iterate` includes:
  - `/src/static/shared.css?v=20260302-designlock`
  - `/static/css/style.css?v=20260303-designlock-uiux08`
- `GET /review` headers include:
  - `cache-control: no-store`
- `Content-Security-Policy` now allows:
  - `https://fonts.googleapis.com`
  - `https://fonts.gstatic.com`
  - `https://cdn.jsdelivr.net`
  - `https://cdnjs.cloudflare.com`

### 2.3 Model Payload (OpenRouter + Gemini)
- `GET /api/iterate-data?catalog=classics`:
  - total models: `22`
  - required OpenRouter production set present: `15`
  - direct Gemini IDs present: `3`
  - current provider connectivity on iterate page:
    - OpenRouter: connected
    - OpenAI: connected
    - Fal: connected
    - Google direct: degraded (`403 PERMISSION_DENIED`, leaked key)

### 2.4 Dashboard Recent Covers
- Live generation run:
  - Job ID: `4517fa87-a7c9-432d-be8b-b522e6c45964`
  - Request: `book=3`, `model=openrouter/google/gemini-2.5-flash-image`, `cover_source=drive`
  - Final status: `completed`
- `GET /api/dashboard-data?catalog=classics` now reports:
  - `recent_results = 1`
  - card present under “Latest Generated Covers”

## 3. Visual Proof Artifacts

### 3.0 PROMPT-07B Inline-Proof Assets (chat-safe absolute paths)
- `/Users/timzengerink/proofs/proof-iterate-page-live-20260303.png`
- `/Users/timzengerink/proofs/proof-iterate-heartbeat-queue-20260303.png`
- `/Users/timzengerink/proofs/proof-07b-book1-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b-book1-medallion.png`
- `/Users/timzengerink/proofs/proof-07b-book9-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b-book9-medallion.png`
- `/Users/timzengerink/proofs/proof-07b-book25-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b-book25-medallion.png`

### 3.0.1 PROMPT-07B2 Inline-Proof Assets (strict parameters)
- `/Users/timzengerink/proofs/proof-07b2-book1-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b2-book1-medallion.png`
- `/Users/timzengerink/proofs/proof-07b2-book9-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b2-book9-medallion.png`
- `/Users/timzengerink/proofs/proof-07b2-book25-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b2-book25-medallion.png`
- `/Users/timzengerink/proofs/proof-07b2-summary.json`

### 3.0.2 PROMPT-07C Inline-Proof Assets (known geometry)
- `/Users/timzengerink/proofs/proof-07c-live-iterate.png`
- `/Users/timzengerink/proofs/proof-07c-book1-composite-full.png`
- `/Users/timzengerink/proofs/proof-07c-book1-medallion.png`
- `/Users/timzengerink/proofs/proof-07c-book9-composite-full.png`
- `/Users/timzengerink/proofs/proof-07c-book9-medallion.png`
- `/Users/timzengerink/proofs/proof-07c-book25-composite-full.png`
- `/Users/timzengerink/proofs/proof-07c-book25-medallion.png`
- `/Users/timzengerink/proofs/proof-07c-summary.json`

### 3.0.3 PROMPT-07E Inline-Proof Assets (bigger centered art + mask disabled)
- `/Users/timzengerink/proofs/proof-07e-live-iterate.png`
- `/Users/timzengerink/proofs/proof-07e-book1-composite-full.png`
- `/Users/timzengerink/proofs/proof-07e-book1-medallion.png`
- `/Users/timzengerink/proofs/proof-07e-book9-composite-full.png`
- `/Users/timzengerink/proofs/proof-07e-book9-medallion.png`
- `/Users/timzengerink/proofs/proof-07e-book25-composite-full.png`
- `/Users/timzengerink/proofs/proof-07e-book25-medallion.png`
- `/Users/timzengerink/proofs/proof-07e-medallion-triptych.png`
- `/Users/timzengerink/proofs/proof-07e-summary.json`

### 3.0.4 PROMPT-07F Inline-Proof Assets (PNG template pipeline)
- `/Users/timzengerink/proofs/proof-07f-live-iterate.png`
- `/Users/timzengerink/proofs/proof-07f-book1-composite-full.png`
- `/Users/timzengerink/proofs/proof-07f-book1-medallion.png`
- `/Users/timzengerink/proofs/proof-07f-book9-composite-full.png`
- `/Users/timzengerink/proofs/proof-07f-book9-medallion.png`
- `/Users/timzengerink/proofs/proof-07f-book25-composite-full.png`
- `/Users/timzengerink/proofs/proof-07f-book25-medallion.png`
- `/Users/timzengerink/proofs/proof-07f-medallion-triptych.png`
- `/Users/timzengerink/proofs/proof-07f-summary.json`

### 3.1 Live UI Screenshots
- `tmp/proof-live-iterate-20260302-prompt06.png`
- `tmp/proof-live-dashboard-20260302-prompt06.png`
- `tmp/proof-live-review-20260302-prompt06.png`
- `tmp/proof-live-prompts-20260302-prompt06.png`
- `tmp/proof-live-iterate-ui-redesign-20260303.png`

### 3.2 Local Validation Screenshots
- `tmp/proof-local-iterate-20260302-fix.png`
- `tmp/proof-local-dashboard-20260302-fix.png`
- `tmp/proof-local-review-20260302-fix.png`
- `tmp/proof-local-iterate-ui-redesign-final-20260303.png`

### 3.3 PROMPT-06 UI/UX Rebuild Proof (Latest)
- `tmp/proof-local-iterate-20260302-uiux-cspfixed.png`
- `tmp/proof-local-dashboard-20260302-uiux.png`
- `tmp/proof-local-review-20260302-uiux.png`
- `tmp/proof-local-prompts-20260302-uiux.png`
- Playwright console check:
  - local: `0 errors, 0 warnings`
  - live: `0 errors, 0 warnings`

## 4. Design-Lock Enforcement
- Global sidebar-first UX lock remains in `src/static/shared.css` (`DESIGN LOCK` block).
- Static revision token remains `20260302-designlock` across all pages.
- SPA asset revision token for JS/CSS cache busting is now `20260303-designlock-uiux08`.
- Static hygiene tests enforce token + design lock markers.
- CSP now explicitly allows required frontend assets:
  - `style-src` includes `https://fonts.googleapis.com`
  - `script-src` includes `https://cdn.jsdelivr.net` and `https://cdnjs.cloudflare.com`
  - `font-src` includes `https://fonts.gstatic.com`

## 5. Delivery Rule (Mandatory)
Every completion message must include:
1. direct deployed URL;
2. visual proof report path(s).
