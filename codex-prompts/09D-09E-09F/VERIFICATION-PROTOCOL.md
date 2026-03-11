# Compositor Verification Protocol — MANDATORY

**This protocol is NON-NEGOTIABLE. Every compositor change must pass verification before committing.**

Both Claude Cowork and Codex MUST follow this protocol. No exceptions.

---

## The Problem This Solves

Neither Claude Cowork nor Codex can visually inspect composited cover output. Previous attempts (07A through 07H) were "correct" according to code review but failed when visually inspected by Tim. This protocol replaces human visual inspection with automated pixel-level verification.

---

## Two Verification Modes

### PDF Mode (Preferred — 9 checks)
Used when the source PDF is available. Provides the strongest verification because it can directly compare against the PDF's internal SMask and raster data.

```bash
python scripts/verify_composite.py <output.jpg> --source-pdf <source.pdf> --output-pdf <output.pdf> --strict
```

| # | Check | What it verifies | Normal | Strict |
|---|-------|-----------------|--------|--------|
| 1 | Dimensions | Output is 3784×2777 | Exact | Exact |
| 2 | Ornament zone | Frame pixels match source PDF render | 99.5% | 99.9% |
| 3 | Art zone | Inner circle pixels differ from source | 90% | 95% |
| 4 | Centering | Art center at (2864, 1620) | 5px | 3px |
| 5 | Transition quality | No harsh gradients at boundary | <2% | <2% |
| 6 | SMask integrity | Output PDF SMask is BIT-IDENTICAL to source | 100% | 100% |
| 7 | Frame pixels | Im0 frame ring (SMask 5–250) CMYK preserved | 99.99% | 99.99% |
| 8 | AI Art Border | No decorative border in AI art frame zone (--ai-art) | <0.08 edge | <0.08 edge |
| 9 | Visual Frame | Rendered frame zone matches source PDF visually | <5.0 diff | <5.0 diff |

### JPG Mode (Fallback — 5 checks)
Used when only the source JPG is available. Uses radial zone comparison.

```bash
python scripts/verify_composite.py <output.jpg> <source_cover.jpg> --strict
```

| # | Check | What it verifies | Normal | Strict |
|---|-------|-----------------|--------|--------|
| 1 | Dimensions | Output is 3784×2777 | Exact | Exact |
| 2 | Ornament zone | r>480 pixels match source JPG | 99.5% | 99.9% |
| 3 | Art zone | r<370 pixels differ from source | 90% | 95% |
| 4 | Centering | Art center at (2864, 1620) | 5px | 3px |
| 5 | Transition quality | Clean transition zone | <2% | <2% |

---

## The Verification Script

**File:** `scripts/verify_composite.py`

**Usage (PDF mode — preferred):**
```bash
python scripts/verify_composite.py <composited.jpg> --source-pdf <source.pdf> --output-pdf <output.pdf> --ai-art <generated.png> --strict
```

**Usage (JPG mode — fallback):**
```bash
python scripts/verify_composite.py <composited.jpg> <source_cover.jpg> --strict
```

**Exit codes:**
- `0` = ALL CHECKS PASSED — safe to commit
- `1` = ONE OR MORE CHECKS FAILED — DO NOT commit, fix the issue
- `2` = ERROR (missing files, wrong dimensions)

---

## When to Run

### For Codex:
1. After ANY change to `src/pdf_compositor.py` or `src/cover_compositor.py`
2. After ANY change to SMask handling, frame masking, or compositing logic
3. Before EVERY `git commit` that touches compositor code
4. Always use `--strict` mode

**How Codex runs it (PDF mode):**
```bash
# Generate test composite
python -c "
from src.pdf_compositor import composite_cover_pdf
composite_cover_pdf(
    source_pdf_path='tmp/source_pdfs/fairy_tales.pdf',
    ai_art_path='test_fixtures/sample_illustration.png',
    output_pdf_path='tmp/test_output.pdf',
    output_jpg_path='tmp/test_output.jpg',
)"

# Verify (PDF mode, strict, with AI art border check)
python scripts/verify_composite.py tmp/test_output.jpg \
    --source-pdf tmp/source_pdfs/fairy_tales.pdf \
    --output-pdf tmp/test_output.pdf \
    --ai-art test_fixtures/sample_illustration.png \
    --strict
```

**How Codex runs it (JPG fallback mode):**
```bash
# Generate test composite
python -c "
from src.cover_compositor import composite_single
from pathlib import Path
composite_single(
    cover_path=Path('config/covers/cover_001.jpg'),
    illustration_path=Path('test_fixtures/sample_illustration.png'),
    region={'region_type': 'circle'},
    output_path=Path('tmp/test_composite.jpg'),
)"

# Verify (JPG mode, strict)
python scripts/verify_composite.py tmp/test_composite.jpg config/covers/cover_001.jpg --strict
```

If exit code is not 0, DO NOT commit. Fix the issue and re-run.

### For Claude Cowork:
1. When reviewing Codex's compositor changes, ask: "Did verify_composite.py pass in --strict mode?"
2. If Codex didn't run it, instruct Codex to run it before accepting the change
3. When writing compositor prompts, always include the verification mandate block (below)

---

## Adding to Every Compositor Prompt

Every Codex prompt that touches the compositor MUST include this block at the end:

```
## MANDATORY: Run Verification Before Committing

After making changes, generate a test composite and verify:

    python scripts/verify_composite.py <output.jpg> --source-pdf <source.pdf> --output-pdf <output.pdf> --ai-art <generated.png> --strict

    OR (if no source PDF available):

    python scripts/verify_composite.py <output.jpg> <source_cover.jpg> --strict

All checks must PASS. If any check FAILS, do not commit.
Report the full output of verify_composite.py in your response.
```

---

## Convenience Integration Test

```bash
# Run full integration test for a specific book
bash scripts/test_compositor_integration.sh <book_id>

# Run for multiple books
bash scripts/test_compositor_integration.sh 1
bash scripts/test_compositor_integration.sh 9
bash scripts/test_compositor_integration.sh 25
```

---

## Known Geometry Reference

| Parameter | Value | Notes |
|-----------|-------|-------|
| Cover size | 3784 × 2777 | All 99 covers |
| Medallion center | (2864, 1620) | 99 covers identical, 1 differs by 2px |
| Outer frame radius | 500 | Gold border outer edge |
| Frame inner edge | 378–480px | Varies by angle (irregular scrollwork) |
| Art zone | r < 370px | Always clear of frame |
| Ornament zone | r > 480px | Always frame |
| Transition | 370–480px | Scrollwork, beads, detail |
| Embedded image | 2480 × 2470 | CMYK, Im0 at xref 19 |
| SMask | 2480 × 2470 | Grayscale, at xref 24 |
| SMask frame ring | values 5–250 | Semi-transparent ornamental frame |
| SMask inner circle | values >250 | Fully opaque, illustration area |
| SMask outer area | values <5 | Fully transparent, hidden by background |

---

## PDF-Based Approach (Current — PROMPT-09 Series)

The PDF compositor (PROMPT-09A) works at the PDF object level:
1. Opens the source PDF with pikepdf
2. Extracts Im0 (CMYK raster) and SMask (grayscale transparency)
3. Composites: AI art fills everything, then frame ring pixels (SMask 5–250) are restored from original
4. Writes composited data back into Im0, keeping SMask unchanged
5. Renders PDF to JPG via PyMuPDF at 300 DPI

This makes frame corruption **structurally impossible** — there is no edge detection, approximation, or reconstruction. The SMask from the original designer is the frame boundary, period.

### PROMPT-09D Frame Protection Enhancement

PROMPT-09D added a critical safeguard: before compositing, the compositor now zeros out all AI art pixels in the frame ring zone (SMask 5–250) and outer transparent zone (SMask <5) to white CMYK `[0,0,0,0]`. This means even if the AI art generates its own decorative border, those pixels are blanked before the source frame data is laid on top. Only the original gold filigree ornaments are visible.

### PROMPT-09F Verification Upgrade

PROMPT-09F added two new checks:
- **Check 8 (AI Art Border Detection)**: Examines the AI art image before compositing using Sobel edge detection on the frame zone annular ring (r=420–480 in embedded image space). Detects decorative border elements. Requires `--ai-art` flag.
- **Check 9 (Visual Frame Comparison)**: Renders both source and output PDFs at 300 DPI and compares the frame zone pixel-by-pixel at the rendered RGB level — catching visual differences that CMYK-level checks miss.
