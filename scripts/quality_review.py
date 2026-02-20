#!/usr/bin/env python3
"""Prompt 5 review tooling: /iterate, /review, fallback gallery, and API server."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from src import config
    from src import cover_compositor
    from src import image_generator
    from src.prompt_library import LibraryPrompt, PromptLibrary
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import cover_compositor  # type: ignore
    import image_generator  # type: ignore
    from prompt_library import LibraryPrompt, PromptLibrary  # type: ignore


logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REVIEW_DATA_PATH = PROJECT_ROOT / "data" / "review_data.json"
ITERATE_DATA_PATH = PROJECT_ROOT / "data" / "iterate_data.json"
SELECTIONS_PATH = PROJECT_ROOT / "data" / "variant_selections.json"
FALLBACK_HTML_PATH = PROJECT_ROOT / "data" / "review_gallery.html"
HISTORY_PATH = PROJECT_ROOT / "data" / "generation_history.json"
QUALITY_SCORES_PATH = PROJECT_ROOT / "data" / "quality_scores.json"


def create_comparison_grid(original_path: Path, variants_dir: Path, output_path: Path) -> Path:
    """Create side-by-side image: original + up to 5 variants."""
    images = [Image.open(original_path).convert("RGB")]
    variant_images = sorted(variants_dir.glob("Variant-*/*.jpg"))[:5]

    for path in variant_images:
        images.append(Image.open(path).convert("RGB"))

    thumb_w = 640
    thumb_h = 470
    gap = 18
    width = (thumb_w * len(images)) + (gap * (len(images) + 1))
    height = thumb_h + 100

    canvas = Image.new("RGB", (width, height), "#f6f2e8")
    draw = ImageDraw.Draw(canvas)

    x = gap
    labels = ["Original"] + [f"Variant {i}" for i in range(1, len(images))]
    for img, label in zip(images, labels):
        resized = img.resize((thumb_w, thumb_h), Image.LANCZOS)
        canvas.paste(resized, (x, 40))
        draw.text((x, 16), label, fill="#223")
        x += thumb_w + gap

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=92)
    return output_path


def build_review_dataset(
    output_dir: Path,
    *,
    input_dir: Path = config.INPUT_DIR,
    catalog_path: Path = config.BOOK_CATALOG_PATH,
    books: list[int] | None = None,
    max_books: int | None = None,
) -> list[dict[str, Any]]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if books:
        wanted = set(books)
        catalog = [row for row in catalog if int(row.get("number", 0)) in wanted]
    catalog = sorted(catalog, key=lambda row: int(row.get("number", 0)))
    if max_books:
        catalog = catalog[:max_books]

    quality_lookup = _load_quality_lookup(QUALITY_SCORES_PATH)
    rows: list[dict[str, Any]] = []

    for entry in catalog:
        number = int(entry.get("number", 0))
        folder_name = str(entry.get("folder_name", ""))
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]

        output_book = output_dir / folder_name
        input_book = input_dir / str(entry.get("folder_name", ""))
        original = _find_original_image(input_book)

        variants = []
        for variant_dir in sorted([p for p in output_book.glob("Variant-*") if p.is_dir()]):
            variant_num = _parse_variant_number(variant_dir.name)
            if variant_num is None:
                continue
            image = _find_first_jpg(variant_dir)
            if not image:
                continue
            variants.append(
                {
                    "variant": variant_num,
                    "label": f"Variant {variant_num}",
                    "image": _to_project_relative(image),
                    "quality_score": quality_lookup.get((number, variant_num)),
                }
            )

        rows.append(
            {
                "number": number,
                "title": entry.get("title", ""),
                "author": entry.get("author", ""),
                "folder": folder_name,
                "original": _to_project_relative(original) if original else "",
                "variants": sorted(variants, key=lambda item: item["variant"]),
                "best_quality_score": max(
                    [float(v["quality_score"]) for v in variants if isinstance(v.get("quality_score"), (int, float))],
                    default=0.0,
                ),
            }
        )

    return rows


def write_review_data(output_dir: Path, *, max_books: int | None = None) -> Path:
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "books": build_review_dataset(output_dir, max_books=max_books),
    }
    REVIEW_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return REVIEW_DATA_PATH


def write_iterate_data(*, prompts_path: Path = config.PROMPTS_PATH) -> Path:
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    library = PromptLibrary(config.PROMPT_LIBRARY_PATH)

    books = []
    for book in prompts.get("books", []):
        default_prompt = book.get("variants", [{}])[0].get("prompt", "") if book.get("variants") else ""
        books.append(
            {
                "number": int(book.get("number", 0)),
                "title": book.get("title", ""),
                "author": book.get("author", ""),
                "default_prompt": default_prompt,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": config.ALL_MODELS,
        "books": books,
        "style_anchors": [asdict(anchor) for anchor in library.get_style_anchors()],
        "prompt_library": [asdict(item) for item in library.get_prompts()],
    }

    ITERATE_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    ITERATE_DATA_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return ITERATE_DATA_PATH


def generate_review_gallery(
    output_dir: Path,
    output_path: Path = FALLBACK_HTML_PATH,
    *,
    max_books: int | None = None,
) -> Path:
    """Generate standalone fallback gallery with embedded data + localStorage."""
    data = {
        "books": build_review_dataset(output_dir, max_books=max_books),
    }

    html = f"""<!doctype html>
<html><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/><title>Review Gallery</title>
<style>
body{{font-family:Georgia,serif;background:#11274d;color:#f7ecd1;margin:0;padding:18px;}}
.grid{{display:grid;gap:14px;}}
.card{{background:#f8f3e5;color:#1b2740;border-radius:14px;padding:12px;}}
.images{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;}}
img{{width:100%;border-radius:8px;}}
</style></head><body>
<h1>Standalone Review Gallery</h1>
<button onclick='download()'>Export Selections JSON</button>
<div id='grid' class='grid'></div>
<script>
const data = {json.dumps(data, ensure_ascii=False)};
const selections = JSON.parse(localStorage.getItem('variantSelections') || '{{}}');
function render(){{
  const root=document.getElementById('grid');
  root.innerHTML='';
  data.books.forEach(book=>{{
    const card=document.createElement('section');
    card.className='card';
    card.innerHTML=`<h2>${{book.number}}. ${{book.title}}</h2><div>${{book.author}}</div><div class='images'></div>`;
    const images=card.querySelector('.images');
    const all=[{{variant:0,label:'Original',image:book.original}}, ...(book.variants||[])];
    all.forEach(item=>{{
      const checked = selections[String(book.number)]===item.variant ? 'checked' : '';
      const disabled = item.variant===0 ? 'disabled' : '';
      const box=`<label>${{item.label}} <input type='checkbox' data-book='${{book.number}}' data-variant='${{item.variant}}' ${{checked}} ${{disabled}} /></label>`;
      const el=document.createElement('div');
      el.innerHTML=`<img src='${{item.image}}'/>${{box}}`;
      images.appendChild(el);
    }});
    root.appendChild(card);
  }});
  document.querySelectorAll('input[data-book]').forEach(box=>{{
    box.onchange=()=>{{
      const b=box.dataset.book,v=Number(box.dataset.variant);
      if(box.checked) selections[b]=v;
      else if(selections[b]===v) selections[b]=0;
      localStorage.setItem('variantSelections', JSON.stringify(selections));
      render();
    }};
  }});
}}
function download(){{
  const blob=new Blob([JSON.stringify(selections,null,2)],{{type:'application/json'}});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download='variant_selections.json';a.click();URL.revokeObjectURL(url);
}}
render();
</script></body></html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def serve_review_webapp(output_dir: Path, port: int = 8001) -> None:
    """Serve /review and /iterate pages with lightweight API."""
    write_review_data(output_dir)
    write_iterate_data()
    generate_review_gallery(output_dir)

    lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            if path == "/review":
                self.path = "/src/static/review.html"
                return super().do_GET()
            if path == "/iterate":
                self.path = "/src/static/iterate.html"
                return super().do_GET()

            if path == "/api/review-data":
                return self._send_json(_load_json(REVIEW_DATA_PATH, {"books": []}))
            if path == "/api/iterate-data":
                return self._send_json(_load_json(ITERATE_DATA_PATH, {"books": [], "models": []}))
            if path == "/api/history":
                book = int(parse_qs(parsed.query).get("book", ["0"])[0])
                history_payload = _load_json(HISTORY_PATH, {"items": []})
                items = [item for item in history_payload.get("items", []) if int(item.get("book_number", 0)) == book]
                return self._send_json({"items": items[-200:]})

            return super().do_GET()

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            size = int(self.headers.get("Content-Length", "0"))
            body_raw = self.rfile.read(size) if size > 0 else b"{}"

            try:
                body = json.loads(body_raw.decode("utf-8"))
            except json.JSONDecodeError:
                body = {}

            if path == "/api/save-selections":
                SELECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
                with lock:
                    SELECTIONS_PATH.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
                return self._send_json({"ok": True, "path": str(SELECTIONS_PATH)})

            if path == "/api/save-prompt":
                with lock:
                    library = PromptLibrary(config.PROMPT_LIBRARY_PATH)
                    prompt = LibraryPrompt(
                        id=str(uuid.uuid4()),
                        name=str(body.get("name", "Saved Prompt")),
                        prompt_template=str(body.get("prompt_template", "{title}")),
                        style_anchors=list(body.get("style_anchors", [])),
                        negative_prompt=str(body.get("negative_prompt", "")),
                        source_book="iteration",
                        source_model="manual",
                        quality_score=float(body.get("quality_score", 0.75)),
                        saved_by="tim",
                        created_at=datetime.now(timezone.utc).isoformat(),
                        notes=str(body.get("notes", "saved from iterate page")),
                        tags=list(body.get("tags", [])) or ["iterative"],
                    )
                    library.save_prompt(prompt)
                write_iterate_data()
                return self._send_json({"ok": True, "prompt_id": prompt.id})

            if path == "/api/generate":
                book = int(body.get("book", 0))
                models = list(body.get("models", []))
                variants = int(body.get("variants", 5))
                prompt = str(body.get("prompt", ""))

                runtime = config.get_config()
                dry_run = not runtime.has_any_api_key()

                with lock:
                    results = image_generator.generate_single_book(
                        book_number=book,
                        prompts_path=runtime.prompts_path,
                        output_dir=runtime.tmp_dir / "generated",
                        models=models or runtime.all_models,
                        variants=variants,
                        prompt_text=prompt,
                        resume=False,
                        dry_run=dry_run,
                    )

                    if not dry_run:
                        regions = _load_json(runtime.config_dir / "cover_regions.json", {})
                        try:
                            cover_compositor.composite_all_variants(
                                book_number=book,
                                input_dir=runtime.input_dir,
                                generated_dir=runtime.tmp_dir / "generated",
                                output_dir=runtime.tmp_dir / "composited",
                                regions=regions,
                            )
                        except Exception as exc:
                            logger.error("Compositing after generate failed: %s", exc)

                serialized = []
                fit_overlay_rel = None
                fit_overlay = runtime.tmp_dir / "composited" / str(book) / "fit_overlay.png"
                if fit_overlay.exists():
                    fit_overlay_rel = str(fit_overlay.relative_to(PROJECT_ROOT))

                for row in results:
                    image_rel = str(row.image_path.relative_to(PROJECT_ROOT)) if row.image_path else None
                    composed = None
                    if row.image_path:
                        candidate = _resolve_composited_candidate(row.image_path)
                        if candidate and candidate.exists():
                            composed = str(candidate.relative_to(PROJECT_ROOT))
                    serialized.append(
                        {
                            "book_number": row.book_number,
                            "variant": row.variant,
                            "model": row.model,
                            "prompt": row.prompt,
                            "image_path": image_rel,
                            "composited_path": composed,
                            "success": row.success,
                            "error": row.error,
                            "generation_time": row.generation_time,
                            "cost": row.cost,
                            "dry_run": row.dry_run,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "fit_overlay_path": fit_overlay_rel,
                        }
                    )

                with lock:
                    _append_generation_history(HISTORY_PATH, serialized)

                message = "Dry-run generation plan created (no API keys configured)." if dry_run else "Generation complete."
                write_review_data(output_dir)
                return self._send_json({"ok": True, "message": message, "results": serialized})

            return self._send_json({"ok": False, "error": "Unknown endpoint"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args):
            logger.info("%s", fmt % args)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    logger.info("Review webapp running at http://127.0.0.1:%d/review", port)
    logger.info("Iteration page running at http://127.0.0.1:%d/iterate", port)
    server.serve_forever()


def _resolve_composited_candidate(image_path: Path) -> Path | None:
    runtime = config.get_config()
    if len(image_path.parts) < 2:
        return None

    variant = _parse_variant(image_path.stem)
    if variant <= 0:
        return None

    # Structure A: tmp/generated/{book}/variant_n.png
    if image_path.parent.name.isdigit():
        book = image_path.parent.name
        return runtime.tmp_dir / "composited" / book / f"variant_{variant}.jpg"

    # Structure B: tmp/generated/{book}/{model}/variant_n.png
    if image_path.parent.parent.name.isdigit():
        book = image_path.parent.parent.name
        model = image_path.parent.name
        return runtime.tmp_dir / "composited" / book / model / f"variant_{variant}.jpg"

    return None


def _parse_variant(stem: str) -> int:
    if "variant_" not in stem:
        return 0
    token = stem.split("variant_", 1)[1].split("_", 1)[0]
    try:
        return int(token)
    except ValueError:
        return 0


def _find_original_image(input_book: Path) -> Path | None:
    if not input_book.exists():
        return None
    jpgs = sorted(input_book.glob("*.jpg"))
    return jpgs[0] if jpgs else None


def _find_first_jpg(folder: Path) -> Path | None:
    jpgs = sorted(folder.glob("*.jpg"))
    return jpgs[0] if jpgs else None


def _parse_variant_number(name: str) -> int | None:
    if not name.startswith("Variant-"):
        return None
    try:
        return int(name.split("-", 1)[1])
    except ValueError:
        return None


def _load_quality_lookup(path: Path) -> dict[tuple[int, int], float]:
    payload = _load_json(path, {"scores": []})
    rows = payload.get("scores", []) if isinstance(payload, dict) else []
    lookup: dict[tuple[int, int], float] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            book = int(row.get("book_number", 0))
            variant = int(row.get("variant_id", 0))
            score = float(row.get("overall_score", 0.0))
        except (TypeError, ValueError):
            continue
        key = (book, variant)
        lookup[key] = max(lookup.get(key, 0.0), score)

    return lookup


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return default
    return default


def _append_generation_history(path: Path, items: list[dict[str, Any]]) -> None:
    payload = _load_json(path, {"items": []})
    history = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(history, list):
        history = []
    history.extend(items)
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": history[-5000:],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


def _to_project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _parse_books(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    values: set[int] = set()
    for piece in raw.split(","):
        token = piece.strip()
        if not token:
            continue
        if "-" in token:
            start, end = token.split("-", 1)
            for value in range(min(int(start), int(end)), max(int(start), int(end)) + 1):
                values.add(value)
        else:
            values.add(int(token))
    return sorted(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 5 review and iteration tooling")
    parser.add_argument("--output-dir", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--books", type=str, default=None)
    parser.add_argument("--max-books", type=int, default=None)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--grid", type=Path, default=None, help="Create one comparison grid image")
    parser.add_argument("--book", type=int, default=None, help="Book number for comparison grid")

    args = parser.parse_args()

    if args.grid and args.book:
        catalog = json.loads(config.BOOK_CATALOG_PATH.read_text(encoding="utf-8"))
        entry = next((row for row in catalog if int(row.get("number", 0)) == args.book), None)
        if not entry:
            raise KeyError(f"Book {args.book} not in catalog")

        folder_name = str(entry["folder_name"])
        if folder_name.endswith(" copy"):
            folder_name = folder_name[:-5]

        original = _find_original_image(config.INPUT_DIR / str(entry["folder_name"]))
        variants_dir = args.output_dir / folder_name
        if not original:
            raise FileNotFoundError("Original cover not found")
        create_comparison_grid(original, variants_dir, args.grid)
        print(f"Wrote comparison grid to {args.grid}")
        return 0

    books = _parse_books(args.books)
    review_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "books": build_review_dataset(args.output_dir, books=books, max_books=args.max_books),
    }
    REVIEW_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_DATA_PATH.write_text(json.dumps(review_data, indent=2, ensure_ascii=False), encoding="utf-8")
    write_iterate_data()
    generate_review_gallery(args.output_dir, max_books=args.max_books)

    if args.serve:
        serve_review_webapp(args.output_dir, port=args.port)
        return 0

    print(f"Wrote review data: {REVIEW_DATA_PATH}")
    print(f"Wrote iterate data: {ITERATE_DATA_PATH}")
    print(f"Wrote fallback gallery: {FALLBACK_HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
