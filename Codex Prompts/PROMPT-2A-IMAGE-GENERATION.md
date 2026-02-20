# Prompt 2A — Image Generation Pipeline

**Priority**: HIGH — Core image generation
**Scope**: `src/image_generator.py`, `src/config.py`
**Depends on**: Prompt 1B (prompts must exist)
**Estimated time**: 60-90 minutes (code) + generation runtime

---

## Context

Read `PROJECT-STATE.md` for full context. Read `config/book_prompts.json` for all 495 prompts.

We need to batch-generate 495 illustrations (99 books × 5 variants) using an AI image generation API. Primary target: FLUX.1 [schnell] via Replicate API (≈$1.50 total). Must handle rate limiting, retries, and incremental progress.

---

## Task

Create `src/image_generator.py` — a robust batch image generation pipeline.

### Core Features

1. **API Integration**:
   - Primary: Replicate API (FLUX.1 schnell model)
   - Fallback: fal.ai or direct HTTP to alternative providers
   - API key from environment variable (`REPLICATE_API_TOKEN`)

2. **Batch Processing**:
   - Process all 495 prompts sequentially (or with configurable concurrency)
   - Save each generated image to `tmp/generated/{book_number}/variant_{n}.png`
   - Skip already-generated images (resume support)
   - Progress reporting: `[42/495] Generating Variant 3 for "Moby Dick"...`

3. **Error Handling**:
   - Retry on API errors (429, 500, 502, 503) with exponential backoff
   - Max 3 retries per image
   - Log failures and continue (don't abort entire batch)
   - Save failure log to `data/generation_failures.json`

4. **Rate Limiting**:
   - Configurable delay between requests (default 1 second)
   - Respect API rate limits

5. **Image Post-Processing**:
   - Ensure output is 1024×1024 PNG
   - Apply circular crop/mask (the illustration will be composited into a circle)
   - Basic quality check: reject blank/solid-color images

### Code Structure

```python
# src/image_generator.py

from pathlib import Path
from dataclasses import dataclass

@dataclass
class GenerationResult:
    book_number: int
    variant: int
    prompt: str
    image_path: Path | None
    success: bool
    error: str | None
    generation_time: float

def generate_image(prompt: str, negative_prompt: str, params: dict) -> bytes:
    """Generate a single image via the configured AI API."""
    ...

def generate_batch(prompts_path: Path, output_dir: Path, resume: bool = True) -> list[GenerationResult]:
    """Generate all images from the prompts file."""
    ...

def generate_single_book(book_number: int, prompts_path: Path, output_dir: Path) -> list[GenerationResult]:
    """Generate all 5 variants for a single book (useful for testing)."""
    ...
```

### Also Create `src/config.py`

```python
# src/config.py

from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
INPUT_DIR = PROJECT_ROOT / os.getenv("INPUT_DIR", "Input Covers")
OUTPUT_DIR = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "Output Covers")
TMP_DIR = PROJECT_ROOT / "tmp"
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"

# AI Generation
AI_PROVIDER = os.getenv("AI_PROVIDER", "replicate")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
VARIANTS_PER_COVER = int(os.getenv("VARIANTS_PER_COVER", "5"))
BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "1"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.0"))

# Quality
MIN_QUALITY_SCORE = float(os.getenv("MIN_QUALITY_SCORE", "0.6"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
```

---

## Verification Checklist

### Syntax
1. `py_compile` passes for `src/image_generator.py` — PASS/FAIL
2. `py_compile` passes for `src/config.py` — PASS/FAIL

### Single Image
3. Generate 1 image for book #2 (Moby Dick), variant 1 — PASS/FAIL
4. Generated image is valid PNG, 1024×1024 — PASS/FAIL
5. Image visually depicts a whale/sea scene (manual check) — PASS/FAIL

### Batch (Small)
6. Generate all 5 variants for book #2 (Moby Dick) — PASS/FAIL
7. All 5 images saved to `tmp/generated/2/` — PASS/FAIL
8. All 5 images are visually distinct — PASS/FAIL

### Resume
9. Re-run generation for book #2 — skips existing images — PASS/FAIL
10. Progress output shows "Skipping..." for existing images — PASS/FAIL

### Error Handling
11. Set invalid API key → graceful error, logged to failures.json — PASS/FAIL
12. Generation failure doesn't abort the batch — PASS/FAIL

### Full Batch (if API key available)
13. Run full batch for all 99 books → 495 images generated — PASS/FAIL
14. `data/generation_failures.json` lists any failures — PASS/FAIL
15. Success rate ≥ 95% (≥470/495) — PASS/FAIL

---

## Notes

- Start with a single book to verify quality before running the full batch
- The full batch at $0.003/image costs about $1.50 — confirm with Tim before running
- If no API key is available, implement a "dry run" mode that saves prompts without generating
- Generated images are intermediate — they'll be composited in Prompt 3A
