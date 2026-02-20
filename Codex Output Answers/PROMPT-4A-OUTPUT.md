# PROMPT-4A OUTPUT — Batch Orchestration (End-to-End Pipeline)

## Summary
Implemented a full end-to-end orchestration layer in `src/pipeline.py` and updated `scripts/run_pipeline.sh` as the convenience wrapper. The pipeline now supports single-cover iteration as the primary mode, all-model generation, prompt-library usage, selective reruns, batch-size chunking, resume, dry-run, error isolation, and run summaries.

## Files Modified
- `src/pipeline.py`
- `scripts/run_pipeline.sh`

## Features Implemented
- End-to-end flow per book:
  - prerequisite ensure (regions/prompts/library)
  - generate (single-cover and batch modes)
  - quality gate (book-scoped + retries)
  - composite
  - export
- Single-cover mode (D19):
  - `--book N`
  - supports `--model` / `--models` / `--all-models`
  - supports `--prompt-override`
- Prompt-library integration (D21):
  - `--use-library`
  - `--prompt-id <id>`
  - `--style-anchors a,b,c`
- All-models mode (D20): `--all-models`
- Selective rerun support:
  - `--variant 3`
  - `--variants 1-3` (variant-id range)
- Configurable variation counts (D22):
  - `--variants 10` interpreted as variation count when numeric
- Batch control:
  - `--books 1-5`
  - `--batch-size <N>`
- Resume and incremental processing:
  - pipeline state in `data/pipeline_state.json`
  - completed books skipped on rerun
- Error isolation:
  - one-book failure does not abort remaining books
- Summary reporting:
  - `data/pipeline_summary.json`
  - `data/pipeline_summary.md`
- Wrapper script updated with practical 20-title/single-cover usage examples.

## Verification Checklist
1. `py_compile` passes — **PASS**
2. Dry-run mode works (no generation writes, plan-only behavior) — **PASS**
3. Single-book end-to-end for book #2 works — **PASS**
4. Resume skips completed book on rerun — **PASS**
5. Books 1–5 batch run completes with outputs — **PASS**
6. Summary reports generated (`json` + `md`) — **PASS**
7. Failed book does not abort batch (`--books 1,999`) — **PASS**

## Notes
- Pipeline quality scoring is now scoped per active book to keep runtime predictable during iterative single-cover workflows.
- Default scope remains D23-friendly (20-title orientation) unless explicit book selection is provided.
