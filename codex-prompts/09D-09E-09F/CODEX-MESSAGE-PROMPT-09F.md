# Codex Task — PROMPT-09F: Verification Protocol Upgrade

## Priority: HIGH — Deploy After 09D

## Context

The current verification script passes even when AI art has its own decorative border that visually corrupts the original gold ornaments. The checks validate CMYK data integrity but miss visual-level frame corruption. Two new checks are needed.

## What To Do

Follow **PROMPT-09F-VERIFICATION-UPGRADE.md** exactly:

1. **`scripts/verify_composite.py`** — Add Check 8 (AI Art Border Detection): uses Sobel edge detection on the AI art's annular ring zone to detect decorative borders before compositing. Requires new `--ai-art` CLI flag.

2. **`scripts/verify_composite.py`** — Add Check 9 (Visual Frame Comparison): renders both source and output PDFs to RGB at 300 DPI via PyMuPDF, then compares the frame zone pixel-by-pixel at the rendered level.

3. **CLI update** — Add `--ai-art` optional argument to `argparse`. Check 8 is skipped with a warning if not provided.

4. **`scripts/test_compositor_integration.sh`** — Update to pass `--ai-art` flag when available.

5. **Dependencies** — Ensure `opencv-python` is in requirements if not already present.

## Verification

After changes, run the script against a known-good composite and a known-bad one (with AI border) to confirm Check 8 and Check 9 work correctly.

## Final Step

```bash
git add -A && git commit -m "PROMPT-09F: Verification upgrade — border detection + visual frame comparison" && git push
```

Railway will auto-deploy after push.
