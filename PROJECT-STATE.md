# Alexandria Cover Designer — Project State

> **Purpose**: This is the living source of truth for the entire project. When a conversation compacts or a new chat starts, paste or reference this file to restore full context instantly. Update this file after every completed phase.
>
> **Last updated**: 2026-02-20 — **Project initialized. Folder structure created. Planning phase.**
>
> **OWNERSHIP: This file may ONLY be edited by Claude (Cowork) or Tim. Codex must NEVER edit, modify, or overwrite this file. Codex should READ it for context only.**

---

## Project Summary

**Goal**: Replace the AI-generated center illustrations on 99 existing book covers with 5 higher-quality artistic variants per cover, producing 495 total variant covers. The ornamental borders, text, and layout remain untouched — only the circular medallion illustration in the center-right of the front cover changes.

**Why**: The current center illustrations look "too AI-generated." We want classical oil painting / renaissance illustration quality that feels hand-painted, not machine-made.

---

## Architecture (Final Design)

```
Input Cover (.ai/.jpg/.pdf)
    → [src/cover_analyzer.py] → Extract design region coordinates + metadata
    → [src/prompt_generator.py] → Generate 5 book-specific art prompts per title
    → [src/image_generator.py] → Generate 5 variant illustrations via AI model
    → [src/cover_compositor.py] → Composite new illustrations into cover template
    → [src/output_exporter.py] → Export as .ai/.jpg/.pdf (matching input formats)
    → 5 variant folders per cover, each with 3 files
```

**Stack**: Python + Pillow/OpenCV (image processing) → FLUX.1 or SDXL (AI generation via API or local) → ReportLab/pypdf (PDF export) → svglib or Illustrator scripting (.ai export)

---

## Phase Status

| Phase | Description | Status | Notes |
|-------|-------------|--------|-------|
| **0. Project Setup** | Folder structure, PROJECT-STATE.md, CLAUDE.md, prompts | ✅ COMPLETE | This document |
| **1A. Cover Analysis** | Analyze input covers: extract center design region, detect ornament boundaries | ⏳ PLANNED | |
| **1B. Prompt Engineering** | Build title→prompt mapping for all 99 books, 5 style variants each | ⏳ PLANNED | |
| **2A. Image Generation Pipeline** | Batch generate 495 illustrations via chosen AI model | ⏳ PLANNED | |
| **2B. Quality Gate** | Auto-filter bad generations, score quality, flag for review | ⏳ PLANNED | |
| **3A. Cover Composition** | Composite new illustrations into existing cover templates | ⏳ PLANNED | |
| **3B. Format Export** | Export each variant as .ai, .jpg, .pdf matching input specs | ⏳ PLANNED | |
| **4A. Batch Orchestration** | End-to-end pipeline: input folder → output folder structure | ⏳ PLANNED | |
| **4B. Google Drive Sync** | Upload output to Google Drive folder structure | ⏳ PLANNED | |
| **5. Visual QA** | Side-by-side comparison tool, Tim picks best variants | ⏳ PLANNED | |

---

## Critical Technical Facts

### Input Covers
- **Count**: 99 covers (numbered 1–100, #12 missing)
- **Location**: `Input Covers/` (local) + [Google Drive](https://drive.google.com/drive/folders/1ybFYDJk7Y3VlbsEjRAh1LOfdyVsHM_cS?usp=sharing)
- **Formats per cover**: `.ai`, `.jpg`, `.pdf` (3 files each)
- **JPG specs**: 3784×2777 pixels, 300 DPI, RGB, ~4.8MB each
- **Layout**: Full wraparound cover (front + spine + back)
  - Front cover is RIGHT side of the image
  - Spine is the narrow center strip
  - Back cover is LEFT side of the image

### Cover Design Anatomy
```
┌─────────────────┬──────┬─────────────────────┐
│   BACK COVER    │SPINE │    FRONT COVER       │
│                 │      │                      │
│  Quote          │ Title│   TITLE              │
│  Author quote   │(vert)│   Subtitle           │
│  Description    │      │                      │
│                 │      │   ┌──────────┐       │
│                 │      │   │ORNAMENTAL│       │
│                 │      │   │ FRAME    │       │
│                 │      │   │          │       │
│                 │      │   │ ●CENTER● │       │
│                 │      │   │ ●IMAGE●  │       │
│                 │      │   │          │       │
│                 │      │   └──────────┘       │
│  Alexandria     │      │                      │
│  logo           │      │   AUTHOR NAME        │
│                 │      │                      │
│  Gold ornaments │      │   Gold ornaments     │
└─────────────────┴──────┴─────────────────────┘
```

### Design Constants (DO NOT CHANGE)
- **Background**: Navy blue (#1a2744 approximately)
- **Ornaments**: Gold/bronze decorative corner pieces + frame around center image
- **Center frame**: Circular/medallion with ornate gold baroque border
- **Typography**: Gold text, serif font (likely Garamond or similar)
- **Spine**: Title vertical, small Alexandria logo at bottom

### Center Illustration (THE PART WE'RE REPLACING)
- **Shape**: Circular, sits inside the ornamental frame
- **Position**: Center-right of full cover (on front cover)
- **Approximate region**: ~1100px diameter circle
- **Current style**: AI-generated scenes relating to book content
- **Target style**: Classical oil painting / renaissance illustration feel
- **Must depict**: Scene or motif directly relevant to the specific book title

### Output Specifications
- **Per cover**: 5 variant folders (Variant-1 through Variant-5)
- **Per variant**: 3 files (.ai, .jpg, .pdf) — same filenames as input
- **Folder naming**: Match input folder name exactly (without " copy" suffix)
- **Resolution**: Must match input (3784×2777, 300 DPI)
- **Output location**: Google Drive folder: https://drive.google.com/drive/folders/1Vr184ZsX3k38xpmZkd8g2vwB5y9LYMRC?usp=sharing

### Output Folder Structure
```
Output Covers/
├── 1. A Room with a View - E. M. Forster/
│   ├── Variant-1/
│   │   ├── A Room with a View - E. M. Forster.ai
│   │   ├── A Room with a View - E. M. Forster.jpg
│   │   └── A Room with a View - E. M. Forster.pdf
│   ├── Variant-2/
│   │   └── ...
│   ├── Variant-3/
│   │   └── ...
│   ├── Variant-4/
│   │   └── ...
│   └── Variant-5/
│       └── ...
├── 2. Moby Dick; Or, The Whale - Herman Melville/
│   ├── Variant-1/
│   └── ...
└── ...
```

---

## AI Image Generation Strategy

### Primary Tool: FLUX.1 [schnell] via Replicate API
- **Cost**: ~$0.003/image → $1.50 for 500 images
- **Quality**: State-of-the-art, excellent with classical/painterly prompts
- **Fallback**: SDXL + ClassipeintXL LoRA (local, $0)
- **Alternative API**: fal.ai, SiliconFlow, Google Imagen 3

### Prompt Strategy (5 variants per book)
Each book gets 5 different illustration approaches:
1. **Iconic Scene** — The most famous/recognizable scene from the book
2. **Character Portrait** — Main character in period-appropriate setting
3. **Symbolic/Allegorical** — Abstract representation of the book's themes
4. **Setting/Landscape** — Key location from the story
5. **Dramatic Moment** — A pivotal or climactic scene

### Style Anchors (apply to ALL prompts)
```
"classical oil painting, masterpiece quality, warm golden lighting,
renaissance art style, detailed brushwork, gallery-quality illustration,
circular vignette composition, rich color palette, dramatic chiaroscuro"
```

---

## Folder Structure

```
Alexandria Cover designer/
├── Input Covers/           ← 99 folders with .ai/.jpg/.pdf (READ ONLY)
├── Sample Output style covers/  ← Tim's approved style examples
├── Output Covers/          ← Generated variants (→ synced to Google Drive)
├── src/                    ← Source code
│   ├── cover_analyzer.py       ← Phase 1A: Extract design region
│   ├── prompt_generator.py     ← Phase 1B: Book→prompt mapping
│   ├── image_generator.py      ← Phase 2A: AI image generation
│   ├── quality_gate.py         ← Phase 2B: Quality scoring/filtering
│   ├── cover_compositor.py     ← Phase 3A: Composite into template
│   ├── output_exporter.py      ← Phase 3B: Export .ai/.jpg/.pdf
│   ├── pipeline.py             ← Phase 4A: End-to-end orchestrator
│   ├── gdrive_sync.py          ← Phase 4B: Google Drive upload
│   └── config.py               ← Configuration + env vars
├── config/
│   ├── book_catalog.json       ← All 99 books: number, title, author, genre, themes
│   └── prompt_templates.json   ← 5 variant prompt templates
├── scripts/
│   ├── run_pipeline.sh         ← Main execution script
│   ├── generate_catalog.py     ← Build book_catalog.json from folder names
│   └── quality_review.py       ← Side-by-side comparison tool
├── tests/
│   └── test_unit.py            ← Unit tests
├── Codex Prompts/          ← Per-phase build instructions for Codex
├── Codex Output Answers/   ← Codex responses saved after each phase
├── data/                   ← Runtime data (gitignored)
├── logs/                   ← Logs (gitignored)
├── tmp/                    ← Temp files (gitignored)
├── PROJECT-STATE.md        ← THIS FILE
├── CLAUDE.md               ← Codex instructions
├── QA-CHECKLIST.md         ← Quality assurance checklist
├── .gitignore
├── .env.example            ← Environment variable template
└── requirements.txt        ← Python dependencies
```

---

## Google Drive Links

| Resource | URL |
|----------|-----|
| **Input Covers** | https://drive.google.com/drive/folders/1ybFYDJk7Y3VlbsEjRAh1LOfdyVsHM_cS?usp=sharing |
| **Output Destination** | https://drive.google.com/drive/folders/1Vr184ZsX3k38xpmZkd8g2vwB5y9LYMRC?usp=sharing |

---

## Golden Rules (Apply to ALL Phases)

1. **NEVER modify the ornamental borders, text, or layout** — only the center illustration changes
2. **NEVER modify Input Covers** — they are read-only source material
3. **Output filenames MUST match input filenames exactly** (minus " copy" suffix on folders)
4. **All outputs must be 300 DPI, 3784×2777 pixels**
5. **Each illustration must be directly relevant to the specific book title**
6. **Style must be classical oil painting — NOT photorealistic, NOT cartoonish, NOT obviously AI**
7. **Do NOT modify PROJECT-STATE.md** (Codex reads only; Cowork/Tim updates)
