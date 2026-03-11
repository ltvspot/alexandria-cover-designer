# PROMPT-20: Force Fallback Frame Overlay — Disable Broken Per-Book Overlays

## Root Cause — Why PROMPT-19 Had No Effect

PROMPT-19 correctly rewrote `_build_fallback_frame_overlay()`. But that function is NEVER CALLED on the live server. Here's why:

1. PROMPT-18 set `FRAME_OVERLAY_VERSION = 6`
2. On Railway startup, `ensure_frame_overlays_exist()` runs `extract_frame_overlays.py`
3. That script uses `_apply_scrollwork_gap_transparency()` — a color-based classifier that tries to detect "gold frame metal" vs "non-metal" pixels
4. This classifier incorrectly makes frame ornament pixels transparent → broken per-book `*_frame.png` overlays are generated and cached in `config/frame_overlays/`
5. When `composite_single()` runs, `_load_frame_overlay()` finds these broken cached overlays and returns them
6. `_build_fallback_frame_overlay()` (our correct code) is only called when `_load_frame_overlay()` returns `None`
7. Since the broken overlays exist, `_load_frame_overlay()` always returns the broken overlay → our fallback NEVER runs

**This is why nothing changed for the last 5 prompts** — the per-book overlays were being loaded every time, bypassing whatever we did to the fallback.

## The Fix — Two Changes

### Change 1: Make `_load_frame_overlay()` always return `None`

Find `_load_frame_overlay()` (around line 1452). Replace the ENTIRE function body with:

```python
def _load_frame_overlay(cover_path: Path, size: tuple[int, int]) -> Image.Image | None:
    """Per-book frame overlays are disabled.

    The extraction script's scrollwork gap classifier damages frame ornaments.
    All compositing now uses _build_fallback_frame_overlay() which uses the
    proven simple-layering approach (navy erase + transparent hole at r=540).
    """
    return None
```

### Change 2: Make `ensure_frame_overlays_exist()` a no-op

Find `ensure_frame_overlays_exist()` (around line 1536). Replace the ENTIRE function body with:

```python
def ensure_frame_overlays_exist(*, input_dir: Path, catalog_path: Path) -> None:
    """Per-book overlay extraction is disabled.

    The extraction script damages frame ornaments via incorrect color classification.
    All compositing now uses the fallback path (simple layering).
    """
    return
```

### That's it. Two functions → two stubs. Nothing else changes.

## What NOT to Change

- `_build_fallback_frame_overlay()` — this is CORRECT from PROMPT-19, do not touch it
- The constants `FRAME_HOLE_RADIUS`, `ART_CLIP_RADIUS`, `NAVY_FILL_RGB` — correct, do not touch
- The medallion path in `composite_single()` — correct, do not touch
- `extract_frame_overlays.py` — leave it, it's just not called anymore
- `FRAME_OVERLAY_VERSION` — leave it, doesn't matter since extraction is disabled
- Frame integrity guard — leave it
- Any other function — leave it

## Files to Modify

**ONLY ONE FILE: `src/cover_compositor.py`**

Two function replacements:
1. `_load_frame_overlay()` → return None
2. `ensure_frame_overlays_exist()` → return immediately

## End with

```bash
git add -A && git commit -m "PROMPT-20: Disable broken per-book overlays — force fallback path (navy erase + r=540 hole)" && git push
```
