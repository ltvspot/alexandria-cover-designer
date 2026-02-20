# Prompt 1B — Prompt Engineering (Book-Specific AI Art Prompts)

**Priority**: HIGH — Determines illustration quality
**Scope**: `src/prompt_generator.py`, `config/book_prompts.json`
**Depends on**: Nothing (can run in parallel with 1A)
**Estimated time**: 45-60 minutes

---

## Context

Read `PROJECT-STATE.md` for full context. Read `config/book_catalog.json` for the list of all 99 books. Read `config/prompt_templates.json` for the 5 variant templates.

We need to generate 5 unique, book-specific illustration prompts for each of the 99 books. Each prompt must produce a classical oil painting style circular illustration depicting something directly relevant to that specific book.

---

## Task

Create `src/prompt_generator.py` that generates detailed, book-specific prompts, and output `config/book_prompts.json` containing all 495 prompts (99 books × 5 variants).

### For Each Book, Generate 5 Variant Prompts

Using `config/prompt_templates.json` as the template framework:

1. **Iconic Scene** — The most famous scene (e.g., Moby Dick: "a massive white whale breaching from stormy seas, harpoons embedded in its flesh, a small whaling boat being tossed by waves")
2. **Character Portrait** — Main character (e.g., Moby Dick: "Captain Ahab standing on the deck of the Pequod, one ivory leg, weathered face staring at the horizon, stormy seas behind him")
3. **Symbolic/Allegorical** — Themes (e.g., Moby Dick: "a man's silhouette consumed by a colossal whale shadow, symbolizing obsession and the vastness of nature")
4. **Setting/Landscape** — Key location (e.g., Moby Dick: "a 19th century whaling ship on a vast dark ocean under dramatic clouds, distant whale spout visible")
5. **Dramatic Moment** — Climactic scene (e.g., Moby Dick: "the final chase, Captain Ahab hurling a harpoon at the great white whale as the ship splinters apart in towering waves")

### Prompt Quality Requirements

Each prompt must:
- Be 40-80 words (detailed enough for good generation, not so long it confuses the model)
- Include the style anchors from `prompt_templates.json`
- Specify "circular vignette composition" (the illustration will be cropped into a circle)
- Include "no text, no letters, no words, no watermarks"
- Be historically/literarily accurate to the source material
- Describe visual elements (colors, composition, lighting, mood)
- NOT mention the book title or author in the prompt (the image should stand on its own)

### Code Structure

```python
# src/prompt_generator.py

from pathlib import Path

def generate_prompts_for_book(book: dict) -> dict:
    """Generate 5 variant prompts for a single book.

    Args:
        book: Entry from book_catalog.json with title, author, number

    Returns:
        Dict with variant_1 through variant_5, each containing:
        - prompt: The full generation prompt
        - negative_prompt: What to avoid
        - description: Brief human-readable description of the scene
    """
    ...

def generate_all_prompts(catalog_path: Path) -> list:
    """Generate prompts for all 99 books."""
    ...

def save_prompts(prompts: list, output_path: Path):
    """Save all prompts to config/book_prompts.json."""
    ...
```

### Implementation Notes

- You MUST have specific literary knowledge for each book. Use the title and author to infer the content.
- For less well-known titles, generate reasonable prompts based on the title, author, and genre context.
- The prompts file will be reviewed by Tim before generation — it must be human-readable.
- Include the negative prompt from `prompt_templates.json` with every entry.

---

## Verification Checklist

1. `python3 -c "import py_compile; py_compile.compile('src/prompt_generator.py', doraise=True)"` — PASS/FAIL
2. `config/book_prompts.json` exists and is valid JSON — PASS/FAIL
3. Contains exactly 99 book entries — PASS/FAIL
4. Each book has exactly 5 variants — PASS/FAIL
5. Total prompt count: 495 — PASS/FAIL
6. Every prompt includes "circular vignette composition" — PASS/FAIL
7. Every prompt includes "no text" or "no letters" — PASS/FAIL
8. Every prompt is 40-80 words — PASS/FAIL
9. No prompt mentions the book title or author name — PASS/FAIL
10. Spot-check: Moby Dick prompts reference whales/sea/Ahab — PASS/FAIL
11. Spot-check: Alice in Wonderland prompts reference rabbit hole/tea party/queen — PASS/FAIL
12. Spot-check: Dracula prompts reference vampires/castle/Transylvania — PASS/FAIL
13. Spot-check: Pride and Prejudice prompts reference Regency era/English countryside/ballroom — PASS/FAIL
14. Spot-check: Frankenstein prompts reference the creature/laboratory/lightning — PASS/FAIL
15. Every negative_prompt matches the template — PASS/FAIL
