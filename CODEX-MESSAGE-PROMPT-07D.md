# Codex Message for PROMPT-07D

## What to paste in the Codex chat:

---

**CRITICAL: Preserve the current design/UI/UX exactly as it is.** Only change the specific files listed in PROMPT-07D.

Read `Codex Prompts/PROMPT-07D-MASK-COMPOSITOR.md` in the repo.

**THREE ROUNDS OF FIXES HAVE FAILED.** Tuning detection parameters (07B x2) and switching to known geometry (07C) both still produce art bleeding past the frame. The root cause is now understood:

**The gold frame is NOT a circle.** It has irregular decorative scrollwork. The opening radius varies from **380px to 460px** depending on angle. All previous circular clips used **464px radius** which exceeds the actual opening at most angles, causing bleed-through.

**THE FIX: A pixel-perfect frame mask + conservative circular clip.**

`config/compositing_mask.png` has already been updated with a pixel-perfect mask derived from gold-color analysis of the actual frame. The Python backend ALREADY has code to load and use this mask (`_load_global_compositing_mask` at line 1269). We just need to reduce the circular clip ratio so the circle is also safely inside the frame.

**What to do (5 things):**

1. **`src/static/js/compositor.js`** — Change `OPENING_RATIO` from `0.965` to `0.74`. Change `OPENING_SAFETY_INSET` from `18` to `4`. Add `loadFrameMask()` that loads `/static/img/frame_mask.png` as ImageData. In `smartComposite`, after drawing art with circular clip, apply the frame mask pixel-by-pixel: where mask R > 128, replace art pixel with background fill color. In `buildCoverTemplate`, use the mask for punch-out when available (mask R < 128 = transparent). Version bump to v11. See PROMPT-07D for exact code.

2. **`src/static/js/app.js`** — Add `Compositor.loadFrameMask()` call at startup alongside existing `Compositor.loadRegions()`.

3. **`src/cover_compositor.py`** — Change `DETECTION_OPENING_RATIO` to `0.74`. Change `OPENING_SAFETY_INSET_PX` to `4`. Change `OVERLAY_PUNCH_INSET_PX` to `4`. The mask at `config/compositing_mask.png` is already correct and the existing `_load_global_compositing_mask()` will pick it up automatically.

4. **Model grid layout** — Add `.model-grid` CSS (grid layout with card borders) in `style.css`. Change `checkbox-group` to `model-grid` in `iterate.js`.

5. **Verify `/static/img/frame_mask.png` is accessible** — Load it in a browser. It's a grayscale PNG where 0=opening, 255=frame.

**MANDATORY TESTING:**

After fixing, open browser console. You MUST see:
- `[Compositor] Loaded geometry for 99 covers` (page load)
- `[Compositor] Loaded frame mask: 3784x2777` (page load)
- `[Compositor v11] Using known geometry for book X: cx=2864, cy=1620, clipRadius=366` (on generate)
- `[Compositor v11] Applying pixel-perfect frame mask` (on generate)

Generate a cover for Book #1 with Nano Banana Pro. HONESTLY answer:
- Is the art COMPLETELY inside the gold frame at ALL angles, including where decorative scrollwork narrows?
- Is there ZERO bleed-through at ANY point around the frame?
- Is the art CENTERED and FILLS the medallion opening?

If ANY answer is NO, debug the mask loading — do NOT go back to tuning circular clip parameters. The mask is the source of truth. Repeat with Book #9 and Book #25.

```bash
git add -A && git commit -m "fix: use pixel-perfect frame mask for compositing, kill circular clip (07D)" && git push
```

After done, send the deployed URL and a screenshot of a composited cover. Be HONEST about whether art bleeds past the frame — do not claim success if it doesn't look right.

---
