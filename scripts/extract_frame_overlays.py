#!/usr/bin/env python3
"""Extract per-cover RGBA frame overlays from source PDFs (SMask) with JPG fallback."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pikepdf
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src import config
    from src import safe_json
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import safe_json  # type: ignore


logger = logging.getLogger("extract_frame_overlays")

DEFAULT_SX = 325.984
DEFAULT_SY = 324.670
DEFAULT_TX = 524.410
DEFAULT_TY = 110.511
CENTER_X = 2864
CENTER_Y = 1620
CM_DO_PATTERN = re.compile(
    rb"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    rb"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    rb"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    rb"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    rb"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+"
    rb"([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s+cm\s*/Im0\s+Do",
    re.S,
)

VALID_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(slots=True)
class OverlayStats:
    total: int = 0
    pdf_extracted: int = 0
    fallback: int = 0
    skipped: int = 0
    failed: int = 0


def _apply_scrollwork_gap_transparency(
    *,
    cover_rgb: np.ndarray,
    alpha: np.ndarray,
    center_x: int,
    center_y: int,
    ring_inner: int = 465,
    ring_outer: int = 700,
) -> tuple[np.ndarray, int, int]:
    """Keep frame metal opaque; make non-metal scrollwork gaps transparent."""
    target_h, target_w = cover_rgb.shape[:2]
    cx, cy = int(center_x), int(center_y)
    if cx >= target_w or cy >= target_h:
        cx, cy = target_w // 2, target_h // 2

    yy, xx = np.ogrid[:target_h, :target_w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    ring_mask = (dist >= float(ring_inner)) & (dist <= float(ring_outer)) & (alpha >= 250)

    r_ch = cover_rgb[:, :, 0].astype(np.float32)
    g_ch = cover_rgb[:, :, 1].astype(np.float32)
    b_ch = cover_rgb[:, :, 2].astype(np.float32)
    brightness = np.maximum(r_ch, np.maximum(g_ch, b_ch))
    shadow = np.minimum(r_ch, np.minimum(g_ch, b_ch))
    saturation = brightness - shadow

    # Keep only likely frame metal in the ring; aggressively drop old medallion art.
    is_gold = (
        ring_mask
        & (r_ch >= 120.0)
        & (g_ch >= 85.0)
        & (b_ch <= 145.0)
        & ((r_ch - g_ch) >= -4.0)
        & ((r_ch - b_ch) >= 14.0)
        & (saturation >= 22.0)
    )
    is_dark_frame = ring_mask & (brightness <= 40.0)
    is_frame_metal = is_gold | is_dark_frame
    is_non_metal = ring_mask & ~is_frame_metal

    updated = alpha.copy()
    gap_count = int(np.sum(is_non_metal))
    ring_count = int(np.sum(ring_mask))
    if gap_count > 0:
        updated[is_non_metal] = 0
    return updated, gap_count, ring_count


def _iter_dir_files(folder: Path) -> Iterable[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted([p for p in folder.iterdir() if p.is_file()])


def _first_image_file(folder: Path) -> Path | None:
    for path in _iter_dir_files(folder):
        if path.suffix.lower() in VALID_IMAGE_SUFFIXES:
            return path
    return None


def _first_pdf_file(folder: Path) -> Path | None:
    for path in _iter_dir_files(folder):
        if path.suffix.lower() == ".pdf":
            return path
    return None


def _read_page_contents(page: pikepdf.Page) -> bytes:
    contents = page.obj.get("/Contents")
    if contents is None:
        return b""
    if isinstance(contents, pikepdf.Array):
        chunks: list[bytes] = []
        for stream in contents:
            try:
                chunks.append(bytes(stream.read_bytes()))
            except Exception:
                continue
        return b"\n".join(chunks)
    try:
        return bytes(contents.read_bytes())
    except Exception:
        return b""


def _parse_page_size_points(page: pikepdf.Page) -> tuple[float, float]:
    mediabox = page.obj.get("/MediaBox")
    if mediabox is not None and len(mediabox) >= 4:
        x0 = float(mediabox[0])
        y0 = float(mediabox[1])
        x1 = float(mediabox[2])
        y1 = float(mediabox[3])
        return max(1.0, x1 - x0), max(1.0, y1 - y0)
    return 907.0, 666.0


def _parse_im0_cm_matrix(page: pikepdf.Page) -> tuple[float, float, float, float]:
    content = _read_page_contents(page)
    if not content:
        return DEFAULT_SX, DEFAULT_SY, DEFAULT_TX, DEFAULT_TY

    matches = list(CM_DO_PATTERN.finditer(content))
    if not matches:
        return DEFAULT_SX, DEFAULT_SY, DEFAULT_TX, DEFAULT_TY

    match = matches[-1]
    sx = float(match.group(1))
    sy = float(match.group(4))
    tx = float(match.group(5))
    ty = float(match.group(6))
    return sx, sy, tx, ty


def _extract_smask_from_pdf(pdf_path: Path) -> tuple[pikepdf.Page, Image.Image]:
    pdf = pikepdf.open(pdf_path)
    page = pdf.pages[0]
    xobjects = page.obj.get("/Resources", {}).get("/XObject", {})
    im0 = xobjects.get("/Im0")
    if im0 is None:
        for key, value in xobjects.items():
            if str(key).lower() == "/im0":
                im0 = value
                break
    if im0 is None:
        pdf.close()
        raise ValueError("Im0 not found in PDF resources")

    smask_obj = im0.get("/SMask")
    if smask_obj is None:
        pdf.close()
        raise ValueError("SMask missing from Im0")

    smask_pil = pikepdf.PdfImage(smask_obj).as_pil_image().convert("L")
    # Keep page alive for consumers; they can call page.root.close() later.
    return page, smask_pil


def _compose_overlay_with_smask(
    *,
    cover_path: Path,
    smask: Image.Image,
    frame_mask_path: Path,
    sx: float,
    sy: float,
    tx: float,
    ty: float,
    page_w_pt: float,
    page_h_pt: float,
    output_path: Path,
) -> None:
    cover_rgb = np.array(Image.open(cover_path).convert("RGB"), dtype=np.uint8)
    target_h, target_w = cover_rgb.shape[:2]
    ppx = float(target_w) / max(1.0, page_w_pt)
    ppy = float(target_h) / max(1.0, page_h_pt)

    im0_left = int(round(tx * ppx))
    im0_width = max(1, int(round(sx * ppx)))
    im0_height = max(1, int(round(sy * ppy)))
    im0_top = int(round(target_h - (ty * ppy) - im0_height))

    smask_resized = smask.resize((im0_width, im0_height), Image.LANCZOS)
    smask_arr = np.array(smask_resized, dtype=np.uint8)

    smask_canvas = np.zeros((target_h, target_w), dtype=np.uint8)
    left = max(0, im0_left)
    top = max(0, im0_top)
    right = min(target_w, im0_left + im0_width)
    bottom = min(target_h, im0_top + im0_height)
    if right <= left or bottom <= top:
        raise ValueError("Computed Im0 placement is outside cover bounds")

    src_left = left - im0_left
    src_top = top - im0_top
    src_right = src_left + (right - left)
    src_bottom = src_top + (bottom - top)
    smask_canvas[top:bottom, left:right] = smask_arr[src_top:src_bottom, src_left:src_right]

    alpha = np.full((target_h, target_w), 255, dtype=np.uint8)
    alpha[smask_canvas >= 240] = 0
    feather_zone = (smask_canvas >= 225) & (smask_canvas < 240)
    if np.any(feather_zone):
        feather_values = (240.0 - smask_canvas[feather_zone].astype(np.float32)) / 15.0 * 255.0
        alpha[feather_zone] = np.clip(feather_values, 0, 255).astype(np.uint8)
    # Preserve original medallion/frame exactly: only the inner opening may be transparent.
    # The frame mask encodes this contract (0 = opening, 255 = preserved frame/ring).
    frame_mask = Image.open(frame_mask_path).convert("L")
    if frame_mask.size != (target_w, target_h):
        frame_mask = frame_mask.resize((target_w, target_h), Image.LANCZOS)
    frame_mask_arr = np.array(frame_mask, dtype=np.uint8)
    alpha = np.maximum(alpha, frame_mask_arr)

    alpha, gap_count, ring_count = _apply_scrollwork_gap_transparency(
        cover_rgb=cover_rgb,
        alpha=alpha,
        center_x=CENTER_X,
        center_y=CENTER_Y,
    )
    if gap_count > 0:
        logger.info(
            "Made %d scrollwork gap pixels transparent (%.1f%% of ring) for %s",
            gap_count,
            100.0 * float(gap_count) / max(1, ring_count),
            output_path.name,
        )

    rgba = np.dstack([cover_rgb, alpha])
    # Zero RGB in fully transparent pixels to drastically improve PNG compression.
    rgba[rgba[:, :, 3] == 0, :3] = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(output_path, format="PNG", optimize=True)


def extract_overlay_from_pdf(pdf_path: Path, cover_jpg_path: Path, output_path: Path, frame_mask_path: Path) -> None:
    page = None
    pdf = None
    try:
        pdf = pikepdf.open(pdf_path)
        page = pdf.pages[0]
        xobjects = page.obj.get("/Resources", {}).get("/XObject", {})
        im0 = xobjects.get("/Im0")
        if im0 is None:
            for key, value in xobjects.items():
                if str(key).lower() == "/im0":
                    im0 = value
                    break
        if im0 is None:
            raise ValueError("Im0 not found in PDF resources")

        smask_obj = im0.get("/SMask")
        if smask_obj is None:
            raise ValueError("SMask missing from Im0")
        smask = pikepdf.PdfImage(smask_obj).as_pil_image().convert("L")

        page_w_pt, page_h_pt = _parse_page_size_points(page)
        sx, sy, tx, ty = _parse_im0_cm_matrix(page)
        _compose_overlay_with_smask(
            cover_path=cover_jpg_path,
            smask=smask,
            frame_mask_path=frame_mask_path,
            sx=sx,
            sy=sy,
            tx=tx,
            ty=ty,
            page_w_pt=page_w_pt,
            page_h_pt=page_h_pt,
            output_path=output_path,
        )
    finally:
        if pdf is not None:
            pdf.close()


def extract_overlay_fallback(cover_jpg_path: Path, output_path: Path, frame_mask_path: Path) -> None:
    cover_rgb = np.array(Image.open(cover_jpg_path).convert("RGB"), dtype=np.uint8)
    target_h, target_w = cover_rgb.shape[:2]
    mask = Image.open(frame_mask_path).convert("L")
    if mask.size != (target_w, target_h):
        mask = mask.resize((target_w, target_h), Image.LANCZOS)
    alpha = np.array(mask, dtype=np.uint8)

    alpha, gap_count, ring_count = _apply_scrollwork_gap_transparency(
        cover_rgb=cover_rgb,
        alpha=alpha,
        center_x=CENTER_X,
        center_y=CENTER_Y,
    )
    if gap_count > 0:
        logger.info(
            "Fallback: Made %d scrollwork gap pixels transparent (%.1f%% of ring) for %s",
            gap_count,
            100.0 * float(gap_count) / max(1, ring_count),
            output_path.name,
        )

    rgba = np.dstack([cover_rgb, alpha])
    # Zero RGB in fully transparent pixels to drastically improve PNG compression.
    rgba[rgba[:, :, 3] == 0, :3] = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(output_path, format="PNG", optimize=True)


def run_extraction(
    *,
    input_dir: Path,
    catalog_path: Path,
    overlay_dir: Path,
    frame_mask_path: Path,
    force: bool = False,
) -> OverlayStats:
    catalog = safe_json.load_json(catalog_path, [])
    if not isinstance(catalog, list):
        raise ValueError(f"Catalog payload must be a list: {catalog_path}")
    if not frame_mask_path.exists():
        raise FileNotFoundError(f"Missing frame mask fallback file: {frame_mask_path}")

    overlay_dir.mkdir(parents=True, exist_ok=True)
    stats = OverlayStats(total=len(catalog))

    for row in catalog:
        if not isinstance(row, dict):
            stats.failed += 1
            continue
        folder_name = str(row.get("folder_name", "")).strip()
        if not folder_name:
            stats.failed += 1
            continue

        cover_folder = input_dir / folder_name
        cover_jpg = _first_image_file(cover_folder)
        if cover_jpg is None:
            logger.warning("No source cover image found in %s", cover_folder)
            stats.failed += 1
            continue

        output_path = overlay_dir / f"{cover_jpg.stem}_frame.png"
        if output_path.exists() and not force:
            stats.skipped += 1
            continue

        source_pdf = _first_pdf_file(cover_folder)
        if source_pdf is not None:
            try:
                extract_overlay_from_pdf(source_pdf, cover_jpg, output_path, frame_mask_path)
                stats.pdf_extracted += 1
                logger.info("PDF-based overlay: %s -> %s", source_pdf.name, output_path.name)
                continue
            except Exception as exc:
                logger.warning("PDF extraction failed for %s: %s (fallback)", source_pdf, exc)

        try:
            extract_overlay_fallback(cover_jpg, output_path, frame_mask_path)
            stats.fallback += 1
            logger.info("Fallback overlay: %s -> %s", cover_jpg.name, output_path.name)
        except Exception as exc:
            logger.error("Overlay extraction failed for %s: %s", cover_jpg, exc)
            stats.failed += 1

    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract per-cover RGBA frame overlays")
    parser.add_argument("--input-dir", type=Path, default=config.INPUT_DIR)
    parser.add_argument("--catalog-path", type=Path, default=config.BOOK_CATALOG_PATH)
    parser.add_argument("--overlay-dir", type=Path, default=config.CONFIG_DIR / "frame_overlays")
    parser.add_argument("--frame-mask", type=Path, default=config.CONFIG_DIR / "frame_mask.png")
    parser.add_argument("--force", action="store_true", help="Recreate overlays even if already present")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")

    stats = run_extraction(
        input_dir=args.input_dir,
        catalog_path=args.catalog_path,
        overlay_dir=args.overlay_dir,
        frame_mask_path=args.frame_mask,
        force=bool(args.force),
    )
    print(
        "Overlay extraction complete: "
        f"total={stats.total}, pdf_extracted={stats.pdf_extracted}, "
        f"fallback={stats.fallback}, skipped={stats.skipped}, failed={stats.failed}"
    )
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
