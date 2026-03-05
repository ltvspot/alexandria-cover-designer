FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    /opt/venv/bin/pip install --no-cache-dir pytest-cov

FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8001

WORKDIR /app

# Runtime system dependencies for Pillow/OpenCV and health checks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    tini && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv

COPY src/ src/
RUN mkdir -p config scripts
COPY scripts/quality_review.py scripts/quality_review.py
COPY config/catalogs.json config/catalogs.json
COPY config/book_catalog.json config/book_catalog.json
COPY config/book_prompts.json config/book_prompts.json
COPY config/book_catalog_test-catalog.json config/book_catalog_test-catalog.json
COPY config/book_prompts_test-catalog.json config/book_prompts_test-catalog.json
COPY config/cover_regions.json config/cover_regions.json
COPY config/cover_regions_test-catalog.json config/cover_regions_test-catalog.json
COPY config/frame_mask.png config/frame_mask.png
COPY scripts/extract_frame_overlays.py scripts/extract_frame_overlays.py
COPY scripts/verify_composite.py scripts/verify_composite.py
COPY config/prompt_templates.json config/prompt_templates.json
COPY config/prompt_library.json config/prompt_library.json
COPY config/cover_templates.json config/cover_templates.json
COPY config/model_prompt_overrides.json config/model_prompt_overrides.json
COPY config/genre_presets.json config/genre_presets.json
COPY config/mockup_templates.json config/mockup_templates.json
COPY config/mockup_background_prompts.json config/mockup_background_prompts.json
COPY favicon.ico favicon.ico
COPY .env.example .env.example

# Seed lightweight placeholder inputs for the default test catalog in stateless deploys.
RUN mkdir -p tmp/test_catalog_input/"1. Sample Book - Test Author" \
    tmp/test_catalog_input/"2. Another Story - Demo Writer" \
    data "Output Covers" "Output Covers Test" "Input Covers" && \
    python - <<'PY'
from PIL import Image, ImageDraw

items = [
    ("tmp/test_catalog_input/1. Sample Book - Test Author/Sample Book - Test Author.jpg", "Sample Book"),
    ("tmp/test_catalog_input/2. Another Story - Demo Writer/Another Story - Demo Writer.jpg", "Another Story"),
]
for path, label in items:
    img = Image.new("RGB", (1200, 1800), "#0a2f5a")
    draw = ImageDraw.Draw(img)
    draw.rectangle((80, 80, 1120, 1720), outline="#d4af37", width=12)
    draw.text((120, 840), label, fill="#f6e7a2")
    img.save(path, format="JPEG", quality=82, optimize=True)
PY
RUN chown -R app:app /app

USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "exec python3 scripts/quality_review.py --serve --host ${HOST:-0.0.0.0} --port ${PORT:-8001} --output-dir \"Output Covers\""]
