"""LLM-powered catalog enrichment for Alexandria cover prompts."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from src import config
    from src import safe_json
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import safe_json  # type: ignore
    from logger import get_logger  # type: ignore

logger = get_logger(__name__)

DEFAULT_OUTPUT_PATH = config.CONFIG_DIR / "book_catalog_enriched.json"
DEFAULT_USAGE_PATH = config.llm_usage_path()
DEFAULT_DESCRIPTIONS_PATH = config.CONFIG_DIR / "book_descriptions.json"
DEFAULT_DELAY_SECONDS = 0.5
DEFAULT_BATCH_SIZE = 50
DEFAULT_BATCH_PAUSE_SECONDS = 5.0
DEFAULT_WORKERS = 1
DEFAULT_OPENAI_ENRICHMENT_MODEL = "gpt-4o-mini"
DEFAULT_ANTHROPIC_ENRICHMENT_MODEL = "claude-sonnet-4-5-20250929"
BANNED_GENERIC_PHRASES = [
    "central protagonist",
    "iconic turning point from",
    "defining confrontation involving",
    "period-appropriate settings",
    "historically grounded era",
    "classical dramatic tension",
    "atmospheric setting moment",
    "supporting cast",
    "antagonistic force",
    "mentor/foil",
]
GENERIC_PROTAGONISTS = {
    "",
    "central protagonist",
    "the main character",
}
TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "several",
    "the",
    "to",
    "with",
    "world",
}
KNOWN_FALLBACK_ENRICHMENT: dict[str, dict[str, Any]] = {
    "gulliver": {
        "genre": "Satirical fantasy / travel adventure",
        "era": "Early 18th century Atlantic voyages and imagined island kingdoms",
        "setting_primary": "Lilliput's shoreline and miniature imperial court",
        "setting_details": [
            "The beach where Gulliver wakes pinned down by tiny ropes",
            "The palace chambers of the Emperor of Lilliput",
            "The harbor facing rival Blefuscu across the channel",
        ],
        "protagonist": "Lemuel Gulliver — an English ship surgeon in weathered 18th-century travel clothes and boots",
        "key_characters": [
            "Lemuel Gulliver — towering castaway among miniature courtiers",
            "The Emperor of Lilliput — a tiny ruler in ceremonial robes and crown",
            "Lilliputian soldiers — six-inch archers and engineers surrounding Gulliver",
        ],
        "iconic_scenes": [
            "Lemuel Gulliver waking on the beach of Lilliput, his arms and hair pinned by hundreds of tiny ropes while ranks of six-inch soldiers climb across his coat.",
            "Gulliver kneeling before the Emperor of Lilliput as miniature courtiers crowd palace balconies and banners ripple above the tiny throne room.",
            "Gulliver wading into the harbor and towing Blefuscu's fleet by rope while alarmed Lilliputian spectators watch from the fortified shoreline.",
        ],
        "visual_motifs": [
            "Extreme scale contrast between Gulliver and the Lilliputians",
            "Miniature ropes, ladders, spears, and court regalia",
            "Seacoast light, travel gear, and satirical imperial pageantry",
        ],
        "emotional_tone": "Playful wonder edged with political satire",
        "color_palette_suggestion": "Sea blue, sandy gold, scarlet banners, and weathered brass",
        "art_period_match": "Rococo-inflected narrative illustration",
        "symbolic_elements": [
            "Tiny ropes restraining a giant traveler",
            "Imperial banners and miniature warships",
        ],
    },
    "moby dick": {
        "genre": "Maritime obsession epic",
        "era": "1840s New England whaling age",
        "setting_primary": "The Pequod on the open sea beneath storm skies",
        "setting_details": [
            "The quarterdeck of the Pequod",
            "The whaleboats lowered into violent waves",
            "The final chase across a dark rolling ocean",
        ],
        "protagonist": "Captain Ahab — scarred whaling captain with a severe gaze, sea-black coat, and ivory leg",
        "key_characters": [
            "Captain Ahab — monomaniacal commander of the Pequod",
            "Ishmael — thoughtful young sailor in rough wool and tar-stained gear",
            "Queequeg — tattooed harpooner with ceremonial adornment and harpoon",
        ],
        "iconic_scenes": [
            "Captain Ahab striking the quarterdeck of the Pequod with his ivory leg and swearing vengeance on the white whale before the assembled crew.",
            "Ishmael and Queequeg watching the whaleboats slash through black water as Moby Dick's white body erupts beside them in spray.",
            "The last chase of Moby Dick, with snapped lines, shattered boats, and Ahab dragged into the sea beneath storm clouds.",
        ],
        "visual_motifs": [
            "Harpoons, rigging, and salt-whipped sails",
            "The white whale against iron-dark water",
            "Obsessive maritime ritual and storm light",
        ],
        "emotional_tone": "Grand, tragic, and obsessive",
        "color_palette_suggestion": "Whale white, tar black, ocean blue-gray, and rusted rope brown",
        "art_period_match": "19th-century romantic seascape illustration",
        "symbolic_elements": [
            "The white whale as an overwhelming force",
            "Ahab's ivory leg and broken harpoon lines",
        ],
    },
    "dracula": {
        "genre": "Victorian gothic horror",
        "era": "Late 19th-century Eastern Europe and London",
        "setting_primary": "Dracula's Transylvanian castle and fog-bound nocturnal landscapes",
        "setting_details": [
            "The torch-lit corridors and battlements of Castle Dracula",
            "A moonlit carriage road through the Borgo Pass",
            "A crypt chamber lined with coffins and candles",
        ],
        "protagonist": "Count Dracula — aristocratic vampire with pale features, dark formal clothing, and predatory eyes",
        "key_characters": [
            "Count Dracula — ancient vampire nobleman of Transylvania",
            "Jonathan Harker — English solicitor in travel coat with lantern and papers",
            "Mina Harker — poised Victorian heroine in dark dress and determined gaze",
        ],
        "iconic_scenes": [
            "Jonathan Harker standing in the shadowed halls of Castle Dracula as the Count emerges from a stone staircase under candlelight.",
            "A black carriage racing through the Borgo Pass toward Dracula's Transylvanian castle while wolves close in beneath a blood-red moon.",
            "Van Helsing's band confronting Dracula's coffin in a crypt, holy symbols raised as the vampire's castle looms overhead.",
        ],
        "visual_motifs": [
            "Castle battlements, wolves, and candlelit stone corridors",
            "Crucifixes, coffins, and wind-blown Victorian garments",
            "Crimson moonlight and nocturnal mist",
        ],
        "emotional_tone": "Sinister, nocturnal, and suspenseful",
        "color_palette_suggestion": "Crimson, moonlit blue, ash gray, and black velvet",
        "art_period_match": "Victorian gothic illustration",
        "symbolic_elements": [
            "Castle Dracula rising over Transylvania",
            "A crucifix and coffin in candlelight",
        ],
    },
    "pride and prejudice": {
        "genre": "Regency social romance",
        "era": "Early 19th-century English Regency",
        "setting_primary": "Country estates, assembly rooms, and garden walks in Hertfordshire and Derbyshire",
        "setting_details": [
            "A candlelit assembly room at Meryton",
            "The lawns and lake at Pemberley",
            "A windswept path between Longbourn and Netherfield",
        ],
        "protagonist": "Elizabeth Bennet — bright-eyed young woman in Regency dress, walking boots, and windswept curls",
        "key_characters": [
            "Elizabeth Bennet — witty heroine with lively expression",
            "Mr. Darcy — reserved gentleman in dark tailored coat",
            "Jane Bennet — serene elder sister in pale Regency gown",
        ],
        "iconic_scenes": [
            "Elizabeth Bennet meeting Mr. Darcy across the crowded Meryton assembly room beneath chandeliers and Regency uniforms.",
            "Elizabeth walking the grounds of Pemberley while Darcy appears unexpectedly among the trees and stone balustrades.",
            "Elizabeth reading Darcy's letter in a quiet interior, sunlight falling across the page as her opinion shifts.",
        ],
        "visual_motifs": [
            "Regency gowns, gloves, letters, and ballroom light",
            "English manor architecture and landscaped gardens",
            "Subtle tension between courtship and pride",
        ],
        "emotional_tone": "Elegant, romantic, and sharply observant",
        "color_palette_suggestion": "Ivory, sage, rose, and polished mahogany",
        "art_period_match": "Regency portrait and narrative illustration",
        "symbolic_elements": [
            "A folded letter revealing hidden feeling",
            "Pemberley's architecture as a sign of character and status",
        ],
    },
    "frankenstein": {
        "genre": "Gothic science fiction tragedy",
        "era": "Late 18th-century Europe and Alpine wilderness",
        "setting_primary": "Laboratory chambers, graveyard textures, and icy mountain landscapes",
        "setting_details": [
            "Victor Frankenstein's candlelit laboratory",
            "A storm-swept churchyard and charnel-house imagery",
            "The frozen Arctic wasteland of the pursuit",
        ],
        "protagonist": "Victor Frankenstein — young scholar with fevered eyes, dark coat, and scientific instruments",
        "key_characters": [
            "Victor Frankenstein — driven student-scientist",
            "The creature — towering stitched figure with luminous eyes and rough improvised garments",
            "Elizabeth Lavenza — gentle companion in pale dress and soft lamplight",
        ],
        "iconic_scenes": [
            "Victor Frankenstein recoiling in his laboratory as the creature opens its yellow eye beneath crackling storm light and scattered instruments.",
            "The creature standing alone on an Alpine ridge above glaciers, vast clouds and jagged peaks surrounding its solitary form.",
            "Victor pursuing the creature across the Arctic ice, sled tracks cutting through snow beneath a deathly polar sky.",
        ],
        "visual_motifs": [
            "Electric storm light over scientific apparatus",
            "Stitched flesh, laboratory glass, and alpine ice",
            "Isolation within sublime natural landscapes",
        ],
        "emotional_tone": "Haunted, tragic, and sublime",
        "color_palette_suggestion": "Storm blue, glacial white, sepulchral green, and candle amber",
        "art_period_match": "Romantic gothic illustration",
        "symbolic_elements": [
            "Lightning animating forbidden creation",
            "Footprints across snow and ice",
        ],
    },
}


@dataclass(slots=True)
class UsageCounters:
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0

    def add(self, input_tokens: int, output_tokens: int, cost_per_1k: float, *, calls: int = 1) -> None:
        self.total_calls += max(0, int(calls))
        self.total_input_tokens += max(0, int(input_tokens))
        self.total_output_tokens += max(0, int(output_tokens))
        self.total_cost_usd += ((max(0, int(input_tokens)) + max(0, int(output_tokens))) / 1000.0) * float(cost_per_1k)


def enrich_catalog(
    *,
    catalog_path: Path,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    books: list[int] | None = None,
    force_refresh: bool = False,
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    cost_per_1k_tokens: float | None = None,
    usage_path: Path = DEFAULT_USAGE_PATH,
    descriptions_path: Path = DEFAULT_DESCRIPTIONS_PATH,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_pause_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Enrich catalog entries with genre/scenes/motifs metadata."""
    runtime = config.get_config()

    llm_provider, llm_model = _resolve_llm_provider_model(runtime=runtime, provider=provider, model=model)
    llm_max_tokens = int(max_tokens or int(getattr(runtime, "llm_max_tokens", 2000) or 2000))
    llm_cost = float(cost_per_1k_tokens or float(getattr(runtime, "llm_cost_per_1k_tokens", 0.003) or 0.003))

    source_catalog = _load_json_list(catalog_path)
    existing_catalog = _load_json_list(output_path)
    existing_by_number = {
        _safe_int(item.get("number"), 0): item
        for item in existing_catalog
        if isinstance(item, dict) and _safe_int(item.get("number"), 0) > 0
    }

    requested = set(int(b) for b in (books or []) if int(b) > 0)
    descriptions = _load_descriptions(descriptions_path)

    usage = UsageCounters()
    output_rows: list[dict[str, Any]] = []
    enriched_count = 0
    llm_count = 0
    fallback_count = 0

    target_numbers: set[int] = set()
    for row in source_catalog:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        existing_row = existing_by_number.get(number, {})
        existing_enrichment = existing_row.get("enrichment") if isinstance(existing_row, dict) else None
        should_attempt = False
        if requested:
            should_attempt = number in requested
        elif force_refresh:
            should_attempt = True
        else:
            should_attempt = not isinstance(existing_enrichment, dict) or not existing_enrichment
        if should_attempt:
            target_numbers.add(number)

    total_targets = len(target_numbers)
    processed_targets = 0
    pause_every = max(0, int(batch_size or 0))
    inter_call_delay = max(0.0, float(delay_seconds or 0.0))
    inter_batch_pause = max(0.0, float(batch_pause_seconds or 0.0))
    target_rows = [
        row
        for row in source_catalog
        if isinstance(row, dict) and _safe_int(row.get("number"), 0) in target_numbers
    ]
    target_results: dict[int, tuple[dict[str, Any], int, int, str]] = {}
    worker_count = max(1, min(int(workers or 1), max(1, total_targets)))

    if worker_count > 1 and total_targets > 1:
        logger.info("Running enrichment with %s workers for %s target books", worker_count, total_targets)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(
                    _generate_enrichment,
                    row=row,
                    description=descriptions.get(str(_safe_int(row.get("number"), 0)), ""),
                    provider=llm_provider,
                    model=llm_model,
                    max_tokens=llm_max_tokens,
                    runtime=runtime,
                ): row
                for row in target_rows
            }
            for future in as_completed(future_map):
                row = future_map[future]
                number = _safe_int(row.get("number"), 0)
                processed_targets += 1
                logger.info(
                    "Enriching book %s/%s: %s",
                    processed_targets,
                    max(1, total_targets),
                    str(row.get("title", f"Book {number}")).strip() or f"Book {number}",
                )
                enrichment, in_tok, out_tok, source = future.result()
                target_results[number] = (enrichment, in_tok, out_tok, source)
                if in_tok > 0 or out_tok > 0:
                    usage.add(in_tok, out_tok, llm_cost)
                if source == "llm":
                    llm_count += 1
                else:
                    fallback_count += 1
                enriched_count += 1
                if (
                    pause_every > 0
                    and inter_batch_pause > 0
                    and processed_targets < total_targets
                    and processed_targets % pause_every == 0
                ):
                    logger.info(
                        "Pausing enrichment after %s books for %.1fs to avoid rate limits",
                        processed_targets,
                        inter_batch_pause,
                    )
                    time.sleep(inter_batch_pause)
    else:
        for row in target_rows:
            number = _safe_int(row.get("number"), 0)
            processed_targets += 1
            logger.info(
                "Enriching book %s/%s: %s",
                processed_targets,
                max(1, total_targets),
                str(row.get("title", f"Book {number}")).strip() or f"Book {number}",
            )
            enrichment, in_tok, out_tok, source = _generate_enrichment(
                row=row,
                description=descriptions.get(str(number), ""),
                provider=llm_provider,
                model=llm_model,
                max_tokens=llm_max_tokens,
                runtime=runtime,
            )
            target_results[number] = (enrichment, in_tok, out_tok, source)
            if in_tok > 0 or out_tok > 0:
                usage.add(in_tok, out_tok, llm_cost)
            if source == "llm":
                llm_count += 1
            else:
                fallback_count += 1
            enriched_count += 1
            if processed_targets < total_targets and inter_call_delay > 0:
                time.sleep(inter_call_delay)
            if (
                pause_every > 0
                and inter_batch_pause > 0
                and processed_targets < total_targets
                and processed_targets % pause_every == 0
            ):
                logger.info(
                    "Pausing enrichment after %s books for %.1fs to avoid rate limits",
                    processed_targets,
                    inter_batch_pause,
                )
                time.sleep(inter_batch_pause)

    for row in source_catalog:
        if not isinstance(row, dict):
            continue
        number = _safe_int(row.get("number"), 0)
        if number <= 0:
            continue
        existing_row = existing_by_number.get(number, {})
        existing_enrichment = existing_row.get("enrichment") if isinstance(existing_row, dict) else None
        target_row = dict(row)
        if number in target_numbers:
            enrichment, _in_tok, _out_tok, _source = target_results.get(
                number,
                (_fallback_enrichment(row=row, description=descriptions.get(str(number), "")), 0, 0, "fallback"),
            )
            target_row["enrichment"] = _normalize_enrichment(enrichment, row)
        elif isinstance(existing_enrichment, dict):
            target_row["enrichment"] = _normalize_enrichment(existing_enrichment, row)
        output_rows.append(target_row)

    usage_summary = _merge_usage(
        usage_path=usage_path,
        run_usage=usage,
        enriched_count=enriched_count,
        provider=llm_provider,
        model=llm_model,
    )
    safe_json.atomic_write_many_json(
        [
            (output_path, output_rows),
            (usage_path, usage_summary),
        ]
    )

    summary = {
        "catalog": str(catalog_path),
        "output": str(output_path),
        "books_total": len(output_rows),
        "books_enriched_in_run": enriched_count,
        "books_targeted": total_targets,
        "provider": llm_provider,
        "model": llm_model,
        "usage": usage_summary,
        "llm_count": llm_count,
        "fallback_count": fallback_count,
        "validation": validate_enrichment_rows(output_rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "Enrichment complete: %s books written to %s (%s enriched in this run)",
        len(output_rows),
        output_path,
        enriched_count,
    )
    return summary


def _generate_enrichment(
    *,
    row: dict[str, Any],
    description: str,
    provider: str,
    model: str,
    max_tokens: int,
    runtime: config.Config,
) -> tuple[dict[str, Any], int, int, str]:
    # Fallback always available for offline/test mode.
    fallback = _fallback_enrichment(row=row, description=description)

    if provider == "anthropic":
        api_key = str(getattr(runtime, "anthropic_api_key", "") or "").strip()
        if not api_key:
            return fallback, 0, 0, "fallback"
        return _generate_enrichment_via_llm(
            provider_name="Anthropic",
            fallback=fallback,
            row=row,
            description=description,
            call_llm=lambda retry_guidance="": _call_anthropic(
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                row=row,
                description=description,
                retry_guidance=retry_guidance,
            ),
        )

    if provider == "openai":
        api_key = str(getattr(runtime, "openai_api_key", "") or "").strip()
        if not api_key:
            return fallback, 0, 0, "fallback"
        return _generate_enrichment_via_llm(
            provider_name="OpenAI",
            fallback=fallback,
            row=row,
            description=description,
            call_llm=lambda retry_guidance="": _call_openai(
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                row=row,
                description=description,
                retry_guidance=retry_guidance,
            ),
        )

    logger.warning("Unsupported LLM provider '%s'; using fallback enrichment", provider)
    return fallback, 0, 0, "fallback"


def _generate_enrichment_via_llm(
    *,
    provider_name: str,
    fallback: dict[str, Any],
    row: dict[str, Any],
    description: str,
    call_llm: Any,
) -> tuple[dict[str, Any], int, int, str]:
    retry_guidance = ""
    total_input_tokens = 0
    total_output_tokens = 0
    for attempt in range(1, 3):
        try:
            payload = call_llm(retry_guidance=retry_guidance)
        except Exception as exc:
            logger.warning("%s enrichment failed for book %s: %s", provider_name, row.get("number"), exc)
            return fallback, total_input_tokens, total_output_tokens, "fallback"
        total_input_tokens += _safe_int(payload.get("input_tokens"), 0)
        total_output_tokens += _safe_int(payload.get("output_tokens"), 0)
        enrichment = payload.get("enrichment", {}) if isinstance(payload, dict) else {}
        normalized = _normalize_enrichment(enrichment if isinstance(enrichment, dict) else {}, row)
        if _has_generic_content(normalized):
            logger.warning(
                "%s enrichment returned generic content for book %s on attempt %s; %s",
                provider_name,
                row.get("number"),
                attempt,
                "retrying with stricter prompt" if attempt == 1 else "using fallback enrichment",
            )
            if attempt == 1:
                retry_guidance = _generic_retry_guidance(row=row, description=description)
                continue
            return fallback, total_input_tokens, total_output_tokens, "fallback"
        return enrichment if isinstance(enrichment, dict) else normalized, total_input_tokens, total_output_tokens, "llm"
    return fallback, total_input_tokens, total_output_tokens, "fallback"


def _call_anthropic(
    *,
    api_key: str,
    model: str,
    max_tokens: int,
    row: dict[str, Any],
    description: str,
    retry_guidance: str = "",
) -> dict[str, Any]:
    user_prompt = _build_enrichment_prompt(row=row, description=description, retry_guidance=retry_guidance)
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "system": _enrichment_system_prompt(),
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Anthropic error {response.status_code}: {response.text[:240]}")

    body = response.json()
    content = body.get("content", [])
    text_parts: list[str] = []
    for part in content:
        if isinstance(part, dict) and str(part.get("type")) == "text":
            text_parts.append(str(part.get("text", "")))
    raw = "\n".join(text_parts).strip()
    parsed = _parse_json_object(raw)

    usage = body.get("usage", {}) if isinstance(body, dict) else {}
    in_tok = _safe_int(usage.get("input_tokens"), 0)
    out_tok = _safe_int(usage.get("output_tokens"), 0)

    return {
        "enrichment": parsed,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }


def _call_openai(
    *,
    api_key: str,
    model: str,
    max_tokens: int,
    row: dict[str, Any],
    description: str,
    retry_guidance: str = "",
) -> dict[str, Any]:
    user_prompt = _build_enrichment_prompt(row=row, description=description, retry_guidance=retry_guidance)
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _enrichment_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI error {response.status_code}: {response.text[:240]}")

    body = response.json()
    choices = body.get("choices", [])
    message = choices[0].get("message", {}) if choices else {}
    raw = str(message.get("content", "") or "")
    parsed = _parse_json_object(raw)

    usage = body.get("usage", {}) if isinstance(body, dict) else {}
    in_tok = _safe_int(usage.get("prompt_tokens"), 0)
    out_tok = _safe_int(usage.get("completion_tokens"), 0)

    return {
        "enrichment": parsed,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }


def _build_enrichment_prompt(*, row: dict[str, Any], description: str, retry_guidance: str = "") -> str:
    number = _safe_int(row.get("number"), 0)
    title = str(row.get("title", "")).strip()
    author = str(row.get("author", "")).strip()
    parts = [
        "Generate cover illustration metadata for this book:",
        "",
        f"Book number: {number}",
        f"Title: {title}",
        f"Author: {author}",
    ]
    if description.strip():
        parts.append(f"Description: {description.strip()}")
    if retry_guidance.strip():
        parts.extend(["", retry_guidance.strip()])

    parts.extend(
        [
            "",
            """Return a JSON object with these keys. EVERY field must be specific to THIS book:

{
  "genre": "The actual specific genre (for example: 'Satirical Fantasy / Adventure', not 'Classic Literary Fiction')",
  "era": "The actual time period of the book's setting with year or decade if known",
  "setting_primary": "The primary setting with concrete specifics",
  "setting_details": "2-4 specific locations from the book",
  "protagonist": "Real character name — visual description in period clothing or appearance",
  "key_characters": ["Character Name — brief visual descriptor", "up to 4-6 characters"],
  "iconic_scenes": [
    "A visually rich, specific scene from the book with character names, setting details, and action",
    "Minimum 3 scenes, maximum 6 scenes",
    "Each scene should be 1-2 sentences that an AI image model can illustrate"
  ],
  "visual_motifs": ["3-4 actual visual themes from the book"],
  "emotional_tone": "The actual emotional tone of the book",
  "color_palette_suggestion": "Colors that match the book's mood and setting",
  "art_period_match": "Art style that fits the book's era and genre",
  "symbolic_elements": ["2-3 actual symbols from the book with their meaning"]
}

Example iconic scene:
"Gulliver waking up on a beach, bound by hundreds of tiny ropes staked into the ground by six-inch-tall Lilliputians who climb over his body."

REMEMBER: iconic_scenes is the most critical field. Each scene MUST be a specific, visual moment from this exact book.""",
        ]
    )
    return "\n".join(parts)


def _default_model_for_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "openai":
        return DEFAULT_OPENAI_ENRICHMENT_MODEL
    if normalized == "anthropic":
        return DEFAULT_ANTHROPIC_ENRICHMENT_MODEL
    return ""


def _model_matches_provider(*, provider: str, model: str) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    token = str(model or "").strip().lower()
    if not token:
        return False
    if normalized_provider == "openai":
        return token.startswith("gpt-") or token.startswith("o1") or token.startswith("o3") or token.startswith("o4")
    if normalized_provider == "anthropic":
        return "claude" in token
    return True


def _resolve_llm_provider_model(
    *,
    runtime: config.Config,
    provider: str | None,
    model: str | None,
) -> tuple[str, str]:
    requested_provider = (provider or str(getattr(runtime, "llm_provider", "anthropic")) or "anthropic").strip().lower()
    requested_model = (model or str(getattr(runtime, "llm_model", "")) or "").strip()
    anthropic_key = str(getattr(runtime, "anthropic_api_key", "") or "").strip()
    openai_key = str(getattr(runtime, "openai_api_key", "") or "").strip()

    resolved_provider = requested_provider
    resolved_model = requested_model

    if requested_provider == "anthropic" and not anthropic_key and openai_key:
        logger.warning("Anthropic enrichment requested but no Anthropic key is configured; switching to OpenAI")
        resolved_provider = "openai"
    elif requested_provider == "openai" and not openai_key and anthropic_key:
        logger.warning("OpenAI enrichment requested but no OpenAI key is configured; switching to Anthropic")
        resolved_provider = "anthropic"
    elif requested_provider not in {"anthropic", "openai"}:
        if openai_key:
            logger.warning("Unsupported enrichment provider '%s'; switching to OpenAI", requested_provider)
            resolved_provider = "openai"
        elif anthropic_key:
            logger.warning("Unsupported enrichment provider '%s'; switching to Anthropic", requested_provider)
            resolved_provider = "anthropic"

    if not _model_matches_provider(provider=resolved_provider, model=resolved_model):
        resolved_model = _default_model_for_provider(resolved_provider)

    if not resolved_model:
        resolved_model = _default_model_for_provider(resolved_provider) or requested_model or DEFAULT_OPENAI_ENRICHMENT_MODEL

    return resolved_provider, resolved_model


def _enrichment_system_prompt() -> str:
    return """You are an expert literary art director creating metadata for AI-generated book cover illustrations. Your job is to produce SPECIFIC, ACCURATE, VISUALLY DESCRIPTIVE metadata for classic literature.

CRITICAL RULES:
1. Every field must be specific to the actual book — no generic templates.
2. The 'iconic_scenes' field is the most important — each scene must be visually descriptive enough for an AI image model to illustrate it.
3. Each iconic_scene must include real character names, specific settings, and visual details.
4. The 'protagonist' field must be the real character's name with a visual description of their appearance.
5. Do NOT use any of these generic phrases: Central protagonist, Iconic turning point from, Defining confrontation involving, Period-appropriate settings, Historically grounded era, Classical dramatic tension, Atmospheric setting moment, Supporting cast, Antagonistic force, Mentor/foil.
6. Stick to actual plot points — do not hallucinate scenes that do not exist in the book.
7. For lesser-known books, focus on the title, opening scene, climactic moment, and the primary setting.

Output valid JSON only. No markdown fences, no explanation — just the JSON object."""


def _fallback_enrichment(*, row: dict[str, Any], description: str) -> dict[str, Any]:
    title = str(row.get("title", "")).strip()
    author = str(row.get("author", "")).strip()
    title_lower = title.lower()
    for needle, payload in KNOWN_FALLBACK_ENRICHMENT.items():
        if needle in title_lower:
            return dict(payload)

    keywords = _title_keywords(title)
    keyword_phrase = ", ".join(keywords[:3]) if keywords else (title or "the story")
    clipped_description = re.sub(r"\s+", " ", description).strip()
    protagonist = (
        f"{keywords[0].title()}-linked figure in period dress and story-specific surroundings"
        if keywords
        else (f"Lead figure from {title} in period clothing" if title else "Lead literary figure in period clothing")
    )
    opening_scene = (
        clipped_description[:240]
        if clipped_description
        else f"Illustrated opening tableau of {title or 'the story'}, built around {keyword_phrase} and the first dramatic setting."
    )
    middle_scene = f"Narrative confrontation from {title or 'the book'}, emphasizing {keyword_phrase} in the central setting."
    ending_scene = f"Atmospheric closing image for {title or 'the book'}, using {keyword_phrase} as the dominant visual cue."

    return {
        "genre": _guess_genre(title_lower=title_lower, author=author),
        "era": _guess_era(title_lower=title_lower),
        "setting_primary": _guess_setting(title_lower=title_lower),
        "setting_details": [
            f"Location suggested by the imagery of {keyword_phrase}",
            f"Period environment associated with {title or 'the narrative'}",
            f"Secondary story space tied to {author or 'the author'}'s dramatic world",
        ],
        "protagonist": protagonist,
        "key_characters": [
            protagonist,
            f"Supporting figure connected to {keyword_phrase}",
            f"Opposing or reflective figure within {title or 'the narrative'}",
        ],
        "iconic_scenes": [opening_scene, middle_scene, ending_scene],
        "visual_motifs": [
            keyword_phrase,
            f"Objects and costumes associated with {title or 'the story'}",
            "Dramatic environment and symbolic props",
        ],
        "emotional_tone": f"Story-driven atmosphere for {title or 'the book'}",
        "color_palette_suggestion": "Muted classical tones with focused dramatic highlights",
        "art_period_match": "Narrative literary illustration",
        "symbolic_elements": [
            f"Recurring object or emblem tied to {keyword_phrase}",
            f"Setting motif drawn from {title or 'the narrative'}",
        ],
    }


def _guess_genre(*, title_lower: str, author: str) -> str:
    author_lower = author.lower()
    if any(token in title_lower for token in ["dracula", "frankenstein", "jungle", "island", "whale"]):
        return "Adventure / Gothic Classic"
    if any(token in title_lower for token in ["pride", "prejudice", "room with a view", "jane", "sense"]):
        return "Literary Fiction / Social Novel"
    if any(token in title_lower for token in ["hamlet", "romeo", "oedipus"]):
        return "Classical Tragedy"
    if any(token in author_lower for token in ["dostoev", "kafka", "camus"]):
        return "Psychological / Philosophical Fiction"
    if any(token in title_lower for token in ["time", "invisible", "twenty thousand", "journey"]):
        return "Speculative / Science Fiction Classic"
    return "Classic Literary Fiction"


def _guess_setting(*, title_lower: str) -> str:
    if any(token in title_lower for token in ["moby", "whale", "sea", "ocean"]):
        return "Maritime world of ships and stormy seas"
    if any(token in title_lower for token in ["dracula", "castle", "gothic"]):
        return "Castle interiors and moonlit European landscapes"
    if any(token in title_lower for token in ["pride", "prejudice", "room", "view"]):
        return "English estates and European travel settings"
    if any(token in title_lower for token in ["jungle", "island", "wild"]):
        return "Wilderness landscapes and frontier environments"
    return "Story-world setting shaped by the book's primary locations"


def _guess_era(*, title_lower: str) -> str:
    if any(token in title_lower for token in ["hamlet", "romeo", "oedipus"]):
        return "Classical / Renaissance-era dramatic tradition"
    if any(token in title_lower for token in ["moby", "whale", "dickens", "victorian", "dracula"]):
        return "19th-century literary era"
    return "Publication-era world and period atmosphere grounded in the book"


def _title_keywords(title: str, limit: int = 4) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", str(title or "").lower())
    out: list[str] = []
    for token in tokens:
        if token in TITLE_STOPWORDS or len(token) <= 2:
            continue
        if token not in out:
            out.append(token)
        if len(out) >= limit:
            break
    return out


def _normalize_enrichment(enrichment: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    fallback = _fallback_enrichment(row=row, description="")
    merged = dict(fallback)
    for key in fallback.keys():
        value = enrichment.get(key) if isinstance(enrichment, dict) else None
        if value is None:
            continue
        if isinstance(fallback[key], list):
            if isinstance(value, list):
                merged[key] = [str(item).strip() for item in value if str(item).strip()][:6]
            elif isinstance(value, str):
                merged[key] = [part.strip() for part in value.split(",") if part.strip()][:6]
            if not merged[key]:
                merged[key] = fallback[key]
        else:
            merged[key] = str(value).strip() or fallback[key]

    # Ensure minimum list lengths for downstream prompt generation quality.
    for list_key, min_items in {
        "key_characters": 3,
        "iconic_scenes": 3,
        "visual_motifs": 3,
        "symbolic_elements": 2,
    }.items():
        values = merged.get(list_key, [])
        if not isinstance(values, list):
            values = []
        while len(values) < min_items:
            values.append(str(fallback[list_key][len(values) % len(fallback[list_key])]))
        merged[list_key] = values

    return merged


def _generic_retry_guidance(*, row: dict[str, Any], description: str) -> str:
    title = str(row.get("title", "")).strip() or "this book"
    guidance = [
        f"Your previous answer for {title} used generic language and was rejected.",
        "Rewrite every field with actual character names, concrete settings, and real plot moments from the book.",
        "Do not use placeholder phrases like 'central protagonist' or 'iconic turning point'.",
    ]
    if description.strip():
        guidance.append("Use the supplied description as grounding, but keep the scenes factual to the book.")
    return " ".join(guidance)


def _has_generic_content(enrichment: dict[str, Any]) -> bool:
    if not isinstance(enrichment, dict):
        return True
    serialized = json.dumps(enrichment, ensure_ascii=False).lower()
    if any(phrase in serialized for phrase in BANNED_GENERIC_PHRASES):
        return True
    protagonist = str(enrichment.get("protagonist", "") or "").strip().lower()
    if protagonist in GENERIC_PROTAGONISTS:
        return True
    scenes = enrichment.get("iconic_scenes", [])
    if not isinstance(scenes, list) or len([scene for scene in scenes if str(scene).strip()]) < 3:
        return True
    return False


def validate_enrichment_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_books = 0
    books_with_enrichment = 0
    books_missing_enrichment = 0
    generic_rows = 0
    issues: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        total_books += 1
        number = _safe_int(row.get("number"), 0)
        enrichment = row.get("enrichment", {})
        if not isinstance(enrichment, dict) or not enrichment:
            books_missing_enrichment += 1
            issues.append(f"Book {number or '?'}: missing enrichment")
            continue
        books_with_enrichment += 1
        if _has_generic_content(enrichment):
            generic_rows += 1
            issues.append(f"Book {number or '?'}: generic enrichment detected")
    usable_books = max(0, books_with_enrichment - generic_rows)
    return {
        "total_books": total_books,
        "books_with_enrichment": books_with_enrichment,
        "books_missing_enrichment": books_missing_enrichment,
        "generic_rows": generic_rows,
        "usable_books": usable_books,
        "passed": books_missing_enrichment == 0 and generic_rows == 0,
        "issues": issues[:200],
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}

    try:
        loaded = json.loads(text)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        pass

    # Recover JSON embedded in markdown/text wrappers.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    snippet = match.group(0)
    try:
        loaded = json.loads(snippet)
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def _merge_usage(
    *,
    usage_path: Path,
    run_usage: UsageCounters,
    enriched_count: int,
    provider: str,
    model: str,
) -> dict[str, Any]:
    existing = _load_json_dict(usage_path)

    total_calls = int(existing.get("total_calls", 0) or 0) + run_usage.total_calls
    total_input = int(existing.get("total_input_tokens", 0) or 0) + run_usage.total_input_tokens
    total_output = int(existing.get("total_output_tokens", 0) or 0) + run_usage.total_output_tokens
    total_cost = float(existing.get("total_cost_usd", 0.0) or 0.0) + run_usage.total_cost_usd

    payload = {
        "total_calls": total_calls,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "per_book_avg_cost": round((run_usage.total_cost_usd / max(1, enriched_count)), 6),
        "last_run": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "calls": run_usage.total_calls,
            "input_tokens": run_usage.total_input_tokens,
            "output_tokens": run_usage.total_output_tokens,
            "cost_usd": round(run_usage.total_cost_usd, 6),
            "books_enriched": enriched_count,
        },
    }

    return payload


def _load_descriptions(path: Path) -> dict[str, str]:
    payload = _load_json_dict(path)
    out: dict[str, str] = {}
    for key, value in payload.items():
        out[str(key)] = str(value)
    return out


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    payload = safe_json.load_json(path, [])
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = safe_json.load_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _parse_books(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    values: set[int] = set()
    for token in str(raw).split(","):
        part = token.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            lo = _safe_int(start, 0)
            hi = _safe_int(end, 0)
            if lo > 0 and hi > 0:
                for value in range(min(lo, hi), max(lo, hi) + 1):
                    values.add(value)
            continue
        value = _safe_int(part, 0)
        if value > 0:
            values.add(value)
    return sorted(values) if values else None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 11A: book metadata enrichment")
    parser.add_argument("--catalog", type=Path, default=config.BOOK_CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--books", type=str, default=None, help="Book list/range, e.g. 1,5,8-12")
    parser.add_argument("--all", action="store_true", help="Process all books in the source catalog")
    parser.add_argument("--force", "--force-refresh", dest="force", action="store_true", help="Recompute even if enrichment exists")
    parser.add_argument("--provider", type=str, default=None, help="anthropic|openai")
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--cost-per-1k", type=float, default=None)
    parser.add_argument("--usage-path", type=Path, default=DEFAULT_USAGE_PATH)
    parser.add_argument("--descriptions", type=Path, default=DEFAULT_DESCRIPTIONS_PATH)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help="Delay between LLM calls in seconds")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Books to process before a batch pause")
    parser.add_argument("--batch-pause", type=float, default=DEFAULT_BATCH_PAUSE_SECONDS, help="Pause between batches in seconds")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel LLM workers for enrichment")
    parser.add_argument("--validate", action="store_true", help="Validate the enriched catalog instead of generating new data")
    args = parser.parse_args()

    if args.validate:
        payload = _load_json_list(args.output)
        summary = validate_enrichment_rows(payload)
        logger.info("Enrichment validation: %s", summary)
        return 0 if bool(summary.get("passed", False)) else 1

    summary = enrich_catalog(
        catalog_path=args.catalog,
        output_path=args.output,
        books=None if args.all else _parse_books(args.books),
        force_refresh=bool(args.force),
        provider=args.provider,
        model=args.model,
        max_tokens=args.max_tokens,
        cost_per_1k_tokens=args.cost_per_1k,
        usage_path=args.usage_path,
        descriptions_path=args.descriptions,
        delay_seconds=float(args.delay),
        batch_size=int(args.batch_size),
        batch_pause_seconds=float(args.batch_pause),
        workers=int(args.workers),
    )
    logger.info("Enrichment summary: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
