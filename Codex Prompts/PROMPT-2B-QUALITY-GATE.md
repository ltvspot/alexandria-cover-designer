# Prompt 2B — Quality Gate (Scoring + Filtering)

**Priority**: MEDIUM — Ensures only good images proceed
**Scope**: `src/quality_gate.py`
**Depends on**: Prompt 2A (generated images must exist)
**Estimated time**: 30-45 minutes

---

## Context

Read `PROJECT-STATE.md`. After Prompt 2A, we have ~495 generated images in `tmp/generated/`. Some may be low quality (artifacts, wrong content, blank images, etc.). We need an automated quality gate to score and filter before compositing.

---

## Task

Create `src/quality_gate.py` with automated quality checks:

1. **Technical Quality**: Resolution, aspect ratio, no blank/solid images, no extreme noise
2. **Color Compatibility**: The illustration should have warm tones compatible with the navy/gold cover palette
3. **AI Artifact Detection**: Flag images with common AI artifacts (text-like patterns, distorted features)
4. **Diversity Check**: Ensure the 5 variants for each book are sufficiently different from each other
5. **Scoring**: Aggregate score 0-1, with configurable threshold (default 0.6)

### Output
- `data/quality_scores.json`: Per-image scores and pass/fail
- `data/quality_report.md`: Human-readable summary
- Images below threshold flagged for re-generation or manual review

---

## Verification Checklist

1. `py_compile` passes — PASS/FAIL
2. Score a known-good generated image → score ≥ 0.7 — PASS/FAIL
3. Score a blank/solid-color test image → score < 0.3 — PASS/FAIL
4. Score all images for one book (5 variants) → report generated — PASS/FAIL
5. Diversity check flags 5 identical images as "not diverse" — PASS/FAIL
6. `data/quality_scores.json` is valid JSON with all entries — PASS/FAIL
7. `data/quality_report.md` is readable and accurate — PASS/FAIL
