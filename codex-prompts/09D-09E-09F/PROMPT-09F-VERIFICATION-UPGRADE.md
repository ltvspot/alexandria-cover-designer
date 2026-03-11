# PROMPT-09F — Verification Protocol Upgrade

## Overview

The Alexandria Cover Designer verification script (`scripts/verify_composite.py`) currently runs 7 checks in PDF mode and 5 checks in JPG mode. This prompt upgrades the protocol by adding two new checks:

- **Check 8 — AI Art Border Detection**: Examines the AI-generated art image *before* compositing to detect whether it contains circular border or frame elements that would visually conflict with the original gold ornamental frame.
- **Check 9 — Visual Frame Comparison**: After compositing, renders both source and output PDFs to JPG and compares the frame zone at the pixel level — catching corruption that CMYK-data-level checks miss.

These fixes close a known blind spot: the current suite passes even when AI art contains its own decorative border that visually overwrites the original gold filigree, because the data-level check (Check 2) only confirms that the original CMYK pixel values are technically present — not that they are visually dominant.

---

## Root Cause

### Why Current Checks Miss Visual Frame Corruption

**Check 2 (Ornament zone)** works at the CMYK PDF data layer. It samples the frame ring pixels directly from the PDF's `Im0` image stream and compares them to the source PDF. Because the compositing process preserves the original CMYK data in the frame region (SMask values 5–250), Check 2 reports a match at 99.9%+.

However, the PDF's SMask values in the frame zone are *semi-transparent* — they are not fully opaque (255). When the AI art is placed behind the frame layer, any decorative border in the AI art image bleeds through the semi-transparent SMask zone and is rendered visually on top of the original gold ornaments. The CMYK data for the original ornaments is still present in the stream, but it is visually overridden by the AI art content underneath.

The verification never checks whether the AI art image *itself* carries border or frame elements in the region that corresponds to the ornamental ring. This gap allows AI-generated images with their own circular borders (e.g., vignettes, brushstroke rings, stylised frames) to pass all 7 checks while corrupting the cover's visual output.

**The two new checks address this at complementary levels:**

1. Check 8 catches the problem *proactively*, before compositing, by inspecting the AI art image directly.
2. Check 9 catches it *retroactively*, after compositing, by comparing rendered (human-visible) output to rendered source.

---

## Changes Required

### 1. `scripts/verify_composite.py` — Add Check 8 and Check 9

#### Geometry Constants (add near top of file, after existing constants)

```python
# --- Geometry constants ---
# JPG-space (rendered at 300 DPI, output size 3784x2777)
JPG_CENTER_X = 2864
JPG_CENTER_Y = 1620
JPG_FRAME_RADIUS = 480          # pixels; frame zone = r > this value

# Embedded AI art image space (2480x2470 native resolution)
AI_ART_CENTER_X = 1240
AI_ART_CENTER_Y = 1235
AI_ART_FRAME_INNER_R = 420      # inner edge of frame annular sample ring
AI_ART_FRAME_OUTER_R = 480      # outer edge of frame annular sample ring

# Check 8 thresholds
AI_BORDER_EDGE_DENSITY_THRESHOLD = 0.08   # fraction of frame-zone pixels with strong edges
AI_BORDER_SOBEL_MAGNITUDE_THRESHOLD = 30  # Sobel magnitude (0-255) to count as an edge pixel

# Check 9 thresholds
VISUAL_FRAME_MEAN_DIFF_THRESHOLD = 5.0    # mean absolute difference (0-255 scale)
RENDER_DPI = 300
```

---

#### Check 8: AI Art Border Detection

**Purpose:** Load the AI-generated art image before compositing. Sample a thin annular ring at the expected ornamental frame zone. Use a Sobel edge filter to measure structural detail (edge density) in that ring. If edge density exceeds the threshold, the AI art contains its own decorative border that will visually conflict with the original gold frame.

**When it runs:** PDF mode only. Requires `--ai-art` flag. Skipped if `--ai-art` is not provided (degraded mode — a warning is printed but the overall result is not failed).

**Add the following function** after the existing helper functions and before `run_checks()`:

```python
def check_ai_art_border(ai_art_path: str) -> tuple[bool, str]:
    """
    Check 8 — AI Art Border Detection.

    Examines the AI art image in the annular ring that corresponds to the
    ornamental frame zone (r=420–480 from center at 1240,1235 in 2480x2470 space).
    Uses a Sobel edge filter to detect whether the AI art contains its own
    decorative border elements in this zone.

    Returns (passed: bool, message: str).
    """
    import cv2
    import numpy as np

    img = cv2.imread(ai_art_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return False, f"Check 8 FAIL: could not load AI art image: {ai_art_path}"

    h, w = img.shape

    # Build coordinate grids
    ys, xs = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xs - AI_ART_CENTER_X) ** 2 + (ys - AI_ART_CENTER_Y) ** 2)

    # Annular mask for the frame zone
    ring_mask = (dist >= AI_ART_FRAME_INNER_R) & (dist <= AI_ART_FRAME_OUTER_R)

    if ring_mask.sum() == 0:
        return False, "Check 8 FAIL: frame ring mask is empty — image may be wrong size"

    # Compute Sobel magnitude over the entire image, then sample in the ring
    sobel_x = cv2.Sobel(img, cv2.CV_64F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(img, cv2.CV_64F, 0, 1, ksize=3)
    sobel_mag = np.sqrt(sobel_x ** 2 + sobel_y ** 2)
    sobel_mag_8u = np.clip(sobel_mag, 0, 255).astype(np.uint8)

    ring_pixels = sobel_mag_8u[ring_mask]
    strong_edge_pixels = (ring_pixels >= AI_BORDER_SOBEL_MAGNITUDE_THRESHOLD).sum()
    edge_density = strong_edge_pixels / ring_mask.sum()

    if edge_density > AI_BORDER_EDGE_DENSITY_THRESHOLD:
        return False, (
            f"Check 8 FAIL: AI art contains decorative border in frame zone. "
            f"Edge density = {edge_density:.4f} (threshold {AI_BORDER_EDGE_DENSITY_THRESHOLD}). "
            f"The AI art has structural detail at r=420–480 that will visually overwrite the gold ornaments."
        )

    return True, (
        f"Check 8 PASS: AI art frame zone is clean. "
        f"Edge density = {edge_density:.4f} (threshold {AI_BORDER_EDGE_DENSITY_THRESHOLD})."
    )
```

**Wire Check 8 into `run_checks()`** — add after Check 7:

```python
# --- BEFORE (end of run_checks, PDF mode) ---
results.append(check_frame_pixels(source_pdf, output_pdf))   # Check 7

return results

# --- AFTER ---
results.append(check_frame_pixels(source_pdf, output_pdf))   # Check 7

# Check 8 — AI Art Border Detection (requires --ai-art flag)
if args.ai_art:
    results.append(check_ai_art_border(args.ai_art))
else:
    print("  [Check 8] SKIPPED — no --ai-art path provided (pass --ai-art <path> to enable)")

return results
```

---

#### Check 9: Visual Frame Comparison (rendered JPG level)

**Purpose:** Render both the source PDF and the output PDF to RGB at 300 DPI using PyMuPDF (`fitz`). Create a mask of the frame zone (all pixels where distance from center (2864, 1620) > 480 in the 3784×2777 rendered space). Compute the mean absolute pixel difference in the masked zone. If the mean diff exceeds 5.0 (on a 0–255 scale), the frame has been visually altered and the check fails.

**This is the decisive check** — it operates at the rendered (human-visible) level, not the CMYK data level, and will catch frame corruption that Check 2 misses.

**Add the following function:**

```python
def check_visual_frame(source_pdf: str, output_pdf: str) -> tuple[bool, str]:
    """
    Check 9 — Visual Frame Comparison (rendered JPG level).

    Renders source and output PDFs to RGB at 300 DPI using PyMuPDF.
    Compares the frame zone (r > 480 from center 2864,1620) pixel-by-pixel.
    Mean absolute difference < 5.0 = PASS.

    Returns (passed: bool, message: str).
    """
    import fitz  # PyMuPDF
    import numpy as np

    def render_pdf_page(pdf_path: str, dpi: int = RENDER_DPI) -> np.ndarray:
        doc = fitz.open(pdf_path)
        page = doc.load_page(0)
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        doc.close()
        return arr

    src_rgb = render_pdf_page(source_pdf)
    out_rgb = render_pdf_page(output_pdf)

    # Verify rendered dimensions match expected
    expected_h, expected_w = 2777, 3784
    for label, arr in [("source", src_rgb), ("output", out_rgb)]:
        if arr.shape[:2] != (expected_h, expected_w):
            return False, (
                f"Check 9 FAIL: {label} PDF rendered to {arr.shape[1]}x{arr.shape[0]}, "
                f"expected {expected_w}x{expected_h}. DPI or page size mismatch."
            )

    # Build frame zone mask: all pixels at r > JPG_FRAME_RADIUS from center
    ys, xs = np.mgrid[0:expected_h, 0:expected_w]
    dist = np.sqrt((xs - JPG_CENTER_X) ** 2 + (ys - JPG_CENTER_Y) ** 2)
    frame_mask = dist > JPG_FRAME_RADIUS   # shape (H, W), bool

    # Compute mean absolute difference in frame zone across all three channels
    diff = np.abs(src_rgb.astype(np.float32) - out_rgb.astype(np.float32))  # (H, W, 3)
    frame_diff = diff[frame_mask]   # shape (N*3,) after flatten, or index per channel

    # Mean over all frame-zone pixels and all channels
    mean_diff = frame_diff.mean()

    if mean_diff > VISUAL_FRAME_MEAN_DIFF_THRESHOLD:
        return False, (
            f"Check 9 FAIL: rendered frame zone differs from source. "
            f"Mean absolute diff = {mean_diff:.3f} (threshold {VISUAL_FRAME_MEAN_DIFF_THRESHOLD}). "
            f"The composited output has visual changes in the ornamental frame zone."
        )

    return True, (
        f"Check 9 PASS: rendered frame zone matches source. "
        f"Mean absolute diff = {mean_diff:.3f} (threshold {VISUAL_FRAME_MEAN_DIFF_THRESHOLD})."
    )
```

**Wire Check 9 into `run_checks()`** — add after Check 8:

```python
# Check 9 — Visual Frame Comparison (rendered JPG level)
results.append(check_visual_frame(source_pdf, output_pdf))

return results
```

---

### 2. CLI Changes — Add `--ai-art` Flag

**File:** `scripts/verify_composite.py`

Locate the `argparse` setup block (near the bottom of the file) and add the new optional argument:

```python
# --- BEFORE ---
parser.add_argument("output_jpg",  help="Path to the composited output JPG")
parser.add_argument("source_pdf",  help="Path to the source/original PDF")
parser.add_argument("output_pdf",  help="Path to the composited output PDF")

# --- AFTER ---
parser.add_argument("output_jpg",  help="Path to the composited output JPG")
parser.add_argument("source_pdf",  help="Path to the source/original PDF")
parser.add_argument("output_pdf",  help="Path to the composited output PDF")
parser.add_argument(
    "--ai-art",
    dest="ai_art",
    default=None,
    metavar="PATH",
    help=(
        "Path to the AI-generated art image before compositing (PNG or JPG). "
        "When provided, enables Check 8 (AI Art Border Detection). "
        "Omitting this flag skips Check 8 with a warning."
    ),
)
```

Make sure `args = parser.parse_args()` is called after all `add_argument` calls, then pass `args` through to `run_checks(args)` (or thread `args.ai_art` explicitly — whichever pattern the existing code uses).

---

### 3. Update the Integration Test Script

**File:** `scripts/test_compositor_integration.sh`

Find the line that invokes `verify_composite.py` and add the `--ai-art` flag pointing to the AI art path used in the integration test. The exact variable name will depend on what the test script already defines, but it will look like:

```bash
# --- BEFORE ---
python scripts/verify_composite.py \
    "$OUTPUT_JPG" \
    "$SOURCE_PDF" \
    "$OUTPUT_PDF"

# --- AFTER ---
python scripts/verify_composite.py \
    "$OUTPUT_JPG" \
    "$SOURCE_PDF" \
    "$OUTPUT_PDF" \
    --ai-art "$AI_ART_PATH"
```

Where `$AI_ART_PATH` should be set earlier in the script to point to the PNG/JPG generated by the AI art step before compositing. If the integration test does not currently retain this intermediate file, update the compositing step to write it to a known path (e.g., `output/ai_art_pre_composite.png`) before invoking the compositor.

---

## Updated Check Summary Table

| #  | Check                    | Mode         | What it verifies                                                    |
|----|--------------------------|--------------|---------------------------------------------------------------------|
| 1  | Dimensions               | PDF + JPG    | Output JPG is exactly 3784×2777                                     |
| 2  | Ornament zone            | PDF          | Frame CMYK pixels match source PDF at data level                    |
| 3  | Art zone                 | PDF          | Inner circle pixels differ from source (art was replaced)           |
| 4  | Centering                | PDF + JPG    | Art center is at (2864, 1620) in output                             |
| 5  | Transition quality       | PDF + JPG    | No harsh gradients across the art/frame boundary                    |
| 6  | SMask integrity          | PDF          | SMask stream is bit-identical to source PDF                         |
| 7  | Frame pixels             | PDF          | Im0 frame ring CMYK values are preserved from source                |
| 8  | AI Art Border *(new)*    | PDF          | AI art has no decorative border in frame zone (r=420–480, center 1240,1235); requires `--ai-art` |
| 9  | Visual Frame *(new)*     | PDF          | Rendered frame zone (r>480, center 2864,1620) matches source visually at ≤5.0 mean diff |

**PDF mode total: 9 checks (8 active when `--ai-art` omitted, 9 when provided)**
**JPG mode total: 5 checks (unchanged)**

---

## Testing

### Unit-level: test Check 8 in isolation

Create two synthetic test images in `tests/fixtures/`:

- `ai_art_clean.png` — a 2480×2470 image with no content at r=420–480 (pure gradient or solid color in that zone). Check 8 should **PASS**.
- `ai_art_bordered.png` — a 2480×2470 image with a visible circular ring/stroke at r≈450 from center. Check 8 should **FAIL**.

Run:

```bash
python -c "
from scripts.verify_composite import check_ai_art_border
print(check_ai_art_border('tests/fixtures/ai_art_clean.png'))
print(check_ai_art_border('tests/fixtures/ai_art_bordered.png'))
"
```

Expected output:
```
(True,  'Check 8 PASS: AI art frame zone is clean. Edge density = 0.0012 (threshold 0.08).')
(False, 'Check 8 FAIL: AI art contains decorative border in frame zone. Edge density = 0.1437 ...')
```

### Unit-level: test Check 9 in isolation

```bash
python -c "
from scripts.verify_composite import check_visual_frame
# Should PASS — comparing source to itself
print(check_visual_frame('tests/fixtures/source.pdf', 'tests/fixtures/source.pdf'))
# Should FAIL — comparing source to a corrupted composite
print(check_visual_frame('tests/fixtures/source.pdf', 'tests/fixtures/corrupted_frame.pdf'))
"
```

### Integration-level: full verification run with new checks

```bash
python scripts/verify_composite.py \
    output/cover_composite.jpg \
    assets/alexandria_source.pdf \
    output/cover_composite.pdf \
    --ai-art output/ai_art_pre_composite.png
```

All 9 checks should print `PASS`. If Check 8 or Check 9 fails, inspect:

- **Check 8 failure**: The AI art generation prompt needs to explicitly instruct the model not to include borders, frames, vignettes, or circular decorative elements. Re-generate the art.
- **Check 9 failure**: The compositing step is altering the rendered appearance of the frame zone. Inspect the SMask application and blending mode in `scripts/compositor.py`.

### Regression: verify existing passing cases still pass

Run the full integration test suite:

```bash
bash scripts/test_compositor_integration.sh
```

All checks 1–9 must pass on known-good fixtures. If Check 9 is unexpectedly sensitive (false positives due to JPEG compression rounding), lower `RENDER_DPI` to 150 first to diagnose, or tighten the frame zone radius exclusion by increasing `JPG_FRAME_RADIUS` slightly (e.g., to 490).

---

## Dependency Notes

- **Check 8** requires `opencv-python` (`cv2`). This should already be present in the project's Python environment. If not: `pip install opencv-python`.
- **Check 9** requires `PyMuPDF` (`fitz`). If not already installed: `pip install pymupdf`. Confirm the installed version supports `page.get_pixmap()` with the `colorspace` argument (any version ≥ 1.18.0 does).

---

## MANDATORY: Run Verification Before Committing

After implementing all changes, run the full verification suite against real output before committing:

```bash
bash scripts/test_compositor_integration.sh
```

All 9 checks must pass. Do not commit if any check fails.

---

## Final Step

```bash
git add -A && git commit -m "PROMPT-09F: Verification upgrade — border detection + visual frame comparison" && git push
```
