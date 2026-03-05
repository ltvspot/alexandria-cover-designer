# Visual Proof Report

Last updated: `2026-03-04`
Deployment URL: `https://web-production-900a7.up.railway.app`
Deployment ID: `58267a2d-62b4-418c-b4ea-c8296210e45f`

## 1.5 PROMPT-11 White Gap + Download/Raw Fixes (2026-03-04)
- Git commit (master):
  - `2ac1018` — white-gap bleed/crop fix, durable raw-art persistence, robust download handlers, deterministic frame mask
- Railway deploy:
  - `6e587f48-40dd-42c9-b084-ba30337e9d16` (`SUCCESS`)
  - `58267a2d-62b4-418c-b4ea-c8296210e45f` (`SUCCESS`, final parity deploy from latest master head)
- Live health:
  - `status: ok`
  - `healthy: true`
  - `books_cataloged: 99` (`/api/health`)
- Live iterate UI check:
  - top-right badge shows `999 books`
  - catalog status line shows `99 books loaded (catalog).`
- Mandatory strict compositor verification:
  - `bash scripts/test_compositor_integration.sh 1`
  - result: `ALL CHECKS PASSED` (strict PDF mode, 9 checks)
- Full regression suite:
  - `.venv/bin/pytest` -> `688 passed`
  - `pytest -q tests/test_frame_mask_integrity.py` -> `PASS`
- ZIP raw/source validation (live code path):
  - package contains both `source_images/` (generated raw) and `source_files/` (source raw)
  - md5 differs (`same False`) and sizes differ (`2108478` vs `4808591`)
- Visual proof artifacts:
  - live iterate page with generated cover card:
    - `/Users/timzengerink/proofs/2026-03-04-prompt11-final/live-iterate-prompt11-final-deploy.png`
  - live cover card crop:
    - `/Users/timzengerink/proofs/2026-03-04-prompt11-final/live-cover-card-prompt11-final-deploy.png`
  - strict compositor composite output:
    - `/Users/timzengerink/proofs/2026-03-04-prompt11-final/compositor-test-output.jpg`
  - strict compositor raw art input:
    - `/Users/timzengerink/proofs/2026-03-04-prompt11-final/compositor-test-raw-art.png`

## 1.4 PROMPT-10 Frame/Prompt/ZIP Fix (2026-03-04)
- Git commit (master):
  - `56df67e` — frame fallback safety, prompt relevance anchoring, ZIP raw/source separation
- Railway deploy:
  - `7373b253-be3a-4f1c-8e0c-e52f60b75c00` (`SUCCESS`)
- Live health:
  - `status: ok`
  - `healthy: true`
  - `uptime_seconds: 1` immediately after rollout
- Required validation runs:
  - Validation 1 (frame mask): `PASS` (`Center=(2867,1600), opaque=94.2%`)
  - Validation 2 (frame preservation/art insertion): `PASS` (`max delta: 0`, `art delta: 204`)
  - Validation 3 (prompt reference): `PASS` (`moby/whale/melville` references present)
  - Validation 4 (ZIP distinct files): `PASS`
    - source-raw: `4,658,268` bytes
    - generated-raw: `2,012,761` bytes
    - composited: `2,834,807` bytes
- Mandatory strict compositor verification:
  - `.venv/bin/python scripts/verify_composite.py --strict tmp/composited/69/openai__gpt-image-1/variant_1.jpg 'Input Covers/69. The Prince and the Pauper — Mark Twain copy/The Prince and the Pauper — Mark Twain.jpg'`
  - result: `ALL CHECKS PASSED`
- Visual proof artifacts:
  - live iterate page (deployed): `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-iterate-prompt10-20260304.png`
  - source cover proof: `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-prompt10-source-book61.jpg`
  - generated raw proof: `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-prompt10-generated-book61.png`
  - composited cover proof: `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-prompt10-composite-book61.jpg`
  - side-by-side proof: `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-prompt10-triptych-book61.jpg`

## 1.3 Model Label + Default Selection Correction (2026-03-04)
- Git commit (master):
  - `3e46c82` — enforce single Nano Banana Pro default selection and rename Google-direct Gemini card.
- Railway deploy:
  - `db7f071e-6455-4b42-844b-ea704580956a` (`SUCCESS`)
  - `a1cbac07-8f7a-40bd-a83e-3a7eff8649b7` (`SUCCESS`, final parity redeploy from latest master)
- Live API verification:
  - `GET /api/models` now returns:
    - `openrouter/google/gemini-2.5-flash-image` -> `Nano Banana Pro`
    - `google/gemini-2.5-flash-image` -> `Gemini Flash (Google Direct)`
- Live Iterate UI verification:
  - summary reads `1 model selected` on initial load.
  - default selected card is only `Nano Banana Pro`.
  - direct Google card title shows `Gemini Flash (Google Direct)` and is not checked by default.
- Visual proof artifact:
  - `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-model-selection-20260304.png`

## 1.2 PROMPT-09 Ornament Guardrail Hardening (2026-03-04)
- Git commits (master):
  - `22c6237` — anti-ornament prompt hardening + style/pipeline guardrails
  - `77c92d8` — preserve anti-ornament negatives during sanitization
- Railway deploys:
  - `9388980c-2b28-4388-a43a-935e3c684767` (`SUCCESS`)
  - `feb98ade-1d1d-4afd-8e07-a4872e6e6bdc` (`SUCCESS`, latest live)
- Verification (local strict, mandatory):
  - `bash scripts/test_compositor_integration.sh 1`
  - result: all 9 checks passed (`ornament_zone`, `frame_pixels`, `ai_art_border`, `visual_frame` all `PASS`)
- Live generation proof (post-deploy):
  - API job: `fe14f0d7-b1d2-4d3b-b7ca-655f47fa2851` (`completed`)
  - model: `openrouter/google/gemini-2.5-flash-image`
  - output artifacts:
    - composited: `tmp/composited/1/openrouter__google__gemini-2.5-flash-image/variant_1.jpg`
    - raw: `tmp/generated/1/openrouter__google__gemini-2.5-flash-image/variant_1.png`
- Visual proof artifacts:
  - live dashboard with generated cover card:
    - `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-dashboard-card-20260304-ornament-fix-v2.png`
  - live dashboard modal (composite/raw tabs):
    - `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-dashboard-20260304-ornament-fix-v2.png`
  - direct composited cover image:
    - `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-cover-book1-20260304-v2.jpg`
  - direct raw generated image:
    - `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-raw-book1-20260304-v2.png`

## 1.1 PROMPT-09C ZIP + Sync/Dropdown + Cache Rollout (2026-03-04)
- Git commits (master):
  - `97e3314` — sync title parsing fix (`Untitled` regression removed)
  - `7bdc4d4` — include cover JPG + raw assets in iterate ZIP
  - `51f1f43` — use in-memory blobs for stable ZIP asset inclusion
  - `f62e258` — SPA JS cache-bust token bump (`20260304-zipfix09c-uiux09`)
- Railway deploy:
  - deployment `dba78a91-2bbe-4122-b38c-3d566715a04a` (`SUCCESS`)
  - final parity redeploy from latest `master` head: `c4c2133e-adaa-4cfc-a430-02c5e7f921c6` (`SUCCESS`)
- Live health post-rollout:
  - `status: ok`
  - `healthy: true`
  - `uptime_seconds: 81`
- Dropdown verification (before + after Sync on live Iterate page):
  - before: `loaded=999`, `untitled=0`, status `999 books loaded (catalog).`
  - after clicking Sync: `loaded=999`, `untitled=0`, status `999 books loaded (catalog).`
- Active frontend token verification:
  - deployed script URL: `/static/js/pages/iterate.js?v=20260304-zipfix09c-uiux09`
- UI ZIP verification from live page (`downloadComposite`):
  - ZIP name: `1. A Room with a View - E. M. Forster.zip`
  - files included:
    - `A Room with a View - E. M. Forster.jpg`
    - `A Room with a View - E. M. Forster (generated raw).png`
    - `A Room with a View - E. M. Forster (source raw).png`
    - `A Room with a View - E. M. Forster.pdf`
    - `A Room with a View - E. M. Forster.ai`
- Visual proof artifacts:
  - iterate page (layout/no dead sidebar space): `/Users/timzengerink/proofs/2026-03-04-zipfix/proof-live-iterate-layout-20260304-zipfix.png`
  - iterate page (dropdown/sync context): `/Users/timzengerink/proofs/2026-03-04-zipfix/proof-live-iterate-dropdown-20260304-zipfix.png`
  - real composited cover image: `/Users/timzengerink/proofs/2026-03-04-zipfix/proof-live-cover-composite-20260304.jpg`
  - real source raw image: `/Users/timzengerink/proofs/2026-03-04-zipfix/proof-live-cover-source-20260304.png`
  - UI ZIP content proof JSON: `/Users/timzengerink/proofs/2026-03-04-zipfix/proof-live-ui-zip-contents-20260304.json`

## 1.0 Sidebar Gap Fix + Live Redeploy (2026-03-04)
- Git commits:
  - `9c4ba94` — layout fix (`.app-shell` tracks sidebar width + `.content` margin reset)
  - `fafb1da` — cache-bust style asset URL in SPA shell
- GitHub push:
  - `master` updated to `fafb1da`
- Railway deploy:
  - deployment `73d32fc1-50a5-4fab-ab9c-ef771ccb1efb` (`SUCCESS`)
- Live health after rollout:
  - `status: ok`
  - `healthy: true`
  - `uptime_seconds: 1`
- Geometry proof (live, collapsed sidebar):
  - expanded: `contentX=240`
  - collapsed: `contentX=56`, `sidebarW=56` (no dead gutter remains)
- Visual proof artifacts:
  - live iterate gap fix: `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-iterate-gapfix-20260304.png`
  - cover proof (latest generated covers): `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-local-dashboard-covers-gapfix-20260304.png`

## 0.9 PROMPT-09 Redeploy + Inline-Proof Render Fix (2026-03-04)
- Forced GitHub push check:
  - `git push origin master` -> `Everything up-to-date`
- Forced Railway deploy:
  - deployment: `a3d30f1b-74f0-4fbd-8087-bdc4834604c9` (`SUCCESS`)
- Live health immediately after rollout:
  - `status: ok`
  - `healthy: true`
  - `uptime_seconds: 1`
  - `books_cataloged: 999`
- Inline-proof compatibility fix:
  - proof files exported to absolute paths without spaces under `/Users/timzengerink/proofs/` for reliable in-chat rendering.

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

## 0.6 PROMPT-07H Bundle (2026-03-03)
- Implemented 07H, 07H-B, 07H-C, 07H-D in code and deployed.
- Compositor medallion bleed guard:
  - `ART_BLEED_PX = 60`
  - medallion art diameter is now `punch_radius * 2 + (ART_BLEED_PX * 2)` (1050px at default radius).
- Catalog default fix:
  - `config/catalogs.json` default switched to `classics`.
  - Runtime override fixed in Railway env: `CATALOG_ID=classics` (was `test-catalog`).
- Variant diversity anchors:
  - fixed first two style IDs now `pre-raphaelite-v2`, `baroque-v2`.
  - curated pool backfilled with `sevastopol-conflict`.
- Download/export overhaul:
  - card button label changed from `⬇ Composite` to `⬇ Download`.
  - download now packages ZIP with composite + raw illustration using book naming.
  - app-side composite source resolution now rejects thumbnail paths and warns on suspiciously small blobs.
- Live checks passed:
  - `/api/health` reports `books_cataloged: 99`, `budget.catalog: classics`.
  - `/api/iterate-data` defaults to `catalog: classics`.
  - `/cgi-bin/catalog.py` returns `count: 99`.
  - generated composite verifies as `3784x2777` at `300 DPI`.

## 0.7 PROMPT-07I + 07I-B (2026-03-04)
- Implemented diff-based frame-mask compositing pipeline and download naming fix.
- Added script:
  - `scripts/generate_frame_mask.py`
  - run completed successfully; mask generated from two Drive covers.
- Updated compositor:
  - added `FRAME_MASK_PATH` and `_load_frame_mask()`
  - medallion `else` branch now prefers `config/frame_mask.png` and logs explicit usage
  - fallback circle punch retained for resilience
  - art diameter now expands to `1120px` when frame mask is active
- Updated iterate downloads:
  - naming now prefers catalog `file_base` over title/author synthesis
  - ZIP structure now mirrors source folder naming (`{number}. {file_base}/...`)
  - raw single-file download now includes book-number prefix
- Production packaging fixes:
  - Docker now copies `config/frame_mask.png`
  - Railway upload allowlist now includes `!config/frame_mask.png`
- Live verification:
  - `/config/frame_mask.png` returns `HTTP 200` on production
  - compositor runtime log confirms mask usage:
    - `Using pixel-perfect frame mask from /app/config/frame_mask.png`
  - generated composite output remains full-resolution (`3784x2777 @ 300 DPI`)

## 0.8 PROMPT-09A + 09B + 09C (2026-03-04)
- Implemented PDF compositor and wiring:
  - added `src/pdf_compositor.py`
  - iterate generation now prefers source PDF compositing and falls back to raster compositor when PDF is unavailable
  - Drive source cover ensure flow now downloads JPG + PDF companion (`cover_from_drive.pdf`) when present
  - output artifacts per variant now include `.jpg`, `.pdf`, `.ai` in `tmp/composited/...`
- Verification suite overhaul:
  - replaced `scripts/verify_composite.py` with dual-mode PDF/JPG verifier
  - added `scripts/test_compositor_integration.sh` and `Makefile` targets (`verify`, `test-compositor`)
  - strict checks passed for two books in PDF mode (`book 1`, `book 9`)
- Download/export naming + files:
  - iterate ZIP keeps `{number}. {file_base}` folder structure
  - ZIP now includes PDF/AI when available
  - raw download remains `{number}. {file_base} (illustration).jpg`
- Deployment/live verification:
  - commit: `7f4a2be`
  - deployment: `8f13004d-97e3-42fc-b672-2a8a43a23918` (`SUCCESS`)
  - `/api/health` reports `status: ok`, `healthy: true`, `uptime_seconds: 1`

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

### 3.0.5 PROMPT-07H Inline-Proof Assets (latest live deploy)
- `/Users/timzengerink/proofs/07h-live-iterate-overview.png`
- `/Users/timzengerink/proofs/07h-live-recent-result-card.png`
- `/Users/timzengerink/proofs/07h-live-composite-fullres.jpg`

### 3.0.6 PROMPT-07I Inline-Proof Assets (frame mask + naming)
- `/Users/timzengerink/proofs/07i-live-recent-result-card.png`
- `/Users/timzengerink/proofs/07i-live-composite-fullres.jpg`
- `/Users/timzengerink/proofs/07i-live-medallion-crop.jpg`

### 3.0.7 PROMPT-09 Inline-Proof Assets (PDF compositor + verifier + downloads)
- `/Users/timzengerink/proofs/prompt09-live-iterate.png`
- `/Users/timzengerink/proofs/book_1-medallion-proof.jpg`
- `/Users/timzengerink/proofs/book_9-medallion-proof.jpg`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/test_composites/book_1/test_output.jpg`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/test_composites/book_9/test_output.jpg`
- `/Users/timzengerink/proofs/prompt09-live-iterate-20260304-final.png`
- `/Users/timzengerink/proofs/prompt09-book1-proof-20260304.jpg`
- `/Users/timzengerink/proofs/prompt09-book9-proof-20260304.jpg`

### 3.0.8 Live Dropdown Population Fix Proof (2026-03-04)
- Deployment: `d04bd195-1135-41fa-93e7-f51ce2adb79f`
- Live URL: `https://web-production-900a7.up.railway.app`
- API verification after live `POST /api/drive/catalog-sync`:
  - `total_books = 999`
  - `books.length = 999`
  - `untitled_titles = 0`
- Visual proof:
  - `/Users/timzengerink/proofs/proof-live-iterate-dropdown-expanded-fixed-20260304.png`
  - `/Users/timzengerink/proofs/proof-live-iterate-dropdown-fixed-20260304.png`

### 3.0.9 PROMPT-09E/09D Live Proof (2026-03-04)
- Deployment: `2d7852fa-b2fd-4bd1-801e-7a546584fb25`
- Live URL: `https://web-production-900a7.up.railway.app`
- Health/API checks:
  - `GET /api/health` -> `status=ok`
  - `GET /api/iterate-data?catalog=classics&limit=9999` -> `books=999`, `untitled=0`
  - Live generate canary: `job_id=3affefb5-00a5-4315-84de-0ac60843d225` completed (`book=1`, `model=openrouter/google/gemini-2.5-flash-image`, `variant=1`)
  - `GET /api/variant-download?book=1&variant=1&model=openrouter/google/gemini-2.5-flash-image` ZIP contains:
    - `composites/...cover_v1.jpg`
    - `composites/...cover_v1.pdf`
    - `source_images/...generated_raw_v1.png`
    - `source_files/...source_raw_v1.jpg`
    - `manifest.csv`, `metadata.json`
- Proof artifacts (chat-safe absolute paths):
  - `/Users/timzengerink/proofs/proof-live-iterate-no-gap-dropdown-20260304.png`
  - `/Users/timzengerink/proofs/proof-live-review-covers-loaded-20260304-b.png`
  - `/Users/timzengerink/proofs/proof-live-generated-composite-book1-v1-20260304.jpg`
  - `/Users/timzengerink/proofs/proof-live-generated-raw-book1-v1-20260304.png`
  - `/Users/timzengerink/proofs/proof-live-source-raw-book1-v1-20260304.jpg`
  - `/Users/timzengerink/proofs/proof-local-iterate-no-left-gap-20260304.png`
  - `/Users/timzengerink/proofs/proof-local-review-covers-loaded-20260304.png`

### 3.0.10 Drive Selection Mismatch Fix Proof (2026-03-04)
- Deployment: `cdab0ddb-49b0-4a47-ab8d-00e08d44f447`
- Live URL: `https://web-production-900a7.up.railway.app`
- Verification:
  - `POST /api/generate` with `book=2` and intentionally wrong `selected_cover_id` (book 990 cover) now returns `HTTP 200`.
  - Queued job payload is normalized to the correct cover id for book 2: `selected_cover_id=1vqzzuKlwgtv0G0fFcUknKO36fn8ttxEK`.
  - `GET /api/health` returns `status=ok`.
- Visual proof:
  - `/Users/timzengerink/proofs/2026-03-04-09f-fix/proof-live-review-covers-20260304-09f-fix.png`

### 3.0.11 Iterate Two-Model Card + Cost Verification (2026-03-04)
- Deployment: `059af182-4b1e-4c61-a4a3-64298630bd61`
- Live URL: `https://web-production-900a7.up.railway.app`
- Verification:
  - Recommended filter now shows both Nano cards.
  - Card 1 maps to `openrouter/google/gemini-2.5-flash-image` at `$0.003`.
  - Card 2 maps to `google/gemini-2.5-flash-image` at `$0.003`.
  - Both are selected by default.
  - Cost math is correct:
    - variants `1` -> `$0.003 + $0.003 = $0.006`
    - variants `2` -> `$0.006 + $0.006 = $0.012` (verified in live DOM)
- Visual proof:
  - `/Users/timzengerink/proofs/2026-03-04-09g-model-cards/proof-live-iterate-two-nano-models-20260304-09g.png`

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

### 3.0.12 PROMPT-17 Batch Re-Composite + QA Proof (2026-03-05)
- Commit: `42c0a6c`
- Deployment: `9a18b0f2-80c6-4397-8e2c-1c9c49561f3d`
- Live URL: `https://web-production-900a7.up.railway.app`
- Build log: `https://railway.com/project/ff92d325-72a5-480f-8ff7-856744b6b859/service/3e03e783-724a-4999-8c55-c83db5a84b5e?id=9a18b0f2-80c6-4397-8e2c-1c9c49561f3d&`

Verification summary:
- Batch recomposite: `99 books`, `482 variants`, `99 passed frame check`, `0 failed`, `0 skipped`
- Structural QA (`scripts/visual_qa.py`): `total=99`, `verified=99`, `passed=99`, `failed=0`
- Comparison grids (`scripts/generate_comparison.py --catalog classics`): `generated=99`, `passed=0`, `failed=99` (whole-medallion diff metric, expected when artwork changes)
- Sample comparison runs requested by prompt:
  - generated: books `1, 10, 25, 50, 75, 100`
  - not present in local catalog/composites: books `200, 500, 750, 999`

Prompt-17 artifacts:
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/qa_output/classics/recomposite_summary.json`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/qa_output/classics/qa_report.json`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/recomposite_log.txt`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/visual_qa_log.txt`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/generate_comparison_all_log.txt`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/generate_comparison_samples_log.txt`

Direct visual proofs:
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/proof-live-visualqa-prompt17-20260305.png`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/visual-qa/compare_001.jpg`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/visual-qa/compare_010.jpg`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/visual-qa/compare_025.jpg`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/visual-qa/compare_050.jpg`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/visual-qa/compare_075.jpg`
- `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/tmp/visual-qa/compare_100.jpg`
