# Codex Message for PROMPT-19

## Task

Read and execute `PROMPT-19-FIX-COMPOSITING-EXACT.md` in the repo root.

## Context

PROMPT-18 was NOT implemented correctly. The specified approach (simple 3-layer compositing with known-good radii) was ignored. Instead, complex color-based "scrollwork gap" detection was added, `frame_mask.png` is still being loaded, invented constants `ART_TARGET_OUTER_RADIUS=700` and `ART_OUTER_INSET_PX=8` were used instead of the specified `FRAME_HOLE_RADIUS=540` and `ART_CLIP_RADIUS=600`, and the result looks terrible — rectangular art edges bleed through the frame, old illustration shows through, and frame ornaments are damaged.

## What to do — EXACT changes, one file only

**File: `src/cover_compositor.py`**

1. **Replace constants** (around line 52): Delete `ART_TARGET_OUTER_RADIUS = 700` and `ART_OUTER_INSET_PX = 8`. Add instead: `FRAME_HOLE_RADIUS = 540`, `ART_CLIP_RADIUS = 600`, `NAVY_FILL_RGB = (21, 32, 76)`.

2. **Replace `_build_fallback_frame_overlay()` entirely** (around line 1490): The function body is provided VERBATIM in the prompt. It does three things: (a) copy cover, (b) paint navy circle at r=540 to erase old illustration, (c) punch transparent hole at r=540 with 4x supersampling. That's it. NO frame_mask.png loading. NO color analysis. NO scrollwork gap detection.

3. **Update art sizing in `composite_single()`** medallion path (around line 781): Change `art_radius` from the `max(FALLBACK_RADIUS + ART_BLEED_PX, ART_TARGET_OUTER_RADIUS - ART_OUTER_INSET_PX)` computation to simply `art_radius = ART_CLIP_RADIUS` (600). Update art_diameter and paste offset accordingly.

4. **Remove `strict_window_mask` clipping** in medallion path if present — art is clipped only by the ART_CLIP_RADIUS circle.

## CRITICAL — Do not

- Do NOT add any color detection, HSV analysis, gold pixel classification, or "frame-metal" logic
- Do NOT load or use `frame_mask.png` in the fallback builder
- Do NOT bump `FRAME_OVERLAY_VERSION`
- Do NOT change any other files (no extract_frame_overlays.py, no Dockerfile, no scripts)
- Do NOT "improve" or adapt the provided code — copy it exactly as specified

## Visual verification

After implementing, run composites on Moby Dick and at least one other book. Open the JPEGs and visually verify: no rectangular edges, no old illustration bleed-through, gold frame intact all around, art fills opening, no white patches.

## End with

```bash
git add -A && git commit -m "PROMPT-19: Simple layer compositing — navy erase + transparent hole at r=540, art at r=600, frame on top" && git push
```
