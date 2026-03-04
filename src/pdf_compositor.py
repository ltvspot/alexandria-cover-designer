"""PDF-based compositor that preserves ornamental frame pixels via source SMask."""

from __future__ import annotations

import re
import shutil
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

try:
    import fitz  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PyMuPDF is required for PDF compositor") from exc

try:
    import pikepdf  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pikepdf is required for PDF compositor") from exc

try:
    from src import config
    from src import safe_json
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import safe_json  # type: ignore
    from logger import get_logger  # type: ignore

logger = get_logger(__name__)

SMASK_FRAME_MIN = 5
SMASK_FRAME_MAX = 250
EXPECTED_DPI = 300
EXPECTED_JPG_SIZE = (3784, 2777)
# Trim generated art edges before fitting into the medallion image stream.
# This reduces border-like artifacts synthesized near image boundaries.
AI_ART_EDGE_TRIM_RATIO = 0.08
# Feather the first non-frame alpha band so high-contrast art edges do not
# read like ornamental side cutouts against semi-transparent frame details.
ART_EDGE_BLEND_MIN = SMASK_FRAME_MAX + 1  # 251
ART_EDGE_BLEND_MAX = 254


def rgb_to_cmyk(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB uint8 array (h,w,3) to CMYK uint8 (h,w,4)."""
    rgb = np.asarray(rgb_array, dtype=np.uint8)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("rgb_to_cmyk expects an (h,w,3) uint8 array")

    r = rgb[:, :, 0].astype(np.float32)
    g = rgb[:, :, 1].astype(np.float32)
    b = rgb[:, :, 2].astype(np.float32)

    c = 255.0 - r
    m = 255.0 - g
    y = 255.0 - b
    k = np.minimum(np.minimum(c, m), y)

    denom = np.maximum(1.0, 255.0 - k)
    c_out = np.where(k >= 255.0, 0.0, ((c - k) / denom) * 255.0)
    m_out = np.where(k >= 255.0, 0.0, ((m - k) / denom) * 255.0)
    y_out = np.where(k >= 255.0, 0.0, ((y - k) / denom) * 255.0)

    out = np.stack(
        [
            np.clip(c_out, 0, 255).astype(np.uint8),
            np.clip(m_out, 0, 255).astype(np.uint8),
            np.clip(y_out, 0, 255).astype(np.uint8),
            np.clip(k, 0, 255).astype(np.uint8),
        ],
        axis=-1,
    )
    return out


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


def _inflate_stream_bytes(stream_obj: Any, *, expected_len: int) -> bytes:
    raw = bytes(stream_obj.read_raw_bytes())
    data: bytes
    try:
        data = zlib.decompress(raw)
    except Exception:
        data = bytes(stream_obj.read_bytes())
    if len(data) != expected_len:
        raise ValueError(f"Decoded stream length mismatch: got {len(data)}, expected {expected_len}")
    return data


def _resolve_im0(page: Any) -> Any:
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


def _load_ai_art_cmyk(*, ai_art_path: Path, width: int, height: int) -> np.ndarray:
    with Image.open(ai_art_path) as source:
        rgb_source = source.convert("RGB")
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
    rgb_arr = np.asarray(rgb, dtype=np.uint8)
    return rgb_to_cmyk(rgb_arr)


def _render_pdf_to_jpg(*, source_pdf: Path, output_jpg: Path, dpi: int = EXPECTED_DPI) -> None:
    output_jpg.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(source_pdf))
    try:
        if doc.page_count <= 0:
            raise ValueError("PDF has no pages")
        page = doc[0]
        scale = float(dpi) / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if image.size != EXPECTED_JPG_SIZE:
            image = image.resize(EXPECTED_JPG_SIZE, Image.LANCZOS)
        image.save(output_jpg, format="JPEG", quality=100, subsampling=0, dpi=(dpi, dpi))
    finally:
        doc.close()


def composite_cover_pdf(
    source_pdf_path: str,
    ai_art_path: str,
    output_pdf_path: str,
    output_jpg_path: str,
    output_ai_path: str | None = None,
) -> dict[str, Any]:
    """Replace PDF medallion illustration while preserving frame pixels + SMask."""
    source_pdf = Path(source_pdf_path)
    art_path = Path(ai_art_path)
    output_pdf = Path(output_pdf_path)
    output_jpg = Path(output_jpg_path)
    output_ai = Path(output_ai_path) if output_ai_path else output_pdf.with_suffix(".ai")

    if not source_pdf.exists():
        raise FileNotFoundError(f"Source PDF not found: {source_pdf}")
    if not art_path.exists():
        raise FileNotFoundError(f"AI art image not found: {art_path}")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_jpg.parent.mkdir(parents=True, exist_ok=True)
    output_ai.parent.mkdir(parents=True, exist_ok=True)

    pdf = pikepdf.Pdf.open(str(source_pdf))
    try:
        if len(pdf.pages) == 0:
            raise ValueError("Source PDF has no pages")
        page = pdf.pages[0]
        im0 = _resolve_im0(page)

        width = int(im0.get("/Width"))
        height = int(im0.get("/Height"))
        if width <= 0 or height <= 0:
            raise ValueError("Invalid Im0 dimensions")

        raw_cmyk = _inflate_stream_bytes(im0, expected_len=width * height * 4)
        source_cmyk = np.frombuffer(raw_cmyk, dtype=np.uint8).reshape(height, width, 4)

        smask_obj = im0.get("/SMask")
        if smask_obj is None:
            raise ValueError("Im0 is missing /SMask")
        smask_raw = _inflate_stream_bytes(smask_obj, expected_len=width * height)
        smask = np.frombuffer(smask_raw, dtype=np.uint8).reshape(height, width)

        ai_cmyk = _load_ai_art_cmyk(ai_art_path=art_path, width=width, height=height)

        # Frame protection: zero AI pixels outside art-safe SMask zone before composite.
        ai_cmyk[smask < SMASK_FRAME_MIN] = [0, 0, 0, 0]
        frame_zone_mask = (smask >= SMASK_FRAME_MIN) & (smask <= SMASK_FRAME_MAX)
        ai_cmyk[frame_zone_mask] = [0, 0, 0, 0]

        composite = ai_cmyk.copy()
        # Preserve source CMYK for all non-opaque SMask pixels (ring + antialiasing).
        preserve_mask = smask <= SMASK_FRAME_MAX
        composite[preserve_mask] = source_cmyk[preserve_mask]
        blend_mask = (smask >= ART_EDGE_BLEND_MIN) & (smask <= ART_EDGE_BLEND_MAX)
        if np.any(blend_mask):
            blend_span = max(1.0, float(ART_EDGE_BLEND_MAX - ART_EDGE_BLEND_MIN))
            edge_alpha = (
                (smask[blend_mask].astype(np.float32) - float(ART_EDGE_BLEND_MIN)) / blend_span
            ).reshape(-1, 1)
            edge_alpha = np.clip(edge_alpha, 0.0, 1.0)
            src_edge = source_cmyk[blend_mask].astype(np.float32)
            ai_edge = composite[blend_mask].astype(np.float32)
            composite[blend_mask] = np.clip(
                (src_edge * (1.0 - edge_alpha)) + (ai_edge * edge_alpha),
                0.0,
                255.0,
            ).astype(np.uint8)

        encoded = zlib.compress(composite.tobytes())
        smask_ref = im0.get("/SMask")
        im0.write(encoded, filter=pikepdf.Name("/FlateDecode"))
        if smask_ref is not None:
            im0["/SMask"] = smask_ref
        if "/DecodeParms" in im0:
            del im0["/DecodeParms"]

        pdf.save(str(output_pdf))
    finally:
        pdf.close()

    _render_pdf_to_jpg(source_pdf=output_pdf, output_jpg=output_jpg, dpi=EXPECTED_DPI)
    shutil.copyfile(output_pdf, output_ai)

    return {
        "success": True,
        "source_pdf": str(source_pdf),
        "output_pdf": str(output_pdf),
        "output_jpg": str(output_jpg),
        "output_ai": str(output_ai),
        "center_x": 2864,
        "center_y": 1620,
        "image_width": int(width),
        "image_height": int(height),
    }


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
    """Composite all generated variants for a book via source PDF."""
    source_pdf = find_source_pdf_for_book(input_dir=input_dir, book_number=book_number, catalog_path=catalog_path)
    if source_pdf is None:
        raise FileNotFoundError(f"No source PDF found for book {book_number}")

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
        )
        outputs.append(output_jpg)
        report_items.append(
            {
                "output_path": str(output_jpg),
                "valid": True,
                "issues": [],
                "mode": "pdf",
                "source_pdf": str(source_pdf),
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
        "PDF compositor completed",
        extra={"book_number": int(book_number), "variants": len(outputs), "source_pdf": str(source_pdf)},
    )
    return outputs


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="PDF compositor for one generated image")
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("ai_art", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("output_jpg", type=Path)
    parser.add_argument("--output-ai", type=Path, default=None)
    args = parser.parse_args()

    result = composite_cover_pdf(
        source_pdf_path=str(args.source_pdf),
        ai_art_path=str(args.ai_art),
        output_pdf_path=str(args.output_pdf),
        output_jpg_path=str(args.output_jpg),
        output_ai_path=str(args.output_ai) if args.output_ai else None,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
