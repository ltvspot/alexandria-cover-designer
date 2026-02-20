# PROMPT-1A OUTPUT — Cover Analysis (Center Region Detection)

## Summary
Implemented `src/cover_analyzer.py` to detect and validate the circular center illustration region for all 99 input covers using a template-consensus approach (shared cover template). The script now generates:
- `config/cover_regions.json` with all cover regions and confidence scores
- `config/compositing_mask.png` (RGBA circular alpha mask)
- 5 debug overlays in `config/debug_overlays/`

## Files Modified / Created
- Modified: `src/cover_analyzer.py`
- Created/updated: `config/cover_regions.json`
- Created/updated: `config/compositing_mask.png`
- Created/updated: `config/debug_overlays/debug_overlay_001.png`
- Created/updated: `config/debug_overlays/debug_overlay_002.png`
- Created/updated: `config/debug_overlays/debug_overlay_003.png`
- Created/updated: `config/debug_overlays/debug_overlay_004.png`
- Created/updated: `config/debug_overlays/debug_overlay_005.png`

## Features Implemented
- `CoverRegion` dataclass with:
  - `center_x`, `center_y`, `radius`, `frame_bbox`, `confidence`
- `analyze_cover(jpg_path)`:
  - Loads a cover JPG
  - Applies template-based center medallion region
  - Computes confidence from image evidence:
    - gold ring/frame detection in HSV
    - navy-background consistency outside frame
    - interior texture variance
- `analyze_all_covers(input_dir)`:
  - Processes all 99 cover JPGs
  - Produces per-cover entries + outlier flags
  - Writes `config/cover_regions.json`
- `generate_compositing_mask(region, cover_size)`:
  - Produces circular RGBA alpha mask (white inside, transparent outside)
- `save_debug_overlays(...)`:
  - Writes visual overlays with detected circle and frame bbox on sample covers
- CLI runner (`python3 src/cover_analyzer.py`) that generates all Prompt 1A artifacts in one execution.

## Verification Checklist (All 14)
1. `py_compile` on `src/cover_analyzer.py` — **PASS**
2. `analyze_cover()` on cover #2 — **PASS** (valid `CoverRegion`)
3. `analyze_cover()` on cover #26 — **PASS** (valid `CoverRegion`)
4. `analyze_cover()` on cover #89 — **PASS** (valid `CoverRegion`)
5. #2/#26/#89 centers/radii within ±20px — **PASS**
6. `analyze_all_covers()` on all 99 covers — **PASS**
7. All 99 covers produce valid `CoverRegion` — **PASS**
8. No outliers (`confidence > 0.9` for all) — **PASS**
9. `config/cover_regions.json` has all 99 entries — **PASS**
10. Compositing mask is valid PNG with alpha — **PASS**
11. Mask circle radius matches detected region — **PASS**
12. Mask applied to cover #2 isolates illustration area — **PASS**
13. 5 debug overlay images saved — **PASS**
14. Overlays clearly show detected circle — **PASS**

## Notes
- Detected consensus region used for compositing:
  - `center_x=2864`, `center_y=1620`, `radius=500`
- One source JPG (`#9`) is `3781x2777` instead of `3784x2777`; analyzer handles this with right-edge anchoring while preserving the same template region behavior.
