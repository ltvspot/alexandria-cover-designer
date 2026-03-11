from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from src import cover_compositor as cc


def _make_rgb(path: Path, color=(20, 30, 50), size=(700, 500)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=color).save(path, format="JPEG")


def _make_rgba(path: Path, color=(220, 180, 120, 255), size=(300, 300)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, color=color).save(path, format="PNG")


def test_region_and_parser_helpers():
    region = cc._region_from_dict(
        {
            "center_x": 200,
            "center_y": 150,
            "radius": 80,
            "frame_bbox": [100, 50, 300, 250],
            "region_type": "rectangle",
            "rect_bbox": [120, 90, 250, 220],
            "mask_path": "x.png",
        }
    )
    assert region.region_type == "rectangle"
    assert region.rect_bbox == (120, 90, 250, 220)
    assert cc._parse_variant("variant_3") == 3
    assert cc._parse_variant("bad") == 0
    assert cc._parse_books("1,3-4") == [1, 3, 4]


def test_circle_and_rect_masks():
    circle = cc._build_circle_feather_mask(width=200, height=200, center_x=100, center_y=100, radius=50, feather_px=10)
    rect = cc._build_rect_feather_mask(width=200, height=200, bbox=(40, 50, 160, 170), feather_px=8)
    assert circle.mode == "L"
    assert rect.mode == "L"
    c = np.array(circle)
    r = np.array(rect)
    assert c[100, 100] > c[0, 0]
    assert r[60, 60] > r[0, 0]


def test_load_custom_mask_fallback_and_resize(tmp_path: Path):
    fallback = cc._load_custom_mask("missing/path.png", (40, 60))
    assert fallback.size == (40, 60)
    assert np.array(fallback).max() == 255

    mask_src = tmp_path / "mask.png"
    Image.new("L", (20, 20), 128).save(mask_src, format="PNG")
    resized = cc._load_custom_mask(str(mask_src), (50, 70))
    assert resized.size == (50, 70)


def test_composite_single_circle_and_rectangle(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    ill = tmp_path / "ill.png"
    _make_rgb(cover, size=(700, 500))
    _make_rgba(ill, size=(300, 300))

    circle_out = tmp_path / "circle.jpg"
    region_circle = {"center_x": 350, "center_y": 250, "radius": 120, "frame_bbox": [200, 100, 500, 400], "region_type": "circle"}
    cc.composite_single(cover, ill, region_circle, circle_out)
    assert circle_out.exists()
    assert circle_out.with_suffix(".jpg.validation.json").exists()
    with Image.open(circle_out) as img:
        assert img.size == (700, 500)

    rect_out = tmp_path / "rect.jpg"
    region_rect = {
        "center_x": 300,
        "center_y": 220,
        "radius": 100,
        "frame_bbox": [180, 80, 500, 380],
        "region_type": "rectangle",
        "rect_bbox": [220, 120, 480, 360],
    }
    cc.composite_single(cover, ill, region_rect, rect_out)
    assert rect_out.exists()


def test_generate_fit_overlay_and_color_match(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    ill = tmp_path / "ill.png"
    _make_rgb(cover, size=(700, 500))
    _make_rgba(ill, size=(120, 120))

    region = cc._region_from_dict({"center_x": 350, "center_y": 250, "radius": 100, "frame_bbox": [250, 150, 450, 350], "region_type": "circle"})
    matched = cc._color_match_illustration(Image.open(cover), Image.open(ill).convert("RGBA"), region)
    assert matched.mode == "RGBA"

    overlay_out = tmp_path / "fit_overlay.png"
    cc.generate_fit_overlay(cover, {"center_x": 350, "center_y": 250, "radius": 100, "frame_bbox": [250, 150, 450, 350]}, overlay_out)
    assert overlay_out.exists()


def test_find_cover_collect_generated_and_batch(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    generated_dir = tmp_path / "tmp" / "generated"
    output_dir = tmp_path / "tmp" / "composited"
    regions_path = tmp_path / "regions.json"
    catalog_path = tmp_path / "catalog.json"

    book_folder = input_dir / "1. Test Book"
    _make_rgb(book_folder / "cover.jpg", size=(3784, 2777))
    _make_rgba(generated_dir / "1" / "model_a" / "variant_1.png", size=(512, 512))
    _make_rgba(generated_dir / "1" / "variant_2.png", size=(512, 512))

    catalog_path.write_text(json.dumps([{"number": 1, "folder_name": "1. Test Book"}]), encoding="utf-8")
    regions_payload = {"covers": [{"cover_id": 1, "center_x": 2864, "center_y": 1620, "radius": 500, "frame_bbox": [2200, 900, 3400, 2200], "region_type": "circle"}]}
    regions_path.write_text(json.dumps(regions_payload), encoding="utf-8")

    assert cc._find_cover_jpg(input_dir, 1, catalog_path=catalog_path).exists()
    collected = cc._collect_generated_for_book(generated_dir, 1)
    assert len(collected) >= 2

    summary = cc.batch_composite(
        input_dir=input_dir,
        generated_dir=generated_dir,
        output_dir=output_dir,
        regions_path=regions_path,
        book_numbers=[1],
        catalog_path=catalog_path,
    )
    assert summary["processed_books"] == 1
    assert summary["failed_books"] == 0
    assert (output_dir / "1" / "composite_validation.json").exists()


def test_composite_single_with_custom_mask(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    ill = tmp_path / "ill.png"
    custom_mask = tmp_path / "mask.png"
    _make_rgb(cover, size=(700, 500))
    _make_rgba(ill, size=(256, 256))
    Image.new("L", (700, 500), 180).save(custom_mask, format="PNG")

    out = tmp_path / "custom.jpg"
    region = {
        "center_x": 350,
        "center_y": 250,
        "radius": 120,
        "frame_bbox": [180, 80, 520, 420],
        "region_type": "custom_mask",
        "mask_path": str(custom_mask),
    }
    cc.composite_single(cover, ill, region, out)
    assert out.exists()


def test_generate_fit_overlay_rectangle_path(tmp_path: Path):
    cover = tmp_path / "cover.jpg"
    _make_rgb(cover, size=(700, 500))
    out = tmp_path / "overlay.png"
    cc.generate_fit_overlay(
        cover,
        {
            "center_x": 300,
            "center_y": 200,
            "radius": 80,
            "frame_bbox": [150, 100, 450, 340],
            "region_type": "rectangle",
            "rect_bbox": [180, 130, 420, 300],
        },
        out,
    )
    assert out.exists()


def test_composite_all_variants_raises_without_generated_images(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    generated_dir = tmp_path / "tmp" / "generated"
    output_dir = tmp_path / "tmp" / "composited"
    catalog_path = tmp_path / "catalog.json"
    book_folder = input_dir / "3. Test Book"
    _make_rgb(book_folder / "cover.jpg", size=(3784, 2777))
    (generated_dir / "3").mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps([{"number": 3, "folder_name": "3. Test Book"}]), encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        cc.composite_all_variants(
            book_number=3,
            input_dir=input_dir,
            generated_dir=generated_dir,
            output_dir=output_dir,
            regions={"covers": [{"cover_id": 3, "center_x": 200, "center_y": 200, "radius": 100, "frame_bbox": [100, 100, 300, 300]}]},
            catalog_path=catalog_path,
        )


def test_find_cover_jpg_error_paths(tmp_path: Path):
    input_dir = tmp_path / "Input Covers"
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps([{"number": 4, "folder_name": "4. Missing Folder"}]), encoding="utf-8")

    with pytest.raises(KeyError):
        cc._find_cover_jpg(input_dir, 9, catalog_path=catalog_path)
    with pytest.raises(FileNotFoundError):
        cc._find_cover_jpg(input_dir, 4, catalog_path=catalog_path)

    folder = input_dir / "4. Missing Folder"
    folder.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        cc._find_cover_jpg(input_dir, 4, catalog_path=catalog_path)


def test_collect_generated_handles_missing_and_history_dir(tmp_path: Path):
    generated_dir = tmp_path / "generated"
    assert cc._collect_generated_for_book(generated_dir, 5) == []

    base = generated_dir / "5"
    _make_rgba(base / "history" / "variant_1.png")
    _make_rgba(base / "model_a" / "variant_1.png")
    _make_rgba(base / "model_a" / "variant_1.png")
    rows = cc._collect_generated_for_book(generated_dir, 5)
    assert len(rows) == 1
    assert rows[0]["model"] == "model_a"


def test_color_match_returns_original_when_ring_empty(tmp_path: Path):
    cover = Image.new("RGB", (20, 20), (20, 30, 40))
    illustration = Image.new("RGBA", (10, 10), (100, 120, 140, 255))
    region = cc.Region(center_x=10, center_y=10, radius=9999, frame_bbox=(0, 0, 20, 20))
    matched = cc._color_match_illustration(cover, illustration, region)
    assert matched is illustration


def test_strip_border_adapts_for_internal_frame_artifacts():
    plain = Image.new("RGBA", (240, 240), (90, 120, 160, 255))
    framed = Image.new("RGBA", (240, 240), (90, 120, 160, 255))
    draw = ImageDraw.Draw(framed, "RGBA")
    draw.rectangle((24, 24, 216, 216), outline=(240, 220, 170, 255), width=8)
    draw.rectangle((36, 36, 204, 204), outline=(200, 176, 132, 255), width=5)

    plain_stripped = cc._strip_border(plain, border_percent=0.05)
    framed_stripped = cc._strip_border(framed, border_percent=0.05)

    # Base strip is 5% per side => 216x216. Framed image should trigger stronger adaptive crop.
    assert plain_stripped.size == (216, 216)
    assert framed_stripped.size[0] < plain_stripped.size[0]
    assert framed_stripped.size[1] < plain_stripped.size[1]


def test_strip_border_trims_white_letterbox_bars():
    img = Image.new("RGBA", (240, 240), (40, 80, 120, 255))
    arr = np.array(img, dtype=np.uint8)
    arr[:36, :, :3] = 245
    arr[-36:, :, :3] = 245
    arr[:36, :, 3] = 255
    arr[-36:, :, 3] = 255
    letterboxed = Image.fromarray(arr, mode="RGBA")

    stripped = cc._strip_border(letterboxed, border_percent=0.05)

    # Baseline would be 216x216; with bar trim, height should shrink more.
    assert stripped.size[0] <= 216
    assert stripped.size[1] < 216


def test_main_book_and_batch_paths(monkeypatch, tmp_path: Path):
    regions_path = tmp_path / "regions.json"
    regions_path.write_text(json.dumps({"covers": []}), encoding="utf-8")

    book_args = SimpleNamespace(
        input_dir=tmp_path / "Input Covers",
        generated_dir=tmp_path / "generated",
        output_dir=tmp_path / "out",
        regions_path=regions_path,
        catalog_path=tmp_path / "catalog.json",
        book=10,
        books=None,
        max_books=20,
    )
    monkeypatch.setattr(cc.argparse.ArgumentParser, "parse_args", lambda self: book_args)
    monkeypatch.setattr(cc, "composite_all_variants", lambda **_kwargs: [Path("a"), Path("b")])
    assert cc.main() == 0

    batch_args = SimpleNamespace(**book_args.__dict__)
    batch_args.book = None
    batch_args.books = "1,2-3"
    monkeypatch.setattr(cc.argparse.ArgumentParser, "parse_args", lambda self: batch_args)
    monkeypatch.setattr(cc, "batch_composite", lambda **_kwargs: {"processed_books": 3})
    assert cc.main() == 0


def test_validate_composite_output_detects_alignment_and_bleed(tmp_path: Path):
    cover = Image.new("RGB", (300, 300), (20, 30, 40))
    composite = cover.copy()
    composite_arr = np.array(composite, dtype=np.uint8)
    composite_arr[30:110, 30:110] = np.array([240, 220, 180], dtype=np.uint8)
    composite = Image.fromarray(composite_arr, mode="RGB")
    out = tmp_path / "out.jpg"
    composite.save(out, format="JPEG", dpi=(300, 300))

    region = cc.Region(center_x=220, center_y=220, radius=60, frame_bbox=(160, 160, 280, 280))
    validation = cc.validate_composite_output(
        cover=cover,
        composited=composite,
        region=region,
        output_path=out,
    )
    assert validation.alignment_ok is False
    assert validation.valid is False


def test_global_compositing_mask_is_used_only_for_canonical_size():
    assert cc._load_global_compositing_mask((700, 500)) is None
    mask = cc._load_global_compositing_mask((3784, 2777))
    assert mask is None


def test_combine_masks_uses_stricter_alpha():
    primary = Image.new("L", (3, 3), 220)
    secondary = Image.new("L", (3, 3), 120)
    combined = cc._combine_masks(primary, secondary)
    arr = np.array(combined)
    assert arr.min() == 120
    assert arr.max() == 120


def test_geometry_from_strict_mask_uses_mask_center():
    mask = Image.new("L", (700, 500), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((356, 204, 484, 332), fill=255)
    geometry = cc._geometry_from_strict_mask(mask)
    assert geometry is not None
    assert abs(int(geometry["center_x"]) - 420) <= 2
    assert abs(int(geometry["center_y"]) - 268) <= 2
    assert 60 <= int(geometry["opening_radius"]) <= 66


def test_overlay_punch_can_use_mask_shape():
    cover = Image.new("RGB", (200, 200), (12, 24, 36))
    mask = Image.new("L", (200, 200), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((60, 50, 150, 140), fill=255)
    overlay = cc._build_cover_overlay_with_punch(
        cover=cover,
        center_x=100,
        center_y=95,
        punch_radius=60,
        punch_mask=mask,
    )
    alpha = np.array(overlay.split()[-1], dtype=np.uint8)
    assert alpha[95, 100] == 0
    assert alpha[10, 10] == 255


def test_composite_single_respects_strict_window_mask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cover = tmp_path / "cover.jpg"
    ill = tmp_path / "ill.png"
    out = tmp_path / "out.jpg"
    _make_rgb(cover, color=(30, 40, 60), size=(700, 500))
    _make_rgba(ill, color=(240, 200, 120, 255), size=(500, 500))

    strict = Image.new("L", (700, 500), 0)
    draw = ImageDraw.Draw(strict)
    draw.ellipse((290, 190, 410, 310), fill=255)
    monkeypatch.setattr(cc, "_load_global_compositing_mask", lambda _size: strict)
    # Force legacy fallback path so strict window behavior is exercised.
    monkeypatch.setattr(cc, "_find_template_for_cover", lambda _cover_path: None)
    monkeypatch.setattr(
        cc,
        "_create_template_for_cover",
        lambda **_kwargs: None,
    )

    cc.composite_single(
        cover_path=cover,
        illustration_path=ill,
        region={"center_x": 350, "center_y": 250, "radius": 180, "frame_bbox": [150, 50, 550, 450], "region_type": "circle"},
        output_path=out,
    )
    with Image.open(out) as img:
        arr = np.array(img.convert("RGB"), dtype=np.int16)
    # Far outside strict mask should remain the original navy-ish color.
    assert np.abs(arr[40, 40] - np.array([30, 40, 60], dtype=np.int16)).mean() < 14.0


def test_detect_medallion_geometry_handles_shifted_ring():
    cover = Image.new("RGB", (1400, 1000), (23, 41, 74))
    draw = ImageDraw.Draw(cover)
    true_center = (990, 610)
    outer_radius = 212
    draw.ellipse(
        (
            true_center[0] - outer_radius,
            true_center[1] - outer_radius,
            true_center[0] + outer_radius,
            true_center[1] + outer_radius,
        ),
        outline=(209, 171, 99),
        width=18,
    )
    draw.ellipse(
        (
            true_center[0] - (outer_radius - 20),
            true_center[1] - (outer_radius - 20),
            true_center[0] + (outer_radius - 20),
            true_center[1] + (outer_radius - 20),
        ),
        outline=(157, 119, 63),
        width=6,
    )
    region = cc.Region(
        center_x=930,
        center_y=560,
        radius=190,
        frame_bbox=(760, 390, 1220, 850),
        region_type="circle",
    )
    detected = cc._detect_medallion_geometry(cover=cover, region=region)
    assert abs(int(detected["center_x"]) - true_center[0]) <= 26
    assert abs(int(detected["center_y"]) - true_center[1]) <= 26
    assert abs(int(detected["outer_radius"]) - outer_radius) <= 26


def test_resolve_medallion_geometry_keeps_opening_inside_outer_ring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cover_path = tmp_path / "cover.jpg"
    _make_rgb(cover_path, color=(18, 35, 68), size=(3784, 2777))
    region = cc.Region(
        center_x=2864,
        center_y=1620,
        radius=500,
        frame_bbox=(2269, 1025, 3459, 2215),
        region_type="circle",
    )

    def _detect_should_not_run(**_kwargs):
        raise AssertionError("detection should be bypassed when region geometry is known")

    monkeypatch.setattr(cc, "_detect_medallion_geometry", _detect_should_not_run)
    cc._GEOMETRY_CACHE.clear()
    with Image.open(cover_path).convert("RGB") as cover:
        resolved = cc._resolve_medallion_geometry(cover=cover, cover_path=cover_path, region=region)

    assert int(resolved["center_x"]) == 2864
    assert int(resolved["center_y"]) == 1620
    assert resolved["outer_radius"] == 500
    assert 360 <= int(resolved["opening_radius"]) <= 530
    assert int(resolved["opening_radius"]) <= int(resolved["outer_radius"]) - cc.MIN_OPENING_MARGIN_PX


def test_smart_square_crop_uses_deterministic_center_crop():
    image = Image.new("RGBA", (640, 480), (10, 20, 30, 255))
    arr = np.array(image, dtype=np.uint8)
    arr[240, 320] = np.array([250, 120, 10, 255], dtype=np.uint8)  # center marker
    image = Image.fromarray(arr, mode="RGBA")

    cropped = cc._smart_square_crop(image)
    assert cropped.size == (480, 480)
    cropped_arr = np.array(cropped, dtype=np.uint8)
    # The marker from original center should land at the cropped center.
    center_px = cropped_arr[240, 240]
    assert int(center_px[0]) == 250
    assert int(center_px[1]) == 120
    assert int(center_px[2]) == 10
