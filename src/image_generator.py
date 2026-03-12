"""Prompt 2A image generation pipeline with provider abstraction and all-model mode."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import logging
import random
import re
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import numpy as np
import requests
from PIL import Image, ImageDraw

try:  # pragma: no cover - optional dependency path
    from scipy import ndimage as _ndi
except Exception:  # pragma: no cover
    _ndi = None

try:
    from src import config
    from src import content_relevance
    from src import safe_json
    from src import similarity_detector
    from src import prompt_generator
    from src.logger import get_logger
    from src.prompt_library import PromptLibrary
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import content_relevance  # type: ignore
    import safe_json  # type: ignore
    import similarity_detector  # type: ignore
    import prompt_generator  # type: ignore
    from logger import get_logger  # type: ignore
    from prompt_library import PromptLibrary  # type: ignore

logger = get_logger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

MODEL_STYLE_PROFILES: list[dict[str, str]] = [
    {
        "style": "dramatic cinematic classic",
        "detail": "deep chiaroscuro, tactile brush texture, clean scene geometry",
        "palette": "deep navy, gold, warm amber, vivid cobalt contrast",
        "composition": "full-bleed narrative scene with centered focal subject",
    },
    {
        "style": "heroic painterly realism",
        "detail": "confident brushwork, atmospheric depth, strong silhouette hierarchy",
        "palette": "ultramarine, vermilion, antique gold, luminous highlights",
        "composition": "single dominant subject with layered depth and crop-safe margins",
    },
    {
        "style": "narrative chromatic realism",
        "detail": "painterly texture with grounded environment detail and scene-first storytelling",
        "palette": "vibrant sapphire, teal, amber, and luminous brass highlights",
        "composition": "edge-to-edge narrative scene with natural perspective and no medallion-like framing",
    },
    {
        "style": "bold graphic poster",
        "detail": "high-contrast value grouping, expressive shape rhythm, clear focal tension",
        "palette": "vibrant jewel tones with a dark anchor and bright highlights",
        "composition": "dominant foreground subject with dynamic layered background",
    },
    {
        "style": "ethereal painterly",
        "detail": "soft atmospheric diffusion, expressive edges, dreamlike depth",
        "palette": "luminous teal, peach, and gold with saturated accents",
        "composition": "centered narrative moment with flowing directional light",
    },
    {
        "style": "dark moody gothic",
        "detail": "inky shadows, selective highlights, dramatic depth cues, no decorative overlays",
        "palette": "deep charcoal with electric blue and gold accents",
        "composition": "close-up focal subject with clean edge-to-edge scene composition",
    },
    {
        "style": "illustrated hand-crafted",
        "detail": "ink-and-wash feel, visible hand-crafted marks, energetic brush texture",
        "palette": "earth pigments with vivid turquoise and crimson accents",
        "composition": "scene-led narrative tableau with diagonal motion",
    },
    {
        "style": "baroque adventure painting",
        "detail": "dramatic light choreography, layered atmospheric perspective, dramatic motion",
        "palette": "rich emerald, crimson, ultramarine, and luminous gold",
        "composition": "high-energy centered action with crop-safe margins",
    },
]

MODEL_PROVIDER_HINTS: tuple[tuple[str, str], ...] = (
    ("midjourney", "Emphasize artistic direction, stylized brushwork, and cinematic composition cues."),
    ("dalle", "Use precise scene layout instructions and clear object placement relationships."),
    ("gpt-image", "Use precise scene layout instructions and clear object placement relationships."),
    ("openai", "Use precise scene layout instructions and clear object placement relationships."),
    ("flux", "Prioritize tactile lighting realism and material texture fidelity."),
    ("gemini", "Prioritize grounded narrative scenes with natural perspective; avoid emblematic or circular compositions."),
    ("stable-diffusion", "Include technical style keywords and painterly medium guidance."),
    ("sdxl", "Include technical style keywords and painterly medium guidance."),
)

STRICT_SCENE_GUARDRAIL = (
    "Mandatory output rules: produce only the scene artwork. "
    "No text, no letters, no numbers, no words, no logos, no title design, no labels, "
    "no ribbons, no banners, no plaques, no inscriptions, no calligraphy, no medallion ring, "
    "no medallion composition, no circular vignette, no circular framing, no circular crop, "
    "no frame, no border, no decorative edge, no seal, no coin, no emblem."
)
NO_ORNAMENT_GUARDRAIL = (
    "No filigree, no scrollwork, no arabesques, no ornamental curls, no decorative flourishes, "
    "no black ornamental silhouettes, no lace-like cutout motifs."
)
VIVID_COLOR_GUARDRAIL = (
    "Color direction: vivid, high-saturation painterly palette with rich contrast and luminous highlights."
)
GENERATION_GUARDRAIL = f"{STRICT_SCENE_GUARDRAIL} {NO_ORNAMENT_GUARDRAIL} {VIVID_COLOR_GUARDRAIL}"
MAX_CONTENT_VIOLATION_SCORE = 0.24
TEXT_ARTIFACT_HARD_SCORE_FLOOR = 0.20
TEXT_ARTIFACT_HARD_TEXT_PENALTY = 0.62
TEXT_ARTIFACT_HARD_BAND_RATIO = 0.165
TEXT_ARTIFACT_HARD_TINY_EFFECTIVE = 0.030
TEXT_ARTIFACT_ORNAMENT_TEXT_PENALTY = 0.40
TEXT_ARTIFACT_ORNAMENT_BAND_MIN = 0.075
TEXT_ARTIFACT_ORNAMENT_BAND_MAX = 0.155
TEXT_ARTIFACT_ORNAMENT_TINY_MIN = 0.017
ARTIFACT_RETRY_LIMIT = 3
ARTIFACT_RETRY_APPEND = (
    "Retry instruction: scene artwork only. Absolutely no words, letters, numbers, logos, labels, ribbons, "
    "banners, plaques, medallion rings, medallion compositions, circular frames, circular vignettes, "
    "circular crops, ornamental borders, decorative edges, "
    "filigree, scrollwork, arabesques, ornamental curls, black ornamental silhouettes, or lace-like cutout motifs."
)
ALEXANDRIA_NEGATIVE_PROMPT = (
    "No text, no letters, no words, no numbers, no titles, no author names, no typography, no captions, "
    "no labels, no watermarks, no signatures, no inscriptions of any kind. No modern elements, no photography, "
    "no 3D rendering, no digital art aesthetic, no gradients on background, no neon colours, no sans-serif fonts, "
    "no minimalist design, no stock photo look, no cartoonish style, no anime influence, no spelling mistakes, "
    "no blurry medallion illustration, no medallion composition, no circular vignette, no circular framing, "
    "no off-centre composition, no white or light backgrounds."
)
_PROMPT_REMOVAL_PATTERNS: tuple[str, ...] = (
    r"\bcircular vignette composition\b",
    r"(?<!no )\bcircular(?:\s+medallion)?(?:\s+frame|\s+framing)?\b",
    r"\btypography(?:[- ]led)?\b",
    r"\btext[- ]safe\b",
    r"\btitle[- ]safe\b",
    r"\bnameplate\b",
    r"\blogo(?:s)?\b",
    r"\bwatermark(?:s)?\b",
    r"\bribbon(?:\s+banner)?\b",
    r"(?<!no )\bfiligree\b",
    r"(?<!no )\bscroll(?:work)?\b",
    r"(?<!no )\barabesque(?:s)?\b",
    r"(?<!no )\btracery\b",
    r"(?<!no )\bflourish(?:es)?\b",
    r"(?<!no )\bbotanical ornament\b",
    r"(?<!no )\bornamental arches?\b",
    r"(?<!no )\blace(?:-like)?(?:\s+cutout)?(?:\s+motifs?)?\b",
    r"\bplaque\b",
    r"\bseal\b",
    r"\binner(?:\s+frame|\s+ring|\s+border)?\b",
    r"(?<!no )\bdecorative(?:\s+edge|\s+frame|\s+border)?\b",
    r"(?<!no )\bornamental(?:\s+border|\s+frame|\s+edge)?\b",
    r"(?<!no )\bmedallion(?:\s+(?:zone|opening|window|ring|frame|border|composition))?\b",
    r"\bgilt ornament language\b",
)


def _host_matches_allowlist(host: str, pattern: str) -> bool:
    host_token = str(host or "").strip().lower()
    allow = str(pattern or "").strip().lower()
    if not host_token or not allow:
        return False
    if allow in {"*", "any"}:
        return True
    if allow.startswith("*.") and len(allow) > 2:
        root = allow[2:]
        return host_token == root or host_token.endswith(f".{root}")
    return host_token == allow or host_token.endswith(f".{allow}")


def _sanitize_prompt_text(prompt: str) -> str:
    text = " ".join(str(prompt or "").split())
    if not text:
        return text
    for pattern in _PROMPT_REMOVAL_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    # Cleanup artifacts created by removing forbidden tokens from "no ..." clauses.
    text = re.sub(r"\bno\s*,\s*no\b", "no", text, flags=re.IGNORECASE)
    text = re.sub(r"\bno,\s*(?=no\b)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bno,\s*(?=[\.,;:!?]|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*no\s*,", ", ", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*,+", ", ", text)
    return text.strip(" ,")


def _guardrailed_prompt(prompt: str) -> str:
    base = _sanitize_prompt_text(prompt)
    if not base:
        return GENERATION_GUARDRAIL
    text = f"{GENERATION_GUARDRAIL} {base}".strip()
    return " ".join(text.split())


def _prompt_reference_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", str(value or "").lower())
    return [token for token in tokens if len(token) >= 4]


def _validate_prompt_relevance(prompt: str, book_title: str, book_author: str) -> str:
    """Ensure prompt keeps strong title/author anchoring before provider dispatch."""
    base_prompt = " ".join(str(prompt or "").split())
    title = str(book_title or "").strip()
    author = str(book_author or "").strip()
    if not title:
        return base_prompt

    prompt_lower = base_prompt.lower()
    title_tokens = _prompt_reference_tokens(title)
    author_tokens = _prompt_reference_tokens(author)
    token_pool = title_tokens + author_tokens
    has_reference = any(token in prompt_lower for token in token_pool if token)
    if has_reference:
        return base_prompt

    motif_scene = ""
    try:
        motif = prompt_generator._motif_for_book({"title": title, "author": author})  # type: ignore[attr-defined]
        motif_scene = str(getattr(motif, "iconic_scene", "") or "").strip()
    except Exception:
        motif_scene = ""

    prefix_parts = [f"Book cover illustration for '{title}'"]
    if author:
        prefix_parts[0] = f"{prefix_parts[0]} by {author}"
    if motif_scene:
        prefix_parts.append(f"Primary scene anchor: {motif_scene}")
    prefix = ". ".join(prefix_parts).strip().rstrip(".") + "."
    logger.warning("Prompt lacked explicit book reference. Prepending title/motif anchor for '%s'.", title)
    if not base_prompt:
        return prefix
    return f"{prefix} {base_prompt}".strip()


def _is_artifact_generation_error(message: str) -> bool:
    token = str(message or "").strip().lower()
    if not token:
        return False
    return any(
        marker in token
        for marker in (
            "text_or_banner_artifact",
            "inner_frame_or_ring_artifact",
            "rectangular_frame_artifact",
            "circular_crop_artifact",
            "content guardrail",
        )
    )


def _artifact_retry_prompt(*, prompt: str, retry_index: int) -> str:
    hardened = (
        f"{prompt} {ARTIFACT_RETRY_APPEND} "
        f"Retry #{int(retry_index)}: increase color contrast and keep only one clear focal subject."
    ).strip()
    return _guardrailed_prompt(hardened)


def _is_high_confidence_text_artifact(*, content_score: float, metrics: dict[str, float]) -> bool:
    def _metric(name: str, default: float = 0.0) -> float:
        try:
            return float(metrics.get(name, default))
        except (TypeError, ValueError):
            return default

    text_penalty = _metric("text_penalty")
    text_band_ratio = _metric("text_band_ratio")
    tiny_effective = _metric("tiny_effective")

    # Ornament-like black cutout signatures often evade the old high-score thresholds.
    ornament_signature = (
        text_penalty >= TEXT_ARTIFACT_ORNAMENT_TEXT_PENALTY
        and TEXT_ARTIFACT_ORNAMENT_BAND_MIN <= text_band_ratio <= TEXT_ARTIFACT_ORNAMENT_BAND_MAX
        and tiny_effective >= TEXT_ARTIFACT_ORNAMENT_TINY_MIN
    )
    if ornament_signature:
        return True

    if text_penalty >= TEXT_ARTIFACT_HARD_TEXT_PENALTY:
        return True

    if float(content_score) < TEXT_ARTIFACT_HARD_SCORE_FLOOR:
        return False

    return (
        text_band_ratio >= TEXT_ARTIFACT_HARD_BAND_RATIO
        or tiny_effective >= TEXT_ARTIFACT_HARD_TINY_EFFECTIVE
    )


@dataclass(slots=True)
class GenerationResult:
    """Result for one generated image."""

    book_number: int
    variant: int
    prompt: str
    model: str
    image_path: Path | None
    success: bool
    error: str | None
    generation_time: float
    cost: float
    provider: str
    skipped: bool = False
    dry_run: bool = False
    attempts: int = 0
    failure_meta: dict[str, Any] = field(default_factory=dict)
    similarity_warning: str | None = None
    similar_to_book: int | None = None
    distinctiveness_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["image_path"] = str(self.image_path) if self.image_path else None
        return payload


class GenerationError(Exception):
    """Terminal generation error."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RetryableGenerationError(GenerationError):
    """Generation error that should be retried."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message, status_code=status_code)


def _summarize_error_payload(payload: str, *, limit: int = 240) -> str:
    text = str(payload or "").strip()
    if not text:
        return ""
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return text[:limit]

    queue: list[Any] = [
        body.get("error"),
        body.get("message"),
        body.get("detail"),
        body.get("details"),
    ]
    while queue:
        item = queue.pop(0)
        if isinstance(item, dict):
            for key in ("message", "detail", "error", "details", "reason"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:limit]
                if isinstance(value, (dict, list)):
                    queue.append(value)
        elif isinstance(item, list):
            queue.extend(item)
        elif isinstance(item, str) and item.strip():
            return item.strip()[:limit]

    compact = json.dumps(body, ensure_ascii=True)
    return compact[:limit]


class BaseProvider:
    """Provider interface."""

    name = "base"

    def __init__(
        self,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
        runtime: config.Config | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.runtime = runtime

    def generate(self, prompt: str, negative_prompt: str, width: int, height: int, seed: int | None = None) -> Image.Image:
        raise NotImplementedError

    def _assert_outbound_url(self, url: str) -> None:
        runtime = self.runtime or config.get_config()
        allowed = [str(item).strip().lower() for item in runtime.outbound_allowlist_domains if str(item).strip()]
        if not allowed:
            return
        host = str(urlparse(url).hostname or "").strip().lower()
        if not host:
            raise GenerationError(f"Outbound URL missing host: {url}")
        for token in allowed:
            if _host_matches_allowlist(host, token):
                return
        raise GenerationError(f"Outbound URL blocked by allowlist: host={host}")


class SyntheticProvider(BaseProvider):
    """Offline synthetic generator used when API keys are unavailable."""

    name = "synthetic"

    def generate(self, prompt: str, negative_prompt: str, width: int, height: int, seed: int | None = None) -> Image.Image:
        del negative_prompt
        del seed
        prompt_lower = prompt.lower()
        image = Image.new("RGB", (width, height), (26, 39, 68))
        draw = ImageDraw.Draw(image, "RGBA")

        if any(token in prompt_lower for token in ("whale", "sea", "ocean", "ship", "ahab")):
            self._draw_whale_scene(draw, width, height)
        elif any(token in prompt_lower for token in ("dracula", "vampire", "castle", "gothic")):
            self._draw_gothic_scene(draw, width, height)
        elif any(token in prompt_lower for token in ("oil painting", "chiaroscuro", "dramatic")):
            self._draw_oil_scene(draw, width, height)
        else:
            self._draw_classical_scene(draw, width, height)

        self._overlay_engraving_texture(draw, width, height)
        return image

    @staticmethod
    def _draw_whale_scene(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        draw.rectangle((0, int(height * 0.55), width, height), fill=(19, 65, 118, 220))

        for idx in range(14):
            y = int(height * 0.55 + idx * (height * 0.028))
            draw.arc(
                (-80, y - 26, width + 80, y + 26),
                0,
                180,
                fill=(120, 176, 219, 170),
                width=3,
            )

        draw.ellipse(
            (
                int(width * 0.18),
                int(height * 0.30),
                int(width * 0.82),
                int(height * 0.72),
            ),
            fill=(215, 221, 232, 235),
        )
        draw.polygon(
            [
                (int(width * 0.18), int(height * 0.52)),
                (int(width * 0.05), int(height * 0.60)),
                (int(width * 0.19), int(height * 0.64)),
            ],
            fill=(192, 203, 220, 225),
        )

        draw.polygon(
            [
                (int(width * 0.52), int(height * 0.73)),
                (int(width * 0.75), int(height * 0.73)),
                (int(width * 0.68), int(height * 0.82)),
                (int(width * 0.46), int(height * 0.82)),
            ],
            fill=(108, 78, 54, 240),
        )
        draw.line(
            (
                int(width * 0.60),
                int(height * 0.74),
                int(width * 0.60),
                int(height * 0.57),
            ),
            fill=(224, 198, 158, 230),
            width=4,
        )
        draw.polygon(
            [
                (int(width * 0.60), int(height * 0.58)),
                (int(width * 0.74), int(height * 0.66)),
                (int(width * 0.60), int(height * 0.66)),
            ],
            fill=(240, 231, 211, 195),
        )

    @staticmethod
    def _draw_gothic_scene(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        draw.rectangle((0, 0, width, height), fill=(29, 22, 42, 220))
        draw.ellipse(
            (int(width * 0.62), int(height * 0.10), int(width * 0.90), int(height * 0.38)),
            fill=(176, 43, 59, 210),
        )
        draw.rectangle(
            (int(width * 0.22), int(height * 0.40), int(width * 0.52), int(height * 0.84)),
            fill=(17, 14, 25, 230),
        )
        draw.ellipse(
            (int(width * 0.58), int(height * 0.36), int(width * 0.82), int(height * 0.74)),
            fill=(38, 30, 45, 230),
        )

    @staticmethod
    def _draw_oil_scene(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        draw.rectangle((0, 0, width, height), fill=(68, 54, 42, 210))
        draw.ellipse(
            (int(width * 0.10), int(height * 0.10), int(width * 0.46), int(height * 0.46)),
            fill=(248, 196, 112, 150),
        )
        draw.polygon(
            [
                (0, height),
                (int(width * 0.5), int(height * 0.58)),
                (width, height),
            ],
            fill=(22, 18, 26, 135),
        )
        draw.ellipse(
            (int(width * 0.32), int(height * 0.34), int(width * 0.70), int(height * 0.84)),
            fill=(125, 88, 68, 205),
        )

    @staticmethod
    def _draw_classical_scene(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        draw.rectangle((0, 0, width, height), fill=(42, 53, 72, 210))
        draw.ellipse(
            (int(width * 0.15), int(height * 0.15), int(width * 0.85), int(height * 0.85)),
            fill=(146, 123, 90, 145),
        )
        draw.rectangle(
            (int(width * 0.25), int(height * 0.45), int(width * 0.75), int(height * 0.80)),
            fill=(92, 78, 62, 185),
        )

    @staticmethod
    def _overlay_engraving_texture(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        step = max(6, width // 120)
        for y in range(0, height, step):
            draw.line((0, y, width, y + step // 2), fill=(233, 205, 158, 36), width=1)


class OpenAIProvider(BaseProvider):
    """OpenAI Images API."""

    name = "openai"

    def generate(self, prompt: str, negative_prompt: str, width: int, height: int, seed: int | None = None) -> Image.Image:
        if not self.api_key:
            raise GenerationError("Missing OPENAI_API_KEY")

        endpoint = "https://api.openai.com/v1/images/generations"
        self._assert_outbound_url(endpoint)
        seeded_prompt = f"{prompt}\nVariation seed: {seed}" if seed is not None else prompt
        payload = {
            "model": self.model,
            "prompt": f"{seeded_prompt}\nAvoid: {negative_prompt}",
            "size": f"{width}x{height}",
        }
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise RetryableGenerationError(
                f"OpenAI temporary error {response.status_code}: {_summarize_error_payload(response.text, limit=240)}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise GenerationError(
                f"OpenAI error {response.status_code}: {_summarize_error_payload(response.text, limit=300)}",
                status_code=response.status_code,
            )

        body = response.json()
        candidate = (body.get("data") or [{}])[0]
        if isinstance(candidate, dict):
            encoded = candidate.get("b64_json")
            if encoded:
                image_bytes = base64.b64decode(encoded)
                return Image.open(io.BytesIO(image_bytes)).convert("RGB")
            image_url = candidate.get("url")
            if image_url:
                return _download_image(str(image_url), timeout=self.timeout)
        raise GenerationError("OpenAI response missing image payload")


class OpenRouterProvider(BaseProvider):
    """OpenRouter image endpoint (OpenAI-compatible schema)."""

    name = "openrouter"

    def generate(self, prompt: str, negative_prompt: str, width: int, height: int, seed: int | None = None) -> Image.Image:
        if not self.api_key:
            raise GenerationError("Missing OPENROUTER_API_KEY")

        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        self._assert_outbound_url(endpoint)
        seeded_prompt = f"{prompt}\nVariation seed: {seed}" if seed is not None else prompt
        runtime = self.runtime or config.get_config()
        modality = runtime.get_model_modality(f"openrouter/{self.model}")
        modalities = ["image", "text"] if modality == "both" else ["image"]
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only scene artwork. Strictly avoid text, letters, logos, labels, plaques, "
                        "ribbons, medallion rings, frames, decorative borders, filigree, scrollwork, "
                        "arabesques, ornamental curls, black ornamental silhouettes, or lace-like cutout motifs."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Create a distinctly different artistic interpretation than prior variants. "
                        f"{seeded_prompt}\nAvoid: {negative_prompt}\nTarget size: {width}x{height}."
                    ),
                }
            ],
            "modalities": modalities,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://alexandria-cover-designer.local",
            "X-Title": "Alexandria Cover Designer",
        }

        response = None
        for attempt in range(1, 4):
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if response.status_code == 429:
                retry_after_raw = str(response.headers.get("Retry-After", "")).strip()
                try:
                    retry_after = max(1.0, float(retry_after_raw))
                except ValueError:
                    retry_after = float(10 * attempt)
                if attempt >= 3:
                    raise RetryableGenerationError(
                        f"OpenRouter rate-limited after retries (429): {_summarize_error_payload(response.text, limit=240)}",
                        status_code=429,
                    )
                logger.warning("OpenRouter 429; retrying in %.1fs (attempt %d/3)", retry_after, attempt)
                time.sleep(retry_after)
                continue
            break

        assert response is not None
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise RetryableGenerationError(
                f"OpenRouter temporary error {response.status_code}: {_summarize_error_payload(response.text, limit=240)}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise GenerationError(
                f"OpenRouter error {response.status_code}: {_summarize_error_payload(response.text, limit=300)}",
                status_code=response.status_code,
            )

        body = response.json()

        def _decode_candidate_url(image_url: str) -> Image.Image | None:
            token = str(image_url or "").strip()
            if not token:
                return None
            if token.startswith("data:image") and "," in token:
                encoded = token.split(",", 1)[1]
                image_bytes = base64.b64decode(encoded)
                return Image.open(io.BytesIO(image_bytes)).convert("RGB")
            if token.startswith("http"):
                return _download_image(token, timeout=self.timeout)
            return None

        # Format 1: choices[].message.images[].image_url/url
        for choice in body.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message", {})
            if not isinstance(message, dict):
                continue
            images = message.get("images") or []
            if isinstance(images, list):
                for image_row in images:
                    if not isinstance(image_row, dict):
                        continue
                    image_ref = image_row.get("image_url", image_row.get("url", ""))
                    if isinstance(image_ref, dict):
                        image_ref = image_ref.get("url", "")
                    parsed = _decode_candidate_url(str(image_ref or ""))
                    if parsed is not None:
                        return parsed

            # Format 2: OpenAI-style message content blocks.
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    image_ref = part.get("image_url", "")
                    if isinstance(image_ref, dict):
                        image_ref = image_ref.get("url", "")
                    parsed = _decode_candidate_url(str(image_ref or ""))
                    if parsed is not None:
                        return parsed

        # Format 3: OpenAI-compatible data[] envelope.
        for candidate in body.get("data") or []:
            if not isinstance(candidate, dict):
                continue
            encoded = str(candidate.get("b64_json", "") or "").strip()
            if encoded:
                image_bytes = base64.b64decode(encoded)
                return Image.open(io.BytesIO(image_bytes)).convert("RGB")
            parsed = _decode_candidate_url(str(candidate.get("url", "") or ""))
            if parsed is not None:
                return parsed

        # Format 4: generated_images[] envelopes.
        for candidate in body.get("generated_images") or body.get("generatedImages") or []:
            if not isinstance(candidate, dict):
                continue
            nested = candidate.get("image", {})
            if isinstance(nested, dict):
                encoded = str(nested.get("imageBytes", "") or "").strip()
                if encoded:
                    image_bytes = base64.b64decode(encoded)
                    return Image.open(io.BytesIO(image_bytes)).convert("RGB")
            parsed = _decode_candidate_url(str(candidate.get("url", "") or ""))
            if parsed is not None:
                return parsed

        raise GenerationError("OpenRouter response missing image payload")


class FalProvider(BaseProvider):
    """fal.ai generation endpoint."""

    name = "fal"

    def generate(self, prompt: str, negative_prompt: str, width: int, height: int, seed: int | None = None) -> Image.Image:
        if not self.api_key:
            raise GenerationError("Missing FAL_API_KEY")

        endpoint_model = self.model.replace("fal/", "")
        endpoint = f"https://fal.run/{endpoint_model}"
        self._assert_outbound_url(endpoint)
        payload: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "image_size": {"width": width, "height": height},
        }
        if seed is not None:
            payload["seed"] = int(seed)
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Key {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code in RETRYABLE_STATUS_CODES:
            raise RetryableGenerationError(
                f"fal.ai temporary error {response.status_code}: {_summarize_error_payload(response.text, limit=240)}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise GenerationError(
                f"fal.ai error {response.status_code}: {_summarize_error_payload(response.text, limit=300)}",
                status_code=response.status_code,
            )

        body = response.json()
        images = body.get("images") or body.get("output", {}).get("images") or []
        if not images:
            raise GenerationError("fal.ai response missing images")
        first = images[0]
        if isinstance(first, dict):
            url = first.get("url")
        else:
            url = str(first)
        if not url:
            raise GenerationError("fal.ai response image URL missing")
        return _download_image(url, timeout=self.timeout)


class ReplicateProvider(BaseProvider):
    """Replicate Predictions API."""

    name = "replicate"

    def generate(self, prompt: str, negative_prompt: str, width: int, height: int, seed: int | None = None) -> Image.Image:
        if not self.api_key:
            raise GenerationError("Missing REPLICATE_API_TOKEN")

        endpoint = "https://api.replicate.com/v1/predictions"
        self._assert_outbound_url(endpoint)
        input_payload: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
        }
        if seed is not None:
            input_payload["seed"] = int(seed)
        create_response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "version": self.model,
                "input": input_payload,
            },
            timeout=self.timeout,
        )

        if create_response.status_code in RETRYABLE_STATUS_CODES:
            raise RetryableGenerationError(
                f"Replicate temporary error {create_response.status_code}: {create_response.text[:240]}",
                status_code=create_response.status_code,
            )
        if create_response.status_code >= 400:
            raise GenerationError(
                f"Replicate error {create_response.status_code}: {create_response.text[:300]}"
            )

        prediction = create_response.json()
        prediction_id = prediction.get("id")
        if not prediction_id:
            raise GenerationError("Replicate response missing prediction id")

        poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
        self._assert_outbound_url(poll_url)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            poll = requests.get(
                poll_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            if poll.status_code in RETRYABLE_STATUS_CODES:
                time.sleep(1.0)
                continue
            if poll.status_code >= 400:
                raise GenerationError(f"Replicate poll error {poll.status_code}: {poll.text[:300]}")

            body = poll.json()
            status = body.get("status")
            if status == "succeeded":
                output = body.get("output")
                if isinstance(output, list) and output:
                    first = output[0]
                    if isinstance(first, dict):
                        output_url = first.get("url")
                        if output_url:
                            return _download_image(str(output_url), timeout=self.timeout)
                    return _download_image(str(first), timeout=self.timeout)
                if isinstance(output, str):
                    return _download_image(output, timeout=self.timeout)
                raise GenerationError("Replicate succeeded but output is empty")
            if status in {"failed", "canceled"}:
                raise GenerationError(f"Replicate prediction {status}: {body.get('error', 'unknown error')}")
            time.sleep(1.0)

        raise RetryableGenerationError("Replicate timed out while polling")


class GoogleCloudProvider(BaseProvider):
    """Google Generative API image endpoint (API key flow)."""

    name = "google"

    def generate(self, prompt: str, negative_prompt: str, width: int, height: int, seed: int | None = None) -> Image.Image:
        if not self.api_key:
            raise GenerationError("Missing GOOGLE_API_KEY")

        model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent"
        self._assert_outbound_url(url)
        prompt_text = (
            "Create a distinctly different artistic interpretation than prior variants. "
            f"{prompt}. Variation seed: {seed if seed is not None else 'n/a'}. "
            f"Avoid: {negative_prompt}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"width": width, "height": height},
            },
        }
        response = requests.post(
            url,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )

        # Some models reject width/height imageConfig; retry once with modality-only config.
        if response.status_code == 400:
            fallback_payload = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "generationConfig": {
                    "responseModalities": ["IMAGE"],
                },
            }
            response = requests.post(
                url,
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=fallback_payload,
                timeout=self.timeout,
            )

        if response.status_code in RETRYABLE_STATUS_CODES:
            raise RetryableGenerationError(
                f"Google temporary error {response.status_code}: {_summarize_error_payload(response.text, limit=240)}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise GenerationError(
                f"Google error {response.status_code}: {_summarize_error_payload(response.text, limit=300)}",
                status_code=response.status_code,
            )

        body = response.json()
        candidates = body.get("candidates", [])
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                inline = part.get("inlineData", {}) or part.get("inline_data", {})
                data = inline.get("data")
                if data:
                    image_bytes = base64.b64decode(data)
                    return Image.open(io.BytesIO(image_bytes)).convert("RGB")

        generated_images = body.get("generatedImages", []) or body.get("generated_images", [])
        for item in generated_images:
            encoded = item.get("image", {}).get("imageBytes") if isinstance(item, dict) else None
            if encoded:
                image_bytes = base64.b64decode(encoded)
                return Image.open(io.BytesIO(image_bytes)).convert("RGB")

        raise GenerationError("Google response missing image bytes")


_PROVIDER_CLASS_MAP = {
    "openrouter": OpenRouterProvider,
    "fal": FalProvider,
    "replicate": ReplicateProvider,
    "openai": OpenAIProvider,
    "google": GoogleCloudProvider,
}


class ProviderRateLimiter:
    """Sliding-window limiter with per-second and per-minute caps."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._second_windows: dict[str, deque[float]] = defaultdict(deque)
        self._minute_windows: dict[str, deque[float]] = defaultdict(deque)

    def wait(self, provider: str, *, per_second: int, per_minute: int, base_delay: float) -> None:
        if base_delay > 0:
            time.sleep(base_delay)

        backoff = 1.0
        while True:
            now = time.monotonic()
            with self._lock:
                second_window = self._second_windows[provider]
                minute_window = self._minute_windows[provider]

                while second_window and (now - second_window[0]) >= 1.0:
                    second_window.popleft()
                while minute_window and (now - minute_window[0]) >= 60.0:
                    minute_window.popleft()

                sec_blocked = per_second > 0 and len(second_window) >= per_second
                min_blocked = per_minute > 0 and len(minute_window) >= per_minute
                if not sec_blocked and not min_blocked:
                    second_window.append(now)
                    minute_window.append(now)
                    return

            sleep_for = min(60.0, backoff)
            logger.warning(
                "Rate limit reached for provider '%s'; backing off %.1fs",
                provider,
                sleep_for,
            )
            time.sleep(sleep_for)
            backoff = min(60.0, backoff * 2.0)

    def reset(self, provider: str | None = None) -> None:
        with self._lock:
            if provider is None:
                self._second_windows.clear()
                self._minute_windows.clear()
                return
            token = str(provider).strip().lower()
            self._second_windows.pop(token, None)
            self._minute_windows.pop(token, None)

    def snapshot(self) -> dict[str, dict[str, int]]:
        now = time.monotonic()
        with self._lock:
            rows: dict[str, dict[str, int]] = {}
            providers = set(self._second_windows.keys()) | set(self._minute_windows.keys())
            for provider in providers:
                second_window = self._second_windows[provider]
                minute_window = self._minute_windows[provider]
                while second_window and (now - second_window[0]) >= 1.0:
                    second_window.popleft()
                while minute_window and (now - minute_window[0]) >= 60.0:
                    minute_window.popleft()
                rows[provider] = {
                    "rate_limit_window_second": len(second_window),
                    "rate_limit_window_minute": len(minute_window),
                }
            return rows


class ProviderCircuitBreaker:
    """Simple per-provider circuit breaker to avoid retry storms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "state": "closed",
                "consecutive_failures": 0,
                "opened_until_monotonic": 0.0,
                "opened_until_utc": "",
                "last_error": "",
                "open_events": 0,
                "probe_in_flight": False,
            }
        )

    def allow(self, provider: str) -> tuple[bool, float]:
        now_mono = time.monotonic()
        with self._lock:
            state = self._state[provider]
            current_state = str(state.get("state", "closed") or "closed")
            opened_until = float(state.get("opened_until_monotonic", 0.0) or 0.0)

            if current_state == "open":
                if opened_until > now_mono:
                    return False, max(0.0, opened_until - now_mono)
                # Cooldown elapsed: permit exactly one half-open probe request.
                state["state"] = "half_open"
                state["opened_until_monotonic"] = 0.0
                state["opened_until_utc"] = ""
                state["consecutive_failures"] = 0
                state["probe_in_flight"] = False
                current_state = "half_open"

            if current_state == "half_open":
                if bool(state.get("probe_in_flight", False)):
                    return False, 0.25
                state["probe_in_flight"] = True
                return True, 0.0

            return True, 0.0

    def record_success(self, provider: str) -> None:
        with self._lock:
            state = self._state[provider]
            state["state"] = "closed"
            state["consecutive_failures"] = 0
            state["opened_until_monotonic"] = 0.0
            state["opened_until_utc"] = ""
            state["last_error"] = ""
            state["probe_in_flight"] = False

    def record_failure(
        self,
        provider: str,
        *,
        error_text: str,
        failure_threshold: int,
        cooldown_seconds: float,
        transient: bool = True,
    ) -> None:
        threshold = max(1, int(failure_threshold))
        cooldown = max(1.0, float(cooldown_seconds))
        now_mono = time.monotonic()
        now_utc = datetime.now(timezone.utc)
        with self._lock:
            state = self._state[provider]
            state["last_error"] = str(error_text or "")
            current_state = str(state.get("state", "closed") or "closed")

            if not transient:
                state["probe_in_flight"] = False
                if current_state == "half_open":
                    state["state"] = "closed"
                    state["consecutive_failures"] = 0
                return

            if current_state == "half_open":
                next_open_event = int(state.get("open_events", 0) or 0) + 1
                factor = min(4.0, float(2 ** max(0, next_open_event - 1)))
                adaptive_cooldown = min(900.0, cooldown * factor)
                state["state"] = "open"
                state["probe_in_flight"] = False
                state["consecutive_failures"] = threshold
                state["opened_until_monotonic"] = now_mono + adaptive_cooldown
                state["opened_until_utc"] = (now_utc + timedelta(seconds=adaptive_cooldown)).isoformat()
                state["open_events"] = next_open_event
                return

            state["consecutive_failures"] = int(state.get("consecutive_failures", 0) or 0) + 1
            if state["consecutive_failures"] < threshold:
                return
            next_open_event = int(state.get("open_events", 0) or 0) + 1
            factor = min(4.0, float(2 ** max(0, next_open_event - 1)))
            adaptive_cooldown = min(900.0, cooldown * factor)
            state["state"] = "open"
            state["probe_in_flight"] = False
            state["opened_until_monotonic"] = now_mono + adaptive_cooldown
            state["opened_until_utc"] = (now_utc + timedelta(seconds=adaptive_cooldown)).isoformat()
            state["open_events"] = next_open_event

    def snapshot(self) -> dict[str, dict[str, Any]]:
        now_mono = time.monotonic()
        with self._lock:
            rows: dict[str, dict[str, Any]] = {}
            for provider, values in self._state.items():
                opened_until = float(values.get("opened_until_monotonic", 0.0) or 0.0)
                remaining = max(0.0, opened_until - now_mono) if opened_until > 0 else 0.0
                state = str(values.get("state", "closed"))
                if state == "open" and opened_until <= now_mono:
                    state = "closed"
                rows[provider] = {
                    "state": state,
                    "consecutive_failures": int(values.get("consecutive_failures", 0) or 0),
                    "open_events": int(values.get("open_events", 0) or 0),
                    "cooldown_remaining_seconds": round(remaining, 3),
                    "opened_until_utc": str(values.get("opened_until_utc", "") or ""),
                    "last_error": str(values.get("last_error", "") or ""),
                    "probe_in_flight": bool(values.get("probe_in_flight", False)),
                }
            return rows

    def reset(self, provider: str | None = None) -> None:
        with self._lock:
            if provider is None:
                self._state.clear()
                return
            token = str(provider).strip().lower()
            self._state.pop(token, None)


_RATE_LIMITER = ProviderRateLimiter()
_CIRCUIT_BREAKER = ProviderCircuitBreaker()
_PROVIDER_STATS_LOCK = threading.Lock()
_PROVIDER_STATS: dict[str, dict[str, int]] = defaultdict(lambda: {"requests_today": 0, "errors_today": 0})


def _record_provider_request(provider: str, *, success: bool) -> None:
    with _PROVIDER_STATS_LOCK:
        stats = _PROVIDER_STATS[provider]
        stats["requests_today"] += 1
        if not success:
            stats["errors_today"] += 1


def _is_transient_provider_exception(exc: Exception) -> bool:
    if isinstance(exc, (RetryableGenerationError, requests.RequestException, TimeoutError)):
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(status_code, int) and status_code in RETRYABLE_STATUS_CODES


def reset_provider_runtime_state(provider: str | None = None) -> None:
    """Reset in-memory provider runtime state (rate limiter, breaker, stats)."""
    token = str(provider).strip().lower() if provider else None
    _RATE_LIMITER.reset(token)
    _CIRCUIT_BREAKER.reset(token)
    with _PROVIDER_STATS_LOCK:
        if token is None:
            _PROVIDER_STATS.clear()
        else:
            _PROVIDER_STATS.pop(token, None)


def get_provider_runtime_stats() -> dict[str, dict[str, Any]]:
    breaker_state = _CIRCUIT_BREAKER.snapshot()
    limiter_state = _RATE_LIMITER.snapshot()
    with _PROVIDER_STATS_LOCK:
        rows: dict[str, dict[str, Any]] = {}
        for provider, values in _PROVIDER_STATS.items():
            merged: dict[str, Any] = values.copy()
            merged.update(breaker_state.get(provider, {}))
            merged.update(limiter_state.get(provider, {}))
            rows[provider] = merged
        for provider, values in breaker_state.items():
            if provider in rows:
                continue
            rows[provider] = {
                "requests_today": 0,
                "errors_today": 0,
                **values,
                **limiter_state.get(provider, {}),
            }
        for provider, values in limiter_state.items():
            if provider in rows:
                continue
            rows[provider] = {
                "requests_today": 0,
                "errors_today": 0,
                "state": "closed",
                "consecutive_failures": 0,
                "open_events": 0,
                "cooldown_remaining_seconds": 0.0,
                "opened_until_utc": "",
                "last_error": "",
                "probe_in_flight": False,
                **values,
            }
        return rows


def generate_image(
    prompt: str,
    negative_prompt: str,
    model: str,
    params: dict[str, Any],
    *,
    seed: int | None = None,
) -> bytes:
    """Generate a single image via the specified model/provider."""
    runtime = config.get_config()

    negative_prompt = _merge_negative_prompt(negative_prompt)
    requested_provider = str(params.get("provider", "") or "").strip().lower()
    model_prefix = _model_provider_prefix(runtime, model)
    provider_candidates = _model_provider_chain(
        runtime,
        model=model,
        primary=requested_provider or runtime.resolve_model_provider(model),
    )
    if requested_provider and requested_provider in provider_candidates:
        provider = requested_provider
    elif model_prefix and model_prefix in provider_candidates:
        provider = model_prefix
    elif provider_candidates:
        provider = provider_candidates[0]
    else:
        provider = requested_provider or model_prefix or runtime.resolve_model_provider(model)
    provider = str(provider).strip().lower()
    provider_model = _resolve_provider_model_name(provider=provider, model=model, runtime=runtime)
    width = int(params.get("width", runtime.image_width))
    height = int(params.get("height", runtime.image_height))

    allowed, cooldown_remaining = _CIRCUIT_BREAKER.allow(provider)
    if not allowed:
        raise RetryableGenerationError(
            f"Provider '{provider}' is in cooldown ({cooldown_remaining:.1f}s remaining)",
            status_code=503,
        )

    request_delay = float(params.get("request_delay", _provider_request_delay(runtime, provider)))
    per_second = int(runtime.provider_rate_limit_per_second.get(provider, 0))
    per_minute = int(runtime.provider_rate_limit_per_minute.get(provider, 0))
    _RATE_LIMITER.wait(provider, per_second=per_second, per_minute=per_minute, base_delay=request_delay)

    provider_instance = _create_provider_instance(
        runtime=runtime,
        provider=provider,
        model=provider_model,
        allow_synthetic_fallback=bool(params.get("allow_synthetic_fallback", not runtime.has_any_api_key())),
    )

    try:
        image = provider_instance.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            seed=seed,
        )
        _record_provider_request(provider, success=True)
        _CIRCUIT_BREAKER.record_success(provider)
    except Exception as exc:
        _record_provider_request(provider, success=False)
        _CIRCUIT_BREAKER.record_failure(
            provider,
            error_text=str(exc),
            failure_threshold=runtime.provider_circuit_failure_threshold,
            cooldown_seconds=runtime.provider_circuit_cooldown_seconds,
            transient=_is_transient_provider_exception(exc),
        )
        raise

    processed = _post_process_image(image, width=width, height=height)
    if _is_blank_or_solid(processed):
        raise GenerationError("Generated image rejected by blank/solid-color quality check")
    # Synthetic fallback exists for key-less demo/testing environments; keep guardrails strict for real providers.
    provider_name = str(getattr(provider_instance, "name", "")).strip().lower()
    if provider_name != "synthetic":
        content_score, content_issues, metrics = _content_guardrail_score(processed)
        has_text_artifact = "text_or_banner_artifact" in content_issues
        hard_text_artifact = has_text_artifact and _is_high_confidence_text_artifact(
            content_score=content_score,
            metrics=metrics,
        )
        hard_frame_artifact = (
            ("inner_frame_or_ring_artifact" in content_issues or "rectangular_frame_artifact" in content_issues)
            and content_score >= 0.35
        )
        if has_text_artifact and not hard_text_artifact:
            logger.info(
                "Soft-passing low-confidence text artifact: score=%.3f text_penalty=%.3f band=%.3f tiny=%.3f",
                content_score,
                float(metrics.get("text_penalty", 0.0) or 0.0),
                float(metrics.get("text_band_ratio", 0.0) or 0.0),
                float(metrics.get("tiny_effective", 0.0) or 0.0),
            )
        if content_score > MAX_CONTENT_VIOLATION_SCORE or hard_text_artifact or hard_frame_artifact:
            issue_blob = ", ".join(content_issues[:3]) if content_issues else "content_artifacts"
            raise GenerationError(
                f"Generated image rejected by content guardrail ({content_score:.3f}): {issue_blob}"
            )

    buffer = io.BytesIO()
    processed.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_all_models(
    book_number: int,
    prompt: str,
    negative_prompt: str,
    models: list[str],
    variants_per_model: int,
    output_dir: Path,
    *,
    book_title: str = "",
    book_author: str = "",
    resume: bool = True,
    dry_run: bool = False,
    provider_override: str | None = None,
    cancel_checker: Callable[[str, int], bool] | None = None,
    preserve_prompt_text: bool = False,
) -> list[GenerationResult]:
    """Fire ALL models concurrently for the same prompt."""
    runtime = config.get_config()
    output_dir.mkdir(parents=True, exist_ok=True)

    if variants_per_model < 1:
        raise ValueError("variants_per_model must be >= 1")
    if not models:
        raise ValueError("models list cannot be empty")

    results: list[GenerationResult] = []
    failures: list[GenerationResult] = []
    dry_run_plan: list[dict[str, Any]] = []
    effective_negative_prompt = _merge_negative_prompt(negative_prompt)

    tasks: list[tuple[str, int, Path, str, str, int]] = []
    rng = random.SystemRandom()
    for model_index, model in enumerate(models):
        model_dir = output_dir / str(book_number) / _model_to_directory(model)
        model_dir.mkdir(parents=True, exist_ok=True)

        provider = provider_override or runtime.resolve_model_provider(model)
        provider = provider.lower()

        for variant in range(1, variants_per_model + 1):
            if callable(cancel_checker):
                try:
                    if bool(cancel_checker(model, variant)):
                        logger.info(
                            "Skipping cancelled generation for book %s model %s variant %s",
                            book_number,
                            model,
                            variant,
                        )
                        results.append(
                            GenerationResult(
                                book_number=book_number,
                                variant=variant,
                                prompt=prompt,
                                model=model,
                                image_path=None,
                                success=False,
                                error="Cancelled before generation started",
                                generation_time=0.0,
                                cost=0.0,
                                provider=provider,
                                skipped=True,
                            )
                        )
                        continue
                except Exception as exc:
                    logger.debug("cancel_checker failed for %s v%s: %s", model, variant, exc)

            image_path = model_dir / f"variant_{variant}.png"
            if preserve_prompt_text:
                diversified_prompt = _sanitize_prompt_text(str(prompt or ""))
            else:
                diversified_prompt = _diversify_prompt_for_model_variant(
                    prompt=prompt,
                    model=model,
                    provider=provider,
                    variant=variant,
                    model_index=model_index,
                )
                diversified_prompt = _validate_prompt_relevance(
                    diversified_prompt,
                    book_title=book_title,
                    book_author=book_author,
                )
            seed = _variant_seed(rng=rng, book_number=book_number, model=model, variant=variant)
            if resume and image_path.exists():
                logger.info(
                    'Skipping existing image for book %s model "%s" variant %s',
                    book_number,
                    model,
                    variant,
                )
                results.append(
                    GenerationResult(
                        book_number=book_number,
                        variant=variant,
                        prompt=diversified_prompt,
                        model=model,
                        image_path=image_path,
                        success=True,
                        error=None,
                        generation_time=0.0,
                        cost=0.0,
                        provider=provider,
                        skipped=True,
                        attempts=0,
                    )
                )
                continue

            if dry_run:
                dry_run_plan.append(
                    {
                        "book_number": book_number,
                        "model": model,
                        "provider": provider,
                        "variant": variant,
                        "prompt": diversified_prompt,
                        "negative_prompt": effective_negative_prompt,
                        "output_path": str(image_path),
                        "estimated_cost": runtime.get_model_cost(model),
                        "seed": seed,
                    }
                )
                results.append(
                    GenerationResult(
                        book_number=book_number,
                        variant=variant,
                        prompt=diversified_prompt,
                        model=model,
                        image_path=None,
                        success=True,
                        error=None,
                        generation_time=0.0,
                        cost=runtime.get_model_cost(model),
                        provider=provider,
                        dry_run=True,
                        attempts=0,
                    )
                )
                continue

            tasks.append((model, variant, image_path, provider, diversified_prompt, seed))

    if dry_run:
        _append_generation_plan(runtime.generation_plan_path, dry_run_plan)
        return _sort_results(results)

    max_workers = min(len(tasks), max(len(models), runtime.batch_concurrency, 1)) if tasks else 1
    if tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    _generate_one,
                    book_number=book_number,
                    variant=variant,
                    prompt=variant_prompt,
                    negative_prompt=effective_negative_prompt,
                    model=model,
                    provider=provider,
                    output_path=image_path,
                    resume=resume,
                    seed=seed,
                    preserve_prompt_text=preserve_prompt_text,
                ): (model, variant)
                for model, variant, image_path, provider, variant_prompt, seed in tasks
            }

            for future in as_completed(future_map):
                result = future.result()
                results.append(result)
                if not result.success:
                    failures.append(result)

    if tasks and results:
        results = _regenerate_near_duplicate_variants(
            runtime=runtime,
            book_number=book_number,
            negative_prompt=effective_negative_prompt,
            output_dir=output_dir,
            results=results,
            resume=resume,
            provider_override=provider_override,
        )
        failures = [row for row in results if not row.success]

    if failures:
        _append_failures(runtime.failures_path, failures)

    return _sort_results(results)


def _diversify_prompt_for_variant(*, prompt: str, variant: int) -> str:
    base_text = _sanitize_prompt_text(str(prompt or "").strip())
    if not base_text:
        base_text = "Cinematic full-bleed narrative scene with one dominant focal subject and vivid color"
    base = _guardrailed_prompt(base_text)
    diversified = prompt_generator.diversify_prompt(base, int(variant))
    if int(variant) > 1:
        diversified = (
            f"{diversified} Create a visibly distinct composition from prior variants for this title."
        ).strip()
    return " ".join(diversified.split())


def _stable_model_seed(*, model: str, provider: str) -> int:
    token = f"{provider.strip().lower()}::{model.strip().lower()}"
    digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _provider_model_hint(*, model: str, provider: str) -> str:
    token = f"{provider.strip().lower()} {model.strip().lower()}"
    for marker, hint in MODEL_PROVIDER_HINTS:
        if marker in token:
            return hint
    return ""


def _diversify_prompt_for_model_variant(
    *,
    prompt: str,
    model: str,
    provider: str,
    variant: int,
    model_index: int,
) -> str:
    diversified = _diversify_prompt_for_variant(prompt=prompt, variant=variant)
    if not MODEL_STYLE_PROFILES:
        return diversified

    stable_seed = _stable_model_seed(model=model, provider=provider)
    profile = MODEL_STYLE_PROFILES[(stable_seed + int(model_index) + int(variant)) % len(MODEL_STYLE_PROFILES)]
    provider_hint = _provider_model_hint(model=model, provider=provider)
    provider_token = provider.strip().lower()
    model_token = model.strip().lower()
    signature_token = model_token if model_token.startswith(f"{provider_token}/") else f"{provider_token}/{model_token}"
    directive_parts = [
        f"Model signature: {signature_token}.",
        f"Style direction: {profile['style']}.",
        f"Color direction: {profile['palette']}.",
        f"Composition direction: {profile['composition']}.",
        f"Visual treatment: {profile['detail']}.",
        "Ensure this result is intentionally different from other models in the same run.",
    ]
    if STRICT_SCENE_GUARDRAIL not in diversified:
        directive_parts.append(STRICT_SCENE_GUARDRAIL)
    if VIVID_COLOR_GUARDRAIL not in diversified:
        directive_parts.append(VIVID_COLOR_GUARDRAIL)
    if provider_hint:
        directive_parts.append(provider_hint)
    merged = f"{' '.join(directive_parts)} {diversified}".strip()
    # Keep explicit anti-text / anti-frame directives verbatim for provider calls.
    # Re-running constraint sanitization here can strip key "no ..." terms and create malformed lists.
    return " ".join(merged.split())


def _variant_seed(*, rng: random.Random | random.SystemRandom, book_number: int, model: str, variant: int) -> int:
    del book_number
    del model
    del variant
    return int(rng.getrandbits(32))


def _duplicate_prompt_suffix(*, variant: int, distance: float) -> str:
    return (
        "Force a substantially different visual outcome than previous variants. "
        f"Use a fresh palette/composition strategy for variant {int(variant)} (similarity distance={distance:.3f})."
    )


def _regenerate_near_duplicate_variants(
    *,
    runtime: config.Config,
    book_number: int,
    negative_prompt: str,
    output_dir: Path,
    results: list[GenerationResult],
    resume: bool,
    provider_override: str | None,
) -> list[GenerationResult]:
    del output_dir
    del resume
    distance_threshold = 0.15  # ~= 85%+ similar by inverse distance interpretation.
    viable: list[tuple[int, GenerationResult]] = []
    for idx, row in enumerate(results):
        if not row.success or row.dry_run or row.skipped or not row.image_path or not row.image_path.exists():
            continue
        viable.append((idx, row))
    if len(viable) < 2:
        return results

    try:
        regions = safe_json.load_json(
            config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir),
            {},
        )
    except Exception as exc:
        logger.debug("Similarity dedupe skipped (regions unavailable): %s", exc)
        return results

    grouped: dict[str, list[tuple[int, GenerationResult, Any]]] = {}
    for idx, row in viable:
        try:
            hash_obj = similarity_detector._compute_hash_for_book(  # type: ignore[attr-defined]
                book_number=book_number,
                image_path=row.image_path,
                regions=regions,
            )
        except Exception as exc:
            logger.debug("Similarity hash failed for %s: %s", row.image_path, exc)
            continue
        grouped.setdefault(row.model, []).append((idx, row, hash_obj))

    duplicate_targets: dict[int, tuple[GenerationResult, float]] = {}
    for model, rows in grouped.items():
        if len(rows) < 2:
            continue
        rows = sorted(rows, key=lambda item: item[1].variant)
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                left = rows[i]
                right = rows[j]
                try:
                    metrics = similarity_detector._compare_hash_objects(left[2], right[2])  # type: ignore[attr-defined]
                    distance = float(metrics.get("combined_similarity", 1.0) or 1.0)
                except Exception as exc:
                    logger.debug("Similarity compare failed for model %s: %s", model, exc)
                    continue
                if distance > distance_threshold:
                    continue
                idx = int(right[0])
                existing = duplicate_targets.get(idx)
                if existing is None or distance < existing[1]:
                    duplicate_targets[idx] = (right[1], distance)

    if not duplicate_targets:
        return results

    logger.warning(
        "Detected %d near-duplicate variant(s) for book %s; attempting one regeneration pass",
        len(duplicate_targets),
        book_number,
    )
    regen_rng = random.SystemRandom()
    for idx, (row, distance) in sorted(duplicate_targets.items(), key=lambda item: item[0]):
        if not row.image_path:
            continue
        regen_prompt = f"{row.prompt} {_duplicate_prompt_suffix(variant=row.variant, distance=distance)}".strip()
        regen_prompt = prompt_generator.enforce_prompt_constraints(regen_prompt)
        seed = _variant_seed(rng=regen_rng, book_number=book_number, model=row.model, variant=row.variant)
        provider = provider_override or row.provider or runtime.resolve_model_provider(row.model)
        regenerated = _generate_one(
            book_number=book_number,
            variant=row.variant,
            prompt=regen_prompt,
            negative_prompt=negative_prompt,
            model=row.model,
            provider=provider,
            output_path=row.image_path,
            resume=False,
            seed=seed,
        )
        if regenerated.success:
            logger.info(
                "Regenerated near-duplicate variant for book %s model %s variant %s (distance %.3f)",
                book_number,
                row.model,
                row.variant,
                distance,
            )
            results[idx] = regenerated
        else:
            logger.warning(
                "Failed to regenerate near-duplicate variant for book %s model %s variant %s: %s",
                book_number,
                row.model,
                row.variant,
                regenerated.error,
            )

    return results


def generate_single_book(
    book_number: int,
    prompts_path: Path,
    output_dir: Path,
    models: list[str] | None = None,
    variants: int = 5,
    *,
    prompt_variant: int = 1,
    prompt_text: str | None = None,
    negative_prompt: str | None = None,
    provider_override: str | None = None,
    library_prompt_id: str | None = None,
    resume: bool = True,
    dry_run: bool = False,
    cancel_checker: Callable[[str, int], bool] | None = None,
    preserve_prompt_text: bool = False,
) -> list[GenerationResult]:
    """Primary single-cover entry point for iterative generation (D19)."""
    runtime = config.get_config()

    payload = _load_prompts_payload(prompts_path)
    book_entry = _find_book_entry(payload, book_number)
    title = str(book_entry.get("title", f"Book {book_number}"))
    author = str(book_entry.get("author", "")).strip()

    base_variant = _find_variant(book_entry, prompt_variant)
    selected_negative_prompt = negative_prompt or str(base_variant.get("negative_prompt", ""))

    selected_prompt = prompt_text
    if library_prompt_id:
        prompt_library = PromptLibrary(runtime.prompt_library_path)
        library_matches = [prompt for prompt in prompt_library.get_prompts() if prompt.id == library_prompt_id]
        if not library_matches:
            raise KeyError(f"Prompt id '{library_prompt_id}' not found in prompt library")
        selected_prompt = _apply_library_prompt_tokens(
            library_matches[0].prompt_template,
            title=title,
            author=author,
            book=book_entry,
        )
        if not negative_prompt:
            selected_negative_prompt = library_matches[0].negative_prompt

    if not selected_prompt:
        selected_prompt = str(base_variant.get("prompt", "")).strip()
    selected_prompt = _sanitize_prompt_text(str(selected_prompt or ""))

    active_models = models[:] if models else runtime.all_models[:]
    if not active_models:
        active_models = [runtime.ai_model]

    logger.info(
        "Generating single book %s using %d model(s), %d variant(s)/model",
        book_number,
        len(active_models),
        variants,
    )

    return generate_all_models(
        book_number=book_number,
        prompt=selected_prompt,
        negative_prompt=selected_negative_prompt,
        models=active_models,
        variants_per_model=variants,
        output_dir=output_dir,
        book_title=title,
        book_author=author,
        resume=resume,
        dry_run=dry_run,
        provider_override=provider_override,
        cancel_checker=cancel_checker,
        preserve_prompt_text=preserve_prompt_text,
    )


def generate_batch(
    prompts_path: Path,
    output_dir: Path,
    resume: bool = True,
    *,
    books: list[int] | None = None,
    model: str | None = None,
    dry_run: bool = False,
    max_books: int = 20,
) -> list[GenerationResult]:
    """Batch generation mode for validated model/prompt combinations.

    D23 scope default: first 20 titles only.
    """
    runtime = config.get_config()
    payload = _load_prompts_payload(prompts_path)

    all_books = sorted(payload.get("books", []), key=lambda item: int(item.get("number", 0)))
    if books:
        wanted = {int(num) for num in books}
        all_books = [item for item in all_books if int(item.get("number", 0)) in wanted]
    else:
        all_books = all_books[:max_books]

    chosen_model = model or runtime.ai_model
    chosen_provider = runtime.resolve_model_provider(chosen_model)

    total_jobs = sum(min(runtime.variants_per_cover, len(entry.get("variants", []))) for entry in all_books)
    completed = 0

    results: list[GenerationResult] = []
    failures: list[GenerationResult] = []
    dry_run_plan: list[dict[str, Any]] = []

    for book_entry in all_books:
        book_number = int(book_entry.get("number", 0))
        title = str(book_entry.get("title", f"Book {book_number}"))
        variants = sorted(book_entry.get("variants", []), key=lambda item: int(item.get("variant_id", 0)))
        variants = variants[: runtime.variants_per_cover]

        for variant_entry in variants:
            completed += 1
            variant_id = int(variant_entry.get("variant_id", completed))
            prompt = _sanitize_prompt_text(str(variant_entry.get("prompt", "")))
            negative_prompt = str(variant_entry.get("negative_prompt", ""))
            image_path = output_dir / str(book_number) / f"variant_{variant_id}.png"

            if resume and image_path.exists():
                logger.info(
                    "[%d/%d] Skipping Variant %d for \"%s\" (already exists)",
                    completed,
                    total_jobs,
                    variant_id,
                    title,
                )
                results.append(
                    GenerationResult(
                        book_number=book_number,
                        variant=variant_id,
                        prompt=prompt,
                        model=chosen_model,
                        image_path=image_path,
                        success=True,
                        error=None,
                        generation_time=0.0,
                        cost=0.0,
                        provider=chosen_provider,
                        skipped=True,
                        attempts=0,
                    )
                )
                continue

            logger.info(
                "[%d/%d] Generating Variant %d for \"%s\"...",
                completed,
                total_jobs,
                variant_id,
                title,
            )

            if dry_run:
                dry_run_plan.append(
                    {
                        "book_number": book_number,
                        "model": chosen_model,
                        "provider": chosen_provider,
                        "variant": variant_id,
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "output_path": str(image_path),
                        "estimated_cost": runtime.get_model_cost(chosen_model),
                    }
                )
                results.append(
                    GenerationResult(
                        book_number=book_number,
                        variant=variant_id,
                        prompt=prompt,
                        model=chosen_model,
                        image_path=None,
                        success=True,
                        error=None,
                        generation_time=0.0,
                        cost=runtime.get_model_cost(chosen_model),
                        provider=chosen_provider,
                        dry_run=True,
                        attempts=0,
                    )
                )
                continue

            result = _generate_one(
                book_number=book_number,
                variant=variant_id,
                prompt=prompt,
                negative_prompt=negative_prompt,
                model=chosen_model,
                provider=chosen_provider,
                output_path=image_path,
                resume=resume,
            )
            results.append(result)
            if not result.success:
                failures.append(result)

    if dry_run and dry_run_plan:
        _append_generation_plan(runtime.generation_plan_path, dry_run_plan)

    if failures:
        _append_failures(runtime.failures_path, failures)

    return _sort_results(results)


def _generate_one(
    *,
    book_number: int,
    variant: int,
    prompt: str,
    negative_prompt: str,
    model: str,
    provider: str,
    output_path: Path,
    resume: bool,
    seed: int | None = None,
    preserve_prompt_text: bool = False,
) -> GenerationResult:
    runtime = config.get_config()
    catalog_id = getattr(runtime, "catalog_id", None)
    original_prompt = str(prompt)

    def _result_prompt(current_prompt: str) -> str:
        if preserve_prompt_text:
            return original_prompt
        return str(current_prompt)

    prompt_similarity_alert: str | None = None
    try:
        prompt_similarity = similarity_detector.check_prompt_similarity_against_winners(
            prompt=original_prompt,
            current_book=book_number,
            winner_selections_path=config.winner_selections_path(catalog_id=catalog_id, data_dir=runtime.data_dir),
            generation_history_path=config.generation_history_path(catalog_id=catalog_id, data_dir=runtime.data_dir),
            threshold=0.85,
        )
        if bool(prompt_similarity.get("alert")):
            close_book = prompt_similarity.get("closest_book")
            similarity_value = float(prompt_similarity.get("similarity", 0.0) or 0.0)
            prompt_similarity_alert = (
                f"Prompt similarity warning: book {book_number} prompt is {similarity_value:.3f} similar to winner prompt for book {close_book}."
            )
            logger.warning(prompt_similarity_alert)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Prompt similarity pre-check failed: %s", exc)

    if resume and output_path.exists():
        return GenerationResult(
            book_number=book_number,
            variant=variant,
            prompt=_result_prompt(original_prompt),
            model=model,
            image_path=output_path,
            success=True,
            error=None,
            generation_time=0.0,
            cost=0.0,
            provider=provider,
            skipped=True,
            attempts=0,
        )

    start = time.perf_counter()
    last_error: str | None = None
    last_failure_meta: dict[str, Any] = {}
    provider_chain = _model_provider_chain(runtime, model=model, primary=provider)
    provider_index = 0
    active_provider = provider_chain[provider_index]
    consecutive_provider_failures = 0

    attempt = 0
    max_attempts = max(1, runtime.max_retries) * max(1, len(provider_chain))
    artifact_retry_count = 0
    working_prompt = original_prompt
    while attempt < max_attempts:
        # Skip providers that are currently in cooldown.
        provider_advanced = False
        while provider_index < len(provider_chain):
            candidate = provider_chain[provider_index]
            allowed, cooldown_remaining = _CIRCUIT_BREAKER.allow(candidate)
            if allowed:
                active_provider = candidate
                break
            logger.warning(
                "Skipping provider '%s' for book %s model %s variant %s due to cooldown (%.1fs remaining)",
                candidate,
                book_number,
                model,
                variant,
                cooldown_remaining,
            )
            provider_index += 1
            provider_advanced = True
        if provider_index >= len(provider_chain):
            last_error = "All providers are in cooldown"
            last_failure_meta = {
                "provider": active_provider,
                "error": last_error,
                "error_type": "provider_cooldown",
                "retry_count": attempt,
            }
            break
        if provider_advanced:
            consecutive_provider_failures = 0

        attempt += 1
        try:
            image_bytes = generate_image(
                prompt=working_prompt,
                negative_prompt=negative_prompt,
                model=model,
                params={
                    "provider": active_provider,
                    "width": runtime.image_width,
                    "height": runtime.image_height,
                    "request_delay": _provider_request_delay(runtime, active_provider),
                    "allow_synthetic_fallback": not runtime.has_any_api_key(),
                },
                seed=seed,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_bytes)

            similar_to_book: int | None = None
            distinctiveness_score: float = 1.0
            post_warning: str | None = prompt_similarity_alert
            try:
                post_check = similarity_detector.check_generated_image_against_winners(
                    image_path=output_path,
                    book_number=book_number,
                    output_dir=runtime.output_dir,
                    catalog_path=runtime.book_catalog_path,
                    winner_selections_path=config.winner_selections_path(catalog_id=catalog_id, data_dir=runtime.data_dir),
                    regions_path=config.cover_regions_path(catalog_id=catalog_id, config_dir=runtime.config_dir),
                    threshold=0.25,
                )
                nearest_similarity = float(post_check.get("similarity", 1.0) or 1.0)
                distinctiveness_score = max(0.0, min(1.0, nearest_similarity))
                similar_to_book = post_check.get("closest_book")
                if bool(post_check.get("alert")) and similar_to_book:
                    suffix = f"SIMILAR TO BOOK #{similar_to_book} (distance={nearest_similarity:.3f})"
                    post_warning = f"{post_warning} | {suffix}" if post_warning else suffix
                    logger.warning(
                        "Post-generation similarity alert for book %s variant %s model %s: %s",
                        book_number,
                        variant,
                        model,
                        suffix,
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Post-generation similarity check failed: %s", exc)

            elapsed = time.perf_counter() - start
            return GenerationResult(
                book_number=book_number,
                variant=variant,
                prompt=_result_prompt(working_prompt),
                model=model,
                image_path=output_path,
                success=True,
                error=None,
                generation_time=elapsed,
                cost=runtime.get_model_cost(model),
                provider=active_provider,
                attempts=attempt,
                similarity_warning=post_warning,
                similar_to_book=similar_to_book,
                distinctiveness_score=distinctiveness_score,
            )
        except RetryableGenerationError as exc:
            last_error = str(exc)
            last_failure_meta = {
                "provider": active_provider,
                "error": last_error,
                "error_type": "retryable_generation_error",
                "retry_count": attempt,
                "status_code": int(exc.status_code or 0),
            }
            consecutive_provider_failures += 1
            if consecutive_provider_failures >= 3 and provider_index < (len(provider_chain) - 1):
                previous_provider = active_provider
                provider_index += 1
                active_provider = provider_chain[provider_index]
                consecutive_provider_failures = 0
                logger.warning(
                    "Provider failover triggered for book %s model %s variant %s: %s -> %s",
                    book_number,
                    model,
                    variant,
                    previous_provider,
                    active_provider,
                )
                continue
            if attempt >= max_attempts:
                break
            if "in cooldown" in str(exc).lower() and provider_index < (len(provider_chain) - 1):
                previous_provider = active_provider
                provider_index += 1
                active_provider = provider_chain[provider_index]
                consecutive_provider_failures = 0
                logger.warning(
                    "Provider cooldown failover for book %s model %s variant %s: %s -> %s",
                    book_number,
                    model,
                    variant,
                    previous_provider,
                    active_provider,
                )
                continue
            backoff = min(60.0, max(1.0, runtime.request_delay * (2 ** (attempt - 1))))
            logger.warning(
                "Retryable error for book %s model %s variant %s (%d/%d): %s",
                book_number,
                model,
                variant,
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(backoff)
        except GenerationError as exc:
            last_error = str(exc)
            last_failure_meta = {
                "provider": active_provider,
                "error": last_error,
                "error_type": "generation_error",
                "retry_count": attempt,
                "status_code": int(exc.status_code or 0),
            }
            if _is_artifact_generation_error(last_error) and artifact_retry_count < ARTIFACT_RETRY_LIMIT:
                artifact_retry_count += 1
                working_prompt = _artifact_retry_prompt(prompt=working_prompt, retry_index=artifact_retry_count)
                logger.warning(
                    "Artifact guardrail retry for book %s model %s variant %s (%d/%d): %s",
                    book_number,
                    model,
                    variant,
                    artifact_retry_count,
                    ARTIFACT_RETRY_LIMIT,
                    exc,
                )
                continue
            consecutive_provider_failures += 1
            if _should_immediately_failover(active_provider, exc) and provider_index < (len(provider_chain) - 1):
                previous_provider = active_provider
                provider_index += 1
                active_provider = provider_chain[provider_index]
                consecutive_provider_failures = 0
                logger.warning(
                    "Immediate provider failover triggered for book %s model %s variant %s after provider credits/auth issue: %s -> %s (%s)",
                    book_number,
                    model,
                    variant,
                    previous_provider,
                    active_provider,
                    exc,
                )
                continue
            if consecutive_provider_failures >= 3 and provider_index < (len(provider_chain) - 1):
                previous_provider = active_provider
                provider_index += 1
                active_provider = provider_chain[provider_index]
                consecutive_provider_failures = 0
                logger.warning(
                    "Provider failover triggered for book %s model %s variant %s after GenerationError: %s -> %s",
                    book_number,
                    model,
                    variant,
                    previous_provider,
                    active_provider,
                )
                continue
            if attempt >= max_attempts:
                break
        except requests.RequestException as exc:
            last_error = f"Request failure: {exc}"
            last_failure_meta = {
                "provider": active_provider,
                "error": last_error,
                "error_type": "request_exception",
                "retry_count": attempt,
            }
            consecutive_provider_failures += 1
            if consecutive_provider_failures >= 3 and provider_index < (len(provider_chain) - 1):
                previous_provider = active_provider
                provider_index += 1
                active_provider = provider_chain[provider_index]
                consecutive_provider_failures = 0
                logger.warning(
                    "Provider failover triggered for book %s model %s variant %s after network failures: %s -> %s",
                    book_number,
                    model,
                    variant,
                    previous_provider,
                    active_provider,
                )
                continue
            if attempt >= max_attempts:
                break
            backoff = min(60.0, max(1.0, runtime.request_delay * (2 ** (attempt - 1))))
            logger.warning(
                "Network retry for book %s model %s variant %s (%d/%d): %s",
                book_number,
                model,
                variant,
                attempt,
                max_attempts,
                exc,
            )
            time.sleep(backoff)

    elapsed = time.perf_counter() - start
    return GenerationResult(
        book_number=book_number,
        variant=variant,
        prompt=_result_prompt(working_prompt),
        model=model,
        image_path=None,
        success=False,
        error=last_error or "Unknown generation failure",
        generation_time=elapsed,
        cost=0.0,
        provider=active_provider,
        attempts=attempt,
        failure_meta=last_failure_meta,
    )


def _provider_request_delay(runtime: config.Config, provider: str) -> float:
    return float(runtime.provider_request_delay.get(provider, runtime.request_delay))


def _canonical_model_family(runtime: config.Config, model: str) -> str:
    token = runtime.resolve_model_alias(model).strip()
    if not token:
        return ""
    parts = [part.strip() for part in token.split("/") if part.strip()]
    while len(parts) > 1 and parts[0].lower() in runtime.provider_keys:
        parts.pop(0)
    return "/".join(parts)


def _model_provider_chain(runtime: config.Config, *, model: str, primary: str) -> list[str]:
    token = runtime.resolve_model_alias(model).strip()
    explicit_provider = _model_provider_prefix(runtime, token)
    if not explicit_provider:
        return _provider_fallback_chain(runtime, primary=primary)

    any_key = runtime.has_any_api_key()

    def _provider_enabled(provider: str) -> bool:
        if not any_key:
            return True
        return bool(runtime.get_api_key(provider).strip())

    providers: list[str] = []

    def _append(provider: str | None) -> None:
        candidate = str(provider or "").strip().lower()
        if not candidate or candidate in providers or not _provider_enabled(candidate):
            return
        providers.append(candidate)

    _append(explicit_provider)
    family = _canonical_model_family(runtime, token)
    for candidate_model in [token, *runtime.all_models]:
        candidate_token = runtime.resolve_model_alias(candidate_model).strip()
        if not candidate_token:
            continue
        if _canonical_model_family(runtime, candidate_token) != family:
            continue
        _append(_model_provider_prefix(runtime, candidate_token) or runtime.resolve_model_provider(candidate_token))
    if not providers and explicit_provider:
        providers.append(explicit_provider)
    return providers


def _provider_fallback_chain(runtime: config.Config, *, primary: str) -> list[str]:
    primary_token = str(primary or "").strip().lower()
    any_key = runtime.has_any_api_key()

    def _provider_enabled(token: str) -> bool:
        if not any_key:
            return True
        return bool(runtime.get_api_key(token).strip())

    providers: list[str] = []
    if primary_token and _provider_enabled(primary_token):
        providers.append(primary_token)
    for provider in runtime.provider_keys.keys():
        token = str(provider).strip().lower()
        if not token or token in providers:
            continue
        if not _provider_enabled(token):
            continue
        providers.append(token)
    if not providers and primary_token:
        providers.append(primary_token)
    return providers


def _create_provider_instance(
    *,
    runtime: config.Config,
    provider: str,
    model: str,
    allow_synthetic_fallback: bool,
) -> BaseProvider:
    api_key = runtime.get_api_key(provider)

    if provider not in _PROVIDER_CLASS_MAP:
        raise GenerationError(f"Unsupported provider: {provider}")

    if not api_key and allow_synthetic_fallback:
        logger.info(
            "No API key configured for provider '%s'; using synthetic provider fallback for local iteration",
            provider,
        )
        return SyntheticProvider(model=model, runtime=runtime)

    provider_class = _PROVIDER_CLASS_MAP[provider]
    return provider_class(model=model, api_key=api_key, runtime=runtime)


def _resolve_provider_model_name(provider: str, model: str, runtime: config.Config | None = None) -> str:
    """Strip provider prefix from provider/model notation, including nested provider families."""
    cfg = runtime or config.get_config()
    token = cfg.resolve_model_alias(model)
    if "/" not in token:
        return token

    parts = [part.strip() for part in token.split("/") if part.strip()]
    for index, part in enumerate(parts):
        if part.lower() != provider.lower():
            continue
        suffix = "/".join(parts[index + 1 :]).strip()
        if suffix:
            return suffix
    return token


def _should_immediately_failover(provider: str, exc: Exception) -> bool:
    token = str(provider or "").strip().lower()
    if token != "openrouter":
        return False
    status_code = getattr(exc, "status_code", None)
    error_text = str(exc).lower()
    return bool(
        status_code == 402
        or "error 402" in error_text
        or '"code":402' in error_text
        or "requires more credits" in error_text
        or "insufficient credits" in error_text
    )


def _merge_negative_prompt(negative_prompt: str | None) -> str:
    custom = " ".join(str(negative_prompt or "").split()).strip()
    baseline = " ".join(ALEXANDRIA_NEGATIVE_PROMPT.split()).strip()
    if not custom:
        return baseline
    if baseline.lower() in custom.lower():
        return custom
    return f"{custom} {baseline}".strip()


def _apply_library_prompt_tokens(
    template: str,
    *,
    title: str,
    author: str,
    book: dict[str, Any] | None = None,
) -> str:
    context = content_relevance.resolve_prompt_context(book or {"title": title, "author": author})
    prompt = (
        str(template or "")
        .replace("{title}", str(title or ""))
        .replace("{author}", str(author or ""))
        .replace("{TITLE}", str(title or ""))
        .replace("{AUTHOR}", str(author or ""))
        .replace("{SCENE}", str(context.get("scene_with_protagonist", "") or context.get("scene", "")))
        .replace("{MOOD}", str(context.get("mood", "")))
        .replace("{ERA}", str(context.get("era", "")))
    )
    return content_relevance.ensure_prompt_book_context(
        prompt=prompt,
        book=book or {"title": title, "author": author},
        require_scene_anchor=True,
    )


def _model_provider_prefix(runtime: config.Config, model: str) -> str | None:
    """Return explicit provider prefix for provider/model notation, when present."""
    token = str(model).strip()
    if "/" not in token:
        return None
    prefix = token.split("/", 1)[0].strip().lower()
    if prefix in runtime.provider_keys:
        return prefix
    return None


def _post_process_image(image: Image.Image, width: int, height: int) -> Image.Image:
    return image.convert("RGBA").resize((width, height), Image.LANCZOS)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _edge_energy_map(gray: np.ndarray) -> np.ndarray:
    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    return np.pad(dx, ((0, 0), (0, 1)), mode="constant") + np.pad(dy, ((0, 1), (0, 0)), mode="constant")


def _tiny_component_ratio(binary: np.ndarray, mask: np.ndarray) -> float:
    active = (binary.astype(bool) & mask.astype(bool))
    if not np.any(active):
        return 0.0
    total = max(1, int(mask.sum()))
    if _ndi is not None:
        labeled, count = _ndi.label(active.astype(np.uint8))
        if int(count) <= 0:
            return 0.0
        sizes = np.bincount(labeled.ravel())
        if sizes.shape[0] <= 1:
            return 0.0
        tiny_pixels = int(sizes[1:][(sizes[1:] >= 2) & (sizes[1:] <= 160)].sum())
        return float(tiny_pixels) / float(total)
    # Fallback path when scipy is unavailable: ensure arithmetic runs on integers, not bool.
    padded = np.pad(active.astype(np.uint8), 1, mode="constant")
    neighbors = (
        padded[1:-1, :-2]
        + padded[1:-1, 2:]
        + padded[:-2, 1:-1]
        + padded[2:, 1:-1]
    )
    tiny = active & (neighbors <= 2)
    return float(tiny.mean())


def _ring_artifact_penalty(edge_map: np.ndarray, mask: np.ndarray) -> tuple[float, dict[str, float]]:
    h, w = edge_map.shape[:2]
    if h <= 0 or w <= 0:
        return 1.0, {"annulus_ratio": 0.0, "ring_peaks": 0.0}

    center_x = (w - 1.0) / 2.0
    center_y = (h - 1.0) / 2.0
    radius = max(1.0, min(h, w) / 2.0)
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - center_x) ** 2 + (yy - center_y) ** 2)

    masked_edges = edge_map[mask]
    mean_edge = float(masked_edges.mean()) if masked_edges.size else 0.0
    annulus = mask & (dist >= radius * 0.68) & (dist <= radius * 0.97)
    annulus_edges = edge_map[annulus]
    annulus_mean = float(annulus_edges.mean()) if annulus_edges.size else 0.0
    annulus_ratio = annulus_mean / max(1e-6, mean_edge)

    bins = max(32, int(radius * 0.12))
    radial = np.linspace(0.0, radius, bins + 1)
    bin_idx = np.clip(np.digitize(dist.ravel(), radial) - 1, 0, bins - 1)
    vals = edge_map.ravel()
    mask_flat = mask.ravel()
    profile = np.zeros(bins, dtype=np.float32)
    counts = np.zeros(bins, dtype=np.float32)
    np.add.at(profile, bin_idx[mask_flat], vals[mask_flat])
    np.add.at(counts, bin_idx[mask_flat], 1.0)
    profile = np.divide(profile, np.maximum(counts, 1.0))
    smooth = np.convolve(profile, np.array([0.2, 0.6, 0.2], dtype=np.float32), mode="same")

    tail_start = int(bins * 0.70)
    tail = smooth[tail_start:] if tail_start < smooth.shape[0] else smooth
    if tail.size <= 4:
        ring_peaks = 0
    else:
        threshold = float(tail.mean() + (tail.std() * 1.15))
        ring_peaks = 0
        for idx in range(tail_start + 1, smooth.shape[0] - 1):
            value = float(smooth[idx])
            if value <= threshold:
                continue
            if value >= float(smooth[idx - 1]) and value >= float(smooth[idx + 1]):
                ring_peaks += 1

    penalty = (0.55 * _clip((annulus_ratio - 1.30) / 1.20)) + (0.45 * _clip((ring_peaks - 2.0) / 4.0))
    return _clip(penalty), {"annulus_ratio": float(annulus_ratio), "ring_peaks": float(ring_peaks)}


def _dull_palette_penalty(rgb: np.ndarray, mask: np.ndarray) -> tuple[float, dict[str, float]]:
    if rgb.size == 0 or not np.any(mask):
        return 1.0, {"mean_saturation": 0.0, "contrast": 0.0}
    norm = rgb / 255.0
    r = norm[..., 0]
    g = norm[..., 1]
    b = norm[..., 2]
    maxc = np.maximum.reduce([r, g, b])
    minc = np.minimum.reduce([r, g, b])
    saturation = np.where(maxc > 1e-5, (maxc - minc) / np.maximum(maxc, 1e-5), 0.0)
    sat_mean = float(saturation[mask].mean())

    brightness = ((r + g + b) / 3.0)[mask]
    if brightness.size:
        contrast = float(np.percentile(brightness, 95) - np.percentile(brightness, 5))
    else:
        contrast = 0.0
    penalty = (0.70 * _clip((0.18 - sat_mean) / 0.18)) + (0.30 * _clip((0.34 - contrast) / 0.34))
    return _clip(penalty), {"mean_saturation": sat_mean, "contrast": contrast}


def _rectangular_frame_penalty(edge_map: np.ndarray, mask: np.ndarray) -> tuple[float, dict[str, float]]:
    h, w = edge_map.shape[:2]
    if h <= 10 or w <= 10:
        return 0.0, {"line_strength": 0.0, "frame_vs_center_ratio": 0.0}

    valid = edge_map[mask]
    if valid.size == 0:
        return 0.0, {"line_strength": 0.0, "frame_vs_center_ratio": 0.0}
    threshold = float(np.percentile(valid, 98.8))
    strong = (edge_map >= threshold) & mask

    row_fill = strong.mean(axis=1)
    col_fill = strong.mean(axis=0)
    top_peak = float(row_fill[: max(2, int(h * 0.22))].max(initial=0.0))
    bottom_peak = float(row_fill[min(h - 1, int(h * 0.78)) :].max(initial=0.0))
    left_peak = float(col_fill[: max(2, int(w * 0.22))].max(initial=0.0))
    right_peak = float(col_fill[min(w - 1, int(w * 0.78)) :].max(initial=0.0))
    line_strength = (top_peak + bottom_peak + left_peak + right_peak) / 4.0

    yy, xx = np.ogrid[:h, :w]
    frame_band = mask & ((xx < w * 0.18) | (xx > w * 0.82) | (yy < h * 0.18) | (yy > h * 0.82))
    center_band = mask & (xx > w * 0.30) & (xx < w * 0.70) & (yy > h * 0.30) & (yy < h * 0.70)
    frame_density = float(strong[frame_band].mean()) if np.any(frame_band) else 0.0
    center_density = float(strong[center_band].mean()) if np.any(center_band) else 0.0
    frame_vs_center_ratio = frame_density / max(1e-6, center_density + 1e-6)

    penalty = (0.60 * _clip((line_strength - 0.22) / 0.38)) + (0.40 * _clip((frame_vs_center_ratio - 1.8) / 1.9))
    return _clip(penalty), {
        "line_strength": line_strength,
        "frame_vs_center_ratio": frame_vs_center_ratio,
    }


def _circular_crop_penalty(rgb: np.ndarray, mask: np.ndarray) -> tuple[float, dict[str, float]]:
    h, w = rgb.shape[:2]
    if h <= 24 or w <= 24 or not np.any(mask):
        return 0.0, {
            "center_foreground_ratio": 0.0,
            "outer_foreground_ratio": 0.0,
            "corner_foreground_ratio": 0.0,
            "corner_background_match_ratio": 0.0,
            "corner_color_spread": 1.0,
        }

    patch_h = max(8, int(h * 0.16))
    patch_w = max(8, int(w * 0.16))
    corner_mask = np.zeros((h, w), dtype=bool)
    corner_mask[:patch_h, :patch_w] = True
    corner_mask[:patch_h, w - patch_w :] = True
    corner_mask[h - patch_h :, :patch_w] = True
    corner_mask[h - patch_h :, w - patch_w :] = True
    corner_mask &= mask
    if not np.any(corner_mask):
        return 0.0, {
            "center_foreground_ratio": 0.0,
            "outer_foreground_ratio": 0.0,
            "corner_foreground_ratio": 0.0,
            "corner_background_match_ratio": 0.0,
            "corner_color_spread": 1.0,
        }

    corner_pixels = rgb[corner_mask]
    background = np.median(corner_pixels, axis=0)
    background_delta = np.linalg.norm(rgb - background.reshape(1, 1, 3), axis=2)
    corner_delta = background_delta[corner_mask]
    threshold = max(28.0, float(np.percentile(corner_delta, 92)) + 10.0) if corner_delta.size else 28.0
    foreground = (background_delta >= threshold) & mask

    yy, xx = np.ogrid[:h, :w]
    nx = (xx - ((w - 1.0) / 2.0)) / max(1.0, w / 2.0)
    ny = (yy - ((h - 1.0) / 2.0)) / max(1.0, h / 2.0)
    radial = np.sqrt((nx ** 2) + (ny ** 2))
    center_band = mask & (radial <= 0.55)
    outer_band = mask & (radial >= 0.82)

    center_foreground_ratio = float(foreground[center_band].mean()) if np.any(center_band) else 0.0
    outer_foreground_ratio = float(foreground[outer_band].mean()) if np.any(outer_band) else 0.0
    corner_foreground_ratio = float(foreground[corner_mask].mean()) if np.any(corner_mask) else 0.0
    corner_background_match_ratio = float((background_delta[corner_mask] < (threshold * 0.55)).mean()) if np.any(corner_mask) else 0.0
    corner_color_spread = float(np.std((corner_pixels / 255.0).reshape(-1, 3))) if corner_pixels.size else 1.0

    structure_penalty = (
        (0.46 * _clip((center_foreground_ratio - 0.66) / 0.22))
        + (0.32 * _clip((0.18 - outer_foreground_ratio) / 0.18))
        + (0.22 * _clip((0.14 - corner_foreground_ratio) / 0.14))
    )
    flat_background_gate = _clip((0.12 - corner_color_spread) / 0.12)
    background_match_gate = _clip((corner_background_match_ratio - 0.72) / 0.18)
    penalty = structure_penalty * ((0.55 * background_match_gate) + (0.45 * flat_background_gate))
    return _clip(penalty), {
        "center_foreground_ratio": center_foreground_ratio,
        "outer_foreground_ratio": outer_foreground_ratio,
        "corner_foreground_ratio": corner_foreground_ratio,
        "corner_background_match_ratio": corner_background_match_ratio,
        "corner_color_spread": corner_color_spread,
    }


def _transparent_corner_crop_penalty(alpha: np.ndarray) -> tuple[float, dict[str, float]]:
    h, w = alpha.shape[:2]
    if h <= 24 or w <= 24:
        return 0.0, {
            "deep_corner_transparent_ratio": 0.0,
            "outer_transparent_ratio": 0.0,
            "center_opaque_ratio": 0.0,
        }

    yy, xx = np.ogrid[:h, :w]
    nx = (xx - ((w - 1.0) / 2.0)) / max(1.0, w / 2.0)
    ny = (yy - ((h - 1.0) / 2.0)) / max(1.0, h / 2.0)
    radial = np.sqrt((nx ** 2) + (ny ** 2))
    deep_corner_band = radial >= 1.05
    outer_band = radial >= 0.82
    center_band = radial <= 0.55

    deep_corner_transparent_ratio = float((alpha[deep_corner_band] < 0.10).mean()) if np.any(deep_corner_band) else 0.0
    outer_transparent_ratio = float((alpha[outer_band] < 0.10).mean()) if np.any(outer_band) else 0.0
    center_opaque_ratio = float((alpha[center_band] > 0.90).mean()) if np.any(center_band) else 0.0

    transparency_gate = _clip((deep_corner_transparent_ratio - 0.42) / 0.24)
    structure_gate = (
        (0.56 * _clip((outer_transparent_ratio - 0.10) / 0.24))
        + (0.44 * _clip((center_opaque_ratio - 0.82) / 0.12))
    )
    penalty = transparency_gate * structure_gate
    return _clip(penalty), {
        "deep_corner_transparent_ratio": deep_corner_transparent_ratio,
        "outer_transparent_ratio": outer_transparent_ratio,
        "center_opaque_ratio": center_opaque_ratio,
    }


def _content_guardrail_score(image: Image.Image) -> tuple[float, list[str], dict[str, float]]:
    rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
    rgb = rgba[..., :3].astype(np.float32)
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    mask = alpha > 0.04
    if not np.any(mask):
        mask = np.ones(alpha.shape, dtype=bool)

    gray = rgb.mean(axis=2)
    edge_map = _edge_energy_map(gray)
    valid_edges = edge_map[mask]
    if valid_edges.size:
        edge_threshold = float(np.percentile(valid_edges, 98))
    else:
        edge_threshold = float(np.percentile(edge_map, 98))
    binary = (edge_map >= edge_threshold) & mask
    binary_ratio = float(binary.mean())

    tiny_ratio = _tiny_component_ratio(binary, mask)
    tiny_effective = float(tiny_ratio)
    if binary_ratio > 0.15:
        tiny_effective *= 0.25
    elif binary_ratio > 0.10:
        tiny_effective *= 0.45
    h = binary.shape[0]
    w = binary.shape[1]
    row_window = binary[int(h * 0.50) : int(h * 0.96), int(w * 0.12) : int(w * 0.88)]
    if row_window.size:
        row_density = row_window.mean(axis=1)
        peak_cutoff = float(row_density.mean() + (1.15 * row_density.std()) + 0.0015)
        text_band_ratio = float((row_density > peak_cutoff).mean())
    else:
        text_band_ratio = 0.0
    if min(h, w) < 128:
        tiny_effective *= 0.15
        text_band_ratio *= 0.35
    text_penalty = (0.58 * _clip((tiny_effective - 0.004) / 0.030)) + (0.42 * _clip((text_band_ratio - 0.040) / 0.16))

    ring_penalty, ring_metrics = _ring_artifact_penalty(edge_map=edge_map, mask=mask)
    frame_penalty, frame_metrics = _rectangular_frame_penalty(edge_map=edge_map, mask=mask)
    circular_crop_penalty, circular_metrics = _circular_crop_penalty(rgb=rgb, mask=mask)
    transparent_corner_penalty, transparent_metrics = _transparent_corner_crop_penalty(alpha=alpha)
    dull_penalty, color_metrics = _dull_palette_penalty(rgb=rgb, mask=mask)

    score = (
        (0.44 * text_penalty)
        + (0.22 * ring_penalty)
        + (0.20 * frame_penalty)
        + (0.34 * circular_crop_penalty)
        + (0.36 * transparent_corner_penalty)
        + (0.16 * dull_penalty)
    )
    score = _clip(score)

    issues: list[str] = []
    if text_penalty > 0.26 and (text_band_ratio > 0.12 or tiny_effective > 0.018):
        issues.append("text_or_banner_artifact")
    if ring_penalty > 0.22:
        issues.append("inner_frame_or_ring_artifact")
    if frame_penalty > 0.22:
        issues.append("rectangular_frame_artifact")
    if circular_crop_penalty > 0.26 or transparent_corner_penalty > 0.24:
        issues.append("circular_crop_artifact")
    if dull_penalty > 0.12:
        issues.append("low_vibrancy")
    metrics = {
        "text_penalty": float(text_penalty),
        "ring_penalty": float(ring_penalty),
        "frame_penalty": float(frame_penalty),
        "circular_crop_penalty": float(circular_crop_penalty),
        "dull_penalty": float(dull_penalty),
        "tiny_component_ratio": float(tiny_ratio),
        "tiny_effective": float(tiny_effective),
        "text_band_ratio": float(text_band_ratio),
        "binary_ratio": float(binary_ratio),
        "annulus_ratio": float(ring_metrics.get("annulus_ratio", 0.0)),
        "ring_peaks": float(ring_metrics.get("ring_peaks", 0.0)),
        "frame_line_strength": float(frame_metrics.get("line_strength", 0.0)),
        "frame_vs_center_ratio": float(frame_metrics.get("frame_vs_center_ratio", 0.0)),
        "circular_center_foreground_ratio": float(circular_metrics.get("center_foreground_ratio", 0.0)),
        "circular_outer_foreground_ratio": float(circular_metrics.get("outer_foreground_ratio", 0.0)),
        "circular_corner_foreground_ratio": float(circular_metrics.get("corner_foreground_ratio", 0.0)),
        "circular_corner_background_match_ratio": float(circular_metrics.get("corner_background_match_ratio", 0.0)),
        "circular_corner_color_spread": float(circular_metrics.get("corner_color_spread", 0.0)),
        "transparent_corner_penalty": float(transparent_corner_penalty),
        "transparent_deep_corner_ratio": float(transparent_metrics.get("deep_corner_transparent_ratio", 0.0)),
        "transparent_outer_ratio": float(transparent_metrics.get("outer_transparent_ratio", 0.0)),
        "transparent_center_opaque_ratio": float(transparent_metrics.get("center_opaque_ratio", 0.0)),
        "mean_saturation": float(color_metrics.get("mean_saturation", 0.0)),
    }
    return score, issues, metrics


def _is_blank_or_solid(image: Image.Image) -> bool:
    rgb = np.array(image.convert("RGB"), dtype=np.uint8)
    std = float(rgb.std())
    min_val = int(rgb.min())
    max_val = int(rgb.max())
    unique_ratio = float(np.unique(rgb.reshape(-1, 3), axis=0).shape[0]) / float(rgb.shape[0] * rgb.shape[1])
    return std < 4.0 or (max_val - min_val) < 8 or unique_ratio < 0.00001


def _download_image(url: str, timeout: float = 120.0) -> Image.Image:
    response = requests.get(url, timeout=timeout)
    if response.status_code in RETRYABLE_STATUS_CODES:
        raise RetryableGenerationError(
            f"Temporary download error {response.status_code} for {url}",
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        raise GenerationError(f"Image download failed {response.status_code}: {url}")
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def _load_prompts_payload(prompts_path: Path) -> dict[str, Any]:
    payload = safe_json.load_json(prompts_path, {})
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid prompts file at {prompts_path}: expected object payload")
    books = payload.get("books")
    if not isinstance(books, list):
        raise ValueError(f"Invalid prompts file at {prompts_path}: missing 'books' list")
    return payload


def _find_book_entry(payload: dict[str, Any], book_number: int) -> dict[str, Any]:
    for book in payload.get("books", []):
        if int(book.get("number", 0)) == int(book_number):
            return book
    raise KeyError(f"Book #{book_number} not found in prompts file")


def _find_variant(book_entry: dict[str, Any], variant_id: int) -> dict[str, Any]:
    variants = book_entry.get("variants", [])
    for item in variants:
        if int(item.get("variant_id", 0)) == int(variant_id):
            return item
    if variants:
        return variants[0]
    raise KeyError(f"Book {book_entry.get('number')} has no variants")


def _model_to_directory(model: str) -> str:
    return model.strip().lower().replace("/", "__").replace(" ", "_")


def _error_kind(error_message: str | None) -> str:
    text = (error_message or "").lower()
    if "429" in text or "rate" in text:
        return "rate_limit"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "key" in text or "credential" in text or "auth" in text:
        return "auth"
    return "provider_error"


def _append_failures(path: Path, failed_results: list[GenerationResult]) -> None:
    payload = safe_json.load_json(path, {})

    existing = payload.get("failures") if isinstance(payload, dict) else None
    if not isinstance(existing, list):
        existing = []

    timestamp = datetime.now(timezone.utc).isoformat()
    for result in failed_results:
        existing.append(
            {
                "timestamp": timestamp,
                "book_number": result.book_number,
                "variant": result.variant,
                "model": result.model,
                "provider": result.provider,
                "prompt": result.prompt,
                "error_kind": _error_kind(result.error),
                "error": result.error,
                "retries": result.attempts,
            }
        )

    output = {
        "updated_at": timestamp,
        "failures": existing,
    }
    safe_json.atomic_write_json(path, output)


def retry_failures(*, failures_path: Path, output_dir: Path, resume: bool = False) -> list[GenerationResult]:
    """Retry only failed generation rows from failure log."""
    payload = safe_json.load_json(failures_path, {})
    failures = payload.get("failures", []) if isinstance(payload, dict) else []
    if not isinstance(failures, list):
        failures = []

    results: list[GenerationResult] = []
    seen: set[tuple[int, int, str]] = set()
    for row in failures:
        if not isinstance(row, dict):
            continue
        book = _safe_int(row.get("book_number"), 0)
        variant = _safe_int(row.get("variant"), 0)
        model = str(row.get("model", ""))
        provider = str(row.get("provider", "")) or config.get_config().resolve_model_provider(model)
        prompt = str(row.get("prompt", ""))
        if book <= 0 or variant <= 0 or not model or not prompt:
            continue
        key = (book, variant, model)
        if key in seen:
            continue
        seen.add(key)
        output_path = output_dir / str(book) / _model_to_directory(model) / f"variant_{variant}.png"
        results.append(
            _generate_one(
                book_number=book,
                variant=variant,
                prompt=prompt,
                negative_prompt="",
                model=model,
                provider=provider,
                output_path=output_path,
                resume=resume,
            )
        )

    return _sort_results(results)


def _append_generation_plan(path: Path, plan_rows: list[dict[str, Any]]) -> None:
    if not plan_rows:
        return

    payload = safe_json.load_json(path, {})

    existing = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(existing, list):
        existing = []

    existing.extend(plan_rows)
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": existing,
    }
    safe_json.atomic_write_json(path, output)


def _sort_results(results: list[GenerationResult]) -> list[GenerationResult]:
    return sorted(results, key=lambda item: (item.book_number, item.model, item.variant, item.image_path is None))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_books_arg(raw: str | None) -> list[int] | None:
    if not raw:
        return None

    result: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue

        if "-" in token:
            start_str, end_str = token.split("-", 1)
            start = int(start_str)
            end = int(end_str)
            for value in range(min(start, end), max(start, end) + 1):
                result.add(value)
        else:
            result.add(int(token))

    return sorted(result)


def _build_models_from_args(args: argparse.Namespace, runtime: config.Config) -> list[str] | None:
    if args.all_models:
        return runtime.all_models[:]
    if args.models:
        return [token.strip() for token in args.models.split(",") if token.strip()]
    if args.model:
        return [args.model.strip()]
    return None


def _summarize_results(results: list[GenerationResult]) -> dict[str, Any]:
    total = len(results)
    success = sum(1 for result in results if result.success)
    failed = sum(1 for result in results if not result.success)
    skipped = sum(1 for result in results if result.skipped)
    dry_run = sum(1 for result in results if result.dry_run)
    total_cost = sum(result.cost for result in results)

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "dry_run": dry_run,
        "total_cost": round(total_cost, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 2A image generation pipeline")
    parser.add_argument("--prompts-path", type=Path, default=config.PROMPTS_PATH)
    parser.add_argument("--output-dir", type=Path, default=config.TMP_DIR / "generated")

    parser.add_argument("--book", type=int, help="Single book number for iteration mode")
    parser.add_argument("--books", type=str, help="Batch selection, e.g. 1-20 or 2,5,8")

    parser.add_argument("--model", type=str, help="Single model, e.g. openai/gpt-image-1")
    parser.add_argument("--models", type=str, help="Comma-separated model list")
    parser.add_argument("--all-models", action="store_true", help="Use all configured models")

    parser.add_argument("--variants", type=int, default=config.VARIANTS_PER_COVER)
    parser.add_argument("--prompt-variant", type=int, default=1)
    parser.add_argument("--prompt-text", type=str, default=None)
    parser.add_argument("--negative-prompt", type=str, default=None)
    parser.add_argument("--library-prompt-id", type=str, default=None)

    parser.add_argument("--provider", type=str, default=None, help="Override provider for all requests")
    parser.add_argument("--dry-run", action="store_true", help="Save generation plan without generating images")
    parser.add_argument("--no-resume", action="store_true", help="Disable skip-existing behavior")

    parser.add_argument(
        "--max-books",
        type=int,
        default=20,
        help="Batch scope limit (default 20 per D23)",
    )

    args = parser.parse_args()
    runtime = config.get_config()

    models = _build_models_from_args(args, runtime)
    resume = not args.no_resume

    if args.book is not None:
        results = generate_single_book(
            book_number=args.book,
            prompts_path=args.prompts_path,
            output_dir=args.output_dir,
            models=models,
            variants=args.variants,
            prompt_variant=args.prompt_variant,
            prompt_text=args.prompt_text,
            negative_prompt=args.negative_prompt,
            provider_override=args.provider,
            library_prompt_id=args.library_prompt_id,
            resume=resume,
            dry_run=args.dry_run,
        )
    else:
        book_selection = _parse_books_arg(args.books)
        chosen_model = None
        if models:
            chosen_model = models[0]

        results = generate_batch(
            prompts_path=args.prompts_path,
            output_dir=args.output_dir,
            resume=resume,
            books=book_selection,
            model=chosen_model,
            dry_run=args.dry_run,
            max_books=args.max_books,
        )

    summary = _summarize_results(results)
    logger.info("Generation summary: %s", summary)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
