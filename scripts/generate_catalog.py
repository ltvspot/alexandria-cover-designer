#!/usr/bin/env python3
"""Prompt 5 catalog generator: build final Alexandria lookbook PDF."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "Output Covers"
DEFAULT_SELECTIONS = PROJECT_ROOT / "data" / "variant_selections.json"
DEFAULT_CATALOG = PROJECT_ROOT / "config" / "book_catalog.json"
DEFAULT_QUALITY_SCORES = PROJECT_ROOT / "data" / "quality_scores.json"
DEFAULT_PDF_PATH = DEFAULT_OUTPUT_ROOT / "Alexandria-Cover-Catalog.pdf"

PAGE_SIZE = (2480, 3508)  # A4 at 300dpi
MARGIN = 120
GRID_COLS = 2
GRID_ROWS = 2
COVERS_PER_PAGE = GRID_COLS * GRID_ROWS
TOC_LINES_PER_PAGE = 44


def generate_catalog_pdf(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    selections_path: Path = DEFAULT_SELECTIONS,
    catalog_path: Path = DEFAULT_CATALOG,
    quality_scores_path: Path = DEFAULT_QUALITY_SCORES,
    output_pdf: Path = DEFAULT_PDF_PATH,
) -> Path:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    selections = _load_json_or_empty(selections_path)
    quality_scores = _load_json_or_empty(quality_scores_path)

    winners = _resolve_winners(catalog, output_root, selections)

    pages: list[Image.Image] = []
    pages.append(_build_cover_page(len(winners)))

    toc_pages = _build_toc_pages(winners)
    pages.extend(toc_pages)

    grid_pages = _build_grid_pages(winners)
    pages.extend(grid_pages)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    pages_rgb = [page.convert("RGB") for page in pages]
    pages_rgb[0].save(
        output_pdf,
        format="PDF",
        save_all=True,
        append_images=pages_rgb[1:],
        resolution=300,
    )

    _write_catalog_stats(output_root, winners, quality_scores)
    return output_pdf


def _resolve_winners(catalog: list[dict[str, Any]], output_root: Path, selections: dict[str, Any]) -> list[dict[str, Any]]:
    winners: list[dict[str, Any]] = []

    for row in sorted(catalog, key=lambda item: int(item.get("number", 0))):
        number = int(row.get("number", 0))
        folder_name = str(row.get("folder_name", ""))
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]

        book_dir = output_root / folder_name
        if not book_dir.exists():
            continue

        selected_variant = int(selections.get(str(number), 0) or 0)
        if selected_variant <= 0:
            selected_variant = _first_available_variant(book_dir)
        if selected_variant <= 0:
            continue

        variant_dir = book_dir / f"Variant-{selected_variant}"
        file_base = str(row.get("file_base", "")).strip()
        image_path = variant_dir / f"{file_base}.jpg"
        if not image_path.exists():
            fallback = sorted(variant_dir.glob("*.jpg"))
            if not fallback:
                continue
            image_path = fallback[0]

        winners.append(
            {
                "number": number,
                "title": row.get("title", ""),
                "author": row.get("author", ""),
                "variant": selected_variant,
                "image_path": image_path,
            }
        )

    return winners


def _first_available_variant(book_dir: Path) -> int:
    variants = [p for p in book_dir.iterdir() if p.is_dir() and p.name.startswith("Variant-")]
    if not variants:
        return 0
    parsed = []
    for item in variants:
        try:
            parsed.append(int(item.name.split("-", 1)[1]))
        except ValueError:
            continue
    return min(parsed) if parsed else 0


def _build_cover_page(total_covers: int) -> Image.Image:
    page = Image.new("RGB", PAGE_SIZE, "#102447")
    draw = ImageDraw.Draw(page)

    title_font = _font(110)
    subtitle_font = _font(52)
    body_font = _font(38)

    title = "Alexandria Cover Catalog"
    subtitle = "Winning Variants Lookbook"
    timestamp = datetime.now().strftime("%B %d, %Y")

    draw.text((MARGIN, 900), title, font=title_font, fill="#E8C66C")
    draw.text((MARGIN, 1050), subtitle, font=subtitle_font, fill="#F2E5C9")
    draw.text((MARGIN, 1220), f"Total Covers: {total_covers}", font=body_font, fill="#F2E5C9")
    draw.text((MARGIN, 1280), f"Generated: {timestamp}", font=body_font, fill="#F2E5C9")

    return page


def _build_toc_pages(winners: list[dict[str, Any]]) -> list[Image.Image]:
    if not winners:
        return [Image.new("RGB", PAGE_SIZE, "white")]

    total_grid_pages = math.ceil(len(winners) / COVERS_PER_PAGE)
    toc_pages_count = math.ceil(len(winners) / TOC_LINES_PER_PAGE)
    first_grid_page_number = 1 + toc_pages_count + 1  # cover + toc pages + first grid page index

    lines: list[str] = []
    for idx, item in enumerate(winners):
        page_no = first_grid_page_number + (idx // COVERS_PER_PAGE)
        label = f"{item['number']:>3}. {item['title']} — {item['author']}  ....  p.{page_no}"
        lines.append(label)

    pages: list[Image.Image] = []
    for page_idx in range(toc_pages_count):
        page = Image.new("RGB", PAGE_SIZE, "#f7f3e9")
        draw = ImageDraw.Draw(page)

        title_font = _font(64)
        line_font = _font(30)

        draw.text((MARGIN, 120), "Table of Contents", font=title_font, fill="#1e2a46")

        y = 260
        chunk = lines[page_idx * TOC_LINES_PER_PAGE : (page_idx + 1) * TOC_LINES_PER_PAGE]
        for line in chunk:
            draw.text((MARGIN, y), line, font=line_font, fill="#222")
            y += 66

        footer = f"TOC Page {page_idx + 1} / {toc_pages_count}"
        draw.text((MARGIN, PAGE_SIZE[1] - 100), footer, font=_font(26), fill="#555")
        pages.append(page)

    return pages


def _build_grid_pages(winners: list[dict[str, Any]]) -> list[Image.Image]:
    pages: list[Image.Image] = []
    if not winners:
        return pages

    card_width = (PAGE_SIZE[0] - (MARGIN * 2) - 80) // 2
    card_height = (PAGE_SIZE[1] - (MARGIN * 2) - 220) // 2

    for idx in range(0, len(winners), COVERS_PER_PAGE):
        page = Image.new("RGB", PAGE_SIZE, "#fcfaf6")
        draw = ImageDraw.Draw(page)

        chunk = winners[idx : idx + COVERS_PER_PAGE]

        draw.text((MARGIN, 60), "Winning Covers", font=_font(52), fill="#1e2a46")

        for offset, item in enumerate(chunk):
            row = offset // GRID_COLS
            col = offset % GRID_COLS

            x = MARGIN + col * (card_width + 80)
            y = 160 + row * (card_height + 110)

            _draw_cover_card(page, draw, item, x, y, card_width, card_height)

        page_num = (idx // COVERS_PER_PAGE) + 1
        draw.text((MARGIN, PAGE_SIZE[1] - 80), f"Grid Page {page_num}", font=_font(24), fill="#666")
        pages.append(page)

    return pages


def _draw_cover_card(
    page: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: dict[str, Any],
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    image_path = Path(item["image_path"])
    image = Image.open(image_path).convert("RGB")

    max_img_w = width
    max_img_h = height - 110

    scale = min(max_img_w / image.width, max_img_h / image.height)
    resized = image.resize((int(image.width * scale), int(image.height * scale)), Image.LANCZOS)

    page.paste(resized, (x + (max_img_w - resized.width) // 2, y + 8))

    title = f"{item['number']}. {item['title']}"
    author = item["author"]
    variant = f"Variant {item['variant']}"

    draw.text((x, y + max_img_h + 16), title[:62], font=_font(24), fill="#1e2a46")
    draw.text((x, y + max_img_h + 48), author[:62], font=_font(22), fill="#333")
    draw.text((x, y + max_img_h + 78), variant, font=_font(20), fill="#666")


def _write_catalog_stats(output_root: Path, winners: list[dict[str, Any]], quality_scores: dict[str, Any]) -> None:
    stats_path = output_root / "catalog_stats.json"

    model_counts: dict[str, int] = {}
    rankings = quality_scores.get("scores", []) if isinstance(quality_scores, dict) else []
    for row in rankings:
        model = str(row.get("model", "unknown"))
        model_counts[model] = model_counts.get(model, 0) + 1

    payload = {
        "total_winning_covers": len(winners),
        "generated_at": datetime.now().isoformat(),
        "model_breakdown": model_counts,
    }
    stats_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return {}
    return {}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/System/Library/Fonts/Supplemental/Garamond.ttf",
    ]:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Alexandria winning-cover catalog PDF")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--selections", type=Path, default=DEFAULT_SELECTIONS)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--quality-scores", type=Path, default=DEFAULT_QUALITY_SCORES)
    parser.add_argument("--output-pdf", type=Path, default=DEFAULT_PDF_PATH)

    args = parser.parse_args()
    output = generate_catalog_pdf(
        output_root=args.output_root,
        selections_path=args.selections,
        catalog_path=args.catalog,
        quality_scores_path=args.quality_scores,
        output_pdf=args.output_pdf,
    )
    print(f"Catalog written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
