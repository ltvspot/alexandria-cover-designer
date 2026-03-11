# Codex Task — PROMPT-09E: Book-Specific Visual Motifs for All 99 Books

## Priority: HIGH — Deploy After 09D

## Context

Currently only ~25 books have specific visual motifs in `_motif_for_book()`. All other books fall through to a generic fallback that produces identical romantic-couple-kissing scenes regardless of the actual book content. This must be fixed so every book gets a unique, recognizable cover illustration.

## What To Do

Follow **PROMPT-09E-BOOK-MOTIFS.md** exactly:

1. **`src/prompt_generator.py`** — Add 68 new `BookMotif` entries to the `_motif_for_book()` function. Each entry uses title matching on the normalized `title_author` string.

2. Insert all new entries AFTER the existing specific book entries (moby dick, alice, dracula, etc.) but BEFORE the author-fallback section (the `if "austen" in author:` block).

3. Every new motif has been crafted to be visually specific to its book — naming concrete objects, settings, characters, and scenes that are unique and immediately recognizable.

## Testing

After adding all entries, verify no book falls through to generic:
```python
python -c "
from src.prompt_generator import _motif_for_book
import json
from pathlib import Path

catalog = json.loads(Path('config/book_catalog.json').read_text())
generic = 'pivotal narrative tableau'
for book in catalog:
    motif = _motif_for_book(book)
    if generic in motif.iconic_scene:
        print(f'GENERIC FALLBACK: {book[\"number\"]}. {book[\"title\"]}')
"
```
Expected output: NO books should print (zero generic fallbacks).

## Final Step

```bash
git add -A && git commit -m "PROMPT-09E: Book-specific motifs for all 99 books" && git push
```

Railway will auto-deploy after push.
