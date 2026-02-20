# Prompt 5 — Visual QA Tool

**Priority**: MEDIUM — Helps Tim pick the best variants
**Scope**: `scripts/quality_review.py`, `src/static/review.html` (optional)
**Depends on**: Prompt 3B (exported covers must exist)
**Estimated time**: 30-45 minutes

---

## Context

Read `PROJECT-STATE.md`. Tim needs to review all 99 books × 5 variants and pick the best design for each. We need a tool that makes this easy.

---

## Task

Create a visual review tool (one or both approaches):

### Approach A: HTML Gallery (Recommended)
Generate a static HTML page that shows:
- All 99 books in a grid
- For each book: the original cover + 5 variant thumbnails side-by-side
- Click to zoom
- Checkboxes to mark "winner" per book
- Export selections as JSON

### Approach B: CLI Review
- Iterate through each book
- Open 6 images (original + 5 variants) in the default image viewer
- Prompt Tim to pick 1-5 or skip
- Save selections to JSON

### Output
- `data/variant_selections.json`: Tim's picks per book
- Stats: how many books reviewed, how many selected

---

## Verification Checklist

1. `py_compile` passes — PASS/FAIL
2. Generate review page/tool for 5 test books — PASS/FAIL
3. All 6 images (original + 5 variants) visible per book — PASS/FAIL
4. Selection mechanism works (checkbox or CLI input) — PASS/FAIL
5. Selections saved to JSON — PASS/FAIL
6. Full 99-book review tool loads without errors — PASS/FAIL
