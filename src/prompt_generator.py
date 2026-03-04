"""Phase 1B — Prompt engineering for 99 books × 5 variants."""

from __future__ import annotations

import argparse
import hashlib
import logging
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from src import safe_json
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    import safe_json  # type: ignore
    from logger import get_logger  # type: ignore

logger = get_logger(__name__)

DEFAULT_CATALOG_PATH = Path("config/book_catalog.json")
DEFAULT_TEMPLATES_PATH = Path("config/prompt_templates.json")
DEFAULT_OUTPUT_PATH = Path("config/book_prompts.json")

REQUIRED_PHRASE_COMPOSITION = "full-bleed narrative scene, centered focal subject, edge-to-edge narrative detail"
REQUIRED_PHRASE_TEXT = (
    "no text, no letters, no words, no typography"
)
REQUIRED_PHRASE_NO_FRAME = (
    "no border, no frame, no decorative edge. "
    "CRITICAL: The artwork must NOT contain any circular border, frame, wreath, "
    "garland, vine ring, floral ring, or ANY decorative edge element. "
    "The scene fills the full rectangular canvas edge-to-edge with NO circular "
    "cropping or circular framing of any kind. "
    "Paint the scene as if it extends infinitely beyond the canvas edges."
)
REQUIRED_PHRASE_VIVID = "vivid, high-saturation painterly color palette, colorful, richly colored, rich contrast"
REQUIRED_PHRASE_NO_EMPTY = "no empty space, no plain backgrounds"
REQUIRED_PHRASE_CANVAS = (
    "The final image must be a FULL rectangular canvas of solid painted scene — "
    "no circular boundaries, no vignette edges, no decorative rings. "
    "Think of this as a square painting that will later be cropped into a circle, "
    "NOT as a circular medallion with its own frame."
)
REQUIRED_PHRASE_NO_FRAME_RUNTIME = (
    "no border, no frame, no circular border, no circular frame, no wreath, no garland, no vine ring, no floral ring"
)
REQUIRED_PHRASE_CANVAS_RUNTIME = (
    "full rectangular canvas, no vignette edges, no decorative rings"
)
REQUIRED_PHRASE_NO_ORNAMENT_RUNTIME = (
    "no filigree, no scrollwork, no arabesques, no ornamental curls, "
    "no decorative flourishes, no black ornamental silhouettes, no lace-like cutout motifs"
)

REQUIRED_NEGATIVE_BORDER_TERMS: tuple[str, ...] = (
    "circular border",
    "circular frame",
    "wreath",
    "garland",
    "vine ring",
    "floral ring",
    "decorative edge",
    "ornamental ring",
    "medallion border",
    "scalloped edge",
    "filigree",
    "scrollwork",
    "arabesque",
    "ornamental flourish",
    "ornamental curls",
    "black ornamental silhouettes",
    "lace-like cutout motifs",
)

_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bcircular vignette composition\b", "full-bleed narrative scene"),
    (r"\bstructured geometry with deliberate text-safe negative space\b", "dense story-focused composition"),
    (r"\btypography[- ]led\b", "painterly"),
    (r"\btext[- ]safe\b", "detail-rich"),
    (r"\btitle[- ]safe\b", "detail-rich"),
    (r"\bthe subject is framed by\b", "the subject appears within"),
    (r"\bborders of illuminated floral arabesques\b", "illuminated floral color harmonies"),
)

_REMOVAL_PATTERNS: tuple[str, ...] = (
    r"\bgilt ornament language\b",
    r"\bfiligree\b",
    r"\bscroll(?:work)?\b",
    r"\barabesque(?:s)?\b",
    r"\btracery\b",
    r"\bflourish(?:es)?\b",
    r"\bbotanical ornament\b",
    r"\bornamental arches?\b",
    r"\blace(?:-like)?(?:\s+cutout)?(?:\s+motifs?)?\b",
    r"\bornamental(?:\s+border|\s+frame|\s+edge)?\b",
    r"\bdecorative(?:\s+edge|\s+frame|\s+border)?\b",
    r"\bcircular(?:\s+medallion|\s+vignette|\s+frame|\s+boundary|\s+cropping)?\b",
    r"\binner(?:\s+frame|\s+border|\s+ring)?\b",
    r"\bcircular frame\b",
    r"\bdecorative rings?\b",
    r"\bmedallion with (?:its )?own frame\b",
    r"\bribbon(?:\s+banner)?\b",
    r"\bscroll(?:work)?\b",
    r"\bframed by\b",
    r"\bframe(?:s|d)?\s+the\s+(?:scene|subject|composition)\b",
    r"\bnameplate\b",
    r"\bplaque\b",
    r"\bseal\b",
    r"\bframing\b",
    r"\bmedallion\s+(?:ring|frame|window|zone)\b",
    r"\bposter(?:\s+layout)?\b",
    r"\btitle(?:\s+treatment|\s+text)?\b",
    r"\btypography\b",
    r"\blogo(?:s)?\b",
    r"\bwatermark(?:s)?\b",
)

STYLE_POOL: list[dict[str, str]] = [
    {"id": "sevastopol-conflict", "label": "Sevastopol / Dramatic Conflict", "modifier": "Render as a sweeping military oil painting inspired by Vasily Vereshchagin and the Crimean War panoramas. Towering smoke columns against a blood-orange sky, shattered stone walls catching the last golden light. Palette: deep crimson, burnt sienna, cannon-smoke grey, flashes of imperial gold on epaulettes and bayonets. Thick impasto brushwork on uniforms and rubble, softer glazes for distant fires. Dramatic diagonal composition — figures surge from lower-left toward an explosive upper-right horizon. Every surface glistens with rain or sweat; the atmosphere is heavy, humid, and heroic."},
    {"id": "cossack-epic", "label": "Cossack / Epic Journey", "modifier": "Paint as a kinetic oil painting in the tradition of Ilya Repin's \"Reply of the Zaporozhian Cossacks\" and Franz Roubaud's battle panoramas. Galloping horses kicking up ochre dust against an endless steppe under a violet-streaked twilight. Palette: sunburnt ochre, Cossack-red sashes, tarnished silver sabres, deep indigo sky fading to amber at the horizon. Thick, energetic brushstrokes convey speed and fury — manes flying, cloaks billowing. Warm firelight illuminates weathered faces. The composition spirals outward from the center like a cavalry charge, filling every inch with movement and color."},
    {"id": "golden-atmosphere", "label": "Golden Atmosphere", "modifier": "Paint in the pastoral tradition of the Barbizon school — Corot, Millet, Theodore Rousseau. A scene bathed in honeyed afternoon light filtering through ancient oaks. Palette: liquid gold, warm amber, deep forest green, touches of dusty rose in the sky. Soft, feathered brushwork with visible canvas texture. Figures are small against the vast, luminous landscape. Every leaf and blade of grass catches light differently — the entire scene glows from within as if lit by a divine lamp behind the clouds."},
    {"id": "venetian-renaissance", "label": "Venetian Renaissance", "modifier": "Render in the sumptuous Venetian style of Titian, Giorgione, and Veronese. Rich sfumato modeling with warm flesh tones against deep emerald and ultramarine drapery. Palette: venetian red, lapis lazuli blue, cloth-of-gold yellow, alabaster white, deep bronze shadow. Luminous glazed layers that give skin an inner glow. Classical architecture deepens spatial depth — marble columns, brocade curtains, distant lagoon views. Every textile shimmers with painted thread detail. Compositions feel grand, balanced, and sensually alive."},
    {"id": "dutch-golden-age", "label": "Dutch Golden Age", "modifier": "Paint in the intimate tradition of Vermeer, de Hooch, and Jan Steen. A single window casts a shaft of pearl-white light across the scene, illuminating every surface with photographic precision. Palette: warm candlelight amber, cool slate blue-grey, polished mahogany brown, cream linen, touches of lemon yellow and Delft blue in ceramics. Thick impasto on metallic highlights — pewter, brass, glass. Deep velvety shadows. The composition draws the eye through a doorway or window into layered depth. Every object tells a story."},
    {"id": "dark-romantic-v2", "label": "Dark Romantic", "modifier": "Depict in the Dark Romantic tradition of Caspar David Friedrich and Gustave Dore. A moonlit or twilight scene with dramatic silvered edges. Palette: midnight indigo, icy blue-white, charcoal black, with sudden accents of blood-red berries or a single warm candle flame. Haunting, melancholic beauty. Mist curls around ancient trees and ruins. A solitary figure silhouetted against a vast, brooding sky with torn clouds revealing cold starlight. Deep atmosphere — you can almost feel the chill."},
    {"id": "pre-raphaelite-v2", "label": "Pre-Raphaelite", "modifier": "Render in the lush, hyper-detailed Pre-Raphaelite style of Waterhouse, Rossetti, and Millais. Jewel-toned colors that sing: deep ruby garments, emerald moss-covered banks, sapphire water, and golden autumn leaves. Meticulous botanical detail — individual petals, veins on leaves, embroidery threads. Ethereal figures with flowing copper or raven hair, draped in medieval fabrics of damask and velvet. Rich symbolism: lilies for purity, roses for passion, willow for sorrow. Light enters from the upper left creating an otherworldly radiance."},
    {"id": "art-nouveau-v2", "label": "Art Nouveau", "modifier": "Create in the expressive Art Nouveau color-and-line tradition of Alphonse Mucha and Eugene Grasset. Flowing organic line rhythm — sinuous vines, lily stems, and graceful movement in fabrics and hair. Palette: sage green, dusty rose, antique gold, deep teal, warm ivory. Flat color areas with fine painterly linework. Keep the composition scene-first and full-bleed with one dominant subject and atmospheric depth. Muted metallic accents throughout — gold leaf, bronze patina, copper highlights."},
    {"id": "ukiyo-e-v2", "label": "Ukiyo-e Woodblock", "modifier": "Reimagine as a Japanese ukiyo-e woodblock print in the tradition of Hokusai and Hiroshige. Bold black outlines with flat areas of saturated color. Palette: deep indigo, vermillion red, pale ochre, celadon green, white rice-paper negative space. Fine parallel hatching for sky, waves, and rain. Dramatic spatial tension with exaggerated perspective. Stylized waves, windblown cherry blossoms, or towering mountains create dynamic movement. A striking interplay of pattern and void — every empty space is as deliberate as every filled one."},
    {"id": "noir-v2", "label": "Film Noir", "modifier": "Depict as a high-contrast film noir composition straight from 1940s Hollywood. Palette: pure black, brilliant white, with ONE dramatic accent — a deep amber streetlight, a crimson lipstick, or a neon sign reflected in wet pavement. Hard-edged silhouettes, slashing Venetian blind shadows, extreme chiaroscuro. Figures caught in dramatic angles — shot from below or above. Rain-slicked streets reflect fragmented light. Cigarette smoke curls into geometric patterns. Moral ambiguity made visual."},
    {"id": "botanical-v2", "label": "Botanical Engraving", "modifier": "Render as a vintage scientific illustration in the tradition of Maria Sibylla Merian and Pierre-Joseph Redoute. Exquisitely detailed: fine intaglio linework with hairline cross-hatching and stipple shading creating three-dimensional form. Hand-applied watercolor washes: soft leaf green, petal pink, butterfly-wing orange, lichen yellow. The subject is centered on a cream parchment ground with pencil construction lines faintly visible. Latin labels in copperplate script. Precision meets artistic beauty — every stamen, every wing scale rendered with love."},
    {"id": "stained-glass-v2", "label": "Gothic Stained Glass", "modifier": "Create a luminous Gothic stained-glass color language translated into a painted narrative scene. Rich jewel-toned color blocks glow with inner light: ruby red, cobalt blue, emerald green, amber gold, amethyst purple. Strong lead-like contour lines guide form without creating borders. Light streams through mist and stone to create prismatic pools of color. Figures are stylized and iconic with flowing robes. The overall effect is transcendent and awe-inspiring, like sunrise light through cathedral glass."},
    {"id": "impressionist-v2", "label": "Impressionist", "modifier": "Paint in the sun-drenched Impressionist style of Monet, Renoir, and Pissarro. Visible dappled brushstrokes that dissolve form into pure light and color. Palette: lavender shadow, rose-pink skin, sky blue reflected in water, warm peach sunlight, chartreuse new leaves. No hard edges — everything shimmers and vibrates. Emphasis on the play of natural light on water, foliage, or figures. A sense of a perfect afternoon frozen in time — warm, joyful, alive with color. Paint applied thickly so individual strokes catch their own light."},
    {"id": "expressionist-v2", "label": "Expressionist", "modifier": "Render in the raw, emotionally charged style of Munch, Kirchner, and Emil Nolde. Colors are weapons: acid yellow, blood orange, electric blue, toxic green — applied in thick, agitated brushstrokes that seem to vibrate with anxiety. Warped perspectives and exaggerated proportions. Faces are masks of emotion. The sky may swirl, buildings may lean, shadows may reach like grasping hands. Everything is psychologically charged. The palette should feel almost violent in its intensity — beauty through discomfort."},
    {"id": "baroque-v2", "label": "Baroque Drama", "modifier": "Depict as a grand Baroque composition worthy of Rubens, Velazquez, or Artemisia Gentileschi. A single dramatic light source (upper left) carves figures from deep velvet darkness. Palette: crimson silk, liquid gold, ivory flesh, deep shadow approaching black. Dynamic diagonal composition — bodies twist, arms reach, fabric billows in invisible wind. Extreme physicality and emotion. Thick impasto on highlights, transparent glazes in shadows. Figures caught at the peak of action — the most dramatic possible moment."},
    {"id": "watercolour-v2", "label": "Delicate Watercolour", "modifier": "Paint as a refined watercolour illustration evoking beloved vintage book editions. Translucent washes where colors bloom and bleed softly into one another. The white paper ground glows through every stroke. Palette: muted cerulean blue, sage green, warm grey, burnt sienna, with accents of violet and rose. Soft, fluid edges with no hard lines — everything dissolves at the margins. Fine pen linework adds delicate structure. The mood is intimate, gentle, and nostalgic — like discovering a treasured illustration in a grandmother's bookshelf."},
    {"id": "symbolist-v2", "label": "Symbolist Dream", "modifier": "Create in the mystical Symbolist tradition of Gustave Moreau, Odilon Redon, and Fernand Khnopff. A dreamlike, otherworldly scene shimmering between reality and vision. Palette: deep purple, tarnished gold, midnight blue, absinthe green, with iridescent highlights that shift like oil on water. Soft, hazy edges where forms dissolve into mist. Figures and elements feel archetypal — the Sphinx, the Angel, the Tower, the Rose. Eyes that see beyond the visible world. Rich mystical symbolism layered into every element."},
    {"id": "persian-miniature", "label": "Persian Miniature", "modifier": "Render in the exquisite tradition of Persian miniature painting — Reza Abbasi, Kamal ud-Din Behzad. Bird's-eye perspective with no single vanishing point; the scene unfolds across multiple spatial planes simultaneously. Palette: lapis lazuli blue, vermillion, leaf gold, turquoise, saffron yellow, rose pink. Ultra-fine brushwork: individual leaves on trees, patterns on textiles, and tiles on architecture. Figures are elegant with almond eyes and flowing garments. Use illuminated floral color harmonies and dense narrative detail across the full scene."},
    {"id": "russian-realist-v2", "label": "Russian Realist", "modifier": "Paint in the tradition of the Peredvizhniki — Ilya Repin, Ivan Kramskoi, Vasily Surikov, Isaac Levitan. Dense atmospheric detail with muted earth tones that suddenly catch fire with patches of vivid color. Palette: ochre, raw umber, slate grey, with flashes of birch-white, blood-red, and the golden glow of icon lamps. Thick expressive brushwork that captures raw human emotion and the vastness of the Russian landscape. Faces are unflinchingly honest — every wrinkle, every tear, every defiant glance tells a story. Deep, humane, and monumental."},
    {"id": "romantic-sublime", "label": "Romantic Sublime", "modifier": "Paint in the awe-inspiring style of Turner, John Martin, and Frederic Edwin Church. VAST landscapes that dwarf human figures — towering mountains, raging seas, volcanic skies. Palette: molten gold and amber sunsets, storm-purple clouds, electric white lightning, deep ocean teal, misty lavender distances. The sky takes up two-thirds of the composition and is the real subject. Light breaks through clouds in god-rays. The feeling is of standing at the edge of creation — sublime terror and beauty combined. Thick, energetic brushwork in the sky, finer detail in the landscape below."},
]

FIXED_VARIANT_STYLE_IDS: list[str] = [
    "pre-raphaelite-v2",
    "baroque-v2",
]

CURATED_VARIANT_STYLE_IDS: list[str] = [
    "golden-atmosphere",
    "venetian-renaissance",
    "dutch-golden-age",
    "dark-romantic-v2",
    "sevastopol-conflict",
    "art-nouveau-v2",
    "ukiyo-e-v2",
    "noir-v2",
]

# Compatibility alias used by tests and downstream imports.
PRIMARY_VARIANT_STYLE_IDS: list[str] = [
    *FIXED_VARIANT_STYLE_IDS,
    *CURATED_VARIANT_STYLE_IDS,
]

PROMPT_LIBRARY_BUILTINS: list[dict[str, str]] = [dict(row) for row in STYLE_POOL[:10]]

_BUILTIN_BY_ID = {row["id"]: row for row in PROMPT_LIBRARY_BUILTINS}
_STYLE_POOL_BY_ID = {row["id"]: row for row in STYLE_POOL}


def _seeded_fisher_yates(rows: list[dict[str, str]], seed_token: str) -> list[dict[str, str]]:
    output = list(rows)
    if len(output) <= 1:
        return output
    digest = hashlib.sha1(str(seed_token or "alexandria").encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:8], 16))
    for idx in range(len(output) - 1, 0, -1):
        swap = rng.randint(0, idx)
        output[idx], output[swap] = output[swap], output[idx]
    return output


def _style_rows_from_ids(style_ids: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for style_id in style_ids:
        row = _BUILTIN_BY_ID.get(style_id) or _STYLE_POOL_BY_ID.get(style_id)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def select_diverse_styles(count: int, *, seed_token: str = "") -> list[dict[str, str]]:
    """Return style rows with a deterministic 2+3+5 plan for the first 10 variants."""
    wanted = max(0, int(count))
    if wanted <= 0:
        return []

    output: list[dict[str, str]] = []
    seen: set[str] = set()

    def _push_unique(rows: list[dict[str, str]], cap: int | None = None) -> None:
        nonlocal output
        remaining = cap if cap is not None else len(rows)
        for row in rows:
            style_id = str(row.get("id", "")).strip()
            if not style_id or style_id in seen:
                continue
            output.append(row)
            seen.add(style_id)
            if len(output) >= wanted:
                return
            remaining -= 1
            if remaining <= 0:
                return

    # 1) Fixed anchors.
    _push_unique(_style_rows_from_ids(FIXED_VARIANT_STYLE_IDS))
    if len(output) >= wanted:
        return output[:wanted]

    # 2) Curated middle styles (pick 3, deterministic shuffle per title/prompt).
    curated_rows = _seeded_fisher_yates(_style_rows_from_ids(CURATED_VARIANT_STYLE_IDS), f"{seed_token}::curated")
    _push_unique(curated_rows, cap=3)
    if len(output) >= wanted:
        return output[:wanted]

    # 3) Wildcards from broader style pool, excluding fixed/curated ids.
    reserved = set(FIXED_VARIANT_STYLE_IDS) | set(CURATED_VARIANT_STYLE_IDS)
    wildcard_pool = [
        row
        for row in STYLE_POOL
        if str(row.get("id", "")).strip() and str(row.get("id", "")).strip() not in reserved
    ]
    wildcard_rows = _seeded_fisher_yates(wildcard_pool, f"{seed_token}::wildcards")
    _push_unique(wildcard_rows, cap=5)
    if len(output) >= wanted:
        return output[:wanted]

    # 4) Fill remainder from full style inventory, then cycle if needed.
    full_pool: list[dict[str, str]] = []
    full_seen: set[str] = set()
    for row in PROMPT_LIBRARY_BUILTINS + STYLE_POOL:
        style_id = str(row.get("id", "")).strip()
        if not style_id or style_id in full_seen:
            continue
        full_pool.append(row)
        full_seen.add(style_id)
    if not full_pool:
        return []

    _push_unique(_seeded_fisher_yates(full_pool, f"{seed_token}::full"))
    cycle = 1
    while len(output) < wanted:
        cycle_rows = _seeded_fisher_yates(full_pool, f"{seed_token}::cycle::{cycle}")
        for row in cycle_rows:
            output.append(row)
            if len(output) >= wanted:
                break
        cycle += 1
    return output


def build_diversified_prompt(title: str, author: str, style: dict[str, str]) -> str:
    """Build a title-aware diversified prompt with strict scene-only output rules."""
    label = str(style.get("label", "Classical Illustration")).strip() or "Classical Illustration"
    modifier = str(style.get("modifier", "")).strip()
    style_modifier = (
        modifier
        or "Classical illustration using ruby red, emerald green, cobalt blue, amber gold, and ivory highlights."
    )
    canvas_directive = (
        "The final image must be a FULL rectangular canvas of solid painted scene — "
        "no circular boundaries, no vignette edges, no decorative rings. "
        "Think of this as a square painting that will later be cropped into a circle, "
        "NOT as a circular medallion with its own frame."
    )
    base = " ".join(
        [
            f'Create a breathtaking, richly colored illustration for the classic book "{title}" by {author}. Style direction: {label}.',
            "Identify the single most iconic, dramatic, and visually striking scene from this specific story — the moment readers remember most vividly.",
            "No border, no frame, no decorative edge.",
            "Depict that scene as a luminous full-bleed narrative illustration for a luxury leather-bound edition.",
            "Adapt all motifs, costumes, architecture, and symbols strictly to this specific book; avoid cross-book visual clichés.",
            "Fill the entire rectangular composition with rich detail and vivid color — no empty space, no plain backgrounds.",
            "The artwork must feel like a museum-quality painting that captures the emotional heart of the story.",
            style_modifier,
            "CRITICAL COMPOSITION RULES: Keep one dominant focal subject and edge-to-edge scene detail.",
            "NO text, NO letters, NO words anywhere in the image.",
            "The scene must be COLORFUL and DETAILED — avoid monochrome, avoid sparse compositions.",
            "Keep one dominant focal subject, layered depth, dense detail.",
            canvas_directive,
        ]
    )
    return _ensure_prompt_constraints(base)


@dataclass
class BookPrompt:
    """One generated prompt variant for one book."""

    book_number: int
    book_title: str
    book_author: str
    variant_id: int
    variant_key: str
    variant_name: str
    description: str
    prompt: str
    negative_prompt: str
    style_reference: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "variant_key": self.variant_key,
            "variant_name": self.variant_name,
            "description": self.description,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "style_reference": self.style_reference,
            "word_count": _word_count(self.prompt),
        }


@dataclass
class BookMotif:
    """Visual motif pack for one title."""

    iconic_scene: str
    character_portrait: str
    setting_landscape: str
    dramatic_moment: str
    symbolic_theme: str
    style_specific_prefix: str = "woodcut allegorical tableau"


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _word_count(text: str) -> int:
    return len(text.split())


def _limit_words(text: str, max_words: int = 24) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    trimmed = words[:max_words]
    while trimmed and trimmed[-1].lower().strip(",.;:") in {
        "and",
        "or",
        "with",
        "of",
        "the",
        "a",
        "an",
        "to",
        "toward",
        "towards",
    }:
        trimmed = trimmed[:-1]
    return " ".join(trimmed)


def _strip_forbidden(text: str, title: str, author: str) -> str:
    # Prevent direct mention of full title/author strings in prompts.
    for forbidden in (title.strip(), author.strip()):
        if not forbidden or len(forbidden) < 4:
            continue
        pattern = re.compile(rf"\b{re.escape(forbidden)}\b", flags=re.IGNORECASE)
        text = pattern.sub("the story", text)
    return text


def _ensure_negative_prompt_terms(negative_prompt: str) -> str:
    tokens = [token.strip() for token in str(negative_prompt or "").split(",") if token.strip()]
    seen = {token.lower() for token in tokens}
    for term in REQUIRED_NEGATIVE_BORDER_TERMS:
        key = term.lower()
        if key in seen:
            continue
        tokens.append(term)
        seen.add(key)
    return ", ".join(tokens)


def _remove_conflicting_directions(prompt: str) -> str:
    text = str(prompt or "")
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    for pattern in _REMOVAL_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*,\s*,+", ", ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+,", ",", text)
    return text.strip(" ,")


def _prepend_missing_runtime_constraints(prompt: str) -> str:
    low = str(prompt or "").lower()
    missing: list[str] = []
    if "no border" not in low:
        missing.append("no border")
    if "no frame" not in low:
        missing.append("no frame")
    if "no text" not in low:
        missing.append("no text, no letters, no words, no typography")
    if "full rectangular canvas" not in low:
        missing.append("full rectangular canvas")
    if "no filigree" not in low:
        missing.append("no filigree")
    if "no scrollwork" not in low:
        missing.append("no scrollwork")
    if not missing:
        return str(prompt or "").strip(" ,")
    return f"{', '.join(missing)}, {prompt}".strip(" ,")


def _ensure_prompt_constraints(prompt: str) -> str:
    prompt = _remove_conflicting_directions(prompt)
    prompt = re.sub(r"\s+", " ", prompt).strip().rstrip(",")
    low = prompt.lower()
    required_prefix: list[str] = []
    if REQUIRED_PHRASE_COMPOSITION not in low:
        required_prefix.append(REQUIRED_PHRASE_COMPOSITION)
    if REQUIRED_PHRASE_TEXT not in low:
        required_prefix.append(REQUIRED_PHRASE_TEXT)
    if "no border" not in low or "no frame" not in low:
        required_prefix.append(REQUIRED_PHRASE_NO_FRAME_RUNTIME)
    if "full rectangular canvas" not in low:
        required_prefix.append(REQUIRED_PHRASE_CANVAS_RUNTIME)
    if "no filigree" not in low or "no scrollwork" not in low:
        required_prefix.append(REQUIRED_PHRASE_NO_ORNAMENT_RUNTIME)
    if REQUIRED_PHRASE_VIVID not in low:
        required_prefix.append(REQUIRED_PHRASE_VIVID)
    if REQUIRED_PHRASE_NO_EMPTY not in low:
        required_prefix.append(REQUIRED_PHRASE_NO_EMPTY)
    if required_prefix:
        prompt = f"{', '.join(required_prefix)}, {prompt}".strip(" ,")

    while _word_count(prompt) < 44:
        prompt += ", warm cinematic atmosphere, bold color contrast, intricate period detail"

    if _word_count(prompt) > 92:
        prompt = " ".join(prompt.split()[:92]).rstrip(",")

    # Cleanup artifacts introduced when forbidden tokens are stripped from "no ..." directives.
    prompt = re.sub(r"\bno\s*,\s*no\b", "no", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bno,\s*(?=no\b)", "", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r"\bno,\s*(?=[\.,;:!?]|$)", "", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r",\s*no\s*,", ", ", prompt, flags=re.IGNORECASE)
    prompt = re.sub(r",\s*,+", ", ", prompt)
    prompt = re.sub(r"\s+,", ",", prompt)
    prompt = re.sub(r"\s+", " ", prompt)
    prompt = _prepend_missing_runtime_constraints(prompt)
    if _word_count(prompt) > 92:
        prompt = " ".join(prompt.split()[:92]).rstrip(",")
    return prompt.strip(" ,")


def enforce_prompt_constraints(prompt: str) -> str:
    """Public wrapper used by runtime generation paths."""
    return _ensure_prompt_constraints(prompt)


def diversify_prompt(base_prompt: str, variant_index: int) -> str:
    """Inject style variation directives so variants are meaningfully distinct."""
    text = re.sub(r"\s+", " ", str(base_prompt or "")).strip()
    if not text:
        return text
    token = max(1, int(variant_index))
    style_rows = select_diverse_styles(token, seed_token=text[:180])
    if not style_rows:
        return text
    style = style_rows[token - 1]
    modifier = str(style.get("modifier", "")).strip()
    label = str(style.get("label", "")).strip()
    if not modifier:
        return _ensure_prompt_constraints(text)
    sanitized_modifier = _remove_conflicting_directions(modifier)
    sanitized_modifier = re.sub(r"\s+", " ", sanitized_modifier).strip(" ,")
    if not sanitized_modifier:
        return _ensure_prompt_constraints(text)
    diversified = f"{text} Style variation {token} ({label}): {sanitized_modifier}".strip()
    return _ensure_prompt_constraints(diversified)


def _motif_for_book(book: dict[str, Any]) -> BookMotif:
    title = _normalize(book.get("title", ""))
    author = _normalize(book.get("author", ""))
    title_author = f"{title} {author}"

    if "moby dick" in title_author or "whale" in title_author:
        core = "Captain Ahab, white whale, stormy sea, splintering whaling ship, violent spray"
        return BookMotif(
            iconic_scene=core,
            character_portrait="Captain Ahab with ivory leg on a rain-lashed deck, white whale looming across stormy sea",
            setting_landscape="the Pequod crossing black sea swells beneath thunderheads, white whale wake trailing beside Captain Ahab's hunt",
            dramatic_moment="Captain Ahab hurling a final harpoon as the white whale erupts through stormy sea and shattered masts",
            symbolic_theme="obsession consuming Captain Ahab beneath a colossal white whale shadow over a furious stormy sea",
            style_specific_prefix="storm-lit symbolic woodcut",
        )
    if "alice" in title_author and "wonderland" in title_author:
        core = "rabbit hole descent, mad tea party table, Queen of Hearts court, surreal garden labyrinth"
        return BookMotif(
            iconic_scene=core,
            character_portrait="curious young girl in blue dress navigating rabbit hole tunnels toward a mad tea party and Queen of Hearts banners",
            setting_landscape="dreamlike chessboard garden where rabbit hole paths lead to a mad tea party beneath Queen of Hearts roses",
            dramatic_moment="chaotic card soldiers charging from the Queen of Hearts court as a rabbit hole portal tears open beside the tea party",
            symbolic_theme="curiosity confronting absurd authority through rabbit hole spirals, shattered tea party clocks, and Queen of Hearts emblems",
            style_specific_prefix="surreal ink-wash allegorical tableau",
        )
    if "dracula" in title_author:
        core = "vampire stalking moonlit battlements of a Transylvanian castle above misted forest"
        return BookMotif(
            iconic_scene=f"{core}, torchlit crypts, red moon",
            character_portrait="aristocratic vampire with pale gaze on a Transylvanian castle balcony, wolves and fog below",
            setting_landscape="looming Transylvanian castle perched over ravines, chapel ruins, and swirling bats under winter moonlight",
            dramatic_moment="vampire advancing through candlelit crypt corridors as dawn strikes a Transylvanian castle stained-glass tower",
            symbolic_theme="predatory immortality symbolized by a vampire silhouette eclipsing a Transylvanian castle over blood-red mist",
            style_specific_prefix="gothic chiaroscuro woodcut",
        )
    if "pride and prejudice" in title_author:
        core = "Regency era courtship in an English countryside estate ballroom with candlelight and social tension"
        return BookMotif(
            iconic_scene=core,
            character_portrait="a poised Regency-era gentlewoman and a reserved gentleman framed by an English countryside manor ballroom",
            setting_landscape="rolling English countryside, grand manor facade, and illuminated Regency-era ballroom windows at dusk",
            dramatic_moment="heated proposal exchange on a rain-dark terrace above an English countryside ballroom during the Regency era",
            symbolic_theme="class expectation versus desire shown through mirrored Regency-era dancers in an English countryside ballroom",
            style_specific_prefix="Regency-era watercolor engraving fusion",
        )
    if "frankenstein" in title_author or "modern prometheus" in title_author:
        core = "the creature awakening in a candlelit laboratory as lightning forks through high windows"
        return BookMotif(
            iconic_scene=core,
            character_portrait="the creature, stitched and sorrowful, lit by laboratory coils and violent lightning shadows",
            setting_landscape="alpine laboratory tower above storm clouds, cracked instruments, and lightning illuminating frozen peaks",
            dramatic_moment="the creature confronting its creator amid shattered laboratory glass while lightning ignites the night sky",
            symbolic_theme="human ambition fractured by conscience, represented by the creature before a laboratory halo of lightning",
            style_specific_prefix="expressionist woodcut etching",
        )
    if "christmas carol" in title_author:
        return BookMotif(
            iconic_scene="a miser guided through snowy Victorian streets by a luminous spirit above clock towers",
            character_portrait="an elderly businessman in frosted nightcoat, haunted by ghostly light in a Victorian doorway",
            setting_landscape="snowy Victorian London lanes, gas lamps, church spires, and warm windows in winter fog",
            dramatic_moment="spirit-led revelation over a gravestone in swirling snow as dawn breaks over Victorian rooftops",
            symbolic_theme="redemption symbolized by an icy heart thawing into candlelit generosity over winter streets",
            style_specific_prefix="festive etching with watercolor wash",
        )
    if "crime and punishment" in title_author:
        return BookMotif(
            iconic_scene="a guilt-ridden student wandering a cramped Petersburg alley after a violent moral transgression",
            character_portrait="gaunt young intellectual under a streetlamp, restless eyes, fevered expression, threadbare coat",
            setting_landscape="narrow Petersburg courtyards, wet cobblestones, oppressive tenement walls, and pale dawn haze",
            dramatic_moment="confession in a crowded police office as rain-streaked windows trap the city in gray light",
            symbolic_theme="conscience as a split shadow stalking a lone figure through labyrinthine streets and church domes",
            style_specific_prefix="psychological charcoal-etch hybrid",
        )
    if "romeo and juliet" in title_author:
        return BookMotif(
            iconic_scene="moonlit balcony meeting between rival houses in Renaissance Verona with tense guards below",
            character_portrait="young lovers in Renaissance attire, longing expressions, candlelight and danger in the courtyard",
            setting_landscape="Verona rooftops, cypress silhouettes, stone arches, and lantern-lit piazza at twilight",
            dramatic_moment="desperate final embrace in a candlelit crypt amid roses and cold marble",
            symbolic_theme="love against feud shown as intertwined roses crossing two drawn blades",
            style_specific_prefix="Renaissance tempera-style allegory",
        )
    if "journey to the centre of the earth" in title_author:
        return BookMotif(
            iconic_scene="expedition crossing a subterranean sea beneath colossal crystal caverns and volcanic arches",
            character_portrait="determined explorer with lantern and rope map, soot-streaked face, awe before underground giants",
            setting_landscape="vast caverns of glowing minerals, ancient forests, and distant prehistoric silhouettes",
            dramatic_moment="raft hurled toward a volcanic shaft as molten light and steam engulf the cavern",
            symbolic_theme="human curiosity represented by a tiny lantern descending spiral strata toward primal fire",
            style_specific_prefix="adventure lithograph tableau",
        )
    if "twenty thousand leagues" in title_author:
        return BookMotif(
            iconic_scene="a sleek submarine gliding past giant squid and ruined statues in midnight blue depths",
            character_portrait="stoic sea captain in ornate coat within brass-lit control room, ocean pressure beyond glass",
            setting_landscape="abyssal seascape with coral cathedrals, volcanic vents, and bioluminescent currents",
            dramatic_moment="submarine struck by a giant squid as lightning flashes across storm waves above",
            symbolic_theme="isolation and wonder symbolized by a lone vessel encircled by abyssal light",
            style_specific_prefix="nautical copperplate allegory",
        )
    if "prince and the pauper" in title_author:
        return BookMotif(
            iconic_scene="two identical boys exchanging garments in a crowded Tudor marketplace",
            character_portrait="noble youth and street child facing each other, mirrored expressions, contrasting fabrics",
            setting_landscape="Tudor London lanes, palace towers, and bustling market stalls under gray sky",
            dramatic_moment="public coronation turmoil as hidden identity is revealed before astonished court",
            symbolic_theme="class inversion symbolized by a split crown above worn shoes and velvet slippers",
            style_specific_prefix="Tudor woodcut narrative plate",
        )
    if "invisible man" in title_author:
        return BookMotif(
            iconic_scene="bandaged figure in a provincial inn, objects levitating as townsfolk recoil",
            character_portrait="faceless man wrapped in cloth and dark goggles, tense posture, winter coat",
            setting_landscape="windswept village street with blown papers and open doors revealing disturbed interiors",
            dramatic_moment="chaotic pursuit through snow as footprints race without a visible body",
            symbolic_theme="unchecked intellect symbolized by empty clothing collapsing beneath cold light",
            style_specific_prefix="grotesque monochrome etching",
        )
    if "time machine" in title_author:
        return BookMotif(
            iconic_scene="inventor operating brass chronometer in a Victorian laboratory as time blurs around him",
            character_portrait="Victorian scientist with soot-streaked waistcoat, focused gaze, mechanical controls in hand",
            setting_landscape="ruined future city beneath red twilight, broken statues, and overgrown marble steps",
            dramatic_moment="descent into subterranean tunnels where pale creatures surround a flickering machine",
            symbolic_theme="progress and decay represented by a clock face split between roses and rusted gears",
            style_specific_prefix="retro-futurist etching plate",
        )
    if "jungle book" in title_author:
        return BookMotif(
            iconic_scene="wolf-raised child moving through moonlit jungle beside panther and bear companions",
            character_portrait="young forest boy poised with staff, alert gaze, tiger-striped shadows behind",
            setting_landscape="dense tropical canopy, river bend, ruined temples, and monsoon clouds",
            dramatic_moment="fire confrontation with a tiger at the edge of a storm-lit clearing",
            symbolic_theme="belonging and instinct shown by human footprints merging with animal tracks",
            style_specific_prefix="lush watercolor-etch fusion",
        )
    if "robinson crusoe" in title_author:
        return BookMotif(
            iconic_scene="shipwreck survivor building shelter beside palms and broken timbers on a remote shore",
            character_portrait="bearded castaway with handmade tools, weathered clothes, vigilant horizon gaze",
            setting_landscape="lonely island cove, steep cliffs, driftwood, and a distant storm at sea",
            dramatic_moment="first encounter with an ally marked by footprints in wet sand at dawn",
            symbolic_theme="self-reliance represented by a solitary fire against endless ocean",
            style_specific_prefix="maritime wood engraving",
        )
    if "hamlet" in title_author:
        return BookMotif(
            iconic_scene="brooding prince in a torchlit hall holding a skull under northern night",
            character_portrait="melancholic royal in black attire, sharp profile, spectral light across his face",
            setting_landscape="windswept Danish battlements, icy sea horizon, and banners under moonlight",
            dramatic_moment="duel in a crowded court as poisoned steel flashes beneath chandeliers",
            symbolic_theme="indecision and fate represented by a cracked crown beside an hourglass",
            style_specific_prefix="tragic chiaroscuro engraving",
        )
    if "oedipus" in title_author:
        return BookMotif(
            iconic_scene="troubled king before temple steps as plague-stricken citizens plead for relief",
            character_portrait="tormented ruler in Greek robes, laurel crown askew, eyes shadowed by prophecy",
            setting_landscape="ancient Theban gates, marble columns, and dry hills under harsh sun",
            dramatic_moment="horrific revelation in palace court with torn garments and fallen scepter",
            symbolic_theme="fate represented by a blindfolded figure beneath a broken royal seal",
            style_specific_prefix="classical fresco-inspired woodcut",
        )
    if "dorian gray" in title_author:
        return BookMotif(
            iconic_scene="young aesthete facing an unsettling portrait in candlelit studio",
            character_portrait="refined gentleman in velvet coat, beautiful surface hiding moral corruption",
            setting_landscape="opulent London salon with mirrors, drapery, and covered canvases",
            dramatic_moment="portrait unveiled during thunder as hidden decay erupts into view",
            symbolic_theme="beauty versus guilt represented by a gilded frame around a rotting reflection",
            style_specific_prefix="decadent etching with watercolor stain",
        )
    if "sherlock" in title_author or "sign of the four" in title_author:
        return BookMotif(
            iconic_scene="detective examining cryptic clues in a gaslit Victorian sitting room",
            character_portrait="razor-focused investigator in long coat and gloves, violin nearby, keen expression",
            setting_landscape="foggy London river docks, hansom cabs, and lamplit alleys",
            dramatic_moment="river pursuit at night as criminals flee through smoke and engine spray",
            symbolic_theme="reason cutting through chaos represented by a magnifying lens over tangled footprints",
            style_specific_prefix="detective copperplate engraving",
        )
    if "les miserables" in title_author or "les mise rables" in title_author:
        return BookMotif(
            iconic_scene="revolutionaries manning a Paris barricade as smoke and flags fill dawn streets",
            character_portrait="hunted ex-convict carrying compassion in his eyes, worn coat, protective stance",
            setting_landscape="19th-century Paris lanes, cathedral silhouettes, and barricades of cobblestone",
            dramatic_moment="final stand amid musket fire while civilians flee under storm light",
            symbolic_theme="mercy versus law embodied by a candle glowing beside broken chains",
            style_specific_prefix="epic historical oil-etch blend",
        )
    if "call of the wild" in title_author:
        return BookMotif(
            iconic_scene="sled dog leading a team across frozen wilderness under aurora and blowing snow",
            character_portrait="powerful canine in harness, fierce eyes, frost-coated fur, primal resolve",
            setting_landscape="Yukon river valley, pine forests, mountains, and pale winter sun",
            dramatic_moment="pack challenge at twilight with snow spraying from clashing bodies",
            symbolic_theme="civilization fading into instinct symbolized by pawprints leaving a campfire",
            style_specific_prefix="northern woodcut composition",
        )
    if "we " in f" {title} ":
        return BookMotif(
            iconic_scene="uniform citizens marching through a transparent city beneath surveillance spires",
            character_portrait="state engineer in numbered uniform, conflicted gaze, rigid geometric backdrop",
            setting_landscape="glass avenues, regimented housing blocks, and metallic skies",
            dramatic_moment="forbidden encounter in a wild zone beyond the city wall",
            symbolic_theme="individual desire cracking a perfect geometric grid",
            style_specific_prefix="constructivist allegorical engraving",
        )
    if "around the world in eighty days" in title_author:
        return BookMotif(
            iconic_scene="disciplined traveler boarding a steam train while clocks and maps surround him",
            character_portrait="Victorian gentleman with pocket watch, composed face, weathered luggage",
            setting_landscape="montage of ports, deserts, rail bridges, and ocean steamers at golden hour",
            dramatic_moment="last-minute sprint toward a club doorway as sunset bells ring",
            symbolic_theme="precision and adventure shown by a globe encircled with train smoke",
            style_specific_prefix="travel poster-style engraving",
        )
    # ── A Room with a View ─────────────────────────────────────────────────
    if "room with a view" in title_author:
        return BookMotif(
            iconic_scene="Edwardian English tourists at a pensione window overlooking the Arno river with Florentine domes and cypress hills",
            character_portrait="young Englishwoman in white muslin leaning from an open window above terracotta rooftops and the river Arno",
            setting_landscape="sun-drenched Florentine hillside terrace, olive groves, ochre villas, and a shimmering Arno valley below",
            dramatic_moment="spontaneous kiss in a golden Italian wheat field as Edwardian propriety crumbles under Tuscan sun",
            symbolic_theme="liberation from repression shown by an open shuttered window framing Florence's sky against a closed English parlour",
            style_specific_prefix="Edwardian watercolour travel illustration",
        )

    # ── Gulliver's Travels ─────────────────────────────────────────────────
    if "gulliver" in title_author:
        return BookMotif(
            iconic_scene="giant human pinned to a beach by hundreds of tiny ropes while Lilliputian soldiers swarm his body",
            character_portrait="bemused giant ship's surgeon flat on a sunlit strand, bound by thread-fine ropes, tiny armies at his cuffs",
            setting_landscape="miniature Lilliputian city of delicate spires and streets stretching beneath a stranded giant's coat",
            dramatic_moment="voyage to Laputa as the floating island's shadow darkens a fleet below and scholars peer from cloud-level windows",
            symbolic_theme="human arrogance satirised by a colossus helpless in a nation of thumb-sized rulers wielding needle swords",
            style_specific_prefix="satirical Georgian copperplate engraving",
        )

    # ── Emma ───────────────────────────────────────────────────────────────
    if " emma " in f" {title} " or title.startswith("emma"):
        return BookMotif(
            iconic_scene="self-assured young matchmaker surveying Highbury village from a sunlit drawing room window with tea and embroidery",
            character_portrait="confident Regency gentlewoman at a writing desk, quill in hand, scheming smile, afternoon light on silk dress",
            setting_landscape="prosperous English village green, Hartfield gardens, stone church tower, and neat hedgerows in warm summer",
            dramatic_moment="sudden mortifying picnic on Box Hill as careless wit wounds a gentle companion before all of society",
            symbolic_theme="self-deception unravelled by mismatched silhouettes on a village green under clearing clouds",
            style_specific_prefix="Regency pastoral watercolour etching",
        )

    # ── A Modest Proposal ──────────────────────────────────────────────────
    if "modest proposal" in title_author:
        return BookMotif(
            iconic_scene="Georgian pamphlet illustration of gaunt Irish children and well-fed English landlords at a banquet table",
            character_portrait="sardonic pamphleteer in Georgian wig gesturing toward a ledger of infant statistics with bitter calm",
            setting_landscape="bleak Georgian Dublin streets, starving families by doorways, cattle market pennants above cobblestones",
            dramatic_moment="absurd proposal read aloud to powdered aristocrats who nod approvingly over a silver dining service",
            symbolic_theme="institutional cruelty masked as philanthropy shown by a roast silver platter bearing an infant's bonnet",
            style_specific_prefix="dark satirical Georgian broadside woodcut",
        )

    # ── The Mysterious Stranger ────────────────────────────────────────────
    if "mysterious stranger" in title_author:
        return BookMotif(
            iconic_scene="a beautiful young stranger with supernatural calm conjures miniature human figures in a medieval Austrian village square",
            character_portrait="elegant pale youth with otherworldly eyes shaping tiny clay people with indifferent grace in firelight",
            setting_landscape="medieval Austrian hilltop village, cobbled lanes, a church steeple, and perpetual twilight over forested valleys",
            dramatic_moment="stranger sweeping away his miniature village with one hand as boys watch in existential horror",
            symbolic_theme="divine indifference illustrated by a god-figure crushing a perfect tiny world between thumb and finger",
            style_specific_prefix="dark Romantic expressionist woodcut",
        )

    # ── Right Ho, Jeeves ───────────────────────────────────────────────────
    if "right ho jeeves" in title_author or ("jeeves" in title_author and "right ho" in title_author):
        return BookMotif(
            iconic_scene="bumbling English aristocrat sprawled in a deck chair at Brinkley Court while an immaculate valet surveys the chaos",
            character_portrait="genial young gentleman in white flannel suit, straw boater askew, look of cheerful bewilderment",
            setting_landscape="lush Worcestershire country house lawns, rose borders, croquet hoops, and a long gravel drive at summer noon",
            dramatic_moment="disastrous fancy-dress dinner erupting into social catastrophe as Jeeves stands serenely at the sideboard",
            symbolic_theme="class comedy shown by a butler's perfectly pressed gloves beside a crumpled master's panama hat",
            style_specific_prefix="Edwardian comic illustration watercolour",
        )

    # ── The Enchanted April ────────────────────────────────────────────────
    if "enchanted april" in title_author:
        return BookMotif(
            iconic_scene="four English women in a medieval Italian castle garden awash with wisteria, bougainvillea, and spring sea light",
            character_portrait="reserved English gentlewoman transformed, arms open on a Mediterranean castle terrace, sun on her upturned face",
            setting_landscape="terraced San Salvatore castle above a shimmering Ligurian bay, stone walls dripping with jasmine and wisteria",
            dramatic_moment="first morning when each woman steps into the Italian garden and feels the enchantment dissolve English reserve",
            symbolic_theme="emotional rebirth shown by an English grey coat shed at the gate of a blossom-drenched Mediterranean garden",
            style_specific_prefix="Edwardian Mediterranean watercolour idyll",
        )

    # ── Cranford ───────────────────────────────────────────────────────────
    if "cranford" in title_author:
        return BookMotif(
            iconic_scene="genteel elderly ladies taking tea in a modest parlour, fine china and faded lace, Victorian social ritual",
            character_portrait="dignified older Englishwoman in Victorian cap and shawl, erect posture, gentle authority in a small drawing room",
            setting_landscape="quiet English market town, neat brick cottages, a high street with a draper's bow window and gas lamp",
            dramatic_moment="unexpected railway arrival disrupting Cranford's tranquil order as modern England presses at the hedgerow",
            symbolic_theme="graceful decline shown by a chipped teacup beside a sealed letter on a fading floral tablecloth",
            style_specific_prefix="Victorian domestic genre engraving",
        )

    # ── Expedition of Humphry Clinker ──────────────────────────────────────
    if "humphry clinker" in title_author:
        return BookMotif(
            iconic_scene="a motley English family party in a jolting coach careening through 18th-century Scottish highland roads",
            character_portrait="irascible Welsh squire in travelling clothes, apoplectic expression, bouncing in a mud-spattered post-chaise",
            setting_landscape="rolling 18th-century British countryside, Roman baths, Edinburgh closes, and Highland mountain passes",
            dramatic_moment="chaotic ford crossing where the coach sinks and passengers scramble to muddy riverbanks in full comedy",
            symbolic_theme="national character exposed by comic journey shown as a patchwork travelling bag spilling across a map of Britain",
            style_specific_prefix="Georgian picaresque caricature engraving",
        )

    # ── History of Tom Jones ───────────────────────────────────────────────
    if "tom jones" in title_author:
        return BookMotif(
            iconic_scene="handsome foundling in Georgian hunting attire striding through English countryside toward a manor house at dawn",
            character_portrait="open-faced young man in 18th-century coat, honest expression, walking stick, fields and distant hall behind",
            setting_landscape="rolling Georgian England, Squire Western's park, inn courtyards, London coaching roads, and open meadows",
            dramatic_moment="confrontation in a London drawing room as true identity is revealed before assembled Georgian society",
            symbolic_theme="good nature triumphing over class shown by a foundling's token beside a broken aristocratic seal",
            style_specific_prefix="Georgian narrative engraving pastoral",
        )

    # ── The Pickwick Papers ────────────────────────────────────────────────
    if "pickwick" in title_author:
        return BookMotif(
            iconic_scene="portly bespectacled gentleman and three loyal companions boarding a coach outside a Georgian inn at dawn",
            character_portrait="round benevolent gentleman in tights and gaiters, beaming smile, tasselled hat, notebooks under arm",
            setting_landscape="coaching-inn yard, Dingley Dell snowscape, Fleet Prison courtyard, and bustling Victorian London streets",
            dramatic_moment="Mr Pickwick's chaotic ice-skating expedition ending in a snowdrift to universal hilarity",
            symbolic_theme="innocent optimism shown by a magnifying glass and a notebook over a tangled map of English roads",
            style_specific_prefix="Victorian comic engraving Dickensian",
        )

    # ── The Wind in the Willows ────────────────────────────────────────────
    if "wind in the willows" in title_author:
        return BookMotif(
            iconic_scene="Mole, Rat, and Badger picnicking on the river bank while Toad Hall rises through weeping willows behind",
            character_portrait="cheerful Mole in his velvet waistcoat beside Rat with a rowing hamper on the sunlit Thames bank",
            setting_landscape="the gentle River Bank with osiers, water-meadows, and Toad Hall's chimneys visible through summer willow curtains",
            dramatic_moment="Mr Toad in racing goggles at the wheel of a motor car careening down a country lane in ecstatic speed",
            symbolic_theme="home and friendship shown by four animal silhouettes at a lantern-lit burrow door in a winter snowfield",
            style_specific_prefix="Edwardian pastoral watercolour illustration",
        )

    # ── Middlemarch ────────────────────────────────────────────────────────
    if "middlemarch" in title_author:
        return BookMotif(
            iconic_scene="idealistic young gentlewoman in black riding dress surveys a provincial English town from a hilltop at sunrise",
            character_portrait="earnest Victorian woman with thoughtful eyes, dark dress, an open book, and reform documents on her desk",
            setting_landscape="Midlands market town, brick hospital under construction, Casaubon's library, and fog-softened fields",
            dramatic_moment="Dorothea's torchlit renunciation of fortune in a grey dawn as rain runs down tall rectory windows",
            symbolic_theme="thwarted idealism shown by an extinguished torch before an unfinished reform map and a locked casket",
            style_specific_prefix="Victorian realist oil-engraving hybrid",
        )

    # ── The Lady with the Dog ──────────────────────────────────────────────
    if "lady with the dog" in title_author or "lady with a dog" in title_author:
        return BookMotif(
            iconic_scene="solitary woman with a white Pomeranian on the Yalta promenade as grey sea meets overcast sky",
            character_portrait="pale melancholy woman in a light summer dress and hat, small dog on leash, eyes fixed on the Black Sea",
            setting_landscape="Yalta promenade, acacia trees, white hotels above a calm sea, afternoon light fading on resort parasols",
            dramatic_moment="first silent meeting on the embankment as sea mist rolls in and a watermelon slice sits untouched",
            symbolic_theme="illicit longing shown by two separate shadows converging on a Yalta seafront in winter fog",
            style_specific_prefix="melancholy Russian Impressionist plein-air",
        )

    # ── The Lady of the Lake ───────────────────────────────────────────────
    if "lady of the lake" in title_author:
        return BookMotif(
            iconic_scene="a warrior's horn call echoing across a Highland loch as a woman glides toward shore in a birch-bark skiff",
            character_portrait="Ellen Douglas in white robe at the prow of a small boat, misty loch and craggy island peak behind her",
            setting_landscape="Ben Venue's rocky reflection in a dawn loch, heather shores, pine forest, and morning mist rising",
            dramatic_moment="Highland chieftain and hidden king in disguise face off on a misty island as Ellen watches from a crag",
            symbolic_theme="highland loyalty shown by a claymore laid at the feet of a woman on an island in morning mist",
            style_specific_prefix="Romantic Scottish landscape engraving",
        )

    # ── The Satyricon ──────────────────────────────────────────────────────
    if "satyricon" in title_author:
        return BookMotif(
            iconic_scene="Trimalchio's banquet hall erupting with roast peacocks, acrobats, wine fountains, and guests in gold-trimmed togas",
            character_portrait="wealthy freedman in extravagant purple robes presiding over his own mock-funeral feast among slavering guests",
            setting_landscape="ancient Roman triclinium dripping with garlands, exotic birds in gilded cages, mosaic floors, and amphorae",
            dramatic_moment="skeleton automaton carried in at the feast as drunk guests recoil from mortality hidden beneath the revelry",
            symbolic_theme="Roman excess embodied by a gold skeleton toasting with a brimming goblet over an overturned world",
            style_specific_prefix="decadent Roman mosaic fresco style",
        )

    # ── Little Women ───────────────────────────────────────────────────────
    if "little women" in title_author:
        return BookMotif(
            iconic_scene="four March sisters gathered around a hearth in a Civil War-era New England parlour, sewing, reading, and laughing",
            character_portrait="spirited tomboy in ink-stained fingers and chestnut hair at a writing desk, manuscript pages around her",
            setting_landscape="warm New England cottage in winter snow, evergreen wreath on the door, amber lamplight in frosted windows",
            dramatic_moment="Beth's piano playing filling the parlour as the family waits for news from the front in hushed candlelight",
            symbolic_theme="sisterhood shown by four pairs of hands clasped over a worn family Bible beside a Christmas stocking",
            style_specific_prefix="Civil War-era domestic narrative engraving",
        )

    # ── The Eyes Have It ───────────────────────────────────────────────────
    if "eyes have it" in title_author:
        return BookMotif(
            iconic_scene="paranoid commuter in a 1950s train carriage scrutinising fellow passengers' eyes for alien telltale signs",
            character_portrait="tense suburban man gripping a newspaper, sweating, watching eyes in a crowded mid-century rail carriage",
            setting_landscape="bland 1950s American suburbs, identical houses, commuter trains, and eyes that never look quite right",
            dramatic_moment="protagonist's dawning realisation that every passenger in the car has detachable eyes on short stalks",
            symbolic_theme="Cold War paranoia shown by a field of mismatched glass eyes staring from a newspaper's grey columns",
            style_specific_prefix="1950s pulp sci-fi ink halftone illustration",
        )

    # ── Laughter: An Essay on the Meaning of the Comic ────────────────────
    if "laughter" in title_author and "bergson" in title_author:
        return BookMotif(
            iconic_scene="a theatre stage where mechanical marionettes laugh and weep identically, actors frozen mid-gesture like wound-up toys",
            character_portrait="philosopher in a frock coat studying two masks — comedy and tragedy — reflected in a cracked mirror",
            setting_landscape="a commedia dell'arte stage with raked boards, footlights, and an audience of identical blank-faced spectators",
            dramatic_moment="jack-in-the-box moment as a dignified gentleman slips on ice and an audience bursts into simultaneous laughter",
            symbolic_theme="automatism in life shown by a clockwork figure in a frock coat miming a human's most solemn gestures",
            style_specific_prefix="Belle Époque philosophical allegorical engraving",
        )

    # ── Eve's Diary ────────────────────────────────────────────────────────
    if "eve s diary" in title_author or "eves diary" in title_author:
        return BookMotif(
            iconic_scene="first woman in paradise writing in a journal amid cascading flowers, curious animals gathering to look",
            character_portrait="wide-eyed Eve in Eden, garland of flowers in her hair, kneeling to examine a butterfly on her finger",
            setting_landscape="lush Garden of Eden with waterfalls, tropical blossoms, peacocks, and an amber sunset over paradise hills",
            dramatic_moment="Eve's first encounter with fire, prodding glowing embers with a branch as Adam watches from a distance",
            symbolic_theme="wonder and naming shown by Eve holding an apple up to sunlight as every creature of Eden watches",
            style_specific_prefix="Edenic Pre-Raphaelite botanical illustration",
        )

    # ── The Sky Trap ───────────────────────────────────────────────────────
    if "sky trap" in title_author:
        return BookMotif(
            iconic_scene="a biplane circling helplessly against an invisible ceiling barrier as the sky glows with a strange shimmering membrane",
            character_portrait="goggled aviator in open cockpit, hammering against invisible resistance above cloud tops, face stricken",
            setting_landscape="bright blue sky suddenly terminated by a shimmering translucent ceiling above towering cumulus clouds",
            dramatic_moment="pilot pushing throttle to full as the plane strains against the invisible barrier and instruments spin wildly",
            symbolic_theme="human freedom caged shown by a bird and biplane both pressing against an unseen crystal dome in clear sky",
            style_specific_prefix="1930s pulp adventure aviation illustration",
        )

    # ── The Blue Castle ────────────────────────────────────────────────────
    if "blue castle" in title_author:
        return BookMotif(
            iconic_scene="a repressed woman finally free, laughing in a canoe on a Muskoka wilderness lake under a wide Canadian sky",
            character_portrait="liberated young woman, red cheeks, windswept hair, paddling a birchbark canoe among pine-lined islands",
            setting_landscape="Ontario Muskoka lake at sunset, granite outcroppings, dark pine reflections, and a log cabin on the shore",
            dramatic_moment="Valancy walking out of her aunt's Victorian parlour for the last time, door swinging behind her in spring air",
            symbolic_theme="liberation from convention shown by an open birdcage on a Victorian windowsill above a wide wilderness lake",
            style_specific_prefix="Canadian wilderness watercolour lyric",
        )

    # ── Adventures of Ferdinand Count Fathom ──────────────────────────────
    if "ferdinand count fathom" in title_author or "count fathom" in title_author:
        return BookMotif(
            iconic_scene="charming villain in powdered wig and silk coat bowing to a trusting noblewoman in a candlelit European salon",
            character_portrait="handsome rakish schemer in 18th-century court dress, practised smile hiding cold calculation",
            setting_landscape="gilded European drawing rooms, Vienna streets, London gaming dens, and moonlit forest highway ambush",
            dramatic_moment="Count Fathom cornered at sword point in a midnight forest inn as his web of deceptions collapses",
            symbolic_theme="villainy unmasked shown by a lace handkerchief concealing a dagger beside a forged letter of nobility",
            style_specific_prefix="Georgian picaresque villain engraving",
        )

    # ── Three Men in a Boat ────────────────────────────────────────────────
    if "three men in a boat" in title_author:
        return BookMotif(
            iconic_scene="three hapless friends and a fox terrier crammed in a rowboat on the Thames, one struggling with a tin opener",
            character_portrait="three moustachioed late-Victorian men in straw boaters and blazers looking baffled at a tangled camping tarpaulin",
            setting_landscape="tranquil upper Thames, willow-fringed banks, lock gates, riverside pubs, and a misty morning on the water",
            dramatic_moment="tent collapsing in the rain on a Thames island as the dog sits smug and dry in the upturned boat",
            symbolic_theme="comic English stoicism shown by three sodden figures toasting disaster with tin mugs in a downpour",
            style_specific_prefix="Victorian comic illustration pen-and-ink",
        )

    # ── A Doll's House ─────────────────────────────────────────────────────
    if "doll s house" in title_author or "dolls house" in title_author or "a doll" in title_author:
        return BookMotif(
            iconic_scene="a woman in Victorian parlour dress rising from a perfect bourgeois Christmas Eve interior toward a door",
            character_portrait="Nora Helmer in party dress, coat in hand, resolute face turned from a glittering Christmas tree",
            setting_landscape="Ibsenian Norwegian Victorian parlour, Christmas garlands, a letter box, gas lamp, snow beyond frosted panes",
            dramatic_moment="the slamming door echoing through a silent stage as the audience absorbs the finality of Nora's departure",
            symbolic_theme="liberation shown by an empty doll's house interior with a swinging front door and scattered macaroons",
            style_specific_prefix="Nordic Symbolist theatre engraving",
        )

    # ── Adventures of Roderick Random ─────────────────────────────────────
    if "roderick random" in title_author:
        return BookMotif(
            iconic_scene="young Scottish adventurer on a 18th-century man-of-war deck during a naval battle with smoke and cannon fire",
            character_portrait="raw young Scot in naval surgeon's mate coat, sharp determined eyes, sea spray on his face and coat collar",
            setting_landscape="Georgian naval warship under full sail, tropical port taverns, London coaching roads, and Scottish moorland",
            dramatic_moment="flogged on deck then cast ashore as a Spanish fleet appears on the horizon and smoke billows from cannon ports",
            symbolic_theme="fortune's wheel shown by a naval surgeon's case and a Highland dirk beside a spinning globe on a chart",
            style_specific_prefix="18th-century naval adventure engraving",
        )

    # ── Adventures of Tom Sawyer ───────────────────────────────────────────
    if "tom sawyer" in title_author:
        return BookMotif(
            iconic_scene="mischievous boy supervising friends whitewashing a long picket fence on a sunny Missouri morning",
            character_portrait="barefoot boy in patched trousers and straw hat, grin on his face, paintbrush in hand outside a fence",
            setting_landscape="Mississippi river town, white clapboard church, river bluffs, a steamboat on the brown current",
            dramatic_moment="Tom and Becky lost in McDougal's Cave as a candle gutters, Injun Joe's shadow on the cavern wall",
            symbolic_theme="boyhood freedom shown by a raft at the grassy bank of a wide river under a cloudless sky",
            style_specific_prefix="Americana Mississippi pastoral engraving",
        )

    # ── Twenty Years After ─────────────────────────────────────────────────
    if "twenty years after" in title_author:
        return BookMotif(
            iconic_scene="four ageing musketeers reunited on horseback in Fronde-era Paris, swords drawn, loyalty undiminished by years",
            character_portrait="veteran swordsman in plain grey cloak, grey at the temples, still commanding on a battle-scarred charger",
            setting_landscape="Paris barricades of the Fronde, St Germain's lanes, English scaffold at Whitehall, and French countryside",
            dramatic_moment="Athos, Porthos, Aramis, and d'Artagnan breaking through a Paris gate at a gallop under flintlock fire",
            symbolic_theme="enduring brotherhood shown by four crossed swords forming a star above an hourglass leaking silver sand",
            style_specific_prefix="Baroque swashbuckling oil painting engraving",
        )

    # ── Lady Chatterley's Lover ────────────────────────────────────────────
    if "lady chatterley" in title_author or "chatterley" in title_author:
        return BookMotif(
            iconic_scene="a woman in summer dress walking through an ancient English woodland toward a gamekeeper's stone cottage",
            character_portrait="Connie Chatterley barefoot on a mossy path, sunlight filtering through oaks, Wragby Hall smokestacks behind",
            setting_landscape="ancient Nottinghamshire forest in spring, bluebells under oak canopy, colliery smoke beyond the treeline",
            dramatic_moment="rain falling through woodland as two figures shelter together in the keeper's hut, industrial England forgotten",
            symbolic_theme="natural passion against mechanised England shown by a bluebell breaking through coal-ash beside iron gates",
            style_specific_prefix="English pastoral Impressionist oil study",
        )

    # ── She Stoops to Conquer ──────────────────────────────────────────────
    if "she stoops to conquer" in title_author:
        return BookMotif(
            iconic_scene="young gentleman mistaking a Georgian country manor for an inn, ordering servants about in comic confusion",
            character_portrait="spirited young woman in servant's apron over silk dress, suppressing laughter at a bewildered suitor",
            setting_landscape="Georgian English country house, horse paddock, a stone inn sign, and a moonlit park in 18th-century style",
            dramatic_moment="masked ball revelation in the garden as every identity is exposed under Chinese lanterns at the manor house",
            symbolic_theme="disguise and social comedy shown by a lady's fan laid beside a servant's mop on a Georgian parlour table",
            style_specific_prefix="Georgian comedy of manners engraving",
        )

    # ── Der Struwwelpeter ──────────────────────────────────────────────────
    if "struwwelpeter" in title_author or "struwwel" in title_author:
        return BookMotif(
            iconic_scene="wild-haired boy with yard-long overgrown fingernails displayed on a plinth while gentlemen point in horror",
            character_portrait="Shock-headed Peter standing on a pedestal, towering matted hair, grotesquely long curling fingernails",
            setting_landscape="German bourgeois nursery with embroidered curtains, a spinning top, and a threatening tailor lurking outside",
            dramatic_moment="the great long red-legged scissor-man snipping a thumb-sucking child's fingers off in mid-air",
            symbolic_theme="disobedience punished in lurid moralising colours of black, red, and nursery yellow",
            style_specific_prefix="German Victorian cautionary tale woodcut illustration",
        )

    # ── The History of John Bull ───────────────────────────────────────────
    if "john bull" in title_author:
        return BookMotif(
            iconic_scene="a stout plain Englishman in farmer's coat haggling in a courtroom with allegorical figures of France, Holland, and Scotland",
            character_portrait="John Bull in broad-brimmed hat, beef-red face, stocky frame, clutching a ledger against legal tricksters",
            setting_landscape="18th-century English law courts, tavern parlours, Parliament's exterior, and a Channel port in grey weather",
            dramatic_moment="John Bull tearing up a bogus treaty in front of a disguised lawyer as national allegories grin in defeat",
            symbolic_theme="bluff English common sense against continental scheming shown by a roast beef plate outweighing a stack of treaties",
            style_specific_prefix="Georgian political allegory broadside",
        )

    # ── The Reign of Greed ─────────────────────────────────────────────────
    if "reign of greed" in title_author:
        return BookMotif(
            iconic_scene="Filipino revolutionaries raising a torch in a tropical Manila square under Spanish colonial church towers at night",
            character_portrait="young Filipino idealist in barong tagalog, fierce eyes, clenched fist, a colonial rifle trained on him",
            setting_landscape="Spanish colonial Manila, Intramuros stone walls, tropical palms, Pasig river, and lantern-lit plazas",
            dramatic_moment="public execution in plaza de armas as the crowd holds its breath and a church bell tolls at dawn",
            symbolic_theme="colonial greed shown by golden chains binding tropical flowers to a stone colonial cross at sunrise",
            style_specific_prefix="late-19th-century Philippine revolutionary realism",
        )

    # ── Anthem ─────────────────────────────────────────────────────────────
    if "anthem" in title_author and "rand" in title_author:
        return BookMotif(
            iconic_scene="a lone figure in a grey collective uniform holds a glowing electric bulb aloft in a dark tunnel, forbidden light",
            character_portrait="solitary young man in numbered tunic, defiant upturned face, bare electric filament blazing in his hand",
            setting_landscape="subterranean tunnel beneath a collectivist city, crumbling rails, rubble, and a tiny stolen circle of light",
            dramatic_moment="Equality 7-2521 and Liberty 5-3000 fleeing into forbidden forest as the collectivist city's alarm bells ring",
            symbolic_theme="individual spark shown by a single lit bulb casting a long shadow against a wall of uniform grey stone",
            style_specific_prefix="dystopian constructivist allegory engraving",
        )

    # ── Là-bas ─────────────────────────────────────────────────────────────
    if "l bas" in title_author or "la bas" in title_author or "huysmans" in title_author:
        return BookMotif(
            iconic_scene="decadent Parisian writer in candlelit study researching Satanism amid grimoires, skulls, and black candles",
            character_portrait="pale obsessive scholar surrounded by occult manuscripts, black altar candles, and medieval Gilles de Rais sketches",
            setting_landscape="fin-de-siècle Paris attic, Notre Dame spires through rain-black glass, a black mass chamber in the cellar",
            dramatic_moment="secret Satanic ritual in a Paris cellar as incense smoke and inverted candles surround hooded figures",
            symbolic_theme="spiritual decadence shown by a medieval knight's gauntlet grasping a black candle over an inverted cross",
            style_specific_prefix="Symbolist Decadent occult engraving",
        )

    # ── 2 B R 0 2 B ───────────────────────────────────────────────────────
    if "2 b r 0 2 b" in title_author or "vonnegut" in title_author and "2br02b" in title_author.replace(" ", ""):
        return BookMotif(
            iconic_scene="a sterile futuristic waiting room where a man faces a choice between a newborn's life and an old man's death",
            character_portrait="haggard father in a hygienic future hospital, three birth certificates in hand, a gas chamber phone before him",
            setting_landscape="clinical white future hospital corridor, world population counter on the wall, a flower mural, and a dial phone",
            dramatic_moment="man pressing the government dial as the mural painter watches in silent horror and the counter ticks over",
            symbolic_theme="population as arithmetic shown by an hourglass balanced on birth and death certificates under fluorescent light",
            style_specific_prefix="1960s dystopian satirical illustration",
        )

    # ── The Man from Time ──────────────────────────────────────────────────
    if "man from time" in title_author:
        return BookMotif(
            iconic_scene="a stranger in futuristic attire materialising in a 1950s street, anachronistic technology sparking in his hands",
            character_portrait="temporal traveller in sleek future garments, dazed expression, holding a glowing device in a mid-century city",
            setting_landscape="1950s American city, neon signs, chrome bumpers, and a shimmering temporal rift in the sky above a diner",
            dramatic_moment="time traveller cornered by 1950s policemen as his chronometer shorts out and the time rift begins to close",
            symbolic_theme="temporal displacement shown by a wristwatch with overlapping clock faces above a fragmented calendar",
            style_specific_prefix="1950s pulp science fiction ink illustration",
        )

    # ── The Vibration Wasps ────────────────────────────────────────────────
    if "vibration wasps" in title_author:
        return BookMotif(
            iconic_scene="enormous buzzing wasp creatures with vibrating crystalline wings hovering over a terrified mid-century town",
            character_portrait="scientist in lab coat recoiling from a specimen jar as a giant wasp beats against his laboratory window",
            setting_landscape="American small town, 1940s houses under attack from monstrous insect swarm filling the buzzing summer sky",
            dramatic_moment="wasp swarm descending on a power station as electricity crackles and the creatures grow larger in the arcs",
            symbolic_theme="nature perverted by science shown by a magnified wasp anatomy diagram alive and breaking through the glass",
            style_specific_prefix="1940s pulp horror insect illustration",
        )

    # ── David Copperfield ──────────────────────────────────────────────────
    if "david copperfield" in title_author:
        return BookMotif(
            iconic_scene="earnest young Victorian man at a writer's desk in London garret, candle and manuscripts before him, rising from poverty",
            character_portrait="sensitive young man in threadbare Victorian coat, honest eyes, quill in hand, determination in every line",
            setting_landscape="Victorian London progression from Dover cliffs to Whitechapel lanes, Yarmouth fishing boats, and Soho lodgings",
            dramatic_moment="young David arriving penniless at Aunt Betsey's gate as she strides out in fury then transforms with unexpected kindness",
            symbolic_theme="self-making shown by a quill pen transforming a broken childhood toy into a published book on a London desk",
            style_specific_prefix="Victorian bildungsroman narrative engraving",
        )

    # ── The Murder of Roger Ackroyd ────────────────────────────────────────
    if "roger ackroyd" in title_author or "murder of roger" in title_author:
        return BookMotif(
            iconic_scene="meticulous Belgian detective in a perfect English village garden gesturing toward a closed study door",
            character_portrait="egg-shaped detective with waxed moustache and immaculate suit examining a carved chair in a candlelit library",
            setting_landscape="King's Abbot English village, Tudor study with a locked door, herbaceous borders, and a moonlit terrace",
            dramatic_moment="assembled suspects in the drawing room as the detective's grey cells reveal the impossibly shocking solution",
            symbolic_theme="hidden guilt shown by a narrator's own pen lying beside a victim's chair and a closed locked door",
            style_specific_prefix="Golden Age detective illustration",
        )

    # ── Short Stories by Chekhov ────────────────────────────────────────────
    if "short stories" in title_author and "chekhov" in title_author:
        return BookMotif(
            iconic_scene="melancholy Russian characters at a samovar in a provincial sitting room, birch forest visible through the window",
            character_portrait="weary provincial Russian in a fur-collared coat, eyes distant above a steaming glass of tea",
            setting_landscape="birch-lined Russian countryside, a railway platform in grey mist, a cherry orchard in blossom",
            dramatic_moment="a gun mounted on a wall in Act One finally fired as ordinary life erupts into irreversible consequence",
            symbolic_theme="quiet desperation shown by a fading candle beside a samovar in a birch-frosted Russian window",
            style_specific_prefix="Russian literary realist watercolour sketch",
        )

    # ── Memoirs of Fanny Hill ──────────────────────────────────────────────
    if "fanny hill" in title_author:
        return BookMotif(
            iconic_scene="young country girl arriving in 18th-century London by coach, wide-eyed before St Paul's and the Georgian cityscape",
            character_portrait="rosy-cheeked Georgian young woman in modest travelling cloak, wide eyes absorbing the London street spectacle",
            setting_landscape="Georgian London streets, booksellers' windows, coffee houses, river barges, and Covent Garden colonnades",
            dramatic_moment="Fanny reuniting with her true love on a rain-glistened Georgian street as coach lamps illuminate their faces",
            symbolic_theme="innocence navigating Georgian society shown by a country violet pressed between the pages of a London ledger",
            style_specific_prefix="18th-century picaresque Georgian engraving",
        )

    # ── Justice (Galsworthy) ────────────────────────────────────────────────
    if "justice" in title_author and ("galsworthy" in title_author or "galsworth" in title_author):
        return BookMotif(
            iconic_scene="a young clerk in a solitary confinement cell pacing, grey walls closing in as the prison system grinds on",
            character_portrait="gentle young man in prison grey crouched at a cell door, defeated posture, knuckles white on iron bars",
            setting_landscape="Edwardian courthouse, barristers in wigs, the docks, and a grim prison interior with iron galleries",
            dramatic_moment="prisoner beating helplessly on a cell door in the dark as the warden's footsteps recede down the gallery",
            symbolic_theme="institutional injustice shown by balanced scales held by a blindfolded figure inside a prison door arch",
            style_specific_prefix="Edwardian social realist charcoal engraving",
        )

    # ── Noli Me Tangere ────────────────────────────────────────────────────
    if "noli me tangere" in title_author:
        return BookMotif(
            iconic_scene="young Filipino idealist confronting a Spanish friar in a colonial Manila drawing room lit by oil lamps",
            character_portrait="Crisostomo Ibarra in European suit, torn between love and revolution, Manila's colonial church behind him",
            setting_landscape="Spanish colonial Manila, capiz-shell windows, Calesa carriages, tropical plazas, and Laguna de Bay beyond",
            dramatic_moment="Ibarra's arrest at the pista ng bayan as colonial guards seize him amid lanterns and festival crowd",
            symbolic_theme="colonial awakening shown by a Philippine sampaguita blooming through cracked Spanish stone under dawn light",
            style_specific_prefix="late-19th-century Philippine nationalist realism",
        )

    # ── The Beautiful and Damned ───────────────────────────────────────────
    if "beautiful and damned" in title_author:
        return BookMotif(
            iconic_scene="golden couple in Jazz Age evening dress drifting through a glittering Manhattan rooftop party at midnight",
            character_portrait="beautiful dissipated young man in white tie, glazed eyes, champagne glass tilting, Manhattan skyline behind",
            setting_landscape="1920s Manhattan, Riverside Drive apartment, Long Island lawns, speakeasy booths, and a dawn Hudson River",
            dramatic_moment="once-glamorous couple in a bare apartment, beauty faded, fortune gone, staring past each other at winter light",
            symbolic_theme="gilded American decline shown by a champagne coupe cracked on a marble floor beside a wilting gardenia",
            style_specific_prefix="Jazz Age Art Deco illustration",
        )

    # ── Vanity Fair ────────────────────────────────────────────────────────
    if "vanity fair" in title_author:
        return BookMotif(
            iconic_scene="green-eyed social climber in Regency ball gown ascending a staircase of titled heads toward a coroneted door",
            character_portrait="Becky Sharp in emerald silk gown, calculating smile, opera glass raised in a Regency ballroom",
            setting_landscape="Regency-era London ballrooms, Brussels before Waterloo, a Brussels street under Napoleon's cannon thunder",
            dramatic_moment="Becky Sharp playing charades at Lord Steyne's house as Rawdon Crawley bursts through the door in fury",
            symbolic_theme="social ambition shown by a puppet stage where the puppet climbs over other puppets toward a gold crown",
            style_specific_prefix="Regency satirical novel illustration engraving",
        )

    # ── Second Variety ─────────────────────────────────────────────────────
    if "second variety" in title_author:
        return BookMotif(
            iconic_scene="a soldier on a radioactive no-man's-land confronted by a small wounded boy who is actually a killer robot",
            character_portrait="battle-worn soldier in radiation suit aiming his rifle at a child-shaped robot on a blasted grey plain",
            setting_landscape="post-nuclear European wasteland, shattered buildings, grey ash sky, hidden robot claws in rubble",
            dramatic_moment="human survivors realising they cannot tell each other from killer machines as robots close in from all sides",
            symbolic_theme="dehumanised war shown by a child's shoe embedded in radioactive ash beside a mechanical claw",
            style_specific_prefix="Cold War science fiction graphite illustration",
        )

    # ── Works of Edgar Allan Poe ───────────────────────────────────────────
    if "edgar allan poe" in title_author or ("poe" in title_author and "edgar" in title_author):
        return BookMotif(
            iconic_scene="a black raven perched above a pallid scholar's chamber door as a pendulum swings and crimson masks fill the ballroom",
            character_portrait="tormented Gothic narrator in a candlelit study, raven above, the pit below, masque revellers beyond the door",
            setting_landscape="Gothic chamber with an iron pendulum, a crumbling house above a tarn, and a masquerade hall lit by coloured windows",
            dramatic_moment="the Red Death unmasked at the stroke of midnight as the entire masked ball freezes in horror",
            symbolic_theme="mortality and obsession shown by a raven silhouette over a cracked pendulum above an open grave",
            style_specific_prefix="Gothic Romantic horror chiaroscuro engraving",
        )

    # ── The Railway Children ───────────────────────────────────────────────
    if "railway children" in title_author:
        return BookMotif(
            iconic_scene="three children waving red petticoats frantically from a railway embankment to stop an oncoming steam train",
            character_portrait="eldest girl in Edwardian pinafore on the embankment, red flag aloft, steam locomotive thundering toward her",
            setting_landscape="Yorkshire valley railway line, green embankment, stone tunnel mouth, and smoke-puffed steam engines",
            dramatic_moment="father stepping out of the train's steam cloud to reunite with his children on the platform at last",
            symbolic_theme="faith and reunion shown by a child's paper train on rails leading back to a father's silhouette in steam",
            style_specific_prefix="Edwardian children's book illustration",
        )

    # ── Connecticut Yankee in King Arthur's Court ──────────────────────────
    if "connecticut yankee" in title_author or "king arthur s court" in title_author:
        return BookMotif(
            iconic_scene="19th-century American factory foreman in Camelot's tournament lists, wired electrical fence facing armoured knights",
            character_portrait="Hank Morgan in jeans and shirt beside a medieval knight, wrench in hand, gleam of Yankee ingenuity in his eye",
            setting_landscape="Arthurian Camelot castle contrasted with telegraph poles and a steam engine on a muddy medieval road",
            dramatic_moment="Hank's Gatling guns mowing down charging medieval knights at the final Battle of the Sand-Belt",
            symbolic_theme="industrial modernity against chivalric legend shown by a wrench laid across Excalibur on the round table",
            style_specific_prefix="Victorian satirical Arthurian illustration",
        )

    # ── The Turn of the Screw ──────────────────────────────────────────────
    if "turn of the screw" in title_author:
        return BookMotif(
            iconic_scene="frightened governess on a tower staircase facing a translucent apparition while two pale children sleep below",
            character_portrait="Victorian governess, candle guttering, white-knuckled on a banister, eyes fixed on a ghost at the window",
            setting_landscape="Bly country house, misty lake, night-dark tower, overgrown gardens, and a pale ghost on the battlements",
            dramatic_moment="Miles collapsing in the governess's arms as the ghost of Peter Quint disappears into the darkened lawn",
            symbolic_theme="ambiguous evil shown by two halves of a face — one child's, one ghost's — in a black country-house mirror",
            style_specific_prefix="Victorian Gothic psychological illustration",
        )

    # ── Sorrows of Young Werther ────────────────────────────────────────────
    if "werther" in title_author or "sorrows of young" in title_author:
        return BookMotif(
            iconic_scene="sensitive young man in blue coat and yellow waistcoat reading letters beneath a lime tree in a German summer meadow",
            character_portrait="Werther in his iconic blue coat, passionate eyes, clutching a love letter, stormy sky gathering behind",
            setting_landscape="Wetzlar countryside, Rhine valley village, chestnut trees, and Lotte's garden gate at golden hour",
            dramatic_moment="Werther's final night, blue coat draped over a chair, a pistol and an unfinished letter on the writing desk",
            symbolic_theme="Romantic anguish shown by a blue coat and yellow waistcoat crumpled beside an extinguished candle and letters",
            style_specific_prefix="German Romantic Sturm und Drang watercolour",
        )

    # ── Swann's Way ─────────────────────────────────────────────────────────
    if "swann s way" in title_author or "swanns way" in title_author or "proust" in title_author:
        return BookMotif(
            iconic_scene="a narrator dunking a madeleine into a lime-blossom tea, Combray church spire materialising in golden memory",
            character_portrait="reflective Parisian narrator at a table, teacup raised, entire Combray childhood flooding into his mind's eye",
            setting_landscape="Combray village, hawthorn lanes, grandmother's garden, and gilded Parisian salon interiors merging in memory",
            dramatic_moment="Vinteuil's little phrase rising from the salon piano as Swann sees Odette's face in the music itself",
            symbolic_theme="involuntary memory shown by a madeleine crumb dissolving into a golden Combray church spire",
            style_specific_prefix="Belle Époque Impressionist literary illustration",
        )

    # ── Rip Van Winkle ─────────────────────────────────────────────────────
    if "rip van winkle" in title_author:
        return BookMotif(
            iconic_scene="bearded old man in ragged 18th-century Dutch clothes waking from sleep among mist-shrouded Catskill boulders",
            character_portrait="ancient Rip Van Winkle in colonial hunting coat, white beard to his knees, bewildered in a changed village",
            setting_landscape="Catskill Mountains, Dutch colonial Hudson Valley, ghostly ninepins thunder in mist, and a village changed by decades",
            dramatic_moment="Rip entering his Sleepy Hollow village to find his wife dead, his house ruined, and his children grown strangers",
            symbolic_theme="time's passage shown by a colonial hat and musket overgrown with moss and mountain ferns",
            style_specific_prefix="American folklorish Hudson River School illustration",
        )

    # ── Plays (Susan Glaspell) ──────────────────────────────────────────────
    if "glaspell" in title_author or ("plays" in title and "glaspell" in title_author):
        return BookMotif(
            iconic_scene="two women in a farmhouse kitchen discovering a strangled canary in a box while men search uselessly elsewhere",
            character_portrait="quiet Midwestern farm woman in apron holding a small birdcage, eyes steady with female solidarity",
            setting_landscape="bleak Iowa farmhouse kitchen, cold stove, patchwork quilt half-finished, frosted window, empty bird cage",
            dramatic_moment="two women exchanging a silent look over the dead canary and its cage, sealing their silent sisterly verdict",
            symbolic_theme="silenced female voice shown by an empty birdcage and a knotted quilt on a bare farmhouse kitchen table",
            style_specific_prefix="early American Modernist theatre etching",
        )

    # ── Lysistrata ─────────────────────────────────────────────────────────
    if "lysistrata" in title_author:
        return BookMotif(
            iconic_scene="Greek women barricading the Acropolis gates with olive branches while robed men plead in comic desperation below",
            character_portrait="Lysistrata in Athenian peplos, arms folded, standing before the Parthenon gates, expression imperious",
            setting_landscape="classical Athens Acropolis, Doric columns, olive-grove hillside, the Aegean glittering below in afternoon light",
            dramatic_moment="women declaring a love strike as armoured husbands crash to their knees before the Propylaea in comic agony",
            symbolic_theme="women's peace-power shown by a loom shuttle and distaff blocking a bronze Athenian spear below the Acropolis",
            style_specific_prefix="classical red-figure pottery comedy illustration",
        )

    # ── Anne of Avonlea ─────────────────────────────────────────────────────
    if "anne of avonlea" in title_author:
        return BookMotif(
            iconic_scene="red-haired young teacher with a slate under her arm walking an apple-blossom lane to a one-room island school",
            character_portrait="Anne Shirley with braided auburn hair, bright grey eyes, walking between blooming apple trees toward a schoolhouse",
            setting_landscape="Prince Edward Island in spring, red soil lanes, apple orchards in full bloom, and a white clapboard schoolhouse",
            dramatic_moment="Anne presenting a wreath of apple blossoms at the school's first day as her students break into delighted laughter",
            symbolic_theme="imagination nurturing others shown by a red-haired figure planting words in children's minds like seeds in PEI soil",
            style_specific_prefix="Edwardian pastoral Canadian illustration",
        )

    # ── Pygmalion ──────────────────────────────────────────────────────────
    if "pygmalion" in title_author and ("shaw" in title_author or "bernard" in title_author):
        return BookMotif(
            iconic_scene="phonetics professor pointing at notation on a blackboard while a Cockney flower girl practices vowels in a drawing room",
            character_portrait="Eliza Doolittle transformed in white tea-gown, enunciating carefully, Higgins tapping his phonograph behind her",
            setting_landscape="Edwardian Wimpole Street drawing room, phonograph cylinders, Covent Garden flowers sold from a basket nearby",
            dramatic_moment="Eliza's triumphant vowels at the ambassador's reception as Higgins and Pickering exchange stunned looks of pride",
            symbolic_theme="identity reshaped by language shown by a Cockney cap and violets beside a gold calling card and white gloves",
            style_specific_prefix="Edwardian social comedy illustration",
        )

    # ── Best American Humorous Short Stories ────────────────────────────────
    if "best american humorous" in title_author or ("humorous short stories" in title_author and "american" in title_author):
        return BookMotif(
            iconic_scene="a gallery of comic American characters from frontier tall-tales and parlour wit arrayed on a Mississippi steamboat deck",
            character_portrait="frontier yarn-spinner in coonskin cap and another in frock coat mid-jest, audience howling around them",
            setting_landscape="diverse American scenes stitched together — New England parlour, Mississippi levee, frontier saloon, and city street",
            dramatic_moment="tall tale reaching its impossible climax as the audience falls off their chairs in Yankee disbelief",
            symbolic_theme="American national humour shown by an ink quill tied to a lasso wrapped around a top hat and a frontier rifle",
            style_specific_prefix="19th-century American comic periodical illustration",
        )

    # ── The Happy Prince ────────────────────────────────────────────────────
    if "happy prince" in title_author:
        return BookMotif(
            iconic_scene="a golden statue stripped of sapphire eyes and ruby sword, a small swallow roosting on his bare shoulder in winter",
            character_portrait="the gilded Happy Prince, eyes weeping lead tears, a swallow delicately removing his last gold leaf",
            setting_landscape="a grey wintry city, gold-leaf spiraling off a statue onto a poor seamstress's garret, spire against leaden sky",
            dramatic_moment="the swallow dying at the statue's lead feet as the townspeople melt down the tarnished prince in the morning frost",
            symbolic_theme="charity unto death shown by a bare lead statue and a dead swallow on a snow-covered pedestal",
            style_specific_prefix="Victorian fairy tale watercolour illustration",
        )

    # ── Ivanhoe ────────────────────────────────────────────────────────────
    if "ivanhoe" in title_author:
        return BookMotif(
            iconic_scene="armoured Saxon knight charging across a tournament field as Norman lances splinter and the crowd roars from lists",
            character_portrait="Ivanhoe in white and silver armour with disinherited knight's shield charging under a blazing summer sun",
            setting_landscape="Ashby-de-la-Zouche tournament ground, Sherwood Forest oaks, Torquilstone castle under siege in Norman England",
            dramatic_moment="Ivanhoe's siege of Torquilstone as Templars defend the battlements and Sherwood archers rain arrows from the woods",
            symbolic_theme="Saxon honour against Norman usurpation shown by a disinherited knight's shield against an ironclad Templar's cross",
            style_specific_prefix="Romantic medieval chivalric oil engraving",
        )

    # ── A Princess of Mars ─────────────────────────────────────────────────
    if "princess of mars" in title_author or "barsoom" in title_author:
        return BookMotif(
            iconic_scene="Confederate cavalryman in Martian armour facing towering four-armed green warriors on a rust-red Barsoomian desert",
            character_portrait="John Carter in white cape and Barsoomian harness, sword raised, two moons in the violet Martian sky above",
            setting_landscape="red Martian desert, ruined ancient cities, pale Martian atmosphere, twin moons rising over ochre dunes",
            dramatic_moment="aerial battle of Martian flyers above the dying city as John Carter and Dejah Thoris embrace in the crow's nest",
            symbolic_theme="earthly courage transposed to alien heroism shown by a Confederate sword thrust into red Martian soil",
            style_specific_prefix="1910s planetary romance pulp illustration",
        )

    # ── The Awakening ──────────────────────────────────────────────────────
    if "the awakening" in title_author and "chopin" in title_author:
        return BookMotif(
            iconic_scene="a Creole woman in white walking alone into warm Gulf of Mexico surf, small hotel behind her, free of society",
            character_portrait="Edna Pontellier in white muslin at the shore, face turned seaward, arms open, Gulf light on her hair",
            setting_landscape="Grand Isle Louisiana coast, Spanish moss, Creole cottages, a wide warm Gulf, and New Orleans French Quarter",
            dramatic_moment="Edna wading deeper into the Gulf as the final liberation from convention dissolves into green water",
            symbolic_theme="feminine self-possession shown by a woman's hat adrift on the Gulf alongside a torn calling card",
            style_specific_prefix="Southern Impressionist coastal watercolour",
        )

    # ── The Alchemist (Ben Jonson) ─────────────────────────────────────────
    if "the alchemist" in title_author and ("jonson" in title_author or "ben jon" in title_author):
        return BookMotif(
            iconic_scene="three Jacobean con artists in a London alchemist's den surrounded by retorts, bellows, and a queue of gulled clients",
            character_portrait="Face the con man in multiple disguises — puritan, scholar, captain — pocketing coin from a credulous merchant",
            setting_landscape="Jacobean London plague-emptied house, alchemy laboratory with furnaces, a street full of eager victims",
            dramatic_moment="the alchemist's furnace exploding as clients storm the house and the fraudsters scatter through back lanes",
            symbolic_theme="human greed alchemised from base credulity shown by a philosopher's stone made of painted lead",
            style_specific_prefix="Jacobean city comedy satirical engraving",
        )

    # ── Tristram Shandy ─────────────────────────────────────────────────────
    if "tristram shandy" in title_author:
        return BookMotif(
            iconic_scene="a digressive narrator writing at a desk while his Uncle Toby builds fortifications on a billiard table behind him",
            character_portrait="Tristram Shandy's narrator mid-sentence at a writing desk, volume one open, ink blots, a marble table of fortifications",
            setting_landscape="18th-century English country house, a bowling green with toy fortifications, a library, and Toby's campaign maps",
            dramatic_moment="Uncle Toby and Corporal Trim's fort-building reaching theatrical heights as the family ignores Tristram's birth",
            symbolic_theme="narrative digression shown by a spiral doodle becoming a novel beside a blank marble page and a blotted quill",
            style_specific_prefix="18th-century comic meta-narrative engraving",
        )

    # ── Gargantua and Pantagruel ────────────────────────────────────────────
    if "gargantua" in title_author or "pantagruel" in title_author or "rabelais" in title_author:
        return BookMotif(
            iconic_scene="an enormous laughing giant striding through a Renaissance French village, bells of Notre Dame caught in his hair",
            character_portrait="giant Gargantua in Renaissance doublet with a flagon the size of a hogshead, tearing a forest oak as a toothpick",
            setting_landscape="late-medieval France, Abbey of Thélème, giants feasting on entire oxen, and monks fleeing across monastery courtyards",
            dramatic_moment="Pantagruel opening his enormous mouth to shelter an army as rain falls on the giant tongue landscape inside",
            symbolic_theme="humanist excess and freedom shown by an overflowing banquet table scaled for titans with tiny men at the rim",
            style_specific_prefix="Renaissance Flemish comic giant illustration",
        )

    # ── Space Station 1 (Frank Belknap Long) ────────────────────────────────
    if "space station" in title_author and "long" in title_author:
        return BookMotif(
            iconic_scene="1950s astronauts in bubble-helmeted suits on a rotating orbital space station, Earth arc glowing below",
            character_portrait="retro-futuristic astronaut in chrome space suit tethering a module to a station as Earth fills the porthole",
            setting_landscape="1950s orbital space station with spoke-and-hub design, solar panels, and the blue curve of Earth below",
            dramatic_moment="emergency spacewalk on the station's hull as a meteor shower sparks off the metal skin against star-filled void",
            symbolic_theme="dawn of the space age shown by a human silhouette riveting a hull plate with Earth and Moon framed behind",
            style_specific_prefix="1950s retro space age pulp illustration",
        )

    # ── Arsène Lupin ────────────────────────────────────────────────────────
    if (
        "ars ne lupin" in title_author
        or "arse ne lupin" in title_author
        or "arsene lupin" in title_author
        or "arsnne lupin" in title_author
        or ("lupin" in title_author and ("leblanc" in title_author or "leblan" in title_author))
    ):
        return BookMotif(
            iconic_scene="elegant gentleman thief in a cape and top hat bowing to a duchess at a Belle Époque Paris soirée, jewels vanishing",
            character_portrait="Arsène Lupin in white gloves and top hat, moustached smile, a pilfered diamond barely visible in his cuff",
            setting_landscape="Belle Époque Paris, Second Empire mansions, Seine bridges, the Louvre gallery, and a rooftop at midnight",
            dramatic_moment="Lupin escaping across Paris rooftops at dawn, stolen painting under one arm, gendarmes closing from below",
            symbolic_theme="charming illegality shown by a bouquet of violets over a safe-cracking kit on a Haussmann velvet banquette",
            style_specific_prefix="Belle Époque Art Nouveau adventure illustration",
        )


    # Author/theme fallbacks.
    if "austen" in author:
        return BookMotif(
            iconic_scene="Regency-era social gathering with restrained glances and layered etiquette",
            character_portrait="poised gentlewoman in period dress, composed posture, intelligent eyes",
            setting_landscape="English countryside estate gardens, rolling fields, and elegant manor architecture",
            dramatic_moment="emotionally charged proposal in rain-lit grounds near an illuminated ballroom",
            symbolic_theme="duty and desire represented by paired gloves resting on a sealed letter",
            style_specific_prefix="Regency watercolor etching",
        )
    if "dickens" in author:
        return BookMotif(
            iconic_scene="crowded Victorian street scene with poverty, warmth, and theatrical human contrast",
            character_portrait="earnest figure in worn coat, expressive face, bustling city behind",
            setting_landscape="soot-darkened London rooftops, gas lamps, and narrow alleys",
            dramatic_moment="moral turning point at dawn with church bells and gathering crowd",
            symbolic_theme="compassion symbolized by a lantern glowing in fog and rain",
            style_specific_prefix="Victorian narrative engraving",
        )
    if "mark twain" in author:
        return BookMotif(
            iconic_scene="mischievous adventure on a riverbank with humor and sudden peril",
            character_portrait="quick-witted youth in simple clothes, sly smile, wind-tossed hair",
            setting_landscape="American river town, wooden docks, steamboat smoke, and broad sky",
            dramatic_moment="high-risk escape by raft under moonlit current",
            symbolic_theme="freedom versus convention represented by a drifting hat on the water",
            style_specific_prefix="Americana ink-wash engraving",
        )
    if "jules verne" in author:
        return BookMotif(
            iconic_scene="ambitious expedition confronting technological marvels in hazardous unknown territory",
            character_portrait="determined explorer-scientist with instruments, maps, and windblown coat",
            setting_landscape="dramatic frontier panorama with machinery, cliffs, and atmospheric sky",
            dramatic_moment="mechanical failure during a storm as team members cling to hope",
            symbolic_theme="human curiosity shown as a compass piercing clouds and darkness",
            style_specific_prefix="scientific adventure lithograph",
        )
    if "dostoyev" in author:
        return BookMotif(
            iconic_scene="tormented figure crossing a dim city square burdened by existential guilt",
            character_portrait="intense eyes, gaunt features, worn coat, and clenched hands in cold light",
            setting_landscape="Northern city canals, cramped interiors, and oppressive winter skies",
            dramatic_moment="shattering confession under candlelight amid law, faith, and despair",
            symbolic_theme="split conscience represented by mirrored silhouettes on wet stone",
            style_specific_prefix="psychological monochrome engraving",
        )
    if "shakespeare" in author:
        return BookMotif(
            iconic_scene="stage-like Renaissance confrontation with nobles, swords, and charged gestures",
            character_portrait="dramatic protagonist in period costume, expressive posture, theatrical light",
            setting_landscape="stone courtyards, banners, and moonlit towers framing courtly intrigue",
            dramatic_moment="fatal climax amid crowd and torchlight in a royal chamber",
            symbolic_theme="ambition and fate represented by a crown beside a cracked dagger",
            style_specific_prefix="theatrical chiaroscuro woodcut",
        )

    return BookMotif(
        iconic_scene="pivotal narrative tableau with period costume, emotional tension, and dramatic environmental storytelling",
        character_portrait="central protagonist in historically grounded attire, expressive face, and purposeful posture",
        setting_landscape="key story environment with layered architecture, atmospheric depth, and symbolic objects",
        dramatic_moment="climactic turning point under turbulent light, motion, and heightened emotional stakes",
        symbolic_theme="core themes represented by allegorical objects, contrasting light, and recursive geometry",
        style_specific_prefix="period-inspired mixed-media engraving",
    )


def generate_prompts_for_book(book_entry: dict, templates: dict) -> list[BookPrompt]:
    """Generate 5 variant prompts for one book entry."""
    motif = _motif_for_book(book_entry)
    variants_cfg = templates["variants"]
    style_groups = templates["style_groups"]
    negative_prompt = _ensure_negative_prompt_terms(str(templates["negative_prompt"]))

    variant_plan = [
        (1, "1_iconic_scene_sketch", "scene_description", _limit_words(motif.iconic_scene)),
        (2, "2_character_portrait_sketch", "character_description", _limit_words(motif.character_portrait)),
        (3, "3_setting_landscape_sketch", "setting_description", _limit_words(motif.setting_landscape)),
        (4, "4_dramatic_oil_painting", "moment_description", _limit_words(motif.dramatic_moment)),
        (5, "5_symbolic_alternative", "theme_description", _limit_words(motif.symbolic_theme)),
    ]

    prompts: list[BookPrompt] = []
    for variant_id, variant_key, description_slot, description_text in variant_plan:
        cfg = variants_cfg[variant_key]
        style_group_name = cfg["style_group"]
        style_group = style_groups[style_group_name]
        style_anchors = style_group["style_anchors"]

        format_kwargs = {
            "scene_description": description_text,
            "character_description": description_text,
            "setting_description": description_text,
            "moment_description": description_text,
            "theme_description": description_text,
            "style_anchors": style_anchors,
            "style_specific_prefix": motif.style_specific_prefix,
        }
        format_kwargs[description_slot] = description_text

        prompt = cfg["template"].format(**format_kwargs)
        prompt = _strip_forbidden(prompt, book_entry["title"], book_entry["author"])
        prompt = diversify_prompt(prompt, variant_id)
        prompt = _ensure_prompt_constraints(prompt)

        prompts.append(
            BookPrompt(
                book_number=book_entry["number"],
                book_title=book_entry["title"],
                book_author=book_entry["author"],
                variant_id=variant_id,
                variant_key=variant_key,
                variant_name=cfg["name"],
                description=description_text,
                prompt=prompt,
                negative_prompt=negative_prompt,
                style_reference=style_group_name,
            )
        )

    return prompts


def generate_all_prompts(catalog_path: Path, templates_path: Path) -> list[dict[str, Any]]:
    """Generate all prompt records for the full catalog."""
    catalog = safe_json.load_json(catalog_path, [])
    templates = safe_json.load_json(templates_path, {})

    all_records: list[dict[str, Any]] = []
    for book in catalog if isinstance(catalog, list) else []:
        if not isinstance(book, dict):
            continue
        variant_prompts = generate_prompts_for_book(book, templates)
        record = {
            "number": book["number"],
            "title": book["title"],
            "author": book["author"],
            "folder_name": book.get("folder_name"),
            "file_base": book.get("file_base"),
            "variants": [item.to_dict() for item in variant_prompts],
        }
        all_records.append(record)
    return all_records


def save_prompts(prompts: list[dict[str, Any]], output_path: Path) -> None:
    """Save generated prompts as JSON."""
    payload = {
        "book_count": len(prompts),
        "variant_count_per_book": 5,
        "total_prompts": len(prompts) * 5,
        "books": prompts,
    }
    safe_json.atomic_write_json(output_path, payload)
    logger.info("Wrote %d prompts for %d books to %s", len(prompts) * 5, len(prompts), output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Prompt 1B prompt catalog.")
    parser.add_argument("--catalog-path", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--templates-path", type=Path, default=DEFAULT_TEMPLATES_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    prompts = generate_all_prompts(args.catalog_path, args.templates_path)
    save_prompts(prompts, args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
