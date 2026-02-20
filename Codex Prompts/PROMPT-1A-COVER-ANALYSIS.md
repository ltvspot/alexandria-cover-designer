# Prompt 1A — Cover Analysis (Center Region Detection)

**Priority**: HIGH — Foundation for all compositing
**Scope**: `src/cover_analyzer.py`, `config/cover_regions.json`
**Depends on**: Nothing (first prompt)
**Estimated time**: 30-45 minutes

---

## Context

Read `PROJECT-STATE.md` in the repository root for full technical context before starting.

We have 99 book covers (3784×2777 JPGs at 300 DPI). Each has the same template layout: navy background, gold ornamental corners, and a **circular medallion illustration** on the front cover (right side of the image). We need to precisely detect where that center illustration circle is located so we can replace it.

---

## Task

Create `src/cover_analyzer.py` that analyzes input cover JPGs and extracts:

1. **The center illustration bounding box** — the circular region containing the AI-generated art
2. **The ornamental frame mask** — the gold baroque frame surrounding the circle
3. **A compositing mask** — a clean alpha mask showing exactly where the new illustration should go

### Analysis Approach

Since all 99 covers use the **same template**, the center illustration is in a consistent position. The approach should be:

1. **Template-based detection** (primary):
   - Load 3-5 sample covers
   - The front cover is the RIGHT half of the image (roughly x > 1892)
   - The circular illustration is centered within the ornamental frame on the front cover
   - Detect the gold ornamental frame by color (gold/bronze hues on navy background)
   - The illustration circle is INSIDE the frame — find its exact center and radius
   - Store the region as (center_x, center_y, radius) in pixels

2. **Validation across all covers**:
   - Run the detected region against all 99 covers
   - Verify the ornamental frame pixels match in every cover (they should be identical)
   - Flag any covers where the region doesn't match (for manual review)

3. **Output artifacts**:
   - `config/cover_regions.json`: Region coordinates for compositing
   - A circular alpha mask PNG for the compositing step
   - Debug overlay images showing detected region on 5 sample covers

### Code Structure

```python
# src/cover_analyzer.py

from dataclasses import dataclass
from pathlib import Path

@dataclass
class CoverRegion:
    """Detected center illustration region."""
    center_x: int       # Pixel X of circle center
    center_y: int       # Pixel Y of circle center
    radius: int         # Radius of the illustration circle
    frame_bbox: tuple   # (x1, y1, x2, y2) of the ornamental frame bounding box
    confidence: float   # Detection confidence 0-1

def analyze_cover(jpg_path: Path) -> CoverRegion:
    """Analyze a single cover JPG and return the center illustration region."""
    ...

def analyze_all_covers(input_dir: Path) -> dict:
    """Analyze all covers and return a consensus region + per-cover validation."""
    ...

def generate_compositing_mask(region: CoverRegion, cover_size: tuple) -> 'np.ndarray':
    """Generate a circular alpha mask for compositing."""
    ...

def save_debug_overlays(input_dir: Path, region: CoverRegion, output_dir: Path, count: int = 5):
    """Save debug images showing the detected region overlaid on sample covers."""
    ...
```

---

## Verification Checklist

Run ALL of these checks. Report PASS/FAIL for each.

### Detection
1. `python3 -c "import py_compile; py_compile.compile('src/cover_analyzer.py', doraise=True)"` — PASS/FAIL
2. Run `analyze_cover()` on cover #2 (Moby Dick) — returns valid CoverRegion — PASS/FAIL
3. Run `analyze_cover()` on cover #26 (Alice in Wonderland) — returns valid CoverRegion — PASS/FAIL
4. Run `analyze_cover()` on cover #89 (Christmas Carol) — returns valid CoverRegion — PASS/FAIL
5. All three detected regions have center_x, center_y, radius within ±20px of each other — PASS/FAIL (confirms template consistency)

### Validation
6. Run `analyze_all_covers()` on all 99 input covers — PASS/FAIL
7. All 99 covers produce valid CoverRegion — PASS/FAIL
8. No cover flagged as outlier (confidence > 0.9 for all) — PASS/FAIL
9. `config/cover_regions.json` written with all 99 entries — PASS/FAIL

### Mask
10. Compositing mask is a valid PNG with alpha channel — PASS/FAIL
11. Mask circle radius matches detected region — PASS/FAIL
12. Mask applied to cover #2 correctly isolates the illustration area — PASS/FAIL

### Debug
13. 5 debug overlay images saved — PASS/FAIL
14. Each overlay clearly shows the detected circle on the cover — PASS/FAIL

---

## Notes

- The ornamental frame has a complex shape (baroque scrollwork), but the ILLUSTRATION inside is roughly circular
- There may be a slight feathered edge where illustration meets frame — detect the clean inner circle
- All covers use the same template, so the position should be nearly identical across all 99
- Use OpenCV for detection (Hough circles, color-based segmentation, or template matching)
- Consider that the gold ornament color is approximately HSV(30-45, 150-255, 150-255)
