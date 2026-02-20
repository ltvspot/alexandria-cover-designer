# Prompt 3A — Cover Composition (Illustration Compositing)

**Priority**: HIGH — Core visual output
**Scope**: `src/cover_compositor.py`
**Depends on**: Prompt 1A (cover region) + Prompt 2A (generated images)
**Estimated time**: 45-60 minutes

---

## Context

Read `PROJECT-STATE.md`. We now have:
- The exact circular region coordinates from Prompt 1A (`config/cover_regions.json`)
- 495 generated illustrations from Prompt 2A (`tmp/generated/`)
- The original 99 input covers (`Input Covers/`)

We need to composite each new illustration into its corresponding cover, replacing the center image while keeping everything else pixel-perfect identical.

---

## Task

Create `src/cover_compositor.py` that:

1. **Loads the original cover JPG** (3784×2777, 300 DPI)
2. **Loads the generated illustration** (1024×1024 PNG)
3. **Resizes the illustration** to match the detected circle diameter
4. **Applies a circular mask** with feathered edges for smooth blending
5. **Composites** the illustration into the exact center of the ornamental frame
6. **Color-matches** the illustration to the cover's color temperature (optional but recommended)
7. **Saves** the result as a new JPG at 3784×2777, 300 DPI

### Critical Requirements

- **Everything outside the center circle must be PIXEL-PERFECT identical to the original**
- The ornamental gold frame must NOT be affected
- The feathered edge should blend smoothly with the frame's inner border
- The illustration should "sit inside" the frame naturally, not look pasted on

### Code Structure

```python
# src/cover_compositor.py

from pathlib import Path
import numpy as np

def composite_single(
    cover_path: Path,
    illustration_path: Path,
    region: dict,
    output_path: Path,
    feather_px: int = 15
) -> Path:
    """Composite a single illustration into a cover."""
    ...

def composite_all_variants(
    book_number: int,
    input_dir: Path,
    generated_dir: Path,
    output_dir: Path,
    regions: dict
) -> list[Path]:
    """Composite all 5 variants for a single book."""
    ...

def batch_composite(
    input_dir: Path,
    generated_dir: Path,
    output_dir: Path,
    regions_path: Path
) -> dict:
    """Composite all books, all variants."""
    ...
```

---

## Verification Checklist

### Pixel Accuracy
1. `py_compile` passes — PASS/FAIL
2. Composite variant 1 of Moby Dick → output JPG saved — PASS/FAIL
3. Output is 3784×2777 at 300 DPI — PASS/FAIL
4. Compare a back-cover pixel (x=200, y=200) between original and composite → identical RGB values — PASS/FAIL
5. Compare a title text pixel → identical — PASS/FAIL
6. Compare an ornament pixel outside the circle → identical — PASS/FAIL

### Visual Quality
7. Center illustration properly fills the circular region — PASS/FAIL
8. No visible seam at circle edge — PASS/FAIL
9. Feathered edge blends smoothly with frame border — PASS/FAIL
10. Color temperature looks natural within the cover — PASS/FAIL

### Batch
11. All 5 variants for Moby Dick composited successfully — PASS/FAIL
12. All 5 variants are visually distinct from each other — PASS/FAIL
13. Batch composite for 5 test books completes without error — PASS/FAIL
