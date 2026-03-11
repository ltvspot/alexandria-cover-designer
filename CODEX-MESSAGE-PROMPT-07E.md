# Codex Message for PROMPT-07E

## What to paste in the Codex chat:

---

**CRITICAL: Preserve the current design/UI/UX exactly as it is.** Only change the specific files listed in PROMPT-07E.

Read `Codex Prompts/PROMPT-07E-COMPOSITOR-FIX.md` in the repo.

**THE PROBLEMS:** (1) Art appears too small inside the medallion, (2) art appears off-center — each image has different visual positioning, (3) original cover's background artwork is visible around the generated art.

**Root causes:** `config/compositing_mask.png` restricts art to ~380px radius. Content-aware cropping (`_smart_square_crop()`) shifts the crop center per image causing inconsistent centering. Cover overlay punch (462px) is smaller than art clip (464px) creating a gap where original cover shows.

**FOUR CHANGES:**

1. **Rename** `config/compositing_mask.png` to `config/compositing_mask.png.disabled` — This is the MOST IMPORTANT change. The mask is too restrictive and makes art tiny.

2. **Python backend** (`src/cover_compositor.py`) — Change 3 constants near the top:
   - `DETECTION_OPENING_RATIO` from `0.965` to `0.96`
   - `OPENING_SAFETY_INSET_PX` from `18` to `0`
   - `OVERLAY_PUNCH_INSET_PX` from `20` to `-4` (YES, negative! This makes the punch 4px BIGGER than the opening)

3. **Fix centering** (`src/cover_compositor.py`) — Replace `_smart_square_crop()` with a simple center crop. Remove all foreground detection / energy center logic. Just crop a centered square from the image. This ensures every image is consistently centered in the medallion.

4. **JS frontend** (`src/static/js/compositor.js`) — Change 2 constants:
   - `OPENING_RATIO` from `0.965` to `0.96`
   - `OPENING_SAFETY_INSET` from `18` to `0`
   - Fix `buildCoverTemplate()`: change the punch radius to `geo.openingRadius + 4`
   - If JS has a content-aware crop function, simplify it to center crop too
   - Bump version strings from `v10` to `v12`

5. **Model grid** — Add `.model-grid` CSS (grid layout with card borders) in `style.css`. Change `checkbox-group` to `model-grid` in `iterate.js`. See prompt for exact CSS.

**HOW TO VERIFY:**

After deploying, generate covers for Book #1, #9, and #25 with any model. For EACH:
- Does the art FILL most of the medallion circle? (Should fill to ~480px from center)
- Is there ANY original cover artwork visible around the generated art? (Should be NONE)
- Is the art CENTERED the same way in all three? (All should have identical edge ratios)
- Is there a thin gold frame border visible? (Should be the outermost ~16px ring)

**CRITICAL:** Compare all three covers side by side. The circle size and position should be IDENTICAL across all covers. Only the art content should differ.

If the original cover artwork is STILL visible: check that `config/compositing_mask.png` was actually renamed.
If centering still varies: check that `_smart_square_crop()` was actually simplified to center crop.

```bash
git add -A && git commit -m "fix: bigger art circle, center crop, no mask (07E)" && git push
```

---
