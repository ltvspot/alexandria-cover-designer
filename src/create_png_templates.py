"""Batch-generate PNG templates with transparent medallion centers.

Usage:
    python -m src.create_png_templates [--punch-radius 465] [--source-dir config/covers] [--force]

Each PNG template is a copy of the source cover JPG with the medallion
center punched out (made transparent). These templates are used by the
compositor as the topmost layer, ensuring the ornamental frame is always
on top of the AI-generated artwork.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# --- Configuration ---
TEMPLATE_PUNCH_RADIUS = 465
CENTER_X = 2864
CENTER_Y = 1620
SUPERSAMPLE_FACTOR = 4
TEMPLATE_DIR = Path("config/templates")
SOURCE_DIR = Path("config/covers")
COVER_REGIONS_PATH = Path("config/cover_regions.json")
GDRIVE_SOURCE_FOLDER_ID = "1ybFYDJk7Y3VlbsEjRAh1LOfdyVsHM_cS"


def _extract_numbers(value: str) -> list[str]:
    return re.findall(r"\d+", value or "")


def _load_region_rows() -> list[dict]:
    if not COVER_REGIONS_PATH.exists():
        return []
    try:
        payload = json.loads(COVER_REGIONS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load cover regions from %s: %s", COVER_REGIONS_PATH, exc)
        return []
    if isinstance(payload, dict):
        covers = payload.get("covers", [])
        if isinstance(covers, list):
            return [row for row in covers if isinstance(row, dict)]
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _load_cover_geometry(cover_path: Path, region_rows: list[dict] | None = None) -> tuple[int, int]:
    """Load per-cover center coordinates from cover_regions.json.

    Falls back to default CENTER_X, CENTER_Y if file not found
    or cover not in the JSON.
    """
    rows = region_rows if region_rows is not None else _load_region_rows()
    if not rows:
        return CENTER_X, CENTER_Y

    stem = cover_path.stem
    nums = _extract_numbers(stem)
    rel = cover_path.as_posix()

    # 1) Exact stem match against configured jpg path.
    for row in rows:
        jpg = str(row.get("jpg", "") or "")
        if not jpg:
            continue
        if Path(jpg).stem == stem:
            return int(row.get("center_x", CENTER_X)), int(row.get("center_y", CENTER_Y))

    # 2) Path suffix match.
    for row in rows:
        jpg = str(row.get("jpg", "") or "").replace("\\", "/")
        if jpg and rel.endswith(jpg):
            return int(row.get("center_x", CENTER_X)), int(row.get("center_y", CENTER_Y))

    # 3) Numeric fallback (cover_id or file stem numbers).
    if nums:
        target = nums[-1]
        for row in rows:
            cover_id = str(row.get("cover_id", "") or "")
            if cover_id and cover_id == str(int(target)):
                return int(row.get("center_x", CENTER_X)), int(row.get("center_y", CENTER_Y))
        for row in rows:
            row_stem = Path(str(row.get("jpg", "") or "")).stem
            row_nums = _extract_numbers(row_stem)
            if row_nums and row_nums[-1] == target:
                return int(row.get("center_x", CENTER_X)), int(row.get("center_y", CENTER_Y))

    return CENTER_X, CENTER_Y


def create_template(
    source_path: Path,
    output_path: Path,
    center_x: int = CENTER_X,
    center_y: int = CENTER_Y,
    punch_radius: int = TEMPLATE_PUNCH_RADIUS,
) -> bool:
    """Create a PNG template from a source cover JPG."""
    try:
        with Image.open(source_path) as image:
            cover = image.convert("RGBA")
        width, height = cover.size
        scale = max(1, int(SUPERSAMPLE_FACTOR))
        mask_large = Image.new("L", (width * scale, height * scale), 255)
        draw = ImageDraw.Draw(mask_large)
        cx = int(center_x) * scale
        cy = int(center_y) * scale
        r = int(punch_radius) * scale
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
        mask = mask_large.resize((width, height), Image.LANCZOS)
        cover.putalpha(mask)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cover.save(str(output_path), "PNG")
        return True
    except Exception as exc:
        logger.exception("Failed to create template for %s: %s", source_path, exc)
        return False


def process_all_covers(
    source_dir: Path = SOURCE_DIR,
    template_dir: Path = TEMPLATE_DIR,
    punch_radius: int = TEMPLATE_PUNCH_RADIUS,
    force: bool = False,
) -> dict:
    """Process all cover JPGs into PNG templates."""
    results = {"created": 0, "skipped": 0, "failed": 0}
    if not source_dir.exists():
        logger.warning(
            "No covers found in %s. Download source covers from Google Drive folder %s or specify --source-dir",
            source_dir,
            GDRIVE_SOURCE_FOLDER_ID,
        )
        return results

    source_files = sorted(
        [
            path
            for path in source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
        ]
    )
    if not source_files:
        logger.warning(
            "No covers found in %s. Download source covers from Google Drive folder %s or specify --source-dir",
            source_dir,
            GDRIVE_SOURCE_FOLDER_ID,
        )
        return results

    template_dir.mkdir(parents=True, exist_ok=True)
    regions = _load_region_rows()

    for source_path in source_files:
        output_name = f"{source_path.stem}_template.png"
        output_path = template_dir / output_name
        if output_path.exists() and not force:
            results["skipped"] += 1
            continue
        center_x, center_y = _load_cover_geometry(source_path, regions)
        ok = create_template(
            source_path=source_path,
            output_path=output_path,
            center_x=center_x,
            center_y=center_y,
            punch_radius=int(punch_radius),
        )
        if ok:
            logger.info("Created template: %s", output_path.name)
            results["created"] += 1
        else:
            results["failed"] += 1

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate PNG templates with transparent medallion centers.")
    parser.add_argument(
        "--punch-radius",
        type=int,
        default=TEMPLATE_PUNCH_RADIUS,
        help=f"Radius of transparent circle (default: {TEMPLATE_PUNCH_RADIUS})",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=SOURCE_DIR,
        help=f"Directory with source cover JPGs (default: {SOURCE_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate templates even if they already exist",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    results = process_all_covers(
        source_dir=args.source_dir,
        template_dir=TEMPLATE_DIR,
        punch_radius=args.punch_radius,
        force=bool(args.force),
    )
    logger.info(
        "Done: %s created, %s skipped, %s failed",
        results["created"],
        results["skipped"],
        results["failed"],
    )
    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
