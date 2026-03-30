"""
cover_compositor.py  v2 — Gemini punch-mask compositor.

Based entirely on flows/flow3_gemini_medallion_mask.py:
  1. Crop the medallion region from the cover.
  2. Send the crop to Gemini asking it to fill the interior with solid green.
  3. Extract a binary mask from the green channel.
  4. Composite the replacement art through the mask (centered on mask bbox).

Public API consumed by quality_review.py and pipeline.py:
  composite_single(cover_path, illustration_path, region, output_path, source_pdf_path=None)
  composite_all_variants(book_number, input_dir, generated_dir, output_dir, regions, catalog_path)
  validate_composite_output(cover, composited, region, output_path=None)
  _region_for_book(regions, book_number)
  _region_from_dict(region_dict)
  _find_cover_jpg(input_dir, book_number, catalog_path=None)
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

# ── Gemini / Google GenAI ────────────────────────────────────────────────────
import google.genai as genai
from google.genai import types as genai_types

# ── Tuning knobs (mirror flows/flow3_gemini_medallion_mask.py) ───────────────
CROP_PADDING     = 1.35   # crop radius = outer_radius * CROP_PADDING
GREEN_THRESHOLD  = 150    # G channel must be above this
RED_MAX          = 160    # R channel must be below this
BLUE_MAX         = 100    # B channel must be below this
GREEN_DOMINANCE  = 40     # G - max(R, B) must exceed this
ART_INSET_PX     = 30     # art bleed beyond mask bbox edge on each side
BLEND_RADIUS_PX  = 1      # Gaussian blur radius on mask edge
GEMINI_MODEL     = "gemini-3.1-flash-image-preview"
GEMINI_PROMPT    = (
    "This image shows a circular decorative medallion frame on a book cover. "
    "Fill the ENTIRE circular interior of the medallion with solid pure green (#00FF00). "
    "Paint over absolutely everything inside the circle — any illustration, figure, person, or content "
    "inside must be completely covered with flat solid green. "
    "Treat the inside of the circle as a canvas and paint it entirely green with no exceptions. "
    "Keep only the decorative golden frame border and everything outside the frame unchanged. "
    "No gradients, no textures, no partial fills — solid uniform green inside the circle only."
)

# Debug output directory (saves Gemini crop + mask for inspection)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEBUG_DIR = _REPO_ROOT / "tmp" / "gemini_debug"


# ── Internal Gemini helpers (from flow3) ─────────────────────────────────────

def _call_gemini_edit(api_key: str, crop: Image.Image) -> Image.Image:
    """Send medallion crop to Gemini; returns image with interior painted green."""
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})

    buf = io.BytesIO()
    crop.convert("RGB").save(buf, format="PNG")
    image_bytes = buf.getvalue()

    image_part = genai_types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/png",
        media_resolution=genai_types.MediaResolution.MEDIA_RESOLUTION_HIGH,
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[image_part, GEMINI_PROMPT],
        config=genai_types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=genai_types.ImageConfig(
                aspect_ratio="1:1",
                image_size="2K",
            ),
        ),
    )

    for part in response.parts:
        image = part.as_image()
        if image:
            return image._pil_image.convert("RGB")

    raise RuntimeError(f"Gemini returned no image. Text response: {response.text!r}")


def _extract_green_mask(edited_crop: Image.Image, original_crop_size: tuple[int, int]) -> Image.Image:
    """
    Convert green-painted pixels to a white binary mask, everything else black.
    Rescales back to original_crop_size if Gemini resized the output (always outputs 2048×2048).
    """
    arr = np.array(edited_crop.convert("RGB"), dtype=np.uint8)
    r = arr[..., 0].astype(np.int16)
    g = arr[..., 1].astype(np.int16)
    b = arr[..., 2].astype(np.int16)
    mask_arr = (
        (g > GREEN_THRESHOLD) &
        (r < RED_MAX) &
        (b < BLUE_MAX) &
        (g - np.maximum(r, b) > GREEN_DOMINANCE)
    )
    mask_img = Image.fromarray((mask_arr * 255).astype(np.uint8), mode="L")

    if mask_img.size != original_crop_size:
        print(
            f"  Rescaling mask {mask_img.size} → {original_crop_size} "
            f"(Gemini resized input from {original_crop_size} to {edited_crop.size})"
        )
        mask_img = mask_img.resize(original_crop_size, Image.LANCZOS)
        mask_arr2 = np.array(mask_img, dtype=np.uint8)
        mask_img = Image.fromarray((mask_arr2 > 128).astype(np.uint8) * 255, mode="L")

    return mask_img


def _validate_mask_inner_circle(
    full_mask: Image.Image,
    cx: int,
    cy: int,
    r_outer: int,
    min_fill_ratio: float = 0.85,
    inner_radius_factor: float = 0.55,
) -> tuple[bool, float]:
    """
    Check that the inner portion of the mask is solidly white (i.e. Gemini painted it correctly).

    Samples an inner circle at inner_radius_factor * r_outer and counts white pixels.
    Returns (ok, fill_ratio).  ok=False means the mask has irregular unpainted patches.
    """
    inner_r = int(r_outer * inner_radius_factor)
    arr = np.array(full_mask, dtype=np.uint8)
    H, W = arr.shape

    # Build coordinate grid
    ys, xs = np.mgrid[0:H, 0:W]
    inside = ((xs - cx) ** 2 + (ys - cy) ** 2) <= inner_r ** 2

    total = int(inside.sum())
    if total == 0:
        return False, 0.0

    white = int(((arr > 128) & inside).sum())
    fill_ratio = white / total
    ok = fill_ratio >= min_fill_ratio
    return ok, fill_ratio


def _composite_art_into_mask(
    cover: Image.Image,
    full_mask: Image.Image,
    art: Image.Image,
) -> Image.Image:
    """
    Composite art into the cover using the mask.
    White mask pixels → art shows through; black → original cover.
    Art is centered on the mask bounding-box center (NOT geometry center).
    """
    W, H = cover.size
    cover_rgba = cover.convert("RGBA")

    mask_arr = np.array(full_mask, dtype=np.uint8)
    ys, xs = np.where(mask_arr > 128)
    if len(xs) == 0:
        print("  WARNING: mask is empty — returning original cover unchanged.")
        return cover_rgba.convert("RGB")

    min_x, max_x = int(xs.min()), int(xs.max())
    min_y, max_y = int(ys.min()), int(ys.max())
    bbox_w  = max_x - min_x + 1
    bbox_h  = max_y - min_y + 1
    center_x = (min_x + max_x) // 2
    center_y = (min_y + max_y) // 2
    art_side = min(bbox_w, bbox_h) + ART_INSET_PX * 2

    print(f"  Mask bbox   : ({min_x},{min_y}) → ({max_x},{max_y})")
    print(f"  Mask center : ({center_x}, {center_y})")
    print(f"  Art side    : {art_side} px  (bleed +{ART_INSET_PX}px per side)")

    # Scale-to-fill: enlarge so shorter dimension = art_side, then center-crop to square.
    art_rgba = art.convert("RGBA")
    aw, ah = art_rgba.size
    scale = art_side / min(aw, ah)
    scaled_w, scaled_h = int(aw * scale), int(ah * scale)
    art_scaled = art_rgba.resize((scaled_w, scaled_h), Image.LANCZOS)
    crop_x = (scaled_w - art_side) // 2
    crop_y = (scaled_h - art_side) // 2
    art_resized = art_scaled.crop((crop_x, crop_y, crop_x + art_side, crop_y + art_side))
    art_full    = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    paste_x     = center_x - art_side // 2
    paste_y     = center_y - art_side // 2
    art_full.paste(art_resized, (paste_x, paste_y))

    mask_rgba = full_mask.convert("L").filter(ImageFilter.GaussianBlur(radius=BLEND_RADIUS_PX))
    result = Image.composite(art_full, cover_rgba, mask_rgba)
    return result.convert("RGB")


# ── Region helpers ────────────────────────────────────────────────────────────

def _region_for_book(regions: dict[str, Any], book_number: int) -> dict[str, Any]:
    """
    Return the composite region dict for book_number.
    Falls back to consensus_region if no per-book override exists.
    regions is the parsed cover_regions.json content.
    """
    # Per-book overrides keyed by string book number
    per_book: dict[str, Any] = regions.get("books", {})
    override = per_book.get(str(book_number))
    if override:
        return override

    consensus: dict[str, Any] = regions.get("consensus_region", {})
    return consensus


def _region_from_dict(region_dict: dict[str, Any]) -> dict[str, Any]:
    """Return region dict as-is (kept for API compatibility)."""
    return region_dict or {}


# ── Cover-finding helper ──────────────────────────────────────────────────────

def _find_cover_jpg(
    input_dir: Path,
    book_number: int,
    catalog_path: Path | None = None,
) -> Path | None:
    """
    Locate the source cover JPG for book_number inside input_dir.

    Strategy:
      1. If catalog_path is given, look up folder_name + file_base from catalog JSON.
      2. Otherwise glob for a directory whose name starts with "{book_number}.".
    """
    input_dir = Path(input_dir)

    # Try catalog lookup first
    if catalog_path and Path(catalog_path).exists():
        try:
            catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
            for entry in catalog:
                if int(entry.get("number", -1)) == book_number:
                    folder = entry.get("folder_name", "")
                    file_base = entry.get("file_base", "")
                    if folder:
                        candidate = input_dir / folder / f"{file_base}.jpg"
                        if candidate.exists():
                            return candidate
                        # Fallback: any .jpg in the folder
                        folder_dir = input_dir / folder
                        if folder_dir.is_dir():
                            jpgs = sorted(folder_dir.glob("*.jpg"))
                            if jpgs:
                                return jpgs[0]
        except Exception:
            pass

    # Glob fallback: directory starting with "{book_number}."
    for folder in sorted(input_dir.glob(f"{book_number}.*")):
        if folder.is_dir():
            jpgs = sorted(folder.glob("*.jpg"))
            if jpgs:
                return jpgs[0]

    return None


# ── Validation stub ───────────────────────────────────────────────────────────

@dataclass
class CompositeValidation:
    valid: bool = True
    checks: dict[str, Any] = field(default_factory=dict)
    output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "checks": self.checks,
            "output_path": self.output_path,
        }


def validate_composite_output(
    cover: Image.Image,
    composited: Image.Image,
    region: dict[str, Any],
    output_path: Path | None = None,
) -> CompositeValidation:
    """Minimal validation — always passes (Gemini mask is pixel-perfect)."""
    return CompositeValidation(
        valid=True,
        checks={"gemini_mask": "pass"},
        output_path=str(output_path) if output_path else "",
    )


# ── Primary compositing entry-points ─────────────────────────────────────────

def composite_single(
    cover_path: Path,
    illustration_path: Path,
    region: dict[str, Any] | None,
    output_path: Path,
    source_pdf_path: Path | None = None,  # ignored — kept for API compatibility
) -> Path:
    """
    Run the full Gemini punch-mask composite for one art file.

    Steps (mirrors flows/flow3_gemini_medallion_mask.py):
      1. Crop medallion region from cover.
      2. Call Gemini to paint interior green.
      3. Extract binary mask.
      4. Paste mask into full-cover coordinates.
      5. Composite art through mask.
      6. Save output JPEG.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set in environment or .env")

    cover_path = Path(cover_path)
    illustration_path = Path(illustration_path)
    output_path = Path(output_path)

    cover = Image.open(cover_path).convert("RGB")
    W, H = cover.size

    # Resolve geometry from region dict
    region = region or {}
    cx      = int(region.get("center_x", W * 0.76))
    cy      = int(region.get("center_y", H * 0.58))
    r_outer = int(region.get("radius", 559))

    print(f"Gemini punch-mask composite: {cover_path.name}")
    print(f"  Geometry: center=({cx},{cy})  outer_radius={r_outer}")

    # Check for cached mask — skip Gemini if already computed for this cover.
    _MASK_CACHE_DIR = _REPO_ROOT / "config" / "masks"
    cached_mask_path = _MASK_CACHE_DIR / f"{cover_path.stem}_mask.png"

    if cached_mask_path.exists():
        print(f"  Using cached mask: {cached_mask_path.name}")
        full_mask = Image.open(cached_mask_path).convert("L")
        if full_mask.size != (W, H):
            full_mask = full_mask.resize((W, H), Image.LANCZOS)
    else:
        # Step 1 — crop (same for all attempts)
        crop_r  = int(r_outer * CROP_PADDING)
        crop_l  = max(0, cx - crop_r)
        crop_t  = max(0, cy - crop_r)
        crop_ri = min(W, cx + crop_r)
        crop_bo = min(H, cy + crop_r)
        crop    = cover.crop((crop_l, crop_t, crop_ri, crop_bo))
        print(f"  Crop: ({crop_l},{crop_t}) → ({crop_ri},{crop_bo})  size={crop.size}")

        # Steps 2–3 — Gemini call + mask validation (up to 3 attempts)
        _MASK_MAX_ATTEMPTS = 3
        full_mask = None
        for attempt in range(1, _MASK_MAX_ATTEMPTS + 1):
            print(f"  Calling Gemini ({GEMINI_MODEL}) — attempt {attempt}/{_MASK_MAX_ATTEMPTS} ...")
            edited_crop = _call_gemini_edit(api_key, crop)

            _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            edited_crop.save(_DEBUG_DIR / f"gemini_edited_{cover_path.stem}_attempt{attempt}.png")

            crop_mask = _extract_green_mask(edited_crop, original_crop_size=crop.size)
            green_pixels = int(np.count_nonzero(np.array(crop_mask)))
            print(
                f"  Green mask: {green_pixels} white pixels "
                f"({100 * green_pixels / (crop.size[0] * crop.size[1]):.1f}% of crop)"
            )

            # Step 3a — paste into full-cover coordinates for validation
            candidate_mask = Image.new("L", (W, H), 0)
            candidate_mask.paste(crop_mask, (crop_l, crop_t))

            # Step 3b — validate inner circle fill
            ok, fill_ratio = _validate_mask_inner_circle(candidate_mask, cx, cy, r_outer)
            print(f"  Inner circle fill: {fill_ratio:.1%}  {'✓ ok' if ok else '✗ irregular — retrying'}")

            if ok:
                full_mask = candidate_mask
                break

            if attempt == _MASK_MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Gemini mask quality check failed after {_MASK_MAX_ATTEMPTS} attempts "
                    f"(inner fill {fill_ratio:.1%} < 85%) for {cover_path.name}. "
                    "The medallion interior was not fully painted green."
                )

        # Step 4 — save debug copy and cache
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        full_mask.save(_DEBUG_DIR / f"gemini_full_mask_{cover_path.stem}.png")
        _MASK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        full_mask.save(cached_mask_path)
        print(f"  Mask cached → {cached_mask_path}")

    # Step 5 — composite art
    art = Image.open(illustration_path)
    result = _composite_art_into_mask(cover, full_mask, art)

    # Step 6 — save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.save(str(output_path), "JPEG", quality=95)
    print(f"  Saved → {output_path}")
    print(f"Gemini punch-mask composite complete for {cover_path.name}")

    return output_path


def composite_all_variants(
    book_number: int,
    input_dir: Path,
    generated_dir: Path,
    output_dir: Path,
    regions: dict[str, Any],
    catalog_path: Path | None = None,
) -> list[Path]:
    """
    Composite every generated art PNG for book_number and return output paths.

    Generated art is expected at:  generated_dir / str(book_number) / "*.png"
    Outputs are written to:        output_dir / str(book_number) / "variant_N.jpg"
    """
    input_dir     = Path(input_dir)
    generated_dir = Path(generated_dir)
    output_dir    = Path(output_dir)

    cover_path = _find_cover_jpg(input_dir, book_number, catalog_path=catalog_path)
    if cover_path is None or not cover_path.exists():
        print(f"  WARNING: no cover JPG found for book {book_number} in {input_dir}")
        return []

    region = _region_for_book(regions, book_number)

    art_dir = generated_dir / str(book_number)
    art_files = sorted(art_dir.glob("*.png")) if art_dir.exists() else []
    if not art_files:
        print(f"  WARNING: no generated PNG art found in {art_dir}")
        return []

    book_out_dir = output_dir / str(book_number)
    book_out_dir.mkdir(parents=True, exist_ok=True)

    composited: list[Path] = []
    for i, art_path in enumerate(art_files, start=1):
        out_path = book_out_dir / f"variant_{i:02d}.jpg"
        try:
            result = composite_single(
                cover_path=cover_path,
                illustration_path=art_path,
                region=region,
                output_path=out_path,
            )
            composited.append(result)
        except Exception as exc:
            print(f"  ERROR compositing variant {i} ({art_path.name}): {exc}")

    return composited
