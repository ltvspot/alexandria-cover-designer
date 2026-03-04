const STYLE_POOL = [
  {
    id: 'sevastopol-conflict',
    label: 'Sevastopol / Dramatic Conflict',
    modifier: 'Render as a sweeping military oil painting inspired by Vasily Vereshchagin and the Crimean War panoramas. Towering smoke columns against a blood-orange sky, shattered stone walls catching the last golden light. Palette: deep crimson, burnt sienna, cannon-smoke grey, flashes of imperial gold on epaulettes and bayonets. Thick impasto brushwork on uniforms and rubble, softer glazes for distant fires. Dramatic diagonal composition — figures surge from lower-left toward an explosive upper-right horizon. Every surface glistens with rain or sweat; the atmosphere is heavy, humid, and heroic.',
  },
  {
    id: 'cossack-epic',
    label: 'Cossack / Epic Journey',
    modifier: 'Paint as a kinetic oil painting in the tradition of Ilya Repin\'s "Reply of the Zaporozhian Cossacks" and Franz Roubaud\'s battle panoramas. Galloping horses kicking up ochre dust against an endless steppe under a violet-streaked twilight. Palette: sunburnt ochre, Cossack-red sashes, tarnished silver sabres, deep indigo sky fading to amber at the horizon. Thick, energetic brushstrokes convey speed and fury — manes flying, cloaks billowing. Warm firelight illuminates weathered faces. The composition spirals outward from the center like a cavalry charge, filling every inch with movement and color.',
  },
  {
    id: 'golden-atmosphere',
    label: 'Golden Atmosphere',
    modifier: 'Paint in the pastoral tradition of the Barbizon school — Corot, Millet, Theodore Rousseau. A scene bathed in honeyed afternoon light filtering through ancient oaks. Palette: liquid gold, warm amber, deep forest green, touches of dusty rose in the sky. Soft, feathered brushwork with visible canvas texture. Figures are small against the vast, luminous landscape. Every leaf and blade of grass catches light differently — the entire scene glows from within as if lit by a divine lamp behind the clouds.',
  },
  {
    id: 'venetian-renaissance',
    label: 'Venetian Renaissance',
    modifier: 'Render in the sumptuous Venetian style of Titian, Giorgione, and Veronese. Rich sfumato modeling with warm flesh tones against deep emerald and ultramarine drapery. Palette: venetian red, lapis lazuli blue, cloth-of-gold yellow, alabaster white, deep bronze shadow. Luminous glazed layers that give skin an inner glow. Classical architecture deepens spatial depth — marble columns, brocade curtains, distant lagoon views. Every textile shimmers with painted thread detail. Compositions feel grand, balanced, and sensually alive.',
  },
  {
    id: 'dutch-golden-age',
    label: 'Dutch Golden Age',
    modifier: 'Paint in the intimate tradition of Vermeer, de Hooch, and Jan Steen. A single window casts a shaft of pearl-white light across the scene, illuminating every surface with photographic precision. Palette: warm candlelight amber, cool slate blue-grey, polished mahogany brown, cream linen, touches of lemon yellow and Delft blue in ceramics. Thick impasto on metallic highlights — pewter, brass, glass. Deep velvety shadows. The composition draws the eye through a doorway or window into layered depth. Every object tells a story.',
  },
  {
    id: 'dark-romantic-v2',
    label: 'Dark Romantic',
    modifier: 'Depict in the Dark Romantic tradition of Caspar David Friedrich and Gustave Dore. A moonlit or twilight scene with dramatic silvered edges. Palette: midnight indigo, icy blue-white, charcoal black, with sudden accents of blood-red berries or a single warm candle flame. Haunting, melancholic beauty. Mist curls around ancient trees and ruins. A solitary figure silhouetted against a vast, brooding sky with torn clouds revealing cold starlight. Deep atmosphere — you can almost feel the chill.',
  },
  {
    id: 'pre-raphaelite-v2',
    label: 'Pre-Raphaelite',
    modifier: 'Render in the lush, hyper-detailed Pre-Raphaelite style of Waterhouse, Rossetti, and Millais. Jewel-toned colors that sing: deep ruby garments, emerald moss-covered banks, sapphire water, and golden autumn leaves. Meticulous botanical detail — individual petals, veins on leaves, embroidery threads. Ethereal figures with flowing copper or raven hair, draped in medieval fabrics of damask and velvet. Rich symbolism: lilies for purity, roses for passion, willow for sorrow. Light enters from the upper left creating an otherworldly radiance.',
  },
  {
    id: 'art-nouveau-v2',
    label: 'Art Nouveau',
    modifier: 'Create in the expressive Art Nouveau color-and-line tradition of Alphonse Mucha and Eugene Grasset. Flowing organic line rhythm — sinuous vines, lily stems, and graceful movement in fabrics and hair. Palette: sage green, dusty rose, antique gold, deep teal, warm ivory. Flat color areas with fine painterly linework. Keep the composition scene-first and full-bleed with one dominant subject and atmospheric depth. Muted metallic accents throughout — gold leaf, bronze patina, copper highlights.',
  },
  {
    id: 'ukiyo-e-v2',
    label: 'Ukiyo-e Woodblock',
    modifier: 'Reimagine as a Japanese ukiyo-e woodblock print in the tradition of Hokusai and Hiroshige. Bold black outlines with flat areas of saturated color. Palette: deep indigo, vermillion red, pale ochre, celadon green, white rice-paper negative space. Fine parallel hatching for sky, waves, and rain. Dramatic spatial tension with exaggerated perspective. Stylized waves, windblown cherry blossoms, or towering mountains create dynamic movement. A striking interplay of pattern and void — every empty space is as deliberate as every filled one.',
  },
  {
    id: 'noir-v2',
    label: 'Film Noir',
    modifier: 'Depict as a high-contrast film noir composition straight from 1940s Hollywood. Palette: pure black, brilliant white, with ONE dramatic accent — a deep amber streetlight, a crimson lipstick, or a neon sign reflected in wet pavement. Hard-edged silhouettes, slashing Venetian blind shadows, extreme chiaroscuro. Figures caught in dramatic angles — shot from below or above. Rain-slicked streets reflect fragmented light. Cigarette smoke curls into geometric patterns. Moral ambiguity made visual.',
  },
  {
    id: 'botanical-v2',
    label: 'Botanical Engraving',
    modifier: 'Render as a vintage scientific illustration in the tradition of Maria Sibylla Merian and Pierre-Joseph Redoute. Exquisitely detailed: fine intaglio linework with hairline cross-hatching and stipple shading creating three-dimensional form. Hand-applied watercolor washes: soft leaf green, petal pink, butterfly-wing orange, lichen yellow. The subject is centered on a cream parchment ground with pencil construction lines faintly visible. Latin labels in copperplate script. Precision meets artistic beauty — every stamen, every wing scale rendered with love.',
  },
  {
    id: 'stained-glass-v2',
    label: 'Gothic Stained Glass',
    modifier: 'Create a luminous Gothic stained-glass color language translated into a painted narrative scene. Rich jewel-toned color blocks glow with inner light: ruby red, cobalt blue, emerald green, amber gold, amethyst purple. Strong lead-like contour lines guide form without creating borders. Light streams through mist and stone to create prismatic pools of color. Figures are stylized and iconic with flowing robes. The overall effect is transcendent and awe-inspiring, like sunrise light through cathedral glass.',
  },
  {
    id: 'impressionist-v2',
    label: 'Impressionist',
    modifier: 'Paint in the sun-drenched Impressionist style of Monet, Renoir, and Pissarro. Visible dappled brushstrokes that dissolve form into pure light and color. Palette: lavender shadow, rose-pink skin, sky blue reflected in water, warm peach sunlight, chartreuse new leaves. No hard edges — everything shimmers and vibrates. Emphasis on the play of natural light on water, foliage, or figures. A sense of a perfect afternoon frozen in time — warm, joyful, alive with color. Paint applied thickly so individual strokes catch their own light.',
  },
  {
    id: 'expressionist-v2',
    label: 'Expressionist',
    modifier: 'Render in the raw, emotionally charged style of Munch, Kirchner, and Emil Nolde. Colors are weapons: acid yellow, blood orange, electric blue, toxic green — applied in thick, agitated brushstrokes that seem to vibrate with anxiety. Warped perspectives and exaggerated proportions. Faces are masks of emotion. The sky may swirl, buildings may lean, shadows may reach like grasping hands. Everything is psychologically charged. The palette should feel almost violent in its intensity — beauty through discomfort.',
  },
  {
    id: 'baroque-v2',
    label: 'Baroque Drama',
    modifier: 'Depict as a grand Baroque composition worthy of Rubens, Velazquez, or Artemisia Gentileschi. A single dramatic light source (upper left) carves figures from deep velvet darkness. Palette: crimson silk, liquid gold, ivory flesh, deep shadow approaching black. Dynamic diagonal composition — bodies twist, arms reach, fabric billows in invisible wind. Extreme physicality and emotion. Thick impasto on highlights, transparent glazes in shadows. Figures caught at the peak of action — the most dramatic possible moment.',
  },
  {
    id: 'watercolour-v2',
    label: 'Delicate Watercolour',
    modifier: 'Paint as a refined watercolour illustration evoking beloved vintage book editions. Translucent washes where colors bloom and bleed softly into one another. The white paper ground glows through every stroke. Palette: muted cerulean blue, sage green, warm grey, burnt sienna, with accents of violet and rose. Soft, fluid edges with no hard lines — everything dissolves at the margins. Fine pen linework adds delicate structure. The mood is intimate, gentle, and nostalgic — like discovering a treasured illustration in a grandmother\'s bookshelf.',
  },
  {
    id: 'symbolist-v2',
    label: 'Symbolist Dream',
    modifier: 'Create in the mystical Symbolist tradition of Gustave Moreau, Odilon Redon, and Fernand Khnopff. A dreamlike, otherworldly scene shimmering between reality and vision. Palette: deep purple, tarnished gold, midnight blue, absinthe green, with iridescent highlights that shift like oil on water. Soft, hazy edges where forms dissolve into mist. Figures and elements feel archetypal — the Sphinx, the Angel, the Tower, the Rose. Eyes that see beyond the visible world. Rich mystical symbolism layered into every element.',
  },
  {
    id: 'persian-miniature',
    label: 'Persian Miniature',
    modifier: 'Render in the exquisite tradition of Persian miniature painting — Reza Abbasi, Kamal ud-Din Behzad. Bird\'s-eye perspective with no single vanishing point; the scene unfolds across multiple spatial planes simultaneously. Palette: lapis lazuli blue, vermillion, leaf gold, turquoise, saffron yellow, rose pink. Ultra-fine brushwork: individual leaves on trees, patterns on textiles, and tiles on architecture. Figures are elegant with almond eyes and flowing garments. Use illuminated floral color harmonies and dense narrative detail across the full scene.',
  },
  {
    id: 'russian-realist-v2',
    label: 'Russian Realist',
    modifier: 'Paint in the tradition of the Peredvizhniki — Ilya Repin, Ivan Kramskoi, Vasily Surikov, Isaac Levitan. Dense atmospheric detail with muted earth tones that suddenly catch fire with patches of vivid color. Palette: ochre, raw umber, slate grey, with flashes of birch-white, blood-red, and the golden glow of icon lamps. Thick expressive brushwork that captures raw human emotion and the vastness of the Russian landscape. Faces are unflinchingly honest — every wrinkle, every tear, every defiant glance tells a story. Deep, humane, and monumental.',
  },
  {
    id: 'romantic-sublime',
    label: 'Romantic Sublime',
    modifier: 'Paint in the awe-inspiring style of Turner, John Martin, and Frederic Edwin Church. VAST landscapes that dwarf human figures — towering mountains, raging seas, volcanic skies. Palette: molten gold and amber sunsets, storm-purple clouds, electric white lightning, deep ocean teal, misty lavender distances. The sky takes up two-thirds of the composition and is the real subject. Light breaks through clouds in god-rays. The feeling is of standing at the edge of creation — sublime terror and beauty combined. Thick, energetic brushwork in the sky, finer detail in the landscape below.',
  },
];

function shuffle(items) {
  const arr = [...items];
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

window.StyleDiversifier = {
  STYLE_POOL,

  selectDiverseStyles(count = 1) {
    const n = Math.max(0, Number(count || 0));
    if (n === 0) return [];
    const out = [];
    while (out.length < n) {
      const shuffled = shuffle(STYLE_POOL);
      for (const style of shuffled) {
        out.push(style);
        if (out.length >= n) break;
      }
    }
    return out;
  },

  buildDiversifiedPrompt(title, author, style) {
    const styleModifier = style?.modifier || 'Classical illustration using ruby red, emerald green, cobalt blue, amber gold, and ivory highlights.';
    const canvasDirective = 'The final image must be a FULL rectangular canvas of solid painted scene — no circular boundaries, no vignette edges, no decorative rings. Think of this as a square painting that will later be cropped into a circle, NOT as a circular medallion with its own frame.';
    return [
      `Create a breathtaking, richly colored illustration for the classic book "${title}" by ${author}.`,
      'Identify the single most iconic, dramatic, and visually striking scene from this specific story — the moment readers remember most vividly.',
      'No border, no frame, no decorative edge.',
      'Depict that scene as a luminous full-bleed narrative illustration for a luxury leather-bound edition.',
      'Adapt all motifs, costumes, architecture, and symbols strictly to this specific book; avoid cross-book visual clichés.',
      'Fill the entire rectangular composition with rich detail and vivid color — no empty space, no plain backgrounds.',
      'The artwork must feel like a museum-quality painting that captures the emotional heart of the story.',
      styleModifier,
      'CRITICAL COMPOSITION RULES: Keep one dominant focal subject and edge-to-edge scene detail.',
      'NO filigree, NO scrollwork, NO arabesques, NO ornamental curls, NO decorative flourishes, NO black ornamental silhouettes.',
      'NO text, NO letters, NO words anywhere in the image.',
      'The scene must be COLORFUL and DETAILED — avoid monochrome, avoid sparse compositions.',
      'Keep one dominant focal subject, layered depth, dense detail.',
      canvasDirective,
    ].join(' ');
  },
};
