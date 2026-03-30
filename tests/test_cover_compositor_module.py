"""
Tests for cover_compositor v2 — Gemini punch-mask compositor.

These tests cover the v2 public API without making real Gemini API calls.
Gemini-dependent paths (composite_single without cache) are tested via
a monkeypatched _REPO_ROOT that provides a pre-built cached mask.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src import cover_compositor as cc


# ── Image helpers ─────────────────────────────────────────────────────────────

def _make_rgb(path: Path, color=(20, 30, 50), size=(700, 500)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(path, format="JPEG")


def _make_rgba(path: Path, color=(220, 180, 120, 255), size=(300, 300)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color=color).save(path, format="PNG")


def _circle_mask(size: tuple[int, int], cx: int, cy: int, r: int) -> Image.Image:
    img = Image.new("L", size, 0)
    draw = ImageDraw.Draw(img)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    return img


# ── Region helpers ─────────────────────────────────────────────────────────────

def test_region_from_dict_returns_dict():
    region = cc._region_from_dict({
        "center_x": 200,
        "center_y": 150,
        "radius": 80,
        "frame_bbox": [100, 50, 300, 250],
        "region_type": "rectangle",
        "rect_bbox": [120, 90, 250, 220],
        "mask_path": "x.png",
    })
    assert region["region_type"] == "rectangle"
    assert region["rect_bbox"] == [120, 90, 250, 220]
    assert region["center_x"] == 200


def test_region_from_dict_handles_none():
    assert cc._region_from_dict(None) == {}


def test_region_from_dict_handles_empty():
    assert cc._region_from_dict({}) == {}


def test_region_for_book_returns_consensus_when_no_override():
    regions = {
        "consensus_region": {"center_x": 100, "center_y": 200, "radius": 50},
        "books": {},
    }
    result = cc._region_for_book(regions, 5)
    assert result["center_x"] == 100
    assert result["radius"] == 50


def test_region_for_book_returns_per_book_override():
    regions = {
        "consensus_region": {"center_x": 100, "center_y": 200, "radius": 50},
        "books": {
            "3": {"center_x": 999, "center_y": 888, "radius": 77}
        },
    }
    result = cc._region_for_book(regions, 3)
    assert result["center_x"] == 999
    assert result["radius"] == 77


def test_region_for_book_non_override_uses_consensus():
    regions = {
        "consensus_region": {"center_x": 111, "center_y": 222, "radius": 33},
        "books": {"7": {"center_x": 500}},
    }
    assert cc._region_for_book(regions, 1)["center_x"] == 111


# ── _find_cover_jpg ─────────────────────────────────────────────────────────

def test_find_cover_jpg_catalog_lookup(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    catalog_path = tmp_path / "catalog.json"
    book_folder = input_dir / "1. Test Book"
    _make_rgb(book_folder / "cover.jpg", size=(3784, 2777))
    catalog_path.write_text(
        json.dumps([{"number": 1, "folder_name": "1. Test Book"}]),
        encoding="utf-8",
    )
    result = cc._find_cover_jpg(input_dir, 1, catalog_path=catalog_path)
    assert result is not None
    assert result.exists()


def test_find_cover_jpg_glob_fallback(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    book_folder = input_dir / "2. Glob Book"
    _make_rgb(book_folder / "cover.jpg")
    # No catalog — should glob for "2.*" directory
    result = cc._find_cover_jpg(input_dir, 2)
    assert result is not None
    assert result.exists()


def test_find_cover_jpg_unknown_book_returns_none(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps([{"number": 4, "folder_name": "4. Missing Folder"}]),
        encoding="utf-8",
    )
    # Book 9 not in catalog → None
    assert cc._find_cover_jpg(input_dir, 9, catalog_path=catalog_path) is None


def test_find_cover_jpg_missing_folder_returns_none(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps([{"number": 4, "folder_name": "4. Missing Folder"}]),
        encoding="utf-8",
    )
    # Book 4 in catalog but folder doesn't exist → None
    assert cc._find_cover_jpg(input_dir, 4, catalog_path=catalog_path) is None


def test_find_cover_jpg_folder_exists_but_empty_returns_none(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps([{"number": 4, "folder_name": "4. Empty Folder"}]),
        encoding="utf-8",
    )
    (input_dir / "4. Empty Folder").mkdir(parents=True, exist_ok=True)
    assert cc._find_cover_jpg(input_dir, 4, catalog_path=catalog_path) is None


# ── _extract_green_mask ────────────────────────────────────────────────────────

def test_extract_green_mask_all_green_produces_white_mask():
    green_img = Image.new("RGB", (100, 100), (0, 255, 0))
    mask = cc._extract_green_mask(green_img, original_crop_size=(100, 100))
    arr = np.array(mask)
    assert mask.mode == "L"
    assert arr.min() == 255


def test_extract_green_mask_red_image_produces_black_mask():
    red_img = Image.new("RGB", (100, 100), (255, 0, 0))
    mask = cc._extract_green_mask(red_img, original_crop_size=(100, 100))
    arr = np.array(mask)
    assert arr.max() == 0


def test_extract_green_mask_rescales_from_2048():
    # Gemini typically returns 2048×2048 regardless of input size
    green_img = Image.new("RGB", (2048, 2048), (0, 255, 0))
    mask = cc._extract_green_mask(green_img, original_crop_size=(500, 500))
    assert mask.size == (500, 500)
    arr = np.array(mask)
    assert arr.min() == 255  # still all white after rescale + re-threshold


def test_extract_green_mask_mixed_image():
    # Left half green, right half red
    arr = np.zeros((100, 100, 3), dtype=np.uint8)
    arr[:, :50] = [0, 255, 0]   # green left half
    arr[:, 50:] = [255, 0, 0]   # red right half
    img = Image.fromarray(arr, mode="RGB")
    mask = cc._extract_green_mask(img, original_crop_size=(100, 100))
    mask_arr = np.array(mask)
    # Left half should be white, right half black
    assert mask_arr[:, :45].min() == 255
    assert mask_arr[:, 55:].max() == 0


# ── _composite_art_into_mask ──────────────────────────────────────────────────

def test_composite_art_into_mask_places_art_in_mask_region():
    cover = Image.new("RGB", (400, 300), (10, 20, 40))
    # White circle at left side: center ~(100, 150), radius ~50
    mask = _circle_mask((400, 300), cx=100, cy=150, r=50)
    art = Image.new("RGBA", (200, 200), (200, 100, 50, 255))

    result = cc._composite_art_into_mask(cover, mask, art)
    assert result.size == (400, 300)
    assert result.mode == "RGB"

    arr = np.array(result)
    # Mask center (100, 150) should be covered by art (reddish), not original cover (10, 20, 40)
    center_pixel = arr[150, 100]
    assert int(center_pixel[0]) > 100  # red channel from art


def test_composite_art_into_mask_preserves_outside_region():
    cover = Image.new("RGB", (400, 300), (10, 20, 40))
    # Small circle in center
    mask = _circle_mask((400, 300), cx=200, cy=150, r=30)
    art = Image.new("RGBA", (200, 200), (200, 100, 50, 255))

    result = cc._composite_art_into_mask(cover, mask, art)
    arr = np.array(result)
    # Far corner should still be original cover color
    corner = arr[0, 0]
    assert int(corner[0]) < 30  # near original blue-ish


def test_composite_art_into_mask_empty_mask_returns_original():
    cover = Image.new("RGB", (200, 200), (10, 20, 40))
    mask = Image.new("L", (200, 200), 0)  # all black
    art = Image.new("RGBA", (100, 100), (200, 100, 50, 255))

    result = cc._composite_art_into_mask(cover, mask, art)
    arr = np.array(result)
    # All pixels should remain original cover color
    assert int(arr[100, 100, 0]) == 10


def test_composite_art_into_mask_scale_to_fill_non_square_art():
    # Non-square art (landscape) should be scaled to fill mask bbox without distortion
    cover = Image.new("RGB", (400, 300), (10, 20, 40))
    mask = _circle_mask((400, 300), cx=200, cy=150, r=60)

    # Wide landscape art — should be cropped to square without stretching
    art = Image.new("RGBA", (400, 200), (200, 100, 50, 255))
    result = cc._composite_art_into_mask(cover, mask, art)
    assert result.size == (400, 300)  # output always matches cover size


# ── validate_composite_output ─────────────────────────────────────────────────

def test_validate_composite_output_always_valid():
    cover = Image.new("RGB", (300, 300), (20, 30, 40))
    composited = Image.new("RGB", (300, 300), (50, 60, 70))
    region = {"center_x": 150, "center_y": 150, "radius": 60}
    result = cc.validate_composite_output(cover, composited, region)
    assert result.valid is True


def test_validate_composite_output_to_dict():
    cover = Image.new("RGB", (100, 100), (10, 10, 10))
    composited = Image.new("RGB", (100, 100), (20, 20, 20))
    region = {"center_x": 50, "center_y": 50, "radius": 30}
    d = cc.validate_composite_output(cover, composited, region, output_path=None).to_dict()
    assert "valid" in d
    assert d["valid"] is True


def test_validate_composite_output_with_path(tmp_path: Path):
    out = tmp_path / "out.jpg"
    cover = Image.new("RGB", (100, 100))
    composited = Image.new("RGB", (100, 100))
    result = cc.validate_composite_output(cover, composited, {}, output_path=out)
    assert result.output_path == str(out)


# ── composite_single (cached mask path — no Gemini call) ─────────────────────

def test_composite_single_uses_cached_mask(tmp_path: Path, monkeypatch):
    """composite_single must use the cached mask and never call Gemini."""
    cover = tmp_path / "cover.jpg"
    ill = tmp_path / "ill.png"
    out = tmp_path / "out.jpg"
    _make_rgb(cover, size=(700, 500))
    _make_rgba(ill, size=(300, 300))

    # Build a cached mask in the location composite_single will look for it.
    # composite_single uses: _REPO_ROOT / "config" / "masks" / f"{cover.stem}_mask.png"
    mask_dir = tmp_path / "config" / "masks"
    mask_dir.mkdir(parents=True)
    mask_img = _circle_mask((700, 500), cx=350, cy=250, r=100)
    mask_img.save(mask_dir / f"{cover.stem}_mask.png")

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-cached")
    monkeypatch.setattr(cc, "_REPO_ROOT", tmp_path)

    result = cc.composite_single(cover, ill, {"center_x": 350, "center_y": 250, "radius": 120}, out)
    assert out.exists()
    assert result == out

    with Image.open(out) as img:
        assert img.size == (700, 500)


def test_composite_single_no_api_key_raises(tmp_path: Path, monkeypatch):
    cover = tmp_path / "cover.jpg"
    ill = tmp_path / "ill.png"
    out = tmp_path / "out.jpg"
    _make_rgb(cover)
    _make_rgba(ill)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        cc.composite_single(cover, ill, {}, out)


# ── composite_all_variants ────────────────────────────────────────────────────

def test_composite_all_variants_no_cover_returns_empty(tmp_path: Path):
    input_dir = tmp_path / "Input"
    gen_dir = tmp_path / "gen"
    out_dir = tmp_path / "out"
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([{"number": 1, "folder_name": "1. Missing"}]), encoding="utf-8")
    _make_rgba(gen_dir / "1" / "variant_1.png")

    result = cc.composite_all_variants(
        book_number=1,
        input_dir=input_dir,
        generated_dir=gen_dir,
        output_dir=out_dir,
        regions={"consensus_region": {"center_x": 200, "center_y": 200, "radius": 100}},
        catalog_path=catalog,
    )
    assert result == []


def test_composite_all_variants_no_art_returns_empty(tmp_path: Path):
    input_dir = tmp_path / "Input"
    gen_dir = tmp_path / "gen"
    out_dir = tmp_path / "out"
    catalog = tmp_path / "catalog.json"
    book_folder = input_dir / "1. Test Book"
    _make_rgb(book_folder / "cover.jpg")
    catalog.write_text(json.dumps([{"number": 1, "folder_name": "1. Test Book"}]), encoding="utf-8")
    (gen_dir / "1").mkdir(parents=True, exist_ok=True)  # empty art dir

    result = cc.composite_all_variants(
        book_number=1,
        input_dir=input_dir,
        generated_dir=gen_dir,
        output_dir=out_dir,
        regions={"consensus_region": {"center_x": 200, "center_y": 200, "radius": 100}},
        catalog_path=catalog,
    )
    assert result == []


def test_composite_all_variants_composites_art(tmp_path: Path, monkeypatch):
    """Full composite_all_variants run with cached mask."""
    input_dir = tmp_path / "Input"
    gen_dir = tmp_path / "gen"
    out_dir = tmp_path / "out"
    catalog = tmp_path / "catalog.json"

    book_folder = input_dir / "1. Test Book"
    _make_rgb(book_folder / "cover.jpg", size=(700, 500))
    _make_rgba(gen_dir / "1" / "art1.png")
    _make_rgba(gen_dir / "1" / "art2.png")
    catalog.write_text(json.dumps([{"number": 1, "folder_name": "1. Test Book"}]), encoding="utf-8")

    # Seed cached mask
    mask_dir = tmp_path / "config" / "masks"
    mask_dir.mkdir(parents=True)
    mask_img = _circle_mask((700, 500), cx=350, cy=250, r=100)
    mask_img.save(mask_dir / "cover_mask.png")

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-cached")
    monkeypatch.setattr(cc, "_REPO_ROOT", tmp_path)

    result = cc.composite_all_variants(
        book_number=1,
        input_dir=input_dir,
        generated_dir=gen_dir,
        output_dir=out_dir,
        regions={"consensus_region": {"center_x": 350, "center_y": 250, "radius": 120}},
        catalog_path=catalog,
    )
    assert len(result) == 2
    for p in result:
        assert p.exists()
