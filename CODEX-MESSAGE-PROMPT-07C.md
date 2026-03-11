# Codex Message for PROMPT-07C

## What to paste in the Codex chat:

---

**CRITICAL: Preserve the current design/UI/UX exactly as it is.** Only change the specific files listed in PROMPT-07C.

Read `Codex Prompts/PROMPT-07C-COMPOSITOR-REWRITE.md` in the repo.

**STOP TUNING DETECTION PARAMETERS.** Two rounds of parameter adjustments have failed. The auto-detection approach is fundamentally broken because the hardcoded fallback Y-center is **1350** but the actual medallion center is **1620** (270 pixels off). The detection algorithm starts from the wrong point and finds the wrong gold pixels every time.

**THE NEW APPROACH: Use known geometry from `cover_regions.json` instead of detecting.**

`config/cover_regions.json` already has verified coordinates for all 99 covers: `cx=2864, cy=1620, radius=500`. All covers use the same `navy_gold_medallion` template.

**What to do (3 things):**

1. **`src/static/js/compositor.js`** — Add a geometry registry (`loadRegions()` fetches from a new `/api/cover-regions` endpoint). Replace `smartComposite` to use `getKnownGeometry(bookId)` instead of calling `detectMedallionGeometry()`. Fix fallback constants: `DEFAULT_CY` from 1350 to **1620**, `DEFAULT_CX` from 2850 to **2864**, `DEFAULT_RADIUS` from 520 to **500**. Add `Compositor.loadRegions()` call in `app.js` at startup.

2. **`src/cover_compositor.py`** — Fix `FALLBACK_CENTER_Y` from 1350 to **1620** (and CX/RADIUS). In `_resolve_medallion_geometry()`, if region has valid center_x/center_y/radius (all > 0), skip detection entirely and use the region values directly. Detection should NEVER run when `cover_regions.json` provides coordinates.

3. **Add `/api/cover-regions` endpoint** in the Flask app (serves `config/cover_regions.json` as JSON).

4. **Model grid layout** — Add `.model-grid` CSS (grid layout with card borders) in `style.css`. Change `checkbox-group` to `model-grid` in `iterate.js`.

**MANDATORY TESTING:**

After fixing, open browser console. You MUST see:
- `[Compositor] Loaded geometry for 99 covers` (on page load)
- `[Compositor v10] Using known geometry for book X: cx=2864, cy=1620, ...` (on generate)
- You must NOT see any `[Compositor v9] Detection:` messages

Generate a cover for Book #1 with Nano Banana Pro. HONESTLY answer:
- Is the art COMPLETELY inside the gold frame with ZERO bleed-through?
- Is the art CENTERED (equal gap on all sides)?
- Does the art FILL the medallion?

If ANY answer is NO, debug the geometry registry loading — do NOT go back to tuning detection parameters. Repeat with Book #9 and Book #25.

```bash
git add -A && git commit -m "fix: compositor uses cover_regions.json geometry, kill auto-detection (07C)" && git push
```

---
