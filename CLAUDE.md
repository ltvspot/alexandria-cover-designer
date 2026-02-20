# CLAUDE.md — Codex Instructions for Alexandria Cover Designer

## Project Overview

You are building an automated pipeline that replaces the center illustrations on 99 classic book covers with 5 AI-generated artistic variants per cover. Read `PROJECT-STATE.md` for full technical context before starting any work.

## Repository Structure

- `src/` — All Python source code
- `config/` — Configuration files (book catalog, prompt templates)
- `scripts/` — Utility and execution scripts
- `tests/` — Test files
- `Codex Prompts/` — Per-phase implementation instructions (READ these)
- `Codex Output Answers/` — Save your output records here after each phase
- `Input Covers/` — READ ONLY source covers (99 folders, each with .ai/.jpg/.pdf)
- `Output Covers/` — Generated output (5 variants per cover)

## Critical Rules

1. **Read `PROJECT-STATE.md` FIRST** before any implementation work
2. **NEVER modify `PROJECT-STATE.md`** — it is managed by Cowork/Tim only
3. **NEVER modify files in `Input Covers/`** — read-only source material
4. **NEVER modify the ornamental borders, text, or layout on covers** — only the center circular illustration changes
5. **Output filenames must match input filenames exactly** (folder names without " copy" suffix)
6. **All outputs must maintain 3784×2777 pixels at 300 DPI**
7. **Save an output record** in `Codex Output Answers/` after completing each prompt

## Execution Protocol

For each prompt (numbered phase):

1. Read the prompt file from `Codex Prompts/`
2. Read `PROJECT-STATE.md` for context
3. Implement ALL features described
4. Run ALL verification checks — actual execution, not code review
5. If ANY check fails → fix → re-run → repeat until 100% PASS
6. Write output record to `Codex Output Answers/PROMPT-{ID}-OUTPUT.md`
7. Commit with message format: `feat: Prompt {ID} — {description}`
8. Push to master
9. Move to next prompt

## Output Record Format

Each output record must include:
- Summary of what was implemented
- Files modified/created
- Features implemented (with details)
- Verification checklist results (PASS/FAIL for each check)
- Notes on any issues or deviations

## Python Style

- Python 3.10+ with type hints
- Use pathlib.Path for all file operations
- Use dataclasses for structured data
- Handle errors gracefully with clear messages
- Log operations (use Python logging module)
- Environment variables via python-dotenv

## Key Technical Details

- Input JPGs are 3784×2777 at 300 DPI (full wraparound cover)
- The center illustration is a circular medallion (~1100px diameter) on the RIGHT side (front cover)
- It sits inside an ornate gold baroque frame
- The illustration must be composited to match the existing color temperature and style
- `.ai` files are Adobe Illustrator format (binary, ~30MB each)
- The pipeline must handle Unicode characters in folder/file names (accents, em-dashes, etc.)

## Dependencies

Core: Pillow, opencv-python, numpy, requests, python-dotenv
AI: replicate (or httpx for direct API), diffusers (for local generation)
Export: reportlab, pypdf (for PDF), svglib (for .ai workaround)
