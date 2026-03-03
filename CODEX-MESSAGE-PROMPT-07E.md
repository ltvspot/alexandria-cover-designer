# Codex Message for PROMPT-07E

## What to paste in the Codex chat:

---

**CRITICAL: Preserve the current design/UI/UX exactly as it is.** Only change the specific files listed in PROMPT-07E.

Read `Codex Prompts/PROMPT-07E-COMPOSITOR-FIX.md` in the repo.

**THE PROBLEM:** Generated art appears as a tiny circle inside the medallion with the original cover's background artwork clearly visible around it. Root cause: `config/compositing_mask.png` restricts art to ~380px radius, AND the cover overlay punch (462px) is smaller than the art clip (464px), creating a gap where the original cover shows.

**THREE CHANGES:**

1. **Rename** `config/compositing_mask.png` to `config/compositing_mask.png.disabled` — This is the MOST IMPORTANT change. The mask is too restrictive and makes art tiny.

2. **Python backend** (`src/cover_compositor.py`) — Change 3 constants near the top:
   - `DETECTION_OPENING_RATIO` from `0.965` to `0.92`
   - `OPENING_SAFETY_INSET_PX` from `18` to `2`
   - `OVERLAY_PUNCH_INSET_PX` from `20` to `-2` (YES, negative! This makes the punch BIGGER than the opening, ensuring the cover overlay is transparent well beyond the art edge)

3. **JS frontend** (`src/static/js/compositor.js`) — Change 2 constants:
   - `OPENING_RATIO` from `0.965` to `0.92`
   - `OPENING_SAFETY_INSET` from `18` to `2`
   - Fix `buildCoverTemplate()`: change the punch radius to `geo.openingRadius + 4` (not bare `geo.openingRadius`)
   - Bump version strings from `v10` to `v12`

4. **Model grid** — Add `.model-grid` CSS (grid layout with card borders) in `style.css`. Change `checkbox-group` to `model-grid` in `iterate.js`. See prompt for exact CSS.

**HOW TO VERIFY:**

After deploying, generate a cover for Book #1 with any model. HONESTLY answer:
- Does the art FILL most of the medallion circle? (Not a tiny circle in the middle)
- Is there ANY original cover artwork (illustrations, scenery) visible around the generated art? (Should be NONE)
- Is there a thin gold frame border visible? (Should be the outermost ~38px ring)
- Is the art CENTERED?

If the original cover's artwork is STILL visible: check that `config/compositing_mask.png` was actually renamed. This is the #1 cause.

Repeat with Book #9 and Book #25.

```bash
git add -A && git commit -m "fix: remove restrictive mask, match art/punch circles (07E)" && git push
```

---
