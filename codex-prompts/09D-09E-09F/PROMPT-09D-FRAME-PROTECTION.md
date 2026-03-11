# PROMPT-09D — Frame Protection & Anti-Border Directives

## Overview

This prompt addresses a critical visual defect in the Alexandria Cover Designer compositor: AI-generated artwork includes its own decorative circular borders (floral vines, flowers, scrollwork) that visually overpower the original gold filigree ornamental frame in the source PDF. Two targeted fixes are required — one in the compositor to hard-mask the frame zone, and one in the prompt generator to issue stronger anti-frame directives to the AI model.

---

## Root Cause Analysis

The source PDF contains a gold filigree ornamental frame rendered as a circular ring surrounding the medallion zone. The SMask layer encodes three regions:

| SMask value | Region | Intended behavior |
|---|---|---|
| `> 250` | Inner circle (art zone) | AI art fully visible |
| `5 – 250` | Frame ring (semi-transparent) | Source CMYK frame shows through |
| `< 5` | Outer area | Fully transparent / hidden |

The compositor at `src/pdf_compositor.py` line 221 correctly restores source CMYK pixels for the frame ring (`smask <= SMASK_FRAME_MAX`). However, the AI-generated image is a full 2480×2470 px canvas that itself contains decorative circular border elements. Because those elements land precisely in the `5–250` SMask zone, they bleed through the semi-transparent layer and visually replace — rather than sit behind — the gold ornaments.

The prompt generator's existing `REQUIRED_PHRASE_NO_FRAME` directive ("no border, no frame, no decorative edge") is insufficiently strong; current AI models still synthesize circular framing when asked to paint a medallion-style scene.

---

## Changes Required

### 1. `src/pdf_compositor.py` — Hard-mask frame zone

Zero-out all AI art pixels that fall inside the frame ring and the outer transparent zone **before** compositing. This guarantees that nothing from the AI canvas can visually contaminate the frame ring, regardless of SMask alpha math.

**Constants already present (confirm these exist at the top of the file):**

```python
SMASK_FRAME_MIN = 5    # lower bound of semi-transparent frame ring
SMASK_FRAME_MAX = 250  # upper bound of semi-transparent frame ring
```

**BEFORE** (line 221, existing logic):

```python
preserve_mask = smask <= SMASK_FRAME_MAX  # 250
composite[preserve_mask] = source_cmyk[preserve_mask]
```

**AFTER** (replace the block starting at line 221 with the following):

```python
# ── Frame Protection ────────────────────────────────────────────────────────
# Step 1: Blank AI art in the full outer transparent zone (smask < SMASK_FRAME_MIN).
#         These pixels are hidden by SMask transparency anyway, but zeroing them
#         prevents any bleed if alpha math is not perfectly clean.
ai_cmyk[smask < SMASK_FRAME_MIN] = [0, 0, 0, 0]

# Step 2: Blank AI art in the frame ring zone (SMASK_FRAME_MIN <= smask <= SMASK_FRAME_MAX).
#         This is the critical change: the original gold filigree lives here.
#         Nothing from the AI canvas must be visible in this zone.
frame_zone_mask = (smask >= SMASK_FRAME_MIN) & (smask <= SMASK_FRAME_MAX)
ai_cmyk[frame_zone_mask] = [0, 0, 0, 0]
# ────────────────────────────────────────────────────────────────────────────

# Step 3: Composite — restore all source CMYK pixels that belong to the frame ring.
#         (Unchanged logic; now operates on the already-cleaned ai_cmyk.)
preserve_mask = smask <= SMASK_FRAME_MAX  # 250
composite[preserve_mask] = source_cmyk[preserve_mask]
```

**Result after this change:**

- `smask > 250` → AI art (untouched, full color)
- `5 ≤ smask ≤ 250` → Source CMYK only (AI art zeroed out beforehand, then overwritten by source)
- `smask < 5` → Zero/white (invisible under SMask transparency)

---

### 2. `src/prompt_generator.py` — Stronger anti-frame language

Three targeted changes are required.

---

#### 2a. Replace `REQUIRED_PHRASE_NO_FRAME`

**BEFORE:**

```python
REQUIRED_PHRASE_NO_FRAME = (
    "no border, no frame, no decorative edge"
)
```

**AFTER:**

```python
REQUIRED_PHRASE_NO_FRAME = (
    "no border, no frame, no decorative edge. "
    "CRITICAL: The artwork must NOT contain any circular border, frame, wreath, "
    "garland, vine ring, floral ring, or ANY decorative edge element. "
    "The scene fills the full rectangular canvas edge-to-edge with NO circular "
    "cropping or circular framing of any kind. "
    "Paint the scene as if it extends infinitely beyond the canvas edges."
)
```

---

#### 2b. Add explicit canvas instruction inside `build_diversified_prompt()`

Locate the return statement (or final string assembly) inside `build_diversified_prompt()` and insert the following sentence immediately before the closing of the positive prompt string:

**BEFORE** (wherever the prompt string is finalized, e.g.):

```python
    prompt = f"{scene_description}. {style_directives}. {REQUIRED_PHRASE_NO_FRAME}."
    return prompt
```

**AFTER:**

```python
    canvas_directive = (
        "The final image must be a FULL rectangular canvas of solid painted scene — "
        "no circular boundaries, no vignette edges, no decorative rings. "
        "Think of this as a square painting that will later be cropped into a circle, "
        "NOT as a circular medallion with its own frame."
    )
    prompt = f"{scene_description}. {style_directives}. {REQUIRED_PHRASE_NO_FRAME}. {canvas_directive}"
    return prompt
```

If `build_diversified_prompt()` assembles the prompt differently (e.g. via a list join), add `canvas_directive` as a final element in the list immediately before joining.

---

#### 2c. Extend the negative prompt list

Locate the negative prompt string or list in `prompt_generator.py` (typically assigned to a variable named `NEGATIVE_PROMPT`, `negative_prompt`, or passed as `negative_prompt=...` in an API call).

**BEFORE** (example — the exact existing string will differ):

```python
NEGATIVE_PROMPT = (
    "blurry, low quality, watermark, signature, text, logo"
)
```

**AFTER** — append the following terms (do not remove existing terms):

```python
NEGATIVE_PROMPT = (
    "blurry, low quality, watermark, signature, text, logo, "
    "circular border, circular frame, wreath, garland, vine ring, floral ring, "
    "decorative edge, ornamental ring, medallion border, scalloped edge"
)
```

---

### 3. `config/prompt_templates.json` — Update negative prompt (if applicable)

If the project stores negative prompt terms in `config/prompt_templates.json` rather than (or in addition to) `prompt_generator.py`, locate the `"negative_prompt"` key and append the same terms listed in §2c above:

```json
{
  "negative_prompt": "...(existing terms)..., circular border, circular frame, wreath, garland, vine ring, floral ring, decorative edge, ornamental ring, medallion border, scalloped edge"
}
```

If this file does not exist or does not contain a `"negative_prompt"` key, skip this step.

---

## Testing

### Unit check — compositor masking

After modifying `src/pdf_compositor.py`, run the compositor in isolation against a known source PDF and inspect the frame ring pixels in the output:

```bash
python scripts/debug_compositor.py \
  --source-pdf assets/source_cover_001.pdf \
  --ai-art assets/test_art_with_border.jpg \
  --output-pdf /tmp/test_composite_001.pdf \
  --dump-smask-zones
```

Confirm in the dump output:
- Zone `smask > 250`: AI art CMYK values are non-zero (art is present)
- Zone `5 ≤ smask ≤ 250`: CMYK values match source PDF (not AI art)
- Zone `smask < 5`: All CMYK channels are `0`

### Visual inspection

Open `/tmp/test_composite_001.pdf` in a PDF viewer. The gold filigree ornamental frame must be fully intact and clearly visible. No floral vines, vine rings, or decorative edges from the AI art should appear in the frame ring area.

### Regression — all 99 covers

Run the full batch generation for all 99 covers and visually spot-check a minimum of 10 covers that previously exhibited the bleed-through defect:

```bash
python scripts/generate_all.py --batch-size 99 --output-dir /tmp/batch_test/
```

---

## MANDATORY: Run Verification Before Committing

After making all changes, generate a test composite and run the strict verification script:

```bash
python scripts/verify_composite.py <output.jpg> \
  --source-pdf <source.pdf> \
  --output-pdf <output.pdf> \
  --strict
```

All checks must **PASS**. If any check **FAILS**, do not commit. Diagnose the failure, fix the code, and re-run until all checks pass.

**Report the full output of `verify_composite.py` in your response before proceeding to the commit step.**

---

## Final Step

Once all verification checks pass:

```bash
git add -A && git commit -m "PROMPT-09D: Hard-mask frame zone + stronger anti-border directives" && git push
```

Railway will auto-deploy after the push. Monitor the Railway dashboard to confirm the deploy completes without errors before closing this task.
