# Project State Pointer

Last updated: `2026-03-11`

Canonical project state file:

- `Project state Alexandria Cover designer.md`

---

## ⛔ NON-NEGOTIABLE VISUAL REQUIREMENTS — READ BEFORE ANY CODE CHANGE

**Single source of truth: `VISUAL-REQUIREMENTS.md`** (in project root)

**Catalog size: 2,000+ books (continuously growing). NOT 99.**

Before ANY deployment, answer these 4 questions with YES:

1. **STYLE PRESERVATION (Style ≠ Scene)**: Do the 5 base prompts produce the SAME art technique/palette/rendering as before? Styles define ONLY the illustration method, NOT scene content. (Classical Devotion = warm oil-painting tones, rich earth colours, sacred atmosphere; Romantic Realism = warm earth tones, dramatic skies, painterly brushwork; Esoteric Mysticism = celestial symbolism, midnight blue and gold, visionary atmosphere; Gothic Atmosphere = moonlit shadows, deep indigo/crimson, expressionist contrast; Philosophical Gravitas = contemplative chiaroscuro, deep shadows, muted umber/ochre). Scene content (sunflower fields, gardens, cityscapes, mountains) comes from enrichment data via {SCENE}, NOT from the style.
2. **CONTENT RELEVANCE**: Does every cover depict content specific to ITS book? (Romeo & Juliet = Verona/balcony, Moby Dick = whaling ship/sea, etc.) This requires REAL enrichment data for all 2,000+ books.
3. **VISUAL DIVERSITY**: Are the 4-10 variants for each book visually DISTINCT? (Different scenes + different styles + different compositions)
4. **CODEX VERIFICATION**: Has the code been INDEPENDENTLY VERIFIED by reading actual diffs, running actual code, and generating actual covers — not just trusting Codex's summary?

5. **DEPLOYED + TESTED ON PRODUCTION**: Has the code been pushed, deployed to Railway, and tested on the LIVE webapp at `https://web-production-900a7.up.railway.app` by generating actual covers for 3+ books — NOT just local testing?

**IF ANY ANSWER IS NO → DO NOT DEPLOY. DO NOT DELIVER.**

**Mandatory visual test**: Generate 4 variants each for Romeo and Juliet, Moby Dick, Emma, Frankenstein, The Art of War. Verify content relevance + visual diversity + style preservation for all 20 covers.

**⛔ CODEX DEPLOYMENT MANDATE (NON-NEGOTIABLE):**
- Codex MUST `git commit` + `git push` + wait for Railway deploy + test on LIVE production webapp
- Codex MUST open `https://web-production-900a7.up.railway.app/iterate` and generate actual covers
- Codex MUST provide the direct webapp link and screenshots from PRODUCTION in every response
- Local-only testing is NEVER acceptable — it missed the OpenRouter 402 credit exhaustion bug
- Provider fallback: if OpenRouter returns 402, the app MUST fall back to direct Google API

---

Quick status snapshot:
- PROMPT-06 frontend SPA is now implemented at `src/static/index.html` with hash-router + 14 page renderers in `src/static/js/pages/`.
- All UI routes (`/iterate`, `/review`, `/batch`, `/jobs`, `/compare`, `/similarity`, `/mockups`, `/dashboard`, `/history`, `/analytics`, `/catalogs`, `/prompts`, `/settings`, `/api-docs`) now serve the same SPA shell.
- New design system is active at `src/static/css/style.css` (navy/gold sidebar shell, card/tables/forms/components).
- In-memory DB + CGI-compatible persistence layer is active (`src/static/js/db.js`, `/cgi-bin/settings.py`, `/cgi-bin/catalog.py` route handlers).
- UI shell is locked to the new sidebar design with anti-stale controls (`Cache-Control: no-store` + `?v=20260302-designlock`).
- CSP now allows required frontend dependencies (`fonts.googleapis.com`, `fonts.gstatic.com`, `cdn.jsdelivr.net`, `cdnjs.cloudflare.com`) so Chart.js/JSZip/Inter load correctly.
- COMPOSITOR STATUS (2026-03-05): **PROMPT-21 — Fix Blend Radius & Guardrail** (on top of PROMPT-20 Im0 Layer Swap). PROMPT-20 shipped with blend radius 938 (SMask outer edge) — should be 840 (frame ornaments start at r≈870). Also guardrail thresholds too aggressive (false-rejecting art with linear structures). PROMPT-21 hardcodes `DEFAULT_BLEND_RADIUS = 840` and raises `hard_frame_artifact` from 0.22→0.35, penalty thresholds from 0.14→0.22. Deployed as commit e55e53d (Railway dbeb6051, SUCCESS). **Issue persists in production — live generations still show compositor problems with real AI art despite QA passing with synthetic test images.** Developer hire in progress. See `Codex Prompts/PROMPT-21-FIX-BLEND-RADIUS-AND-GUARDRAIL.md`.
- **PROMPT-42 (2026-03-11): 📋 READY TO SEND — CRITICAL** — Enrichment Pipeline + Visual Quality Hardening for All 2,000+ Books. PROMPT-41 deployed the architecture but enrichment data is still 100% generic placeholders for ALL books. 7 tasks: (1) fix `enrich_catalog()` to detect/replace generic enrichment via `_enrichment_is_generic()`, (2) auto-enrich new books on addition via background threads, (3) `--replace-generic` flag for bulk re-enrichment with rate limiting/checkpointing, (4) `/api/enrichment-health` endpoint, (5) frontend enrichment status badge + re-enrich button, (6) validation script, **(7) MANDATORY visual verification — 5 test books × 4 variants = 20 covers, verify style preservation + content relevance + visual diversity**. After deploy: MUST run `scripts/enrich_catalog.py --replace-generic` on production. **Must comply with `VISUAL-REQUIREMENTS.md` — all 4 non-negotiable rules.** See `Codex Prompts/PROMPT-42-ENRICHMENT-PIPELINE-ALL-BOOKS.md` and `Codex Prompts/CODEX-MESSAGE-PROMPT-42.md`.
- **PROMPT-41 (2026-03-10): ✅ DEPLOYED & VERIFIED** — Complete Content-Relevance Overhaul. Verified: 35 scene-first templates (5 base + 30 wildcards) all with {SCENE} at position 178, no frame/background directives, `_ensure_alexandria_prompts()` now always updates existing entries, `content_relevance.py` with generic detection + fallback chain, frontend `_isGenericContent()` + protagonist injection + validation + preview + daily rotation, backend integration via `content_relevance` module, GENRE_PROMPT_MAP with 15+ genre-to-wildcard mappings. **Remaining issue**: enrichment data still 100% generic → addressed by PROMPT-42. See `Codex Prompts/PROMPT-41-COMPLETE-CONTENT-RELEVANCE-OVERHAUL.md`.
- **PROMPT-38/39/40 (2026-03-10): ⚠️ NOT IMPLEMENTED** — Codex claimed implementation but investigation found NONE of the core changes were made. Templates unchanged, only 5 wildcards, no filtering, no rotation. Superseded by PROMPT-41.
- **PROMPT-37 (2026-03-10): ✅ DEPLOYED** — Scene rotation via `buildScenePool()`, Save Raw 6-file fix, removed directory-scanning fallbacks, fixed "99 books" references.
- **PROMPT-36 (2026-03-10): ✅ DEPLOYED** — Reverted compositor blanking. Compositor confirmed clean.
- **PROMPT-35 (2026-03-10): ⚠️ NOT IMPLEMENTED** — Superseded by PROMPT-37.
- **PROMPT-34 (2026-03-10): ✅ DEPLOYED** — Forced book-specific enrichment into ALL prompts. Fixed generation reliability (DEAD_JOB_TIMEOUT 3→8min). Preserved enrichment across browser catalog sync. Commits: 225adbb, Railway ba1b9e01.
- **PROMPT-33 (2026-03-10): ✅ DEPLOYED** — Fixed {SCENE}/{MOOD}/{ERA} placeholder resolution. Added `_resolve_alexandria_placeholders()`, `_sanitize_prompt_placeholders()` safety net, fixed `defaultMoodForBook()` to use `emotional_tone`, fixed batch page enrichment. Commits: f04e11c, 76014d9, 036fc30.
- **PROMPT-32 (2026-03-10): ✅ DEPLOYED** — Switch Drive upload to Shared Drive folder `0ABLZWLOVzq-qUk9PVA`. `supportsAllDrives=True` on all API calls. Save Raw + Drive upload working.
- **PROMPT-31 (2026-03-09): ✅ DEPLOYED** — App stability fixed, cover-preview 404 fixed, visual-qa 502 fixed, 22 models with pricing. Commit 92faf7a, Railway 97f2f7f6 SUCCESS.
- **PROMPT-30 (2026-03-09): ✅ DEPLOYED** — All 2,397 books enriched (0 generic), searchable book combobox, validate_prompt_resolution.py, Gemini pricing fixed. Deployed as version 2.1.1 (commits ba4d78a, 271d211). Railway deployment 5c8487b0 SUCCESS.
- **PROMPT-29: ⚠️ PARTIALLY IMPLEMENTED** — Catalog expanded to 2,397 books, enrichment pipeline rewritten, pricing fixed. But enrichment never run. Superseded by PROMPT-30.
- **PROMPT-22 (2026-03-08): PENDING — Fix Nano Banana Pro Model Routing + 10 Alexandria Prompts + Save Raw Button.** Three tasks: (1) Fix model routing bug — "Nano Banana Pro" label currently maps to `openrouter/google/gemini-2.5-flash-image` (Gemini 2.5 Flash, WRONG) instead of `openrouter/google/gemini-3-pro-image-preview` (actual Nano Banana Pro). (2) Implement 10 new prompts (5 base + 5 wildcard) with three-part formula (FIXED FRAME + STYLE LAYER + TITLE SLOT), variable injection for {SCENE}/{MOOD}/{ERA}, genre-to-prompt auto-mapping, and hardcoded negative prompt. (3) Add "Save Raw" button in Recent Results with Google Drive upload to "Chosen Winner Generated Covers" folder (ID: 1SHzAaDU1pN0ECC61KCRtYijv4dp4IR59). See `Codex Prompts/PROMPT-22-MODEL-FIX-PROMPTS-SAVE-RAW.md` and `Codex Prompts/CODEX-MESSAGE-PROMPT-22.md`.
- MANDATORY VERIFICATION: Every compositor change must pass `scripts/verify_composite.py --strict` before committing. PDF mode (7 checks) preferred; JPG mode (5 checks) fallback. See `VERIFICATION-PROTOCOL.md`. Both Claude Cowork and Codex must comply — no exceptions. **Additionally: visual inspection by a human is MANDATORY.** Programmatic checks alone have repeatedly missed visual defects (PROMPTs 07–17).
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

**⛔ CODEX PROMPT RULE:** Always use a NEW prompt number for every Codex submission. Never resubmit or continue a previous PROMPT-XX. Codex starts fresh each time — increment the number, reference what was already done, and specify only new/remaining work.

This pointer exists so tooling/instructions that reference `PROJECT-STATE.md` resolve to the same source of truth.
