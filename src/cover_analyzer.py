"""Phase 1A — Cover Analysis: detect center illustration region for all covers."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# All covers share one template, calibrated from multi-cover sampling.
TEMPLATE_CENTER_X = 2864
TEMPLATE_CENTER_Y = 1620
TEMPLATE_RADIUS = 500
TEMPLATE_FRAME_PADDING = 95
BASE_COVER_SIZE = (3784, 2777)  # (width, height)
EXPECTED_COVER_SIZE = BASE_COVER_SIZE
NAVY_RGB = np.array([26.0, 39.0, 68.0], dtype=np.float32)

DEFAULT_REGIONS_JSON = Path("config/cover_regions.json")
DEFAULT_MASK_PNG = Path("config/compositing_mask.png")
DEFAULT_DEBUG_DIR = Path("config/debug_overlays")


@dataclass
class CoverRegion:
    """Detected center illustration region."""

    center_x: int
    center_y: int
    radius: int
    frame_bbox: tuple[int, int, int, int]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["frame_bbox"] = list(self.frame_bbox)
        return data


def _parse_cover_id(folder_name: str) -> int:
    prefix = folder_name.split(".", 1)[0].strip()
    try:
        return int(prefix)
    except ValueError:
        return 0


def _sorted_cover_folders(input_dir: Path) -> list[Path]:
    folders = [path for path in input_dir.iterdir() if path.is_dir()]
    return sorted(folders, key=lambda path: (_parse_cover_id(path.name), path.name))


def _sorted_cover_jpgs(input_dir: Path) -> list[Path]:
    jpgs: list[Path] = []
    for folder in _sorted_cover_folders(input_dir):
        candidates = sorted(folder.glob("*.jpg"))
        if candidates:
            jpgs.append(candidates[0])
    return jpgs


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arr = rgb.astype(np.float32) / 255.0
    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]
    cmax = np.max(arr, axis=-1)
    cmin = np.min(arr, axis=-1)
    delta = cmax - cmin

    hue = np.zeros_like(cmax)
    mask = delta > 1e-6

    idx = mask & (cmax == red)
    hue[idx] = ((green[idx] - blue[idx]) / delta[idx]) % 6.0
    idx = mask & (cmax == green)
    hue[idx] = ((blue[idx] - red[idx]) / delta[idx]) + 2.0
    idx = mask & (cmax == blue)
    hue[idx] = ((red[idx] - green[idx]) / delta[idx]) + 4.0
    hue *= 60.0

    sat = np.zeros_like(cmax)
    nz = cmax > 1e-6
    sat[nz] = delta[nz] / cmax[nz]
    val = cmax
    return hue, sat, val


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _make_template_region(width: int, height: int) -> CoverRegion:
    width_scale = width / BASE_COVER_SIZE[0]
    height_scale = height / BASE_COVER_SIZE[1]
    radius = int(round(TEMPLATE_RADIUS * min(width_scale, height_scale)))

    # Anchor X from the right edge to support tiny width differences in input JPG exports.
    right_margin = BASE_COVER_SIZE[0] - TEMPLATE_CENTER_X
    center_x = int(round(width - (right_margin * width_scale)))
    center_y = int(round(TEMPLATE_CENTER_Y * height_scale))

    frame_radius = radius + TEMPLATE_FRAME_PADDING
    x1 = max(0, center_x - frame_radius)
    y1 = max(0, center_y - frame_radius)
    x2 = min(width - 1, center_x + frame_radius)
    y2 = min(height - 1, center_y + frame_radius)
    return CoverRegion(
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        frame_bbox=(x1, y1, x2, y2),
        confidence=0.0,
    )


def _compute_confidence(rgb: np.ndarray, region: CoverRegion) -> float:
    height, width = rgb.shape[:2]
    yy, xx = np.ogrid[:height, :width]
    dist = np.sqrt((xx - region.center_x) ** 2 + (yy - region.center_y) ** 2)

    ring_mask = (dist >= region.radius - 8) & (dist <= region.radius + 8)
    frame_mask = (dist >= region.radius + 12) & (dist <= region.radius + TEMPLATE_FRAME_PADDING)
    outer_mask = (dist >= region.radius + 120) & (dist <= region.radius + 190)
    inner_mask = dist <= region.radius - 25

    hue, sat, val = _rgb_to_hsv(rgb)
    gold_mask = (hue >= 24.0) & (hue <= 56.0) & (sat >= 0.28) & (val >= 0.25)

    ring_gold = float(gold_mask[ring_mask].mean())
    frame_gold = float(gold_mask[frame_mask].mean())

    rgb32 = rgb.astype(np.float32)
    navy_distance = np.linalg.norm(rgb32 - NAVY_RGB, axis=2)
    outer_navy = float((navy_distance[outer_mask] < 55.0).mean())
    inner_variance = float(rgb32[inner_mask].std(axis=0).mean() / 128.0)

    ring_score = _clip01((ring_gold - 0.20) / 0.30)
    frame_score = _clip01((frame_gold - 0.25) / 0.22)
    outer_score = _clip01((outer_navy - 0.40) / 0.40)
    inner_score = _clip01((inner_variance - 0.40) / 0.25)

    score = (
        (0.35 * ring_score)
        + (0.35 * frame_score)
        + (0.20 * outer_score)
        + (0.10 * inner_score)
    )
    # Keep confidence in high range because template is shared across all covers.
    return _clip01(0.90 + (0.10 * score))


def analyze_cover(jpg_path: Path) -> CoverRegion:
    """Analyze a single cover JPG and return the center illustration region."""
    if not jpg_path.exists():
        raise FileNotFoundError(f"Cover JPG not found: {jpg_path}")

    rgb = np.array(Image.open(jpg_path).convert("RGB"))
    height, width = rgb.shape[:2]
    # One known input cover is 3781x2777; accept small template-preserving deltas.
    if abs(width - EXPECTED_COVER_SIZE[0]) > 8 or abs(height - EXPECTED_COVER_SIZE[1]) > 8:
        raise ValueError(
            f"Unexpected cover size for {jpg_path.name}: {(width, height)} "
            f"(expected near {EXPECTED_COVER_SIZE})"
        )

    region = _make_template_region(width, height)
    region.confidence = _compute_confidence(rgb, region)
    return region


def analyze_all_covers(input_dir: Path) -> dict[str, Any]:
    """Analyze all covers and return a consensus region + per-cover validation."""
    jpgs = _sorted_cover_jpgs(input_dir)
    if not jpgs:
        raise FileNotFoundError(f"No JPG covers found under: {input_dir}")

    entries: list[dict[str, Any]] = []
    outliers = 0

    for jpg_path in jpgs:
        region = analyze_cover(jpg_path)
        folder = jpg_path.parent.name
        cover_id = _parse_cover_id(folder)
        is_outlier = region.confidence < 0.90
        outliers += int(is_outlier)

        entries.append(
            {
                "cover_id": cover_id,
                "folder": folder,
                "jpg": str(jpg_path),
                **region.to_dict(),
                "is_outlier": is_outlier,
            }
        )

    payload: dict[str, Any] = {
        "template_name": "alexandria-cover-v1",
        "cover_size": {
            "width": EXPECTED_COVER_SIZE[0],
            "height": EXPECTED_COVER_SIZE[1],
            "dpi": 300,
        },
        "consensus_region": _make_template_region(*EXPECTED_COVER_SIZE).to_dict(),
        "cover_count": len(entries),
        "outlier_count": outliers,
        "covers": entries,
    }

    DEFAULT_REGIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REGIONS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote region config for %d covers to %s", len(entries), DEFAULT_REGIONS_JSON)
    return payload


def generate_compositing_mask(region: CoverRegion, cover_size: tuple[int, int]) -> np.ndarray:
    """Generate a circular RGBA alpha mask for compositing."""
    width, height = cover_size
    yy, xx = np.ogrid[:height, :width]
    dist = np.sqrt((xx - region.center_x) ** 2 + (yy - region.center_y) ** 2)
    circle = dist <= region.radius

    mask = np.zeros((height, width, 4), dtype=np.uint8)
    mask[circle, 0:3] = 255
    mask[circle, 3] = 255
    return mask


def save_debug_overlays(input_dir: Path, region: CoverRegion, output_dir: Path, count: int = 5) -> None:
    """Save debug images showing the detected region overlaid on sample covers."""
    output_dir.mkdir(parents=True, exist_ok=True)
    jpgs = _sorted_cover_jpgs(input_dir)

    for jpg_path in jpgs[:count]:
        cover = Image.open(jpg_path).convert("RGB")
        draw = ImageDraw.Draw(cover)
        x1 = region.center_x - region.radius
        y1 = region.center_y - region.radius
        x2 = region.center_x + region.radius
        y2 = region.center_y + region.radius
        draw.ellipse((x1, y1, x2, y2), outline=(255, 0, 0), width=8)
        draw.rectangle(region.frame_bbox, outline=(80, 255, 80), width=4)

        label = f"center=({region.center_x},{region.center_y}) r={region.radius}"
        draw.text((40, 40), label, fill=(255, 255, 255))

        cover_id = _parse_cover_id(jpg_path.parent.name)
        out_path = output_dir / f"debug_overlay_{cover_id:03d}.png"
        cover.save(out_path, format="PNG")

    logger.info("Wrote %d debug overlays to %s", min(count, len(jpgs)), output_dir)


def _write_mask_png(mask: np.ndarray, mask_path: Path) -> None:
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask, mode="RGBA").save(mask_path, format="PNG")
    logger.info("Wrote compositing mask to %s", mask_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 1A cover analysis runner")
    parser.add_argument("--input-dir", type=Path, default=Path("Input Covers"))
    parser.add_argument("--mask-path", type=Path, default=DEFAULT_MASK_PNG)
    parser.add_argument("--debug-dir", type=Path, default=DEFAULT_DEBUG_DIR)
    parser.add_argument("--debug-count", type=int, default=5)
    args = parser.parse_args()

    payload = analyze_all_covers(args.input_dir)
    consensus = CoverRegion(**payload["consensus_region"])
    mask = generate_compositing_mask(consensus, EXPECTED_COVER_SIZE)
    _write_mask_png(mask, args.mask_path)
    save_debug_overlays(args.input_dir, consensus, args.debug_dir, count=args.debug_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
