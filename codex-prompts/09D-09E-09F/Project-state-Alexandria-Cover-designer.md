# Alexandria Cover Designer — Project State

Last updated: `2026-03-04` (PROMPT-09D/09E/09F series — frame protection, motifs, verification upgrade)
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
**PDF-based compositor approach is now active (2026-03-04, PROMPT-09 series). See `VERIFICATION-PROTOCOL.md`.**

Approaches 07A through 07H all failed visual inspection. The core problem: a circle punch at r=465 cuts into the ornamental frame at 87% of angles because the frame's inner edge varies from 378–480px (irregular scrollwork). The "punch a hole" approach is fundamentally flawed.

**PROMPT-09A** — PDF-Based Cover Compositor (CURRENT):
Analysis of the actual source PDF files from Google Drive revealed that the ornamental frame is stored as a raster image (`Im0`, 2480×2470 CMYK) with a soft mask (`SMask`) that defines the exact frame boundary from the original designer. The compositor replaces Im0 data using `pikepdf` while preserving the SMask unchanged.

PDF Internal Structure:
- Vector content stream: background, text, corner ornaments, spine (untouched)
- Im0 (xref 19): 2480×2470 CMYK raster containing medallion frame + illustration
- SMask (xref 24): 2480×2470 grayscale defining frame boundary
  - Values >250 = inner circle (illustration, replaced with AI art)
  - Values 5–250 = frame ring (kept pixel-identical from original)
  - Values <5 = outer area (hidden by page background)

Compositing algorithm:
1. Open source PDF with pikepdf
2. Extract Im0 (CMYK) and SMask (grayscale)
3. Convert AI art from RGB to CMYK, resize to 2480×2470
4. Create composite: AI art everywhere, then restore original pixels where SMask is 5–250
5. Write composite back into Im0, keep SMask unchanged
6. Save PDF → render to JPG via PyMuPDF at 300 DPI

Result: Ornamental frame is preserved **pixel-for-pixel** from the original designer's file. The SMask provides **sub-pixel-accurate** transparency. Vector content is completely untouched. Frame corruption is **structurally impossible**.

**PROMPT-09D** — Frame Protection & Anti-Border Directives (2026-03-04):
- CRITICAL FIX: AI art was generating its own decorative borders (floral vines, scrollwork) that bled through the semi-transparent SMask zone, visually overpowering the original gold filigree ornaments.
- Compositor fix: Before compositing, all AI art pixels in the frame ring zone (SMask 5–250) and outer zone (SMask <5) are zeroed to white CMYK `[0,0,0,0]`. This blanks out any AI border elements before the source frame data is restored.
- Prompt fix: Strengthened anti-frame directives — expanded `REQUIRED_PHRASE_NO_FRAME`, added canvas directive explaining "square painting that will be cropped into a circle, NOT a circular medallion," extended negative prompt with 9 specific border/ring terms.

**PROMPT-09E** — Book-Specific Visual Motifs for All 99 Books (2026-03-04):
- CRITICAL FIX: Only ~25 of 99 books had specific visual motifs. The rest fell through to a generic fallback producing identical romantic-couple-kissing scenes regardless of book content.
- Added 68 new `BookMotif` entries to `_motif_for_book()` in `prompt_generator.py`, covering every uncovered title.
- Each motif includes: iconic_scene, character_portrait, setting_landscape, dramatic_moment, symbolic_theme, and style_specific_prefix — all crafted to be visually unique and book-specific.
- After this change, ZERO books fall through to the generic fallback.

Fallback: If only source JPG is available (no PDF), falls back to `cover_compositor.py`.

**PROMPT-09B** — Automated Visual Regression Test Suite:
Dual-mode verification script (`scripts/verify_composite.py`):
- PDF mode (9 checks after PROMPT-09F): dimensions, ornament zone, art zone, centering, transition, SMask integrity (bit-identical), frame pixel preservation (CMYK byte-identical), AI art border detection (Sobel edge), visual frame comparison (rendered RGB)
- JPG mode (5 checks): dimensions, ornament zone, art zone, centering, transition
Strict thresholds: ornament 99.9%, art 95%, centering 3px
MUST pass before every compositor-related commit. Non-negotiable.

**PROMPT-09F** — Verification Protocol Upgrade (2026-03-04):
- Added Check 8 (AI Art Border Detection): Uses Sobel edge detection on the AI art's annular ring zone (r=420–480 in embedded image space) to detect decorative borders before compositing. Requires `--ai-art` CLI flag.
- Added Check 9 (Visual Frame Comparison): Renders both source and output PDFs at 300 DPI and compares frame zone pixels at the rendered RGB level — catches visual differences that CMYK-level checks miss.

**PROMPT-09C** — Download Naming + PDF/AI Output:
- Updates `resolveBookMetadataForJob()` in `iterate.js` to use `file_base` from catalog
- ZIP structure mirrors source cover folder naming
- ZIP now includes `.pdf` and `.ai` output files from PDF compositor

Full history: `Codex Prompts/Alexandria_Compositing_Report.pdf`

**MANDATORY VERIFICATION (NON-NEGOTIABLE):**
Every compositor change must pass `scripts/verify_composite.py --strict` before committing. See `VERIFICATION-PROTOCOL.md`. Both Claude Cowork and Codex must run this — no exceptions. PDF mode now checks 9 items (including SMask bit-identity, frame pixel CMYK preservation, AI art border detection, and visual frame comparison). JPG fallback mode checks 5 items.

Known consensus defaults:
- `cx = 2864`
- `cy = 1620`
- `radius = 500`
- Frame inner edge: 378–480px (varies by angle)
- Art zone: r < 370px
- Ornament zone: r > 480px

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
16. PROMPT-07I verification infrastructure (2026-03-04):
   - `scripts/verify_composite.py` — automated 5-check visual regression test (dimensions, ornament zone, art zone, centering, transition quality).
   - `VERIFICATION-PROTOCOL.md` — mandatory rules for both Claude Cowork and Codex.
   - Both agents must run `verify_composite.py` before any compositor commit — no exceptions.

## 7. Known Constraints / Honest Caveats
- In production, direct Google provider is currently failing key validation (`Your API key was reported as leaked`); these models are disabled in UI connectivity state until key replacement.
- Provider-side image models can still occasionally emit pseudo-typography; current guardrails and retry hardening reduce this risk but cannot mathematically guarantee zero artifact probability from upstream model outputs.

## 8. Next Recommended Work
1. **Deploy PROMPT-09A via Codex** — PDF-based compositor. Run `scripts/verify_composite.py --strict` on output before committing.
2. **Deploy PROMPT-09B via Codex** — Automated verification test suite with PDF+JPG modes.
3. **Deploy PROMPT-09C via Codex** — Download naming fix + PDF/AI output in ZIP.
4. **Fix prompt variation** — `_motif_for_book()` in `src/prompt_generator.py` only covers ~25 books; ~70+ get generic "period costume" prompts. Needs book-specific content diversity.
5. **Fix dropdown titles** — many books show as "Untitled" in the iterate page dropdown.
6. Run a live canary (10-book sample) with active provider keys and capture fresh composited proofs.
7. Keep the revision token centralized in one constant to avoid accidental per-page drift.

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
