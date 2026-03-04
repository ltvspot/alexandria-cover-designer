#!/usr/bin/env bash
set -euo pipefail

BOOK_ID="${1:-1}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
OUTPUT_DIR="$PROJECT_ROOT/tmp/test_composites/book_${BOOK_ID}"
mkdir -p "$OUTPUT_DIR"

echo "=== Alexandria Compositor Integration Test ==="
echo "Book: $BOOK_ID"
echo

echo "Step 1: Resolve source assets..."
SOURCE_INFO_JSON="$OUTPUT_DIR/source_info.json"
"$PYTHON_BIN" - <<'PY' "$BOOK_ID" "$SOURCE_INFO_JSON"
import json
import sys
from pathlib import Path

book_id = int(sys.argv[1])
out_path = Path(sys.argv[2])
project_root = out_path.parents[3]

sys.path.insert(0, str(project_root))
from src import config
from src import pdf_compositor

runtime = config.get_config("classics")
source_pdf = pdf_compositor.find_source_pdf_for_book(
    input_dir=runtime.input_dir,
    book_number=book_id,
    catalog_path=runtime.book_catalog_path,
)

source_jpg = None
if runtime.book_catalog_path.exists():
    try:
        catalog = json.loads(runtime.book_catalog_path.read_text(encoding="utf-8"))
    except Exception:
        catalog = []
    for row in catalog:
        if not isinstance(row, dict):
            continue
        if int(row.get("number", 0) or 0) != book_id:
            continue
        folder = runtime.input_dir / str(row.get("folder_name", "")).strip()
        if folder.exists():
            jpgs = sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}])
            if jpgs:
                source_jpg = jpgs[0]
        break

payload = {
    "source_pdf": str(source_pdf) if source_pdf else "",
    "source_jpg": str(source_jpg) if source_jpg else "",
}
out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(json.dumps(payload, indent=2))
PY

SOURCE_PDF="$("$PYTHON_BIN" - <<'PY' "$SOURCE_INFO_JSON"
import json,sys
from pathlib import Path
row=json.loads(Path(sys.argv[1]).read_text())
print(row.get('source_pdf',''))
PY
)"
SOURCE_JPG="$("$PYTHON_BIN" - <<'PY' "$SOURCE_INFO_JSON"
import json,sys
from pathlib import Path
row=json.loads(Path(sys.argv[1]).read_text())
print(row.get('source_jpg',''))
PY
)"

if [ -z "$SOURCE_JPG" ] || [ ! -f "$SOURCE_JPG" ]; then
  echo "ERROR: No source JPG found for book $BOOK_ID"
  exit 2
fi

echo
echo "Step 2: Build sample art + composite..."
ART_PATH="$OUTPUT_DIR/sample_illustration.png"
OUT_JPG="$OUTPUT_DIR/test_output.jpg"
OUT_PDF="$OUTPUT_DIR/test_output.pdf"
OUT_AI="$OUTPUT_DIR/test_output.ai"

"$PYTHON_BIN" - <<'PY' "$ART_PATH" "$SOURCE_JPG"
import sys
from pathlib import Path
from PIL import Image, ImageDraw

art_path = Path(sys.argv[1])
source_jpg = Path(sys.argv[2])
with Image.open(source_jpg) as src:
    w, h = src.size
side = max(1024, min(w, h))
img = Image.new("RGB", (side, side), (16, 39, 84))
draw = ImageDraw.Draw(img)
for i in range(0, side, max(8, side // 40)):
    color = (20 + (i % 180), 120 + (i % 100), 200 - (i % 120))
    draw.rectangle((0, i, side, min(side, i + max(4, side // 60))), fill=color)
draw.ellipse((int(side*0.18), int(side*0.16), int(side*0.82), int(side*0.84)), outline=(240, 190, 90), width=max(4, side // 120))
img.save(art_path, format="PNG")
print(str(art_path))
PY

if [ -n "$SOURCE_PDF" ] && [ -f "$SOURCE_PDF" ]; then
  echo "Using PDF compositor"
  "$PYTHON_BIN" - <<'PY' "$SOURCE_PDF" "$ART_PATH" "$OUT_PDF" "$OUT_JPG" "$OUT_AI"
import sys
from src.pdf_compositor import composite_cover_pdf

result = composite_cover_pdf(
    source_pdf_path=sys.argv[1],
    ai_art_path=sys.argv[2],
    output_pdf_path=sys.argv[3],
    output_jpg_path=sys.argv[4],
    output_ai_path=sys.argv[5],
)
print(result)
PY
else
  echo "Source PDF unavailable; using JPG fallback compositor"
  "$PYTHON_BIN" - <<'PY' "$SOURCE_JPG" "$ART_PATH" "$OUT_JPG" "$BOOK_ID"
import json
import sys
from pathlib import Path
from src import config
from src.cover_compositor import composite_single

source_jpg = Path(sys.argv[1])
art_path = Path(sys.argv[2])
out_jpg = Path(sys.argv[3])
book_id = int(sys.argv[4])
runtime = config.get_config("classics")
regions_path = config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
regions = json.loads(regions_path.read_text(encoding="utf-8")) if regions_path.exists() else {}
region = regions.get("consensus_region", {})
for row in regions.get("covers", []):
    if int(row.get("cover_id", 0) or 0) == book_id:
        region = row
        break
composite_single(
    cover_path=source_jpg,
    illustration_path=art_path,
    region=region,
    output_path=out_jpg,
)
print(str(out_jpg))
PY
fi

echo
echo "Step 3: Run strict verification..."
if [ -f "$OUT_PDF" ] && [ -n "$SOURCE_PDF" ] && [ -f "$SOURCE_PDF" ]; then
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/verify_composite.py" \
    "$OUT_JPG" \
    --source-pdf "$SOURCE_PDF" \
    --output-pdf "$OUT_PDF" \
    --strict
else
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/verify_composite.py" \
    "$OUT_JPG" \
    "$SOURCE_JPG" \
    --strict
fi

echo
echo "Integration verification complete."
