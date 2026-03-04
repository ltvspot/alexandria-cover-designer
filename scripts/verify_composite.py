#!/usr/bin/env python3
"""
Visual Regression Test for Alexandria Cover Designer Compositing.

Supports two modes:
1. PDF MODE (preferred): Uses the source PDF's SMask to verify frame preservation
2. JPG MODE (fallback): Compares composite JPG against source cover JPG

Usage:
    # PDF mode (preferred - exact SMask-based verification):
    python scripts/verify_composite.py <composited.jpg> --source-pdf <source.pdf>

    # JPG mode (fallback - radial zone comparison):
    python scripts/verify_composite.py <composited.jpg> <source_cover.jpg>

    # Strict mode (tighter thresholds):
    python scripts/verify_composite.py <composited.jpg> --source-pdf <source.pdf> --strict

    # JSON output:
    python scripts/verify_composite.py <composited.jpg> --source-pdf <source.pdf> --json

Exit codes:
    0 = ALL CHECKS PASSED
    1 = ONE OR MORE CHECKS FAILED
    2 = ERROR (missing files, wrong dimensions, etc.)

This script MUST be run after every compositor change before committing.
Both Claude Cowork and Codex are required to run this and report results.
"""

import argparse
import io
import json
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

# -- Known Geometry (page-level, for JPG mode) --
CENTER_X = 2864
CENTER_Y = 1620
OUTER_FRAME_RADIUS = 500
PDF_ORNAMENT_SAFE_RADIUS = 520
SMASK_FRAME_MIN = 5
SMASK_FRAME_MAX = 250

# -- Test Zone Radii (for JPG mode) --
ORNAMENT_ZONE_MIN = 480
ART_ZONE_MAX = 370

# -- Thresholds (normal mode) --
ORNAMENT_MATCH_THRESHOLD = 0.995
ART_DIFFER_THRESHOLD = 0.90
CHANNEL_DIFF_TOLERANCE = 2
CENTERING_TOLERANCE_PX = 5
TRANSITION_HARSH_THRESHOLD = 0.02

# -- Strict thresholds --
STRICT_ORNAMENT_MATCH = 0.999
STRICT_ART_DIFFER = 0.95
STRICT_CENTERING_PX = 3


def load_image_array(path: Path) -> np.ndarray:
    """Load image as RGB numpy array."""
    img = Image.open(path).convert("RGB")
    return np.array(img, dtype=np.uint8)


def normalize_render_shape(render: np.ndarray, target_shape: tuple[int, int, int] | tuple[int, int]) -> np.ndarray:
    """Resize rendered image to match target HxW when PDF renderer rounding differs."""
    target_h = int(target_shape[0])
    target_w = int(target_shape[1])
    if render.shape[0] == target_h and render.shape[1] == target_w:
        return render
    resized = Image.fromarray(render, mode="RGB").resize((target_w, target_h), Image.LANCZOS)
    return np.array(resized, dtype=np.uint8)


def normalize_reference_jpeg(reference: np.ndarray) -> np.ndarray:
    """Match comparison baseline to output JPG compression characteristics."""
    buffer = io.BytesIO()
    Image.fromarray(reference, mode="RGB").save(
        buffer,
        format="JPEG",
        quality=100,
        subsampling=0,
        dpi=(300, 300),
    )
    buffer.seek(0)
    with Image.open(buffer) as image:
        return np.array(image.convert("RGB"), dtype=np.uint8)


def make_radial_mask(shape, center_x, center_y, radius):
    """Create a boolean mask for pixels within radius of center."""
    h, w = shape[:2]
    yy, xx = np.ogrid[:h, :w]
    dist_sq = (xx - center_x).astype(np.float64) ** 2 + (yy - center_y).astype(np.float64) ** 2
    return dist_sq <= radius**2


# =================================================================
# PDF MODE - SMask-based verification (preferred)
# =================================================================

def extract_pdf_smask_and_image(pdf_path: Path):
    """Extract SMask and original CMYK image from source PDF."""
    import pikepdf

    pdf = pikepdf.Pdf.open(str(pdf_path))
    page = pdf.pages[0]
    xobjects = page.get("/Resources").get("/XObject")
    im0 = xobjects["/Im0"]

    w = int(im0.get("/Width"))
    h = int(im0.get("/Height"))
    raw = zlib.decompress(bytes(im0.read_raw_bytes()))
    cmyk = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)

    smask_obj = im0.get("/SMask")
    smask_raw = zlib.decompress(bytes(smask_obj.read_raw_bytes()))
    smask = np.frombuffer(smask_raw, dtype=np.uint8).reshape(h, w)

    pdf.close()
    return cmyk, smask, w, h


def check_ornament_zone_pdf(
    composite_jpg: np.ndarray,
    source_pdf_path: Path,
    threshold: float,
    output_pdf_path: Path | None = None,
) -> dict:
    """
    PDF-mode ornament check.
    Render the SOURCE PDF to JPG, then confirm that pixels in the
    ornament zone (SMask 5-250) are identical between source render
    and composite output.
    """
    if output_pdf_path and Path(output_pdf_path).exists():
        cmyk_src, smask, _, _ = extract_pdf_smask_and_image(source_pdf_path)

        import pikepdf

        pdf = pikepdf.Pdf.open(str(output_pdf_path))
        page = pdf.pages[0]
        xobjects = page.get("/Resources").get("/XObject")
        im0 = xobjects["/Im0"]
        w = int(im0.get("/Width"))
        h = int(im0.get("/Height"))
        raw = zlib.decompress(bytes(im0.read_raw_bytes()))
        cmyk_out = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
        pdf.close()

        preserve_mask = smask <= SMASK_FRAME_MAX
        total = int(np.sum(preserve_mask))
        if total == 0:
            return {"pass": False, "error": "No non-opaque ornament pixels found in SMask"}

        matching = int(np.sum(np.all(cmyk_src[preserve_mask] == cmyk_out[preserve_mask], axis=1)))
        ratio = matching / total
        passed = ratio >= threshold
        return {
            "pass": passed,
            "match_ratio": round(ratio, 6),
            "threshold": threshold,
            "total_pixels": total,
            "matching_pixels": matching,
            "mismatched_pixels": total - matching,
            "message": (
                f"PASS: {ratio:.2%} ornament/non-opaque CMYK pixels match source"
                if passed
                else f"FAIL: {ratio:.2%} ornament/non-opaque pixels match (need {threshold:.1%}). "
                f"{total - matching:,} pixels differ."
            ),
        }

    import fitz

    doc = fitz.open(str(source_pdf_path))
    page = doc[0]
    mat = fitz.Matrix(300 / 72, 300 / 72)
    pix = page.get_pixmap(matrix=mat)
    source_render = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:  # RGBA
        source_render = source_render[:, :, :3]
    doc.close()
    source_render = normalize_render_shape(source_render, composite_jpg.shape)
    source_render = normalize_reference_jpeg(source_render)

    ornament_mask = ~make_radial_mask(composite_jpg.shape, CENTER_X, CENTER_Y, PDF_ORNAMENT_SAFE_RADIUS)
    h = min(composite_jpg.shape[0], source_render.shape[0])
    w = min(composite_jpg.shape[1], source_render.shape[1])
    comp = composite_jpg[:h, :w]
    src = source_render[:h, :w]
    om = ornament_mask[:h, :w]

    total = int(np.sum(om))
    if total == 0:
        return {"pass": False, "error": "No ornament zone pixels found"}
    diff = np.max(np.abs(comp.astype(np.int16) - src.astype(np.int16)), axis=2)
    matching = int(np.sum(diff[om] <= CHANNEL_DIFF_TOLERANCE))
    ratio = matching / total
    passed = ratio >= threshold
    return {
        "pass": passed,
        "match_ratio": round(ratio, 6),
        "threshold": threshold,
        "total_pixels": total,
        "matching_pixels": matching,
        "mismatched_pixels": total - matching,
        "message": (
            f"PASS: {ratio:.2%} ornament pixels match source PDF render"
            if passed
            else f"FAIL: {ratio:.2%} ornament pixels match (need {threshold:.1%}). "
            f"{total - matching:,} pixels differ."
        ),
    }


def check_art_zone_pdf(composite_jpg: np.ndarray, source_pdf_path: Path, threshold: float) -> dict:
    """
    PDF-mode art check.
    Pixels in the art zone (r < 370 from center) must DIFFER from the
    source PDF render - meaning AI art has replaced the original illustration.
    """
    import fitz

    doc = fitz.open(str(source_pdf_path))
    page = doc[0]
    mat = fitz.Matrix(300 / 72, 300 / 72)
    pix = page.get_pixmap(matrix=mat)
    source_render = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        source_render = source_render[:, :, :3]
    doc.close()
    source_render = normalize_render_shape(source_render, composite_jpg.shape)
    source_render = normalize_reference_jpeg(source_render)

    art_mask = make_radial_mask(composite_jpg.shape, CENTER_X, CENTER_Y, ART_ZONE_MAX)

    h = min(composite_jpg.shape[0], source_render.shape[0])
    w = min(composite_jpg.shape[1], source_render.shape[1])
    comp = composite_jpg[:h, :w]
    src = source_render[:h, :w]
    am = art_mask[:h, :w]

    total = int(np.sum(am))
    if total == 0:
        return {"pass": False, "error": "No art zone pixels found"}

    diff = np.max(np.abs(comp.astype(np.int16) - src.astype(np.int16)), axis=2)
    different = int(np.sum(diff[am] > CHANNEL_DIFF_TOLERANCE))
    ratio = different / total

    passed = ratio >= threshold
    return {
        "pass": passed,
        "differ_ratio": round(ratio, 6),
        "threshold": threshold,
        "total_pixels": total,
        "different_pixels": different,
        "same_pixels": total - different,
        "message": (
            f"PASS: {ratio:.2%} art zone pixels differ from source (AI art present)"
            if passed
            else f"FAIL: {ratio:.2%} art zone pixels differ (need {threshold:.0%}). "
            f"Original illustration may still be visible."
        ),
    }


def check_smask_integrity(source_pdf_path: Path, output_pdf_path: Path) -> dict:
    """
    NEW CHECK - Verify SMask in the output PDF is bit-identical to source.
    This is the most critical check: the SMask defines the frame boundary
    and must NEVER be modified.
    """
    _, smask_src, _, _ = extract_pdf_smask_and_image(source_pdf_path)

    import pikepdf

    pdf = pikepdf.Pdf.open(str(output_pdf_path))
    page = pdf.pages[0]
    xobjects = page.get("/Resources").get("/XObject")
    im0 = xobjects["/Im0"]
    smask_obj = im0.get("/SMask")
    w = int(smask_obj.get("/Width"))
    h = int(smask_obj.get("/Height"))
    smask_out_raw = zlib.decompress(bytes(smask_obj.read_raw_bytes()))
    smask_out = np.frombuffer(smask_out_raw, dtype=np.uint8).reshape(h, w)
    pdf.close()

    identical = np.array_equal(smask_src, smask_out)
    if not identical:
        diff_count = int(np.sum(smask_src != smask_out))
        total = smask_src.size
    else:
        diff_count = 0
        total = smask_src.size

    return {
        "pass": identical,
        "total_pixels": total,
        "differing_pixels": diff_count,
        "message": (
            f"PASS: SMask is bit-identical between source and output ({total:,} pixels)"
            if identical
            else f"FAIL: SMask was modified! {diff_count:,} of {total:,} pixels differ. "
            f"The SMask must NEVER be changed."
        ),
    }


def check_frame_pixels_preserved(source_pdf_path: Path, output_pdf_path: Path) -> dict:
    """
    NEW CHECK - At the raster image level, verify that pixels in the frame
    ring (SMask 5-250) are identical between source and output Im0 data.
    This confirms the compositor kept original frame pixels.
    """
    cmyk_src, smask, _, _ = extract_pdf_smask_and_image(source_pdf_path)

    import pikepdf

    pdf = pikepdf.Pdf.open(str(output_pdf_path))
    page = pdf.pages[0]
    xobjects = page.get("/Resources").get("/XObject")
    im0 = xobjects["/Im0"]
    w = int(im0.get("/Width"))
    h = int(im0.get("/Height"))
    raw = zlib.decompress(bytes(im0.read_raw_bytes()))
    cmyk_out = np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)
    pdf.close()

    frame_mask = (smask >= 5) & (smask <= 250)
    total = int(np.sum(frame_mask))
    if total == 0:
        return {"pass": False, "error": "No frame ring pixels found in SMask"}

    # Frame pixels must be byte-identical (no JPEG tolerance - this is raw CMYK)
    matching = int(np.sum(np.all(cmyk_src[frame_mask] == cmyk_out[frame_mask], axis=1)))
    ratio = matching / total

    passed = ratio >= 0.9999  # Essentially 100% - allow 1-2 pixels for edge cases
    return {
        "pass": passed,
        "match_ratio": round(ratio, 6),
        "total_frame_pixels": total,
        "matching_pixels": matching,
        "differing_pixels": total - matching,
        "message": (
            f"PASS: {ratio:.4%} of frame ring pixels ({total:,}) preserved from source"
            if passed
            else f"FAIL: {ratio:.4%} of frame ring pixels match. "
            f"{total - matching:,} frame pixels were corrupted."
        ),
    }


# =================================================================
# JPG MODE - Radial zone comparison (fallback)
# =================================================================

def check_ornament_zone_jpg(composite, source, threshold):
    """JPG-mode: Check ornament zone pixels match source."""
    ornament_mask = ~make_radial_mask(composite.shape, CENTER_X, CENTER_Y, ORNAMENT_ZONE_MIN)
    frame_outer = make_radial_mask(composite.shape, CENTER_X, CENTER_Y, OUTER_FRAME_RADIUS + 50)
    full_cover = ~make_radial_mask(composite.shape, CENTER_X, CENTER_Y, OUTER_FRAME_RADIUS + 50)
    check_mask = (ornament_mask & frame_outer) | full_cover

    total = int(np.sum(check_mask))
    if total == 0:
        return {"pass": False, "error": "No ornament zone pixels found"}

    diff = np.max(np.abs(composite.astype(np.int16) - source.astype(np.int16)), axis=2)
    matching = int(np.sum(diff[check_mask] <= CHANNEL_DIFF_TOLERANCE))
    ratio = matching / total

    passed = ratio >= threshold
    return {
        "pass": passed,
        "match_ratio": round(ratio, 6),
        "threshold": threshold,
        "total_pixels": total,
        "matching_pixels": matching,
        "mismatched_pixels": total - matching,
        "message": (
            f"PASS: {ratio:.2%} ornament pixels match source"
            if passed
            else f"FAIL: {ratio:.2%} match (need {threshold:.1%}). {total - matching:,} differ."
        ),
    }


def check_art_zone_jpg(composite, source, threshold):
    """JPG-mode: Check art zone pixels differ from source."""
    art_mask = make_radial_mask(composite.shape, CENTER_X, CENTER_Y, ART_ZONE_MAX)
    total = int(np.sum(art_mask))
    if total == 0:
        return {"pass": False, "error": "No art zone pixels found"}

    diff = np.max(np.abs(composite.astype(np.int16) - source.astype(np.int16)), axis=2)
    different = int(np.sum(diff[art_mask] > CHANNEL_DIFF_TOLERANCE))
    ratio = different / total

    passed = ratio >= threshold
    return {
        "pass": passed,
        "differ_ratio": round(ratio, 6),
        "threshold": threshold,
        "total_pixels": total,
        "different_pixels": different,
        "same_pixels": total - different,
        "message": (
            f"PASS: {ratio:.2%} art zone pixels differ (AI art present)"
            if passed
            else f"FAIL: {ratio:.2%} differ (need {threshold:.0%}). Original art may show."
        ),
    }


# =================================================================
# COMMON CHECKS (both modes)
# =================================================================

def check_dimensions(composite, expected_w=3784, expected_h=2777):
    h, w = composite.shape[:2]
    passed = (w == expected_w) and (h == expected_h)
    return {
        "pass": passed,
        "actual_size": f"{w}x{h}",
        "expected_size": f"{expected_w}x{expected_h}",
        "message": (
            f"PASS: Dimensions {w}x{h} match expected"
            if passed
            else f"FAIL: Dimensions {w}x{h}, expected {expected_w}x{expected_h}"
        ),
    }


def check_centering(composite, source):
    """Check AI art is centered at medallion center."""
    diff = np.max(np.abs(composite.astype(np.int16) - source.astype(np.int16)), axis=2)
    art_pixels = diff > 20
    medallion_mask = make_radial_mask(composite.shape, CENTER_X, CENTER_Y, OUTER_FRAME_RADIUS)
    art_in_medallion = art_pixels & medallion_mask

    if not np.any(art_in_medallion):
        return {"pass": False, "error": "No art detected in medallion area"}

    ys, xs = np.where(art_in_medallion)
    cx, cy = float(np.mean(xs)), float(np.mean(ys))
    offset = ((cx - CENTER_X) ** 2 + (cy - CENTER_Y) ** 2) ** 0.5

    passed = offset <= CENTERING_TOLERANCE_PX
    return {
        "pass": passed,
        "art_center_x": round(cx, 1),
        "art_center_y": round(cy, 1),
        "offset_total": round(offset, 1),
        "tolerance": CENTERING_TOLERANCE_PX,
        "message": (
            f"PASS: Art centered at ({cx:.0f},{cy:.0f}), offset {offset:.1f}px"
            if passed
            else f"FAIL: Art at ({cx:.0f},{cy:.0f}), offset {offset:.1f}px > {CENTERING_TOLERANCE_PX}px"
        ),
    }


def check_transition_zone(composite):
    """Check transition zone for harsh artifacts."""
    inner = make_radial_mask(composite.shape, CENTER_X, CENTER_Y, ART_ZONE_MAX)
    outer = make_radial_mask(composite.shape, CENTER_X, CENTER_Y, ORNAMENT_ZONE_MIN)
    transition = outer & ~inner

    total = int(np.sum(transition))
    if total == 0:
        return {"pass": False, "error": "No transition zone pixels"}

    gray = np.mean(composite.astype(np.float32), axis=2)
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    gradient = np.sqrt(gx**2 + gy**2)

    harsh = int(np.sum(gradient[transition] > 100))
    ratio = harsh / total

    passed = ratio < TRANSITION_HARSH_THRESHOLD
    return {
        "pass": passed,
        "harsh_ratio": round(ratio, 6),
        "total_pixels": total,
        "message": (
            f"PASS: Transition zone clean ({ratio:.2%} harsh pixels)"
            if passed
            else f"FAIL: Transition artifacts ({ratio:.2%} harsh pixels)"
        ),
    }


# =================================================================
# MAIN ORCHESTRATOR
# =================================================================

def verify_composite(composite_path, source_jpg_path=None, source_pdf_path=None, output_pdf_path=None, strict=False):
    """Run all verification checks. Auto-selects PDF or JPG mode."""

    if strict:
        global ORNAMENT_MATCH_THRESHOLD, ART_DIFFER_THRESHOLD, CENTERING_TOLERANCE_PX
        ORNAMENT_MATCH_THRESHOLD = STRICT_ORNAMENT_MATCH
        ART_DIFFER_THRESHOLD = STRICT_ART_DIFFER
        CENTERING_TOLERANCE_PX = STRICT_CENTERING_PX

    mode = "PDF" if source_pdf_path else "JPG"
    print(f"\n{'=' * 70}")
    print(f"COMPOSITE VERIFICATION [{mode} MODE]{'  (STRICT)' if strict else ''}")
    print(f"  Composite: {composite_path}")
    if source_pdf_path:
        print(f"  Source PDF: {source_pdf_path}")
    if source_jpg_path:
        print(f"  Source JPG: {source_jpg_path}")
    if output_pdf_path:
        print(f"  Output PDF: {output_pdf_path}")
    print(f"{'=' * 70}\n")

    composite = load_image_array(composite_path)
    checks = {}

    # 1. Dimensions
    checks["dimensions"] = check_dimensions(composite)

    if mode == "PDF":
        # PDF-mode checks
        checks["ornament_zone"] = check_ornament_zone_pdf(
            composite,
            source_pdf_path,
            ORNAMENT_MATCH_THRESHOLD,
            output_pdf_path=output_pdf_path,
        )
        checks["art_zone"] = check_art_zone_pdf(composite, source_pdf_path, ART_DIFFER_THRESHOLD)

        # Render source PDF for centering check
        import fitz

        doc = fitz.open(str(source_pdf_path))
        page = doc[0]
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat)
        src_render = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        if pix.n == 4:
            src_render = src_render[:, :, :3]
        doc.close()
        src_render = normalize_render_shape(src_render, composite.shape)
        src_render = normalize_reference_jpeg(src_render)
        h = min(composite.shape[0], src_render.shape[0])
        w = min(composite.shape[1], src_render.shape[1])
        checks["centering"] = check_centering(composite[:h, :w], src_render[:h, :w])

        # SMask integrity (if output PDF provided)
        if output_pdf_path and Path(output_pdf_path).exists():
            checks["smask_integrity"] = check_smask_integrity(source_pdf_path, output_pdf_path)
            checks["frame_pixels"] = check_frame_pixels_preserved(source_pdf_path, output_pdf_path)
    else:
        # JPG-mode checks
        source = load_image_array(source_jpg_path)
        checks["ornament_zone"] = check_ornament_zone_jpg(composite, source, ORNAMENT_MATCH_THRESHOLD)
        checks["art_zone"] = check_art_zone_jpg(composite, source, ART_DIFFER_THRESHOLD)
        checks["centering"] = check_centering(composite, source)

    # Transition quality (both modes)
    checks["transition_quality"] = check_transition_zone(composite)

    # Print results
    all_passed = all(c["pass"] for c in checks.values())
    for name, result in checks.items():
        icon = "+" if result["pass"] else "X"
        print(f"  [{icon}] {name}: {result.get('message', '')}")

    print(f"\n{'=' * 70}")
    if all_passed:
        print("  RESULT: ALL CHECKS PASSED - safe to commit")
    else:
        failed = [k for k, v in checks.items() if not v["pass"]]
        print(f"  RESULT: FAILED ({len(failed)} check(s): {', '.join(failed)})")
        print("  DO NOT COMMIT. Fix issues and re-run.")
    print(f"{'=' * 70}\n")

    return {"overall_pass": all_passed, "mode": mode, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description="Verify composited cover output (PDF or JPG mode).")
    parser.add_argument("composite", type=Path, help="Path to composited output JPG")
    parser.add_argument("source_jpg", type=Path, nargs="?", default=None, help="Path to source cover JPG (JPG mode)")
    parser.add_argument("--source-pdf", type=Path, default=None, help="Path to source cover PDF (enables PDF mode)")
    parser.add_argument("--output-pdf", type=Path, default=None, help="Path to output PDF (for SMask integrity check)")
    parser.add_argument("--strict", action="store_true", help="Stricter thresholds")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    if not args.composite.exists():
        print(f"ERROR: Composite not found: {args.composite}", file=sys.stderr)
        sys.exit(2)

    if args.source_pdf and not args.source_pdf.exists():
        print(f"ERROR: Source PDF not found: {args.source_pdf}", file=sys.stderr)
        sys.exit(2)

    if not args.source_pdf and args.source_jpg and not args.source_jpg.exists():
        print(f"ERROR: Source JPG not found: {args.source_jpg}", file=sys.stderr)
        sys.exit(2)

    if not args.source_pdf and not args.source_jpg:
        print("ERROR: Must provide either --source-pdf or a source JPG path", file=sys.stderr)
        sys.exit(2)

    result = verify_composite(
        args.composite,
        source_jpg_path=args.source_jpg,
        source_pdf_path=args.source_pdf,
        output_pdf_path=args.output_pdf,
        strict=args.strict,
    )

    if args.json:

        def sanitize(obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return obj

        clean = json.loads(json.dumps(result, default=sanitize))
        print(json.dumps(clean, indent=2))

    sys.exit(0 if result["overall_pass"] else 1)


if __name__ == "__main__":
    main()
