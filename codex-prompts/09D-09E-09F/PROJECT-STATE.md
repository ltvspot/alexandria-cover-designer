# Project State Pointer

Last updated: `2026-03-04` (PROMPT-09D/09E/09F series — frame protection, motifs, verification upgrade)

Canonical project state file:

- `Project state Alexandria Cover designer.md`

Quick status snapshot:
- PROMPT-06 frontend SPA is now implemented at `src/static/index.html` with hash-router + 14 page renderers in `src/static/js/pages/`.
- All UI routes (`/iterate`, `/review`, `/batch`, `/jobs`, `/compare`, `/similarity`, `/mockups`, `/dashboard`, `/history`, `/analytics`, `/catalogs`, `/prompts`, `/settings`, `/api-docs`) now serve the same SPA shell.
- New design system is active at `src/static/css/style.css` (navy/gold sidebar shell, card/tables/forms/components).
- In-memory DB + CGI-compatible persistence layer is active (`src/static/js/db.js`, `/cgi-bin/settings.py`, `/cgi-bin/catalog.py` route handlers).
- UI shell is locked to the new sidebar design with anti-stale controls (`Cache-Control: no-store` + `?v=20260302-designlock`).
- CSP now allows required frontend dependencies (`fonts.googleapis.com`, `fonts.gstatic.com`, `cdn.jsdelivr.net`, `cdnjs.cloudflare.com`) so Chart.js/JSZip/Inter load correctly.
- COMPOSITOR STATUS (2026-03-04): PROMPT-09A (PDF-based compositor) is the current approach. PROMPT-09D adds critical frame protection: AI art pixels in the frame ring zone (SMask 5–250) and outer zone (SMask <5) are zeroed to white BEFORE compositing, preventing AI-generated borders from bleeding through. Anti-border directives in prompt_generator.py are also strengthened.
- MOTIF COVERAGE (2026-03-04): PROMPT-09E adds book-specific visual motifs for ALL 99 books. Previously only ~25 had specific motifs; the rest fell through to a generic fallback producing identical romantic scenes. Now every book has unique iconic scenes, character portraits, settings, dramatic moments, and symbolic themes.
- VERIFICATION (2026-03-04): PROMPT-09F upgrades verification to 9 checks in PDF mode. Check 8 (AI Art Border Detection) uses Sobel edge detection on the AI art's frame zone. Check 9 (Visual Frame Comparison) renders both PDFs and compares frame zones at the pixel level. See updated `VERIFICATION-PROTOCOL.md`.
- MANDATORY VERIFICATION: Every compositor change must pass `scripts/verify_composite.py --strict` before committing. PDF mode now runs 9 checks (including new border detection and visual frame comparison). JPG fallback runs 5 checks. See `VERIFICATION-PROTOCOL.md`. Both Claude Cowork and Codex must run this script — no exceptions.
- Prompt assembly is hardened against malformed constraints and duplicated provider/model signatures.
- Dashboard recent cards are prompt-aware/style-tag-aware and backfill from filesystem when persisted rows are sparse.
- Required model inventory is force-enforced at runtime (15 OpenRouter production models + Gemini direct IDs), even when `ALL_MODELS` env is stale.
- Built-in prompt seed now auto-runs cleanly at startup (fixed logger-field collision on `created`).
- Content guardrail fallback path is fixed for non-`scipy` environments (tiny-component math bug removed), so valid generations are no longer falsely blocked.

Verification snapshot (local + live, `2026-03-02`):
- Full `pytest` pass.
- `PROMPT-06` SPA assets compile and load (`node --check src/static/js/*.js src/static/js/pages/*.js`).
- Local visual proof for new design shell:
  - `tmp/proof-local-iterate-prompt06-20260302-final.png`
  - `tmp/proof-local-dashboard-prompt06-20260302-final.png`
  - `tmp/proof-local-review-prompt06-20260302-final.png`
- Latest local PROMPT-06 visual proof:
  - `tmp/proof-local-iterate-20260302-uiux-cspfixed.png`
  - `tmp/proof-local-dashboard-20260302-uiux.png`
  - `tmp/proof-local-review-20260302-uiux.png`
  - `tmp/proof-local-prompts-20260302-uiux.png`
- API docs route-matrix test hardened for heavy ZIP endpoints by increasing per-request timeout from `20s` to `45s`.
- Deployment `addf1b1c-2d44-495c-b1d2-19b16cb0a393` on Railway is healthy.
- `GET /api/iterate-data?catalog=classics` returns 22 models, including:
  - all 15 required OpenRouter models in configured order
  - 3 direct Gemini IDs
  - existing Fal/OpenAI options
- `POST /api/generate` (catalog `classics`, book `3`, model `openrouter/google/gemini-2.5-flash-image`, `cover_source=drive`) completed successfully with medallion-safe composite (job `4517fa87-a7c9-432d-be8b-b522e6c45964`).
- `GET /api/dashboard-data?catalog=classics` now returns `recent_results = 1` on live after generation.
- Direct Google provider is currently degraded in prod (`HTTP 403 leaked key`), while OpenRouter/Fal/OpenAI are healthy.
- Visual proof:
  - `tmp/proof-live-iterate-20260302-prompt06.png`
  - `tmp/proof-live-dashboard-20260302-prompt06.png`
  - `tmp/proof-live-review-20260302-prompt06.png`
  - `tmp/proof-live-prompts-20260302-prompt06.png`

Mandatory handoff policy (non-negotiable):
- Every user-facing delivery must include:
  1. direct deployed webapp link, and
  2. visual proof report path(s) with screenshots from that deployment.
- Canonical proof artifact file: `VISUAL-PROOF-REPORT.md`.

This pointer exists so tooling/instructions that reference `PROJECT-STATE.md` resolve to the same source of truth.
