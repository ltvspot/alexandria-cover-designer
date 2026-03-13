"""Prompt library system for reusable, title-agnostic generation prompts (Prompt 2A)."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

try:
    from src import config
    from src import safe_json
    from src.logger import get_logger
except ModuleNotFoundError:  # pragma: no cover
    import config  # type: ignore
    import safe_json  # type: ignore
    from logger import get_logger  # type: ignore

logger = get_logger(__name__)

SUPPORTED_REUSABLE_PLACEHOLDERS: tuple[str, ...] = (
    "{title}",
    "{author}",
    "{TITLE}",
    "{AUTHOR}",
    "{SUBTITLE}",
    "{SCENE}",
    "{MOOD}",
    "{ERA}",
)

ALEXANDRIA_SYSTEM_NEGATIVE_PROMPT = (
    "No text, no letters, no words, no numbers, no titles, no author names, no typography, no captions, "
    "no labels, no watermarks, no signatures, no inscriptions of any kind. No modern elements, no photography, "
    "no 3D rendering, no digital art aesthetic, no gradients on background, no neon colours, no sans-serif fonts, "
    "no minimalist design, no stock photo look, no cartoonish style, no anime influence, no spelling mistakes, "
    "no blurry illustration, no off-centre composition, no white or light backgrounds. "
    "No ornamental borders, no frames, no scrollwork, no filigree, no decorative edges, no corner ornaments, "
    "no dividers."
)

ALEXANDRIA_BASE_NEGATIVE_PROMPT = (
    f"{ALEXANDRIA_SYSTEM_NEGATIVE_PROMPT} "
    "No circular vignette, no medallion composition, no ornamental frame, no decorative border, "
    "no floral border frame, no scrollwork frame."
)


def _scene_first_prompt(style_label: str, style_description: str, *, full_canvas: bool = False) -> str:
    del full_canvas
    return (
        "Book cover illustration only — no text, no title, no author name, no lettering of any kind. "
        "No border, no frame, no ornamental elements, no medallion, no decorative edges. "
        "This illustration MUST depict the following specific scene: {SCENE}. Every figure, object, and "
        "setting element in this scene must be clearly recognizable and faithful to the source material. "
        f"Rendered in {style_label} style — {style_description}. "
        "The mood is {MOOD}. Era reference: {ERA}. Full scene composition filling the entire canvas, "
        "no circular framing. Square format, high resolution, print-ready."
    )


ALEXANDRIA_PROMPT_CATALOG: tuple[dict[str, object], ...] = (
    {
        "id": "alexandria-base-classical-devotion",
        "name": "BASE 1 — Classical Devotion",
        "style_label": "Alphonse Mucha and Edward Burne-Jones",
        "style_description": (
            "MANDATORY Art Nouveau Pre-Raphaelite illustration style. Color palette MUST use: deep midnight navy "
            "blue (#0a1628) as dominant background, warm burnished gold (#c5941a) and antique brass (#b5884e) for "
            "all highlights and light sources, rich cobalt (#0047ab) and cerulean blue (#2a7ab0) for mid-tones and "
            "clothing, earth ochre (#cc7722) and burnt sienna (#8a3324) for skin and landscapes. MANDATORY fine "
            "botanical detail: every flower petal, leaf vein, and vine tendril must be individually rendered. "
            "Flowing Art Nouveau lines throughout. Figures wear hyper-detailed period clothing with visible "
            "embroidery, flowing auburn or golden hair. Background features lush pastoral gardens with medieval "
            "stone castles, winding rivers, willow trees. Overall texture: gilded illuminated manuscript with "
            "visible gold leaf effect"
        ),
        "prompt_template": (
            "Book cover illustration only — no text, no title, no author name, no lettering of any kind. "
            "No border, no frame, no ornamental elements, no medallion, no decorative edges. "
            "This illustration MUST depict the following specific scene: {SCENE}. Every figure, object, and "
            "setting element in this scene must be clearly recognizable and faithful to the source material. "
            "Rendered in the style of Alphonse Mucha and Edward Burne-Jones — MANDATORY Art Nouveau "
            "Pre-Raphaelite illustration style. Color palette MUST use: deep midnight navy blue (#0a1628) as "
            "dominant background, warm burnished gold (#c5941a) and antique brass (#b5884e) for all highlights "
            "and light sources, rich cobalt (#0047ab) and cerulean blue (#2a7ab0) for mid-tones and clothing, "
            "earth ochre (#cc7722) and burnt sienna (#8a3324) for skin and landscapes. MANDATORY fine botanical "
            "detail: every flower petal, leaf vein, and vine tendril must be individually rendered. Flowing Art "
            "Nouveau lines throughout. Figures wear hyper-detailed period clothing with visible embroidery, "
            "flowing auburn or golden hair. Background features lush pastoral gardens with medieval stone "
            "castles, winding rivers, willow trees. Overall texture: gilded illuminated manuscript with visible "
            "gold leaf effect. The mood is {MOOD}. Era reference: {ERA}. Full scene composition filling the "
            "entire canvas, no circular framing. Square format, high resolution, print-ready."
        ),
        "full_canvas": True,
        "negative_prompt": ALEXANDRIA_BASE_NEGATIVE_PROMPT,
        "notes": "Alexandria base prompt. Best for: Religious, Apocryphal, Biblical.",
        "tags": ["alexandria", "base", "classical-devotion", "religious", "apocryphal", "biblical"],
        "category": "builtin",
    },
    {
        "id": "alexandria-base-philosophical-gravitas",
        "name": "BASE 2 — Philosophical Gravitas",
        "style_label": "contemplative chiaroscuro illustration",
        "style_description": (
            "deep shadows, selective warm highlights, muted burnt umber and ochre palette, single focal light "
            "source, grave reflective atmosphere"
        ),
        "full_canvas": True,
        "negative_prompt": ALEXANDRIA_BASE_NEGATIVE_PROMPT,
        "notes": "Alexandria base prompt. Best for: Philosophy, Self-Help, Strategy.",
        "tags": ["alexandria", "base", "philosophical-gravitas", "philosophy", "self-help", "strategy"],
        "category": "builtin",
    },
    {
        "id": "alexandria-base-gothic-atmosphere",
        "name": "BASE 3 — Gothic Atmosphere",
        "style_label": "dark atmospheric Gothic illustration",
        "style_description": (
            "moonlit shadows, drifting mist, deep indigo and crimson tones, expressionist contrast, dramatic "
            "silhouettes against turbulent skies"
        ),
        "full_canvas": True,
        "negative_prompt": ALEXANDRIA_BASE_NEGATIVE_PROMPT,
        "notes": "Alexandria base prompt. Best for: Horror, Gothic, Supernatural.",
        "tags": ["alexandria", "base", "gothic-atmosphere", "horror", "gothic", "supernatural"],
        "category": "builtin",
    },
    {
        "id": "alexandria-base-romantic-realism",
        "name": "BASE 4 — Romantic Realism",
        "style_label": "Dante Gabriel Rossetti and William Morris",
        "style_description": (
            "MANDATORY romantic Pre-Raphaelite realism with Art Nouveau decorative influence. Color palette MUST "
            "use: deep navy (#0e1f3d) and midnight blue (#1a2a4a) for shadows and sky, warm gold (#d4a017) and "
            "amber (#f0a500) for light sources and highlights, rich crimson (#8b0000) and ivory (#fffff0) in "
            "clothing, sage green (#6b8e4e) and forest green (#2d572c) in foliage. MANDATORY botanical precision: "
            "every plant rendered like a Victorian botanical plate. Dramatic skies with swirling clouds in "
            "graduated blues and golds. Figures wear medieval or Renaissance clothing with visible brocade and "
            "embroidery, flowing fabric catching golden light. Background: lush English gardens, Gothic "
            "architecture, winding paths through wildflower meadows. Overall feel: a gilded 19th-century Royal "
            "Academy painting"
        ),
        "prompt_template": (
            "Book cover illustration only — no text, no title, no author name, no lettering of any kind. "
            "No border, no frame, no ornamental elements, no medallion, no decorative edges. "
            "This illustration MUST depict the following specific scene: {SCENE}. Every figure, object, and "
            "setting element in this scene must be clearly recognizable and faithful to the source material. "
            "Rendered in the style of Dante Gabriel Rossetti and William Morris — MANDATORY romantic "
            "Pre-Raphaelite realism with Art Nouveau decorative influence. Color palette MUST use: deep navy "
            "(#0e1f3d) and midnight blue (#1a2a4a) for shadows and sky, warm gold (#d4a017) and amber "
            "(#f0a500) for light sources and highlights, rich crimson (#8b0000) and ivory (#fffff0) in "
            "clothing, sage green (#6b8e4e) and forest green (#2d572c) in foliage. MANDATORY botanical "
            "precision: every plant rendered like a Victorian botanical plate. Dramatic skies with swirling "
            "clouds in graduated blues and golds. Figures wear medieval or Renaissance clothing with visible "
            "brocade and embroidery, flowing fabric catching golden light. Background: lush English gardens, "
            "Gothic architecture, winding paths through wildflower meadows. Overall feel: a gilded "
            "19th-century Royal Academy painting. The mood is {MOOD}. Era reference: {ERA}. Full scene "
            "composition filling the entire canvas, no circular framing. Square format, high resolution, "
            "print-ready."
        ),
        "full_canvas": True,
        "negative_prompt": ALEXANDRIA_BASE_NEGATIVE_PROMPT,
        "notes": "Alexandria base prompt. Best for: Classical Literature, Novels, Drama.",
        "tags": ["alexandria", "base", "romantic-realism", "literature", "novels", "drama"],
        "category": "builtin",
    },
    {
        "id": "alexandria-base-esoteric-mysticism",
        "name": "BASE 5 — Esoteric Mysticism",
        "style_label": "esoteric mystical illustration",
        "style_description": (
            "celestial motifs, sacred geometry accents, deep midnight blue and gold palette, luminous ethereal "
            "lighting, symbolic depth"
        ),
        "full_canvas": True,
        "negative_prompt": ALEXANDRIA_BASE_NEGATIVE_PROMPT,
        "notes": "Alexandria base prompt. Best for: Occult, Mystical, Forbidden Texts.",
        "tags": ["alexandria", "base", "esoteric-mysticism", "occult", "mystical", "esoteric"],
        "category": "builtin",
    },
    {
        "id": "alexandria-wildcard-edo-meets-alexandria",
        "name": "WILDCARD 1 — Dramatic Graphic Novel",
        "style_label": "dramatic graphic novel engraving",
        "style_description": (
            "bold parallel crosshatching, heavy black outlines, expressive faces in close-up, deep black with "
            "warm amber and burnt orange highlights, swirling dramatic sky"
        ),
        "notes": "Alexandria wildcard prompt. Dramatic amber-black engraving with graphic novel poster energy.",
        "tags": ["alexandria", "wildcard", "dramatic-graphic-novel", "graphic-novel", "crosshatch", "dramatic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-pre-raphaelite-garden",
        "name": "WILDCARD 2 — Vintage Travel Poster",
        "style_label": "bold 1930s vintage travel poster",
        "style_description": (
            "flat unblended colour blocks with clean outlines, layered depth planes, burgundy navy cream and "
            "forest green palette, geometric confidence"
        ),
        "notes": "Alexandria wildcard prompt. Flat-colour travel-poster composition with bold geometric depth.",
        "tags": ["alexandria", "wildcard", "vintage-travel-poster", "travel-poster", "graphic", "flat-color"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-illuminated-manuscript",
        "name": "WILDCARD 3 — Illuminated Manuscript",
        "style_label": "medieval illuminated manuscript",
        "style_description": (
            "gold leaf accents, ultramarine blue and vermilion, intricate marginalia patterns, flat perspective "
            "with symbolic scale, rich decorative detail"
        ),
        "notes": "Alexandria wildcard prompt. Medieval manuscript energy for ancient or sacred material.",
        "tags": ["alexandria", "wildcard", "illuminated-manuscript", "medieval", "celtic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-celestial-cartography",
        "name": "WILDCARD 4 — Celestial Cartography",
        "style_label": "scientific cartographic illustration",
        "style_description": (
            "compass roses, parchment tones, precise linework, sepia and aged-gold palette, navigational chart "
            "aesthetics, hand-drawn map detail"
        ),
        "notes": "Alexandria wildcard prompt. Cosmic engraving language for knowledge-rich or metaphysical titles.",
        "tags": ["alexandria", "wildcard", "celestial-cartography", "celestial", "astronomy"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-temple-of-knowledge",
        "name": "WILDCARD 5 — Temple of Knowledge",
        "style_label": "monumental architectural illustration",
        "style_description": (
            "classical columns, dramatic perspective, warm lamplight on stone, scrolls and books as decorative "
            "elements, sepia and amber palette with selective gold highlights"
        ),
        "notes": "Alexandria wildcard prompt. Direct homage to Alexandria's Egyptian origin and temple symbolism.",
        "tags": ["alexandria", "wildcard", "temple-of-knowledge", "egyptian", "mystical"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-venetian-renaissance",
        "name": "Venetian Renaissance",
        "style_label": "Venetian Renaissance oil painting",
        "style_description": (
            "Titian-warm glazes, luminous skin tones, rich velvet and brocade fabrics, atmospheric sfumato "
            "backgrounds, deep jewel-tone crimson sapphire and gold palette"
        ),
        "notes": "Alexandria wildcard prompt. Venetian Renaissance richness with glowing jewel-tone depth.",
        "tags": ["alexandria", "wildcard", "venetian-renaissance", "classical", "fine-art"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-dutch-golden-age",
        "name": "Dutch Golden Age",
        "style_label": "Dutch Golden Age painting",
        "style_description": (
            "Rembrandt-like chiaroscuro, intimate domestic lighting, meticulous fabric texture, warm amber and "
            "deep brown palette, candlelit atmosphere with selective highlights"
        ),
        "notes": "Alexandria wildcard prompt. Dutch interior drama with intimate candlelit precision.",
        "tags": ["alexandria", "wildcard", "dutch-golden-age", "classical", "fine-art"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-impressionist-plein-air",
        "name": "Impressionist Plein Air",
        "style_label": "French Impressionist plein air",
        "style_description": (
            "visible brushstrokes, dappled natural sunlight, soft focus atmospheric depth, luminous pastel and "
            "sky-blue palette, Monet-like light on water and foliage"
        ),
        "notes": "Alexandria wildcard prompt. Sunlit Impressionist atmosphere with airy painterly motion.",
        "tags": ["alexandria", "wildcard", "impressionist-plein-air", "classical", "fine-art"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-academic-neoclassical",
        "name": "Academic Neoclassical",
        "style_label": "Academic Neoclassical painting",
        "style_description": (
            "idealized proportions, marble-smooth surfaces, heroic poses, cool grey-blue and warm sandstone "
            "palette, classical architectural framing, David-like precision and grandeur"
        ),
        "notes": "Alexandria wildcard prompt. Neoclassical grandeur with disciplined heroic staging.",
        "tags": ["alexandria", "wildcard", "academic-neoclassical", "classical", "fine-art"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-baroque-dramatic",
        "name": "Baroque Dramatic",
        "style_label": "Baroque dramatic painting",
        "style_description": (
            "Caravaggio-intense spotlighting, deep blacks with explosive warm highlights, theatrical gesture and "
            "expression, swirling drapery, rich crimson and gold against darkness"
        ),
        "notes": "Alexandria wildcard prompt. Baroque spotlighting with theatrical emotional force.",
        "tags": ["alexandria", "wildcard", "baroque-dramatic", "classical", "fine-art"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-art-nouveau-poster",
        "name": "Art Nouveau Poster",
        "style_label": "Art Nouveau illustration",
        "style_description": (
            "sinuous organic linework, flowing hair and fabric, jewel-tone flat colours with gold outlines, "
            "Mucha-inspired decorative elegance, nature-integrated composition"
        ),
        "notes": "Alexandria wildcard prompt. Art Nouveau elegance with flowing decorative rhythm.",
        "tags": ["alexandria", "wildcard", "art-nouveau-poster", "illustration", "graphic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-vintage-pulp-cover",
        "name": "Vintage Pulp Cover",
        "style_label": "1940s vintage pulp illustration",
        "style_description": (
            "saturated primary colours, high-contrast dramatic lighting, bold expressive faces, painterly gouache "
            "texture, action-forward composition with dynamic diagonals"
        ),
        "notes": "Alexandria wildcard prompt. Pulpy action illustration with bold mid-century energy.",
        "tags": ["alexandria", "wildcard", "vintage-pulp-cover", "illustration", "graphic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-woodcut-relief",
        "name": "Woodcut Relief Print",
        "style_label": "hand-carved woodcut relief print",
        "style_description": (
            "bold black lines on warm cream, hatched shadow textures, simplified dramatic forms, limited "
            "two-tone palette, Dürer-inspired precision with folk art warmth"
        ),
        "notes": "Alexandria wildcard prompt. Woodcut austerity with carved graphic punch.",
        "tags": ["alexandria", "wildcard", "woodcut-relief", "illustration", "graphic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-art-deco-glamour",
        "name": "Art Deco Glamour",
        "style_label": "Art Deco glamour illustration",
        "style_description": (
            "geometric symmetry, sleek metallic gold and silver accents, jade green and midnight black palette, "
            "elongated elegant figures, Chrysler Building-era luxury and angular precision"
        ),
        "notes": "Alexandria wildcard prompt. Art Deco luxury with angular metropolitan polish.",
        "tags": ["alexandria", "wildcard", "art-deco-glamour", "illustration", "graphic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-soviet-constructivist",
        "name": "Soviet Constructivist",
        "style_label": "Soviet Constructivist poster",
        "style_description": (
            "bold angular composition, red black cream and steel grey palette, photomontage-inspired layering, "
            "diagonal dynamic energy, heroic monumental scale"
        ),
        "notes": "Alexandria wildcard prompt. Constructivist urgency with bold political poster force.",
        "tags": ["alexandria", "wildcard", "soviet-constructivist", "illustration", "graphic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-ukiyo-e-woodblock",
        "name": "Ukiyo-e Woodblock",
        "style_label": "Japanese ukiyo-e woodblock print",
        "style_description": (
            "flat colour planes with precise black outlines, asymmetric composition, indigo and vermilion palette, "
            "stylized wave and cloud motifs, Hokusai-inspired naturalistic detail"
        ),
        "notes": "Alexandria wildcard prompt. Ukiyo-e clarity with strong asymmetric composition.",
        "tags": ["alexandria", "wildcard", "ukiyo-e-woodblock", "eastern", "cross-cultural"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-persian-miniature",
        "name": "Persian Miniature",
        "style_label": "Persian miniature painting",
        "style_description": (
            "bird's-eye multi-level perspective, jewel-bright lapis lazuli and emerald palette, intricate floral "
            "details, gold leaf accents, delicate figure rendering with expressive faces"
        ),
        "notes": "Alexandria wildcard prompt. Persian miniature luminosity with jewel-bright layered perspective.",
        "tags": ["alexandria", "wildcard", "persian-miniature", "eastern", "cross-cultural"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-chinese-ink-wash",
        "name": "Chinese Ink Wash",
        "style_label": "Chinese ink wash painting",
        "style_description": (
            "misty mountain atmosphere, graded ink tones from deep black to pale grey, negative space as a "
            "compositional element, bamboo-brush spontaneity, Song dynasty landscape grandeur"
        ),
        "notes": "Alexandria wildcard prompt. Ink-wash restraint with spacious atmospheric depth.",
        "tags": ["alexandria", "wildcard", "chinese-ink-wash", "eastern", "cross-cultural"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-ottoman-illumination",
        "name": "Ottoman Illumination",
        "style_label": "Ottoman illuminated manuscript",
        "style_description": (
            "turquoise and coral palette with gold filigree, tulip and carnation motifs, flat decorative "
            "perspective, intricate geometric borders, courtly mineral-pigment elegance"
        ),
        "notes": "Alexandria wildcard prompt. Ottoman courtly illumination with vibrant mineral ornament.",
        "tags": ["alexandria", "wildcard", "ottoman-illumination", "eastern", "cross-cultural"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-film-noir-shadows",
        "name": "Film Noir Shadows",
        "style_label": "film noir cinematic",
        "style_description": (
            "high-contrast black and white with selective warm amber highlights, venetian blind shadow patterns, "
            "rain-slicked surfaces, cigarette-smoke atmosphere, dramatic low-angle perspective"
        ),
        "notes": "Alexandria wildcard prompt. Noir contrast with smoky urban menace.",
        "tags": ["alexandria", "wildcard", "film-noir-shadows", "atmospheric", "moody"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-pre-raphaelite-dream",
        "name": "Pre-Raphaelite Dream",
        "style_label": "Pre-Raphaelite painting",
        "style_description": (
            "jewel-bright saturated colours, hyper-detailed botanical elements, flowing auburn hair and "
            "medieval-inspired drapery, Waterhouse-like romantic atmosphere"
        ),
        "notes": "Alexandria wildcard prompt. Pre-Raphaelite romanticism with lush botanical intensity.",
        "tags": ["alexandria", "wildcard", "pre-raphaelite-dream", "atmospheric", "moody"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-twilight-symbolism",
        "name": "Twilight Symbolism",
        "style_label": "Symbolist painting",
        "style_description": (
            "dreamlike twilight atmosphere, deep purple and midnight blue palette with phosphorescent accents, "
            "enigmatic figure poses, Redon-inspired otherworldly luminescence, mythology blended with nature"
        ),
        "notes": "Alexandria wildcard prompt. Symbolist twilight with strange luminous mood.",
        "tags": ["alexandria", "wildcard", "twilight-symbolism", "atmospheric", "moody"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-northern-renaissance",
        "name": "Northern Renaissance",
        "style_label": "Northern Renaissance oil painting",
        "style_description": (
            "Van Eyck meticulous detail, cool silvery light through leaded glass windows, rich textile patterns, "
            "precise botanical accuracy, intimate domestic scale with symbolic objects"
        ),
        "notes": "Alexandria wildcard prompt. Northern Renaissance precision with intimate symbolic detail.",
        "tags": ["alexandria", "wildcard", "northern-renaissance", "atmospheric", "moody"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-william-morris-textile",
        "name": "William Morris Textile",
        "style_label": "William Morris Arts and Crafts",
        "style_description": (
            "intertwining vines and birds framing the scene, muted sage green and indigo palette, hand-printed "
            "woodblock texture, medieval-inspired naturalism, Kelmscott Press decorative richness"
        ),
        "notes": "Alexandria wildcard prompt. Arts and Crafts ornament with hand-printed texture.",
        "tags": ["alexandria", "wildcard", "william-morris-textile", "decorative", "ornamental"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-klimt-gold-leaf",
        "name": "Klimt Gold Leaf",
        "style_label": "Gustav Klimt decorative",
        "style_description": (
            "lavish gold leaf mosaic patterns integrated with realistic figures, Byzantine-inspired geometric "
            "abstraction, warm ochre and deep emerald palette, sensuous flowing forms"
        ),
        "notes": "Alexandria wildcard prompt. Klimt-like ornament with sensuous gold mosaic richness.",
        "tags": ["alexandria", "wildcard", "klimt-gold-leaf", "decorative", "ornamental"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-celtic-knotwork",
        "name": "Celtic Knotwork",
        "style_label": "Celtic illuminated manuscript",
        "style_description": (
            "interlaced knotwork framing the scene, Book of Kells-inspired zoomorphic details, deep forest green "
            "and burnished gold palette, spiralling decorative accents, insular art precision"
        ),
        "notes": "Alexandria wildcard prompt. Celtic manuscript knotwork with mythic illuminated precision.",
        "tags": ["alexandria", "wildcard", "celtic-knotwork", "decorative", "ornamental"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-botanical-plate",
        "name": "Botanical Plate",
        "style_label": "18th-century botanical illustration",
        "style_description": (
            "precise scientific observation, delicate hand-tinted watercolour washes on cream paper, naturalist "
            "field-drawing accuracy, muted sage and rose palette, Redouté-inspired elegance"
        ),
        "notes": "Alexandria wildcard prompt. Botanical illustration discipline with delicate naturalist grace.",
        "tags": ["alexandria", "wildcard", "botanical-plate", "cartographic", "scientific"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-antique-map",
        "name": "Antique Map",
        "style_label": "antique cartographic illustration",
        "style_description": (
            "aged parchment texture, hand-engraved linework, sepia and faded indigo palette, compass rose "
            "elements, sea monsters and ships in margins, Age-of-Exploration wonder"
        ),
        "notes": "Alexandria wildcard prompt. Antique map wonder with engraved exploratory drama.",
        "tags": ["alexandria", "wildcard", "antique-map", "cartographic", "scientific"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-maritime-chart",
        "name": "Maritime Chart",
        "style_label": "naval maritime illustration",
        "style_description": (
            "dramatic seascape composition, storm-grey and deep ocean-blue palette, copper-engraving linework, "
            "billowing sails and rigging detail, Turner-inspired atmospheric light on waves"
        ),
        "notes": "Alexandria wildcard prompt. Maritime chart drama with seafaring linework and storm light.",
        "tags": ["alexandria", "wildcard", "maritime-chart", "cartographic", "scientific"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-painterly-storybook",
        "name": "Painterly Storybook",
        "style_label": "hand-painted gouache storybook illustration",
        "style_description": (
            "visible gouache and oil brushwork, warm gold to navy palette, luminous atmospheric lighting, "
            "storybook warmth, softly blended painterly edges"
        ),
        "prompt_template": (
            "Book cover illustration only — no text, no title, no author name, no lettering of any kind. "
            "No border, no frame, no ornamental elements, no medallion, no decorative edges. This "
            "illustration MUST depict the following specific scene: {SCENE}. Every figure, object, and "
            "setting element in this scene must be clearly recognizable and faithful to the source material. "
            "Rendered as a HAND-PAINTED storybook illustration in gouache and oil painting style — "
            "MANDATORY visible brushwork texture throughout, soft blended edges with NO hard vector lines, "
            "NO photorealism, NO 3D rendering, NO digital sharpness. Atmospheric lighting with warm golden "
            "hour glow blending into cool deep blues. Color palette: deep midnight navy sky (#0a1628), warm "
            "wheat gold (#c5941a) and burnt amber (#cc7722) for foreground warmth, soft sage green (#6b8e5e) "
            "and muted olive for foliage, dusty rose (#c08b7a) for skin and warm accents. Clouds must have "
            "visible painterly brushstrokes with warm-lit edges. Landscape elements (fields, trees, "
            "buildings) rendered with the soft textural quality of traditional gouache painting — luminous, "
            "layered, slightly impressionistic depth. Overall mood: the warmth and wonder of a beautifully "
            "illustrated classic storybook. The mood is {MOOD}. Era reference: {ERA}. Full scene "
            "composition filling the entire canvas, no circular framing. Square format, high resolution, "
            "print-ready."
        ),
        "negative_prompt": (
            "no text, no letters, no words, no numbers, no medallion, no circular frame, no border, "
            "no photorealism, no 3D rendering, no vector art, no digital sharpness, no hard edges"
        ),
        "notes": "Alexandria wildcard prompt. Hand-painted storybook gouache with warm gold and navy brushwork.",
        "tags": ["painterly", "storybook", "gouache", "atmospheric"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-painterly-atmospheric",
        "name": "Painterly Atmospheric",
        "style_label": "hand-painted atmospheric concept-art illustration",
        "style_description": (
            "cinematic concept-art lighting, volumetric atmosphere, visible canvas grain and layered pigment, "
            "dramatic painterly depth, warm copper and gold against indigo shadows"
        ),
        "prompt_template": (
            "Book cover illustration only — no text, no title, no author name, no lettering of any kind. "
            "No border, no frame, no ornamental elements, no medallion, no decorative edges. This "
            "illustration MUST depict the following specific scene: {SCENE}. Every figure, object, and "
            "setting element in this scene must be clearly recognizable and faithful to the source material. "
            "Rendered as a HAND-PAINTED atmospheric illustration in the style of premium editorial concept art "
            "— MANDATORY soft painterly brushwork, rich tonal depth, dramatic light-to-shadow transitions, "
            "NO photorealism, NO 3D rendering, NO vector lines. Warm light sources scatter through volumetric "
            "atmosphere (clouds, mist, dust motes). Color palette: rich deep indigo night (#1a1a3e) and "
            "midnight teal (#0d2f4f) for shadows and sky, warm burnished gold (#d4a017) and copper (#b87333) "
            "for all highlights and light sources, deep forest green (#1a4a1a) and moss (#4a6a3a) for organic "
            "elements, warm ivory (#f5e6c8) for illuminated surfaces. Every surface must show visible painted "
            "texture — canvas grain, layered pigment, soft dry-brush details. Composition uses cinematic "
            "depth with a clear foreground subject, atmospheric middle ground, and painterly soft-focus "
            "background. The mood is {MOOD}. Era reference: {ERA}. Full scene composition filling the entire "
            "canvas, no circular framing. Square format, high resolution, print-ready."
        ),
        "negative_prompt": (
            "no text, no letters, no words, no numbers, no medallion, no circular frame, no border, "
            "no photorealism, no 3D rendering, no vector art, no digital sharpness, no hard edges"
        ),
        "notes": "Alexandria wildcard prompt. Atmospheric painterly concept art with dramatic volumetric light.",
        "tags": ["painterly", "atmospheric", "concept-art", "cinematic"],
        "category": "wildcard",
    },
    {
        "id": "alexandria-wildcard-naturalist-field-drawing",
        "name": "Naturalist Field Drawing",
        "style_label": "Victorian naturalist field drawing",
        "style_description": (
            "precise pencil and watercolour, expedition-journal authenticity, warm sepia and olive green palette, "
            "scientific curiosity with artistic sensitivity, Audubon-inspired detail"
        ),
        "notes": "Alexandria wildcard prompt. Expedition-journal naturalism with observational precision.",
        "tags": ["alexandria", "wildcard", "naturalist-field-drawing", "cartographic", "scientific"],
        "category": "wildcard",
    },
)

ALEXANDRIA_PROMPT_SPECS: tuple[dict[str, object], ...] = tuple(
    {
        "id": str(spec["id"]),
        "name": str(spec["name"]),
        "prompt_template": str(spec.get("prompt_template") or _scene_first_prompt(
            str(spec["style_label"]),
            str(spec["style_description"]),
            full_canvas=bool(spec.get("full_canvas")),
        )),
        "negative_prompt": str(spec.get("negative_prompt") or ALEXANDRIA_BASE_NEGATIVE_PROMPT),
        "notes": str(spec["notes"]),
        "tags": list(spec["tags"]),
        "category": str(spec["category"]),
    }
    for spec in ALEXANDRIA_PROMPT_CATALOG
)

ALEXANDRIA_SCENE_FIRST_PROMPT_TEMPLATES: dict[str, str] = {
    str(spec["id"]): str(spec["prompt_template"])
    for spec in ALEXANDRIA_PROMPT_SPECS
}


@dataclass(slots=True)
class StyleAnchor:
    """A reusable style component that can be mixed into prompts."""

    name: str
    description: str
    style_text: str
    tags: list[str]


@dataclass(slots=True)
class LibraryPrompt:
    """A saved prompt that worked well."""

    id: str
    name: str
    prompt_template: str
    style_anchors: list[str]
    negative_prompt: str
    source_book: str
    source_model: str
    quality_score: float
    saved_by: str
    created_at: str
    notes: str
    tags: list[str]
    category: str = "general"
    version: int = 1
    usage_count: int = 0
    win_count: int = 0
    last_used_at: str = ""
    updated_at: str = ""


class PromptLibrary:
    """Manages style anchors and saved prompts for single-cover iteration and bulk runs."""

    def __init__(self, library_path: Path):
        self.library_path = library_path
        self.library_path.parent.mkdir(parents=True, exist_ok=True)
        self._style_anchors: dict[str, StyleAnchor] = {}
        self._prompts: dict[str, LibraryPrompt] = {}
        self._versions: dict[str, list[dict[str, object]]] = {}
        self._load_or_seed()

    def get_style_anchors(self) -> list[StyleAnchor]:
        """Return all available style anchors."""
        return sorted(self._style_anchors.values(), key=lambda anchor: anchor.name)

    def save_prompt(self, prompt: LibraryPrompt) -> None:
        """Save a successful prompt to the library."""
        category = str(getattr(prompt, "category", "general") or "general")
        _validate_prompt_template(prompt.prompt_template, category=category)
        existing = self._prompts.get(prompt.id)
        normalized = LibraryPrompt(
            id=str(prompt.id),
            name=str(prompt.name or prompt.id),
            prompt_template=str(prompt.prompt_template),
            style_anchors=[str(anchor).strip() for anchor in list(prompt.style_anchors)],
            negative_prompt=str(prompt.negative_prompt or ""),
            source_book=str(prompt.source_book or ""),
            source_model=str(prompt.source_model or ""),
            quality_score=float(prompt.quality_score or 0.0),
            saved_by=str(prompt.saved_by or "auto"),
            created_at=str(prompt.created_at or _utc_now()),
            notes=str(prompt.notes or ""),
            tags=[str(tag).strip() for tag in list(prompt.tags)],
            category=category,
            version=max(1, int(getattr(prompt, "version", 1) or 1)),
            usage_count=max(0, int(getattr(prompt, "usage_count", 0) or 0)),
            win_count=max(0, int(getattr(prompt, "win_count", 0) or 0)),
            last_used_at=str(getattr(prompt, "last_used_at", "") or ""),
            updated_at=str(getattr(prompt, "updated_at", "") or _utc_now()),
        )
        if existing is not None:
            history = self._versions.setdefault(str(prompt.id), [])
            history.append(asdict(existing))
            normalized.version = max(1, int(existing.version or 1) + 1)
            if len(history) > 100:
                del history[:-100]
        self._prompts[prompt.id] = normalized
        self._persist()
        logger.info(
            "Saved prompt to library",
            extra={"prompt_id": prompt.id, "prompt_name": prompt.name, "score": prompt.quality_score},
        )

    def get_prompts(self, tags: list[str] | None = None) -> list[LibraryPrompt]:
        """Get prompts, optionally filtered by tags."""
        values = list(self._prompts.values())
        if tags:
            wanted = {tag.strip().lower() for tag in tags if tag.strip()}
            values = [
                prompt
                for prompt in values
                if wanted.intersection({tag.lower() for tag in prompt.tags})
                or wanted.intersection({anchor.lower() for anchor in prompt.style_anchors})
            ]
        return _sorted_prompts(values)

    def get_prompt(self, prompt_id: str) -> LibraryPrompt | None:
        """Return one prompt by id."""
        return self._prompts.get(str(prompt_id))

    def find_prompt_by_template_text(self, prompt_text: str) -> LibraryPrompt | None:
        """Return one prompt whose stored text matches after whitespace normalization."""
        target = _normalize_prompt_text(prompt_text)
        if not target:
            return None
        for prompt in self._prompts.values():
            if _normalize_prompt_text(prompt.prompt_template) == target:
                return prompt
        return None

    def get_versions(self, prompt_id: str) -> list[dict[str, object]]:
        """Return historical versions for one prompt id."""
        rows = self._versions.get(str(prompt_id), [])
        return list(rows)

    def update_prompt(self, prompt_id: str, **updates: object) -> LibraryPrompt:
        """Update one prompt and persist previous state to versions history."""
        token = str(prompt_id)
        current = self._prompts.get(token)
        if current is None:
            raise KeyError(prompt_id)

        history = self._versions.setdefault(token, [])
        history.append(asdict(current))
        if len(history) > 100:
            del history[:-100]

        name = str(updates.get("name", current.name) or current.name).strip() or current.name
        prompt_template = str(updates.get("prompt_template", current.prompt_template) or current.prompt_template).strip() or current.prompt_template
        target_category = str(updates.get("category", current.category) or current.category or "general")
        _validate_prompt_template(prompt_template, category=target_category)

        style_anchors = updates.get("style_anchors", current.style_anchors)
        tags = updates.get("tags", current.tags)
        updated = LibraryPrompt(
            id=current.id,
            name=name,
            prompt_template=prompt_template,
            style_anchors=[str(anchor).strip() for anchor in style_anchors] if isinstance(style_anchors, list) else list(current.style_anchors),
            negative_prompt=str(updates.get("negative_prompt", current.negative_prompt) or current.negative_prompt),
            source_book=str(updates.get("source_book", current.source_book) or current.source_book),
            source_model=str(updates.get("source_model", current.source_model) or current.source_model),
            quality_score=float(updates.get("quality_score", current.quality_score) or current.quality_score),
            saved_by=str(updates.get("saved_by", current.saved_by) or current.saved_by),
            created_at=current.created_at,
            notes=str(updates.get("notes", current.notes) or current.notes),
            tags=[str(tag).strip() for tag in tags] if isinstance(tags, list) else list(current.tags),
            category=target_category,
            version=max(1, int(current.version or 1) + 1),
            usage_count=max(0, int(updates.get("usage_count", current.usage_count) or current.usage_count)),
            win_count=max(0, int(updates.get("win_count", current.win_count) or current.win_count)),
            last_used_at=str(updates.get("last_used_at", current.last_used_at) or current.last_used_at),
            updated_at=_utc_now(),
        )
        self._prompts[token] = updated
        self._persist()
        return updated

    def delete_prompt(self, prompt_id: str) -> bool:
        """Delete one prompt by id."""
        token = str(prompt_id)
        if token not in self._prompts:
            return False
        self._prompts.pop(token, None)
        self._versions.pop(token, None)
        self._persist()
        return True

    def record_usage(self, prompt_id: str, *, won: bool = False) -> LibraryPrompt:
        """Increment usage and optional win counters for one prompt."""
        token = str(prompt_id)
        current = self._prompts.get(token)
        if current is None:
            raise KeyError(prompt_id)
        updated = LibraryPrompt(
            id=current.id,
            name=current.name,
            prompt_template=current.prompt_template,
            style_anchors=list(current.style_anchors),
            negative_prompt=current.negative_prompt,
            source_book=current.source_book,
            source_model=current.source_model,
            quality_score=current.quality_score,
            saved_by=current.saved_by,
            created_at=current.created_at,
            notes=current.notes,
            tags=list(current.tags),
            category=current.category,
            version=max(1, int(current.version or 1)),
            usage_count=max(0, int(current.usage_count or 0) + 1),
            win_count=max(0, int(current.win_count or 0) + (1 if won else 0)),
            last_used_at=_utc_now(),
            updated_at=_utc_now(),
        )
        self._prompts[token] = updated
        self._persist()
        return updated

    def search_prompts(
        self,
        query: str = "",
        tags: Sequence[str] | None = None,
        min_quality: float = 0.0,
    ) -> list[LibraryPrompt]:
        """Search prompts by text, tags, and minimum quality score."""
        query_tokens = {token for token in query.lower().split() if token}
        tag_tokens = {token.lower() for token in tags} if tags else set()

        def _matches(prompt: LibraryPrompt) -> bool:
            if prompt.quality_score < min_quality:
                return False

            blob = " ".join(
                [
                    prompt.name,
                    prompt.prompt_template,
                    prompt.notes,
                    " ".join(prompt.tags),
                    " ".join(prompt.style_anchors),
                ]
            ).lower()

            if query_tokens and not all(token in blob for token in query_tokens):
                return False

            if tag_tokens:
                prompt_tokens = {tag.lower() for tag in prompt.tags}.union(
                    {anchor.lower() for anchor in prompt.style_anchors}
                )
                if not tag_tokens.intersection(prompt_tokens):
                    return False
            return True

        return _sorted_prompts(prompt for prompt in self._prompts.values() if _matches(prompt))

    def build_prompt(self, book_title: str, style_anchors: list[str], custom_text: str = "") -> str:
        """Build a prompt from style anchors + book title + optional custom text."""
        selected = [self._style_anchors[name] for name in style_anchors if name in self._style_anchors]
        if not selected:
            raise ValueError("At least one valid style anchor is required to build a prompt.")

        style_text = ", ".join(anchor.style_text for anchor in selected)
        custom_part = f" {custom_text.strip()}" if custom_text.strip() else ""
        prompt = (
            f"Create a circular medallion illustration for \"{book_title}\" showing the most iconic "
            f"scene or symbolic moment from the story.{custom_part} {style_text}"
        )
        return " ".join(prompt.split())

    def get_best_prompts_for_bulk(self, top_n: int = 5) -> list[LibraryPrompt]:
        """Get top-N prompts by quality score for bulk processing."""
        ordered = sorted(self._prompts.values(), key=lambda prompt: prompt.quality_score, reverse=True)
        return ordered[: max(1, top_n)]

    def add_style_anchor(self, anchor: StyleAnchor) -> None:
        """Add or update a style anchor."""
        self._style_anchors[anchor.name] = anchor
        self._persist()
        logger.info("Upserted style anchor", extra={"anchor": anchor.name})

    def _load_or_seed(self) -> None:
        changed = False
        if self.library_path.exists():
            self._load()
            changed = self._ensure_alexandria_prompts() or changed
            if self._style_anchors and self._prompts:
                if changed:
                    self._persist()
                return

        anchors, prompts = self._seed_library()
        self._style_anchors = {anchor.name: anchor for anchor in anchors}
        self._prompts = {prompt.id: prompt for prompt in prompts}
        self._ensure_alexandria_prompts()
        self._persist()

    def _load(self) -> None:
        payload = safe_json.load_json(self.library_path, {})
        if not isinstance(payload, dict):
            payload = {}
        style_payload = payload.get("style_anchors", [])
        prompts_payload = payload.get("prompts", [])

        anchors: dict[str, StyleAnchor] = {}
        for item in style_payload if isinstance(style_payload, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            tags_raw = item.get("tags", [])
            tags = [str(tag).strip() for tag in tags_raw] if isinstance(tags_raw, list) else []
            anchors[name] = StyleAnchor(
                name=name,
                description=str(item.get("description", "")).strip(),
                style_text=str(item.get("style_text", "")).strip(),
                tags=[tag for tag in tags if tag],
            )
        self._style_anchors = anchors

        prompts: dict[str, LibraryPrompt] = {}
        for item in prompts_payload if isinstance(prompts_payload, list) else []:
            if not isinstance(item, dict):
                continue
            prompt_id = str(item.get("id", "")).strip()
            template = str(item.get("prompt_template", "")).strip()
            if not prompt_id or not template:
                continue
            style_raw = item.get("style_anchors", [])
            tags_raw = item.get("tags", [])
            prompts[prompt_id] = LibraryPrompt(
                id=prompt_id,
                name=str(item.get("name", "")).strip() or prompt_id,
                prompt_template=template,
                style_anchors=[str(anchor).strip() for anchor in style_raw] if isinstance(style_raw, list) else [],
                negative_prompt=str(item.get("negative_prompt", "")).strip(),
                source_book=str(item.get("source_book", "")).strip(),
                source_model=str(item.get("source_model", "")).strip(),
                quality_score=float(item.get("quality_score", 0.0) or 0.0),
                saved_by=str(item.get("saved_by", "auto") or "auto"),
                created_at=str(item.get("created_at", _utc_now()) or _utc_now()),
                notes=str(item.get("notes", "")).strip(),
                tags=[str(tag).strip() for tag in tags_raw] if isinstance(tags_raw, list) else [],
                category=str(item.get("category", "general") or "general"),
                version=max(1, int(item.get("version", 1) or 1)),
                usage_count=max(0, int(item.get("usage_count", 0) or 0)),
                win_count=max(0, int(item.get("win_count", 0) or 0)),
                last_used_at=str(item.get("last_used_at", "") or ""),
                updated_at=str(item.get("updated_at", "") or ""),
            )
        self._prompts = prompts

        versions_payload = payload.get("versions", {})
        versions: dict[str, list[dict[str, object]]] = {}
        if isinstance(versions_payload, dict):
            for key, rows in versions_payload.items():
                if not isinstance(rows, list):
                    continue
                cleaned = [dict(item) for item in rows if isinstance(item, dict)]
                if cleaned:
                    versions[str(key)] = cleaned[-100:]
        self._versions = versions

    def _persist(self) -> None:
        payload = {
            "version": 2,
            "updated_at": _utc_now(),
            "style_anchors": [asdict(anchor) for anchor in self.get_style_anchors()],
            "prompts": [
                asdict(prompt)
                for prompt in _sorted_prompts(self._prompts.values())
            ],
            "versions": {prompt_id: rows for prompt_id, rows in self._versions.items()},
        }
        safe_json.atomic_write_json(self.library_path, payload)
        logger.debug("Persisted prompt library", extra={"path": str(self.library_path), "anchors": len(self._style_anchors), "prompts": len(self._prompts)})

    def _ensure_alexandria_prompts(self) -> bool:
        changed = False
        existing_by_name = {str(prompt.name).strip().lower(): prompt for prompt in self._prompts.values()}
        for spec in ALEXANDRIA_PROMPT_SPECS:
            prompt_id = str(spec.get("id", "")).strip()
            name = str(spec.get("name", "")).strip()
            target_template = ALEXANDRIA_SCENE_FIRST_PROMPT_TEMPLATES.get(
                prompt_id,
                str(spec.get("prompt_template", "")).strip(),
            )
            target_negative_prompt = str(spec.get("negative_prompt") or ALEXANDRIA_SYSTEM_NEGATIVE_PROMPT).strip()
            target_notes = str(spec.get("notes", "")).strip()
            target_tags = list(spec.get("tags", [])) if isinstance(spec.get("tags", []), list) else ["alexandria"]
            target_category = str(spec.get("category", "builtin") or "builtin").strip()
            if not prompt_id or not name:
                continue
            current = self._prompts.get(prompt_id) or existing_by_name.get(name.lower())
            if current is not None:
                current_changed = False
                if str(current.name or "").strip() != name:
                    current.name = name
                    current_changed = True
                if str(current.prompt_template or "").strip() != target_template:
                    current.prompt_template = target_template
                    current_changed = True
                if str(current.notes or "").strip() != target_notes:
                    current.notes = target_notes
                    current_changed = True
                if list(current.tags or []) != target_tags:
                    current.tags = list(target_tags)
                    current_changed = True
                if str(current.category or "").strip() != target_category:
                    current.category = target_category
                    current_changed = True
                if str(current.negative_prompt or "").strip() != target_negative_prompt:
                    current.negative_prompt = target_negative_prompt
                    current_changed = True
                if str(current.source_book or "").strip() != "builtin":
                    current.source_book = "builtin"
                    current_changed = True
                if str(current.source_model or "").strip() != "openrouter/google/gemini-3-pro-image-preview":
                    current.source_model = "openrouter/google/gemini-3-pro-image-preview"
                    current_changed = True
                if current_changed:
                    current.updated_at = _utc_now()
                    self._prompts[current.id] = current
                    changed = True
                continue
            created_at = _utc_now()
            prompt = LibraryPrompt(
                id=prompt_id,
                name=name,
                prompt_template=target_template,
                style_anchors=[],
                negative_prompt=target_negative_prompt,
                source_book="builtin",
                source_model="openrouter/google/gemini-3-pro-image-preview",
                quality_score=1.0,
                saved_by="system",
                created_at=created_at,
                notes=target_notes,
                tags=target_tags,
                category=target_category,
                version=1,
                usage_count=0,
                win_count=0,
                last_used_at="",
                updated_at=created_at,
            )
            self._prompts[prompt.id] = prompt
            existing_by_name[name.lower()] = prompt
            changed = True
        return changed

    def _seed_library(self) -> tuple[list[StyleAnchor], list[LibraryPrompt]]:
        templates = safe_json.load_json(config.PROMPT_TEMPLATES_PATH, {})
        if not isinstance(templates, dict):
            templates = {}
        negative_prompt = templates.get("negative_prompt", "")

        style_groups = templates.get("style_groups", {})
        sketch_text = style_groups.get("sketch_style", {}).get("style_anchors", "")
        oil_text = style_groups.get("oil_painting_style", {}).get("style_anchors", "")
        alt_text = style_groups.get("alternative_style", {}).get("style_anchors", "")

        anchors = [
            StyleAnchor(
                name="warm_sepia_sketch",
                description="Hand-drawn 19th-century sketch aesthetic with sepia warmth.",
                style_text=sketch_text or "classical pen-and-ink sketch, sepia tones, crosshatching",
                tags=["sketch", "sepia", "classical"],
            ),
            StyleAnchor(
                name="engraving_detailed",
                description="Ultra-detailed copperplate engraving and etching line work.",
                style_text="copper plate engraving, fine line work, meticulous etching detail, circular vignette composition",
                tags=["engraving", "detailed", "linework"],
            ),
            StyleAnchor(
                name="dramatic_oil",
                description="Classical oil painting with dramatic light and depth.",
                style_text=oil_text or "classical oil painting, dramatic chiaroscuro, rich brushwork",
                tags=["oil", "dramatic", "classical"],
            ),
            StyleAnchor(
                name="gothic_moody",
                description="Dark romantic mood with atmospheric shadows.",
                style_text="gothic romantic atmosphere, moody shadows, dramatic rim lighting, painterly depth",
                tags=["gothic", "moody", "dramatic"],
            ),
            StyleAnchor(
                name="watercolor_soft",
                description="Soft watercolor washes with delicate transitions.",
                style_text="soft watercolor washes, delicate brush texture, gentle tonal transitions, classical composition",
                tags=["watercolor", "soft", "pastoral"],
            ),
            StyleAnchor(
                name="allegorical_symbolic",
                description="Symbolic visual storytelling with period-appropriate motifs.",
                style_text=alt_text or "period-appropriate artistic style, allegorical symbolism, hand-crafted aesthetic",
                tags=["symbolic", "allegory", "alternative"],
            ),
        ]

        starter_prompt_specs = [
            {
                "name": "Iconic Scene Sketch Baseline",
                "template": "Detailed pen-and-ink engraving of the most iconic scene from {title}, rendered as a circular vignette.",
                "anchors": ["warm_sepia_sketch", "engraving_detailed"],
                "model": "flux-2-pro",
                "score": 0.80,
                "tags": ["iconic", "sketch", "baseline"],
                "notes": "Strong baseline for classical literary titles.",
            },
            {
                "name": "Character Portrait Etching",
                "template": "Classical engraved portrait of the central character from {title}, with expressive posture and period costume.",
                "anchors": ["warm_sepia_sketch", "engraving_detailed"],
                "model": "gpt-image-1-medium",
                "score": 0.78,
                "tags": ["portrait", "character", "sketch"],
                "notes": "Works well when character focus is more recognizable than scene focus.",
            },
            {
                "name": "Setting-Led Sketch Landscape",
                "template": "19th-century style book illustration of the defining setting from {title}, emphasizing depth and architectural detail.",
                "anchors": ["warm_sepia_sketch", "engraving_detailed"],
                "model": "flux-2-schnell",
                "score": 0.73,
                "tags": ["setting", "landscape", "sketch"],
                "notes": "Fast and cheap exploration pattern for geography-heavy books.",
            },
            {
                "name": "Dramatic Chiaroscuro Moment",
                "template": "Masterpiece-style classical oil painting of the pivotal dramatic moment in {title}, with cinematic light contrast.",
                "anchors": ["dramatic_oil"],
                "model": "gpt-image-1-high",
                "score": 0.84,
                "tags": ["dramatic", "oil", "high_quality"],
                "notes": "High-end quality ceiling prompt for shortlist comparisons.",
            },
            {
                "name": "Gothic Tension Scene",
                "template": "Atmospheric gothic interpretation of the most psychologically intense moment from {title}.",
                "anchors": ["dramatic_oil", "gothic_moody"],
                "model": "imagen-4-ultra",
                "score": 0.81,
                "tags": ["gothic", "mood", "dramatic"],
                "notes": "Useful for darker classics and tragic narratives.",
            },
            {
                "name": "Soft Symbolic Watercolor",
                "template": "Symbolic watercolor composition for {title}, using allegorical objects to represent the book's core themes.",
                "anchors": ["watercolor_soft", "allegorical_symbolic"],
                "model": "imagen-4-fast",
                "score": 0.75,
                "tags": ["symbolic", "watercolor", "alternative"],
                "notes": "Good fallback when literal scenes feel crowded inside circular crops.",
            },
            {
                "name": "Baroque Allegory",
                "template": "Classical allegorical illustration for {title}, with period motifs and layered symbolic storytelling.",
                "anchors": ["allegorical_symbolic", "engraving_detailed"],
                "model": "nano-banana-pro",
                "score": 0.76,
                "tags": ["allegory", "symbolic", "baroque"],
                "notes": "Balances uniqueness with consistency for batch candidates.",
            },
            {
                "name": "Heroic Oil Tableau",
                "template": "Heroic classical oil tableau depicting the defining confrontation from {title}, with rich golden highlights.",
                "anchors": ["dramatic_oil"],
                "model": "flux-2-pro",
                "score": 0.79,
                "tags": ["heroic", "oil", "tableau"],
                "notes": "Performs well on action-driven works.",
            },
            {
                "name": "Etching with Narrative Depth",
                "template": "Dense copperplate-style etching of a narrative turning point from {title}, emphasizing layered storytelling details.",
                "anchors": ["engraving_detailed", "warm_sepia_sketch"],
                "model": "gpt-image-1-medium",
                "score": 0.82,
                "tags": ["etching", "detail", "narrative"],
                "notes": "Reliable prompt for rich compositions with many micro-details.",
            },
            {
                "name": "Painterly Pastoral Variant",
                "template": "Pastoral yet classical rendering of a key emotional scene from {title}, favoring gentle brushwork over hard outlines.",
                "anchors": ["watercolor_soft", "dramatic_oil"],
                "model": "imagen-4-fast",
                "score": 0.74,
                "tags": ["pastoral", "painterly", "variant"],
                "notes": "Adds tonal diversity while staying aligned with the cover aesthetic.",
            },
        ]

        prompts = [
            LibraryPrompt(
                id=str(uuid.uuid4()),
                name=item["name"],
                prompt_template=item["template"],
                style_anchors=list(item["anchors"]),
                negative_prompt=negative_prompt,
                source_book="Moby Dick",
                source_model=item["model"],
                quality_score=float(item["score"]),
                saved_by="auto",
                created_at=_utc_now(),
                notes=item["notes"],
                tags=list(item["tags"]),
            )
            for item in starter_prompt_specs
        ]

        return anchors, prompts



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_prompt_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _category_allows_plain_prompt(category: str) -> bool:
    return str(category or "").strip().lower() == "winner"


def _validate_prompt_template(template: str, *, category: str = "general") -> None:
    normalized = _normalize_prompt_text(template)
    if not normalized:
        raise ValueError("Prompt template must not be empty.")
    if _category_allows_plain_prompt(category):
        return
    if not _has_supported_placeholder(normalized):
        joined = ", ".join(SUPPORTED_REUSABLE_PLACEHOLDERS)
        raise ValueError(f"Prompt template must include at least one reusable placeholder ({joined}).")


def _has_supported_placeholder(template: str) -> bool:
    token = str(template or "")
    return any(marker in token for marker in SUPPORTED_REUSABLE_PLACEHOLDERS)


def _prompt_priority(prompt: LibraryPrompt) -> tuple[int, int, float, int, int, str]:
    tags = {str(tag).strip().lower() for tag in prompt.tags if str(tag).strip()}
    is_alexandria = 1 if "alexandria" in tags else 0
    is_builtin = 1 if str(prompt.category or "").strip().lower() == "builtin" else 0
    return (
        is_alexandria,
        is_builtin,
        float(prompt.quality_score or 0.0),
        int(prompt.win_count or 0),
        int(prompt.usage_count or 0),
        str(prompt.created_at or ""),
    )


def _sorted_prompts(prompts: Iterable[LibraryPrompt]) -> list[LibraryPrompt]:
    return sorted(prompts, key=_prompt_priority, reverse=True)


def load_default_prompt_library() -> PromptLibrary:
    """Load prompt library from default project location."""
    return PromptLibrary(config.PROMPT_LIBRARY_PATH)


def build_prompt_from_anchors(book_title: str, anchors: Iterable[str], custom_text: str = "") -> str:
    """Convenience wrapper for ad-hoc prompt creation."""
    library = load_default_prompt_library()
    return library.build_prompt(book_title=book_title, style_anchors=list(anchors), custom_text=custom_text)
