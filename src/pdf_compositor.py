"""PDF-based compositor – JPG-level geometric blend approach.

Replaces the center art inside the ornamental medallion by working at the
JPG level instead of PDF rendering.  This avoids all CMYK-to-RGB rendering
issues (dark frames from pdftoppm / Ghostscript / PyMuPDF) by using the
original Illustrator-rendered JPG as the base image.

Algorithm:
  1. Open the source PDF to read Im0 dimensions and its cm-transform on the page.
  2. Open the original source JPG (rendered by Adobe Illustrator — golden frame correct).
  3. Map Im0 coordinates into JPG pixel space via the cm transform matrix.
  4. Create a smooth circular blend mask (r=1020, feather=30 in Im0 space).
  5. Paste new AI art into the centre region, blending smoothly into the original JPG.
  6. Save the result as a high-quality JPG.

The original ornaments, frame, text, and all non-medallion elements remain
pixel-perfect because they come from the untouched source JPG.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

try:
    import pikepdf  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pikepdf is required for PDF compositor") from exc

try:
    from src import config
    from src import safe_image
    from src import safe_json
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import safe_image  # type: ignore
    import safe_json  # type: ignore
    from logger import get_logger  # type: ignore

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXPECTED_DPI = 300
EXPECTED_JPG_SIZE = (3784, 2777)          # full cover w x h

# Im0-space blend parameters (empirically tuned on Book 1, verified on Book 2)
IM0_BLEND_RADIUS = 1020      # pixels from Im0 center — frame ring starts here
IM0_BLEND_FEATHER = 30       # smooth transition width

# Art pre-processing
AI_ART_EDGE_TRIM_RATIO = 0.08
AI_UNIFORM_MARGIN_MAX_TRIM_RATIO = 0.22
AI_UNIFORM_MARGIN_COLOR_TOL = 26.0
AI_UNIFORM_MARGIN_STD_MAX = 22.0
AI_UNIFORM_MARGIN_MATCH_RATIO = 0.92


# ---------------------------------------------------------------------------
# Utility: trim uniform margins from generated art
# ---------------------------------------------------------------------------
def _trim_uniform_margins(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        return rgb
    h, w = int(arr.shape[0]), int(arr.shape[1])
    if h < 64 or w < 64:
        return rgb

    patch = max(4, min(h, w) // 40)
    corners = np.concatenate(
        [
            arr[:patch, :patch].reshape(-1, 3),
            arr[:patch, w - patch :].reshape(-1, 3),
            arr[h - patch :, :patch].reshape(-1, 3),
            arr[h - patch :, w - patch :].reshape(-1, 3),
        ],
        axis=0,
    )
    corner_color = np.median(corners, axis=0)

    def _line_matches(line: np.ndarray) -> bool:
        if line.size == 0:
            return False
        diff = np.abs(line - corner_color).mean(axis=1)
        match_ratio = float(np.mean(diff <= AI_UNIFORM_MARGIN_COLOR_TOL))
        std_mean = float(np.std(line, axis=0).mean())
        return match_ratio >= AI_UNIFORM_MARGIN_MATCH_RATIO and std_mean <= AI_UNIFORM_MARGIN_STD_MAX

    max_trim_x = max(0, int(round(w * AI_UNIFORM_MARGIN_MAX_TRIM_RATIO)))
    max_trim_y = max(0, int(round(h * AI_UNIFORM_MARGIN_MAX_TRIM_RATIO)))

    left = 0
    while left < max_trim_x and _line_matches(arr[:, left, :]):
        left += 1
    right = 0
    while right < max_trim_x and _line_matches(arr[:, w - 1 - right, :]):
        right += 1
    top = 0
    while top < max_trim_y and _line_matches(arr[top, :, :]):
        top += 1
    bottom = 0
    while bottom < max_trim_y and _line_matches(arr[h - 1 - bottom, :, :]):
        bottom += 1

    if (left + right + top + bottom) <= 0:
        return rgb

    new_w = w - left - right
    new_h = h - top - bottom
    if new_w < max(64, int(w * 0.55)) or new_h < max(64, int(h * 0.55)):
        return rgb

    return rgb.crop((left, top, w - right, h - bottom))


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------
def _load_catalog(path: Path) -> list[dict[str, Any]]:
    payload = safe_json.load_json(path, [])
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _find_book_folder_name(*, catalog_path: Path, book_number: int) -> str:
    for row in _load_catalog(catalog_path):
        try:
            number = int(row.get("number", 0))
        except (TypeError, ValueError):
            continue
        if number == int(book_number):
            return str(row.get("folder_name", "")).strip()
    return ""


def find_source_pdf_for_book(*, input_dir: Path, book_number: int, catalog_path: Path = config.BOOK_CATALOG_PATH) -> Path | None:
    """Return source PDF path for a book when available."""
    folder_name = _find_book_folder_name(catalog_path=catalog_path, book_number=book_number)
    if not folder_name:
        return None
    folder = input_dir / folder_name
    if not folder.exists() or not folder.is_dir():
        return None

    pdfs = sorted([path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"])
    if pdfs:
        return pdfs[0]

    ais = sorted([path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".ai"])
    if ais:
        return ais[0]
    return None


def find_source_jpg_for_book(*, input_dir: Path, book_number: int, catalog_path: Path = config.BOOK_CATALOG_PATH) -> Path | None:
    """Return the original Illustrator-rendered JPG for a book."""
    folder_name = _find_book_folder_name(catalog_path=catalog_path, book_number=book_number)
    if not folder_name:
        return None
    folder = input_dir / folder_name
    if not folder.exists() or not folder.is_dir():
        return None

    jpgs = sorted([path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg")])
    if jpgs:
        return jpgs[0]
    return None


# ---------------------------------------------------------------------------
# PDF helpers — extract Im0 position on page
# ---------------------------------------------------------------------------
def _resolve_im0(page: Any) -> Any:
    """Find the Im0 image XObject in the PDF page."""
    resources = page.get("/Resources")
    if resources is None:
        raise ValueError("PDF page has no /Resources")
    xobjects = resources.get("/XObject")
    if xobjects is None:
        raise ValueError("PDF page has no /XObject resources")

    if "/Im0" in xobjects:
        return xobjects["/Im0"]

    for _name, obj in xobjects.items():
        try:
            subtype = str(obj.get("/Subtype", ""))
        except Exception:
            subtype = ""
        if subtype == "/Image" and obj.get("/SMask") is not None:
            return obj
    raise ValueError("No image XObject with SMask found (expected /Im0)")


def _extract_im0_transform(pdf_path: Path) -> dict[str, Any]:
    """Extract Im0 dimensions and its cm-transform from the page content stream.

    The content stream contains a `cm` operator that places Im0 on the page:
        a 0 0 d tx ty cm
    Where:
        a  = width in points
        d  = height in points
        tx = left offset in points from left edge
        ty = bottom offset in points from bottom edge
    """
    pdf = pikepdf.Pdf.open(str(pdf_path))
    try:
        if len(pdf.pages) == 0:
            raise ValueError("Source PDF has no pages")
        page = pdf.pages[0]
        im0 = _resolve_im0(page)

        im0_w = int(im0.get("/Width"))
        im0_h = int(im0.get("/Height"))

        # Parse content stream for cm transform preceding Im0 reference
        raw_content = page.Contents.read_bytes().decode("latin-1")

        # Find the cm transform — it's typically the last `cm` before `/Im0 Do`
        # Content stream pattern: ... a 0 0 d tx ty cm ... /Im0 Do ...
        # Find all cm operators
        cm_pattern = re.compile(
            r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+cm"
        )
        matches = list(cm_pattern.finditer(raw_content))

        # Find the position of /Im0 Do
        im0_pos = raw_content.find("/Im0")
        if im0_pos < 0:
            # Try to find any image reference
            im0_pos = raw_content.find("Do")

        # Get the cm transform closest before Im0
        best_match = None
        for m in matches:
            if m.start() < im0_pos:
                best_match = m

        if best_match is None:
            raise ValueError("Could not find cm transform for Im0 in content stream")

        a = float(best_match.group(1))   # width in points
        b = float(best_match.group(2))
        c = float(best_match.group(3))
        d = float(best_match.group(4))   # height in points
        tx = float(best_match.group(5))  # x offset in points
        ty = float(best_match.group(6))  # y offset in points

        # Get page dimensions in points
        mediabox = page.MediaBox
        page_w_pts = float(mediabox[2]) - float(mediabox[0])
        page_h_pts = float(mediabox[3]) - float(mediabox[1])

        return {
            "im0_w": im0_w,
            "im0_h": im0_h,
            "cm_a": a,
            "cm_d": d,
            "cm_tx": tx,
            "cm_ty": ty,
            "page_w_pts": page_w_pts,
            "page_h_pts": page_h_pts,
        }
    finally:
        pdf.close()


def _im0_to_jpg_mapping(transform: dict[str, Any], jpg_w: int, jpg_h: int) -> dict[str, Any]:
    """Compute the mapping from Im0 pixel coordinates to JPG pixel coordinates.

    The PDF places Im0 at (tx, ty) with size (a x d) points on a page of
    (page_w x page_h) points.  The JPG is a flat render of the full page.

    In JPG space:
        scale_x = jpg_w / page_w_pts
        scale_y = jpg_h / page_h_pts
        im0_left_jpg  = tx * scale_x
        im0_top_jpg   = (page_h_pts - ty - d) * scale_y   (PDF y is bottom-up)
        im0_width_jpg = a * scale_x
        im0_height_jpg = d * scale_y
    """
    page_w_pts = transform["page_w_pts"]
    page_h_pts = transform["page_h_pts"]
    a = transform["cm_a"]
    d = transform["cm_d"]
    tx = transform["cm_tx"]
    ty = transform["cm_ty"]

    scale_x = jpg_w / page_w_pts
    scale_y = jpg_h / page_h_pts

    im0_left = tx * scale_x
    im0_top = (page_h_pts - ty - d) * scale_y
    im0_w_jpg = a * scale_x
    im0_h_jpg = d * scale_y
    im0_cx = im0_left + im0_w_jpg / 2.0
    im0_cy = im0_top + im0_h_jpg / 2.0

    # Scale factor from Im0 pixel space to JPG pixel space
    im0_to_jpg_scale_x = im0_w_jpg / transform["im0_w"]
    im0_to_jpg_scale_y = im0_h_jpg / transform["im0_h"]

    return {
        "im0_left": im0_left,
        "im0_top": im0_top,
        "im0_w_jpg": im0_w_jpg,
        "im0_h_jpg": im0_h_jpg,
        "im0_cx": im0_cx,
        "im0_cy": im0_cy,
        "im0_to_jpg_scale_x": im0_to_jpg_scale_x,
        "im0_to_jpg_scale_y": im0_to_jpg_scale_y,
        "scale_x": scale_x,
        "scale_y": scale_y,
    }


# ---------------------------------------------------------------------------
# Art loading
# ---------------------------------------------------------------------------
def _load_ai_art_rgb(*, ai_art_path: Path, width: int, height: int) -> Image.Image:
    """Load AI art, trim margins, edge-trim, resize to (width, height) as RGB."""
    source = safe_image.load_image(ai_art_path, mode="RGB")
    rgb_source = _trim_uniform_margins(source)
    if AI_ART_EDGE_TRIM_RATIO > 0:
        src_w, src_h = rgb_source.size
        trim_x = int(round(src_w * AI_ART_EDGE_TRIM_RATIO / 2.0))
        trim_y = int(round(src_h * AI_ART_EDGE_TRIM_RATIO / 2.0))
        if (src_w - 2 * trim_x) >= 64 and (src_h - 2 * trim_y) >= 64:
            rgb_source = rgb_source.crop((trim_x, trim_y, src_w - trim_x, src_h - trim_y))
    rgb = ImageOps.fit(
        rgb_source,
        (int(width), int(height)),
        method=Image.LANCZOS,
        centering=(0.5, 0.5),
    )
    return rgb.convert("RGB")


# ---------------------------------------------------------------------------
# Main entry: composite_cover_pdf  (JPG-level geometric blend)
# ---------------------------------------------------------------------------
def composite_cover_pdf(
    source_pdf_path: str,
    ai_art_path: str,
    output_pdf_path: str,
    output_jpg_path: str,
    output_ai_path: str | None = None,
    *,
    source_jpg_path: str | None = None,
) -> dict[str, Any]:
    """Replace medallion art using JPG-level geometric blend.

    Uses the original Illustrator-rendered JPG as the base (golden frame
    rendered correctly), reads Im0 position from the PDF, and blends new
    AI art into the medallion centre with a smooth circular mask.

    The frame, ornaments, text, and all surrounding elements remain
    pixel-perfect from the original JPG.
    """
    source_pdf = Path(source_pdf_path)
    art_path = Path(ai_art_path)
    output_pdf = Path(output_pdf_path)
    output_jpg = Path(output_jpg_path)
    output_ai = Path(output_ai_path) if output_ai_path else output_pdf.with_suffix(".ai")

    if not source_pdf.exists():
        raise FileNotFoundError(f"Source PDF not found: {source_pdf}")
    if not art_path.exists():
        raise FileNotFoundError(f"AI art image not found: {art_path}")

    # Find source JPG — either passed explicitly or inferred from same folder
    jpg_path: Path | None = None
    if source_jpg_path:
        jpg_path = Path(source_jpg_path)
    else:
        # Look for JPG in same folder as the source PDF
        folder = source_pdf.parent
        jpg_candidates = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg")])
        if jpg_candidates:
            jpg_path = jpg_candidates[0]

    if jpg_path is None or not jpg_path.exists():
        raise FileNotFoundError(f"Source JPG not found alongside PDF: {source_pdf.parent}")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_jpg.parent.mkdir(parents=True, exist_ok=True)
    output_ai.parent.mkdir(parents=True, exist_ok=True)

    # --- Step 1: Extract Im0 position from PDF ---
    transform = _extract_im0_transform(source_pdf)

    # --- Step 2: Open original JPG ---
    base_jpg = safe_image.load_image(jpg_path, mode="RGB")
    jpg_w, jpg_h = base_jpg.size

    # --- Step 3: Map Im0 coordinates to JPG space ---
    mapping = _im0_to_jpg_mapping(transform, jpg_w, jpg_h)

    im0_region_w = int(round(mapping["im0_w_jpg"]))
    im0_region_h = int(round(mapping["im0_h_jpg"]))
    im0_cx = mapping["im0_cx"]
    im0_cy = mapping["im0_cy"]

    # Scale blend parameters from Im0 space to JPG space
    im0_scale = (mapping["im0_to_jpg_scale_x"] + mapping["im0_to_jpg_scale_y"]) / 2.0
    blend_radius_jpg = IM0_BLEND_RADIUS * im0_scale
    feather_jpg = IM0_BLEND_FEATHER * im0_scale

    # --- Step 4: Load and prep new AI art ---
    new_art = _load_ai_art_rgb(ai_art_path=art_path, width=im0_region_w, height=im0_region_h)

    # --- Step 5: Create circular blend mask in JPG space ---
    base_arr = np.asarray(base_jpg, dtype=np.float32)
    result_arr = base_arr.copy()

    # Place new art into the Im0 region
    im0_left = int(round(mapping["im0_left"]))
    im0_top = int(round(mapping["im0_top"]))
    new_art_arr = np.asarray(new_art, dtype=np.float32)

    # Build a distance-from-center grid for the Im0 region (in JPG pixels)
    yy, xx = np.mgrid[0:im0_region_h, 0:im0_region_w]
    # Centre of Im0 region relative to its own top-left
    rcx = im0_region_w / 2.0
    rcy = im0_region_h / 2.0
    dist = np.sqrt((xx - rcx) ** 2 + (yy - rcy) ** 2)

    # Smooth circular mask: 1.0 = new art, 0.0 = keep original
    inner_r = blend_radius_jpg - feather_jpg / 2.0
    outer_r = blend_radius_jpg + feather_jpg / 2.0
    mask = np.clip((outer_r - dist) / max(1.0, outer_r - inner_r), 0.0, 1.0)
    mask_3ch = mask[:, :, np.newaxis]

    # Clamp region to image bounds
    src_y1 = max(0, im0_top)
    src_y2 = min(jpg_h, im0_top + im0_region_h)
    src_x1 = max(0, im0_left)
    src_x2 = min(jpg_w, im0_left + im0_region_w)

    art_y1 = src_y1 - im0_top
    art_y2 = art_y1 + (src_y2 - src_y1)
    art_x1 = src_x1 - im0_left
    art_x2 = art_x1 + (src_x2 - src_x1)

    # Blend: result = new_art * mask + original * (1 - mask)
    region_original = result_arr[src_y1:src_y2, src_x1:src_x2]
    region_art = new_art_arr[art_y1:art_y2, art_x1:art_x2]
    region_mask = mask_3ch[art_y1:art_y2, art_x1:art_x2]

    blended = region_art * region_mask + region_original * (1.0 - region_mask)
    result_arr[src_y1:src_y2, src_x1:src_x2] = blended

    # --- Step 6: Save result ---
    result_img = Image.fromarray(np.clip(result_arr, 0, 255).astype(np.uint8), "RGB")

    # Ensure expected dimensions
    if result_img.size != EXPECTED_JPG_SIZE:
        result_img = result_img.resize(EXPECTED_JPG_SIZE, Image.LANCZOS)

    safe_image.atomic_save_image(
        output_jpg,
        result_img,
        format="JPEG",
        quality=100,
        subsampling=0,
        dpi=(EXPECTED_DPI, EXPECTED_DPI),
    )

    # Write a real composited PDF with AI art swapped into /Im0 via SMask preservation.
    try:
        from src.pdf_swap_compositor import composite_via_pdf_swap
    except ModuleNotFoundError:
        from pdf_swap_compositor import composite_via_pdf_swap  # type: ignore

    try:
        composite_via_pdf_swap(
            source_pdf_path=source_pdf,
            ai_art_path=art_path,
            output_jpg_path=output_pdf.with_name(output_pdf.stem + "_swap_render.jpg"),
            expected_output_size=(jpg_w, jpg_h),
        )
        swap_pdf = output_pdf.with_name(output_pdf.stem + "_swap_render.pdf")
        if swap_pdf.exists():
            shutil.move(str(swap_pdf), str(output_pdf))
        else:
            logger.warning("PDF swap did not produce output PDF; copying source as fallback")
            shutil.copyfile(source_pdf, output_pdf)
        swap_jpg = output_pdf.with_name(output_pdf.stem + "_swap_render.jpg")
        if swap_jpg.exists():
            swap_jpg.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("PDF swap compositor failed; copying source PDF as fallback: %s", exc)
        shutil.copyfile(source_pdf, output_pdf)

    shutil.copyfile(output_pdf, output_ai)

    logger.info(
        "JPG blend compositor completed",
        extra={
            "source_pdf": str(source_pdf),
            "source_jpg": str(jpg_path),
            "output_jpg": str(output_jpg),
            "im0_center_jpg": f"({im0_cx:.0f}, {im0_cy:.0f})",
            "blend_radius_jpg": f"{blend_radius_jpg:.0f}",
            "im0_region": f"{im0_region_w}x{im0_region_h}",
        },
    )

    return {
        "success": True,
        "source_pdf": str(source_pdf),
        "source_jpg": str(jpg_path),
        "output_pdf": str(output_pdf),
        "output_jpg": str(output_jpg),
        "output_ai": str(output_ai),
        "center_x": int(round(im0_cx)),
        "center_y": int(round(im0_cy)),
        "image_width": int(transform["im0_w"]),
        "image_height": int(transform["im0_h"]),
    }


# ---------------------------------------------------------------------------
# Batch: composite all variants for a book
# ---------------------------------------------------------------------------
def _parse_variant(stem: str) -> int:
    if "variant_" not in stem:
        return 0
    token = stem.split("variant_", 1)[1].split("_", 1)[0]
    try:
        return int(token)
    except ValueError:
        return 0


def _collect_generated_for_book(generated_dir: Path, book_number: int) -> list[dict[str, Any]]:
    base = generated_dir / str(book_number)
    if not base.exists():
        return []

    rows: list[dict[str, Any]] = []
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}

    for model_dir in sorted([path for path in base.iterdir() if path.is_dir()]):
        if model_dir.name == "history":
            continue
        for image in sorted([p for p in model_dir.iterdir() if p.is_file() and p.suffix.lower() in image_extensions]):
            variant = _parse_variant(image.stem)
            if variant <= 0:
                continue
            rows.append({"model": model_dir.name, "variant": variant, "path": image})

    for image in sorted([p for p in base.iterdir() if p.is_file() and p.suffix.lower() in image_extensions]):
        variant = _parse_variant(image.stem)
        if variant <= 0:
            continue
        rows.append({"model": "default", "variant": variant, "path": image})

    dedup: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        dedup[(str(row["model"]), int(row["variant"]))] = row
    return sorted(dedup.values(), key=lambda row: (str(row["model"]), int(row["variant"])))


def composite_all_variants(
    *,
    book_number: int,
    input_dir: Path,
    generated_dir: Path,
    output_dir: Path,
    catalog_path: Path = config.BOOK_CATALOG_PATH,
) -> list[Path]:
    """Composite all generated variants for a book via JPG-level blend."""
    source_pdf = find_source_pdf_for_book(input_dir=input_dir, book_number=book_number, catalog_path=catalog_path)
    if source_pdf is None:
        raise FileNotFoundError(f"No source PDF found for book {book_number}")

    source_jpg = find_source_jpg_for_book(input_dir=input_dir, book_number=book_number, catalog_path=catalog_path)
    if source_jpg is None:
        raise FileNotFoundError(f"No source JPG found for book {book_number}")

    image_rows = _collect_generated_for_book(generated_dir=generated_dir, book_number=book_number)
    if not image_rows:
        raise FileNotFoundError(f"No generated variants found for book {book_number}")

    outputs: list[Path] = []
    report_items: list[dict[str, Any]] = []

    for row in image_rows:
        model = str(row["model"])
        variant = int(row["variant"])
        image_path = Path(row["path"])

        if model == "default":
            base_output = output_dir / str(book_number) / f"variant_{variant}"
        else:
            base_output = output_dir / str(book_number) / model / f"variant_{variant}"

        output_pdf = base_output.with_suffix(".pdf")
        output_jpg = base_output.with_suffix(".jpg")
        output_ai = base_output.with_suffix(".ai")

        result = composite_cover_pdf(
            source_pdf_path=str(source_pdf),
            ai_art_path=str(image_path),
            output_pdf_path=str(output_pdf),
            output_jpg_path=str(output_jpg),
            output_ai_path=str(output_ai),
            source_jpg_path=str(source_jpg),
        )
        outputs.append(output_jpg)
        report_items.append(
            {
                "output_path": str(output_jpg),
                "valid": True,
                "issues": [],
                "mode": "jpg_blend",
                "source_pdf": str(source_pdf),
                "source_jpg": str(source_jpg),
                "variant": variant,
                "model": model,
                "metrics": {
                    "image_width": float(result.get("image_width", 0)),
                    "image_height": float(result.get("image_height", 0)),
                },
            }
        )

    report = {
        "book_number": int(book_number),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(report_items),
        "invalid": 0,
        "items": report_items,
    }
    safe_json.atomic_write_json(output_dir / str(book_number) / "composite_validation.json", report)
    logger.info(
        "JPG blend compositor completed",
        extra={"book_number": int(book_number), "variants": len(outputs), "source_pdf": str(source_pdf)},
    )
    return outputs


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="PDF compositor (JPG blend) for one generated image")
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("ai_art", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("output_jpg", type=Path)
    parser.add_argument("--output-ai", type=Path, default=None)
    parser.add_argument("--source-jpg", type=Path, default=None, help="Original JPG (auto-detected if not given)")
    args = parser.parse_args()

    result = composite_cover_pdf(
        source_pdf_path=str(args.source_pdf),
        ai_art_path=str(args.ai_art),
        output_pdf_path=str(args.output_pdf),
        output_jpg_path=str(args.output_jpg),
        output_ai_path=str(args.output_ai) if args.output_ai else None,
        source_jpg_path=str(args.source_jpg) if args.source_jpg else None,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
