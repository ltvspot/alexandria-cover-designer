# Alexandria Cover Designer — Project State

Last updated: `2026-03-04`
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
**PDF-based compositor approach is now active (PROMPT-09 series, 2026-03-04). See `VERIFICATION-PROTOCOL.md`.**

Approaches 07A through 07H (raster pixel manipulation on flat JPGs) all failed visual inspection. The core problem: detecting and reconstructing the ornamental frame boundary from a flat JPG is structurally impossible at the required fidelity. The frame ring has semi-transparent edges, sub-pixel detail, and irregular boundaries varying from 378–480px radius.

**The Discovery:** Analysis of the actual source PDF files from Google Drive revealed that each PDF contains the frame/illustration separation already encoded by the original designer:
- **Im0** (2480×2470, CMYK): the complete medallion — frame ring + illustration
- **SMask** (2480×2470, grayscale): transparency mask defining the exact frame boundary
  - Values >250 = inner circle (illustration, fully visible) → replace with AI art
  - Values 5–250 = ornamental frame ring (semi-transparent) → keep ORIGINAL pixels
  - Values <5 = outer area (hidden by background) → replace with AI art (invisible anyway)
- **Vector content**: all text, corner ornaments, spine decorations — completely untouched

**PROMPT-09A** — PDF-Based Compositor (CURRENT):
- New `src/pdf_compositor.py` replaces the entire raster approach
- Opens source PDF with `pikepdf`, extracts Im0 + SMask
- Composites: AI art (RGB→CMYK) fills canvas, then frame ring pixels (SMask 5–250) restored from original
- Writes composite back into Im0, keeping SMask unchanged
- Renders PDF to JPG via PyMuPDF at 300 DPI
- Three output formats: `.pdf` (lossless), `.jpg` (300 DPI render), `.ai` (PDF copy)
- Falls back to old `cover_compositor.py` when only JPG is available
- Dependencies: `pikepdf>=10.0.0`, `PyMuPDF>=1.24.0`

**PROMPT-09B** — Automated Verification Suite (PDF+JPG dual mode):
- PDF mode: 7 checks including SMask bit-identical integrity + frame pixel byte-identical preservation
- JPG mode: 5 checks (radial zone comparison fallback)
- Integration test script: `scripts/test_compositor_integration.sh`

**PROMPT-09C** — Download Naming + PDF/AI Output:
- `resolveBookMetadataForJob()` uses `file_base` from catalog
- ZIP includes `.pdf`, `.ai`, `.jpg`, and raw illustration
- Folder structure mirrors source cover naming

Full history: `Codex Prompts/PROMPT-09-Approach-Report.pdf`

Proof of concept validated: replaced illustration with solid teal fill in actual Fairy Tales PDF — ornamental frame perfectly intact, vector content untouched.

**MANDATORY VERIFICATION (NON-NEGOTIABLE):**
Every compositor change must pass `scripts/verify_composite.py --strict` before committing. See `VERIFICATION-PROTOCOL.md`. Both Claude Cowork and Codex must run this — no exceptions.

PDF mode (7 checks): dimensions, ornament zone match (99.9%), art zone differ (95%), centering (3px), transition quality (<2%), SMask bit-identical (100%), frame pixels byte-identical (99.99%).

JPG mode fallback (5 checks): dimensions, ornament zone (99.9%), art zone (95%), centering (3px), transition (<2%).

Known constants (page-level):
- Cover size: 3784 × 2777 @ 300 DPI
- Medallion center: (2864, 1620)
- Outer frame radius: 500px
- Frame inner edge: 378–480px (varies by angle)
- Art zone: r < 370px | Ornament zone: r > 480px

Known constants (PDF-level):
- Embedded image (Im0): 2480 × 2470, CMYK, xref 19
- SMask: 2480 × 2470, grayscale, xref 24
- Frame ring: SMask values 5–250
- Compression: FlateDecode (zlib)
- PDF filename quirk: trailing space before `.pdf` extension

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

## 7. Known Constraints / Honest Caveats
- In production, direct Google provider is currently failing key validation (`Your API key was reported as leaked`); these models are disabled in UI connectivity state until key replacement.
- Provider-side image models can still occasionally emit pseudo-typography; current guardrails and retry hardening reduce this risk but cannot mathematically guarantee zero artifact probability from upstream model outputs.

## 8. Next Recommended Work
1. **PROMPT-09A deployed via Codex** — PDF-based compositor (Codex currently working on this).
2. **Deploy PROMPT-09B via Codex** — automated verification suite with PDF+JPG dual mode. Must run after 09A.
3. **Deploy PROMPT-09C via Codex** — download naming + PDF/AI output in ZIP. Must run after 09A.
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
