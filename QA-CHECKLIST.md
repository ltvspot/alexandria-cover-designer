# Alexandria Cover Designer — QA Checklist

> Use this checklist after every phase to verify output quality. Each check must PASS before moving to the next phase.

---

## Per-Image Checks

- [ ] Image is circular/medallion shaped (matches original frame)
- [ ] Image content is directly relevant to the book title
- [ ] Style is classical oil painting / renaissance — NOT photorealistic, NOT cartoonish
- [ ] No obvious AI artifacts (distorted hands, melting faces, text artifacts, etc.)
- [ ] Color temperature matches the warm golden/navy aesthetic of the cover
- [ ] Image resolution is sufficient (≥1024×1024 before compositing)
- [ ] No watermarks or model signatures visible

## Per-Cover Checks

- [ ] Ornamental borders are IDENTICAL to original (pixel-perfect outside the center region)
- [ ] Center illustration is properly centered within the ornamental frame
- [ ] No visible seam or edge artifacts where illustration meets frame
- [ ] Color blending between illustration and frame background is smooth
- [ ] Text (title, author, subtitle) is fully legible and unchanged
- [ ] Spine text and back cover are completely untouched

## Per-Variant Folder Checks

- [ ] Contains exactly 3 files: .ai, .jpg, .pdf
- [ ] Filenames match input filenames exactly (no " copy" suffix)
- [ ] JPG is 3784×2777 at 300 DPI
- [ ] PDF contains the same cover at print quality
- [ ] .ai file is valid (or documented workaround applied)
- [ ] All 5 variants are visually distinct from each other

## Batch Checks

- [ ] All 99 covers have 5 variant folders each
- [ ] Output folder structure matches specification in PROJECT-STATE.md
- [ ] No missing or empty variant folders
- [ ] Total output count: 99 × 5 × 3 = 1,485 files
- [ ] Google Drive sync completed (if applicable)

## Style Consistency Checks

- [ ] All illustrations share the same "classical painting" aesthetic
- [ ] No variant looks jarringly different in style from others for the same book
- [ ] Lighting direction is consistent with the gold ornament lighting
- [ ] Color palette stays within warm tones appropriate for the navy/gold theme
