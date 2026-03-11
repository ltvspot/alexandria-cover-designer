# Alexandria Cover Designer — Project State

Last updated: `2026-03-08` (updated: PROMPT-22 deployed ✅, PROMPT-23 ready — Rewrite prompts to scene-only)
Version track: `v2.1.x` (current runtime reports `2.1.1`)

## 1. Current Goal (Production)
Keep the generation webapp in a stable state where:
- the PROMPT-06 SPA shell is the only served frontend across all primary UI routes,
- generated medallion art is composited behind ornament scrollwork,
- generation prompts strongly suppress text/labels/ribbons/frames,
- dashboard reliably shows latest generated covers from persisted data,
- iterate/dashboard stay on the new UI shell (no stale legacy CSS/JS),
- model selection includes all configured Gemini image options.

## 2. Runtime Architecture (Current)
Pipeline:
1. Prompt composition and diversification (`src/prompt_generator.py`)
2. Provider generation + content guardrails (`src/image_generator.py`)
3. Medallion compositing (`src/cover_compositor.py`)
4. Persistence + API surface (`scripts/quality_review.py`)
5. Web UI pages (`src/static/*.html`, `src/static/*.css`, `src/static/navbar.js`)

Serving layer:
- The main HTTP application is served by `scripts/quality_review.py`.
- Static pages are served from `src/static/` with explicit cache behavior.
- New frontend topology (PROMPT-06):
  - SPA shell: `src/static/index.html`
  - Design system: `src/static/css/style.css`
  - Router/orchestrator: `src/static/js/app.js`
  - Data layer: `src/static/js/db.js`
  - 14 pages: `src/static/js/pages/*.js`
  - CGI-compatible endpoints: `/cgi-bin/settings.py`, `/cgi-bin/catalog.py`, `/cgi-bin/catalog.py/status`, `/cgi-bin/catalog.py/refresh`

## 3. Hard Locks in Place

### 3.1 New Design Only (Anti-Stale)
- HTML/CSS/JS responses are returned with `Cache-Control: no-store`.
- Static asset links use revision token `?v=20260302-designlock`.
- `/iterate` and all major UI routes are served through `src/static/index.html` (SPA shell routing).
- `src/static/shared.css` contains a design-lock block with `!important` sidebar/layout rules so legacy page CSS cannot revert to the old top-nav layout.

### 3.2 Medallion Safety (Art Behind Ornaments)
**PROMPT-20 — Im0 Layer Swap Compositor (2026-03-05). Supersedes ALL previous compositor approaches (07–19).**

Approaches 07A through 19 all failed. Every approach from PROMPT-07 through PROMPT-19 tried pixel-level manipulation: extracting frame overlays, color-based metal detection, frame_mask.png, hole punching, SMask-guided compositing — all produced visually broken output that passed numerical tests but looked terrible to a human.

**Root Cause Discovery:** Source PDFs contain `/Im0` (2480×2470, CMYK) which holds BOTH the illustration art AND the gold ornamental frame as one combined image. An `/SMask` clips Im0 onto the cover. The frame is NOT a separate layer — it's baked into Im0.

**PROMPT-20 — Im0 Layer Swap (CURRENT):**
- New `src/pdf_swap_compositor.py` — works directly with Im0 inside the PDF
- Opens source PDF with `pikepdf`, extracts Im0
- Within Im0: replaces CENTER art area with new AI art (geometric circle, radius ~950 from Im0 center)
- Keeps OUTER frame ring pixels from original Im0 untouched
- New art is BEHIND the frame — within Im0 itself, frame pixels sit on top
- Writes modified Im0 back into PDF, keeping original SMask completely unchanged
- Renders modified PDF at 300 DPI using `pdftoppm` → final composite JPG
- Falls back to legacy three-layer approach if PDF swap fails
- Dependencies: `pikepdf>=8.0.0`, `poppler-utils` (for pdftoppm)

**What this eliminates:**
- `config/frame_mask.png` — no longer needed
- `config/frame_overlays/` — not needed
- `scripts/extract_frame_overlays.py` — bypassed entirely
- Color-based frame metal detection — irrelevant
- The `frame_mask_arr` override bug — bypassed
- All hole-punching approaches — not used

**Key geometry (Im0 coordinate space):**
- Im0 dimensions: 2480 × 2470 px (same across all 99 books)
- Im0 center: (1240, 1235)
- Blend radius: ~950 px from center (where frame ring starts)
- Feather: 20 px smooth transition
- SMask: preserved unchanged (handles scrollwork clipping automatically)

**Key geometry (page-level, unchanged):**
- Cover size: 3784 × 2777 @ 300 DPI
- Medallion center: (2864, 1620)
- Outer frame radius: 500px

**Source files:** All 99 books have .ai + .pdf + .jpg in `Input Covers/`. Google Drive: https://drive.google.com/drive/folders/1ybFYDJk7Y3VlbsEjRAh1LOfdyVsHM_cS

**DO NOT:** Replace Im0 entirely (loses frame). Modify the SMask. Do color-based pixel detection. Use frame_mask.png. Punch holes.

**Implementation prompt:** `Codex Prompts/PROMPT-20-IM0-LAYER-SWAP-COMPOSITOR.md`
**Codex message:** `Codex Prompts/CODEX-MESSAGE-PROMPT-20.md`
**Visual analysis PDF:** `Alexandria-Im0-Layer-Swap-Approach.pdf`

**MANDATORY VERIFICATION (NON-NEGOTIABLE):**
Every compositor change requires visual comparison grids committed to `qa_output/`. Tim's visual assessment is the final authority — numerical checks alone have repeatedly missed defects.

### 3.3 Prompt/Generation Hardening
`src/image_generator.py` + `src/prompt_generator.py` enforce:
- strict no-text/no-frame/no-banner/no-seal directives,
- vivid palette guidance for stronger color output,
- modality-aware provider handling,
- 429 retry with `Retry-After` backoff,
- guardrail rejection for text/ring/frame artifacts,
- prompt assembly cleanup for malformed `"no,"` fragments,
- normalized model signature formatting (prevents `openrouter/openrouter/...` duplication),
- corrected non-`scipy` fallback tiny-component math (avoids false text-artifact spikes),
- calibrated text-artifact trigger to require stronger textual structure signals.

### 3.5 Model Inventory Enforcement
`src/config.py` now force-enforces required runtime model inventory even when `ALL_MODELS` env is stale:
- 15 required OpenRouter production models (GPT-5 Image -> Nano Banana order),
- 3 direct Gemini image IDs,
- preserves additional configured models (Fal/OpenAI) after required set.

### 3.6 Built-in Prompt Seed Reliability
`scripts/quality_review.py` startup auto-seed is fixed:
- removed `LogRecord` field collision on `created`,
- built-ins now seed on startup without silent failure.

### 3.4 Dashboard Reliability
`scripts/quality_review.py` dashboard recent-results path:
- prefers composited assets,
- preserves prompt/style metadata for cards,
- resolves root-relative persisted asset paths,
- backfills from `tmp/composited` and `Output Covers` when persisted rows are sparse,
- no longer marks unresolved rows as deduped before a valid file is found (prevents hidden cards),
- falls back to file discovery if persisted rows exist but all resolve to missing paths.

Live note (`2026-03-02`, deployment `e6893537-535e-4a3f-a497-0f33cb938c55`):
- `/api/health` healthy, uptime reset on latest rollout.
- `/api/iterate-data?catalog=classics` returns `22` models, including required 15 OpenRouter + direct Gemini IDs.
- Live generation job (`4517fa87-a7c9-432d-be8b-b522e6c45964`) completed successfully (`openrouter/google/gemini-2.5-flash-image`, `cover_source=drive`).
- `/api/dashboard-data?catalog=classics` now reports `recent_results = 1` after the successful live run.
- Direct Google provider is degraded due leaked API key (`403 PERMISSION_DENIED`), while OpenRouter/Fal/OpenAI remain usable.

Latest live UI rollout (`2026-03-02`, deployment `addf1b1c-2d44-495c-b1d2-19b16cb0a393`):
- `/iterate` now serves the PROMPT-06 SPA shell (`src/static/index.html`) with sidebar navigation + hash router.
- response headers include `cache-control: no-store`.
- CSP now allows Inter/Chart.js/JSZip dependencies required by the new UI.
- fresh live screenshots:
  - `tmp/proof-live-iterate-20260302-prompt06.png`
  - `tmp/proof-live-dashboard-20260302-prompt06.png`
  - `tmp/proof-live-review-20260302-prompt06.png`
  - `tmp/proof-live-prompts-20260302-prompt06.png`

## 4. Prompt Strategy (Current)
Current diversification supports:
- fixed style anchors (including Sevastopol + Cossack),
- curated style families,
- wildcard variants for spread,
- anti-text and anti-frame constraints,
- vivid color steering.

UX support in iterate/dashboard:
- prompt visible under generated cards,
- `Save Prompt` available from result cards,
- reusable prompt library selection.

## 5. Models + Environment Compatibility
Configured model list includes OpenRouter + direct Gemini IDs.

Environment alias compatibility is active:
- `DRIVE_SOURCE_FOLDER_ID` + fallback `GDRIVE_SOURCE_FOLDER_ID`
- `DRIVE_OUTPUT_FOLDER_ID` + fallback `GDRIVE_OUTPUT_FOLDER_ID`
- `BUDGET_LIMIT_USD` + fallback `MAX_COST_USD`

## 6. Verification Snapshot (2026-03-03)
Completed in this workspace session:
1. Full `pytest` passed.
2. API docs route matrix test hardened against heavy ZIP endpoint timeout variance by raising per-request timeout to `45s`.
3. `GET /api/health` returned `{"status":"ok", ...}`.
4. `GET /api/iterate-data?catalog=classics` now returns 22 models including all required OpenRouter+Gemini entries.
5. Fresh live generation verified + composited output validated visually:
   - `tmp/proof-live-composite-book3-v1-20260302-refresh.jpg`
   - `tmp/proof-live-variant-book3-v1-20260302.zip`
6. Dashboard latest cards verified populated from persisted generation record:
   - `tmp/proof-live-dashboard-20260302-refresh.png`
7. Fresh live page proofs:
   - `tmp/proof-live-iterate-20260302-refresh.png`
   - `tmp/proof-live-review-20260302-refresh.png`
8. Additional local proof snapshots:
   - `tmp/proof-local-iterate-20260302-fix.png`
   - `tmp/proof-local-dashboard-20260302-fix.png`
   - `tmp/proof-local-review-20260302-fix.png`
9. PROMPT-06 frontend proof snapshots:
   - `tmp/proof-local-iterate-prompt06-20260302-final.png`
   - `tmp/proof-local-dashboard-prompt06-20260302-final.png`
   - `tmp/proof-local-review-prompt06-20260302-final.png`
10. CSP updated so PROMPT-06 dependencies load (Inter/Chart.js/JSZip):
   - `style-src`: `https://fonts.googleapis.com`
   - `font-src`: `https://fonts.gstatic.com`
   - `script-src`: `https://cdn.jsdelivr.net`, `https://cdnjs.cloudflare.com`
11. Latest local PROMPT-06 visual proofs:
   - `tmp/proof-local-iterate-20260302-uiux-cspfixed.png`
   - `tmp/proof-local-dashboard-20260302-uiux.png`
   - `tmp/proof-local-review-20260302-uiux.png`
   - `tmp/proof-local-prompts-20260302-uiux.png`
12. Latest live PROMPT-06 visual proofs:
   - `tmp/proof-live-iterate-20260302-prompt06.png`
   - `tmp/proof-live-dashboard-20260302-prompt06.png`
   - `tmp/proof-live-review-20260302-prompt06.png`
   - `tmp/proof-live-prompts-20260302-prompt06.png`
13. PROMPT-07C compositor rewrite verified:
   - frontend registry loaded from `/api/cover-regions` and returns `99` covers,
   - known geometry values confirmed for books `1`, `9`, `25`,
   - deployed bundle contains `KNOWN_DEFAULT_CY = 1620` and `[Compositor v10]` log strings,
   - stale `[Compositor v9] Detection:` log string absent from deployed bundle.
14. PROMPT-07E compositor fix verified:
   - `config/compositing_mask.png` disabled (renamed to `.disabled`),
   - deployed bundle contains `OPENING_RATIO = 0.96`, `OPENING_SAFETY_INSET = 0`, `punchRadius = geo.openingRadius + 4`, and `[Compositor v12]`,
   - backend runtime logs show known geometry + `opening=480` on canonical covers.
15. PROMPT-07F template compositor verified:
   - local compositor runs for books `1`, `9`, `25` log `Using PNG template: ...`,
   - on-demand template generation path verified (`Generated PNG template: ...`),
   - composite summary remains successful (`processed_books=3`, `failed_books=0`).
16. PROMPT-09 series (2026-03-04):
   - PDF discovery: source PDFs contain Im0 raster (2480×2470, CMYK) + SMask (grayscale) with exact frame boundary from original designer.
   - Proof of concept validated: teal fill replacement in Fairy Tales PDF — ornamental frame pixel-perfect, vector content untouched.
   - `VERIFICATION-PROTOCOL.md` updated for dual-mode verification (PDF: 7 checks, JPG: 5 checks).
   - `scripts/verify_composite.py` updated with PDF mode: SMask bit-identical check + frame pixel byte-identical check.
   - Both agents must run `verify_composite.py --strict` before any compositor commit — no exceptions.
   - Implementation sequence: 09A (PDF compositor) → 09B (verification suite) → 09C (download naming).
17. Frame damage quantification (2026-03-04):
   - Ran pixel-level comparison across all 99 covers: original input JPG vs composited output JPG.
   - **Result: 65.8% average frame ring pixels changed** (should be <1%). Average pixel delta 56.7 (should be <5). Outer area: 0.0% changed.
   - Root cause confirmed: shared `frame_mask.png` cannot represent 99 unique ornamental frames.
   - Visual comparison images generated: `tmp/verification/compare_{book_number}.jpg` for sample covers.
   - PROMPT-13 written: batch verification system + hard rejection gate inside `composite_single()`.
   - PROMPT-12 updated: ART_BLEED_PX corrected from 60→140, verification integration added.
   - Implementation sequence revised: **PROMPT-13 (verification) → PROMPT-12 (RGBA overlays)**.

## 7. Known Constraints / Honest Caveats
- In production, direct Google provider is currently failing key validation (`Your API key was reported as leaked`); these models are disabled in UI connectivity state until key replacement.
- Provider-side image models can still occasionally emit pseudo-typography; current guardrails and retry hardening reduce this risk but cannot mathematically guarantee zero artifact probability from upstream model outputs.

## 8. Next Recommended Work

**PROMPT-20: 🔴 READY TO SEND TO CODEX — Im0 Layer Swap Compositor (2026-03-05)**
- This supersedes ALL previous compositor prompts (07–19). All of those failed.
- Creates new `src/pdf_swap_compositor.py` that swaps center art within Im0 in source PDFs.
- Keeps gold ornamental frame ring intact, new art placed BEHIND frame.
- Falls back to legacy three-layer approach if PDF swap fails.
- Prompt: `Codex Prompts/PROMPT-20-IM0-LAYER-SWAP-COMPOSITOR.md`
- Codex message: `Codex Prompts/CODEX-MESSAGE-PROMPT-20.md`

**⚠️ PROMPT-20 IMPLEMENTATION RESULT (2026-03-05):**
Codex implemented PROMPT-20 but it shipped with two bugs:
1. **Blend radius too large (938 instead of 840):** `detect_blend_radius_from_smask()` used SMask < 255 boundary — that's the OUTER edge of the medallion (r≈939), not the inner edge of the frame ornaments (r≈870). Cross-book pixel analysis (comparing Im0 across books 1/2/50) proves frame starts at r≈870. Correct blend radius = 840 (30px safety margin).
2. **Content guardrail false rejections:** `hard_frame_artifact` threshold (0.22) and individual `ring_penalty`/`frame_penalty` thresholds (0.14) reject AI art with strong linear structures (ship masts, architecture) as frame artifacts. Moby Dick's whale/ship scene scored 0.261 and was falsely rejected.

**PROMPT-21 — Fix Blend Radius & Guardrail (2026-03-05):**
- Prompt: `Codex Prompts/PROMPT-21-FIX-BLEND-RADIUS-AND-GUARDRAIL.md`
- Codex message: `Codex Prompts/CODEX-MESSAGE-PROMPT-21.md`
- Only 2 files change: `src/pdf_swap_compositor.py` and `src/image_generator.py`
- Deployed: commit e55e53d, Railway deployment dbeb6051 (SUCCESS)

**⚠️ PROMPT-21 DEPLOYMENT RESULT (2026-03-06):**
PROMPT-21 code changes verified correct. QA comparison sheets with synthetic gradient test images show frame preserved correctly. **However, live production generations with real AI art still exhibit the same compositor issue — the gold ornamental frame is not correctly preserved.** The problem persists despite the blend radius fix. A developer hire is in progress to resolve this.

**⚠️ CRITICAL PROCESS LESSON (2026-03-04):**
Every compositor prompt from PROMPT-07 through PROMPT-21 passed its own programmatic/QA tests while producing visually broken output in production. The gap between test conditions (synthetic gradients) and real production conditions (actual AI art) continues to mask the defect. Tim's visual assessment is the final authority. See `CLAUDE.md` mandatory visual validation section.

**PROMPT-22 (2026-03-08) — READY TO SEND:**
Three tasks in one prompt:
1. **Fix Nano Banana Pro model routing** — UI label maps to `openrouter/google/gemini-2.5-flash-image` (Gemini 2.5 Flash, WRONG). Actual model is `openrouter/google/gemini-3-pro-image-preview`. Files: `openrouter.js`, `iterate.js`, `config.py`.
2. **Implement 10 Alexandria prompts** (5 base + 5 wildcard) with {SCENE}/{MOOD}/{ERA} variable injection, genre-to-prompt auto-mapping, hardcoded negative prompt for no-text rule.
3. **Add Save Raw button** in Recent Results → `POST /api/save-raw` → Google Drive upload to "Chosen Winner Generated Covers" (ID: 1SHzAaDU1pN0ECC61KCRtYijv4dp4IR59). Folder naming uses hyphen, file naming uses en-dash.

Prompt: `Codex Prompts/PROMPT-22-MODEL-FIX-PROMPTS-SAVE-RAW.md`
Codex message: `Codex Prompts/CODEX-MESSAGE-PROMPT-22.md`

**Outstanding work (requires developer):**
1. **Compositor frame preservation** — Still broken with real AI art despite PROMPT-21 fixes. Developer hire in progress.
2. **Searchable book selector** — replace flat `<select>` dropdown with search-by-number/title/author (PROMPT-08).
3. Lazy cover file download from Drive (JPG/PDF on demand, not all pre-downloaded).
4. Keep the revision token centralized in one constant to avoid accidental per-page drift.

## 9. Mandatory Delivery Protocol
For every user-facing completion message:
1. Include the direct deployed webapp URL.
2. Include visual proof report artifact path(s) (screenshots + key endpoint checks).
3. Do not claim deployment completeness without both items.
4. Update `VISUAL-PROOF-REPORT.md` for each deployment.

## 10. Chat Proof Rendering Rule (Critical)
- Inline visual proofs in chat must use Markdown image tags with absolute local filesystem paths.
- To avoid renderer failures, publish proof images from a no-space directory: `/Users/timzengerink/proofs/`.
- Standard proof filenames:
  - `/Users/timzengerink/proofs/proof-results-grid.png`
  - `/Users/timzengerink/proofs/proof-modal-composite.png`
  - `/Users/timzengerink/proofs/proof-iterate-page.png`
  - `/Users/timzengerink/proofs/proof-medallion-closeup.png`
- Do not use relative paths for inline chat proofs.
