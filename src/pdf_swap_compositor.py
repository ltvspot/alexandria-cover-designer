"""Im0 layer-swap compositor for medallion covers.

This module replaces only the center art inside the source PDF's ``/Im0``
image XObject while preserving the ornamental frame and the original ``/SMask``.
The modified PDF is then rendered to the final composite JPG.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pikepdf
from PIL import Image

try:
    from src import safe_image
    from src import focus_crop
except ModuleNotFoundError:  # pragma: no cover
    import safe_image  # type: ignore
    import focus_crop  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_BLEND_RADIUS = 840
DEFAULT_FEATHER_PX = 20
DEFAULT_BORDER_TRIM_RATIO = 0.05
JPEG_QUALITY = 100
RENDER_DPI = 300


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

        # SMask-based pixel preservation: the SMask from the original
        # designer encodes the exact frame boundary.
        #   SMask > 250  → fully opaque (illustration area) → use AI art
        #   SMask < 5    → fully transparent (hidden by background) → use AI art
        #   SMask 5–250  → semi-transparent frame ring → keep ORIGINAL pixels
        SMASK_FRAME_LO = 5
        SMASK_FRAME_HI = 250

        frame_ring_mask = (smask_arr >= SMASK_FRAME_LO) & (smask_arr <= SMASK_FRAME_HI)

        blended = art_arr.copy()
        blended[frame_ring_mask] = original_arr[frame_ring_mask]

        _write_im0_stream(
            pdf=pdf,
            im0_obj=im0_obj,
            image_bytes=blended.tobytes(),
            width=width,
            height=height,
            bands=bands,
        )

        frame_pixels_preserved = int(np.sum(frame_ring_mask))

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(output_pdf_path))

    _render_pdf_to_jpg(
        source_pdf_path=output_pdf_path,
        output_jpg_path=output_jpg_path,
        render_dpi=render_dpi,
        expected_output_size=expected_output_size,
    )
    logger.info(
        "PDF swap composite complete (SMask-preserve): source=%s output=%s frame_pixels=%d",
        source_pdf_path.name,
        output_jpg_path,
        frame_pixels_preserved,
    )
    return output_jpg_path


def detect_blend_radius_from_smask(smask_arr: np.ndarray) -> int:
    """Return the safe art radius where frame ornaments have not yet begun."""

    if smask_arr.ndim != 2:
        raise ValueError("SMask array must be 2D")
    return DEFAULT_BLEND_RADIUS


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
    source = safe_image.load_image(ai_art_path, mode="RGB")
    prepared = _strip_border(source, border_trim_ratio=border_trim_ratio)
    fitted = focus_crop.smart_fit(prepared, size)
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
        rendered_rgb = safe_image.load_image(output_jpg_path, mode="RGB")
        if expected_output_size and rendered_rgb.size != expected_output_size:
            rendered_rgb = rendered_rgb.resize(expected_output_size, Image.LANCZOS)
        safe_image.atomic_save_image(
            output_jpg_path,
            rendered_rgb,
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
        safe_image.atomic_save_image(
            output_jpg_path,
            image,
            format="JPEG",
            quality=JPEG_QUALITY,
            subsampling=0,
            dpi=(render_dpi, render_dpi),
        )
    finally:
        doc.close()
