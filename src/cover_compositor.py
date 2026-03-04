"""Prompt 3A cover compositing for circle/rectangle/custom regions."""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

try:
    from src import config
    from src import safe_json
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import safe_json  # type: ignore
    from logger import get_logger  # type: ignore

logger = get_logger(__name__)

DETECTION_ANALYSIS_W = 420
DETECTION_COARSE_STEP = 4
DETECTION_FINE_STEP = 1
DETECTION_SEARCH_RATIO = 0.15
DETECTION_OPENING_RATIO = 0.96
DETECTION_OPENING_MIN = 360
DETECTION_OPENING_MAX = 530
DETECTION_CONFIDENCE_MIN = 4.0
OPENING_SAFETY_INSET_PX = 0
OVERLAY_PUNCH_INSET_PX = -4
INNER_FEATHER_PX = 8
RING_WIDTH_PX = 14
RING_BEADS = 72
MIN_OPENING_MARGIN_PX = 20
FALLBACK_COVER_WIDTH = 3784
FALLBACK_COVER_HEIGHT = 2777
FALLBACK_CENTER_X = 2864
FALLBACK_CENTER_Y = 1620
FALLBACK_RADIUS = 500
TEMPLATE_PUNCH_RADIUS = 465
TEMPLATE_FALLBACK_PUNCH_RADIUS = 420
TEMPLATE_SUPERSAMPLE_FACTOR = 4
ART_BLEED_PX = 140
FRAME_MASK_PATH = Path(__file__).resolve().parent.parent / "config" / "frame_mask.png"
FRAME_OVERLAY_DIR = Path(__file__).resolve().parent.parent / "config" / "frame_overlays"
FRAME_OVERLAY_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_frame_overlays.py"
VERIFY_COMPOSITE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify_composite.py"

_GEOMETRY_CACHE: dict[str, dict[str, int]] = {}
_FRAME_OVERLAY_EXTRACTION_ATTEMPTED = False


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _dynamic_opening_bounds(width: int, height: int) -> tuple[int, int]:
    if int(width) == FALLBACK_COVER_WIDTH and int(height) == FALLBACK_COVER_HEIGHT:
        return DETECTION_OPENING_MIN, DETECTION_OPENING_MAX
    base = min(int(width), int(height))
    return max(16, int(round(base * 0.12))), max(24, int(round(base * 0.46)))


def _geometry_cache_key(cover_path: Path) -> str:
    try:
        stat = cover_path.stat()
        return f"{cover_path.resolve()}::{int(stat.st_mtime)}::{int(stat.st_size)}"
    except Exception:
        return str(cover_path.resolve())


def _fallback_geometry_for_cover(*, cover: Image.Image, region: "Region") -> dict[str, int]:
    width, height = cover.size
    if width == FALLBACK_COVER_WIDTH and height == FALLBACK_COVER_HEIGHT:
        center_x = FALLBACK_CENTER_X
        center_y = FALLBACK_CENTER_Y
        outer = FALLBACK_RADIUS
    else:
        center_x = int(region.center_x or round(width * 0.76))
        center_y = int(region.center_y or round(height * 0.58))
        outer = int(max(20, region.radius or round(min(width, height) * 0.19)))
    min_open, max_open = _dynamic_opening_bounds(width, height)
    opening = int(np.clip(round(outer * DETECTION_OPENING_RATIO), min_open, max_open))
    opening = min(opening, max(20, outer - MIN_OPENING_MARGIN_PX))
    return {
        "center_x": int(np.clip(center_x, 0, max(0, width - 1))),
        "center_y": int(np.clip(center_y, 0, max(0, height - 1))),
        "outer_radius": int(max(20, outer)),
        "opening_radius": int(max(20, opening)),
    }


def _ring_samples(count: int) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for idx in range(max(8, int(count))):
        angle = (idx / float(max(8, int(count)))) * np.pi * 2.0
        out.append((float(np.cos(angle)), float(np.sin(angle))))
    return out


_COARSE_RING_SAMPLES = _ring_samples(96)
_FINE_RING_SAMPLES = _ring_samples(180)


def _sample_map(channel: np.ndarray, x: float, y: float) -> float:
    h, w = channel.shape[:2]
    ix = int(np.clip(round(float(x)), 0, w - 1))
    iy = int(np.clip(round(float(y)), 0, h - 1))
    return float(channel[iy, ix])


def _score_ring(
    *,
    warm_map: np.ndarray,
    sat_map: np.ndarray,
    contrast_map: np.ndarray,
    center_x: float,
    center_y: float,
    radius: float,
    samples: list[tuple[float, float]],
    include_contrast: bool,
) -> float:
    if radius < 8:
        return float("-inf")
    warm_vals: list[float] = []
    sat_vals: list[float] = []
    contrast_vals: list[float] = []
    for cos_a, sin_a in samples:
        px = center_x + (radius * cos_a)
        py = center_y + (radius * sin_a)
        warm_vals.append(_sample_map(warm_map, px, py))
        sat_vals.append(_sample_map(sat_map, px, py))
        if include_contrast:
            contrast_vals.append(_sample_map(contrast_map, px, py))

    ring_warm = float(np.mean(warm_vals)) if warm_vals else float("-inf")
    ring_sat = float(np.mean(sat_vals)) if sat_vals else 0.0
    ring_contrast = float(np.mean(contrast_vals)) if contrast_vals else 0.0
    if include_contrast:
        return ring_warm + (0.24 * ring_sat) + (0.60 * ring_contrast)
    return ring_warm + (0.26 * ring_sat)


def _ring_peak_confidence(
    *,
    warm_map: np.ndarray,
    sat_map: np.ndarray,
    contrast_map: np.ndarray,
    center_x: float,
    center_y: float,
    radius: float,
) -> float:
    probe_offsets = [
        (-10.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (0.0, -10.0, 0.0),
        (0.0, 10.0, 0.0),
        (-8.0, -8.0, 0.0),
        (8.0, 8.0, 0.0),
        (0.0, 0.0, -10.0),
        (0.0, 0.0, 10.0),
    ]
    best_score = _score_ring(
        warm_map=warm_map,
        sat_map=sat_map,
        contrast_map=contrast_map,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        samples=_FINE_RING_SAMPLES,
        include_contrast=False,
    )
    local_scores: list[float] = []
    for dx, dy, dr in probe_offsets:
        score = _score_ring(
            warm_map=warm_map,
            sat_map=sat_map,
            contrast_map=contrast_map,
            center_x=center_x + dx,
            center_y=center_y + dy,
            radius=max(12.0, radius + dr),
            samples=_FINE_RING_SAMPLES,
            include_contrast=False,
        )
        if np.isfinite(score):
            local_scores.append(float(score))
    if not local_scores or not np.isfinite(best_score):
        return 0.0
    return max(0.0, float(best_score) - float(np.median(local_scores)))


def _detect_medallion_geometry(*, cover: Image.Image, region: Region) -> dict[str, int]:
    rgb = np.array(cover.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    if h <= 0 or w <= 0:
        return {
            "center_x": int(region.center_x),
            "center_y": int(region.center_y),
            "outer_radius": int(region.radius),
            "score": int(-1e9),
            "confidence": 0,
        }

    scale = min(1.0, float(DETECTION_ANALYSIS_W) / float(max(h, w)))
    if scale < 0.999:
        scan_w = max(1, int(round(w * scale)))
        scan_h = max(1, int(round(h * scale)))
        scan = np.array(cover.resize((scan_w, scan_h), Image.LANCZOS).convert("RGB"), dtype=np.float32)
    else:
        scan = rgb
        scan_h, scan_w = h, w

    r = scan[..., 0]
    g = scan[..., 1]
    b = scan[..., 2]
    warm_map = (r - b) + (0.45 * (g - b))
    sat_map = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    gray = (0.299 * r) + (0.587 * g) + (0.114 * b)
    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    contrast_map = np.pad(dx, ((0, 0), (0, 1)), mode="constant") + np.pad(dy, ((0, 1), (0, 0)), mode="constant")

    cx0 = float((region.center_x or int(round(w * 0.76))) * scale)
    cy0 = float((region.center_y or int(round(h * 0.58))) * scale)
    r0 = float((region.radius or int(round(min(w, h) * 0.19))) * scale)

    search_x = max(30, int(round(scan_w * DETECTION_SEARCH_RATIO)))
    search_y = max(30, int(round(scan_h * DETECTION_SEARCH_RATIO)))
    coarse_r_min = max(24, int(round(r0 * 0.65)))
    coarse_r_max = min(int(round(min(scan_w, scan_h) * 0.49)), int(round(r0 * 1.40)))
    if coarse_r_max <= coarse_r_min:
        coarse_r_max = coarse_r_min + 24

    best = {"score": float("-inf"), "cx": int(round(cx0)), "cy": int(round(cy0)), "r": int(round(r0))}
    for cy in range(max(12, int(round(cy0)) - search_y), min(scan_h - 12, int(round(cy0)) + search_y + 1), DETECTION_COARSE_STEP):
        for cx in range(max(12, int(round(cx0)) - search_x), min(scan_w - 12, int(round(cx0)) + search_x + 1), DETECTION_COARSE_STEP):
            for radius in range(coarse_r_min, coarse_r_max + 1, DETECTION_COARSE_STEP):
                score = _score_ring(
                    warm_map=warm_map,
                    sat_map=sat_map,
                    contrast_map=contrast_map,
                    center_x=float(cx),
                    center_y=float(cy),
                    radius=float(radius),
                    samples=_COARSE_RING_SAMPLES,
                    include_contrast=True,
                )
                if score > float(best["score"]):
                    best = {"score": score, "cx": cx, "cy": cy, "r": radius}

    fine_best = dict(best)
    fine_r_min = max(20, int(best["r"]) - 16)
    fine_r_max = min(int(round(min(scan_w, scan_h) * 0.50)), int(best["r"]) + 16)
    for cy in range(max(10, int(best["cy"]) - 16), min(scan_h - 10, int(best["cy"]) + 17), DETECTION_FINE_STEP):
        for cx in range(max(10, int(best["cx"]) - 16), min(scan_w - 10, int(best["cx"]) + 17), DETECTION_FINE_STEP):
            for radius in range(fine_r_min, fine_r_max + 1, DETECTION_FINE_STEP):
                score = _score_ring(
                    warm_map=warm_map,
                    sat_map=sat_map,
                    contrast_map=contrast_map,
                    center_x=float(cx),
                    center_y=float(cy),
                    radius=float(radius),
                    samples=_FINE_RING_SAMPLES,
                    include_contrast=False,
                )
                if score > float(fine_best["score"]):
                    fine_best = {"score": score, "cx": cx, "cy": cy, "r": radius}

    inv = 1.0 / max(1e-6, scale)
    center_x = int(round(float(fine_best["cx"]) * inv))
    center_y = int(round(float(fine_best["cy"]) * inv))
    outer_radius = int(round(float(fine_best["r"]) * inv))
    confidence = _ring_peak_confidence(
        warm_map=warm_map,
        sat_map=sat_map,
        contrast_map=contrast_map,
        center_x=float(fine_best["cx"]),
        center_y=float(fine_best["cy"]),
        radius=float(fine_best["r"]),
    )
    return {
        "center_x": center_x,
        "center_y": center_y,
        "outer_radius": outer_radius,
        "score": int(round(float(fine_best["score"]) * 1000.0)),
        "confidence": int(round(confidence * 1000.0)),
    }


def _resolve_medallion_geometry(*, cover: Image.Image, cover_path: Path, region: Region) -> dict[str, int]:
    if region.center_x > 0 and region.center_y > 0 and region.radius > 0:
        outer = int(max(20, region.radius))
        min_open, max_open = _dynamic_opening_bounds(*cover.size)
        opening = int(np.clip(round(outer * DETECTION_OPENING_RATIO), min_open, max_open))
        opening = min(opening, max(20, int(outer) - MIN_OPENING_MARGIN_PX))
        payload = {
            "center_x": int(region.center_x),
            "center_y": int(region.center_y),
            "outer_radius": int(outer),
            "opening_radius": int(opening),
        }
        key = _geometry_cache_key(cover_path)
        _GEOMETRY_CACHE[key] = dict(payload)
        logger.info(
            "Compositor using known geometry: cx=%d cy=%d outer=%d opening=%d",
            payload["center_x"],
            payload["center_y"],
            payload["outer_radius"],
            payload["opening_radius"],
        )
        return payload

    fallback = _fallback_geometry_for_cover(cover=cover, region=region)
    try:
        key = _geometry_cache_key(cover_path)
        if key in _GEOMETRY_CACHE:
            return dict(_GEOMETRY_CACHE[key])
        detected = _detect_medallion_geometry(cover=cover, region=region)
        detected_cx = int(detected.get("center_x", fallback["center_x"]))
        detected_cy = int(detected.get("center_y", fallback["center_y"]))
        detected_outer = int(max(20, detected.get("outer_radius", fallback["outer_radius"])))
        confidence_raw = detected.get("confidence", None)
        if confidence_raw is None:
            confidence = DETECTION_CONFIDENCE_MIN + 1.0
        else:
            confidence = float(confidence_raw) / 1000.0
        score = float(detected.get("score", 0)) / 1000.0

        use_detected = bool(np.isfinite(confidence) and confidence >= DETECTION_CONFIDENCE_MIN and np.isfinite(score))
        if region.center_x > 0 and region.center_y > 0 and region.radius > 0:
            offset = float(np.sqrt(((detected_cx - region.center_x) ** 2) + ((detected_cy - region.center_y) ** 2)))
            max_offset = max(80.0, float(region.radius) * 0.55)
            if offset > max_offset:
                use_detected = False

        outer = detected_outer if use_detected else fallback["outer_radius"]
        center_x = detected_cx if use_detected else fallback["center_x"]
        center_y = detected_cy if use_detected else fallback["center_y"]
        min_open, max_open = _dynamic_opening_bounds(*cover.size)
        opening = int(np.clip(round(outer * DETECTION_OPENING_RATIO), min_open, max_open))
        opening = min(opening, max(20, int(outer) - MIN_OPENING_MARGIN_PX))
        payload = {
            "center_x": int(center_x),
            "center_y": int(center_y),
            "outer_radius": int(outer),
            "opening_radius": int(opening),
        }
        _GEOMETRY_CACHE[key] = dict(payload)
        logger.info("Compositor fallback-detection used for %s", cover_path)
        return payload
    except Exception as exc:
        logger.warning("Falling back to configured medallion geometry for %s: %s", cover_path, exc)
        return fallback


def _sample_cover_background(*, cover: Image.Image, center_x: int, center_y: int, outer_radius: int) -> tuple[int, int, int]:
    rgb = np.array(cover.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - float(center_x)) ** 2 + (yy - float(center_y)) ** 2)
    band_inner = max(12.0, float(outer_radius) * 1.42)
    band_outer = min(float(max(h, w)), float(outer_radius) * 1.92)
    band = (dist >= band_inner) & (dist <= band_outer)
    if np.any(band):
        pixels = rgb[band]
        sat = pixels.max(axis=1) - pixels.min(axis=1)
        dark = pixels.mean(axis=1) < 135
        cool = pixels[:, 2] >= (pixels[:, 0] - 6)
        keep = (sat < 95) & dark & cool
        if np.any(keep):
            pixels = pixels[keep]
        if pixels.size:
            med = np.median(pixels, axis=0)
            return (int(np.clip(med[0], 0, 255)), int(np.clip(med[1], 0, 255)), int(np.clip(med[2], 0, 255)))
    edge_strip = np.concatenate(
        [
            rgb[: max(1, h // 14), :, :].reshape(-1, 3),
            rgb[max(0, h - max(1, h // 14)) :, :, :].reshape(-1, 3),
            rgb[:, : max(1, w // 14), :].reshape(-1, 3),
            rgb[:, max(0, w - max(1, w // 14)) :, :].reshape(-1, 3),
        ],
        axis=0,
    )
    med = np.median(edge_strip, axis=0)
    return (int(np.clip(med[0], 0, 255)), int(np.clip(med[1], 0, 255)), int(np.clip(med[2], 0, 255)))


def _geometry_from_strict_mask(mask: Image.Image | None) -> dict[str, int] | None:
    if mask is None:
        return None
    arr = np.array(mask.convert("L"), dtype=np.uint8)
    if arr.size <= 0:
        return None
    active = arr > 8
    if not np.any(active):
        return None

    ys, xs = np.where(active)
    weights = arr[active].astype(np.float64)
    wsum = float(weights.sum())
    if wsum <= 1e-6:
        return None

    center_x = int(round(float((xs * weights).sum() / wsum)))
    center_y = int(round(float((ys * weights).sum() / wsum)))
    area = float(np.count_nonzero(active))
    equiv_radius = float(np.sqrt(area / np.pi))

    min_x = int(xs.min())
    max_x = int(xs.max())
    min_y = int(ys.min())
    max_y = int(ys.max())
    bbox_radius = 0.5 * float(min(max_x - min_x + 1, max_y - min_y + 1))

    opening_radius = int(round(max(20.0, min(bbox_radius, equiv_radius))))
    outer_radius = int(max(opening_radius + MIN_OPENING_MARGIN_PX, round(opening_radius * 1.06)))

    return {
        "center_x": int(center_x),
        "center_y": int(center_y),
        "opening_radius": int(opening_radius),
        "outer_radius": int(outer_radius),
    }


def _smart_square_crop(image: Image.Image) -> Image.Image:
    """Crop image to a centered square for deterministic medallion placement."""
    src = image.convert("RGBA")
    img_w, img_h = src.size
    if img_w <= 1 or img_h <= 1:
        return src
    side = min(img_w, img_h)
    left = (img_w - side) // 2
    top = (img_h - side) // 2
    return src.crop((left, top, left + side, top + side))


def _simple_center_crop(image: Image.Image) -> Image.Image:
    """Center crop to square. No foreground detection."""
    src = image.convert("RGBA")
    w, h = src.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return src.crop((left, top, left + side, top + side))


def _find_template_for_cover(cover_path: Path) -> Path | None:
    """Find the PNG template matching a cover source file."""
    stem = cover_path.stem
    template_dir = config.CONFIG_DIR / "templates"
    candidate = template_dir / f"{stem}_template.png"
    if candidate.exists():
        return candidate
    nums = re.findall(r"\d+", stem)
    if nums:
        target = nums[-1]
        for file_path in sorted(template_dir.glob("*_template.png")):
            found = re.findall(r"\d+", file_path.stem)
            if found and found[-1] == target:
                return file_path
    return None


def _create_template_for_cover(
    *,
    cover: Image.Image,
    cover_path: Path,
    center_x: int,
    center_y: int,
    punch_radius: int = TEMPLATE_PUNCH_RADIUS,
) -> Path | None:
    """Create a PNG template for a cover on demand."""
    template_dir = config.CONFIG_DIR / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    output_path = template_dir / f"{cover_path.stem}_template.png"
    try:
        cover_rgba = cover.convert("RGBA")
        width, height = cover_rgba.size
        scale = max(1, int(TEMPLATE_SUPERSAMPLE_FACTOR))
        mask_large = Image.new("L", (width * scale, height * scale), 255)
        draw = ImageDraw.Draw(mask_large)
        cx = int(center_x) * scale
        cy = int(center_y) * scale
        r = int(punch_radius) * scale
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
        mask = mask_large.resize((width, height), Image.LANCZOS)
        cover_rgba.putalpha(mask)
        cover_rgba.save(output_path, format="PNG")
        logger.info("Generated PNG template: %s", output_path.name)
        return output_path
    except Exception as exc:
        logger.warning("Failed to generate PNG template for %s: %s", cover_path.name, exc)
        return None


def _prepare_circle_illustration(*, illustration: Image.Image, target_diameter: int, fill_rgb: tuple[int, int, int]) -> Image.Image:
    cropped = _smart_square_crop(illustration)
    if cropped.mode != "RGBA":
        cropped = cropped.convert("RGBA")
    side = max(2, int(target_diameter))
    resized = cropped.resize((side, side), Image.LANCZOS)

    # Flatten transparency to avoid checkerboard/sticker artifacts leaking through.
    flattened = Image.new("RGBA", (side, side), (int(fill_rgb[0]), int(fill_rgb[1]), int(fill_rgb[2]), 255))
    flattened.alpha_composite(resized)
    return flattened


def _draw_gold_ring_pil(
    *,
    size: tuple[int, int],
    center_x: int,
    center_y: int,
    radius: int,
    ring_width: int,
) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")
    outer = float(max(4, int(radius)))
    width_px = max(2, int(ring_width))
    for idx in range(width_px):
        t = idx / float(max(1, width_px - 1))
        brightness = 0.82 + (0.28 * (1.0 - abs((t * 2.0) - 1.0)))
        red = int(np.clip(188 * brightness, 0, 255))
        green = int(np.clip(150 * brightness, 0, 255))
        blue = int(np.clip(74 * brightness, 0, 255))
        alpha = int(np.clip(188 + (42 * (1.0 - t)), 0, 255))
        rad = outer - idx
        draw.ellipse(
            (center_x - rad, center_y - rad, center_x + rad, center_y + rad),
            outline=(red, green, blue, alpha),
            width=1,
        )

    bead_radius = max(1, int(round(width_px * 0.16)))
    bead_ring = outer + (width_px * 0.15)
    for idx in range(RING_BEADS):
        angle = (idx / float(RING_BEADS)) * np.pi * 2.0
        bx = int(round(center_x + (np.cos(angle) * bead_ring)))
        by = int(round(center_y + (np.sin(angle) * bead_ring)))
        draw.ellipse(
            (bx - bead_radius, by - bead_radius, bx + bead_radius, by + bead_radius),
            fill=(236, 202, 130, 170),
            outline=(120, 90, 40, 140),
            width=1,
        )
    return layer


def _build_cover_overlay_with_punch(
    *,
    cover: Image.Image,
    center_x: int,
    center_y: int,
    punch_radius: int,
    punch_mask: Image.Image | None = None,
) -> Image.Image:
    overlay = cover.convert("RGBA").copy()
    if punch_mask is not None:
        mask = punch_mask.convert("L")
        if mask.size != cover.size:
            mask = mask.resize(cover.size, Image.LANCZOS)
        mask_arr = np.array(mask, dtype=np.uint8)
        alpha = Image.fromarray((255 - mask_arr).astype(np.uint8), mode="L")
        overlay.putalpha(alpha)
        return overlay

    alpha = Image.new("L", cover.size, 255)
    draw = ImageDraw.Draw(alpha)
    r = max(4, int(punch_radius))
    draw.ellipse((center_x - r, center_y - r, center_x + r, center_y + r), fill=0)
    overlay.putalpha(alpha)
    return overlay


def _legacy_medallion_composite(
    *,
    cover: Image.Image,
    illustration: Image.Image,
    region_obj: "Region",
    cover_w: int,
    cover_h: int,
    geometry: dict[str, int],
    strict_window_mask: Image.Image | None,
) -> tuple[Image.Image, "Region"]:
    """Legacy medallion compositing pipeline kept as runtime fallback."""
    opening_radius = max(20, int(geometry["opening_radius"]))
    clip_radius = max(14, opening_radius - OPENING_SAFETY_INSET_PX)
    fill_rgb = _sample_cover_background(
        cover=cover,
        center_x=int(geometry["center_x"]),
        center_y=int(geometry["center_y"]),
        outer_radius=int(geometry["outer_radius"]),
    )

    canvas = Image.new("RGBA", (cover_w, cover_h), (*fill_rgb, 255))
    prepared = _prepare_circle_illustration(
        illustration=illustration,
        target_diameter=clip_radius * 2,
        fill_rgb=fill_rgb,
    )
    art_layer = Image.new("RGBA", (cover_w, cover_h), (0, 0, 0, 0))
    _paste_centered(
        canvas=art_layer,
        overlay=prepared,
        center_x=int(geometry["center_x"]),
        center_y=int(geometry["center_y"]),
    )
    clip_mask = _build_circle_feather_mask(
        width=cover_w,
        height=cover_h,
        center_x=int(geometry["center_x"]),
        center_y=int(geometry["center_y"]),
        radius=clip_radius,
        feather_px=INNER_FEATHER_PX,
    )
    if strict_window_mask is not None:
        clip_mask = _combine_masks(clip_mask, strict_window_mask)
    art_layer.putalpha(clip_mask)
    composited = Image.alpha_composite(canvas, art_layer)

    overlay = _build_cover_overlay_with_punch(
        cover=cover,
        center_x=int(geometry["center_x"]),
        center_y=int(geometry["center_y"]),
        punch_radius=max(12, opening_radius - OVERLAY_PUNCH_INSET_PX),
        punch_mask=strict_window_mask,
    )
    composited_rgb = Image.alpha_composite(composited, overlay).convert("RGB")
    validation_region = Region(
        center_x=int(geometry["center_x"]),
        center_y=int(geometry["center_y"]),
        radius=opening_radius,
        frame_bbox=region_obj.frame_bbox,
        region_type="circle",
    )
    return composited_rgb, validation_region


@dataclass(slots=True)
class Region:
    center_x: int
    center_y: int
    radius: int
    frame_bbox: tuple[int, int, int, int]
    region_type: str = "circle"
    rect_bbox: tuple[int, int, int, int] | None = None
    mask_path: str | None = None


@dataclass(slots=True)
class CompositeValidation:
    output_path: str
    valid: bool
    issues: list[str]
    dimensions_ok: bool
    dpi_ok: bool
    file_size_ok: bool
    alignment_ok: bool
    border_bleed_ok: bool
    edge_artifacts_ok: bool
    metrics: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": self.output_path,
            "valid": self.valid,
            "issues": list(self.issues),
            "dimensions_ok": self.dimensions_ok,
            "dpi_ok": self.dpi_ok,
            "file_size_ok": self.file_size_ok,
            "alignment_ok": self.alignment_ok,
            "border_bleed_ok": self.border_bleed_ok,
            "edge_artifacts_ok": self.edge_artifacts_ok,
            "metrics": dict(self.metrics),
        }


def composite_single(
    cover_path: Path,
    illustration_path: Path,
    region: dict[str, Any],
    output_path: Path,
    feather_px: int = 15,
    frame_overlap_px: int = 24,
) -> Path:
    """Composite one illustration into a cover image."""
    runtime = config.get_config()
    cover = Image.open(cover_path).convert("RGB")
    illustration = Image.open(illustration_path).convert("RGBA")
    illustration = _strip_border(illustration, border_percent=float(getattr(runtime, "border_strip_percent", 0.05)))

    if cover.size != (3784, 2777):
        logger.warning("Cover %s has unexpected size %s", cover_path, cover.size)

    region_obj = _region_from_dict(region)
    cover_w, cover_h = cover.size
    strict_window_mask = _load_global_compositing_mask((cover_w, cover_h))

    validation_region = region_obj
    composited_rgb: Image.Image

    if region_obj.region_type == "rectangle" and region_obj.rect_bbox is not None:
        full_overlay = Image.new("RGBA", (cover_w, cover_h), (0, 0, 0, 0))
        x1, y1, x2, y2 = region_obj.rect_bbox
        target_w = max(1, x2 - x1)
        target_h = max(1, y2 - y1)
        resized = illustration.resize((target_w, target_h), Image.LANCZOS)
        resized = _color_match_illustration(cover=cover, illustration=resized, region=region_obj)
        full_overlay.paste(resized, (x1, y1))
        mask = _build_rect_feather_mask(
            width=cover_w,
            height=cover_h,
            bbox=(x1, y1, x2, y2),
            feather_px=feather_px,
        )
        if strict_window_mask is not None:
            mask = _combine_masks(mask, strict_window_mask)
        full_overlay.putalpha(mask)
        composited_rgb = Image.alpha_composite(cover.convert("RGBA"), full_overlay).convert("RGB")
    elif region_obj.region_type == "custom_mask" and region_obj.mask_path:
        # Preserve explicit custom-mask behavior for non-medallion special cases.
        full_overlay = Image.new("RGBA", (cover_w, cover_h), (0, 0, 0, 0))
        effective_radius = max(20, region_obj.radius - frame_overlap_px)
        diameter = effective_radius * 2
        resized = illustration.resize((diameter, diameter), Image.LANCZOS)
        resized = _color_match_illustration(cover=cover, illustration=resized, region=region_obj)
        _paste_centered(
            canvas=full_overlay,
            overlay=resized,
            center_x=region_obj.center_x,
            center_y=region_obj.center_y,
        )
        mask = _load_custom_mask(region_obj.mask_path, cover.size)
        if strict_window_mask is not None:
            mask = _combine_masks(mask, strict_window_mask)
        full_overlay.putalpha(mask)
        composited_rgb = Image.alpha_composite(cover.convert("RGBA"), full_overlay).convert("RGB")
    else:
        # ── RGBA Frame-Overlay Compositing ─────────────────────────
        # Three layers: canvas -> art -> RGBA overlay (frame painted LAST).
        center_x = FALLBACK_CENTER_X
        center_y = FALLBACK_CENTER_Y

        frame_overlay = _load_frame_overlay(cover_path, cover.size)
        if frame_overlay is None:
            frame_overlay = _build_fallback_frame_overlay(
                cover=cover,
                center_x=center_x,
                center_y=center_y,
                punch_radius=TEMPLATE_PUNCH_RADIUS,
            )

        fill_rgb = _sample_cover_background(
            cover=cover,
            center_x=center_x,
            center_y=center_y,
            outer_radius=FALLBACK_RADIUS,
        )

        canvas = Image.new("RGBA", (cover_w, cover_h), (*fill_rgb, 255))

        art_diameter = FALLBACK_RADIUS * 2 + (ART_BLEED_PX * 2)
        art = _simple_center_crop(illustration)
        art = art.resize((art_diameter, art_diameter), Image.LANCZOS)
        art = _color_match_illustration(cover=cover, illustration=art, region=region_obj)

        art_bg = Image.new("RGBA", (art_diameter, art_diameter), (*fill_rgb, 255))
        art_bg.alpha_composite(art)
        art = art_bg

        art_layer = Image.new("RGBA", (cover_w, cover_h), (0, 0, 0, 0))
        art_layer.paste(art, (center_x - art_diameter // 2, center_y - art_diameter // 2))

        result = Image.alpha_composite(canvas, art_layer)
        result = Image.alpha_composite(result, frame_overlay)
        composited_rgb = result.convert("RGB")

        _orig_arr = np.array(cover, dtype=np.float32)
        _comp_arr = np.array(composited_rgb, dtype=np.float32)
        _h, _w = _orig_arr.shape[:2]
        _yy, _xx = np.ogrid[:_h, :_w]
        _dist = np.sqrt((_xx - center_x) ** 2 + (_yy - center_y) ** 2)
        _ring = (_dist >= 500) & (_dist <= 680)
        _diff = np.abs(_orig_arr - _comp_arr).max(axis=2)
        _ring_diff = _diff[_ring]
        _changed_pct = 100.0 * float(np.sum(_ring_diff > 15)) / max(1, int(_ring_diff.size))
        _mean_delta = float(_ring_diff.mean()) if _ring_diff.size else 0.0

        if _changed_pct > 5.0 or _mean_delta > 10.0:
            logger.error(
                "FRAME DAMAGE DETECTED for %s: changed=%.1f%%, mean_delta=%.1f. Composite REJECTED.",
                cover_path.name,
                _changed_pct,
                _mean_delta,
            )
            raise ValueError(
                f"Frame integrity check failed for {cover_path.name}: "
                f"ring_changed={_changed_pct:.1f}%, mean_delta={_mean_delta:.1f}"
            )
        logger.info(
            "Frame integrity OK for %s: changed=%.1f%%, mean_delta=%.1f",
            cover_path.name,
            _changed_pct,
            _mean_delta,
        )

        validation_region = Region(
            center_x=center_x,
            center_y=center_y,
            radius=max(20, TEMPLATE_PUNCH_RADIUS),
            frame_bbox=region_obj.frame_bbox,
            region_type="circle",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    composited_rgb.save(output_path, format="JPEG", quality=100, subsampling=0, dpi=(300, 300))
    validation = validate_composite_output(
        cover=cover,
        composited=composited_rgb,
        region=validation_region,
        output_path=output_path,
    )
    safe_json.atomic_write_json(
        _validation_path(output_path),
        {
            **validation.to_dict(),
            "validated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if not validation.valid:
        logger.warning("Composite validation issues for %s: %s", output_path, ", ".join(validation.issues))
    return output_path


def generate_fit_overlay(cover_path: Path, region: dict[str, Any], output_path: Path) -> Path:
    """Generate visual overlay for fit verification in review UI."""
    base = Image.open(cover_path).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    reg = _region_from_dict(region)

    if reg.region_type == "rectangle" and reg.rect_bbox is not None:
        x1, y1, x2, y2 = reg.rect_bbox
        draw.rectangle((x1, y1, x2, y2), outline=(255, 64, 64, 230), width=6, fill=(255, 64, 64, 40))
    else:
        comp_radius = max(20, reg.radius - 18)
        draw.ellipse(
            (
                reg.center_x - comp_radius,
                reg.center_y - comp_radius,
                reg.center_x + comp_radius,
                reg.center_y + comp_radius,
            ),
            outline=(255, 64, 64, 230),
            width=6,
            fill=(255, 64, 64, 40),
        )
        draw.ellipse(
            (
                reg.center_x - reg.radius,
                reg.center_y - reg.radius,
                reg.center_x + reg.radius,
                reg.center_y + reg.radius,
            ),
            outline=(255, 210, 90, 230),
            width=4,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    base.save(output_path, format="PNG")
    return output_path


def composite_all_variants(
    book_number: int,
    input_dir: Path,
    generated_dir: Path,
    output_dir: Path,
    regions: dict[str, Any],
    *,
    catalog_path: Path = config.BOOK_CATALOG_PATH,
) -> list[Path]:
    """Composite all available generated variants for one book."""
    ensure_frame_overlays_exist(input_dir=input_dir, catalog_path=catalog_path)
    cover_path = _find_cover_jpg(input_dir, book_number, catalog_path=catalog_path)
    region = _region_for_book(regions, book_number)

    image_rows = _collect_generated_for_book(generated_dir, book_number)
    if not image_rows:
        raise FileNotFoundError(f"No generated images found for book {book_number} in {generated_dir}")

    outputs: list[Path] = []
    validations: list[dict[str, Any]] = []
    for row in image_rows:
        if row["model"] == "default":
            out_path = output_dir / str(book_number) / f"variant_{row['variant']}.jpg"
        else:
            out_path = output_dir / str(book_number) / row["model"] / f"variant_{row['variant']}.jpg"

        composite_single(
            cover_path=cover_path,
            illustration_path=row["path"],
            region=region,
            output_path=out_path,
        )
        outputs.append(out_path)
        validation_payload = _load_validation_payload(out_path)
        if validation_payload:
            validations.append(validation_payload)

    generate_fit_overlay(
        cover_path=cover_path,
        region=region,
        output_path=output_dir / str(book_number) / "fit_overlay.png",
    )

    if validations:
        summary = {
            "book_number": int(book_number),
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(validations),
            "invalid": sum(1 for row in validations if not bool(row.get("valid", False))),
            "items": validations,
        }
        report_path = output_dir / str(book_number) / "composite_validation.json"
        safe_json.atomic_write_json(report_path, summary)

    return outputs


def _frame_sample_points(*, width: int, height: int) -> list[tuple[int, int]]:
    points = [
        (max(0, int(round(width * 0.05))), max(0, int(round(height * 0.05)))),
        (max(0, int(round(width * 0.50))), max(0, int(round(height * 0.05)))),
        (max(0, int(round(width * 0.95))), max(0, int(round(height * 0.05)))),
        (max(0, int(round(width * 0.05))), max(0, int(round(height * 0.50)))),
        (max(0, int(round(width * 0.95))), max(0, int(round(height * 0.50)))),
        (max(0, int(round(width * 0.05))), max(0, int(round(height * 0.95)))),
        (max(0, int(round(width * 0.50))), max(0, int(round(height * 0.95)))),
        (max(0, int(round(width * 0.95))), max(0, int(round(height * 0.95)))),
        (max(0, int(round(width * 0.30))), max(0, int(round(height * 0.15)))),
        (max(0, int(round(width * 0.70))), max(0, int(round(height * 0.84)))),
    ]
    dedup: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for x, y in points:
        clamped = (int(np.clip(x, 0, max(0, width - 1))), int(np.clip(y, 0, max(0, height - 1))))
        if clamped in seen:
            continue
        seen.add(clamped)
        dedup.append(clamped)
    return dedup


def _frame_integrity_metrics(
    *,
    cover_arr: np.ndarray,
    comp_arr: np.ndarray,
    region: Region,
) -> tuple[float, float]:
    h, w = cover_arr.shape[:2]
    points = _frame_sample_points(width=w, height=h)
    if region.region_type == "rectangle" and region.rect_bbox is not None:
        x1, y1, x2, y2 = region.rect_bbox
        points = [
            (x, y)
            for (x, y) in points
            if not (x1 - 12 <= x <= x2 + 12 and y1 - 12 <= y <= y2 + 12)
        ]
    else:
        cx = float(region.center_x)
        cy = float(region.center_y)
        guard = max(24.0, float(region.radius) + 20.0)
        points = [
            (x, y)
            for (x, y) in points
            if ((float(x) - cx) ** 2 + (float(y) - cy) ** 2) >= (guard * guard)
        ]
    if not points:
        return 0.0, 0.0
    deltas = [
        float(np.abs(comp_arr[y, x].astype(np.int16) - cover_arr[y, x].astype(np.int16)).mean())
        for (x, y) in points
    ]
    return float(np.max(deltas)), float(np.mean(deltas))


def validate_composite_output(
    *,
    cover: Image.Image,
    composited: Image.Image,
    region: Region,
    output_path: Path,
) -> CompositeValidation:
    issues: list[str] = []
    cover_arr = np.array(cover.convert("RGB"), dtype=np.int16)
    comp_arr = np.array(composited.convert("RGB"), dtype=np.int16)
    diff = np.abs(comp_arr - cover_arr).mean(axis=2)
    changed = diff > 6.0

    dimensions_ok = tuple(composited.size) == tuple(cover.size)
    if not dimensions_ok:
        issues.append("dimension_mismatch")

    try:
        with Image.open(output_path) as output_meta:
            dpi = output_meta.info.get("dpi", (0, 0))
    except Exception:  # pragma: no cover - defensive
        dpi = (0, 0)
    dpi_x, dpi_y = (float(dpi[0]) if len(dpi) > 0 else 0.0, float(dpi[1]) if len(dpi) > 1 else 0.0)
    dpi_ok = dpi_x >= 295.0 and dpi_y >= 295.0
    if not dpi_ok:
        issues.append("dpi_metadata_invalid")

    file_size_kb = float(output_path.stat().st_size) / 1024.0 if output_path.exists() else 0.0
    file_size_ok = 60.0 <= file_size_kb <= 30_000.0
    if not file_size_ok:
        issues.append("file_size_out_of_bounds")

    h, w = diff.shape
    if np.any(changed):
        changed_points = np.argwhere(changed)
        centroid_y = float(changed_points[:, 0].mean())
        centroid_x = float(changed_points[:, 1].mean())
    else:
        centroid_x = float(region.center_x)
        centroid_y = float(region.center_y)
        issues.append("no_visible_composite_difference")

    if region.region_type == "rectangle" and region.rect_bbox is not None:
        x1, y1, x2, y2 = region.rect_bbox
        target_x = (x1 + x2) / 2.0
        target_y = (y1 + y2) / 2.0
        tolerance = max(25.0, max(x2 - x1, y2 - y1) * 0.40)
        expected_mask = np.zeros((h, w), dtype=bool)
        expected_mask[max(0, y1 - 10):min(h, y2 + 10), max(0, x1 - 10):min(w, x2 + 10)] = True
    else:
        target_x = float(region.center_x)
        target_y = float(region.center_y)
        tolerance = max(25.0, float(region.radius) * 0.45)
        yy, xx = np.ogrid[:h, :w]
        dist = np.sqrt((xx - target_x) ** 2 + (yy - target_y) ** 2)
        expected_mask = dist <= max(10.0, float(region.radius) + 10.0)

    alignment_distance = float(np.sqrt((centroid_x - target_x) ** 2 + (centroid_y - target_y) ** 2))
    alignment_ok = alignment_distance <= tolerance
    if not alignment_ok:
        issues.append("alignment_offset_high")

    outside_expected = ~expected_mask
    bleed_ratio = float(changed[outside_expected].mean()) if outside_expected.any() else 0.0
    border_bleed_ok = bleed_ratio <= 0.02
    if not border_bleed_ok:
        issues.append("border_bleed_detected")

    ring_strength = 0.0
    if region.region_type != "rectangle":
        yy, xx = np.ogrid[:h, :w]
        dist = np.sqrt((xx - target_x) ** 2 + (yy - target_y) ** 2)
        ring = (dist >= max(0.0, float(region.radius) - 6.0)) & (dist <= float(region.radius) + 6.0)
        if ring.any():
            ring_strength = float(np.percentile(diff[ring], 95))
    edge_artifacts_ok = ring_strength <= 130.0
    if not edge_artifacts_ok:
        issues.append("edge_artifact_risk")

    frame_max_delta, frame_mean_delta = _frame_integrity_metrics(
        cover_arr=cover_arr,
        comp_arr=comp_arr,
        region=region,
    )
    frame_pixels_ok = frame_max_delta <= 3.0
    if not frame_pixels_ok:
        issues.append("frame_pixels_changed")

    return CompositeValidation(
        output_path=str(output_path),
        valid=bool(
            dimensions_ok
            and dpi_ok
            and file_size_ok
            and alignment_ok
            and border_bleed_ok
            and edge_artifacts_ok
            and frame_pixels_ok
        ),
        issues=issues,
        dimensions_ok=bool(dimensions_ok),
        dpi_ok=bool(dpi_ok),
        file_size_ok=bool(file_size_ok),
        alignment_ok=bool(alignment_ok),
        border_bleed_ok=bool(border_bleed_ok),
        edge_artifacts_ok=bool(edge_artifacts_ok),
        metrics={
            "dpi_x": round(dpi_x, 3),
            "dpi_y": round(dpi_y, 3),
            "file_size_kb": round(file_size_kb, 3),
            "alignment_distance_px": round(alignment_distance, 3),
            "alignment_tolerance_px": round(float(tolerance), 3),
            "border_bleed_ratio": round(bleed_ratio, 6),
            "edge_ring_strength": round(ring_strength, 3),
            "frame_pixel_max_delta": round(frame_max_delta, 6),
            "frame_pixel_mean_delta": round(frame_mean_delta, 6),
        },
    )


def batch_composite(
    input_dir: Path,
    generated_dir: Path,
    output_dir: Path,
    regions_path: Path,
    *,
    book_numbers: list[int] | None = None,
    max_books: int = 20,
    catalog_path: Path = config.BOOK_CATALOG_PATH,
) -> dict[str, Any]:
    """Composite all generated books with error isolation."""
    ensure_frame_overlays_exist(input_dir=input_dir, catalog_path=catalog_path)
    regions = safe_json.load_json(regions_path, {})
    generated_books = sorted(
        [int(path.name) for path in generated_dir.iterdir() if path.is_dir() and path.name.isdigit()]
    )

    if book_numbers:
        target_books = [b for b in generated_books if b in set(book_numbers)]
    else:
        target_books = generated_books[:max_books]

    summary = {
        "processed_books": 0,
        "success_books": 0,
        "failed_books": 0,
        "outputs": 0,
        "errors": [],
    }

    for book_number in target_books:
        summary["processed_books"] += 1
        try:
            outputs = composite_all_variants(
                book_number=book_number,
                input_dir=input_dir,
                generated_dir=generated_dir,
                output_dir=output_dir,
                regions=regions,
                catalog_path=catalog_path,
            )
            summary["success_books"] += 1
            summary["outputs"] += len(outputs)
        except Exception as exc:  # pragma: no cover - defensive
            summary["failed_books"] += 1
            summary["errors"].append({"book_number": book_number, "error": str(exc)})
            logger.error("Compositing failed for book %s: %s", book_number, exc)

    try:
        if VERIFY_COMPOSITE_SCRIPT.exists():
            subprocess.run([sys.executable, str(VERIFY_COMPOSITE_SCRIPT)], check=False, timeout=300)
    except Exception:
        pass

    return summary


def _region_from_dict(region: dict[str, Any]) -> Region:
    bbox = region.get("frame_bbox", [0, 0, 0, 0])
    rect = region.get("rect_bbox")
    rect_bbox = None
    if isinstance(rect, list) and len(rect) == 4:
        rect_bbox = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))

    return Region(
        center_x=int(region.get("center_x", 0)),
        center_y=int(region.get("center_y", 0)),
        radius=int(region.get("radius", 0)),
        frame_bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
        region_type=str(region.get("region_type", "circle") or "circle"),
        rect_bbox=rect_bbox,
        mask_path=str(region.get("mask_path", "") or "") or None,
    )


def _strip_border(image: Image.Image, border_percent: float = 0.05) -> Image.Image:
    """Crop a symmetric outer strip to remove AI-added frame/border artifacts."""
    base_percent = max(0.0, min(0.20, float(border_percent or 0.0)))
    adaptive_extra = _adaptive_border_strip_percent(image)
    # Cap total strip at 12% to avoid over-cropping that can reveal white gaps.
    percent = max(0.0, min(0.12, base_percent + adaptive_extra))
    if percent <= 0:
        return image
    width, height = image.size
    crop_x = int(width * percent)
    crop_y = int(height * percent)
    if crop_x <= 0 and crop_y <= 0:
        return image
    left = max(0, crop_x)
    top = max(0, crop_y)
    right = min(width, width - crop_x)
    bottom = min(height, height - crop_y)
    if right <= left or bottom <= top:
        return image
    cropped = image.crop((left, top, right, bottom))
    return cropped


def _adaptive_border_strip_percent(image: Image.Image) -> float:
    rgb = np.array(image.convert("RGB"), dtype=np.float32)
    if rgb.size == 0:
        return 0.0
    gray = rgb.mean(axis=2)
    h, w = gray.shape[:2]
    if h < 24 or w < 24:
        return 0.0

    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    edge_map = np.pad(dx, ((0, 0), (0, 1)), mode="constant") + np.pad(dy, ((0, 1), (0, 0)), mode="constant")
    if float(edge_map.max()) < 2.0:
        return 0.0

    margin = max(6, int(min(h, w) * 0.14))
    yy, xx = np.ogrid[:h, :w]
    outer_mask = (xx < margin) | (xx >= w - margin) | (yy < margin) | (yy >= h - margin)
    center_mask = (xx >= int(w * 0.30)) & (xx <= int(w * 0.70)) & (yy >= int(h * 0.30)) & (yy <= int(h * 0.70))

    outer_vals = edge_map[outer_mask]
    center_vals = edge_map[center_mask]
    if outer_vals.size == 0 or center_vals.size == 0:
        return 0.0

    outer_strength = float(np.percentile(outer_vals, 90))
    center_strength = float(np.percentile(center_vals, 90))
    strength_ratio = outer_strength / max(1e-6, center_strength)

    threshold = float(np.percentile(edge_map, 97))
    strong = edge_map >= threshold
    outer_density = float(strong[outer_mask].mean())
    center_density = float(strong[center_mask].mean())
    density_ratio = outer_density / max(1e-6, center_density + 1e-6)

    row_fill = strong.mean(axis=1)
    col_fill = strong.mean(axis=0)
    top_peak = float(row_fill[: max(2, int(h * 0.20))].max(initial=0.0))
    bottom_peak = float(row_fill[min(h - 1, int(h * 0.80)) :].max(initial=0.0))
    left_peak = float(col_fill[: max(2, int(w * 0.20))].max(initial=0.0))
    right_peak = float(col_fill[min(w - 1, int(w * 0.80)) :].max(initial=0.0))
    boundary_peak = (top_peak + bottom_peak + left_peak + right_peak) / 4.0

    artifact_score = (
        0.55 * _clip((strength_ratio - 1.25) / 1.55)
        + 0.25 * _clip((density_ratio - 1.45) / 2.30)
        + 0.20 * _clip((boundary_peak - 0.17) / 0.32)
    )
    return 0.10 * _clip(artifact_score)


def _paste_centered(*, canvas: Image.Image, overlay: Image.Image, center_x: int, center_y: int) -> None:
    """Paste overlay so its center aligns exactly to the requested coordinates."""
    paste_x = int(center_x) - int(overlay.width // 2)
    paste_y = int(center_y) - int(overlay.height // 2)
    if overlay.mode == "RGBA":
        canvas.paste(overlay, (paste_x, paste_y), overlay)
    else:
        canvas.paste(overlay, (paste_x, paste_y))


def _build_circle_feather_mask(
    *,
    width: int,
    height: int,
    center_x: int,
    center_y: int,
    radius: int,
    feather_px: int,
) -> Image.Image:
    yy, xx = np.ogrid[:height, :width]
    dist = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)

    alpha = np.zeros((height, width), dtype=np.float32)
    inner = radius - feather_px
    alpha[dist <= inner] = 255.0

    feather_zone = (dist > inner) & (dist <= radius)
    alpha[feather_zone] = np.clip((radius - dist[feather_zone]) / max(1, feather_px) * 255.0, 0, 255)
    return Image.fromarray(alpha.astype(np.uint8), mode="L")


def _build_rect_feather_mask(*, width: int, height: int, bbox: tuple[int, int, int, int], feather_px: int) -> Image.Image:
    x1, y1, x2, y2 = bbox
    alpha = np.zeros((height, width), dtype=np.float32)
    alpha[y1:y2, x1:x2] = 255.0

    # Soft edge feather.
    for step in range(1, max(1, feather_px) + 1):
        value = max(0.0, 255.0 * (1.0 - (step / max(1, feather_px))))
        alpha[max(0, y1 - step):y1, max(0, x1 - step):min(width, x2 + step)] = np.maximum(
            alpha[max(0, y1 - step):y1, max(0, x1 - step):min(width, x2 + step)], value
        )
        alpha[y2:min(height, y2 + step), max(0, x1 - step):min(width, x2 + step)] = np.maximum(
            alpha[y2:min(height, y2 + step), max(0, x1 - step):min(width, x2 + step)], value
        )
        alpha[max(0, y1 - step):min(height, y2 + step), max(0, x1 - step):x1] = np.maximum(
            alpha[max(0, y1 - step):min(height, y2 + step), max(0, x1 - step):x1], value
        )
        alpha[max(0, y1 - step):min(height, y2 + step), x2:min(width, x2 + step)] = np.maximum(
            alpha[max(0, y1 - step):min(height, y2 + step), x2:min(width, x2 + step)], value
        )

    return Image.fromarray(np.clip(alpha, 0, 255).astype(np.uint8), mode="L")


def _load_custom_mask(mask_path: str, size: tuple[int, int]) -> Image.Image:
    candidate = Path(mask_path)
    if not candidate.is_absolute():
        candidate = config.PROJECT_ROOT / candidate
    if not candidate.exists():
        logger.warning("Custom mask path missing: %s", candidate)
        return Image.new("L", size, 255)

    mask = Image.open(candidate).convert("L")
    if mask.size != size:
        mask = mask.resize(size, Image.LANCZOS)
    return mask


def _load_global_compositing_mask(size: tuple[int, int]) -> Image.Image | None:
    if tuple(size) != (3784, 2777):
        return None
    candidate = config.CONFIG_DIR / "compositing_mask.png"
    if not candidate.exists():
        return None
    try:
        mask_rgba = Image.open(candidate).convert("RGBA")
    except Exception:
        logger.warning("Failed to read compositing mask at %s", candidate)
        return None
    if mask_rgba.size != size:
        mask_rgba = mask_rgba.resize(size, Image.LANCZOS)
    alpha = mask_rgba.split()[-1]
    # Ignore malformed masks that are fully opaque or fully transparent.
    arr = np.array(alpha, dtype=np.uint8)
    if int(arr.max()) <= 1 or int(arr.min()) >= 254:
        return None
    return alpha


def _load_frame_overlay(cover_path: Path, size: tuple[int, int]) -> Image.Image | None:
    """Load pre-extracted RGBA frame overlay for a specific source cover."""
    overlay_dir = FRAME_OVERLAY_DIR
    stem = cover_path.stem
    candidate = overlay_dir / f"{stem}_frame.png"

    if not candidate.exists():
        nums = re.findall(r"\d+", stem)
        if nums:
            wanted = nums[-1]
            for fp in sorted(overlay_dir.glob("*_frame.png")):
                fp_nums = re.findall(r"\d+", fp.stem)
                if fp_nums and fp_nums[-1] == wanted:
                    candidate = fp
                    break

    if not candidate.exists():
        return None

    try:
        overlay = Image.open(candidate).convert("RGBA")
    except Exception:
        logger.warning("Failed to load frame overlay %s", candidate)
        return None
    if overlay.size != size:
        overlay = overlay.resize(size, Image.LANCZOS)

    alpha = np.array(overlay.split()[-1], dtype=np.uint8)
    if int(alpha.max()) <= 5 or int(alpha.min()) >= 250:
        logger.warning("Frame overlay alpha is trivial, ignoring %s", candidate)
        return None
    return overlay


def _build_fallback_frame_overlay(
    *,
    cover: Image.Image,
    center_x: int,
    center_y: int,
    punch_radius: int,
) -> Image.Image:
    """Build RGBA overlay from cover + frame_mask.png (fallback path)."""
    cover_rgba = cover.convert("RGBA")
    w, h = cover_rgba.size

    frame_mask = _load_frame_mask((w, h))
    if frame_mask is not None:
        cover_rgba.putalpha(frame_mask)
        return cover_rgba

    scale = 4
    mask_large = Image.new("L", (w * scale, h * scale), 255)
    draw = ImageDraw.Draw(mask_large)
    cx_s, cy_s, r_s = center_x * scale, center_y * scale, punch_radius * scale
    draw.ellipse((cx_s - r_s, cy_s - r_s, cx_s + r_s, cy_s + r_s), fill=0)
    cover_rgba.putalpha(mask_large.resize((w, h), Image.LANCZOS))
    return cover_rgba


def ensure_frame_overlays_exist(*, input_dir: Path, catalog_path: Path) -> None:
    """Lazy extraction gate for frame overlays; runs once per process if needed."""
    global _FRAME_OVERLAY_EXTRACTION_ATTEMPTED
    if _FRAME_OVERLAY_EXTRACTION_ATTEMPTED:
        return
    _FRAME_OVERLAY_EXTRACTION_ATTEMPTED = True

    FRAME_OVERLAY_DIR.mkdir(parents=True, exist_ok=True)

    catalog = _load_catalog(catalog_path)
    missing = 0
    expected = 0
    for entry in catalog:
        folder_name = str(entry.get("folder_name", "")).strip()
        if not folder_name:
            continue
        folder = input_dir / folder_name
        jpgs = sorted([p for p in folder.glob("*") if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}])
        if not jpgs:
            continue
        expected += 1
        overlay_path = FRAME_OVERLAY_DIR / f"{jpgs[0].stem}_frame.png"
        if not overlay_path.exists():
            missing += 1

    if expected == 0:
        logger.warning("No catalog source JPGs found for frame overlay extraction")
        return
    if missing == 0:
        logger.info("Frame overlays already present for all %d covers", expected)
        return
    if not FRAME_OVERLAY_SCRIPT.exists():
        logger.warning("Frame overlay extraction script missing: %s", FRAME_OVERLAY_SCRIPT)
        return

    logger.info("Frame overlays missing for %d/%d covers; running extraction", missing, expected)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(FRAME_OVERLAY_SCRIPT),
                "--input-dir",
                str(input_dir),
                "--catalog-path",
                str(catalog_path),
                "--overlay-dir",
                str(FRAME_OVERLAY_DIR),
                "--frame-mask",
                str(FRAME_MASK_PATH),
            ],
            check=False,
            timeout=1200,
            capture_output=True,
            text=True,
        )
        if proc.stdout.strip():
            logger.info(proc.stdout.strip())
        if proc.returncode != 0:
            logger.warning("Frame overlay extraction exited with code %s", proc.returncode)
            if proc.stderr.strip():
                logger.warning(proc.stderr.strip())
    except Exception as exc:
        logger.warning("Failed to run frame overlay extraction: %s", exc)


def _load_frame_mask(size: tuple[int, int]) -> Image.Image | None:
    """Load config/frame_mask.png as a grayscale alpha mask.

    Returns an 'L' mode image where 255 = frame (opaque) and
    0 = art area (transparent punch). Returns None if unavailable.
    """
    if not FRAME_MASK_PATH.exists():
        logger.warning("frame_mask.png not found at %s", FRAME_MASK_PATH)
        return None
    try:
        mask = Image.open(FRAME_MASK_PATH).convert("L")
    except Exception:
        logger.warning("Failed to load frame mask at %s", FRAME_MASK_PATH)
        return None
    if mask.size != size:
        mask = mask.resize(size, Image.LANCZOS)
    arr = np.array(mask, dtype=np.uint8)
    if int(arr.min()) >= 250 or int(arr.max()) <= 5:
        logger.warning("frame_mask.png appears trivially uniform — ignoring")
        return None
    return mask


def _combine_masks(primary: Image.Image, secondary: Image.Image) -> Image.Image:
    first = np.array(primary.convert("L"), dtype=np.uint8)
    second = np.array(secondary.convert("L"), dtype=np.uint8)
    combined = np.minimum(first, second)
    return Image.fromarray(combined, mode="L")


def _validation_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".validation.json")


def _load_validation_payload(output_path: Path) -> dict[str, Any] | None:
    path = _validation_path(output_path)
    payload = safe_json.load_json(path, None)
    if not isinstance(payload, dict):
        return None
    return payload


def _color_match_illustration(cover: Image.Image, illustration: Image.Image, region: Region) -> Image.Image:
    """Nudge illustration color temperature toward region context."""
    cover_arr = np.array(cover.convert("RGB"), dtype=np.float32)
    ill_arr = np.array(illustration.convert("RGB"), dtype=np.float32)

    yy, xx = np.ogrid[:cover_arr.shape[0], :cover_arr.shape[1]]
    if region.region_type == "rectangle" and region.rect_bbox is not None:
        x1, y1, x2, y2 = region.rect_bbox
        ring = np.zeros((cover_arr.shape[0], cover_arr.shape[1]), dtype=bool)
        ring[max(0, y1 - 30):min(cover_arr.shape[0], y2 + 30), max(0, x1 - 30):min(cover_arr.shape[1], x2 + 30)] = True
        ring[y1:y2, x1:x2] = False
    else:
        dist = np.sqrt((xx - region.center_x) ** 2 + (yy - region.center_y) ** 2)
        ring = (dist >= region.radius - 60) & (dist <= region.radius - 10)

    if not np.any(ring):
        return illustration

    target_mean = cover_arr[ring].mean(axis=0)
    ill_mean = ill_arr.reshape(-1, 3).mean(axis=0)

    scale = np.clip((target_mean + 1.0) / (ill_mean + 1.0), 0.78, 1.22)
    matched = np.clip(ill_arr * scale, 0, 255).astype(np.uint8)

    alpha = np.array(illustration)[..., 3:4] if illustration.mode == "RGBA" else np.full((*matched.shape[:2], 1), 255, dtype=np.uint8)
    rgba = np.concatenate([matched, alpha], axis=2)
    return Image.fromarray(rgba, mode="RGBA")


def _load_catalog(path: Path) -> list[dict[str, Any]]:
    payload = safe_json.load_json(path, [])
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _find_cover_jpg(input_dir: Path, book_number: int, *, catalog_path: Path) -> Path:
    catalog = _load_catalog(catalog_path)
    match = None
    for entry in catalog:
        if int(entry.get("number", 0)) == int(book_number):
            match = entry
            break
    if not match:
        raise KeyError(f"Book {book_number} not found in catalog")

    folder = input_dir / str(match["folder_name"])
    if not folder.exists():
        raise FileNotFoundError(f"Cover folder missing: {folder}")

    jpg_candidates = sorted(folder.glob("*.jpg"))
    if not jpg_candidates:
        raise FileNotFoundError(f"No JPG found in {folder}")
    return jpg_candidates[0]


def _region_for_book(regions_payload: dict[str, Any], book_number: int) -> dict[str, Any]:
    for row in regions_payload.get("covers", []):
        if int(row.get("cover_id", 0)) == int(book_number):
            return row
    return regions_payload.get("consensus_region", {})


def _collect_generated_for_book(generated_dir: Path, book_number: int) -> list[dict[str, Any]]:
    base = generated_dir / str(book_number)
    if not base.exists():
        return []

    rows: list[dict[str, Any]] = []

    for model_dir in sorted([path for path in base.iterdir() if path.is_dir()]):
        if model_dir.name == "history":
            continue
        for image in sorted(model_dir.glob("variant_*.png")):
            variant = _parse_variant(image.stem)
            rows.append({"model": model_dir.name, "variant": variant, "path": image})

    for image in sorted(base.glob("variant_*.png")):
        variant = _parse_variant(image.stem)
        rows.append({"model": "default", "variant": variant, "path": image})

    dedup: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        dedup[(row["model"], row["variant"])] = row

    return sorted(dedup.values(), key=lambda row: (row["model"], row["variant"]))


def _parse_variant(stem: str) -> int:
    if "variant_" not in stem:
        return 0
    token = stem.split("variant_", 1)[1].split("_", 1)[0]
    try:
        return int(token)
    except ValueError:
        return 0


def _parse_books(raw: str | None) -> list[int] | None:
    if not raw:
        return None

    books: set[int] = set()
    for piece in raw.split(","):
        token = piece.strip()
        if not token:
            continue
        if "-" in token:
            start_str, end_str = token.split("-", 1)
            start, end = int(start_str), int(end_str)
            for value in range(min(start, end), max(start, end) + 1):
                books.add(value)
        else:
            books.add(int(token))

    return sorted(books)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 3A cover compositing")
    parser.add_argument("--input-dir", type=Path, default=config.INPUT_DIR)
    parser.add_argument("--generated-dir", type=Path, default=config.TMP_DIR / "generated")
    parser.add_argument("--output-dir", type=Path, default=config.TMP_DIR / "composited")
    parser.add_argument("--regions-path", type=Path, default=config.CONFIG_DIR / "cover_regions.json")
    parser.add_argument("--catalog-path", type=Path, default=config.BOOK_CATALOG_PATH)
    parser.add_argument("--book", type=int, default=None)
    parser.add_argument("--books", type=str, default=None)
    parser.add_argument("--max-books", type=int, default=20)

    args = parser.parse_args()
    regions = safe_json.load_json(args.regions_path, {})

    if args.book is not None:
        outputs = composite_all_variants(
            book_number=args.book,
            input_dir=args.input_dir,
            generated_dir=args.generated_dir,
            output_dir=args.output_dir,
            regions=regions,
            catalog_path=args.catalog_path,
        )
        logger.info("Composited %d files for book %s", len(outputs), args.book)
        return 0

    books = _parse_books(args.books)
    summary = batch_composite(
        input_dir=args.input_dir,
        generated_dir=args.generated_dir,
        output_dir=args.output_dir,
        regions_path=args.regions_path,
        book_numbers=books,
        max_books=args.max_books,
        catalog_path=args.catalog_path,
    )
    logger.info("Batch compositing summary: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
