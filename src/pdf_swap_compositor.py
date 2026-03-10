"""Im0 layer-swap compositor for medallion covers.

This module replaces only the center art inside the source PDF's ``/Im0``
image XObject while preserving the ornamental frame and the original ``/SMask``.
The modified PDF is then rendered to the final composite JPG.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pikepdf
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

DEFAULT_BLEND_RADIUS = 840
DEFAULT_FEATHER_PX = 20
DEFAULT_BORDER_TRIM_RATIO = 0.05
JPEG_QUALITY = 100
RENDER_DPI = 300
TAGLINE_VERTICAL_LIMIT_RATIO = 0.55
TAGLINE_RIGHT_COLUMN_MIN_RATIO = 0.45
TAGLINE_RIGHT_EDGE_MIN_RATIO = 0.55
TAGLINE_PADDING_PT = 6.0


def composite_via_pdf_swap(
    *,
    source_pdf_path: Path,
    ai_art_path: Path,
    output_jpg_path: Path,
    blend_radius: int | None = None,
    feather_px: int = DEFAULT_FEATHER_PX,
    render_dpi: int = RENDER_DPI,
    border_trim_ratio: float = DEFAULT_BORDER_TRIM_RATIO,
    expected_output_size: tuple[int, int] | None = None,
) -> Path:
    """Swap AI art into ``/Im0`` and render the modified PDF to JPG.

    A companion PDF is written beside ``output_jpg_path`` using the same stem.
    """

    source_pdf_path = Path(source_pdf_path)
    ai_art_path = Path(ai_art_path)
    output_jpg_path = Path(output_jpg_path)
    output_pdf_path = output_jpg_path.with_suffix(".pdf")

    if not source_pdf_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {source_pdf_path}")
    if not ai_art_path.exists():
        raise FileNotFoundError(f"AI art not found: {ai_art_path}")

    with pikepdf.Pdf.open(str(source_pdf_path)) as pdf:
        page = pdf.pages[0]
        im0_obj = _resolve_im0(page)
        smask_obj = im0_obj.get("/SMask")
        if smask_obj is None:
            raise ValueError(f"{source_pdf_path.name} /Im0 has no /SMask")

        original_image = pikepdf.PdfImage(im0_obj).as_pil_image()
        width, height = original_image.size
        mode = original_image.mode
        bands = len(original_image.getbands())
        if bands not in (3, 4):
            raise ValueError(f"Unsupported /Im0 mode: {mode}")

        decoded = bytes(im0_obj.read_bytes())
        expected_len = width * height * bands
        if len(decoded) != expected_len:
            raise ValueError(
                f"Decoded /Im0 length mismatch: got {len(decoded)}, expected {expected_len}"
            )
        original_arr = np.frombuffer(decoded, dtype=np.uint8).reshape(height, width, bands).copy()

        smask_pil = pikepdf.PdfImage(smask_obj).as_pil_image().convert("L")
        smask_arr = np.array(smask_pil, dtype=np.uint8)
        if smask_arr.shape != (height, width):
            raise ValueError(
                f"Decoded /SMask shape mismatch: got {smask_arr.shape}, expected {(height, width)}"
            )

        fitted_art = _load_ai_art(
            ai_art_path=ai_art_path,
            size=(width, height),
            mode=mode,
            border_trim_ratio=border_trim_ratio,
        )
        art_arr = np.array(fitted_art, dtype=np.uint8)
        if art_arr.ndim == 2:
            art_arr = art_arr[:, :, np.newaxis]
        if art_arr.shape != original_arr.shape:
            raise ValueError(
                f"AI art shape mismatch: got {art_arr.shape}, expected {original_arr.shape}"
            )

        safe_outer_radius = detect_blend_radius_from_smask(smask_arr)
        requested_radius = int(blend_radius) if blend_radius is not None else DEFAULT_BLEND_RADIUS
        effective_outer_radius = int(requested_radius)
        art_mask = _build_art_mask(
            width=width,
            height=height,
            outer_radius=effective_outer_radius,
            feather_px=feather_px,
        )

        blended = original_arr.copy()
        mix = art_mask[:, :, np.newaxis]
        blended_float = (art_arr.astype(np.float32) * mix) + (original_arr.astype(np.float32) * (1.0 - mix))
        blended[:] = np.clip(blended_float, 0.0, 255.0).astype(np.uint8)

        if np.any(art_mask <= 0.0):
            preserve = art_mask <= 0.0
            blended[preserve] = original_arr[preserve]

        _write_im0_stream(
            pdf=pdf,
            im0_obj=im0_obj,
            image_bytes=blended.tobytes(),
            width=width,
            height=height,
            bands=bands,
        )

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(output_pdf_path))

    _blank_top_right_tagline(output_pdf_path)
    _render_pdf_to_jpg(
        source_pdf_path=output_pdf_path,
        output_jpg_path=output_jpg_path,
        render_dpi=render_dpi,
        expected_output_size=expected_output_size,
    )
    logger.info(
        "PDF swap composite complete: source=%s output=%s safe_radius=%d effective_radius=%d",
        source_pdf_path.name,
        output_jpg_path,
        safe_outer_radius,
        effective_outer_radius,
    )
    return output_jpg_path


def detect_blend_radius_from_smask(smask_arr: np.ndarray) -> int:
    """Return the safe art radius where frame ornaments have not yet begun."""

    if smask_arr.ndim != 2:
        raise ValueError("SMask array must be 2D")
    return DEFAULT_BLEND_RADIUS


def _text_is_all_caps(text: str) -> bool:
    letters = [char for char in str(text or "") if char.isalpha()]
    return bool(letters) and all(char.upper() == char for char in letters)


def _text_has_mixed_case(text: str) -> bool:
    letters = [char for char in str(text or "") if char.isalpha()]
    if len(letters) < 6:
        return False
    return any(char.islower() for char in letters) and any(char.isupper() for char in letters)


def _select_tagline_block_rects(
    blocks: list[tuple[float, float, float, float, str]],
    *,
    page_width: float,
    page_height: float,
) -> list[tuple[float, float, float, float]]:
    candidates: list[dict[str, float | str]] = []
    for x0, y0, x1, y1, text in blocks:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if not cleaned:
            continue
        if x0 < page_width * TAGLINE_RIGHT_COLUMN_MIN_RATIO or x1 < page_width * TAGLINE_RIGHT_EDGE_MIN_RATIO:
            continue
        if y0 > page_height * TAGLINE_VERTICAL_LIMIT_RATIO:
            continue
        if (x1 - x0) < 80 or (y1 - y0) < 10:
            continue
        candidates.append({
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
            "text": cleaned,
        })

    author_top = page_height * TAGLINE_VERTICAL_LIMIT_RATIO
    author_candidates = [
        block
        for block in candidates
        if _text_is_all_caps(str(block["text"]))
        and float(block["y0"]) >= page_height * 0.38
    ]
    if author_candidates:
        author_top = min(float(block["y0"]) for block in author_candidates)

    selected: list[tuple[float, float, float, float]] = []
    for block in candidates:
        text = str(block["text"])
        if not _text_has_mixed_case(text):
            continue
        x0 = max(0.0, float(block["x0"]) - TAGLINE_PADDING_PT)
        y0 = max(0.0, float(block["y0"]) - TAGLINE_PADDING_PT)
        x1 = min(page_width, float(block["x1"]) + TAGLINE_PADDING_PT)
        y1 = min(page_height, float(block["y1"]) + TAGLINE_PADDING_PT)
        if y1 > author_top:
            continue
        selected.append((x0, y0, x1, y1))
    return selected


def _sample_fill_color(page: "fitz.Page", rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float]:
    import fitz  # type: ignore

    matrix = fitz.Matrix(2, 2)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    scale_x = pix.width / max(1.0, float(page.rect.width))
    scale_y = pix.height / max(1.0, float(page.rect.height))

    samples: list[np.ndarray] = []
    for x0, y0, x1, y1 in rects:
        rx0 = max(0, int(np.floor(x0 * scale_x)))
        ry0 = max(0, int(np.floor(y0 * scale_y)))
        rx1 = min(pix.width, int(np.ceil(x1 * scale_x)))
        ry1 = min(pix.height, int(np.ceil(y1 * scale_y)))
        pad = max(2, int(round(4 * max(scale_x, scale_y))))
        regions = [
            array[max(0, ry0 - pad):ry0, rx0:rx1],
            array[ry1:min(pix.height, ry1 + pad), rx0:rx1],
            array[ry0:ry1, max(0, rx0 - pad):rx0],
            array[ry0:ry1, rx1:min(pix.width, rx1 + pad)],
        ]
        for region in regions:
            if region.size:
                samples.append(region.reshape(-1, pix.n))
    if not samples:
        return (1.0, 1.0, 1.0)
    merged = np.concatenate(samples, axis=0)
    rgb = np.median(merged[:, :3], axis=0) / 255.0
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]))


def _blank_top_right_tagline(output_pdf_path: Path) -> None:
    try:
        import fitz  # type: ignore
    except ImportError:  # pragma: no cover
        logger.warning("PyMuPDF unavailable; skipping tagline blanking for %s", output_pdf_path.name)
        return

    doc = fitz.open(str(output_pdf_path))
    try:
        if doc.page_count <= 0:
            return
        page = doc[0]
        raw_blocks = page.get_text("blocks")
        blocks = [
            (float(x0), float(y0), float(x1), float(y1), str(text or ""))
            for x0, y0, x1, y1, text, *_rest in raw_blocks
        ]
        rects = _select_tagline_block_rects(
            blocks,
            page_width=float(page.rect.width),
            page_height=float(page.rect.height),
        )
        if not rects:
            return
        fill_color = _sample_fill_color(page, rects)
        for x0, y0, x1, y1 in rects:
            page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=fill_color, fill=fill_color, overlay=True)
        temp_output = output_pdf_path.with_suffix(".tagline.tmp.pdf")
        doc.save(str(temp_output), garbage=4, deflate=True)
    finally:
        doc.close()

    temp_output.replace(output_pdf_path)


def _build_art_mask(*, width: int, height: int, outer_radius: int, feather_px: int) -> np.ndarray:
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    inner_radius = max(0.0, float(outer_radius) - float(max(0, feather_px)))

    yy, xx = np.ogrid[:height, :width]
    dist = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)
    mask = np.zeros((height, width), dtype=np.float32)
    mask[dist <= inner_radius] = 1.0

    transition = (dist > inner_radius) & (dist < float(outer_radius))
    if np.any(transition) and outer_radius > inner_radius:
        span = float(outer_radius) - inner_radius
        mask[transition] = 1.0 - ((dist[transition] - inner_radius) / span)

    return np.clip(mask, 0.0, 1.0)


def _load_ai_art(
    *,
    ai_art_path: Path,
    size: tuple[int, int],
    mode: str,
    border_trim_ratio: float,
) -> Image.Image:
    with Image.open(ai_art_path) as source:
        prepared = _strip_border(source.convert("RGB"), border_trim_ratio=border_trim_ratio)
        fitted = ImageOps.fit(
            prepared,
            size,
            method=Image.LANCZOS,
            centering=(0.5, 0.5),
        )
        if mode != fitted.mode:
            fitted = fitted.convert(mode)
        return fitted


def _strip_border(image: Image.Image, *, border_trim_ratio: float) -> Image.Image:
    ratio = max(0.0, min(0.35, float(border_trim_ratio)))
    if ratio <= 0.0:
        return image
    width, height = image.size
    trim_x = int(round(width * ratio / 2.0))
    trim_y = int(round(height * ratio / 2.0))
    if width - (trim_x * 2) < 32 or height - (trim_y * 2) < 32:
        return image
    return image.crop((trim_x, trim_y, width - trim_x, height - trim_y))


def _resolve_im0(page: pikepdf.Page) -> pikepdf.Object:
    resources = page.get("/Resources")
    if resources is None:
        raise ValueError("PDF page has no /Resources")
    xobjects = resources.get("/XObject")
    if xobjects is None:
        raise ValueError("PDF page has no /XObject resources")

    im0_obj = xobjects.get("/Im0")
    if im0_obj is None:
        raise ValueError("PDF page has no /Im0 image XObject")
    return im0_obj


def _write_im0_stream(
    *,
    pdf: pikepdf.Pdf,
    im0_obj: pikepdf.Object,
    image_bytes: bytes,
    width: int,
    height: int,
    bands: int,
) -> None:
    colorspace = im0_obj.get("/ColorSpace")
    if colorspace is None:
        if bands == 4:
            colorspace = pikepdf.Name("/DeviceCMYK")
        elif bands == 3:
            colorspace = pikepdf.Name("/DeviceRGB")
        else:
            colorspace = pikepdf.Name("/DeviceGray")

    smask_ref = im0_obj.get("/SMask")
    encoded = zlib.compress(image_bytes)

    im0_obj.write(encoded, filter=pikepdf.Name("/FlateDecode"), type_check=False)
    im0_obj["/Type"] = pikepdf.Name("/XObject")
    im0_obj["/Subtype"] = pikepdf.Name("/Image")
    im0_obj["/Width"] = int(width)
    im0_obj["/Height"] = int(height)
    im0_obj["/ColorSpace"] = colorspace
    im0_obj["/BitsPerComponent"] = int(im0_obj.get("/BitsPerComponent", 8))
    im0_obj["/Filter"] = pikepdf.Name("/FlateDecode")
    if smask_ref is not None:
        im0_obj["/SMask"] = smask_ref
    if "/DecodeParms" in im0_obj:
        del im0_obj["/DecodeParms"]


def _render_pdf_to_jpg(
    *,
    source_pdf_path: Path,
    output_jpg_path: Path,
    render_dpi: int,
    expected_output_size: tuple[int, int] | None,
) -> None:
    output_jpg_path.parent.mkdir(parents=True, exist_ok=True)
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        stem = str(output_jpg_path.with_suffix(""))
        result = subprocess.run(
            [
                pdftoppm,
                "-jpeg",
                "-jpegopt",
                f"quality={JPEG_QUALITY},progressive=n,optimize=n",
                "-r",
                str(int(render_dpi)),
                "-singlefile",
                str(source_pdf_path),
                stem,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pdftoppm failed: {result.stderr.strip() or result.stdout.strip()}")
        if not output_jpg_path.exists():
            raise FileNotFoundError(f"Rendered JPG not found: {output_jpg_path}")
        with Image.open(output_jpg_path) as rendered:
            rendered_rgb = rendered.convert("RGB")
            if expected_output_size and rendered_rgb.size != expected_output_size:
                rendered_rgb = rendered_rgb.resize(expected_output_size, Image.LANCZOS)
            rendered_rgb.save(
                output_jpg_path,
                format="JPEG",
                quality=JPEG_QUALITY,
                subsampling=0,
                dpi=(render_dpi, render_dpi),
            )
        return

    logger.warning("pdftoppm not available; falling back to PyMuPDF render")
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pdftoppm is unavailable and PyMuPDF is not installed") from exc

    doc = fitz.open(str(source_pdf_path))
    try:
        if doc.page_count <= 0:
            raise ValueError("PDF has no pages")
        scale = float(render_dpi) / 72.0
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if expected_output_size and image.size != expected_output_size:
            image = image.resize(expected_output_size, Image.LANCZOS)
        image.save(
            output_jpg_path,
            format="JPEG",
            quality=JPEG_QUALITY,
            subsampling=0,
            dpi=(render_dpi, render_dpi),
        )
    finally:
        doc.close()
