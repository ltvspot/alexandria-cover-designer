# Prompt 3B — Format Export (.ai, .jpg, .pdf)

**Priority**: HIGH — Produces final deliverables
**Scope**: `src/output_exporter.py`
**Depends on**: Prompt 3A (composited JPGs must exist)
**Estimated time**: 45-60 minutes

---

## Context

Read `PROJECT-STATE.md`. After Prompt 3A we have composited JPG covers in the output directory. Now we need to export each variant in all 3 required formats: `.ai`, `.jpg`, `.pdf` — matching the input file specifications exactly.

---

## Task

Create `src/output_exporter.py` that exports each composited cover to:

### 1. JPG Export
- Already produced by Prompt 3A — verify specs: 3784×2777, 300 DPI, RGB, quality 95
- If not already correct, re-save with proper settings

### 2. PDF Export
- Single-page PDF containing the full cover at print quality
- Page size matches the physical dimensions (12.613" × 9.257" at 300 DPI)
- Embedded image at full resolution, no compression artifacts
- Use reportlab or pypdf

### 3. AI (Adobe Illustrator) Export
- This is the hardest format. Options:
  - **Option A (Recommended)**: Create a PDF/AI dual-format file (Illustrator can open PDFs)
    - Use PDF with Illustrator-compatible metadata
    - Save with `.ai` extension
  - **Option B**: Embed the JPG in an SVG, convert to AI via Illustrator scripting
  - **Option C**: If the original `.ai` files are actually PDFs with `.ai` extension (common),
    simply follow the same approach as PDF export with the `.ai` extension
- **CHECK**: First examine the original `.ai` files to determine their actual format
  (many Illustrator files are actually PDFs with an AI extension)

### Output Folder Structure

```
Output Covers/{folder_name}/
├── Variant-1/
│   ├── {file_base}.ai
│   ├── {file_base}.jpg
│   └── {file_base}.pdf
├── Variant-2/
│   └── ...
└── ...
```

Where `{folder_name}` is the input folder name WITHOUT the " copy" suffix, and `{file_base}` matches the input filename base.

---

## Verification Checklist

1. `py_compile` passes — PASS/FAIL
2. Check original `.ai` file format (is it actually a PDF internally?) — documented — PASS/FAIL
3. Export Moby Dick variant 1 → 3 files created (.ai, .jpg, .pdf) — PASS/FAIL
4. JPG: 3784×2777, 300 DPI, RGB — PASS/FAIL
5. PDF: opens correctly, single page, full resolution image — PASS/FAIL
6. .AI: opens in Illustrator (or is valid PDF with AI metadata) — PASS/FAIL
7. Filenames match input: `Moby Dick_ Or, The Whale - Herman Melville.{ext}` — PASS/FAIL
8. Folder name: `2. Moby Dick_ Or, The Whale - Herman Melville` (no " copy") — PASS/FAIL
9. Export all 5 variants for one book → 15 files total — PASS/FAIL
10. Batch export for 5 test books → all files correct — PASS/FAIL
