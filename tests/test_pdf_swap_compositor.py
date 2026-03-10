from __future__ import annotations

import numpy as np
import pytest

from src import pdf_swap_compositor as psc


def test_detect_blend_radius_from_smask_returns_fixed_default_radius():
    smask = np.full((21, 21), 255, dtype=np.uint8)
    yy, xx = np.ogrid[:21, :21]
    dist = np.sqrt((xx - 10) ** 2 + (yy - 10) ** 2)
    smask[dist >= 8] = 200

    assert psc.detect_blend_radius_from_smask(smask) == psc.DEFAULT_BLEND_RADIUS


def test_build_art_mask_fades_before_preserved_ring():
    mask = psc._build_art_mask(width=21, height=21, outer_radius=8, feather_px=4)

    assert mask[10, 10] == pytest.approx(1.0)
    assert mask[10, 17] == pytest.approx(0.25, abs=0.05)
    assert mask[0, 0] == pytest.approx(0.0)


def test_select_tagline_block_rects_targets_only_mixed_case_right_column_block():
    blocks = [
        (550.0, 53.0, 835.0, 166.0, "GULLIVER'S TRAVELS"),
        (502.0, 159.0, 871.0, 179.0, "INTO SEVERAL REMOTE REGIONS OF THE WORLD"),
        (535.0, 184.0, 843.0, 229.0, "An Epic Sea Adventure and Meditation on Obsession and Revenge"),
        (536.0, 556.0, 835.0, 601.0, "JONATHAN SWIFT"),
        (48.0, 210.0, 85.0, 820.0, "CLASSICS"),
    ]

    rects = psc._select_tagline_block_rects(blocks, page_width=1000.0, page_height=700.0)

    assert len(rects) == 1
    x0, y0, x1, y1 = rects[0]
    assert x0 < 535.0
    assert y0 < 184.0
    assert x1 > 843.0
    assert y1 > 229.0
