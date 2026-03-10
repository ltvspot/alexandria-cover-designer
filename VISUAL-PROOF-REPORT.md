# PROMPT-36 Visual Proof Report

## Release

- Functional PROMPT-36 commit: `34171d7` (`Revert compositor blanking and stale 99-book defaults`)
- Railway deployment: `2d404ac4-7075-4b1c-8fa4-7ffb493c33a2` (`SUCCESS`)
- Live app: [https://web-production-900a7.up.railway.app](https://web-production-900a7.up.railway.app)

## Verification

Passed locally:

- `python3 -m py_compile src/pdf_swap_compositor.py src/config.py src/prompt_generator.py scripts/quality_review.py`
- `pytest tests/test_pdf_swap_compositor.py tests/test_config_module.py tests/test_prompt_generator_module.py tests/test_iterate_prompt_builder.py tests/test_batch_prompt_builder.py tests/test_quality_review_utils.py -q`
- `pytest tests/test_quality_review_server_smoke.py -q -k 'generate_dry_run_resolves_placeholder_prompt_from_enrichment or save_raw'`
- `rg -n "blank_description|get_text\\(|99 book|99 title|99 cover|book_count\\\": 99|books=99|total_books\\\":99|value=\\\"99\\\"" src scripts tests -S`
  - zero matches

Strict local compositor smoke:

- Source PDF: `Input Covers/1. A Room with a View - E. M. Forster copy/A Room with a View - E. M. Forster.pdf`
- Raw art: `Output Covers/raw_art/1/variant_1_openrouter_openai_gpt-5-image.png`
- Output JPG: `/tmp/alexandria-proof-live-prompt36-local/book1-pdf-swap.jpg`
- Output PDF: `/tmp/alexandria-proof-live-prompt36-local/book1-pdf-swap.pdf`
- `python scripts/verify_composite.py /tmp/alexandria-proof-live-prompt36-local/book1-pdf-swap.jpg --source-pdf '...A Room with a View - E. M. Forster.pdf' --output-pdf /tmp/alexandria-proof-live-prompt36-local/book1-pdf-swap.pdf --strict`
  - result: `ALL CHECKS PASSED - safe to commit`

Full-suite honesty check:

- `pytest tests/ --maxfail=3 -q` still stops on 3 unrelated failures:
  - `tests/test_api_docs_route_matrix.py::test_api_docs_get_routes_do_not_5xx`
  - `tests/test_prompt_library_module.py::test_alexandria_prompts_seeded_first_and_scene_placeholders_allowed`
  - `tests/test_review_workflow.py::test_review_selection_and_session_roundtrip`

## Live Proof

- Post-deploy readiness:
  - `GET /api/health` returned `status=ok`, `healthy=true`, `uptime_seconds=65`, `books_cataloged=2397`
  - startup check included `save_raw_drive_write_access = Drive upload: OK (Shared Drive)`
- Live Iterate run used book `3` (`Gulliver’s Travels into Several Remote Regions of the World`)
- Live `/api/jobs` snapshot during proof showed multiple completed variants with distinct scenes and prompt families
- Live `POST /api/save-raw` for backend job `cd05fa79-b6cc-46ba-b071-bad9e3681529` returned:
  - `status=saved`
  - `drive_ok=true`
  - `saved_files=6`
  - `drive_uploaded=6`
  - `drive_folder_id=1lK0ADZvLcSuKTkHiK8CAYpWYJDL6samY`

### Book 1 Text Intact

This is the strict local smoke proof for the reverted compositor path. The top-right title/subtitle region remains intact; PROMPT-36 removed the PROMPT-35 blanking logic entirely.

![PROMPT-36 book 1 text proof](/tmp/alexandria-proof-live-prompt36-local/book1-text-proof-prompt36.png)

### Live Scene Variation

This proof board is assembled from the live deployed `/api/jobs` payload plus the actual deployed composited JPGs served by the app.

![PROMPT-36 live scene variation proof](/tmp/alexandria-proof-live-prompt36/live-scene-variation-proof-prompt36.png)

### Live Save Raw 6-file Proof

![PROMPT-36 live save raw proof](/tmp/alexandria-proof-live-prompt36/live-save-raw-proof-prompt36.png)

### Live Health Proof

![PROMPT-36 live health proof](/tmp/alexandria-proof-live-prompt36/live-health-proof-prompt36.png)

## Notes

- Honest live residual issue: one smart-rotation wildcard job failed during proof with `OpenRouter error 400` wrapping `User location is not supported for the API use.` This is provider/runtime behavior on that live route, not a PROMPT-36 compositor regression.
- Despite that provider failure, the deployed app still produced multiple completed distinct variants for book `3`, and `Save Raw` completed successfully with all `6` exports uploaded to Drive.
