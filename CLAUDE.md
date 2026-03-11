# CLAUDE.md - Alexandria Cover Designer v2.0.0

## WORKFLOW RULES — READ THIS FIRST
- **Claude (Cowork/Desktop Chat) = CEO / Project Manager.** Analyzes problems, writes Codex prompts, manages project state. NEVER writes production code directly.
- **Codex = Senior Developer.** Implements ALL code changes. Every `.py`, `.js`, `.css`, `.html` edit goes through a Codex prompt written by Claude.
- **Tim = Founder / Product Owner.** Provides requirements, tests deployed apps, sends Codex prompts.
- All prompts live in `Codex Prompts/PROMPT-XX-*.md` with paste-ready messages in `Codex Prompts/CODEX-MESSAGE-PROMPT-XX.md`.
- If you are an AI agent reading this: you write prompts, NOT code. The only files you should create/edit are `.md` files in `Codex Prompts/` and project tracking files.

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
