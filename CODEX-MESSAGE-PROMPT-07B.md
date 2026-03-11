# Codex Message for PROMPT-07B

## What to paste in the Codex chat:

---

**CRITICAL: Preserve the current design/UI/UX exactly as it is.** Only change the specific files listed in PROMPT-07B.

Read `PROMPT-07B-COMPOSITOR-AND-UI-FIXES.md` in the repo root.

**THE COMPOSITOR IS BROKEN.** The current output shows generated art BLEEDING PAST the gold ornamental frame — art pixels are visible outside the medallion circle where the scrollwork is thin. The art is also off-center. This is because `detectMedallionGeometry()` in `src/static/js/compositor.js` searches only ±4.5% of image dimensions — far too narrow.

**What to fix (4 things):**

1. **`src/static/js/compositor.js`** — Widen detection search window from ±4.5% to ±15%. Increase `OPENING_SAFETY_INSET` from 6 to **18** px. Widen coarse radius range from (0.84x-1.18x) to (0.65x-1.40x). Widen fine scan from ±8 to ±16px. Relax maxOffset guard from 34% to 55%. Add console.log showing detected geometry values. The specific line changes are all in the prompt file.

2. **`src/cover_compositor.py`** — Same parameter changes for Python backend. `OPENING_SAFETY_INSET_PX = 18`.

3. **Model grid layout** — Add `.model-grid` CSS class (grid layout with card-style borders) in `src/static/css/style.css`. Change `checkbox-group` to `model-grid` in `src/static/js/pages/iterate.js`.

4. **Backend style sync** — Replace the short 1-sentence style modifiers in `src/prompt_generator.py` with the enriched paragraph-length versions from `src/static/js/style-diversifier.js`. Also replace `renaissance-fresco` with `persian-miniature`.

**MANDATORY TESTING — DO NOT SKIP:**

After fixing, generate a cover for Book #1 with Nano Banana Pro and HONESTLY answer:
- Is the art COMPLETELY inside the gold frame with ZERO bleed-through?
- Is the art CENTERED (equal gap on all sides)?
- Does the art FILL the medallion (no cream/tan background visible)?

If ANY answer is NO, go back and fix it. DO NOT claim success if the art bleeds past the frame. Repeat the test with Book #9 and Book #25.

```bash
git add -A && git commit -m "fix: compositor centering, model grid, backend style sync (07B)" && git push
```

After done, send the deployed URL and a screenshot of a composited cover.

---
