# Prompt 4A — Batch Orchestration (End-to-End Pipeline)

**Priority**: HIGH — Ties everything together
**Scope**: `src/pipeline.py`, `scripts/run_pipeline.sh`
**Depends on**: All previous prompts (1A, 1B, 2A, 2B, 3A, 3B)
**Estimated time**: 30-45 minutes

---

## Context

Read `PROJECT-STATE.md`. All individual components exist. Now we need a single orchestrator that runs the entire pipeline end-to-end: analyze → generate → quality-check → composite → export.

---

## Task

Create `src/pipeline.py` — the master orchestrator:

1. **Incremental processing**: Track which books are done, skip completed ones on re-run
2. **Progress dashboard**: Show overall progress (e.g., `[42/99 books complete, 210/495 images]`)
3. **Error isolation**: If one book fails, continue with the rest
4. **Summary report**: At completion, generate a summary of successes/failures/quality scores
5. **CLI interface**: `python -m src.pipeline [--books 1-10] [--variants 1-3] [--dry-run] [--resume]`

Also create `scripts/run_pipeline.sh` as a convenience wrapper.

---

## Verification Checklist

1. `py_compile` passes — PASS/FAIL
2. Dry run mode works (no API calls, shows what would be generated) — PASS/FAIL
3. Process single book (book #2) end-to-end → 5 variants, 15 files — PASS/FAIL
4. Resume after partial run skips completed books — PASS/FAIL
5. Process books 1-5 → 25 variants, 75 files — PASS/FAIL
6. Summary report generated with pass/fail counts — PASS/FAIL
7. Failed book doesn't abort the batch — PASS/FAIL
