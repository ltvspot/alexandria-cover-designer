# PROMPT-19: Fix Medallion Compositing — Exact Code Replacements

## What Went Wrong with PROMPT-18

Codex ignored the specified approach and instead:
1. **Did NOT add `FRAME_HOLE_RADIUS`, `ART_CLIP_RADIUS`, or `NAVY_FILL_RGB` constants** — none of these exist in the current code
2. **Did NOT rewrite `_build_fallback_frame_overlay()`** — it still loads `frame_mask.png` and does color-based "scrollwork gap" analysis (lines 1501–1545), which is exactly the broken approach we said to remove
3. **Invented `ART_TARGET_OUTER_RADIUS = 700` and `ART_OUTER_INSET_PX = 8`** — making the art circle r=692, far too large (extends into outer ornaments)
4. **Still uses `frame_mask.png`** — the broken smooth-circle mask that doesn't match the real frame
5. **Added a "frame-metal classifier" with gold/dark pixel detection** — complex color analysis that was explicitly forbidden
6. **Bumped `FRAME_OVERLAY_VERSION` to 6** — triggering re-extraction with the broken extraction logic

The result: art bleeds through as rectangles, old illustration shows through in gaps, frame ornaments are damaged or transparent in places.

## The Fix — EXACT Code to Write

This prompt contains the EXACT code. Do not interpret, adapt, or "improve" it. Copy it verbatim.

### Step 1: Add three constants after line 51 (`ART_BLEED_PX = 140`)

Delete these two lines that Codex added (lines 52-53):
```python
ART_TARGET_OUTER_RADIUS = 700
ART_OUTER_INSET_PX = 8
```

Replace them with:
```python
FRAME_HOLE_RADIUS = 540
ART_CLIP_RADIUS = 600
NAVY_FILL_RGB = (21, 32, 76)
```

### Step 2: Replace `_build_fallback_frame_overlay()` entirely

Find the function `_build_fallback_frame_overlay` (currently at line 1490). Delete the ENTIRE function body (from `def` through `return cover_rgba`). Replace it with this EXACT code:

```python
def _build_fallback_frame_overlay(
    *,
    cover: Image.Image,
    center_x: int,
    center_y: int,
    punch_radius: int,
) -> Image.Image:
    """Build RGBA frame overlay using simple layering.

    1. Copy the original cover
    2. Paint a navy circle at medallion center to erase old illustration
    3. Punch a transparent hole at FRAME_HOLE_RADIUS
    4. Return as RGBA — frame pixels opaque, medallion opening transparent

    The art layer (placed UNDERNEATH this overlay) extends to ART_CLIP_RADIUS (600).
    The frame hole is FRAME_HOLE_RADIUS (540). The 60px overlap is hidden by
    the opaque frame ring sitting on top.
    """
    w, h = cover.size
    cover_rgba = cover.convert("RGBA")

    # Step 1: Erase old illustration — paint solid navy over the entire
    # medallion area. This ensures NO original illustration pixels survive.
    erase_layer = cover_rgba.copy()
    erase_draw = ImageDraw.Draw(erase_layer)
    erase_r = FRAME_HOLE_RADIUS  # 540
    erase_draw.ellipse(
        (center_x - erase_r, center_y - erase_r,
         center_x + erase_r, center_y + erase_r),
        fill=(*NAVY_FILL_RGB, 255),
    )

    # Step 2: Punch transparent hole at FRAME_HOLE_RADIUS with 4x supersampling.
    scale = TEMPLATE_SUPERSAMPLE_FACTOR  # 4
    mask_large = Image.new("L", (w * scale, h * scale), 255)
    mask_draw = ImageDraw.Draw(mask_large)
    cx_s = center_x * scale
    cy_s = center_y * scale
    r_s = FRAME_HOLE_RADIUS * scale
    mask_draw.ellipse(
        (cx_s - r_s, cy_s - r_s, cx_s + r_s, cy_s + r_s),
        fill=0,
    )
    frame_alpha = mask_large.resize((w, h), Image.LANCZOS)

    # Step 3: Apply alpha — outside r=540 is opaque (frame), inside is transparent.
    erase_layer.putalpha(frame_alpha)
    return erase_layer
```

**Do NOT add any scrollwork gap detection, gold pixel classification, or frame_mask.png loading to this function.** The function must do exactly three things: copy cover, paint navy circle, punch transparent hole. Nothing else.

### Step 3: Update art sizing in `composite_single()`

Find the medallion path in `composite_single()` (the `else` branch starting around line 755). Find the art radius computation block. Currently it reads:

```python
        art_radius = max(
            int(FALLBACK_RADIUS + ART_BLEED_PX),
            int(ART_TARGET_OUTER_RADIUS - ART_OUTER_INSET_PX),
        )
        art_diameter = int(art_radius * 2)
```

Replace with:

```python
        art_radius = ART_CLIP_RADIUS  # 600
        art_diameter = art_radius * 2  # 1200
```

Then find the art paste line. Currently it reads:

```python
        art_layer.paste(art, (center_x - art_diameter // 2, center_y - art_diameter // 2))
```

Replace with:

```python
        art_layer.paste(art, (center_x - art_radius, center_y - art_radius))
```

Then find the clip radius line. Currently:

```python
        clip_radius = art_radius
```

This stays the same (art_radius is now 600).

### Step 4: Remove `strict_window_mask` clipping from medallion path

In the medallion compositing path, there may be a block that applies `strict_window_mask` (the global compositing mask) to the art clip. If it exists, REMOVE it for the medallion path. The art should be clipped ONLY by the circle at `ART_CLIP_RADIUS`. The strict_window_mask was part of the old approach and interferes with the new layering.

Look for something like:
```python
        if strict_window_mask is not None:
            clip_mask = _combine_masks(clip_mask, strict_window_mask)
```

If this line exists in the medallion path, DELETE it.

### Step 5: Do NOT touch these

- `_load_frame_overlay()` — leave it as-is (per-book overlays are a separate path)
- `_load_frame_mask()` — leave it as-is (other code paths may use it)
- `extract_frame_overlays.py` — leave it as-is
- Frame integrity guard (the ring check at r=660-800) — leave it as-is
- `_sample_cover_background()` — leave it as-is
- Any rectangle or custom_mask compositing paths — leave them as-is
- `FRAME_OVERLAY_VERSION` — leave at whatever value it is now (do NOT bump it)

## Why This Works

| Layer | Content | Radius | Purpose |
|-------|---------|--------|---------|
| Bottom | Canvas (solid navy fill) | Full cover | Background |
| Middle | New AI art | Clipped to r=600 circle | The illustration |
| Top | Frame overlay (cover with navy erase + transparent hole at r=540) | Opaque outside r=540 | Preserves ALL frame pixels, hides art edges |

- Frame hole r=540 > inner gold ring r≈480-520 → all old illustration erased
- Art r=600 > frame hole r=540 → no gaps, art extends 60px under frame
- Frame outer ornaments reach r≈730 → 130px of opaque frame covers art edge
- Guard ring checks r=660-800 → untouched, will pass

## Visual Verification — MANDATORY

After implementing, Codex MUST:

1. Run a composite on at least TWO books (e.g., Moby Dick and Room with a View)
2. Open the output JPEG files
3. Look at the medallion area with human eyes and verify:
   - **No rectangular edges** of art visible anywhere around the frame
   - **No old illustration** bleeding through (no faint images behind the frame ornaments)
   - **No white or light-colored patches** at the bottom, top, or sides of the medallion
   - **Gold ornamental frame is intact** — every scroll, flower, and leaf is crisp and undamaged
   - **Art fills the medallion opening** completely with no navy/dark gaps between art and frame
   - **No semi-transparent patches** in the frame ornaments

If ANY of these checks fail, the implementation is wrong. Do NOT commit broken output.

## Files to Modify

**ONLY ONE FILE: `src/cover_compositor.py`**

Changes:
1. Replace `ART_TARGET_OUTER_RADIUS` and `ART_OUTER_INSET_PX` with `FRAME_HOLE_RADIUS`, `ART_CLIP_RADIUS`, `NAVY_FILL_RGB`
2. Replace `_build_fallback_frame_overlay()` function body with the exact code above
3. Update art radius/diameter/paste in `composite_single()` medallion path
4. Remove `strict_window_mask` application in medallion path if present

No other files change. No new scripts. No Dockerfile changes.

## End with

```bash
git add -A && git commit -m "PROMPT-19: Simple layer compositing — navy erase + transparent hole at r=540, art at r=600, frame on top" && git push
```
