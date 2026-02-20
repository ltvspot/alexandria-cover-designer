#!/bin/bash
# Alexandria Cover Designer — Main Pipeline Runner
#
# Usage:
#   ./scripts/run_pipeline.sh --dry-run                               # Preview first 20 titles (D23)
#   ./scripts/run_pipeline.sh --book 2 --all-models --variants 10    # Single-cover iteration
#   ./scripts/run_pipeline.sh --books 1-5 --batch-size 5             # Small batch
#   ./scripts/run_pipeline.sh --book 2 --variant 3 --no-resume       # Selective re-run
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load environment
if [ -f .env ]; then
    set -a; source .env; set +a
fi

echo "=== Alexandria Cover Designer Pipeline ==="
echo "Input:  ${INPUT_DIR:-Input Covers}"
echo "Output: ${OUTPUT_DIR:-Output Covers}"
echo ""

python3 -m src.pipeline "$@"
