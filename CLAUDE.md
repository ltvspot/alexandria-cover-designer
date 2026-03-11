# CLAUDE.md - Alexandria Cover Designer v2.0.0

## ⛔⛔ CONTENT RELEVANCE IS NON-NEGOTIABLE — ABSOLUTE TOP PRIORITY ⛔⛔

**HISTORY (2026-03-09):** The initial local enrichment data had GENERIC PLACEHOLDER content ("Central protagonist", "Iconic turning point from [TITLE]"). The AI image model had no idea what to draw. Covers showed generic romantic scenes for satirical adventures, gothic horror, comedy — completely wrong. Tim flagged this REPEATEDLY. This rule exists to prevent that from EVER happening again.

**⚠️ CATALOG SIZE:** The catalog currently has 2,400+ books and is GROWING. The local repo's `config/book_catalog_enriched.json` is stale test data — the deployed server downloads the real catalog (2,400+ books) at Docker build time. NEVER reference "99 books" — that number is wrong. Always assume the catalog is large and growing.

**THE RULE — FOR ALL AGENTS (Claude AND Codex):**

Every generated cover illustration MUST be visually relevant to the ACTUAL content, characters, and scenes of the SPECIFIC book. Generic or wrong-book imagery is a **CRITICAL BUG** — equivalent to a completely broken feature.

**Specifically:**
1. `{SCENE}` MUST resolve to an ACTUAL scene from the ACTUAL book — real character names, real settings, real plot points
2. `{MOOD}` MUST reflect the ACTUAL emotional tone of the book
3. `{ERA}` MUST reflect the ACTUAL time period of the book's setting
4. `iconic_scenes` in `book_catalog_enriched.json` MUST contain visually descriptive, book-specific scenes — NEVER generic templates
5. `protagonist` MUST be the real character name with a visual descriptor — NEVER "Central protagonist"
6. If enrichment data is missing or generic, the system MUST fall back gracefully — NOT silently use broken templates
7. Any code change that could dilute or genericize scene descriptions is FORBIDDEN

**Test:** Show a generated cover to someone who has read the book. They should recognize the scene. If they can't tell what book it's from, the enrichment data is wrong and must be fixed BEFORE any other work proceeds.

**Validation:** After ANY change to enrichment data or scene pipeline, run:
```python
import json
with open('config/book_catalog_enriched.json') as f:
    books = json.load(f)
for b in books:
    e = b.get('enrichment', {})
    assert e.get('protagonist','') != 'Central protagonist', f"Book {b['number']}: generic protagonist"
    for s in e.get('iconic_scenes', []):
        assert 'Iconic turning point' not in s, f"Book {b['number']}: generic scene"
```
This MUST pass with 0 failures.

---

## ⛔ MANDATORY VISUAL VALIDATION LOOP — READ BEFORE ANYTHING ELSE ⛔

**HISTORY:** PROMPT-07 through PROMPT-15 ALL passed their own numerical tests while producing visually broken composites. Neither AI agent (Claude nor Codex) actually looked at the output. Tim was the only one checking. This section exists to prevent that from EVER happening again.

### FOR CODEX (the agent reading this file in a Codex session):

**After ANY change to visual/compositor code (cover_compositor.py, pdf_swap_compositor.py, pdf_compositor.py, overlay/mask logic):**

1. **Generate comparison artifacts** — run `scripts/visual_qa.py` (or `scripts/generate_comparison.py`) to produce:
   - Side-by-side comparison images (original vs composite)
   - Zoomed medallion crops showing frame ring detail
   - Difference heatmaps highlighting changed pixels
2. **Run structural assertions** (not just pixel deltas):
   - Frame ring pixels: extract ornamental border region, compare against original → MUST be <1% changed
   - Art containment: AI art pixels ONLY within medallion boundary, NOT in frame region
   - Medallion center: contains new art (not blank, not old teal fill)
   - Aspect ratio: art not stretched or squashed
3. **Save all artifacts to `qa_output/`** — these MUST be committed so Claude and Tim can inspect them
4. **Honest reporting:**
   - If structural assertions pass: "Structural checks passed. Visual artifacts saved to qa_output/ for human review."
   - If ANY check fails: "FAILED — [specific check] did not pass. Details: [numbers]. NOT claiming success."
   - If you cannot run visual QA: "I could not verify visual output. Reason: [reason]. Human review required."
5. **NEVER claim visual success based on numerical tests alone**
6. **NEVER use phrases like "verified visually" unless you actually rendered and described what you saw**
7. **If you cannot open and inspect images, SAY SO — do not claim success**

**Golden reference system:**
- `qa_output/golden/` contains known-good composites
- Every new composite is compared against its golden reference
- If no golden reference exists, flag for human review

### FOR CLAUDE (reading this in Cowork/Desktop):

**Before declaring ANY compositor change "done":**
1. Open the live app in Chrome browser tools
2. Trigger the actual operation (upload file, composite, generate)
3. Screenshot the output
4. Visually inspect and describe what you see in plain English
5. Compare against Tim's feedback/screenshots
6. Only THEN tell Tim whether it works

**If you cannot visually verify:** Say "I was unable to visually verify" — NEVER say "This should work"

### TIM IS FINAL AUTHORITY
- Tim's visual assessment overrides ALL numerical checks and AI claims
- If Tim says it's broken, it's broken — no arguing, no "but the numbers say..."
- Iterate until Tim confirms visual quality

---

## CURRENT ACTIVE: PROMPT-38 (2026-03-10)

**PROMPT-38: 📋 READY TO SEND** — Scene-First Prompt Restructure for Content Relevance. Root cause: `{SCENE}` appears 50% through each prompt template (~400 chars of style directives come first). AI model prioritizes style over scene → covers match style but depict WRONG content. Fix: (1) Restructure ALL 10 prompt templates — scene FIRST, style second, (2) Inject protagonist name for visual grounding, (3) Backend scene emphasis with "CRITICAL SCENE REQUIREMENT" anchoring, (4) Filter generic enrichment placeholders and fall back to `_motif_for_book()`.

Codex prompt: `Codex Prompts/PROMPT-38-SCENE-FIRST-PROMPT-RESTRUCTURE.md`
Paste-ready message: `Codex Prompts/CODEX-MESSAGE-PROMPT-38.md`

## PREVIOUS

**PROMPT-37 (2026-03-10): ✅ DEPLOYED** — Scene rotation via `buildScenePool()`, Save Raw 6-file output, removed directory-scanning fallbacks, fixed hardcoded "99 books". Covers now rotate through different scenes but content is STILL not relevant — style overrides scene in prompt templates.

**PROMPT-36 (2026-03-10): ✅ DEPLOYED** — Reverted compositor blanking code (was never implemented). Compositor confirmed clean.

**PROMPT-35 (2026-03-10): ⚠️ NOT IMPLEMENTED** — Superseded by PROMPT-37.

**PROMPT-34 (2026-03-10): ✅ DEPLOYED** — Forced book-specific enrichment into ALL prompts (frontend + backend + image_generator). Fixed generation reliability (DEAD_JOB_TIMEOUT 3→8min, heartbeat fix). Preserved enrichment across browser catalog sync. Commits: 225adbb, ba1b9e01.

**PROMPT-33 (2026-03-10): ✅ DEPLOYED** — Fixed {SCENE}/{MOOD}/{ERA} placeholder resolution. Added `_resolve_alexandria_placeholders()`, `_sanitize_prompt_placeholders()` safety net, fixed `defaultMoodForBook()` to use `emotional_tone`, fixed batch page enrichment. Commits: f04e11c, 76014d9, 036fc30.

## PREVIOUS

**PROMPT-32 (2026-03-10): ✅ DEPLOYED** — Switch Drive upload to Shared Drive folder `0ABLZWLOVzq-qUk9PVA`. `supportsAllDrives=True` on all API calls. Save Raw + Drive upload working.

**PROMPT-31 (2026-03-09): ✅ DEPLOYED** (commit 92faf7a, Railway 97f2f7f6 SUCCESS) — App stability fixed, cover-preview 404 fixed, visual-qa 502 fixed, 22 models with pricing.

## PREVIOUS

**PROMPT-30 (2026-03-09): ✅ DEPLOYED** (version 2.1.1, commits ba4d78a + 271d211, Railway 5c8487b0 SUCCESS):
- ✅ All 2,397 books enriched (0 generic — Gulliver mentions Lilliputians, Dracula mentions Transylvania)
- ✅ Searchable book combobox on Iterate page
- ✅ `scripts/validate_prompt_resolution.py` created and passes
- ✅ Gemini pricing fixed ($0.020/$0.003)
- ❌ Intermittent crashes (50.3% API success rate)
- ❌ Cover preview 404, Visual QA 502
- ❌ 8 models missing from dropdown

**PROMPT-29: ⚠️ PARTIALLY IMPLEMENTED** (commit 7452737):
- ✅ Catalog expanded to 2,397 books
- ✅ Enrichment pipeline rewritten (better LLM prompts, banned phrases, fixed fallback)
- ✅ Riverflow V2 Fast pricing fixed ($0.04→$0.02)
- ❌ Enrichment NEVER RUN — superseded by PROMPT-30

## PREVIOUS DEPLOYMENTS

**PROMPT-28: ✅ DEPLOYED** — Replaced WILDCARD 1 → Dramatic Graphic Novel, WILDCARD 2 → Vintage Travel Poster.

**PROMPT-27: ✅ DEPLOYED (PARTIAL)** — Drive upload code fix works. Production blocker: service account quota. PROMPT-29 Task 2 continues this fix.

**PROMPT-26: ✅ DEPLOYED** — Removed 16 legacy prompts. 20 prompts remain.

**PROMPT-25: ✅ DEPLOYED** — Genre-aware rotation + scene variation.

**Status:** DEPLOYED (commit 2605175, Railway deployment d18aa7b7 SUCCESS). Code fix works: structured per-file Drive failures, retry button, `/api/drive-status` endpoint. **But production blocker remains Google-side:** service account cannot upload files — "Service Accounts do not have storage quota... use shared drives or OAuth delegation instead." Needs either shared drive or OAuth delegation to actually upload files.

## PREVIOUS: PROMPT-25 (Genre-Aware Rotation + Scene Variation — 2026-03-09) — ✅ DEPLOYED

**Status:** DEPLOYED. Confirmed live — "Smart rotation (genre-matched + scene variety)" visible in dropdown.

**Changes (4 tasks):**
1. **Scene variation pool** — new `buildScenePool(book, count)` collects ALL available scenes from enrichment data (iconic_scenes, protagonist, setting, motifs, characters) instead of just the first iconic scene. Each variant gets a genuinely different scene description.
2. **Genre-aware rotation** — new `buildGenreAwareRotation(book, variantCount)` returns `[{promptId, sceneOverride}]` per variant. Uses existing `genrePromptConfigForBook()` for genre matching. Passes unique `sceneOverride` to existing `applyPromptPlaceholders()` 3rd parameter.
3. **Fix WILDCARD 4** — Celestial Cartography too similar to BASE 5. Rewritten to cartographic/scientific aesthetic (maps, compass roses, parchment tones).
4. **Prompt + scene labels on cards** — each result card shows prompt name badge + scene snippet so user can see what's different about each variant.

See `Codex Prompts/PROMPT-25-GENRE-AWARE-ROTATION.md` for full implementation details.

## PREVIOUS: PROMPT-24 (Prompt Auto-Rotation + Save Button Fix — 2026-03-08) — ✅ DEPLOYED

**Status:** DEPLOYED (commit a3e8148, Railway deployment 8b4f45ec SUCCESS).
- ✅ Auto-rotation through 10 prompts (each variant gets different prompt)
- ✅ Save Prompt button visible + functional
- ✅ Winners filter in Prompts page and iterate dropdown
- ❌ **ISSUE:** Rotation is BLIND — cycles all 10 prompts regardless of book genre → PROMPT-25
- ❌ **ISSUE:** BASE 5 and WILDCARD 4 produce near-identical cosmic output → PROMPT-25

## PREVIOUS: PROMPT-23 (Rewrite Prompts — Scene-Only Circular Illustrations — 2026-03-08) — ✅ DEPLOYED

**Status:** DEPLOYED (commit 050f63d, Railway deployment ed66858c SUCCESS).
- ✅ All 10 prompts rewritten — scene-only, no frame/border/ornament language
- ✅ BASE prompts use "golden-age illustration style" (not "oil painting")
- ✅ Extended negative prompt with anti-frame/anti-ornament terms
- ✅ Save Prompt button + Winners filter infrastructure deployed
- ❌ **ISSUE:** Save Prompt button not visible (CSS overflow) → Fix in PROMPT-24
- ❌ **ISSUE:** All variants use same prompt (no rotation) → Fix in PROMPT-24

## PREVIOUS: PROMPT-22 (Model Fix + Prompts + Save Raw — 2026-03-08) — ✅ DEPLOYED

**Status:** DEPLOYED and verified. Commits: 7fcd7e6, 4874799, fb0edd4, 7b618c3. Tip: 03a92e8.
- ✅ Nano Banana Pro routes to `openrouter/google/gemini-3-pro-image-preview`
- ✅ 10 Alexandria prompts live with {SCENE}/{MOOD}/{ERA} variable injection
- ✅ Save Raw button works (Drive upload degrades gracefully — storageQuotaExceeded)
- ❌ **ISSUE:** Prompts describe complete covers with frames — need rewrite in PROMPT-23

---

## PREVIOUS COMPOSITOR FIX (PROMPT-21 — Blend Radius Fix + Guardrail — 2026-03-05)

**Status:** PROMPT-21 deployed (commit e55e53d, Railway deployment dbeb6051). Code changes verified correct (DEFAULT_BLEND_RADIUS=840, guardrail thresholds raised). QA comparison sheets with synthetic gradient show frame preserved. **However, live generations with real AI art still show the compositor issue — frame is not correctly preserved in production output.** The problem remains unsolved as of 2026-03-06. A developer hire is in progress to fix this.

**Root cause (compositor):** Source PDFs contain `/Im0` (2480 x 2470 px, CMYK) which holds BOTH the illustration art AND the gold ornamental frame as one combined image. An `/SMask` clips Im0 onto the cover.

**PROMPT-20 bug:** The `detect_blend_radius_from_smask()` function used SMask < 255 to find the blend radius → returned 938. But SMask < 255 marks the **outer edge of the entire medallion**, not the inner edge of the frame. Cross-book pixel analysis proves: frame ornaments start at r≈870. Using 938 covered the entire frame with new art.

**PROMPT-21 fix:** Hardcode blend radius to **840** (30px margin before frame starts at r≈870). Remove SMask-based detection (it finds the wrong boundary).

**Root cause (guardrail):** Content guardrail in `image_generator.py` rejects AI art with strong linear structures (ship masts, architecture) as "rectangular_frame_artifact" at threshold 0.22. PROMPT-21 raises to 0.35.

**Fix approach (Im0 layer swap, corrected radius):**
1. Open the source PDF for the book
2. Extract Im0 (the combined art+frame image)
3. Within Im0, replace the CENTER art area with new AI art (geometric circle, radius **840** from Im0 center, 20px feather)
4. Keep the OUTER frame ring pixels from the original Im0 (frame starts at r≈870)
5. The new art is BEHIND the frame — within Im0 itself, frame pixels sit on top
6. Write modified Im0 back into PDF, keeping original SMask
7. Render modified PDF at 300 DPI → final composite JPG

**Key files:**
- `Codex Prompts/PROMPT-21-FIX-BLEND-RADIUS-AND-GUARDRAIL.md` — current prompt (fixes PROMPT-20 bugs)
- `Codex Prompts/CODEX-MESSAGE-PROMPT-21.md` — paste-ready Codex message
- `Codex Prompts/PROMPT-20-IM0-LAYER-SWAP-COMPOSITOR.md` — original architecture prompt

**Critical geometry (from cross-book pixel analysis):**
- Im0: 2480 x 2470, center (1240, 1235)
- r ≤ 860: ART pixels (different between books)
- r = 870-890: TRANSITION (frame ornaments appear)
- r ≥ 900: SOLID FRAME (99%+ identical across all books)
- **Correct blend radius: 840** (not 938)

**This eliminates:** frame_mask.png, config/frame_overlays/, extract_frame_overlays.py, color-based metal detection, SMask-based radius detection.

**DO NOT:** Use SMask values to determine blend radius (it finds the wrong boundary). Replace Im0 entirely. Modify the SMask. Do color-based pixel detection. Punch holes.

**Source covers:** All books have .ai + .pdf + .jpg files in `Input Covers/`. The catalog currently has 2,400+ books and is growing. Google Drive: https://drive.google.com/drive/folders/1ybFYDJk7Y3VlbsEjRAh1LOfdyVsHM_cS

---

## WORKFLOW RULES
- **Claude (Cowork/Desktop Chat) = CEO / Project Manager.** Analyzes problems, writes Codex prompts, manages project state. NEVER writes production code directly.
- **Codex = Senior Developer.** Implements ALL code changes. Every `.py`, `.js`, `.css`, `.html` edit goes through a Codex prompt written by Claude.
- **Tim = Founder / Product Owner.** Provides requirements, tests deployed apps, sends Codex prompts.
- All prompts live in `Codex Prompts/PROMPT-XX-*.md` with paste-ready messages in `Codex Prompts/CODEX-MESSAGE-PROMPT-XX.md`.
- If you are an AI agent reading this: you write prompts, NOT code. The only files you should create/edit are `.md` files in `Codex Prompts/` and project tracking files.

### ⛔ ALWAYS USE A NEW PROMPT NUMBER — NEVER REUSE OR CONTINUE A PREVIOUS PROMPT
**Codex requires a fresh prompt file for every submission.** It will not accept or re-run a previously submitted prompt number. When writing a new Codex prompt:
1. Always increment the prompt number (e.g., PROMPT-30 → PROMPT-31 → PROMPT-32)
2. Never resubmit the same PROMPT-XX number, even with different content
3. Never tell Codex to "continue" or "finish" a previous prompt — write a NEW prompt with its own number
4. Reference what the previous prompt accomplished, then specify only the NEW/remaining work
5. Each prompt file must be self-contained — Codex starts a fresh conversation every time

## Project Context
This repository implements the Alexandria cover workflow from single-title iteration to scaled batch production.
Always read `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/Project state Alexandria Cover designer.md` before major work.

## Runtime Snapshot
- Version: `2.0.0`
- Python: `3.11+` (validated)
- Core API endpoints documented in app: `88` (`/api/docs`)
- Tests: `408` passing
- Coverage (`src/`): `91.00%`
- Primary app entrypoint: `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/scripts/quality_review.py`

## First-Principles System Model
The app is built around six invariants:
1. Valid input contract (schema/range/path validation).
2. Deterministic orchestration (idempotent job keys, explicit state transitions).
3. Resilient generation/failover (provider abstraction, retries, circuit behavior).
4. Quality/composition gates (quality scoring, similarity checks, export constraints).
5. Observable operation (health, metrics, audit logs, costs, reports).
6. Safe persistence/recovery (atomic writes, SQLite path, migration, backup/restore).

## Architecture (v2)
- Web/API: `scripts/quality_review.py` (ThreadingHTTPServer + worker integration).
- Job execution: `src/job_store.py` + `scripts/job_worker.py`.
- Data layer: JSON compatibility + SQLite (`src/database.py`, `src/db.py`, `src/repository.py`).
- Generation: prompting (`src/prompt_generator.py`, `src/intelligent_prompter.py`) + image providers (`src/image_generator.py`).
- Post-processing: quality (`src/quality_gate.py`), compositing (`src/cover_compositor.py`), exports (`src/output_exporter.py`, platform exporters).
- Delivery: Drive sync + automated delivery (`src/drive_manager.py`, `src/delivery_pipeline.py`).
- Observability: audit/cost/error metrics (`src/audit_log.py`, `src/cost_tracker.py`, `src/error_metrics.py`).

## Source Module Inventory (`src/`)
- `__init__.py`: package metadata/version.
- `api_responses.py`: standardized success/error payload helpers.
- `api_validation.py`: strict request validation and normalization.
- `archiver.py`: non-winner and output archival helpers.
- `audit_log.py`: signed and structured audit log events.
- `book_enricher.py`: metadata enrichment pipeline for titles.
- `book_metadata.py`: tags/notes metadata read/write utilities.
- `catalog_manager.py`: multi-catalog CRUD and active catalog resolution.
- `config.py`: environment/config/catalog runtime resolution.
- `cost_tracker.py`: cost ledger, budgets, and spend analytics.
- `cover_analyzer.py`: cover-region detection and analysis.
- `cover_compositor.py`: medallion compositing into template covers.
- `database.py`: SQLite schema/initialization/indexes/FTS.
- `db.py`: pooled SQLite access with retry and transactions.
- `delivery_pipeline.py`: automatic export + sync delivery orchestration.
- `disaster_recovery.py`: backup restore/integrity helpers.
- `drive_manager.py`: bidirectional drive sync coordination.
- `error_metrics.py`: runtime error counters and aggregation.
- `export_amazon.py`: Amazon KDP export set builder.
- `export_ingram.py`: Ingram export artifact generation.
- `export_social.py`: social platform image export variants.
- `export_utils.py`: shared export path/image/manifest utilities.
- `export_web.py`: web asset export + manifest generation.
- `gdrive_sync.py`: low-level Drive API sync primitives.
- `image_generator.py`: model/provider orchestration and failover.
- `intelligent_prompter.py`: LLM-assisted prompt synthesis/ranking.
- `job_store.py`: persistent async job state/attempt history.
- `logger.py`: structured logging setup.
- `mockup_generator.py`: mockup rendering pipeline.
- `notifications.py`: webhook/notification dispatch.
- `output_exporter.py`: core output export workflow.
- `pipeline.py`: end-to-end generation pipeline orchestrator.
- `prompt_generator.py`: deterministic prompt generation templates.
- `prompt_library.py`: prompt library save/load/mix operations.
- `quality_gate.py`: quality scoring and validation gates.
- `repository.py`: JSON/SQLite repository abstraction.
- `safe_json.py`: atomic JSON read/write helpers.
- `security.py`: sanitization, path safety, key masking/scrubbing.
- `similarity_detector.py`: image similarity matrix + clustering.
- `social_card_generator.py`: social card overlays/templates.
- `state_store.py`: runtime state persistence.
- `thumbnail_server.py`: thumbnail generation/serving utilities.

## Scripts Inventory (`scripts/`)
- `quality_review.py`: web server + API routes.
- `job_worker.py`: standalone worker service mode.
- `migrate_to_sqlite.py`: JSON to SQLite migration.
- `load_test.py`: concurrent API load benchmark.
- `validate_config.py`: startup/runtime configuration validation.
- `validate_environment.py`: interpreter/dependency/network checks.
- Plus operational utilities: `archive_non_winners.py`, `cleanup.py`, `regenerate_weak.py`, `generate_catalog.py`, `generate_thumbnails.py`, `prepare_print_delivery.py`, `disaster_recovery.py`, `import_catalog.py`, `export_winners.py`, `auto_select_winners.py`, `ab_test_prompts.py`, `optimize_style_anchors.py`, `tune_model_prompts.py`.

## API Surface
- Canonical live API reference: `/api/docs` (auto-generated by `_build_api_docs_html` in `scripts/quality_review.py`).
- Categories covered:
  - `Catalogs/Books`: catalog list/switch, paginated books, tags/notes.
  - `Generation/Jobs`: enqueue generate/regenerate, job list/detail/cancel, SSE events.
  - `Review`: iterate/review datasets, winner selection, review sessions/queue.
  - `Analytics`: costs, budget, quality trends/distribution, model comparison, completion, reports, audit.
  - `Similarity/Mockups`: similarity matrix/alerts/clusters, mockup status/images/zip.
  - `Export/Delivery`: Amazon/Ingram/Social/Web exports, export listing/download/delete, delivery status/tracking/batch.
  - `Drive`: push/pull/full sync, schedule CRUD, status.
  - `Admin/Ops`: migrate-to-sqlite, health/version/metrics/cache/docs.

## Database Schema (SQLite)
Defined in `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/src/database.py`.
Core tables:
- `books`
- `variants`
- `generations`
- `jobs`
- `costs`
- `audit_log`
Also includes indexes + FTS for search.

## Config and Env
- Primary env/config loader: `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/src/config.py`
- Key toggles:
  - `USE_SQLITE`
  - `SQLITE_DB_PATH`
  - `JOB_WORKER_MODE`
  - `JOB_WORKERS`
  - `WEB_READ_RATE_LIMIT_PER_MINUTE`
  - provider keys (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, etc.)

## Safety Rules
1. Never modify files under `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/Input Covers`.
2. Never edit `/Users/timzengerink/Documents/Coding Folder/Alexandria Cover designer/Project state Alexandria Cover designer.md`.
3. Keep all file-serving paths sanitized via `security.sanitize_path`.
4. Keep API responses machine-consistent (`ok`, error payload fields).
5. Preserve 300 DPI and layout constraints for generated cover outputs.

## Test and Verification Commands
- Full tests: `.venv/bin/pytest tests --maxfail=1`
- Coverage gate: `.venv/bin/pytest --cov=src --cov-config=/dev/null --cov-fail-under=85 -q`
- Performance marker: `.venv/bin/pytest -m performance -q`
- Config validation: `.venv/bin/python scripts/validate_config.py`
- Environment validation: `.venv/bin/python scripts/validate_environment.py`
- Compile check: `python3 -m compileall src scripts`
- Docker verification:
  - `docker build -t alexandria-cover-designer:v2 .`
  - `docker run -d -p 8001:8001 --name designer-test alexandria-cover-designer:v2`

## Complete API Reference (from /api/docs)

Total endpoints: `88`

| Method | Path | Parameters | Example Response | Description |
|---|---|---|---|---|
| `GET` | `/iterate` | `-` | `-` | Interactive single-cover generation page. |
| `GET` | `/review` | `-` | `-` | Winner review and archive page. |
| `GET` | `/catalogs` | `-` | `-` | Generate winner catalogs/contact sheets/all-variants PDFs. |
| `GET` | `/history` | `-` | `-` | Generation history viewer with filters. |
| `GET` | `/dashboard` | `-` | `-` | Cost/quality dashboard. |
| `GET` | `/similarity` | `-` | `-` | Cross-book similarity heatmap, alerts, and clusters. |
| `GET` | `/mockups` | `-` | `-` | Mockup gallery and generation controls. |
| `GET` | `/api/version` | `-` | `{"version":"2.0.0"}` | Current application version. |
| `GET` | `/api/catalogs` | `-` | `{"catalogs":[...],"active_catalog":"classics"}` | Available catalogs for selector dropdowns. |
| `GET` | `/api/health` | `-` | `{"status":"ok",...}` | Runtime health and config status. |
| `GET` | `/api/metrics` | `-` | `{"cache":{...},"errors":{...},"jobs":{...}}` | Operational counters, error metrics, queue state, and worker service telemetry. |
| `GET` | `/api/workers` | `-` | `{"workers":{...}}` | Worker mode + heartbeat status for inline/external workers. |
| `GET` | `/api/audit-log?limit=100` | `limit` | `{"items":[...]}` | Signed audit entries for cost/destructive operations. |
| `GET` | `/api/analytics/costs?period=7d` | `period,catalog` | `{"summary":{...}}` | Cost totals and operation mix from cost ledger. |
| `GET` | `/api/analytics/costs/by-book` | `period,catalog` | `{"books":[...]}` | Book-level cost breakdown. |
| `GET` | `/api/analytics/costs/by-model` | `period,catalog` | `{"models":[...]}` | Model/provider cost breakdown. |
| `GET` | `/api/analytics/costs/timeline?period=30d&granularity=daily` | `period,granularity,catalog` | `{"timeline":[...]}` | Cost trend with cumulative totals. |
| `GET` | `/api/analytics/budget` | `catalog` | `{"budget":{...}}` | Budget limit, warning/blocked state, and projected spend. |
| `POST` | `/api/analytics/budget` | `{"catalog":"...","limit_usd":100,"warning_threshold":0.8}` | `{"ok":true}` | Set budget limit/threshold. |
| `POST` | `/api/analytics/budget/override` | `{"catalog":"...","extra_limit_usd":25,"duration_hours":24}` | `{"ok":true}` | Temporary budget increase. |
| `GET` | `/api/analytics/quality/trends?period=30d` | `period,catalog` | `{"trend":[...]}` | Quality evolution over time. |
| `GET` | `/api/analytics/quality/distribution` | `catalog` | `{"bins":[...]}` | Quality score histogram. |
| `GET` | `/api/analytics/models/compare` | `catalog` | `{"models":[...],"recommended_model":"..."}` | Quality/cost/speed/failure comparison. |
| `GET` | `/api/analytics/completion` | `catalog` | `{"completion_percent":85.8}` | Winner completion and production-readiness summary. |
| `POST` | `/api/analytics/export-report` | `{"period":"30d"}` | `{"report_id":"..."}` | Generate report artifact in data/reports. |
| `GET` | `/api/analytics/reports` | `-` | `{"reports":[...]}` | List generated analytics report files. |
| `POST` | `/api/admin/migrate-to-sqlite` | `{"db_path":"data/alexandria.db"}` | `{"ok":true,"summary":{...}}` | One-shot migration command for scale mode. |
| `GET` | `/api/jobs?status=queued,running&limit=50` | `status,limit,book,catalog` | `{"jobs":[...],"count":12}` | List persisted async generation jobs. |
| `GET` | `/api/jobs/{id}` | `job_id` | `{"job":{...},"attempts":[...]}` | Inspect one async job including attempt history. |
| `GET` | `/api/review-data?catalog=classics&limit=25&offset=0` | `catalog,limit,offset,sort,order,search,status,tags` | `{"books":[...],"pagination":{...}}` | Paginated review books, winners, and filters. |
| `GET` | `/api/iterate-data?catalog=classics&limit=25&offset=0` | `catalog,limit,offset,sort,order,search,status` | `{"books":[...],"pagination":{...}}` | Paginated iterate books + model configuration. |
| `GET` | `/api/prompt-performance` | `-` | `{"patterns":{...}}` | Prompt performance breakdown for intelligent prompting. |
| `GET` | `/api/history?book=2` | `book` | `{"items":[...]}` | History subset for one book. |
| `GET` | `/api/generation-history?book=2&model=flux&status=success&limit=50&offset=0` | `book,model,provider,status,date_from,date_to,quality_min,quality_max,limit,offset` | `{"items":[...],"total":123,"pagination":{...}}` | Global sortable/filterable generation records. |
| `GET` | `/api/dashboard-data` | `-` | `{"summary":{...},...}` | Cost and quality analytics for charts. |
| `GET` | `/api/weak-books?threshold=0.75` | `threshold,catalog` | `{"books":[...]}` | Books below a quality threshold. |
| `GET` | `/api/regeneration-results?book=15` | `book` | `{"results":[...]}` | Read saved re-generation comparison results. |
| `GET` | `/api/review-queue?threshold=0.90` | `threshold` | `{"queue":[...],"auto_approve":34}` | Ordered speed-review queue with confidence and summary buckets. |
| `GET` | `/api/review-session/{id}` | `session_id` | `{"session":{...}}` | Load a saved speed-review session state. |
| `GET` | `/api/review-stats` | `-` | `{"sessions":[...]}` | Aggregate completed review session metrics. |
| `GET` | `/api/similarity-matrix?threshold=0.25&limit=50&offset=0` | `threshold,limit,offset` | `{"pairs":[...],"pagination":{...}}` | Paginated similarity pairs for large catalogs. |
| `GET` | `/api/similarity-alerts?threshold=0.25` | `threshold` | `{"alerts":[...]}` | Pairs below similarity threshold. |
| `GET` | `/api/similarity-clusters` | `-` | `{"clusters":[...]}` | Connected clusters of visually similar covers. |
| `GET` | `/api/cover-hash/15` | `-` | `{"hash":{...}}` | pHash/dHash/histogram values for one winner. |
| `GET` | `/api/mockup-status?limit=25&offset=0` | `limit,offset` | `{"books":[...],"pagination":{...}}` | Paginated per-book mockup completion status. |
| `GET` | `/api/exports` | `catalog,limit,offset` | `{"exports":[...],"pagination":{...}}` | Export artifacts with size and file counts. |
| `GET` | `/api/exports/{id}/download` | `id` | `binary zip` | Build and stream a ZIP for a single export artifact. |
| `GET` | `/api/delivery/status` | `catalog` | `{"enabled":true,...}` | Delivery automation settings and completion summary. |
| `GET` | `/api/delivery/tracking` | `catalog,limit,offset` | `{"items":[...]}` | Per-book delivery status across platforms. |
| `GET` | `/api/archive/stats` | `catalog` | `{"archive_size_gb":...}` | Archive size, count, and date range. |
| `GET` | `/api/storage/usage` | `catalog` | `{"total_gb":...}` | Storage breakdown + cleanup suggestion. |
| `GET` | `/api/mockup/{book}/{template}` | `book,template` | `binary image` | Serve one generated mockup image. |
| `GET` | `/api/mockup-zip?book=15` | `book` | `{"url":"/...zip"}` | Bundle all mockups for one book as ZIP. |
| `POST` | `/api/save-selections` | `{"selections":{...}}` | `{"ok":true}` | Persist winner selections with metadata. |
| `POST` | `/api/enrich-book` | `{"book":15}` | `{"ok":true,"book":{...}}` | Generate/refresh LLM enrichment metadata for one title. |
| `POST` | `/api/enrich-all` | `{}` | `{"ok":true,"summary":{...}}` | Generate enrichment metadata across the full catalog. |
| `POST` | `/api/generate-smart-prompts` | `{"book":15,"count":5}` | `{"ok":true,"book":{...}}` | Generate AI-authored prompts plus quality scores. |
| `POST` | `/api/generate-mockup` | `{"book":15,"template":"desk_scene"}` | `{"ok":true}` | Generate one mockup template for one book. |
| `POST` | `/api/generate-all-mockups` | `{"book":15}\|{"all_books":true}` | `{"ok":true}` | Generate all selected templates for one/all books. |
| `POST` | `/api/generate-amazon-set` | `{"book":15}\|{"all_books":true}` | `{"ok":true}` | Generate 7-image Amazon listing set. |
| `POST` | `/api/generate-social-cards` | `{"book":15,"formats":["instagram","facebook"]}` | `{"ok":true}` | Generate marketing cards for social platforms. |
| `POST` | `/api/save-prompt` | `{"name":"...","prompt_template":"..."}` | `{"ok":true,"prompt_id":"..."}` | Save prompt into prompt library. |
| `POST` | `/api/test-connection` | `{"provider":"all\|openai\|..."}` | `{"ok":true,"report":{...}}` | Validate provider connectivity. |
| `POST` | `/api/generate` | `{"book":2,"models":[...],"variants":5,"prompt":"...","async":true,"dry_run":false}` | `{"ok":true,"job":{...}}` | Queue async generation job (idempotent). Sync mode (async=false) is disabled by default unless ALLOW_SYNC_GENERATION=1. |
| `POST` | `/api/jobs/{id}/cancel` | `{"reason":"..."}` | `{"ok":true,"job":{...}}` | Cancel queued/retrying/running async job. |
| `POST` | `/api/regenerate` | `{"book":15,"variants":5,"use_library":true}` | `{"ok":true,"summary":{...}}` | Run targeted re-generation workflow. |
| `POST` | `/api/export/amazon` | `{"books":"1-20"}` | `{"ok":true,"export_id":"..."}` | Generate Amazon listing assets for winners. |
| `POST` | `/api/export/amazon/{book_number}` | `-` | `{"ok":true}` | Generate Amazon assets for one title. |
| `POST` | `/api/export/ingram` | `{"books":"1-20"}` | `{"ok":true}` | Generate IngramSpark print package. |
| `POST` | `/api/export/social?platforms=instagram,facebook` | `{"books":"1-20"}` | `{"ok":true}` | Generate multi-platform social cards. |
| `POST` | `/api/export/web` | `{"books":"1-20"}` | `{"ok":true}` | Generate web-optimized cover sizes + manifest. |
| `POST` | `/api/delivery/enable` | `-` | `{"ok":true}` | Enable automatic delivery pipeline for catalog. |
| `POST` | `/api/delivery/disable` | `-` | `{"ok":true}` | Disable automatic delivery pipeline for catalog. |
| `POST` | `/api/delivery/batch?platforms=amazon,social` | `{"books":"1-20"}` | `{"ok":true}` | Deliver selected/all winner books across configured platforms. |
| `POST` | `/api/sync-to-drive` | `{"selections":{...}}` | `{"ok":true,"summary":{...}}` | Sync selected winner files to Google Drive. |
| `POST` | `/api/drive/push` | `{"mode":"push"}` | `{"ok":true}` | Push local winners/mockups/exports to Drive layout. |
| `POST` | `/api/drive/pull` | `{"mode":"pull"}` | `{"ok":true}` | Pull new source covers from Drive input folder. |
| `POST` | `/api/drive/sync` | `{"mode":"bidirectional"}` | `{"ok":true}` | Run pull + push with conflict resolution. |
| `POST` | `/api/archive-non-winners` | `{"dry_run":true}` | `{"ok":true,"summary":{...}}` | Move non-winning variants to Archive/ (never delete). |
| `POST` | `/api/archive/old-exports?days=30` | `days` | `{"ok":true}` | Archive export packages older than N days. |
| `POST` | `/api/archive/restore/{book_number}` | `-` | `{"ok":true}` | Restore archived assets for a title. |
| `POST` | `/api/dismiss-similarity` | `{"book_a":1,"book_b":47}` | `{"ok":true}` | Mark a similarity pair as reviewed/acceptable. |
| `POST` | `/api/batch-approve` | `{"threshold":0.90}` | `{"ok":true,"summary":{...}}` | Confirm all winners above threshold for speed review. |
| `POST` | `/api/review-selection` | `{"book":15,"variant":3,"reviewer":"tim"}` | `{"ok":true}` | Persist a single manual speed-review selection. |
| `POST` | `/api/save-review-session` | `{"session_id":"...","books_reviewed":42}` | `{"ok":true}` | Save or complete a speed-review session snapshot. |
| `DELETE` | `/api/exports/{id}` | `id` | `{"ok":true}` | Delete export artifact and remove it from manifest. |
| `GET` | `/api/generate-catalog?mode=catalog\|contact_sheet\|all_variants` | `mode` | `{"ok":true,"download_url":"/...pdf"}` | Generate catalog/contact/all-variants PDF outputs. |
| `GET` | `/api/docs` | `-` | `HTML` | This documentation page. |
