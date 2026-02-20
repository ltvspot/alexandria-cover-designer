"""Prompt 3B export pipeline: JPG, PDF, and AI deliverables."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from PIL import Image

try:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    REPORTLAB_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency fallback
    REPORTLAB_AVAILABLE = False

try:
    from src import config
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def inspect_ai_internal_format(ai_path: Path) -> dict[str, Any]:
    """Inspect AI file signature to determine if it is PDF-based."""
    if not ai_path.exists():
        raise FileNotFoundError(f"AI file not found: {ai_path}")

    header = ai_path.read_bytes()[:4096]
    is_pdf = header.startswith(b"%PDF") or b"%PDF" in header[:1024]

    return {
        "path": str(ai_path),
        "is_pdf_based": bool(is_pdf),
        "signature_hex": header[:16].hex(),
    }


def export_jpg(composited_image_path: Path, output_path: Path, dpi: int = 300) -> Path:
    """Export image as JPG at print-ready settings."""
    image = Image.open(composited_image_path).convert("RGB")
    if image.size != (3784, 2777):
        image = image.resize((3784, 2777), Image.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=95, subsampling=0, dpi=(dpi, dpi))
    return output_path


def export_pdf(composited_image_path: Path, output_path: Path, dpi: int = 300) -> Path:
    """Export image to single-page print PDF."""
    image = Image.open(composited_image_path).convert("RGB")
    if image.size != (3784, 2777):
        image = image.resize((3784, 2777), Image.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if REPORTLAB_AVAILABLE:
        width_px, height_px = image.size
        page_width = width_px * 72.0 / dpi
        page_height = height_px * 72.0 / dpi
        c = canvas.Canvas(str(output_path), pagesize=(page_width, page_height), pageCompression=0)
        c.setTitle(composited_image_path.stem)
        c.drawImage(ImageReader(image), 0, 0, width=page_width, height=page_height, preserveAspectRatio=True, mask='auto')
        c.showPage()
        c.save()
    else:
        # Pillow fallback when reportlab is unavailable.
        image.save(output_path, format="PDF", resolution=dpi)
    return output_path


def export_ai(composited_image_path: Path, output_path: Path) -> Path:
    """Export Illustrator-compatible PDF content with .ai extension."""
    temp_pdf = output_path.parent / f"{output_path.stem}.__ai_temp__.pdf"
    export_pdf(composited_image_path, temp_pdf, dpi=300)

    # AI-compatible approach: PDF payload with AI extension.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(temp_pdf.read_bytes())
    temp_pdf.unlink(missing_ok=True)
    return output_path


def export_variant(composited_image_path: Path, variant_dir: Path, base_filename: str) -> list[Path]:
    """Export JPG/PDF/AI for one composited variant."""
    variant_dir.mkdir(parents=True, exist_ok=True)

    jpg_path = variant_dir / f"{base_filename}.jpg"
    pdf_path = variant_dir / f"{base_filename}.pdf"
    ai_path = variant_dir / f"{base_filename}.ai"

    export_jpg(composited_image_path, jpg_path)
    export_pdf(composited_image_path, pdf_path)
    export_ai(composited_image_path, ai_path)

    return [ai_path, jpg_path, pdf_path]


def export_book_variants(
    *,
    book_number: int,
    composited_root: Path,
    output_root: Path,
    catalog_path: Path = config.BOOK_CATALOG_PATH,
) -> list[Path]:
    """Export all composited variants for one book to final folder structure."""
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    book_entry = next((row for row in catalog if int(row.get("number", 0)) == int(book_number)), None)
    if not book_entry:
        raise KeyError(f"Book {book_number} missing from catalog")

    folder_name = str(book_entry["folder_name"])
    if folder_name.endswith(" copy"):
        folder_name = folder_name[:-5]
    file_base = str(book_entry["file_base"])

    composited_dir = composited_root / str(book_number)
    if not composited_dir.exists():
        raise FileNotFoundError(f"Composited folder not found: {composited_dir}")

    variant_images = sorted(composited_dir.glob("variant_*.jpg"), key=lambda p: _parse_variant(p.stem))
    if not variant_images:
        variant_images = _fallback_collect_variant_images(composited_dir)

    output_paths: list[Path] = []
    final_book_dir = output_root / folder_name

    for image in variant_images:
        variant_number = _parse_variant(image.stem)
        if variant_number <= 0:
            continue
        variant_dir = final_book_dir / f"Variant-{variant_number}"
        output_paths.extend(export_variant(image, variant_dir, file_base))

    return output_paths


def batch_export(
    *,
    composited_root: Path,
    output_root: Path,
    books: list[int] | None = None,
    max_books: int = 20,
) -> dict[str, Any]:
    """Batch export with D23 default scope (20 books)."""
    available_books = sorted(
        int(path.name) for path in composited_root.iterdir() if path.is_dir() and path.name.isdigit()
    )

    if books:
        selected = [book for book in available_books if book in set(books)]
    else:
        selected = available_books[:max_books]

    summary = {
        "processed_books": 0,
        "success_books": 0,
        "failed_books": 0,
        "files_exported": 0,
        "errors": [],
    }

    for book_number in selected:
        summary["processed_books"] += 1
        try:
            exported = export_book_variants(
                book_number=book_number,
                composited_root=composited_root,
                output_root=output_root,
            )
            summary["success_books"] += 1
            summary["files_exported"] += len(exported)
        except Exception as exc:  # pragma: no cover - defensive
            summary["failed_books"] += 1
            summary["errors"].append({"book_number": book_number, "error": str(exc)})
            logger.error("Export failed for book %s: %s", book_number, exc)

    return summary


def _fallback_collect_variant_images(composited_dir: Path) -> list[Path]:
    """Fallback for model-grouped composited outputs (no default variant files)."""
    grouped = sorted(composited_dir.glob("*/variant_*.jpg"), key=lambda p: (p.parent.name, _parse_variant(p.stem)))
    selected: list[Path] = []
    used_variants: set[int] = set()

    for path in grouped:
        variant = _parse_variant(path.stem)
        if variant <= 0 or variant in used_variants:
            continue
        selected.append(path)
        used_variants.add(variant)
        if len(selected) >= 5:
            break

    return selected


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

    values: set[int] = set()
    for piece in raw.split(","):
        token = piece.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            for value in range(min(int(start), int(end)), max(int(start), int(end)) + 1):
                values.add(value)
        else:
            values.add(int(token))
    return sorted(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 3B output exporter")
    parser.add_argument("--composited-root", type=Path, default=config.TMP_DIR / "composited")
    parser.add_argument("--output-root", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--book", type=int, default=None)
    parser.add_argument("--books", type=str, default=None)
    parser.add_argument("--max-books", type=int, default=20)
    parser.add_argument("--inspect-ai", type=Path, default=None)

    args = parser.parse_args()

    if args.inspect_ai:
        info = inspect_ai_internal_format(args.inspect_ai)
        print(json.dumps(info, indent=2))
        return 0

    if args.book is not None:
        exported = export_book_variants(
            book_number=args.book,
            composited_root=args.composited_root,
            output_root=args.output_root,
        )
        logger.info("Exported %d files for book %s", len(exported), args.book)
        return 0

    summary = batch_export(
        composited_root=args.composited_root,
        output_root=args.output_root,
        books=_parse_books(args.books),
        max_books=args.max_books,
    )
    logger.info("Batch export summary: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
