from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from src import image_generator as ig


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict | None = None,
        *,
        text: str = "",
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)
        self.content = content
        self.headers = headers or {}

    def json(self):  # type: ignore[no-untyped-def]
        return self._payload


class _Runtime:
    def __init__(self, root: Path):
        self.project_root = root
        self.image_width = 64
        self.image_height = 64
        self.request_delay = 0.0
        self.max_retries = 2
        self.provider_circuit_failure_threshold = 2
        self.provider_circuit_cooldown_seconds = 1.0
        self.batch_concurrency = 3
        self.variants_per_cover = 2
        self.ai_model = "openai/gpt-image-1"
        self.all_models = [
            "openai/gpt-image-1",
            "openrouter/flux-2-pro",
            "openrouter/google/gemini-3-pro-image-preview",
            "google/gemini-3-pro-image-preview",
            "openrouter/google/gemini-2.5-flash-image",
            "google/gemini-2.5-flash-image",
        ]
        self.provider_request_delay = {key: 0.0 for key in ["openai", "openrouter", "google", "replicate", "fal"]}
        self.provider_rate_limit_per_second = {key: 0 for key in ["openai", "openrouter", "google", "replicate", "fal"]}
        self.provider_rate_limit_per_minute = {key: 0 for key in ["openai", "openrouter", "google", "replicate", "fal"]}
        self.outbound_allowlist_domains = [
            "api.openai.com",
            "openrouter.ai",
            "fal.run",
            "api.replicate.com",
            "generativelanguage.googleapis.com",
            "img.example",
            "localhost",
        ]
        self.provider_keys = {key: "key" for key in ["openai", "openrouter", "google", "replicate", "fal"]}
        self.model_modality = {
            "openrouter/flux-2-pro": "image",
            "openrouter/google/gemini-2.5-flash-image": "both",
            "openrouter/google/gemini-3-pro-image-preview": "both",
            "flux-2-pro": "image",
            "google/gemini-2.5-flash-image": "both",
            "google/gemini-3-pro-image-preview": "both",
        }
        self.model_alias_map = {
            "nano-banana-pro": "openrouter/google/gemini-3-pro-image-preview",
            "nano-banana-2": "openrouter/google/gemini-2.5-flash-image",
        }

        self.data_dir = root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = root / "tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = root / "Output Covers"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir = root / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.book_catalog_path = self.config_dir / "book_catalog.json"
        self.book_catalog_path.write_text(json.dumps([{"number": 1, "folder_name": "1. Book"}]), encoding="utf-8")
        self.prompt_library_path = self.config_dir / "prompt_library.json"
        self.prompt_library_path.write_text(json.dumps({"prompts": [], "mixes": []}), encoding="utf-8")
        self.prompt_templates_path = self.config_dir / "prompt_templates.json"
        self.prompt_templates_path.write_text(json.dumps({"negative_prompt": "bad"}), encoding="utf-8")

        self.failures_path = self.data_dir / "generation_failures.json"
        self.generation_plan_path = self.data_dir / "generation_plan.json"

    def resolve_model_provider(self, model: str) -> str:
        token = model.lower()
        if token.startswith("openai/") or "gpt-image" in token:
            return "openai"
        if token.startswith("openrouter/") or "flux" in token or "nano" in token:
            return "openrouter"
        if token.startswith("google/") or "imagen" in token:
            return "google"
        if token.startswith("replicate/"):
            return "replicate"
        if token.startswith("fal/"):
            return "fal"
        return "openrouter"

    def get_model_cost(self, _model: str) -> float:
        return 0.05

    def get_model_modality(self, model: str) -> str:
        token = str(model or "").strip()
        normalized = token.split("/", 1)[-1] if "/" in token else token
        return str(
            self.model_modality.get(token)
            or self.model_modality.get(normalized)
            or self.model_modality.get(f"openrouter/{normalized}")
            or "image"
        )

    def resolve_model_alias(self, model: str) -> str:
        token = str(model or "").strip()
        return str(self.model_alias_map.get(token, token)).strip()

    def get_api_key(self, provider: str) -> str:
        return self.provider_keys.get(provider, "")

    def has_any_api_key(self) -> bool:
        return any(bool(str(value).strip()) for value in self.provider_keys.values())


def _image_bytes(size=(64, 64), *, gradient: bool = True) -> bytes:
    image = Image.new("RGB", size, (20, 30, 40))
    if gradient:
        pixels = image.load()
        for y in range(size[1]):
            for x in range(size[0]):
                pixels[x, y] = ((x * 3) % 255, (y * 5) % 255, (x + y) % 255)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_prompts(path: Path) -> None:
    payload = {
        "books": [
            {
                "number": 1,
                "title": "Moby Dick",
                "variants": [
                    {"variant_id": 1, "prompt": "Prompt One", "negative_prompt": "bad"},
                    {"variant_id": 2, "prompt": "Prompt Two", "negative_prompt": "bad"},
                ],
            },
            {
                "number": 2,
                "title": "Dracula",
                "variants": [
                    {"variant_id": 1, "prompt": "Prompt Three", "negative_prompt": "bad"},
                ],
            },
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_synthetic_provider_and_small_helpers():
    provider = ig.SyntheticProvider(model="any")
    for prompt in ["white whale at sea", "Dracula in castle", "dramatic oil painting", "generic classical scene"]:
        image = provider.generate(prompt=prompt, negative_prompt="none", width=128, height=128)
        assert image.size == (128, 128)

    assert ig._resolve_provider_model_name("openai", "openai/gpt-image-1") == "gpt-image-1"
    assert ig._resolve_provider_model_name("openrouter", "flux-2-pro") == "flux-2-pro"
    assert ig._model_to_directory("OpenAI/gpt image") == "openai__gpt_image"
    assert ig._error_kind("HTTP 429") == "rate_limit"
    assert ig._error_kind("timed out") == "timeout"
    assert ig._error_kind("invalid key") == "auth"
    assert ig._error_kind("unknown") == "provider_error"
    assert ig._parse_books_arg("1,3-4") == [1, 3, 4]
    assert ig._host_matches_allowlist("api.openai.com", "api.openai.com") is True
    assert ig._host_matches_allowlist("foo.openai.com", "*.openai.com") is True
    assert ig._host_matches_allowlist("foo.bar.com", "openai.com") is False
    assert ig._host_matches_allowlist("", "*.openai.com") is False
    assert ig._host_matches_allowlist("foo.bar.com", "*") is True


def test_negative_prompt_merge_and_nano_alias_resolution(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)

    merged = ig._merge_negative_prompt("custom negative")
    assert "custom negative" in merged
    assert ig.ALEXANDRIA_NEGATIVE_PROMPT in merged
    assert "No circular vignette, no medallion composition" in merged
    assert ig._resolve_provider_model_name("openrouter", "nano-banana-pro") == "google/gemini-3-pro-image-preview"
    assert ig._resolve_provider_model_name("openrouter", "nano-banana-2") == "google/gemini-2.5-flash-image"


def test_base_provider_allowlist_and_notimplemented(tmp_path: Path):
    runtime = _Runtime(tmp_path)
    provider = ig.BaseProvider(model="m", runtime=runtime)

    # Empty allowlist should allow any outbound URL.
    runtime.outbound_allowlist_domains = []
    provider._assert_outbound_url("https://blocked.example/path")

    runtime.outbound_allowlist_domains = ["api.openai.com"]
    with pytest.raises(ig.GenerationError):
        provider._assert_outbound_url("not-a-url")

    with pytest.raises(NotImplementedError):
        provider.generate("p", "n", 64, 64)


def test_rate_limiter_and_payload_helpers(tmp_path: Path, monkeypatch):
    limiter = ig.ProviderRateLimiter()
    state = {"now": 0.0}
    sleeps: list[float] = []

    def _mono():  # type: ignore[no-untyped-def]
        return state["now"]

    def _sleep(seconds):  # type: ignore[no-untyped-def]
        sleeps.append(seconds)
        state["now"] += max(1.0, float(seconds))

    monkeypatch.setattr(ig.time, "monotonic", _mono)
    monkeypatch.setattr(ig.time, "sleep", _sleep)

    limiter.wait("openai", per_second=1, per_minute=0, base_delay=0.0)
    limiter.wait("openai", per_second=1, per_minute=0, base_delay=0.0)
    assert sleeps  # second call needed backoff

    prompts_path = tmp_path / "prompts.json"
    prompts_path.write_text(json.dumps({"books": []}), encoding="utf-8")
    assert ig._load_prompts_payload(prompts_path)["books"] == []
    with pytest.raises(ValueError):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"wrong": []}), encoding="utf-8")
        ig._load_prompts_payload(bad)


def test_download_postprocess_and_blank_detection(monkeypatch):
    img = _image_bytes((32, 32), gradient=True)

    def _fake_get(url, timeout=None):  # type: ignore[no-untyped-def]
        if "retry" in url:
            return _FakeResponse(503, text="retry")
        if "fail" in url:
            return _FakeResponse(404, text="fail")
        return _FakeResponse(200, content=img)

    monkeypatch.setattr(ig.requests, "get", _fake_get)

    downloaded = ig._download_image("https://img.example/success.png")
    assert downloaded.size == (32, 32)

    with pytest.raises(ig.RetryableGenerationError):
        ig._download_image("https://img.example/retry.png")
    with pytest.raises(ig.GenerationError):
        ig._download_image("https://img.example/fail.png")

    processed = ig._post_process_image(downloaded, width=64, height=64)
    assert processed.mode == "RGBA"
    assert processed.size == (64, 64)
    assert processed.getpixel((0, 0))[3] == 255
    assert processed.getpixel((63, 63))[3] == 255

    assert ig._is_blank_or_solid(Image.new("RGB", (64, 64), (10, 10, 10))) is True
    assert ig._is_blank_or_solid(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True)))) is False


def test_guardrailed_prompt_strips_text_and_frame_directions():
    raw = "Typography-led circular vignette composition with circular medallion illustration, ribbon banner and title text"
    guarded = ig._guardrailed_prompt(raw).lower()
    assert "typography-led" not in guarded
    assert "circular vignette composition" in guarded
    assert "circular medallion illustration" not in guarded
    assert "ribbon banner" not in guarded
    assert "mandatory output rules" in guarded
    assert "no text" in guarded
    assert "vivid, high-saturation painterly palette" in guarded


def test_content_guardrail_score_flags_rings_text_and_dullness():
    artifact = Image.new("RGBA", (256, 256), (58, 64, 78, 255))
    draw = ImageDraw.Draw(artifact, "RGBA")
    draw.ellipse((14, 14, 241, 241), outline=(240, 236, 225, 255), width=5)
    draw.ellipse((24, 24, 231, 231), outline=(210, 200, 184, 255), width=4)
    draw.rectangle((52, 172, 206, 224), fill=(212, 206, 195, 255))
    for y in range(178, 222, 8):
        draw.line((64, y, 194, y), fill=(30, 30, 30, 255), width=2)

    score_artifact, issues_artifact, _metrics_artifact = ig._content_guardrail_score(artifact)
    assert score_artifact > 0.30
    assert any(
        token in issues_artifact
        for token in ("text_or_banner_artifact", "inner_frame_or_ring_artifact", "rectangular_frame_artifact")
    )

    vibrant = Image.new("RGBA", (256, 256), (0, 0, 0, 255))
    px = vibrant.load()
    for y in range(256):
        for x in range(256):
            px[x, y] = ((x * 3) % 255, (y * 5) % 255, ((x + y) * 7) % 255, 255)
    score_vibrant, issues_vibrant, _metrics_vibrant = ig._content_guardrail_score(vibrant)
    assert score_vibrant < ig.MAX_CONTENT_VIOLATION_SCORE
    assert "low_vibrancy" not in issues_vibrant


def test_content_guardrail_detects_rectangular_internal_frame():
    framed = Image.new("RGBA", (256, 256), (96, 78, 52, 255))
    draw = ImageDraw.Draw(framed, "RGBA")
    draw.rectangle((46, 42, 210, 214), outline=(220, 190, 120, 255), width=6)
    draw.rectangle((62, 58, 194, 198), outline=(170, 145, 96, 255), width=4)
    draw.ellipse((80, 92, 180, 192), fill=(145, 132, 118, 255))

    score, issues, metrics = ig._content_guardrail_score(framed)
    assert score > 0.24
    assert "rectangular_frame_artifact" in issues
    assert float(metrics.get("frame_penalty", 0.0)) > 0.20


def test_provider_classes_with_mocked_http(tmp_path: Path, monkeypatch):
    png = _image_bytes((48, 48), gradient=True)
    b64 = base64.b64encode(png).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"
    post_calls = {"google": 0}
    runtime = _Runtime(tmp_path)

    def _fake_post(url, headers=None, json=None, timeout=None):  # type: ignore[no-untyped-def]
        if "openai.com/v1/images/generations" in url:
            return _FakeResponse(200, {"data": [{"b64_json": b64}]})
        if "openrouter.ai" in url:
            return _FakeResponse(
                200,
                {"choices": [{"message": {"images": [{"image_url": data_url}]}}]},
            )
        if "fal.run" in url:
            return _FakeResponse(200, {"images": [{"url": "https://img.example/fal.png"}]})
        if "replicate.com/v1/predictions" in url:
            return _FakeResponse(200, {"id": "pred-1"})
        if "generativelanguage.googleapis.com" in url:
            post_calls["google"] += 1
            if post_calls["google"] == 1:
                return _FakeResponse(400, text="bad size")
            return _FakeResponse(
                200,
                {"candidates": [{"content": {"parts": [{"inlineData": {"data": b64}}]}}]},
            )
        raise AssertionError(f"Unexpected POST URL: {url}")

    def _fake_get(url, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        if "replicate.com/v1/predictions/pred-1" in url:
            return _FakeResponse(200, {"status": "succeeded", "output": ["https://img.example/replicate.png"]})
        if "img.example" in url:
            return _FakeResponse(200, content=png)
        raise AssertionError(f"Unexpected GET URL: {url}")

    monkeypatch.setattr(ig.requests, "post", _fake_post)
    monkeypatch.setattr(ig.requests, "get", _fake_get)

    assert ig.OpenAIProvider(model="gpt-image-1", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)
    assert ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)
    assert ig.FalProvider(model="fal/flux-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)
    assert ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)
    assert ig.GoogleCloudProvider(model="imagen-4", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)


def test_openrouter_modalities_and_429_retry(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.model_modality["openrouter/google/gemini-2.5-flash-image"] = "both"
    runtime.model_modality["google/gemini-2.5-flash-image"] = "both"
    runtime.model_modality["openrouter/flux-2-pro"] = "image"
    runtime.model_modality["flux-2-pro"] = "image"

    png = _image_bytes((48, 48), gradient=True)
    b64 = base64.b64encode(png).decode("ascii")
    calls: list[dict] = []

    def _fake_post(url, headers=None, json=None, timeout=None):  # type: ignore[no-untyped-def]
        calls.append({"url": url, "json": dict(json or {})})
        if len(calls) == 1:
            return _FakeResponse(429, text="rate", headers={"Retry-After": "0"})
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": [{"type": "output_image", "image_url": f"data:image/png;base64,{b64}"}]}}]},
        )

    monkeypatch.setattr(ig.requests, "post", _fake_post)
    monkeypatch.setattr(ig.time, "sleep", lambda _seconds: None)

    gemini = ig.OpenRouterProvider(model="google/gemini-2.5-flash-image", api_key="k", runtime=runtime)
    image = gemini.generate("p", "n", 64, 64)
    assert image.size == (48, 48)
    assert len(calls) == 2
    assert calls[-1]["json"]["modalities"] == ["image", "text"]

    calls.clear()
    flux = ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime)
    _ = flux.generate("p", "n", 64, 64)
    assert calls[-1]["json"]["modalities"] == ["image"]


def test_provider_key_and_error_paths():
    with pytest.raises(ig.GenerationError):
        ig.OpenAIProvider(model="gpt-image-1", api_key="").generate("p", "n", 64, 64)
    with pytest.raises(ig.GenerationError):
        ig.OpenRouterProvider(model="flux", api_key="").generate("p", "n", 64, 64)
    with pytest.raises(ig.GenerationError):
        ig.FalProvider(model="fal/x", api_key="").generate("p", "n", 64, 64)
    with pytest.raises(ig.GenerationError):
        ig.ReplicateProvider(model="v", api_key="").generate("p", "n", 64, 64)
    with pytest.raises(ig.GenerationError):
        ig.GoogleCloudProvider(model="imagen-4", api_key="").generate("p", "n", 64, 64)


def test_provider_allowlist_blocks_unexpected_domain(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.outbound_allowlist_domains = ["api.openai.com"]
    provider = ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime)
    with pytest.raises(ig.GenerationError):
        provider.generate("p", "n", 64, 64)


def test_generate_image_success_and_blank_rejection(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    class _Provider:
        def __init__(self, image):
            self._image = image

        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._image

    monkeypatch.setattr(
        ig,
        "_create_provider_instance",
        lambda **_kwargs: _Provider(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True)))),
    )
    output = ig.generate_image("prompt", "negative", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})
    assert output
    stats = ig.get_provider_runtime_stats()
    assert stats["openai"]["requests_today"] >= 1

    monkeypatch.setattr(
        ig,
        "_create_provider_instance",
        lambda **_kwargs: _Provider(Image.new("RGB", (64, 64), (50, 50, 50))),
    )
    with pytest.raises(ig.GenerationError):
        ig.generate_image("prompt", "negative", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})


def test_generate_image_prefixed_model_ignores_mismatched_provider(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    captured: dict[str, str] = {}

    class _Provider:
        def __init__(self, image):
            self._image = image

        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._image

    def _fake_create_provider_instance(**kwargs):  # type: ignore[no-untyped-def]
        captured["provider"] = kwargs["provider"]
        return _Provider(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True))))

    monkeypatch.setattr(ig, "_create_provider_instance", _fake_create_provider_instance)
    output = ig.generate_image(
        "prompt",
        "negative",
        "fal/fal-ai/flux-2/klein/4b",
        {"provider": "openrouter", "width": 64, "height": 64},
    )
    assert output
    assert captured["provider"] == "fal"


def test_generate_image_prefixed_model_respects_equivalent_provider_override(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    captured: dict[str, str] = {}

    class _Provider:
        def __init__(self, image):
            self._image = image

        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._image

    def _fake_create_provider_instance(**kwargs):  # type: ignore[no-untyped-def]
        captured["provider"] = kwargs["provider"]
        captured["model"] = kwargs["model"]
        return _Provider(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True))))

    monkeypatch.setattr(ig, "_create_provider_instance", _fake_create_provider_instance)
    output = ig.generate_image(
        "prompt",
        "negative",
        "openrouter/google/gemini-3-pro-image-preview",
        {"provider": "google", "width": 64, "height": 64},
    )
    assert output
    assert captured["provider"] == "google"
    assert captured["model"] == "gemini-3-pro-image-preview"


def test_generate_image_skips_hard_content_reject_for_synthetic_fallback(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    class _SyntheticProvider:
        name = "synthetic"

        def __init__(self, image):
            self._image = image

        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._image

    monkeypatch.setattr(
        ig,
        "_create_provider_instance",
        lambda **_kwargs: _SyntheticProvider(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True)))),
    )
    monkeypatch.setattr(
        ig,
        "_content_guardrail_score",
        lambda _image: (0.99, ["text_or_banner_artifact"], {}),
    )

    output = ig.generate_image("prompt", "negative", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})
    assert output


def test_generate_image_soft_text_artifact_does_not_hard_fail(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    class _Provider:
        name = "openai"

        def __init__(self, image):
            self._image = image

        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._image

    monkeypatch.setattr(
        ig,
        "_create_provider_instance",
        lambda **_kwargs: _Provider(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True)))),
    )
    monkeypatch.setattr(
        ig,
        "_content_guardrail_score",
        lambda _image: (
            0.212,
            ["text_or_banner_artifact"],
            {"text_penalty": 0.36, "text_band_ratio": 0.11, "tiny_effective": 0.014},
        ),
    )

    output = ig.generate_image("prompt", "negative", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})
    assert output


def test_generate_image_ornament_signature_text_artifact_rejects(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    class _Provider:
        name = "openai"

        def __init__(self, image):
            self._image = image

        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._image

    monkeypatch.setattr(
        ig,
        "_create_provider_instance",
        lambda **_kwargs: _Provider(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True)))),
    )
    monkeypatch.setattr(
        ig,
        "_content_guardrail_score",
        lambda _image: (
            0.212,
            ["text_or_banner_artifact"],
            {"text_penalty": 0.41, "text_band_ratio": 0.11, "tiny_effective": 0.018},
        ),
    )

    with pytest.raises(ig.GenerationError, match="text_or_banner_artifact"):
        ig.generate_image("prompt", "negative", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})


def test_generate_image_high_confidence_text_artifact_rejects(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    class _Provider:
        name = "openai"

        def __init__(self, image):
            self._image = image

        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            return self._image

    monkeypatch.setattr(
        ig,
        "_create_provider_instance",
        lambda **_kwargs: _Provider(Image.open(io.BytesIO(_image_bytes((64, 64), gradient=True)))),
    )
    monkeypatch.setattr(
        ig,
        "_content_guardrail_score",
        lambda _image: (
            0.221,
            ["text_or_banner_artifact"],
            {"text_penalty": 0.49, "text_band_ratio": 0.19, "tiny_effective": 0.018},
        ),
    )

    with pytest.raises(ig.GenerationError, match="text_or_banner_artifact"):
        ig.generate_image("prompt", "negative", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})


def test_generate_image_provider_circuit_breaker(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_circuit_failure_threshold = 2
    runtime.provider_circuit_cooldown_seconds = 5.0
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    now = {"value": 100.0}
    monkeypatch.setattr(ig.time, "monotonic", lambda: now["value"])
    monkeypatch.setattr(ig, "_CIRCUIT_BREAKER", ig.ProviderCircuitBreaker())

    class _FailingProvider:
        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise ig.RetryableGenerationError("provider temporary 503")

    monkeypatch.setattr(ig, "_create_provider_instance", lambda **_kwargs: _FailingProvider())

    with pytest.raises(ig.RetryableGenerationError):
        ig.generate_image("p", "n", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})
    with pytest.raises(ig.RetryableGenerationError):
        ig.generate_image("p", "n", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})

    with pytest.raises(ig.RetryableGenerationError) as cooldown_error:
        ig.generate_image("p", "n", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})
    assert "cooldown" in str(cooldown_error.value).lower()

    now["value"] += 6.0
    with pytest.raises(ig.RetryableGenerationError):
        ig.generate_image("p", "n", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})


def test_provider_circuit_breaker_half_open_probe_gate(monkeypatch):
    breaker = ig.ProviderCircuitBreaker()
    now = {"value": 100.0}
    monkeypatch.setattr(ig.time, "monotonic", lambda: now["value"])

    breaker.record_failure(
        "openai",
        error_text="temporary 503",
        failure_threshold=1,
        cooldown_seconds=5.0,
        transient=True,
    )
    blocked, remaining = breaker.allow("openai")
    assert blocked is False
    assert remaining > 0

    now["value"] += 6.0
    probe_allowed, probe_wait = breaker.allow("openai")
    assert probe_allowed is True
    assert probe_wait == 0.0

    second_probe_allowed, second_probe_wait = breaker.allow("openai")
    assert second_probe_allowed is False
    assert second_probe_wait > 0.0

    breaker.record_success("openai")
    after_success, after_success_wait = breaker.allow("openai")
    assert after_success is True
    assert after_success_wait == 0.0


def test_generate_image_non_retryable_error_does_not_trip_circuit(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_circuit_failure_threshold = 1
    runtime.provider_circuit_cooldown_seconds = 30.0
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)
    breaker = ig.ProviderCircuitBreaker()
    monkeypatch.setattr(ig, "_CIRCUIT_BREAKER", breaker)

    class _HardFailureProvider:
        def generate(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise ig.GenerationError("invalid prompt payload")

    monkeypatch.setattr(ig, "_create_provider_instance", lambda **_kwargs: _HardFailureProvider())

    with pytest.raises(ig.GenerationError):
        ig.generate_image("p", "n", "openai/gpt-image-1", {"provider": "openai", "width": 64, "height": 64})

    allowed, remaining = breaker.allow("openai")
    assert allowed is True
    assert remaining == 0.0
    snapshot = breaker.snapshot()["openai"]
    assert snapshot["state"] == "closed"
    assert snapshot["open_events"] == 0


def test_generate_all_models_dry_run_resume_and_failures(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    output_dir = tmp_path / "generated"
    existing = output_dir / "1" / ig._model_to_directory("openai/gpt-image-1") / "variant_1.png"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(_image_bytes((64, 64), gradient=True))

    dry_results = ig.generate_all_models(
        book_number=1,
        prompt="Prompt",
        negative_prompt="bad",
        models=["openai/gpt-image-1", "openrouter/flux-2-pro"],
        variants_per_model=2,
        output_dir=output_dir,
        dry_run=True,
        resume=True,
    )
    assert any(row.skipped for row in dry_results)
    assert any(row.dry_run for row in dry_results)
    assert runtime.generation_plan_path.exists()

    def _fake_generate_one(**kwargs):  # type: ignore[no-untyped-def]
        variant = kwargs["variant"]
        if variant == 2:
            return ig.GenerationResult(
                book_number=1,
                variant=variant,
                prompt="p",
                model=kwargs["model"],
                image_path=None,
                success=False,
                error="boom",
                generation_time=0.1,
                cost=0.0,
                provider=kwargs["provider"],
                attempts=1,
            )
        return ig.GenerationResult(
            book_number=1,
            variant=variant,
            prompt="p",
            model=kwargs["model"],
            image_path=kwargs["output_path"],
            success=True,
            error=None,
            generation_time=0.1,
            cost=0.05,
            provider=kwargs["provider"],
            attempts=1,
        )

    monkeypatch.setattr(ig, "_generate_one", _fake_generate_one)
    live_results = ig.generate_all_models(
        book_number=1,
        prompt="Prompt",
        negative_prompt="bad",
        models=["openai/gpt-image-1"],
        variants_per_model=2,
        output_dir=output_dir,
        dry_run=False,
        resume=False,
    )
    assert len(live_results) == 2
    assert any(not row.success for row in live_results)
    assert runtime.failures_path.exists()

    with pytest.raises(ValueError):
        ig.generate_all_models(
            book_number=1,
            prompt="Prompt",
            negative_prompt="bad",
            models=[],
            variants_per_model=1,
            output_dir=output_dir,
        )


def test_diversify_prompt_for_model_variant_injects_style_and_provider_hint():
    prompt = ig._diversify_prompt_for_model_variant(
        prompt="Classical medallion scene for the title.",
        model="openrouter/google/gemini-2.5-flash-image",
        provider="openrouter",
        variant=2,
        model_index=0,
    )
    assert "Style direction:" in prompt
    assert "Color direction:" in prompt
    assert "Composition direction:" in prompt
    assert "model signature:" in prompt.lower()


def test_validate_prompt_relevance_prepends_title_when_missing():
    prompt = ig._validate_prompt_relevance(
        "Painterly storm scene with dramatic ocean spray.",
        book_title="Moby Dick; Or, The Whale",
        book_author="Herman Melville",
    ).lower()
    assert "book cover illustration for 'moby dick; or, the whale'" in prompt
    assert "critical scene requirement" in prompt
    assert "melville" in prompt


def test_validate_prompt_relevance_uses_variant_scene_anchor_from_enrichment(tmp_path: Path):
    runtime = _Runtime(tmp_path)
    enriched_path = ig.config.enriched_catalog_path(config_dir=runtime.config_dir)
    enriched_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "number": 52,
                        "enrichment": {
                            "iconic_scenes": [
                                "Gulliver bound by tiny ropes in Lilliput while miniature figures swarm over him",
                                "Gulliver stands before the giant court of Brobdingnag while nobles crowd around him",
                            ],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    prompt = ig._validate_prompt_relevance(
        "Painterly satirical voyage scene.",
        book_title="Gulliver's Travels",
        book_author="Jonathan Swift",
        runtime=runtime,
        book_number=52,
        variant_index=1,
    )

    assert "CRITICAL SCENE REQUIREMENT" in prompt
    assert "Brobdingnag" in prompt
    assert "Lilliput" not in prompt


def test_validate_prompt_relevance_preserves_scene_first_prompt_order():
    prompt = ig._validate_prompt_relevance(
        (
            "Book cover illustration only - no text, no title, no author name, no lettering of any kind. "
            "No border, no frame, no ornamental elements, no medallion, no decorative edges. "
            "This illustration MUST depict the following specific scene: "
            "Emma Woodhouse and Harriet Smith walk through the gardens of Hartfield at sunset. "
            "Every figure, object, and setting element in this scene must be clearly recognizable and faithful to the source material. "
            "Rendered in Romantic Realism style - luminous regency atmosphere. "
            "The mood is witty romantic self-discovery. Era reference: Regency England. "
            "Full scene composition filling the entire canvas, no circular framing. Square format, high resolution, print-ready."
        ),
        book_title="Emma",
        book_author="Jane Austen",
    )

    assert prompt.startswith("Book cover illustration only")
    assert "Book cover illustration for 'Emma'" not in prompt
    assert "CRITICAL SCENE REQUIREMENT" not in prompt


def test_validate_prompt_relevance_falls_back_to_motif_when_enrichment_is_generic(tmp_path: Path):
    runtime = _Runtime(tmp_path)
    enriched_path = ig.config.enriched_catalog_path(config_dir=runtime.config_dir)
    enriched_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "number": 9,
                        "enrichment": {
                            "iconic_scenes": ["Iconic turning point in the story with classical dramatic tension"],
                            "protagonist": "Central protagonist",
                            "era": "Historically grounded era",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    prompt = ig._validate_prompt_relevance(
        "Painterly obsession on a storm-dark sea.",
        book_title="Moby Dick; Or, The Whale",
        book_author="Herman Melville",
        runtime=runtime,
        book_number=9,
    )

    assert "Captain Ahab" in prompt
    assert "Iconic turning point" not in prompt


def test_generate_all_models_applies_model_specific_diversity(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    output_dir = tmp_path / "generated"
    results = ig.generate_all_models(
        book_number=9,
        prompt="Classical medallion scene for the title.",
        negative_prompt="bad",
        models=["openrouter/google/gemini-2.5-flash-image", "fal/fal-ai/flux-2/klein/4b"],
        variants_per_model=1,
        output_dir=output_dir,
        dry_run=True,
        resume=False,
    )
    assert len(results) == 2
    prompt_by_model = {row.model: row.prompt for row in results}
    assert len(prompt_by_model) == 2
    prompts = list(prompt_by_model.values())
    assert prompts[0] != prompts[1]


def test_generate_single_book_and_batch(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    prompts_path = tmp_path / "book_prompts.json"
    _write_prompts(prompts_path)
    output_dir = tmp_path / "generated"

    monkeypatch.setattr(
        ig,
        "generate_all_models",
        lambda **_kwargs: [
            ig.GenerationResult(
                book_number=1,
                variant=1,
                prompt="p",
                model="openai/gpt-image-1",
                image_path=None,
                success=True,
                error=None,
                generation_time=0.0,
                cost=0.1,
                provider="openai",
                dry_run=True,
            )
        ],
    )
    results = ig.generate_single_book(
        book_number=1,
        prompts_path=prompts_path,
        output_dir=output_dir,
        models=["openai/gpt-image-1"],
        variants=1,
        prompt_text="override prompt",
        dry_run=True,
    )
    assert len(results) == 1

    class _PromptLib:
        def __init__(self, _path):
            pass

        def get_prompts(self):  # type: ignore[no-untyped-def]
            return [SimpleNamespace(id="p1", prompt_template="prompt for {title}", negative_prompt="neg")]

    monkeypatch.setattr(ig, "PromptLibrary", _PromptLib)
    results2 = ig.generate_single_book(
        book_number=1,
        prompts_path=prompts_path,
        output_dir=output_dir,
        models=["openai/gpt-image-1"],
        variants=1,
        library_prompt_id="p1",
        dry_run=True,
    )
    assert len(results2) == 1

    with pytest.raises(KeyError):
        ig.generate_single_book(
            book_number=1,
            prompts_path=prompts_path,
            output_dir=output_dir,
            models=["openai/gpt-image-1"],
            variants=1,
            library_prompt_id="missing",
            dry_run=True,
        )

    monkeypatch.setattr(
        ig,
        "_generate_one",
        lambda **kwargs: ig.GenerationResult(
            book_number=kwargs["book_number"],
            variant=kwargs["variant"],
            prompt=kwargs["prompt"],
            model=kwargs["model"],
            image_path=kwargs["output_path"],
            success=True,
            error=None,
            generation_time=0.1,
            cost=0.05,
            provider=kwargs["provider"],
            attempts=1,
        ),
    )
    batch_results = ig.generate_batch(
        prompts_path=prompts_path,
        output_dir=output_dir,
        resume=False,
        books=[1],
        model="openai/gpt-image-1",
        dry_run=False,
        max_books=2,
    )
    assert batch_results

    # Resume-skip path in batch mode.
    existing = output_dir / "1" / "variant_1.png"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(_image_bytes((64, 64), gradient=True))
    batch_skips = ig.generate_batch(
        prompts_path=prompts_path,
        output_dir=output_dir,
        resume=True,
        books=[1],
        model="openai/gpt-image-1",
        dry_run=False,
        max_books=2,
    )
    assert any(row.skipped for row in batch_skips)


def test_generate_all_models_preserve_prompt_text_skips_backend_diversification(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)

    results = ig.generate_all_models(
        book_number=1,
        prompt="Book cover illustration only - no text. Exact Alexandria prompt.",
        negative_prompt="bad",
        models=["openrouter/google/gemini-3-pro-image-preview"],
        variants_per_model=1,
        output_dir=tmp_path / "generated",
        book_title="A Room with a View",
        book_author="E. M. Forster",
        dry_run=True,
        preserve_prompt_text=True,
    )

    assert len(results) == 1
    assert results[0].prompt == "Book cover illustration only - no text. Exact Alexandria prompt."
    assert "Model signature:" not in results[0].prompt


def test_generate_one_success_failover_and_failure(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_keys = {"openai": "k", "openrouter": "k", "fal": "k", "google": "k", "replicate": "k"}
    runtime.max_retries = 2
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        ig.similarity_detector,
        "check_prompt_similarity_against_winners",
        lambda **_kwargs: {"alert": True, "closest_book": 9, "similarity": 0.91},
    )
    monkeypatch.setattr(
        ig.similarity_detector,
        "check_generated_image_against_winners",
        lambda **_kwargs: {"alert": True, "closest_book": 7, "similarity": 0.2},
    )

    output_path = tmp_path / "generated" / "1" / "variant_1.png"
    monkeypatch.setattr(ig, "generate_image", lambda **_kwargs: _image_bytes((64, 64), gradient=True))
    result = ig._generate_one(
        book_number=1,
        variant=1,
        prompt="prompt",
        negative_prompt="neg",
        model="openai/gpt-image-1",
        provider="openai",
        output_path=output_path,
        resume=False,
    )
    assert result.success is True
    assert result.image_path == output_path
    assert result.similarity_warning

    attempts = {"n": 0}

    def _flaky_generate_image(**_kwargs):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        if attempts["n"] <= 3:
            raise ig.RetryableGenerationError("temporary")
        return _image_bytes((64, 64), gradient=True)

    monkeypatch.setattr(ig, "generate_image", _flaky_generate_image)
    result2 = ig._generate_one(
        book_number=1,
        variant=2,
        prompt="prompt",
        negative_prompt="neg",
        model="flux-2-pro",
        provider="openrouter",
        output_path=tmp_path / "generated" / "1" / "variant_2.png",
        resume=False,
    )
    assert result2.success is True
    assert result2.provider in {"openai", "openrouter"}
    assert result2.attempts >= 4

    prefixed_provider_attempts: list[str] = []

    def _always_fail_prefixed(**kwargs):  # type: ignore[no-untyped-def]
        prefixed_provider_attempts.append(str(kwargs.get("params", {}).get("provider", "")))
        raise ig.RetryableGenerationError("temporary")

    monkeypatch.setattr(ig, "generate_image", _always_fail_prefixed)
    result_prefixed = ig._generate_one(
        book_number=1,
        variant=22,
        prompt="prompt",
        negative_prompt="neg",
        model="fal/fal-ai/flux-2/klein/4b",
        provider="fal",
        output_path=tmp_path / "generated" / "1" / "variant_22.png",
        resume=False,
    )
    assert result_prefixed.success is False
    assert set(prefixed_provider_attempts) == {"fal"}

    monkeypatch.setattr(ig, "generate_image", lambda **_kwargs: (_ for _ in ()).throw(ig.GenerationError("fatal")))
    result3 = ig._generate_one(
        book_number=1,
        variant=3,
        prompt="prompt",
        negative_prompt="neg",
        model="openai/gpt-image-1",
        provider="openai",
        output_path=tmp_path / "generated" / "1" / "variant_3.png",
        resume=False,
    )
    assert result3.success is False
    assert "fatal" in (result3.error or "")


def test_generate_one_openrouter_credit_exhaustion_falls_back_to_google(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_keys = {"openrouter": "k", "google": "k"}
    runtime.max_retries = 1
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ig.similarity_detector, "check_prompt_similarity_against_winners", lambda **_kwargs: {"alert": False})
    monkeypatch.setattr(
        ig.similarity_detector,
        "check_generated_image_against_winners",
        lambda **_kwargs: {"alert": False, "similarity": 1.0},
    )

    attempted_providers: list[str] = []

    def _credit_then_google(**kwargs):  # type: ignore[no-untyped-def]
        provider = str(kwargs.get("params", {}).get("provider", ""))
        attempted_providers.append(provider)
        if provider == "openrouter":
            raise ig.GenerationError("OpenRouter error 402: This request requires more credits.", status_code=402)
        return _image_bytes((64, 64), gradient=True)

    monkeypatch.setattr(ig, "generate_image", _credit_then_google)
    result = ig._generate_one(
        book_number=1,
        variant=6,
        prompt="prompt",
        negative_prompt="neg",
        model="openrouter/google/gemini-3-pro-image-preview",
        provider="openrouter",
        output_path=tmp_path / "generated" / "1" / "variant_6.png",
        resume=False,
    )
    assert result.success is True
    assert result.provider == "google"
    assert result.attempts == 2
    assert attempted_providers == ["openrouter", "google"]


def test_generate_one_artifact_error_retries_with_hardened_prompt(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_keys = {"openai": "k", "openrouter": "k", "fal": "k", "google": "k", "replicate": "k"}
    runtime.max_retries = 2
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        ig.similarity_detector,
        "check_prompt_similarity_against_winners",
        lambda **_kwargs: {"alert": False},
    )
    monkeypatch.setattr(
        ig.similarity_detector,
        "check_generated_image_against_winners",
        lambda **_kwargs: {"alert": False, "similarity": 1.0},
    )

    seen_prompts: list[str] = []
    attempts = {"n": 0}

    def _artifact_then_success(**kwargs):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        seen_prompts.append(str(kwargs.get("prompt", "")))
        if attempts["n"] == 1:
            raise ig.GenerationError("Generated image rejected by content guardrail (0.210): text_or_banner_artifact")
        return _image_bytes((64, 64), gradient=True)

    monkeypatch.setattr(ig, "generate_image", _artifact_then_success)
    result = ig._generate_one(
        book_number=1,
        variant=4,
        prompt="Original prompt",
        negative_prompt="neg",
        model="openai/gpt-image-1",
        provider="openai",
        output_path=tmp_path / "generated" / "1" / "variant_4.png",
        resume=False,
    )
    assert result.success is True
    assert result.attempts == 2
    assert len(seen_prompts) == 2
    assert "Retry instruction" in seen_prompts[1]
    assert "Retry #1" in seen_prompts[1]
    assert "Retry instruction" in result.prompt


def test_generate_one_preserve_prompt_text_keeps_saved_prompt_on_artifact_retry(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_keys = {"openai": "k", "openrouter": "k", "fal": "k", "google": "k", "replicate": "k"}
    runtime.max_retries = 2
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        ig.similarity_detector,
        "check_prompt_similarity_against_winners",
        lambda **_kwargs: {"alert": False},
    )
    monkeypatch.setattr(
        ig.similarity_detector,
        "check_generated_image_against_winners",
        lambda **_kwargs: {"alert": False, "similarity": 1.0},
    )

    original_prompt = "Book cover illustration only - no text. Exact Alexandria wildcard prompt."
    seen_prompts: list[str] = []
    attempts = {"n": 0}

    def _artifact_then_success(**kwargs):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        seen_prompts.append(str(kwargs.get("prompt", "")))
        if attempts["n"] == 1:
            raise ig.GenerationError("Generated image rejected by content guardrail (0.210): text_or_banner_artifact")
        return _image_bytes((64, 64), gradient=True)

    monkeypatch.setattr(ig, "generate_image", _artifact_then_success)
    result = ig._generate_one(
        book_number=1,
        variant=5,
        prompt=original_prompt,
        negative_prompt="neg",
        model="openai/gpt-image-1",
        provider="openai",
        output_path=tmp_path / "generated" / "1" / "variant_5.png",
        resume=False,
        preserve_prompt_text=True,
    )
    assert result.success is True
    assert result.attempts == 2
    assert len(seen_prompts) == 2
    assert "Retry instruction" in seen_prompts[1]
    assert result.prompt == original_prompt


def test_retry_failures_and_plan_helpers(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    output_dir = tmp_path / "generated"

    runtime.failures_path.write_text(
        json.dumps(
            {
                "failures": [
                    {"book_number": 1, "variant": 1, "model": "openai/gpt-image-1", "provider": "openai", "prompt": "p"},
                    {"book_number": 1, "variant": 1, "model": "openai/gpt-image-1", "provider": "openai", "prompt": "p"},
                    {"book_number": "bad", "variant": 0, "model": "", "prompt": ""},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ig,
        "_generate_one",
        lambda **kwargs: ig.GenerationResult(
            book_number=kwargs["book_number"],
            variant=kwargs["variant"],
            prompt=kwargs["prompt"],
            model=kwargs["model"],
            image_path=kwargs["output_path"],
            success=True,
            error=None,
            generation_time=0.1,
            cost=0.05,
            provider=kwargs["provider"],
            attempts=1,
        ),
    )
    retried = ig.retry_failures(failures_path=runtime.failures_path, output_dir=output_dir, resume=False)
    assert len(retried) == 1

    # append helpers tolerate invalid prior payload
    runtime.failures_path.write_text("{bad", encoding="utf-8")
    ig._append_failures(runtime.failures_path, retried)
    payload = json.loads(runtime.failures_path.read_text(encoding="utf-8"))
    assert payload["failures"]

    runtime.generation_plan_path.write_text("{bad", encoding="utf-8")
    ig._append_generation_plan(runtime.generation_plan_path, [{"book_number": 1}])
    plan = json.loads(runtime.generation_plan_path.read_text(encoding="utf-8"))
    assert plan["items"]


def test_provider_instance_resolution_and_main(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)

    # Fallback when missing key.
    runtime.provider_keys["openai"] = ""
    provider = ig._create_provider_instance(
        runtime=runtime,
        provider="openai",
        model="gpt-image-1",
        allow_synthetic_fallback=True,
    )
    assert isinstance(provider, ig.SyntheticProvider)

    with pytest.raises(ig.GenerationError):
        ig._create_provider_instance(
            runtime=runtime,
            provider="unsupported",
            model="m",
            allow_synthetic_fallback=True,
        )
    runtime.provider_keys["openai"] = "k"
    concrete_provider = ig._create_provider_instance(
        runtime=runtime,
        provider="openai",
        model="gpt-image-1",
        allow_synthetic_fallback=False,
    )
    assert isinstance(concrete_provider, ig.OpenAIProvider)
    assert ig._resolve_provider_model_name("openai", "other/gpt-image-1") == "other/gpt-image-1"

    prompts_path = tmp_path / "book_prompts.json"
    _write_prompts(prompts_path)
    args_book = SimpleNamespace(
        prompts_path=prompts_path,
        output_dir=tmp_path / "generated",
        book=1,
        books=None,
        model=None,
        models=None,
        all_models=False,
        variants=1,
        prompt_variant=1,
        prompt_text=None,
        negative_prompt=None,
        library_prompt_id=None,
        provider=None,
        dry_run=True,
        no_resume=False,
        max_books=20,
    )
    monkeypatch.setattr(ig.argparse.ArgumentParser, "parse_args", lambda self: args_book)
    monkeypatch.setattr(
        ig,
        "generate_single_book",
        lambda **_kwargs: [
            ig.GenerationResult(
                book_number=1,
                variant=1,
                prompt="p",
                model="m",
                image_path=None,
                success=True,
                error=None,
                generation_time=0.0,
                cost=0.0,
                provider="openai",
                dry_run=True,
            )
        ],
    )
    assert ig.main() == 0

    args_batch = SimpleNamespace(**args_book.__dict__)
    args_batch.book = None
    args_batch.books = "1-2"
    args_batch.models = "openai/gpt-image-1,openrouter/flux-2-pro"
    monkeypatch.setattr(ig.argparse.ArgumentParser, "parse_args", lambda self: args_batch)
    monkeypatch.setattr(
        ig,
        "generate_batch",
        lambda **_kwargs: [
            ig.GenerationResult(
                book_number=1,
                variant=1,
                prompt="p",
                model="m",
                image_path=None,
                success=False,
                error="x",
                generation_time=0.0,
                cost=0.0,
                provider="openai",
            )
        ],
    )
    assert ig.main() == 1


def test_provider_error_branches_and_fallback_payloads(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    png = _image_bytes((48, 48), gradient=True)
    b64 = base64.b64encode(png).decode("ascii")
    downloaded = Image.open(io.BytesIO(png))
    monkeypatch.setattr(ig, "_download_image", lambda *_args, **_kwargs: downloaded)

    # OpenAI retry/hard error/url fallback/missing payload.
    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(503, text="busy"))
    with pytest.raises(ig.RetryableGenerationError):
        ig.OpenAIProvider(model="gpt-image-1", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(400, text="bad"))
    with pytest.raises(ig.GenerationError):
        ig.OpenAIProvider(model="gpt-image-1", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"data": [{"url": "https://img.example/a.png"}]}))
    assert ig.OpenAIProvider(model="gpt-image-1", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"data": [{}]}))
    with pytest.raises(ig.GenerationError):
        ig.OpenAIProvider(model="gpt-image-1", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    # OpenRouter retry/hard error/choices dict fallbacks.
    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(503, text="busy"))
    with pytest.raises(ig.RetryableGenerationError):
        ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(400, text="bad"))
    with pytest.raises(ig.GenerationError):
        ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(
        ig.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            200,
            {"choices": [{"message": {"images": [{"image_url": {"url": "https://img.example/openrouter.png"}}]}}]},
        ),
    )
    assert ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(
        ig.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            200,
            {"choices": [{"message": {"images": [{"image_url": ""}]}}], "data": [{"b64_json": b64}]},
        ),
    )
    assert ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(
        ig.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(
            200,
            {"choices": [{"message": {"images": [{"image_url": "nourl"}]}}], "data": [{"url": "https://img.example/fallback.png"}]},
        ),
    )
    assert ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"choices": []}))
    with pytest.raises(ig.GenerationError):
        ig.OpenRouterProvider(model="flux-2-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    # fal.ai branches.
    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(503, text="busy"))
    with pytest.raises(ig.RetryableGenerationError):
        ig.FalProvider(model="fal/flux-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(400, text="bad"))
    with pytest.raises(ig.GenerationError):
        ig.FalProvider(model="fal/flux-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"images": []}))
    with pytest.raises(ig.GenerationError):
        ig.FalProvider(model="fal/flux-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"images": ["https://img.example/fal.png"]}))
    assert ig.FalProvider(model="fal/flux-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"images": [{"url": ""}]}))
    with pytest.raises(ig.GenerationError):
        ig.FalProvider(model="fal/flux-pro", api_key="k", runtime=runtime).generate("p", "n", 64, 64)


def test_replicate_and_google_provider_error_branches(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    png = _image_bytes((48, 48), gradient=True)
    b64 = base64.b64encode(png).decode("ascii")
    downloaded = Image.open(io.BytesIO(png))
    monkeypatch.setattr(ig, "_download_image", lambda *_args, **_kwargs: downloaded)

    # Replicate create branches.
    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(503, text="busy"))
    with pytest.raises(ig.RetryableGenerationError):
        ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(400, text="bad"))
    with pytest.raises(ig.GenerationError):
        ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {}))
    with pytest.raises(ig.GenerationError):
        ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"id": "pred-1"}))
    poll_rows = iter(
        [
            _FakeResponse(503, text="retry"),
            _FakeResponse(200, {"status": "succeeded", "output": [{"url": "https://img.example/r1.png"}]}),
        ]
    )
    monkeypatch.setattr(ig.requests, "get", lambda *_args, **_kwargs: next(poll_rows))
    monkeypatch.setattr(ig.time, "sleep", lambda _seconds: None)
    assert ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(ig.requests, "get", lambda *_args, **_kwargs: _FakeResponse(401, text="denied"))
    with pytest.raises(ig.GenerationError):
        ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "get", lambda *_args, **_kwargs: _FakeResponse(200, {"status": "succeeded", "output": "https://img.example/r2.png"}))
    assert ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(ig.requests, "get", lambda *_args, **_kwargs: _FakeResponse(200, {"status": "failed", "error": "boom"}))
    with pytest.raises(ig.GenerationError):
        ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "get", lambda *_args, **_kwargs: _FakeResponse(200, {"status": "succeeded", "output": []}))
    with pytest.raises(ig.GenerationError):
        ig.ReplicateProvider(model="version", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    # Google provider branches.
    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(503, text="busy"))
    with pytest.raises(ig.RetryableGenerationError):
        ig.GoogleCloudProvider(model="imagen-4", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(401, text="denied"))
    with pytest.raises(ig.GenerationError):
        ig.GoogleCloudProvider(model="imagen-4", api_key="k", runtime=runtime).generate("p", "n", 64, 64)

    monkeypatch.setattr(
        ig.requests,
        "post",
        lambda *_args, **_kwargs: _FakeResponse(200, {"generatedImages": [{"image": {"imageBytes": b64}}]}),
    )
    assert ig.GoogleCloudProvider(model="imagen-4", api_key="k", runtime=runtime).generate("p", "n", 64, 64).size == (48, 48)

    monkeypatch.setattr(ig.requests, "post", lambda *_args, **_kwargs: _FakeResponse(200, {"candidates": []}))
    with pytest.raises(ig.GenerationError):
        ig.GoogleCloudProvider(model="imagen-4", api_key="k", runtime=runtime).generate("p", "n", 64, 64)


def test_rate_limiter_base_delay_and_minute_window(monkeypatch):
    limiter = ig.ProviderRateLimiter()
    state = {"now": 0.0}
    sleeps: list[float] = []

    def _mono():  # type: ignore[no-untyped-def]
        return state["now"]

    def _sleep(seconds):  # type: ignore[no-untyped-def]
        sleeps.append(float(seconds))
        state["now"] += max(1.0, float(seconds))

    monkeypatch.setattr(ig.time, "monotonic", _mono)
    monkeypatch.setattr(ig.time, "sleep", _sleep)

    limiter.wait("openrouter", per_second=0, per_minute=1, base_delay=2.0)
    limiter.wait("openrouter", per_second=0, per_minute=1, base_delay=0.0)
    assert any(value >= 2.0 for value in sleeps)
    snapshot = limiter.snapshot()
    assert snapshot["openrouter"]["rate_limit_window_minute"] >= 1
    assert snapshot["openrouter"]["rate_limit_window_second"] >= 1
    state["now"] += 61.0
    limiter.wait("openrouter", per_second=0, per_minute=1, base_delay=0.0)
    limiter.reset("openrouter")
    assert "openrouter" not in limiter.snapshot()


def test_get_provider_runtime_stats_includes_rate_windows(monkeypatch):
    ig.reset_provider_runtime_state()
    state = {"now": 0.0}

    def _mono():  # type: ignore[no-untyped-def]
        return state["now"]

    def _sleep(seconds):  # type: ignore[no-untyped-def]
        state["now"] += max(1.0, float(seconds))

    monkeypatch.setattr(ig.time, "monotonic", _mono)
    monkeypatch.setattr(ig.time, "sleep", _sleep)

    ig._RATE_LIMITER.wait("openai", per_second=5, per_minute=5, base_delay=0.0)
    stats = ig.get_provider_runtime_stats()
    assert stats["openai"]["rate_limit_window_second"] >= 1
    assert stats["openai"]["rate_limit_window_minute"] >= 1

    ig.reset_provider_runtime_state("openai")
    assert "openai" not in ig.get_provider_runtime_stats()


def test_generate_single_book_default_prompt_and_model_fallback(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.all_models = []
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    prompts_path = tmp_path / "book_prompts.json"
    _write_prompts(prompts_path)
    captured: dict[str, object] = {}

    def _capture_generate_all_models(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(ig, "generate_all_models", _capture_generate_all_models)
    ig.generate_single_book(
        book_number=1,
        prompts_path=prompts_path,
        output_dir=tmp_path / "generated",
        models=None,
        variants=1,
        prompt_text=None,
        library_prompt_id=None,
        dry_run=True,
    )
    assert "Prompt One" in str(captured.get("prompt", ""))
    assert captured["models"] == [runtime.ai_model]


def test_generate_single_book_forwards_preserve_prompt_text(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    prompts_path = tmp_path / "book_prompts.json"
    _write_prompts(prompts_path)
    captured: dict[str, object] = {}

    def _capture_generate_all_models(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(ig, "generate_all_models", _capture_generate_all_models)
    ig.generate_single_book(
        book_number=1,
        prompts_path=prompts_path,
        output_dir=tmp_path / "generated",
        models=["openrouter/google/gemini-3-pro-image-preview"],
        variants=1,
        prompt_text="Book cover illustration only - no text. Exact Alexandria prompt.",
        dry_run=True,
        preserve_prompt_text=True,
    )

    assert captured["preserve_prompt_text"] is True


def test_generate_single_book_preserve_prompt_text_keeps_resolved_prompt_even_with_library_id(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    prompts_path = tmp_path / "book_prompts.json"
    _write_prompts(prompts_path)
    captured: dict[str, object] = {}

    class _PromptLib:
        def __init__(self, _path):
            pass

        def get_prompts(self):  # type: ignore[no-untyped-def]
            return [SimpleNamespace(id="p1", prompt_template="prompt for {title}", negative_prompt="library neg")]

    def _capture_generate_all_models(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(ig, "PromptLibrary", _PromptLib)
    monkeypatch.setattr(ig, "generate_all_models", _capture_generate_all_models)
    ig.generate_single_book(
        book_number=1,
        prompts_path=prompts_path,
        output_dir=tmp_path / "generated",
        models=["openrouter/google/gemini-3-pro-image-preview"],
        variants=1,
        prompt_text="Book cover illustration only - no text. Exact resolved scene prompt.",
        library_prompt_id="p1",
        dry_run=True,
        preserve_prompt_text=True,
    )

    assert captured["prompt"] == "Book cover illustration only - no text. Exact resolved scene prompt."
    assert captured["negative_prompt"] == "library neg"
    assert captured["preserve_prompt_text"] is True


def test_generate_batch_dry_run_failure_append_and_scope_limit(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.variants_per_cover = 2
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    prompts_path = tmp_path / "book_prompts.json"
    _write_prompts(prompts_path)
    output_dir = tmp_path / "generated"

    dry_results = ig.generate_batch(
        prompts_path=prompts_path,
        output_dir=output_dir,
        resume=False,
        books=None,
        model="openai/gpt-image-1",
        dry_run=True,
        max_books=1,
    )
    assert dry_results
    assert runtime.generation_plan_path.exists()

    monkeypatch.setattr(
        ig,
        "_generate_one",
        lambda **kwargs: ig.GenerationResult(
            book_number=kwargs["book_number"],
            variant=kwargs["variant"],
            prompt=kwargs["prompt"],
            model=kwargs["model"],
            image_path=None,
            success=False,
            error="fail",
            generation_time=0.0,
            cost=0.0,
            provider=kwargs["provider"],
        ),
    )
    failed = ig.generate_batch(
        prompts_path=prompts_path,
        output_dir=output_dir,
        resume=False,
        books=[1],
        model="openai/gpt-image-1",
        dry_run=False,
        max_books=2,
    )
    assert any(not row.success for row in failed)
    assert runtime.failures_path.exists()


def test_generate_one_cooldown_and_request_exception_paths(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_keys = {"openai": "k", "openrouter": "k"}
    runtime.max_retries = 1
    runtime.request_delay = 0.0
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig.time, "sleep", lambda _s: None)
    monkeypatch.setattr(ig.similarity_detector, "check_prompt_similarity_against_winners", lambda **_kwargs: {"alert": False})
    monkeypatch.setattr(ig.similarity_detector, "check_generated_image_against_winners", lambda **_kwargs: {"alert": False, "similarity": 1.0})
    monkeypatch.setattr(ig, "_provider_fallback_chain", lambda *_args, **_kwargs: ["openai", "openrouter"])

    # All providers in cooldown.
    monkeypatch.setattr(ig._CIRCUIT_BREAKER, "allow", lambda _provider: (False, 9.0))
    cooldown = ig._generate_one(
        book_number=1,
        variant=1,
        prompt="prompt",
        negative_prompt="neg",
        model="flux-2-pro",
        provider="openai",
        output_path=tmp_path / "generated" / "1" / "variant_1.png",
        resume=False,
    )
    assert cooldown.success is False
    assert "cooldown" in (cooldown.error or "").lower()

    monkeypatch.setattr(ig._CIRCUIT_BREAKER, "allow", lambda _provider: (True, 0.0))
    calls = {"n": 0}

    def _cooldown_then_success(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise ig.RetryableGenerationError("provider in cooldown")
        return _image_bytes((64, 64), gradient=True)

    monkeypatch.setattr(ig, "generate_image", _cooldown_then_success)
    switched = ig._generate_one(
        book_number=1,
        variant=2,
        prompt="prompt",
        negative_prompt="neg",
        model="flux-2-pro",
        provider="openai",
        output_path=tmp_path / "generated" / "1" / "variant_2.png",
        resume=False,
    )
    assert switched.success is True
    assert switched.provider == "openrouter"

    req_calls = {"n": 0}

    def _request_then_success(**_kwargs):  # type: ignore[no-untyped-def]
        req_calls["n"] += 1
        if req_calls["n"] == 1:
            raise ig.requests.RequestException("network down")
        return _image_bytes((64, 64), gradient=True)

    monkeypatch.setattr(ig, "generate_image", _request_then_success)
    retried = ig._generate_one(
        book_number=1,
        variant=3,
        prompt="prompt",
        negative_prompt="neg",
        model="flux-2-pro",
        provider="openai",
        output_path=tmp_path / "generated" / "1" / "variant_3.png",
        resume=False,
    )
    assert retried.success is True


def test_retry_failures_decode_and_row_filter_paths(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)

    bad_failures = tmp_path / "bad_failures.json"
    bad_failures.write_text("{bad-json", encoding="utf-8")
    assert ig.retry_failures(failures_path=bad_failures, output_dir=tmp_path / "generated") == []

    not_list_failures = tmp_path / "not_list_failures.json"
    not_list_failures.write_text(json.dumps({"failures": {}}), encoding="utf-8")
    assert ig.retry_failures(failures_path=not_list_failures, output_dir=tmp_path / "generated") == []

    mixed_failures = tmp_path / "mixed_failures.json"
    mixed_failures.write_text(json.dumps({"failures": ["row", {"book_number": 0, "variant": 0, "model": "", "prompt": ""}]}), encoding="utf-8")
    assert ig.retry_failures(failures_path=mixed_failures, output_dir=tmp_path / "generated") == []

    empty_plan = tmp_path / "plan-empty.json"
    ig._append_generation_plan(empty_plan, [])
    assert not empty_plan.exists()


def test_image_helpers_finders_and_arg_builders():
    with pytest.raises(KeyError):
        ig._find_book_entry({"books": []}, 99)
    assert ig._find_variant({"variants": [{"variant_id": 1, "prompt": "p"}]}, 7)["variant_id"] == 1
    with pytest.raises(KeyError):
        ig._find_variant({"number": 1, "variants": []}, 1)

    assert ig._parse_books_arg(None) is None
    assert ig._parse_books_arg("1,,3") == [1, 3]

    runtime = SimpleNamespace(all_models=["m1", "m2"])
    assert ig._build_models_from_args(SimpleNamespace(all_models=True, models=None, model=None), runtime) == ["m1", "m2"]
    assert ig._build_models_from_args(SimpleNamespace(all_models=False, models="x,y", model=None), runtime) == ["x", "y"]
    assert ig._build_models_from_args(SimpleNamespace(all_models=False, models=None, model="x"), runtime) == ["x"]


def test_provider_fallback_chain_skips_missing_keys_when_any_key_exists(tmp_path: Path):
    runtime = _Runtime(tmp_path)
    runtime.provider_keys = {"openai": "", "openrouter": "k", "google": "", "replicate": "", "fal": ""}
    chain = ig._provider_fallback_chain(runtime, primary="openai")
    assert chain == ["openrouter"]

    runtime.provider_keys = {"openai": "", "openrouter": "", "google": "", "replicate": "", "fal": ""}
    chain_no_keys = ig._provider_fallback_chain(runtime, primary="openai")
    assert "openai" in chain_no_keys


def test_generate_image_disables_synthetic_fallback_when_any_key_exists(tmp_path: Path, monkeypatch):
    runtime = _Runtime(tmp_path)
    runtime.provider_keys = {"openai": "", "openrouter": "k", "google": "", "replicate": "", "fal": ""}
    monkeypatch.setattr(ig.config, "get_config", lambda: runtime)
    monkeypatch.setattr(ig._RATE_LIMITER, "wait", lambda *args, **kwargs: None)

    breaker = ig.ProviderCircuitBreaker()
    monkeypatch.setattr(ig, "_CIRCUIT_BREAKER", breaker)

    with pytest.raises(ig.GenerationError):
        ig.generate_image(
            "prompt",
            "negative",
            "openai/gpt-image-1",
            {"provider": "openai", "width": 64, "height": 64},
        )
