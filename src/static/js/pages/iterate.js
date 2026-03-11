window.Pages = window.Pages || {};

let _selectedBookId = null;
let _unsubscribe = null;
let _selectedModelIds = new Set();
let _defaultModelId = null;
let _lastVisibleModelIds = [];
let _defaultSelectedModelIds = [];
let _variantPromptPlan = [];
let _activeVariantPrompt = 1;
const DEFAULT_VARIANT_COUNT = 4;
const AUTO_ROTATE_PROMPT_OPTION_LABEL = 'Auto-Rotate (Recommended)';
const AUTO_ROTATE_PROMPT_INFO = 'Automatically varies artistic styles and scenes across your covers.';
const PREFERRED_DEFAULT_MODELS = [
  'openrouter/google/gemini-3-pro-image-preview',
  'nano-banana-pro',
  'google/gemini-3-pro-image-preview',
];
const RECOMMENDED_PINNED_MODEL_IDS = [
  'openrouter/google/gemini-3-pro-image-preview',
  'google/gemini-3-pro-image-preview',
  'google/gemini-2.5-flash-image',
  'openrouter/google/gemini-2.5-flash-image',
];
const NANO_BANANA_MODEL_IDS = new Set([
  'openrouter/google/gemini-3-pro-image-preview',
  'nano-banana-pro',
]);
const GEMINI_FLASH_DIRECT_MODEL_IDS = new Set([
  'google/gemini-2.5-flash-image',
  'google/gemini-3-pro-image-preview',
]);
const GENERIC_CONTENT_MARKERS = [
  'iconic turning point',
  'central protagonist',
  'atmospheric setting moment',
  'defining confrontation involving',
  'historically grounded era',
  'circular medallion-ready',
  'pivotal narrative tableau',
  'period-appropriate settings',
  'narrative spaces associated with',
  'symbolic object tied to',
  'dramatic light and weather matching',
  'classical dramatic tension',
  'narrative consequence',
  'literary depth',
  'story-specific props and objects',
  'architectural and environmental details from the book\'s world',
  'symbolic objects that reinforce the central conflict',
  'primary ally from the narrative',
  'major opposing force in the story',
  'supporting figure tied to the central conflict',
  '{title}',
  '{author}',
  '{scene}',
  '{mood}',
  '{era}',
  'supporting cast',
  'mentor/foil',
  'antagonistic force',
];
const ALEXANDRIA_BASE_PROMPT_IDS = {
  classicalDevotion: 'alexandria-base-classical-devotion',
  philosophicalGravitas: 'alexandria-base-philosophical-gravitas',
  gothicAtmosphere: 'alexandria-base-gothic-atmosphere',
  romanticRealism: 'alexandria-base-romantic-realism',
  esotericMysticism: 'alexandria-base-esoteric-mysticism',
};
const GENRE_PROMPT_MAP = {
  religious: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.classicalDevotion,
    wildcards: [
      'alexandria-wildcard-illuminated-manuscript',
      'alexandria-wildcard-celtic-knotwork',
      'alexandria-wildcard-temple-of-knowledge',
      'alexandria-wildcard-venetian-renaissance',
      'alexandria-wildcard-klimt-gold-leaf',
    ],
  },
  apocryphal: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.classicalDevotion,
    wildcards: [
      'alexandria-wildcard-illuminated-manuscript',
      'alexandria-wildcard-celtic-knotwork',
      'alexandria-wildcard-temple-of-knowledge',
      'alexandria-wildcard-persian-miniature',
      'alexandria-wildcard-klimt-gold-leaf',
    ],
  },
  biblical: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.classicalDevotion,
    wildcards: [
      'alexandria-wildcard-illuminated-manuscript',
      'alexandria-wildcard-celtic-knotwork',
      'alexandria-wildcard-temple-of-knowledge',
      'alexandria-wildcard-venetian-renaissance',
      'alexandria-wildcard-art-nouveau-poster',
    ],
  },
  philosophy: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-bauhaus-minimalism',
      'alexandria-wildcard-soviet-constructivist',
      'alexandria-wildcard-art-deco-glamour',
    ],
  },
  'self-help': {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-bauhaus-minimalism',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-art-deco-glamour',
      'alexandria-wildcard-impressionist-plein-air',
    ],
  },
  strategy: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-maritime-chart',
      'alexandria-wildcard-soviet-constructivist',
      'alexandria-wildcard-bauhaus-minimalism',
    ],
  },
  horror: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.gothicAtmosphere,
    wildcards: [
      'alexandria-wildcard-film-noir-shadows',
      'alexandria-wildcard-gothic-revival',
      'alexandria-wildcard-misty-romanticism',
      'alexandria-wildcard-pre-raphaelite-dream',
      'alexandria-wildcard-edo-meets-alexandria',
    ],
  },
  gothic: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.gothicAtmosphere,
    wildcards: [
      'alexandria-wildcard-film-noir-shadows',
      'alexandria-wildcard-gothic-revival',
      'alexandria-wildcard-misty-romanticism',
      'alexandria-wildcard-pre-raphaelite-dream',
      'alexandria-wildcard-woodcut-relief',
    ],
  },
  supernatural: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.gothicAtmosphere,
    wildcards: [
      'alexandria-wildcard-film-noir-shadows',
      'alexandria-wildcard-gothic-revival',
      'alexandria-wildcard-misty-romanticism',
      'alexandria-wildcard-pre-raphaelite-dream',
      'alexandria-wildcard-klimt-gold-leaf',
    ],
  },
  literature: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-pre-raphaelite-garden',
      'alexandria-wildcard-impressionist-plein-air',
      'alexandria-wildcard-romantic-landscape',
      'alexandria-wildcard-art-nouveau-poster',
      'alexandria-wildcard-pre-raphaelite-dream',
    ],
  },
  novels: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-pre-raphaelite-garden',
      'alexandria-wildcard-impressionist-plein-air',
      'alexandria-wildcard-romantic-landscape',
      'alexandria-wildcard-dutch-golden-age',
      'alexandria-wildcard-art-nouveau-poster',
    ],
  },
  drama: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-venetian-renaissance',
      'alexandria-wildcard-baroque-chiaroscuro',
      'alexandria-wildcard-pre-raphaelite-dream',
      'alexandria-wildcard-edo-meets-alexandria',
      'alexandria-wildcard-romantic-landscape',
    ],
  },
  poetry: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-klimt-gold-leaf',
      'alexandria-wildcard-romantic-landscape',
      'alexandria-wildcard-pre-raphaelite-dream',
      'alexandria-wildcard-chinese-ink-wash',
      'alexandria-wildcard-impressionist-plein-air',
    ],
  },
  romance: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-pre-raphaelite-dream',
      'alexandria-wildcard-impressionist-plein-air',
      'alexandria-wildcard-art-nouveau-poster',
      'alexandria-wildcard-klimt-gold-leaf',
      'alexandria-wildcard-romantic-landscape',
    ],
  },
  adventure: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-pre-raphaelite-garden',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-maritime-chart',
      'alexandria-wildcard-vintage-pulp-cover',
      'alexandria-wildcard-edo-meets-alexandria',
    ],
  },
  exploration: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-maritime-chart',
      'alexandria-wildcard-pre-raphaelite-garden',
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-vintage-pulp-cover',
    ],
  },
  mythology: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.esotericMysticism,
    wildcards: [
      'alexandria-wildcard-temple-of-knowledge',
      'alexandria-wildcard-persian-miniature',
      'alexandria-wildcard-mughal-court-painting',
      'alexandria-wildcard-klimt-gold-leaf',
      'alexandria-wildcard-venetian-renaissance',
    ],
  },
  occult: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.esotericMysticism,
    wildcards: [
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-temple-of-knowledge',
      'alexandria-wildcard-klimt-gold-leaf',
      'alexandria-wildcard-persian-miniature',
      'alexandria-wildcard-mughal-court-painting',
    ],
  },
  mystical: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.esotericMysticism,
    wildcards: [
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-temple-of-knowledge',
      'alexandria-wildcard-klimt-gold-leaf',
      'alexandria-wildcard-persian-miniature',
      'alexandria-wildcard-chinese-ink-wash',
    ],
  },
  esoteric: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.esotericMysticism,
    wildcards: [
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-temple-of-knowledge',
      'alexandria-wildcard-klimt-gold-leaf',
      'alexandria-wildcard-persian-miniature',
      'alexandria-wildcard-art-deco-glamour',
    ],
  },
  history: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [
      'alexandria-wildcard-venetian-renaissance',
      'alexandria-wildcard-dutch-golden-age',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-naturalist-field-study',
      'alexandria-wildcard-scientific-diagram',
    ],
  },
  science: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-scientific-diagram',
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-naturalist-field-study',
      'alexandria-wildcard-botanical-plate',
      'alexandria-wildcard-antique-map-illustration',
    ],
  },
  war: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-baroque-chiaroscuro',
      'alexandria-wildcard-soviet-constructivist',
      'alexandria-wildcard-vintage-pulp-cover',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-woodcut-relief',
    ],
  },
  political: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-soviet-constructivist',
      'alexandria-wildcard-bauhaus-minimalism',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-scientific-diagram',
      'alexandria-wildcard-dutch-golden-age',
    ],
  },
  collections: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-dutch-golden-age',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-botanical-plate',
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-bauhaus-minimalism',
    ],
  },
  anthologies: {
    base: ALEXANDRIA_BASE_PROMPT_IDS.philosophicalGravitas,
    wildcards: [
      'alexandria-wildcard-dutch-golden-age',
      'alexandria-wildcard-antique-map-illustration',
      'alexandria-wildcard-botanical-plate',
      'alexandria-wildcard-celestial-cartography',
      'alexandria-wildcard-bauhaus-minimalism',
    ],
  },
};
const GENRE_PROMPT_ALIASES = {
  'literary-fiction': 'literature',
  'classic-literature': 'literature',
  literary: 'literature',
  fiction: 'literature',
  novel: 'novels',
  romance: 'romance',
  romantic: 'romance',
  poetry: 'poetry',
  poem: 'poetry',
  collection: 'collections',
  anthology: 'anthologies',
  religion: 'religious',
  sacred: 'religious',
  gnostic: 'apocryphal',
  'biblical-studies': 'biblical',
  spirituality: 'mystical',
  mysticism: 'mystical',
  supernaturalism: 'supernatural',
  adventure: 'adventure',
  exploration: 'exploration',
  history: 'history',
  historical: 'history',
  science: 'science',
  scientific: 'science',
  war: 'war',
  warfare: 'war',
  military: 'war',
  politics: 'political',
  political: 'political',
  government: 'political',
  myth: 'mythology',
  mythology: 'mythology',
  occultism: 'occult',
};

function modelIdToLabel(modelId) {
  const model = OpenRouter.MODELS.find((m) => m.id === modelId);
  return model?.label || modelId;
}

function statusTagClass(status) {
  if (status === 'completed') return 'tag-success';
  if (status === 'failed' || status === 'cancelled') return 'tag-failed';
  if (status === 'queued') return 'tag-queued';
  return 'tag-pending';
}

function qualityClass(score) {
  if (score >= 0.75) return 'high';
  if (score >= 0.5) return 'medium';
  return 'low';
}

function fallbackCardText(status) {
  if (status === 'queued') return 'Queued';
  if (status === 'generating' || status === 'retrying') return 'Generating...';
  if (status === 'downloading_cover') return 'Downloading cover...';
  if (status === 'scoring') return 'Scoring...';
  if (status === 'compositing') return 'Compositing...';
  if (status === 'failed') return 'Generation failed';
  if (status === 'cancelled') return 'Cancelled';
  return 'No preview yet';
}

function isRenderableImageSource(value) {
  if (!value) return false;
  if (typeof value === 'string') return Boolean(window.normalizeAssetUrl ? window.normalizeAssetUrl(value) : String(value).trim());
  if (value instanceof Blob) return !value.type || value.type.startsWith('image/');
  return true;
}

function decodeAttrToken(token) {
  try {
    return decodeURIComponent(String(token || ''));
  } catch {
    return '';
  }
}

function _thumbnailVersionToken(job) {
  if (!job || typeof job !== 'object') return String(Date.now());
  const candidate = String(
    job.completed_at
      || job.updated_at
      || job.created_at
      || job.timestamp
      || job.id
      || Date.now(),
  ).trim();
  return candidate || String(Date.now());
}

function _withVersionQuery(url, versionToken) {
  const raw = String(url || '').trim();
  if (!raw || !versionToken) return raw;
  if (raw.startsWith('blob:') || raw.startsWith('data:')) return raw;
  try {
    const absolute = new URL(raw, window.location.origin);
    absolute.searchParams.set('v', String(versionToken));
    if (/^https?:\/\//i.test(raw)) return absolute.toString();
    return `${absolute.pathname}${absolute.search}${absolute.hash}`;
  } catch {
    const join = raw.includes('?') ? '&' : '?';
    return `${raw}${join}v=${encodeURIComponent(String(versionToken))}`;
  }
}

function resolvePreviewSources(job, keyPrefix = 'display', preferRaw = false) {
  const sources = [];
  const seen = new Set();
  const pushSource = (value, suffix) => {
    if (!isRenderableImageSource(value)) return;
    let src = getBlobUrl(value, `${job.id}-${keyPrefix}-${suffix}`);
    if (typeof value === 'string') {
      src = _withVersionQuery(src, _thumbnailVersionToken(job));
    }
    if (!src || seen.has(src)) return;
    seen.add(src);
    sources.push(src);
    if (typeof value === 'string') {
      const normalized = src || '';
      const isDirectPath = normalized.startsWith('/') && !normalized.startsWith('//');
      if (isDirectPath && !normalized.startsWith('/api/thumbnail')) {
        const rel = normalized.replace(/^\/+/, '');
        const thumb = `/api/thumbnail?path=${encodeURIComponent(rel)}&size=large&v=${encodeURIComponent(_thumbnailVersionToken(job))}`;
        if (!seen.has(thumb)) {
          seen.add(thumb);
          sources.push(thumb);
        }
      }
    }
  };

  if (preferRaw) {
    pushSource(job.generated_image_blob, 'raw');
    pushSource(job.composited_image_blob, 'composite');
  } else {
    pushSource(job.composited_image_blob, 'composite');
    pushSource(job.generated_image_blob, 'raw');
  }

  try {
    const parsed = JSON.parse(String(job.results_json || '{}'));
    const row = parsed?.result || {};
    if (preferRaw) {
      pushSource(row.image_path || row.generated_path, 'row-raw');
      pushSource(row.composited_path, 'row-composite');
    } else {
      pushSource(row.composited_path, 'row-composite');
      pushSource(row.image_path || row.generated_path, 'row-raw');
    }
  } catch {
    // ignore malformed historical rows
  }

  return sources;
}

function resolveCompositePreviewSources(job, keyPrefix = 'display-composite') {
  const sources = [];
  const seen = new Set();
  const pushSource = (value, suffix) => {
    if (!isRenderableImageSource(value)) return;
    let src = getBlobUrl(value, `${job.id}-${keyPrefix}-${suffix}`);
    if (typeof value === 'string') {
      src = _withVersionQuery(src, _thumbnailVersionToken(job));
    }
    if (!src || seen.has(src)) return;
    seen.add(src);
    sources.push(src);
    if (typeof value === 'string') {
      const normalized = src || '';
      const isDirectPath = normalized.startsWith('/') && !normalized.startsWith('//');
      if (isDirectPath && !normalized.startsWith('/api/thumbnail')) {
        const rel = normalized.replace(/^\/+/, '');
        const thumb = `/api/thumbnail?path=${encodeURIComponent(rel)}&size=large&v=${encodeURIComponent(_thumbnailVersionToken(job))}`;
        if (!seen.has(thumb)) {
          seen.add(thumb);
          sources.push(thumb);
        }
      }
    }
  };
  pushSource(job.composited_image_blob, 'composite');
  try {
    const parsed = JSON.parse(String(job.results_json || '{}'));
    const row = parsed?.result || {};
    pushSource(row.composited_path, 'row-composite');
  } catch {
    // ignore malformed historical rows
  }
  return sources;
}

async function ensureJSZip() {
  if (window.JSZip) return window.JSZip;
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
    script.onload = () => resolve(window.JSZip);
    script.onerror = () => reject(new Error('Failed to load JSZip'));
    document.head.appendChild(script);
  });
}

function sanitizeDownloadName(value) {
  return String(value || '')
    .replace(/[\\/:*?"<>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function resolveBookMetadataForJob(job) {
  const bookId = Number(job?.book_id || 0);
  let book = DB.dbGet('books', bookId);
  if (!book) {
    book = DB.dbGetAll('books').find((row) => Number(row.id) === bookId) || null;
  }
  const title = sanitizeDownloadName(book?.title || `Book ${bookId || 'Unknown'}`);
  const author = sanitizeDownloadName(book?.author || 'Unknown');
  const number = sanitizeDownloadName(book?.number || job?.book_id || 'Unknown');
  // Use catalog file_base when present to mirror source cover file names exactly.
  const catalogBase = String(book?.file_base || '').trim();
  const baseName = catalogBase
    ? sanitizeDownloadName(catalogBase)
    : sanitizeDownloadName(`${title} — ${author}`);
  return { title, author, number, baseName };
}

function pickFullResolutionSource(job, keyPrefix, preferRaw = false) {
  const ordered = resolvePreviewSources(job, keyPrefix, preferRaw);
  if (!ordered.length) return '';
  const preferred = ordered.find((src) => {
    const token = String(src || '').trim().toLowerCase();
    return token && !token.startsWith('/api/thumbnail');
  });
  return preferred || ordered[0] || '';
}

async function fetchDownloadBlob(source) {
  if (!source) return null;
  if (typeof source === 'string' && source.startsWith('blob:')) return null;
  try {
    const response = await fetch(source, { cache: 'no-store' });
    if (!response.ok) return null;
    return await response.blob();
  } catch {
    return null;
  }
}

function _extensionFromPath(value) {
  try {
    const absolute = new URL(String(value || ''), window.location.origin);
    const path = String(absolute.pathname || '').trim().toLowerCase();
    const match = path.match(/\.([a-z0-9]{2,5})$/);
    return match ? match[1] : '';
  } catch {
    const token = String(value || '').trim().toLowerCase();
    const clean = token.split('?')[0].split('#')[0];
    const match = clean.match(/\.([a-z0-9]{2,5})$/);
    return match ? match[1] : '';
  }
}

function _extensionFromBlob(blob, fallback = 'jpg') {
  const mime = String(blob?.type || '').toLowerCase();
  if (mime.includes('png')) return 'png';
  if (mime.includes('webp')) return 'webp';
  if (mime.includes('jpeg') || mime.includes('jpg')) return 'jpg';
  if (mime.includes('pdf')) return 'pdf';
  if (mime.includes('postscript') || mime.includes('illustrator')) return 'ai';
  return String(fallback || 'jpg');
}

async function _extractVariantArchiveAssets({ bookId, variant, model }) {
  const book = Number(bookId || 0);
  const variantNumber = Number(variant || 0);
  const modelId = String(model || '').trim();
  if (book <= 0 || variantNumber <= 0 || !modelId) return {};
  try {
    const zipHref = `/api/variant-download?catalog=classics&book=${encodeURIComponent(book)}&variant=${encodeURIComponent(variantNumber)}&model=${encodeURIComponent(modelId)}`;
    const zipBlob = await fetchDownloadBlob(zipHref);
    if (!zipBlob) return {};
    const JSZip = await ensureJSZip();
    const archive = await JSZip.loadAsync(zipBlob);
    const files = Object.values(archive.files || {}).filter((file) => !file.dir);
    const pick = (predicate) => files.find(predicate) || null;
    const imagePattern = /\.(png|jpe?g|webp)$/i;
    const compositeFile = pick((file) => /composites\//i.test(file.name) && /\.jpe?g$/i.test(file.name));
    const generatedRawFile = pick((file) => /source_images\//i.test(file.name) && imagePattern.test(file.name));
    const sourceRawFile = pick((file) => /source_files\//i.test(file.name) && imagePattern.test(file.name));
    const pdfFile = pick((file) => /composites\//i.test(file.name) && /\.pdf$/i.test(file.name));
    const aiFile = pick((file) => /composites\//i.test(file.name) && /\.ai$/i.test(file.name));
    const out = {};
    if (compositeFile) out.compositeBlob = await compositeFile.async('blob');
    if (generatedRawFile) out.rawBlob = await generatedRawFile.async('blob');
    if (sourceRawFile) out.sourceBlob = await sourceRawFile.async('blob');
    if (pdfFile) out.pdfBlob = await pdfFile.async('blob');
    if (aiFile) out.aiBlob = await aiFile.async('blob');
    return out;
  } catch {
    return {};
  }
}

function resolveJobArtifactHref(job, keys = []) {
  const candidates = [];
  const append = (value) => {
    if (!value) return;
    const normalized = window.normalizeAssetUrl ? window.normalizeAssetUrl(value) : String(value || '').trim();
    if (normalized) candidates.push(normalized);
  };

  keys.forEach((key) => append(job?.[key]));
  try {
    const parsed = JSON.parse(String(job?.results_json || '{}'));
    const row = parsed?.result || {};
    keys.forEach((key) => append(row?.[key]));
  } catch {
    // ignore malformed historical rows
  }

  return candidates[0] || '';
}

function _bookEnrichment(book) {
  return (book && typeof book.enrichment === 'object' && book.enrichment) ? book.enrichment : {};
}

function _bookPromptContext(book) {
  return (book && typeof book.prompt_context === 'object' && book.prompt_context) ? book.prompt_context : {};
}

function _normalizePromptText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function _isGenericContent(value) {
  const text = _normalizePromptText(value);
  if (text.length < 4) return !/^[A-Z][a-z]{1,3}(?:\s+[A-Z][a-z]{1,3})*$/.test(text);
  const lower = text.toLowerCase();
  if (GENERIC_CONTENT_MARKERS.some((marker) => lower.includes(marker))) return true;
  if (/\b(main|central)\s+character\b/.test(lower)) return true;
  return text.length < 8 && text === lower;
}

function _dedupeNonGeneric(values = []) {
  const out = [];
  const seen = new Set();
  values.forEach((value) => {
    const text = _normalizePromptText(value);
    if (!text || _isGenericContent(text)) return;
    const key = text.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push(text);
  });
  return out;
}

function _fallbackSceneForBook(book) {
  const title = _normalizePromptText(book?.title || 'the book');
  const author = _normalizePromptText(book?.author || '');
  const protagonist = _normalizePromptText(defaultProtagonistForBook(book) || 'the central figures');
  const setting = _normalizePromptText(_bookPromptContext(book).setting || _bookEnrichment(book).setting_primary || book?.setting || defaultEraForBook(book));
  const fallbackSetting = setting || "the book's defining world";
  return `A decisive scene from "${title}"${author ? ` by ${author}` : ''} set in ${fallbackSetting}, focused on ${protagonist}.`;
}

function defaultProtagonistForBook(book) {
  const enrichment = _bookEnrichment(book);
  const context = _bookPromptContext(book);
  const keyCharacters = Array.isArray(enrichment.key_characters) ? enrichment.key_characters : [];
  const candidates = [
    context.protagonist,
    enrichment.protagonist,
    keyCharacters[0],
    book?.protagonist,
  ];
  const first = candidates.find((value) => {
    const text = _normalizePromptText(value);
    return text && !_isGenericContent(text);
  });
  return _normalizePromptText(first);
}

function buildScenePool(book) {
  const enrichment = _bookEnrichment(book);
  const context = _bookPromptContext(book);
  const iconicScenes = Array.isArray(enrichment.iconic_scenes) ? enrichment.iconic_scenes : [];
  const contextScenes = Array.isArray(context.scene_pool) ? context.scene_pool : [];
  const pool = _dedupeNonGeneric([
    ...contextScenes,
    book?.scene,
    enrichment.scene,
    ...iconicScenes,
    book?.description,
  ]);
  return pool.length ? pool : [_fallbackSceneForBook(book)];
}

function defaultSceneForBook(book) {
  const context = _bookPromptContext(book);
  const contextScene = _normalizePromptText(context.scene);
  if (contextScene && !_isGenericContent(contextScene)) return contextScene;
  return buildScenePool(book)[0] || _fallbackSceneForBook(book);
}

function defaultMoodForBook(book) {
  const enrichment = _bookEnrichment(book);
  const context = _bookPromptContext(book);
  const toneList = Array.isArray(enrichment.tones) ? enrichment.tones.filter((item) => !_isGenericContent(item)) : [];
  return _normalizePromptText(
    context.mood
    || enrichment.emotional_tone
    || enrichment.mood
    || toneList[0]
    || book?.mood
    || 'dramatic, literary, and historically grounded'
  );
}

function defaultEraForBook(book) {
  const enrichment = _bookEnrichment(book);
  const context = _bookPromptContext(book);
  if (!_isGenericContent(context.era)) return _normalizePromptText(context.era);
  if (Array.isArray(enrichment.era)) {
    const first = enrichment.era.find((item) => !_isGenericContent(item));
    return _normalizePromptText(first || '');
  }
  const era = _normalizePromptText(book?.era || enrichment.era || '');
  return _isGenericContent(era) ? '' : era;
}

function sceneForVariant(book, variant, explicitScene = '') {
  const chosen = _normalizePromptText(explicitScene);
  if (chosen && !_isGenericContent(chosen)) return chosen;
  const pool = buildScenePool(book);
  if (!pool.length) return _fallbackSceneForBook(book);
  const index = Math.max(0, Number(variant || 1) - 1) % pool.length;
  return pool[index] || pool[0];
}

function cleanupResolvedPrompt(promptText) {
  return String(promptText || '')
    .replace(/Era reference:\s*(?:\.|,|;|:)?/gi, '')
    .replace(/\s+([,.;:!?])/g, '$1')
    .replace(/([.?!])\s*\./g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function applyPromptPlaceholders(promptText, book, sceneOverride, moodOverride, eraOverride) {
  const baseScene = sceneForVariant(book, 1, sceneOverride || defaultSceneForBook(book));
  const protagonist = defaultProtagonistForBook(book);
  const scene = protagonist && !baseScene.toLowerCase().includes(protagonist.toLowerCase())
    ? `${baseScene}. ${protagonist.toLowerCase().includes(' and ') ? 'The main characters shown are' : 'The main character shown is'} ${protagonist}.`
    : baseScene;
  const mood = _normalizePromptText(moodOverride || defaultMoodForBook(book));
  const era = _normalizePromptText(eraOverride || defaultEraForBook(book));
  const replaced = String(promptText || '')
    .replaceAll('{title}', String(book?.title || ''))
    .replaceAll('{author}', String(book?.author || ''))
    .replaceAll('{TITLE}', String(book?.title || ''))
    .replaceAll('{AUTHOR}', String(book?.author || ''))
    .replaceAll('{SUBTITLE}', String(book?.subtitle || ''))
    .replaceAll('{SCENE}', scene)
    .replaceAll('{MOOD}', mood)
    .replaceAll('{ERA}', era);
  return cleanupResolvedPrompt(replaced);
}

function resolvePrompt(templateObj, book, customPrompt, sceneVal, moodVal, eraVal) {
  const custom = String(customPrompt || '').trim();
  if (custom) {
    return applyPromptPlaceholders(custom, book, sceneVal, moodVal, eraVal).trim();
  }
  const base = templateObj?.prompt_template || `Create a colorful circular medallion illustration for "{title}" by {author}.`;
  const resolved = applyPromptPlaceholders(base, book, sceneVal, moodVal, eraVal);
  if (!resolved.toLowerCase().includes('no text')) {
    return `${resolved} No text, no letters, no words, no numbers.`.trim();
  }
  return resolved.trim();
}

function validatePromptBeforeGeneration({ prompt, book }) {
  const text = _normalizePromptText(prompt);
  const errors = [];
  const warnings = [];
  const expectedScene = defaultSceneForBook(book);
  if (/{SCENE}|{MOOD}|{ERA}|{title}|{author}|{TITLE}|{AUTHOR}/.test(text)) {
    errors.push('Prompt still contains unresolved placeholders.');
  }
  if (_isGenericContent(text.slice(0, 320))) {
    errors.push('Prompt still contains generic content in the first 320 characters.');
  }
  const sceneFragment = _normalizePromptText(expectedScene).slice(0, 48).toLowerCase();
  const scenePosition = sceneFragment ? text.toLowerCase().indexOf(sceneFragment) : -1;
  if (sceneFragment && scenePosition > 250) {
    warnings.push(`Scene-specific content starts too late (${scenePosition} chars).`);
  }
  if (!text.toLowerCase().includes('no text')) {
    warnings.push('Prompt is missing the anti-text guardrail.');
  }
  return {
    ok: errors.length === 0,
    errors,
    warnings,
    scenePosition,
  };
}

function buildGenerationJobPrompt({ book, templateObj, promptId, customPrompt, sceneVal, moodVal, eraVal, style }) {
  const trimmedPromptId = String(promptId || '').trim();
  const trimmedCustomPrompt = String(customPrompt || '').trim();
  const templateText = String(templateObj?.prompt_template || '').trim();
  const promptSource = trimmedCustomPrompt && trimmedCustomPrompt !== templateText
    ? 'custom'
    : (trimmedPromptId ? 'template' : (trimmedCustomPrompt ? 'custom' : 'template'));
  const customPromptOverride = promptSource === 'custom' ? customPrompt : '';
  const basePrompt = resolvePrompt(templateObj, book, customPromptOverride, sceneVal, moodVal, eraVal);
  const usesStandalonePrompt = Boolean(trimmedPromptId || trimmedCustomPrompt);
  const prompt = usesStandalonePrompt
    ? basePrompt
    : `${StyleDiversifier.buildDiversifiedPrompt(book.title, book.author, style)} ${basePrompt}`.trim();
  const templateName = String(templateObj?.name || '').trim();
  const styleLabel = usesStandalonePrompt
    ? (
      (templateName && promptSource === 'custom' && trimmedPromptId)
        ? `${templateName} (edited)`
        : (templateName || (promptSource === 'custom' ? 'Custom prompt' : 'Precomposed prompt'))
    )
    : (style?.label || 'Default');
  return {
    prompt,
    promptSource,
    backendPromptSource: 'custom',
    composePrompt: false,
    preservePromptText: usesStandalonePrompt,
    libraryPromptId: trimmedPromptId,
    styleId: usesStandalonePrompt ? 'none' : (style?.id || 'none'),
    styleLabel,
  };
}

function formatPromptPreview(entries) {
  return (Array.isArray(entries) ? entries : []).map((entry) => {
    const variant = Number(entry?.variant || 0) || 1;
    const prompt = String(entry?.promptPayload?.prompt || '').trim();
    return `Variant ${variant}\n${prompt}`;
  }).join('\n\n');
}

function compactStyleLabel(value) {
  return String(value || '')
    .replace(/^(?:BASE|WILDCARD)\s+\d+\s+[—-]\s+/i, '')
    .trim() || 'Style';
}

function compactSceneLabel(value, maxLength = 72) {
  const normalized = String(value || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  const shortened = normalized
    .replace(/^the illustration must depict:\s*/i, '')
    .replace(/\.\s*The main character shown is .*$/i, '')
    .replace(/\.\s*The main characters shown are .*$/i, '')
    .trim();
  if (shortened.length <= maxLength) return shortened;
  return `${shortened.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function formatVariantSummaryLines(entries) {
  return (Array.isArray(entries) ? entries : []).map((entry) => {
    const styleLabel = compactStyleLabel(
      entry?.assignedTemplate?.name
      || entry?.promptPayload?.styleLabel
      || 'Style',
    );
    const sceneLabel = compactSceneLabel(entry?.assignedScene || entry?.scene_description || '');
    return `Variant ${Number(entry?.variant || 0) || 1}: ${styleLabel}${sceneLabel ? ` — ${sceneLabel}` : ''}`.trim();
  });
}

function buildVariantPromptPayloads({
  book,
  variantCount,
  promptId = '',
  customPrompt = '',
  sceneVal = '',
  moodVal = '',
  eraVal = '',
  variantPlan = null,
  referenceDate = new Date(),
}) {
  const total = Math.max(1, Number(variantCount || DEFAULT_VARIANT_COUNT));
  const assignments = buildVariantPromptAssignments({ book, variantCount: total, referenceDate });
  const previousByVariant = new Map(
    (Array.isArray(variantPlan) ? variantPlan : [])
      .map((item) => [Number(item?.variant || 0), item])
      .filter(([variant]) => variant > 0)
  );
  const styles = typeof StyleDiversifier?.selectDiverseStyles === 'function'
    ? StyleDiversifier.selectDiverseStyles(total)
    : [];
  const entries = [];
  const missingPromptIds = [];

  assignments.forEach((assignment, index) => {
    const variant = Number(assignment?.variant || 0) || (index + 1);
    const planItem = previousByVariant.get(variant) || null;
    const assignedPromptId = String(planItem?.promptId || promptId || assignment?.promptId || '').trim();
    const assignedTemplate = assignedPromptId ? DB.dbGet('prompts', assignedPromptId) : null;
    if (assignedPromptId && !assignedTemplate) missingPromptIds.push(assignedPromptId);
    const assignedSceneInput = String(planItem?.sceneVal || sceneVal || '').trim();
    const assignedScene = sceneForVariant(book, variant, assignedSceneInput);
    const assignedMood = String(planItem?.moodVal || moodVal || '').trim() || defaultMoodForBook(book);
    const assignedEra = String(planItem?.eraVal || eraVal || '').trim() || defaultEraForBook(book);
    const assignedCustomPrompt = String(planItem?.customPrompt || customPrompt || '').trim();
    const promptPayload = buildGenerationJobPrompt({
      book,
      templateObj: assignedTemplate,
      promptId: assignedPromptId,
      customPrompt: assignedCustomPrompt,
      sceneVal: assignedScene,
      moodVal: assignedMood,
      eraVal: assignedEra,
      style: styles[index % Math.max(1, styles.length)] || { id: 'none', label: 'Default' },
    });
    entries.push({
      variant,
      assignedPromptId,
      assignedTemplate,
      assignedScene,
      assignedMood,
      assignedEra,
      promptPayload,
      scene_description: assignedScene,
      mood: assignedMood,
      era: assignedEra,
    });
  });

  return {
    entries,
    missingPromptIds: Array.from(new Set(missingPromptIds)),
  };
}

window.__ITERATE_TEST_HOOKS__ = window.__ITERATE_TEST_HOOKS__ || {};
window.__ITERATE_TEST_HOOKS__.buildGenerationJobPrompt = buildGenerationJobPrompt;
window.__ITERATE_TEST_HOOKS__.buildVariantPromptPayloads = (payload) => buildVariantPromptPayloads(payload);
window.__ITERATE_TEST_HOOKS__.formatVariantSummaryLines = ({ entries }) => formatVariantSummaryLines(entries);
window.__ITERATE_TEST_HOOKS__.iterateUiDefaults = () => ({
  defaultVariantCount: DEFAULT_VARIANT_COUNT,
  autoRotateLabel: AUTO_ROTATE_PROMPT_OPTION_LABEL,
});
window.__ITERATE_TEST_HOOKS__.buildScenePool = buildScenePool;
window.__ITERATE_TEST_HOOKS__.defaultSceneForBook = defaultSceneForBook;
window.__ITERATE_TEST_HOOKS__.applyPromptPlaceholders = applyPromptPlaceholders;
window.__ITERATE_TEST_HOOKS__.validatePromptBeforeGeneration = validatePromptBeforeGeneration;
window.__ITERATE_TEST_HOOKS__.isGenericContent = _isGenericContent;

function sortPromptsForUI(prompts) {
  return [...(Array.isArray(prompts) ? prompts : [])].sort((left, right) => {
    const leftTags = new Set((Array.isArray(left?.tags) ? left.tags : []).map((tag) => String(tag || '').trim().toLowerCase()).filter(Boolean));
    const rightTags = new Set((Array.isArray(right?.tags) ? right.tags : []).map((tag) => String(tag || '').trim().toLowerCase()).filter(Boolean));
    const leftAlex = leftTags.has('alexandria') ? 1 : 0;
    const rightAlex = rightTags.has('alexandria') ? 1 : 0;
    if (leftAlex !== rightAlex) return rightAlex - leftAlex;
    const leftBuiltin = String(left?.category || '').trim().toLowerCase() === 'builtin' ? 1 : 0;
    const rightBuiltin = String(right?.category || '').trim().toLowerCase() === 'builtin' ? 1 : 0;
    if (leftBuiltin !== rightBuiltin) return rightBuiltin - leftBuiltin;
    const leftQuality = Number(left?.quality_score || 0);
    const rightQuality = Number(right?.quality_score || 0);
    if (leftQuality !== rightQuality) return rightQuality - leftQuality;
    return String(left?.name || '').localeCompare(String(right?.name || ''));
  });
}

function isAlexandriaTemplate(templateObj, customPrompt = '') {
  const templateText = String(templateObj?.prompt_template || customPrompt || '').trim();
  return templateText.includes('{SCENE}');
}

function normalizedPromptName(value) {
  return String(value || '').trim().toLowerCase();
}

function findPromptById(promptId) {
  const token = _normalizePromptText(promptId);
  if (!token) return null;
  return sortPromptsForUI(DB.dbGetAll('prompts')).find((prompt) => _normalizePromptText(prompt?.id) === token) || null;
}

function genrePromptConfigForBook(book) {
  const enrichment = _bookEnrichment(book);
  const rawTokens = [
    String(book?.genre || ''),
    String(enrichment.genre || ''),
    String(_bookPromptContext(book).genre || ''),
    ...(Array.isArray(enrichment.tags) ? enrichment.tags.map((item) => String(item || '')) : []),
  ]
    .flatMap((value) => String(value || '').toLowerCase().split(/[^a-z0-9_+-]+/))
    .map((value) => value.replaceAll('_', '-').trim())
    .filter(Boolean);
  const expanded = new Set(rawTokens);
  rawTokens.forEach((token) => {
    const mapped = GENRE_PROMPT_ALIASES[token];
    if (mapped) expanded.add(mapped);
  });
  for (const key of Object.keys(GENRE_PROMPT_MAP)) {
    if (expanded.has(key)) return GENRE_PROMPT_MAP[key];
  }
  if (expanded.has('literary') || expanded.has('fiction')) return GENRE_PROMPT_MAP.literature;
  return null;
}

function _hashString(value) {
  let hash = 0;
  const text = String(value || '');
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash) + text.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function _dayOfYear(referenceDate = new Date()) {
  const current = new Date(referenceDate);
  const start = new Date(current.getFullYear(), 0, 0);
  const diff = current - start;
  const oneDay = 1000 * 60 * 60 * 24;
  return Math.floor(diff / oneDay);
}

function suggestedWildcardPromptForBook(book, referenceDate = new Date()) {
  const config = genrePromptConfigForBook(book);
  const ids = Array.isArray(config?.wildcards) ? config.wildcards : [];
  if (!ids.length) return null;
  const seed = _hashString(`${book?.title || ''}::${book?.author || ''}`);
  const index = (seed + _dayOfYear(referenceDate)) % ids.length;
  return findPromptById(ids[index]);
}

window.__ITERATE_TEST_HOOKS__.suggestedWildcardPromptForBook = suggestedWildcardPromptForBook;
window.__ITERATE_TEST_HOOKS__.suggestedWildcardPromptForBookAtDate = ({ book, referenceDate }) => (
  suggestedWildcardPromptForBook(book, new Date(referenceDate))
);

function defaultAutoPromptConfigForBook(book) {
  return genrePromptConfigForBook(book) || GENRE_PROMPT_MAP.literature || {
    base: ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism,
    wildcards: [],
  };
}

function buildVariantPromptAssignments({ book, variantCount, referenceDate = new Date() }) {
  const total = Math.max(1, Number(variantCount || 1));
  const config = defaultAutoPromptConfigForBook(book);
  const basePromptId = String(config?.base || ALEXANDRIA_BASE_PROMPT_IDS.romanticRealism || '').trim();
  const wildcardIds = Array.isArray(config?.wildcards)
    ? config.wildcards.map((value) => String(value || '').trim()).filter(Boolean)
    : [];
  const wildcardSeed = wildcardIds.length
    ? (_hashString(`${book?.title || ''}::${book?.author || ''}`) + _dayOfYear(referenceDate)) % wildcardIds.length
    : 0;

  return Array.from({ length: total }, (_, index) => {
    const variant = index + 1;
    const promptId = variant === 1 || !wildcardIds.length
      ? basePromptId
      : (wildcardIds[(wildcardSeed + variant - 2) % wildcardIds.length] || basePromptId);
    return {
      variant,
      promptId,
      promptName: String(findPromptById(promptId)?.name || '').trim(),
    };
  });
}

function promptTemplateForPromptId(promptId) {
  return String(findPromptById(promptId)?.prompt_template || '').trim();
}

function buildEditableVariantPromptPlan({ book, variantCount, previousPlan = [], preserveExisting = true, referenceDate = new Date() }) {
  const assignments = buildVariantPromptAssignments({ book, variantCount, referenceDate });
  const previousByVariant = new Map(
    (Array.isArray(previousPlan) ? previousPlan : [])
      .map((item) => [Number(item?.variant || 0), item])
      .filter(([variant]) => variant > 0)
  );

  return assignments.map((assignment) => {
    const variant = Number(assignment.variant || 1);
    const previous = preserveExisting ? previousByVariant.get(variant) : null;
    const autoPromptId = String(assignment.promptId || '').trim();
    const previousAutoPromptId = String(previous?.autoPromptId || '').trim();
    const previousAutoTemplate = promptTemplateForPromptId(previousAutoPromptId);
    const usesAutoAssignment = previous ? Boolean(previous.usesAutoAssignment) : true;
    const manualPromptId = String(previous?.promptId || '').trim();
    const promptId = usesAutoAssignment ? autoPromptId : (manualPromptId || autoPromptId);
    const templatePrompt = promptTemplateForPromptId(promptId) || promptTemplateForPromptId(autoPromptId);
    let customPrompt = String(previous?.customPrompt || '').trim();
    if (!customPrompt || (usesAutoAssignment && (customPrompt === previousAutoTemplate || previousAutoPromptId !== autoPromptId))) {
      customPrompt = templatePrompt;
    }
    let sceneVal = String(previous?.sceneVal || '').trim();
    if (!sceneVal || _isGenericContent(sceneVal)) sceneVal = sceneForVariant(book, variant, '');
    let moodVal = String(previous?.moodVal || '').trim();
    if (!moodVal || _isGenericContent(moodVal)) moodVal = defaultMoodForBook(book);
    let eraVal = String(previous?.eraVal || '').trim();
    if (!eraVal || _isGenericContent(eraVal)) eraVal = defaultEraForBook(book);
    return {
      variant,
      autoPromptId,
      usesAutoAssignment,
      promptId,
      customPrompt,
      sceneVal,
      moodVal,
      eraVal,
    };
  });
}

window.__ITERATE_TEST_HOOKS__.buildVariantPromptAssignments = ({ book, variantCount, referenceDate }) => (
  buildVariantPromptAssignments({
    book,
    variantCount,
    referenceDate: referenceDate ? new Date(referenceDate) : new Date(),
  })
);

function backendJobIdForJob(job) {
  const direct = String(job?.backend_job_id || '').trim();
  if (direct) return direct;
  try {
    const parsed = JSON.parse(String(job?.results_json || '{}'));
    return String(parsed?.result?.job_id || '').trim();
  } catch {
    return '';
  }
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function saveRawButtonState(job) {
  const status = String(job?.save_raw_status || '').trim().toLowerCase();
  const driveUrl = String(job?.save_raw_drive_url || '').trim();
  const warning = String(job?.save_raw_warning || '').trim();
  const truncatedWarning = warning.length > 220 ? `${warning.slice(0, 220)}…` : warning;

  if (status === 'saved') {
    return {
      label: '✓ Saved',
      style: 'background:#2d6a4f;color:#fff;font-weight:600;',
      title: driveUrl ? 'Click to open in Google Drive' : 'Saved raw package.',
      driveUrl,
      status,
    };
  }

  if (status === 'partial') {
    return {
      label: '✓ Saved (Drive unavailable)',
      style: 'background:#d4af37;color:#0a1628;font-weight:600;',
      title: truncatedWarning || 'Saved locally; Google Drive unavailable.',
      driveUrl: '',
      status,
    };
  }

  return {
    label: '💾 Save Raw',
    style: 'background:#d4af37;color:#0a1628;font-weight:600;',
    title: '',
    driveUrl: '',
    status: '',
  };
}

function normalizedModelId(model) {
  return String(model?.id || '').trim();
}

function providerFromModel(modelId) {
  const token = String(modelId || '').trim().toLowerCase();
  if (!token) return 'unknown';
  if (token.startsWith('openrouter/')) return 'openrouter';
  if (token.startsWith('google/')) return 'google';
  if (token.startsWith('openai/')) return 'openai';
  if (token.startsWith('fal/')) return 'fal';
  return token.split('/')[0] || 'unknown';
}

function isGeminiModel(model) {
  return normalizedModelId(model).toLowerCase().includes('gemini');
}

function isNanoModel(model) {
  const token = normalizedModelId(model).toLowerCase();
  return NANO_BANANA_MODEL_IDS.has(token);
}

function isGeminiFlashDirectModel(model) {
  const token = normalizedModelId(model).toLowerCase();
  return GEMINI_FLASH_DIRECT_MODEL_IDS.has(token);
}

function modelCapabilities(model) {
  const modality = String(model?.modality || '').toLowerCase();
  const token = normalizedModelId(model).toLowerCase();
  if (modality.includes('both') || token.includes('gpt-5-image') || token.includes('gpt-image-1') || token.includes('image-preview')) {
    return 'image + text';
  }
  return 'image';
}

function modelDescription(model) {
  const token = normalizedModelId(model).toLowerCase();
  if (isNanoModel(model)) return 'Best Nano Banana quality tier (recommended default).';
  if (token.includes('google/gemini-3-pro-image-preview')) return 'Nano Banana Pro direct Google provider route.';
  if (token.includes('google/gemini-2.5-flash-image')) return 'Gemini 2.5 Flash direct Google provider route.';
  if (isGeminiFlashDirectModel(model)) return 'Gemini direct Google provider route.';
  if (token.includes('gpt-5-image-mini')) return 'Lower-cost GPT-5 image generation.';
  if (token.includes('gpt-5-image') || token.includes('gpt-image-1')) return 'Premium multimodal image + text output.';
  if (token.includes('riverflow') && token.includes('fast-preview')) return 'Fast draft variant for quick iteration.';
  if (token.includes('riverflow') && token.includes('max')) return 'High-fidelity preview-tier Riverflow output.';
  if (token.includes('flux') && token.includes('klein')) return 'Lightweight FLUX variant for cheaper drafts.';
  if (token.includes('flux')) return 'Efficient high-quality FLUX generation model.';
  if (token.includes('seedream')) return 'Expressive painterly and illustrative styling.';
  return 'Balanced quality and cost for iterative cover generation.';
}

function getRecommendedModelIds(models) {
  const top = models.slice(0, Math.min(15, models.length)).map((model) => normalizedModelId(model));
  const pinned = RECOMMENDED_PINNED_MODEL_IDS.filter((id) => models.some((model) => normalizedModelId(model) === id));
  return Array.from(new Set(pinned.concat(top)));
}

function defaultSelectedModelIds(models) {
  const preferred = PREFERRED_DEFAULT_MODELS.find((id) => models.some((model) => normalizedModelId(model) === id));
  if (preferred) return [preferred];
  const first = normalizedModelId(models[0] || null);
  return first ? [first] : [];
}

function filterModelList(models, filterName) {
  if (filterName === 'all') return models;
  if (filterName === 'openrouter') return models.filter((model) => providerFromModel(model.id) === 'openrouter');
  if (filterName === 'gemini') return models.filter((model) => isGeminiModel(model));
  if (filterName === 'nano') return models.filter((model) => isNanoModel(model));
  const byId = new Map(models.map((model) => [normalizedModelId(model), model]));
  return getRecommendedModelIds(models)
    .map((modelId) => byId.get(modelId))
    .filter(Boolean);
}

function renderModelCards({ models, selectedIds, activeFilter, searchText }) {
  const search = String(searchText || '').trim().toLowerCase();
  const filteredByChip = filterModelList(models, activeFilter);
  const visible = filteredByChip.filter((model) => {
    if (!search) return true;
    const id = normalizedModelId(model).toLowerCase();
    const label = String(model.label || '').toLowerCase();
    const provider = providerFromModel(model.id);
    return id.includes(search) || label.includes(search) || provider.includes(search);
  });
  const orderedVisible = visible.slice().sort((left, right) => {
    const leftSelected = selectedIds.has(normalizedModelId(left));
    const rightSelected = selectedIds.has(normalizedModelId(right));
    if (leftSelected === rightSelected) return 0;
    return leftSelected ? -1 : 1;
  });
  const visibleIds = orderedVisible.map((model) => normalizedModelId(model));
  const html = orderedVisible.map((model) => {
    const modelId = normalizedModelId(model);
    const checked = selectedIds.has(modelId);
    const provider = providerFromModel(modelId);
    const capability = modelCapabilities(model);
    return `
      <label class="model-card ${checked ? 'selected' : ''}">
        <div class="model-card-head">
          <div class="model-card-titlewrap">
            <input type="checkbox" class="iter-model-check" value="${escapeHtml(modelId)}" ${checked ? 'checked' : ''} />
            <span class="model-card-title">${escapeHtml(model.label || modelId)}</span>
          </div>
          <span class="tag tag-gold">$${Number(model.cost || 0).toFixed(3)}</span>
        </div>
        <div class="model-card-id">${escapeHtml(modelId)}</div>
        <div class="model-card-desc">${escapeHtml(modelDescription(model))}</div>
        <div class="model-card-tags">
          <span class="tag tag-provider">${escapeHtml(provider)}</span>
          <span class="tag tag-style">${escapeHtml(capability)}</span>
        </div>
      </label>
    `;
  }).join('');
  return { html, visibleIds, visibleCount: orderedVisible.length, filteredCount: filteredByChip.length };
}

window.Pages.iterate = {
  async render() {
    const content = document.getElementById('content');
    const catalogId = 'classics';
    let books = DB.dbGetAll('books');
    if (!books.length) books = await DB.loadBooks(catalogId);
    if (!books.length) {
      try {
        books = await Drive.syncCatalog({ catalog: catalogId, force: true, limit: 20000 });
      } catch {
        // no-op
      }
    }
    await DB.loadPrompts(catalogId);

    const prompts = sortPromptsForUI(DB.dbGetAll('prompts'));
    const options = books
      .sort((a, b) => Number(a.number || 0) - Number(b.number || 0))
      .map((book) => `<option value="${book.id}">${book.number}. ${book.title}</option>`)
      .join('');
    const promptOptions = [`<option value="">${AUTO_ROTATE_PROMPT_OPTION_LABEL}</option>`]
      .concat(prompts.map((p) => `<option value="${p.id}">${p.name}</option>`))
      .join('');

    content.innerHTML = `
      <div class="card">
        <div class="card-header iterate-card-header">
          <div>
            <h3 class="card-title">Generate Illustrations</h3>
            <p class="text-sm text-muted iterate-flow-note">Book → Variants → Style → Generate. Model changes and prompt customization live under Advanced.</p>
          </div>
          <button class="btn btn-secondary btn-sm" id="iterAdvancedToggle" type="button" aria-expanded="false">Advanced</button>
        </div>

        <div class="form-group">
          <div class="flex justify-between items-center">
            <label class="form-label">Book</label>
            <button class="btn btn-secondary btn-sm" id="iterSyncBooksBtn">Sync</button>
          </div>
          <select class="form-select" id="iterBookSelect">
            <option value="">— Select a book —</option>
            ${options}
          </select>
          <p class="text-xs text-muted mt-8" id="iterBookSyncStatus">${books.length ? `${books.length} books loaded (catalog).` : 'No books loaded yet'}</p>
        </div>

        <div class="form-group">
          <div class="flex justify-between items-center">
            <label class="form-label">Enrichment status</label>
            <button class="btn btn-secondary btn-sm" id="iterReenrichGenericBtn">Re-enrich Generic Books</button>
          </div>
          <div class="flex gap-8 items-center">
            <span class="tag tag-pending" id="iterEnrichmentBadge">Checking…</span>
            <span class="text-xs text-muted" id="iterEnrichmentSummary">Loading enrichment health.</span>
          </div>
        </div>

        <div class="form-row iterate-primary-row">
          <div class="form-group">
            <label class="form-label">Variants</label>
            <select class="form-select" id="iterVariants">${Array.from({ length: 10 }, (_, i) => `<option value="${i + 1}" ${i + 1 === DEFAULT_VARIANT_COUNT ? 'selected' : ''}>${i + 1}</option>`).join('')}</select>
          </div>
          <div class="form-group">
            <label class="form-label">Style</label>
            <select class="form-select" id="iterPromptSel">${promptOptions}</select>
            <div class="text-xs text-muted mt-8" id="iterPromptRotationInfo">${escapeHtml(AUTO_ROTATE_PROMPT_INFO)}</div>
            <div class="text-xs text-muted mt-8" id="iterWildcardSuggestion"></div>
          </div>
        </div>

        <div class="flex justify-between items-center iterate-primary-actions">
          <span class="text-muted" id="iterCostEst">Est. cost: $0.000</span>
          <div class="flex gap-8">
            <button class="btn btn-secondary" id="iterCancelBtn">Cancel All</button>
            <button class="btn btn-primary" id="iterGenBtn">Generate</button>
          </div>
        </div>

        <div class="iterate-variant-summary hidden" id="iterVariantSummary"></div>

        <div class="iterate-model-summary-card mt-16">
          <div>
            <div class="form-label iterate-inline-label">Model</div>
            <div class="iterate-model-selected" id="iterModelCollapsedValue">Loading recommended model…</div>
          </div>
          <button class="btn-link" id="iterModelToggle" type="button" aria-expanded="false">Change model</button>
        </div>

        <div id="iterAdvanced" class="hidden mt-16">
          <div class="advanced-block hidden" id="iterModelControls">
            <label class="form-label">Models (best → budget, top → bottom)</label>
            <input class="form-input model-search-input" id="iterModelSearch" placeholder="Search model name / provider / id..." />
            <div class="model-toolbar mt-8">
              <button class="filter-chip active" type="button" data-model-filter="recommended">Recommended</button>
              <button class="filter-chip" type="button" data-model-filter="all">All</button>
              <button class="filter-chip" type="button" data-model-filter="openrouter">OpenRouter</button>
              <button class="filter-chip" type="button" data-model-filter="gemini">Gemini</button>
              <button class="filter-chip" type="button" data-model-filter="nano">Nano Pro only</button>
              <button class="filter-chip" type="button" data-model-action="select-visible">Select visible</button>
              <button class="filter-chip" type="button" data-model-action="clear">Clear</button>
            </div>
            <p class="text-xs text-muted mt-8" id="iterModelSummary"></p>
            <p class="text-xs text-muted mt-8" id="iterCostBreakdown"></p>
            <div class="model-card-grid" id="iterModelGrid"></div>
          </div>

          <details class="advanced-block" id="iterCustomizePanel">
            <summary>Customize variants</summary>
            <div class="advanced-panel-body">
              <div class="form-group">
                <div class="flex justify-between items-center">
                  <label class="form-label">Variant prompt plan</label>
                  <span class="text-xs text-muted" id="iterVariantPlanSummary">Variant 1 starts with the baseline prompt; the rest rotate wildcard prompts.</span>
                </div>
                <div class="grid-auto" id="iterVariantPromptPlan"></div>
              </div>

              <div class="form-group">
                <div class="flex justify-between items-center">
                  <label class="form-label">Custom prompt</label>
                  <span class="text-xs text-muted" id="iterVariantEditorLabel">Editing variant 1.</span>
                </div>
                <textarea class="form-textarea" id="iterPrompt" rows="4" placeholder="Override the prompt. Use {title}, {author}, {SCENE}, {MOOD}, and {ERA} placeholders..."></textarea>
                <div id="iterVarFields" class="mt-8 hidden">
                  <label class="form-label mt-8">Scene description</label>
                  <textarea class="form-textarea" id="iterScene" rows="2" placeholder="e.g. A radiant divine figure emerging from concentric celestial spheres..."></textarea>
                  <label class="form-label mt-8">Mood</label>
                  <input class="form-input" id="iterMood" type="text" placeholder="e.g. mystical, luminous, sacred" />
                  <label class="form-label mt-8">Era (optional)</label>
                  <input class="form-input" id="iterEra" type="text" placeholder="e.g. 2nd century Gnostic" />
                </div>
              </div>

              <div class="form-group">
                <div class="flex justify-between items-center">
                  <label class="form-label">Prompt preview</label>
                  <span class="text-xs text-muted" id="iterPromptValidation">Awaiting book selection.</span>
                </div>
                <textarea class="form-textarea prompt-preview-textarea" id="iterPromptPreview" rows="7" readonly placeholder="Resolved prompt preview will appear here..."></textarea>
              </div>
            </div>
          </details>
        </div>
      </div>

      <div class="card hidden" id="pipelineCard">
        <div class="card-header"><h3 class="card-title">Running Jobs</h3></div>
        <div class="pipeline" id="pipelineArea"></div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">Recent Results</h3>
          <span class="text-muted" id="iterResultCount">0 results</span>
        </div>
        <div class="grid-auto" id="resultsGrid"></div>
      </div>
    `;

    const selectEl = document.getElementById('iterBookSelect');
    const syncBtn = document.getElementById('iterSyncBooksBtn');
    const syncStatus = document.getElementById('iterBookSyncStatus');
    const enrichGenericBtn = document.getElementById('iterReenrichGenericBtn');
    const enrichmentBadgeEl = document.getElementById('iterEnrichmentBadge');
    const enrichmentSummaryEl = document.getElementById('iterEnrichmentSummary');
    const advancedToggleBtn = document.getElementById('iterAdvancedToggle');
    const advanced = document.getElementById('iterAdvanced');
    const modelToggleBtn = document.getElementById('iterModelToggle');
    const modelControlsEl = document.getElementById('iterModelControls');
    const modelCollapsedValueEl = document.getElementById('iterModelCollapsedValue');
    const variantsEl = document.getElementById('iterVariants');
    const promptSelEl = document.getElementById('iterPromptSel');
    const promptRotationInfoEl = document.getElementById('iterPromptRotationInfo');
    const wildcardSuggestionEl = document.getElementById('iterWildcardSuggestion');
    const customPromptEl = document.getElementById('iterPrompt');
    const varFieldsEl = document.getElementById('iterVarFields');
    const sceneEl = document.getElementById('iterScene');
    const moodEl = document.getElementById('iterMood');
    const eraEl = document.getElementById('iterEra');
    const promptPreviewEl = document.getElementById('iterPromptPreview');
    const promptValidationEl = document.getElementById('iterPromptValidation');
    const variantPlanEl = document.getElementById('iterVariantPromptPlan');
    const variantPlanSummaryEl = document.getElementById('iterVariantPlanSummary');
    const variantEditorLabelEl = document.getElementById('iterVariantEditorLabel');
    const variantSummaryEl = document.getElementById('iterVariantSummary');
    const modelSearchEl = document.getElementById('iterModelSearch');
    const modelGridEl = document.getElementById('iterModelGrid');
    const modelSummaryEl = document.getElementById('iterModelSummary');
    const modelFilterButtons = Array.from(content.querySelectorAll('[data-model-filter]'));
    const modelActionButtons = Array.from(content.querySelectorAll('[data-model-action]'));
    let latestEnrichmentHealth = null;

    const renderEnrichmentHealth = (payload) => {
      latestEnrichmentHealth = payload && typeof payload === 'object' ? payload : null;
      if (!enrichmentBadgeEl || !enrichmentSummaryEl || !enrichGenericBtn) return;
      const health = String(latestEnrichmentHealth?.health || 'warning').toLowerCase();
      const total = Number(latestEnrichmentHealth?.total_books || 0);
      const real = Number(latestEnrichmentHealth?.enriched_real || 0);
      const generic = Number(latestEnrichmentHealth?.enriched_generic || 0);
      const missing = Number(latestEnrichmentHealth?.no_enrichment || 0);
      const runStatus = latestEnrichmentHealth?.run_status || {};
      const isRunning = Boolean(runStatus && runStatus.running);
      const label = health === 'healthy' ? 'Healthy' : (health === 'critical' ? 'Critical' : 'Warning');
      enrichmentBadgeEl.textContent = `Enrichment: ${label}`;
      enrichmentBadgeEl.className = `tag ${health === 'healthy' ? 'tag-success' : (health === 'critical' ? 'tag-failed' : 'tag-pending')}`;
      enrichmentSummaryEl.textContent = isRunning
        ? `Background re-enrichment is running. Real: ${real}/${total}. Generic: ${generic}. Missing: ${missing}.`
        : `Real: ${real}/${total}. Generic: ${generic}. Missing: ${missing}.`;
      enrichGenericBtn.disabled = isRunning || (generic <= 0 && missing <= 0);
      enrichGenericBtn.textContent = isRunning ? 'Re-enriching…' : 'Re-enrich Generic Books';
    };

    const fetchEnrichmentHealth = async ({ silent = false } = {}) => {
      try {
        const response = await fetch(`/api/enrichment-health?catalog=${encodeURIComponent(catalogId)}`, { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        renderEnrichmentHealth(payload);
        return payload;
      } catch (err) {
        if (!silent) Toast.error(`Enrichment health failed: ${err.message || err}`);
        if (enrichmentBadgeEl) enrichmentBadgeEl.textContent = 'Enrichment: Unavailable';
        if (enrichmentSummaryEl) enrichmentSummaryEl.textContent = 'Unable to load enrichment health.';
        if (enrichGenericBtn) enrichGenericBtn.disabled = false;
        return null;
      }
    };

    const selectedBook = () => {
      const bookId = Number(selectEl?.value || 0);
      return books.find((row) => Number(row.id) === bookId) || null;
    };

    const selectedVariantCount = () => Math.max(1, Number(variantsEl?.value || DEFAULT_VARIANT_COUNT));

    const activeVariantState = () => _variantPromptPlan.find((item) => Number(item?.variant || 0) === _activeVariantPrompt) || null;

    const promptNameForId = (promptId) => String(findPromptById(promptId)?.name || '').trim();

    const buildPromptSelectOptions = (selectedPromptId = '') => {
      const selectedId = String(selectedPromptId || '').trim();
      return [`<option value="">${AUTO_ROTATE_PROMPT_OPTION_LABEL}</option>`]
        .concat(
          sortPromptsForUI(DB.dbGetAll('prompts')).map((prompt) => {
            const promptId = String(prompt?.id || '').trim();
            const selected = selectedId && promptId === selectedId ? ' selected' : '';
            return `<option value="${escapeHtml(promptId)}"${selected}>${escapeHtml(String(prompt?.name || promptId))}</option>`;
          })
        )
        .join('');
    };

    const renderVariantPromptPlan = () => {
      if (!variantPlanEl || !variantPlanSummaryEl || !variantEditorLabelEl) return;
      const book = selectedBook();
      if (!book || !_variantPromptPlan.length) {
        variantPlanEl.innerHTML = '<div class="text-xs text-muted">Select a book to build the prompt plan.</div>';
        variantPlanSummaryEl.textContent = 'Variant 1 starts with the baseline prompt; the rest rotate wildcard prompts.';
        variantEditorLabelEl.textContent = 'Editing variant 1.';
        return;
      }
      const manualOverrides = _variantPromptPlan.filter((item) => !item.usesAutoAssignment).length;
      variantPlanSummaryEl.textContent = _variantPromptPlan.length > 1
        ? `${manualOverrides} manual override${manualOverrides === 1 ? '' : 's'}. ${AUTO_ROTATE_PROMPT_OPTION_LABEL} uses the baseline prompt for variant 1 and rotating wildcard prompts for the rest.`
        : `${manualOverrides ? 'Manual prompt selected.' : `${AUTO_ROTATE_PROMPT_OPTION_LABEL} uses the baseline prompt.`}`;
      const activeItem = activeVariantState() || _variantPromptPlan[0];
      const activePromptLabel = promptNameForId(activeItem?.promptId || '') || AUTO_ROTATE_PROMPT_OPTION_LABEL;
      const activeAutoLabel = promptNameForId(activeItem?.autoPromptId || '') || activePromptLabel;
      variantEditorLabelEl.textContent = activeItem
        ? `Editing variant ${activeItem.variant} of ${_variantPromptPlan.length}. ${activeItem.usesAutoAssignment ? `Auto assignment: ${activeAutoLabel}.` : `Manual selection: ${activePromptLabel}.`}`
        : 'Editing variant 1.';
      variantPlanEl.innerHTML = _variantPromptPlan.map((item) => {
        const manualPromptLabel = promptNameForId(item.promptId) || AUTO_ROTATE_PROMPT_OPTION_LABEL;
        const autoPromptLabel = promptNameForId(item.autoPromptId) || manualPromptLabel;
        const scenePreview = _normalizePromptText(item.sceneVal || '').slice(0, 140);
        const isActive = Number(item.variant) === _activeVariantPrompt;
        return `
          <div class="card" style="padding:12px;border:${isActive ? '2px solid #d4af37' : '1px solid rgba(10,22,40,0.12)'};box-shadow:none;" data-variant-card="${item.variant}">
            <div class="flex justify-between items-center">
              <div>
                <div style="font-weight:600;">Variant ${item.variant}</div>
                <div class="text-xs text-muted mt-8">${escapeHtml(item.usesAutoAssignment ? `Auto: ${autoPromptLabel}` : `Manual: ${manualPromptLabel}`)}</div>
              </div>
              <button class="btn btn-secondary btn-sm" type="button" data-variant-edit="${item.variant}">${isActive ? 'Editing' : 'Edit details'}</button>
            </div>
            <select class="form-select mt-8" data-variant-prompt="${item.variant}">
              ${buildPromptSelectOptions(item.usesAutoAssignment ? '' : item.promptId)}
            </select>
            <div class="text-xs text-muted mt-8">${escapeHtml(scenePreview || `Scene rotates automatically for variant ${item.variant}.`)}</div>
          </div>
        `;
      }).join('');
    };

    const syncVariantEditor = ({ forceDefaults = false } = {}) => {
      const book = selectedBook();
      const item = activeVariantState();
      if (!book || !item) {
        if (promptSelEl) promptSelEl.value = '';
        if (customPromptEl) customPromptEl.value = '';
        if (sceneEl) sceneEl.value = '';
        if (moodEl) moodEl.value = '';
        if (eraEl) eraEl.value = '';
        updatePromptPreview();
        renderVariantPromptPlan();
        return;
      }
      const promptObj = item.promptId ? DB.dbGet('prompts', String(item.promptId)) : null;
      if (promptSelEl) promptSelEl.value = item.usesAutoAssignment ? '' : String(item.promptId || '');
      if (customPromptEl) customPromptEl.value = String(item.customPrompt || String(promptObj?.prompt_template || ''));
      if (sceneEl) sceneEl.value = String(item.sceneVal || '');
      if (moodEl) moodEl.value = String(item.moodVal || '');
      if (eraEl) eraEl.value = String(item.eraVal || '');
      updateVariableFields(promptObj, { forceDefaults });
      item.customPrompt = String(customPromptEl?.value || '');
      item.sceneVal = String(sceneEl?.value || '');
      item.moodVal = String(moodEl?.value || '');
      item.eraVal = String(eraEl?.value || '');
      renderVariantPromptPlan();
    };

    const rebuildVariantPromptPlan = ({ preserveExisting = true, resetActiveVariant = false } = {}) => {
      const book = selectedBook();
      if (!book) {
        _variantPromptPlan = [];
        _activeVariantPrompt = 1;
        syncVariantEditor({ forceDefaults: false });
        return;
      }
      _variantPromptPlan = buildEditableVariantPromptPlan({
        book,
        variantCount: selectedVariantCount(),
        previousPlan: preserveExisting ? _variantPromptPlan : [],
        preserveExisting,
      });
      if (resetActiveVariant) _activeVariantPrompt = 1;
      if (_activeVariantPrompt > _variantPromptPlan.length) _activeVariantPrompt = _variantPromptPlan.length || 1;
      syncVariantEditor({ forceDefaults: true });
    };

    const syncAdvancedVisibility = (expanded) => {
      const shouldShow = Boolean(expanded);
      advanced?.classList.toggle('hidden', !shouldShow);
      if (advancedToggleBtn) {
        advancedToggleBtn.textContent = shouldShow ? 'Hide Advanced' : 'Advanced';
        advancedToggleBtn.setAttribute('aria-expanded', shouldShow ? 'true' : 'false');
      }
    };

    const syncModelControlVisibility = (expanded) => {
      const shouldShow = Boolean(expanded);
      modelControlsEl?.classList.toggle('hidden', !shouldShow);
      if (modelToggleBtn) {
        modelToggleBtn.textContent = shouldShow ? 'Hide models' : 'Change model';
        modelToggleBtn.setAttribute('aria-expanded', shouldShow ? 'true' : 'false');
      }
    };

    const updatePromptRotationInfo = (promptId = '') => {
      if (!promptRotationInfoEl) return;
      promptRotationInfoEl.textContent = String(promptId || '').trim()
        ? 'Saved style selected. Open Advanced to customize scenes or prompt text.'
        : AUTO_ROTATE_PROMPT_INFO;
    };

    const updateVariantSummary = () => {
      if (!variantSummaryEl) return;
      const book = selectedBook();
      if (!book) {
        variantSummaryEl.classList.add('hidden');
        variantSummaryEl.innerHTML = '';
        return;
      }
      const { entries, missingPromptIds } = buildVariantPromptPayloads({
        book,
        variantCount: selectedVariantCount(),
        variantPlan: _variantPromptPlan,
      });
      if (missingPromptIds.length) {
        variantSummaryEl.classList.remove('hidden');
        variantSummaryEl.innerHTML = `<div class="text-xs text-muted">Missing prompt templates: ${escapeHtml(missingPromptIds.join(', '))}</div>`;
        return;
      }
      const lines = formatVariantSummaryLines(entries);
      variantSummaryEl.classList.toggle('hidden', !lines.length);
      variantSummaryEl.innerHTML = lines.map((line) => `<div class="iterate-variant-line">${escapeHtml(line)}</div>`).join('');
    };

    const updatePromptPreview = () => {
      if (!promptPreviewEl || !promptValidationEl) return;
      const book = selectedBook();
      if (!book) {
        promptPreviewEl.value = '';
        promptValidationEl.textContent = 'Awaiting book selection.';
        updateVariantSummary();
        return;
      }
      const { entries, missingPromptIds } = buildVariantPromptPayloads({
        book,
        variantCount: selectedVariantCount(),
        variantPlan: _variantPromptPlan,
      });
      if (missingPromptIds.length) {
        promptPreviewEl.value = '';
        promptValidationEl.textContent = `Missing prompt templates: ${missingPromptIds.join(', ')}`;
        updateVariantSummary();
        return;
      }
      promptPreviewEl.value = formatPromptPreview(entries);
      const validationIssues = entries.flatMap((entry) => {
        const validation = validatePromptBeforeGeneration({ prompt: entry?.promptPayload?.prompt || '', book });
        const issues = validation.errors.length ? validation.errors : validation.warnings;
        return issues.map((issue) => `Variant ${entry.variant}: ${issue}`);
      });
      promptValidationEl.textContent = validationIssues[0] || `${entries.length} variant prompt${entries.length === 1 ? '' : 's'} ready.`;
      updateVariantSummary();
    };

    const updateWildcardSuggestion = (book) => {
      if (!wildcardSuggestionEl) return;
      const wildcardPrompt = suggestedWildcardPromptForBook(book);
      if (!wildcardPrompt) {
        wildcardSuggestionEl.innerHTML = '';
        return;
      }
      wildcardSuggestionEl.innerHTML = `
        <button class="filter-chip" type="button" data-wildcard-prompt="${escapeHtml(String(wildcardPrompt.id || ''))}">
          Try wildcard: ${escapeHtml(String(wildcardPrompt.name || ''))}
        </button>
      `;
      const button = wildcardSuggestionEl.querySelector('[data-wildcard-prompt]');
      button?.addEventListener('click', () => {
        if (promptSelEl) {
          promptSelEl.value = String(wildcardPrompt.id || '');
          promptSelEl.dispatchEvent(new Event('change'));
        }
      });
    };

    const updateVariableFields = (templateObj, { forceDefaults = false } = {}) => {
      if (!varFieldsEl || !sceneEl || !moodEl || !eraEl) return;
      const book = selectedBook();
      const activePromptText = String(templateObj?.prompt_template || customPromptEl?.value || '').trim();
      const usesAlexandriaFields = activePromptText.includes('{SCENE}');
      varFieldsEl.classList.toggle('hidden', !usesAlexandriaFields);
      if (!usesAlexandriaFields) {
        updatePromptPreview();
        return;
      }
      const item = activeVariantState();
      const variantNumber = Number(item?.variant || 1);
      if (forceDefaults || !String(sceneEl.value || '').trim() || _isGenericContent(sceneEl.value)) sceneEl.value = sceneForVariant(book, variantNumber, '');
      if (forceDefaults || !String(moodEl.value || '').trim() || _isGenericContent(moodEl.value)) moodEl.value = defaultMoodForBook(book);
      if (forceDefaults || !String(eraEl.value || '').trim() || _isGenericContent(eraEl.value)) eraEl.value = defaultEraForBook(book);
      updatePromptPreview();
    };

    const applyPromptSelection = (promptId, { forceAlexandriaDefaults = false, variantNumber = _activeVariantPrompt } = {}) => {
      const item = _variantPromptPlan.find((entry) => Number(entry?.variant || 0) === Number(variantNumber || 0));
      if (!item) return null;
      const selectedPromptId = String(promptId || '').trim();
      const resolvedPromptId = selectedPromptId || String(item.autoPromptId || '').trim();
      const selected = resolvedPromptId ? DB.dbGet('prompts', String(resolvedPromptId)) : null;
      item.usesAutoAssignment = !selectedPromptId;
      item.promptId = resolvedPromptId;
      item.customPrompt = String(selected?.prompt_template || '');
      if (forceAlexandriaDefaults || !String(item.sceneVal || '').trim() || _isGenericContent(item.sceneVal)) item.sceneVal = sceneForVariant(selectedBook(), item.variant, '');
      if (forceAlexandriaDefaults || !String(item.moodVal || '').trim() || _isGenericContent(item.moodVal)) item.moodVal = defaultMoodForBook(selectedBook());
      if (forceAlexandriaDefaults || !String(item.eraVal || '').trim() || _isGenericContent(item.eraVal)) item.eraVal = defaultEraForBook(selectedBook());
      _activeVariantPrompt = item.variant;
      syncVariantEditor({ forceDefaults: forceAlexandriaDefaults });
      updateWildcardSuggestion(selectedBook());
      updatePromptRotationInfo(selectedPromptId);
      return selected;
    };

    const autoSelectGenrePrompt = ({ preserveExisting = true, resetActiveVariant = false } = {}) => {
      const book = selectedBook();
      if (!book) {
        rebuildVariantPromptPlan({ preserveExisting: false, resetActiveVariant: true });
        updateWildcardSuggestion(book);
        updatePromptRotationInfo('');
        updatePromptPreview();
        return;
      }
      if (!preserveExisting && variantsEl) variantsEl.value = String(DEFAULT_VARIANT_COUNT);
      rebuildVariantPromptPlan({ preserveExisting, resetActiveVariant });
      updateWildcardSuggestion(book);
      updatePromptRotationInfo('');
    };

    _defaultSelectedModelIds = defaultSelectedModelIds(OpenRouter.MODELS);
    _defaultModelId = _defaultSelectedModelIds[0] || normalizedModelId(OpenRouter.MODELS[0] || null) || null;
    _selectedModelIds = new Set(_defaultSelectedModelIds);
    _lastVisibleModelIds = [];
    let activeModelFilter = 'recommended';
    let modelSearchText = '';

    advancedToggleBtn?.addEventListener('click', () => {
      const expanded = advanced?.classList.contains('hidden');
      syncAdvancedVisibility(expanded);
    });

    modelToggleBtn?.addEventListener('click', () => {
      const expanded = modelControlsEl?.classList.contains('hidden');
      syncAdvancedVisibility(true);
      syncModelControlVisibility(expanded);
    });

    selectEl?.addEventListener('change', () => {
      _selectedBookId = Number(selectEl.value || 0) || null;
      autoSelectGenrePrompt({ preserveExisting: false, resetActiveVariant: true });
      this.loadExistingResults();
    });

    syncBtn?.addEventListener('click', async () => {
      const previous = syncBtn.textContent;
      syncBtn.disabled = true;
      syncBtn.textContent = 'Syncing...';
      try {
        const synced = await Drive.syncCatalog({ catalog: catalogId, force: true, limit: 20000 });
        const summary = Drive.getLastCatalogSyncSummary();
        let rows = Array.isArray(synced) ? synced : [];
        if (!rows.length) rows = await DB.loadBooks(catalogId);
        const sorted = [...(Array.isArray(rows) ? rows : [])]
          .sort((a, b) => Number(a.number || 0) - Number(b.number || 0));
        books = sorted;
        const current = Number(selectEl?.value || 0);
        if (selectEl) {
          selectEl.innerHTML = ['<option value="">— Select a book —</option>']
            .concat(sorted.map((book) => `<option value="${book.id}">${book.number}. ${book.title}</option>`))
            .join('');
          if (current > 0 && sorted.some((book) => Number(book.id) === current)) {
            selectEl.value = String(current);
          } else if (current > 0) {
            selectEl.value = '';
            _selectedBookId = null;
          }
        }
        const driveTotalRaw = Number(summary.drive_total || summary.source_count || 0);
        const driveTotal = Number.isFinite(driveTotalRaw) && driveTotalRaw > 0 ? Math.round(driveTotalRaw) : 0;
        if (syncStatus) {
          syncStatus.textContent = driveTotal > 0
            ? `${sorted.length} books loaded (catalog). Drive found: ${driveTotal}.`
            : `${sorted.length} books loaded (catalog).`;
        }
        updateHeader();
        if (driveTotal > 0) {
          Toast.success(`Catalog synced: ${sorted.length} books (Drive found ${driveTotal})`);
        } else {
          Toast.success(`Catalog synced: ${sorted.length} books`);
        }
        autoSelectGenrePrompt({ preserveExisting: true, resetActiveVariant: false });
        updatePromptPreview();
        await fetchEnrichmentHealth({ silent: true });
      } catch (err) {
        if (syncStatus) syncStatus.textContent = 'Sync failed';
        Toast.error(`Sync failed: ${err.message || err}`);
      } finally {
        syncBtn.disabled = false;
        syncBtn.textContent = previous || 'Sync';
      }
    });

    enrichGenericBtn?.addEventListener('click', async () => {
      const previous = enrichGenericBtn.textContent;
      enrichGenericBtn.disabled = true;
      enrichGenericBtn.textContent = 'Starting…';
      try {
        const response = await fetch(`/api/enrich-generic?catalog=${encodeURIComponent(catalogId)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ replace_generic: true, delay: 0.5, batch_size: 50 }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload?.ok === false) throw new Error(payload?.error || payload?.message || `HTTP ${response.status}`);
        Toast.success(payload?.started === false ? 'Generic re-enrichment is already running.' : 'Background re-enrichment started.');
        await fetchEnrichmentHealth({ silent: true });
      } catch (err) {
        Toast.error(`Re-enrichment failed: ${err.message || err}`);
        enrichGenericBtn.disabled = false;
        enrichGenericBtn.textContent = previous || 'Re-enrich Generic Books';
      }
    });

    const updateCost = () => {
      const variants = Number(variantsEl?.value || DEFAULT_VARIANT_COUNT);
      const selected = Array.from(_selectedModelIds);
      const total = selected.reduce((sum, modelId) => sum + Number(OpenRouter.MODEL_COSTS[modelId] || 0) * variants, 0);
      const est = document.getElementById('iterCostEst');
      const breakdown = document.getElementById('iterCostBreakdown');
      if (est) {
        const worst = total * 3;
        est.textContent = `Est. cost: $${total.toFixed(3)} · worst-case $${worst.toFixed(3)}`;
      }
      if (breakdown) {
        if (!selected.length) {
          breakdown.textContent = 'No models selected.';
        } else {
          const parts = selected.map((modelId) => {
            const unit = Number(OpenRouter.MODEL_COSTS[modelId] || 0);
            const subtotal = unit * variants;
            return `${modelIdToLabel(modelId)} ($${unit.toFixed(3)} × ${variants} = $${subtotal.toFixed(3)})`;
          });
          breakdown.textContent = `Cost breakdown: ${parts.join(' + ')} = $${total.toFixed(3)}.`;
        }
      }
    };

    const updateCollapsedModelSummary = () => {
      if (!modelCollapsedValueEl) return;
      const selected = Array.from(_selectedModelIds);
      if (!selected.length) {
        modelCollapsedValueEl.textContent = 'No model selected';
        return;
      }
      if (selected.length === 1) {
        const modelId = selected[0];
        const unit = Number(OpenRouter.MODEL_COSTS[modelId] || 0);
        modelCollapsedValueEl.textContent = `${modelIdToLabel(modelId)} ($${unit.toFixed(3)}/image)`;
        return;
      }
      const unitTotal = selected.reduce((sum, modelId) => sum + Number(OpenRouter.MODEL_COSTS[modelId] || 0), 0);
      modelCollapsedValueEl.textContent = `${selected.length} models selected ($${unitTotal.toFixed(3)}/variant)`;
    };

    const renderModels = () => {
      if (!modelGridEl || !modelSummaryEl) return;
      const rendered = renderModelCards({
        models: OpenRouter.MODELS,
        selectedIds: _selectedModelIds,
        activeFilter: activeModelFilter,
        searchText: modelSearchText,
      });
      _lastVisibleModelIds = rendered.visibleIds;
      modelGridEl.innerHTML = rendered.html || '<div class="text-muted text-sm">No models match this filter.</div>';
      const selectedLabels = Array.from(_selectedModelIds)
        .map((id) => modelIdToLabel(id))
        .slice(0, 4)
        .join(', ');
      const remaining = Math.max(0, _selectedModelIds.size - 4);
      const selectedSuffix = remaining > 0 ? ` +${remaining} more` : '';
      const defaultLabels = _defaultSelectedModelIds.map((id) => modelIdToLabel(id)).join(', ') || 'first model';
      modelSummaryEl.textContent = `${_selectedModelIds.size} model selected · showing ${rendered.visibleCount}/${OpenRouter.MODELS.length}. Default selection: ${defaultLabels}. Selected: ${selectedLabels || 'none'}${selectedSuffix}.`;
      updateCost();
      updateCollapsedModelSummary();
    };

    modelSearchEl?.addEventListener('input', () => {
      modelSearchText = String(modelSearchEl.value || '');
      renderModels();
    });

    modelFilterButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        activeModelFilter = String(btn.dataset.modelFilter || 'recommended');
        modelFilterButtons.forEach((node) => node.classList.toggle('active', node === btn));
        renderModels();
      });
    });

    modelActionButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = String(btn.dataset.modelAction || '');
        if (action === 'select-visible') {
          _lastVisibleModelIds.forEach((id) => _selectedModelIds.add(id));
        } else if (action === 'clear') {
          _selectedModelIds.clear();
        }
        renderModels();
      });
    });

    modelGridEl?.addEventListener('change', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (!target.classList.contains('iter-model-check')) return;
      const modelId = String(target.value || '').trim();
      if (!modelId) return;
      if (target.checked) _selectedModelIds.add(modelId);
      else _selectedModelIds.delete(modelId);
      renderModels();
    });

    variantPlanEl?.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const editButton = target.closest('[data-variant-edit]');
      if (!editButton) return;
      const variantNumber = Number(editButton.getAttribute('data-variant-edit') || 0);
      if (variantNumber <= 0) return;
      _activeVariantPrompt = variantNumber;
      syncVariantEditor({ forceDefaults: false });
    });

    variantPlanEl?.addEventListener('change', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLSelectElement)) return;
      const variantNumber = Number(target.getAttribute('data-variant-prompt') || 0);
      if (variantNumber <= 0) return;
      applyPromptSelection(String(target.value || '').trim(), {
        forceAlexandriaDefaults: true,
        variantNumber,
      });
    });

    variantsEl?.addEventListener('change', () => {
      updateCost();
      autoSelectGenrePrompt({ preserveExisting: true, resetActiveVariant: false });
    });
    promptSelEl?.addEventListener('change', () => {
      const promptId = String(promptSelEl.value || '').trim();
      if (_variantPromptPlan.length > 1) {
        _variantPromptPlan.forEach((item) => {
          applyPromptSelection(promptId, {
            forceAlexandriaDefaults: true,
            variantNumber: Number(item?.variant || 0) || 1,
          });
        });
        _activeVariantPrompt = 1;
        syncVariantEditor({ forceDefaults: true });
        updatePromptPreview();
        return;
      }
      applyPromptSelection(promptId, { forceAlexandriaDefaults: true });
    });
    customPromptEl?.addEventListener('input', () => {
      const item = activeVariantState();
      if (item) item.customPrompt = String(customPromptEl.value || '');
      const selectedPromptId = String(item?.promptId || '').trim();
      const selected = selectedPromptId ? DB.dbGet('prompts', selectedPromptId) : null;
      updateVariableFields(selected, { forceDefaults: false });
      renderVariantPromptPlan();
    });
    sceneEl?.addEventListener('input', () => {
      const item = activeVariantState();
      if (item) item.sceneVal = String(sceneEl.value || '');
      renderVariantPromptPlan();
      updatePromptPreview();
    });
    moodEl?.addEventListener('input', () => {
      const item = activeVariantState();
      if (item) item.moodVal = String(moodEl.value || '');
      updatePromptPreview();
    });
    eraEl?.addEventListener('input', () => {
      const item = activeVariantState();
      if (item) item.eraVal = String(eraEl.value || '');
      updatePromptPreview();
    });
    renderModels();
    syncAdvancedVisibility(false);
    syncModelControlVisibility(false);
    updatePromptRotationInfo(String(promptSelEl?.value || '').trim());

    document.getElementById('iterCancelBtn')?.addEventListener('click', () => JobQueue.cancelAll());
    document.getElementById('iterGenBtn')?.addEventListener('click', () => this.handleGenerate());

    if (_unsubscribe) _unsubscribe();
    _unsubscribe = JobQueue.onChange((snapshot) => {
      this.updatePipeline(snapshot.all || []);
      this.loadExistingResults();
    });

    const initialBook = Number(window.__ITERATE_BOOK_ID__ || 0);
    if (initialBook && books.some((b) => Number(b.id) === initialBook)) {
      selectEl.value = String(initialBook);
      _selectedBookId = initialBook;
    }
    if (_selectedBookId) {
      autoSelectGenrePrompt({ preserveExisting: false, resetActiveVariant: true });
    } else {
      _variantPromptPlan = [];
      _activeVariantPrompt = 1;
      updateWildcardSuggestion(null);
      updatePromptRotationInfo('');
      syncVariantEditor({ forceDefaults: false });
      updatePromptPreview();
    }
    renderEnrichmentHealth({ health: 'warning', total_books: 0, enriched_real: 0, enriched_generic: 0, no_enrichment: 0, run_status: {} });
    await fetchEnrichmentHealth({ silent: true });
    this.loadExistingResults();
  },

  async handleGenerate() {
    const bookId = Number(document.getElementById('iterBookSelect')?.value || 0);
    if (!bookId) {
      Toast.warning('Select a book first.');
      return;
    }
    const selectedModels = Array.from(_selectedModelIds);
    if (!selectedModels.length) {
      Toast.warning('Select at least one model.');
      return;
    }

    const variantCount = Number(document.getElementById('iterVariants')?.value || DEFAULT_VARIANT_COUNT);
    const books = DB.dbGetAll('books');
    const book = books.find((b) => Number(b.id) === bookId);
    if (!book) return;

    const variantPromptPlan = Array.isArray(_variantPromptPlan) && _variantPromptPlan.length === variantCount
      ? _variantPromptPlan
      : buildEditableVariantPromptPlan({
        book,
        variantCount,
        previousPlan: [],
        preserveExisting: false,
      });
    const { entries: variantEntries, missingPromptIds } = buildVariantPromptPayloads({
      book,
      variantCount,
      variantPlan: variantPromptPlan,
    });
    if (missingPromptIds.length) {
      Toast.error(`Missing prompt templates: ${missingPromptIds.join(', ')}`);
      return;
    }
    const selectedCoverId = String(book.cover_jpg_id || book.drive_cover_id || '').trim();
    const selectedCoverBookNumber = Number(book.number || book.id || bookId || 0);

    const jobs = [];
    let validationError = '';
    selectedModels.forEach((model) => {
      variantEntries.forEach((entry) => {
        if (validationError) return;
        const promptPayload = entry?.promptPayload || {};
        const validation = validatePromptBeforeGeneration({ prompt: promptPayload.prompt, book });
        if (!validation.ok) {
          validationError = validation.errors[0];
          return;
        }
        jobs.push({
          id: uuid(),
          book_id: bookId,
          model,
          variant: Number(entry?.variant || 1),
          status: 'queued',
          prompt: promptPayload.prompt,
          style_id: promptPayload.styleId,
          style_label: promptPayload.styleLabel,
          prompt_source: promptPayload.promptSource,
          backend_prompt_source: promptPayload.backendPromptSource,
          compose_prompt: promptPayload.composePrompt,
          preserve_prompt_text: promptPayload.preservePromptText,
          library_prompt_id: promptPayload.libraryPromptId,
          scene_description: String(entry?.assignedScene || '').trim(),
          mood: String(entry?.assignedMood || '').trim(),
          era: String(entry?.assignedEra || '').trim(),
          selected_cover_id: selectedCoverId,
          selected_cover_book_number: selectedCoverBookNumber,
          quality_score: null,
          cost_usd: 0,
          generated_image_blob: null,
          composited_image_blob: null,
          started_at: null,
          completed_at: null,
          error: null,
          results_json: null,
          retries: 0,
          _elapsed: 0,
          _subStatus: '',
          _compositeFailed: false,
          _compositeError: null,
          created_at: new Date().toISOString(),
        });
      });
    });

    if (validationError) {
      Toast.error(validationError);
      return;
    }
    if (!jobs.length) return;

    JobQueue.addBatch(jobs);
    document.getElementById('pipelineCard')?.classList.remove('hidden');
    Toast.success(`${jobs.length} job(s) queued.`);
  },

  updatePipeline(allJobs) {
    const area = document.getElementById('pipelineArea');
    const card = document.getElementById('pipelineCard');
    if (!area || !_selectedBookId) {
      card?.classList.add('hidden');
      return;
    }

    const scoped = allJobs
      .filter((job) => Number(job.book_id) === Number(_selectedBookId))
      .sort((a, b) => new Date(b.created_at || b.started_at || 0).getTime() - new Date(a.created_at || a.started_at || 0).getTime());

    if (!scoped.length) {
      area.innerHTML = '<div class="text-muted text-sm">No jobs yet.</div>';
      card?.classList.add('hidden');
      return;
    }

    card?.classList.remove('hidden');
    const active = scoped.filter((job) => !['completed', 'failed', 'cancelled'].includes(job.status)).slice(0, 12);
    const completed = scoped.filter((job) => job.status === 'completed').length;
    const failed = scoped.filter((job) => job.status === 'failed').length;
    const cancelled = scoped.filter((job) => job.status === 'cancelled').length;
    const queuedOrRunning = Math.max(0, scoped.length - completed - failed - cancelled);
    const totalCost = scoped.reduce((sum, job) => sum + Number(job.cost_usd || 0), 0);
    const maxBackendStale = active.reduce((maxAge, job) => Math.max(maxAge, Number(job._backendHeartbeatAge || 0)), 0);
    const queueHint = queuedOrRunning > 0
      ? ` · backend heartbeat ${maxBackendStale}s ago${maxBackendStale >= 20 ? ' (waiting on queue/provider)' : ''}`
      : '';
    const summary = `
      <div class="pipeline-summary">
        <strong>Run status:</strong> ${completed}/${scoped.length} completed · ${queuedOrRunning} active/queued · ${failed} failed · ${cancelled} cancelled · $${totalCost.toFixed(3)}${queueHint}
      </div>
    `;

    if (!active.length) {
      area.innerHTML = `${summary}<div class="text-muted text-sm">No active jobs.</div>`;
      return;
    }

    const mapStatusToStep = (status) => {
      if (status === 'downloading_cover') return 0;
      if (status === 'generating' || status === 'retrying') return 1;
      if (status === 'scoring') return 2;
      if (status === 'compositing') return 3;
      return -1;
    };

    area.innerHTML = summary + active.map((job) => {
      const step = mapStatusToStep(job.status);
      const steps = ['⬇ Cover', '⚡ Generate', '⭐ Score', '🎨 Composite'];
      const renderedSteps = steps.map((label, idx) => {
        let cls = 'pipeline-step';
        if (idx < step) cls += ' done';
        if (idx === step) cls += ' active heartbeat-pulse';
        return `<span class="${cls}">${label}</span>`;
      }).join('');
      const book = DB.dbGet('books', job.book_id);
      return `
        <div class="pipeline-row">
          <span class="text-sm fw-600">${book?.title || `Book ${job.book_id}`} · v${job.variant}</span>
          <div class="pipeline-steps">${renderedSteps}</div>
          <span class="text-xs text-muted">${job._elapsed || 0}s</span>
          <span class="text-xs text-muted">${job._subStatus || ''}</span>
          <button class="btn-cancel-job" data-cancel="${job.id}">Cancel</button>
          <span class="text-xs">$${Number(job.cost_usd || 0).toFixed(3)}</span>
        </div>
      `;
    }).join('');

    area.querySelectorAll('[data-cancel]').forEach((btn) => {
      btn.addEventListener('click', () => JobQueue.abortJob(btn.dataset.cancel, 'Cancelled by user'));
    });
  },

  loadExistingResults() {
    const grid = document.getElementById('resultsGrid');
    const count = document.getElementById('iterResultCount');
    if (!grid || !_selectedBookId) {
      if (grid) grid.innerHTML = '<div class="text-muted">Select a book and generate illustrations</div>';
      if (count) count.textContent = '0 results';
      return;
    }

    const jobs = DB.dbGetByIndex('jobs', 'book_id', _selectedBookId)
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 30);

    if (!jobs.length) {
      grid.innerHTML = '<div class="text-muted">No results yet</div>';
      if (count) count.textContent = '0 results';
      return;
    }

    const completed = jobs.filter((job) => job.status === 'completed').length;
    if (count) count.textContent = `${completed} completed · ${jobs.length} total`;
    grid.innerHTML = jobs.map((job) => {
      const previewSources = resolveCompositePreviewSources(job, 'display');
      const src = previewSources[0] || '';
      const fallbackSrc = previewSources[1] || '';
      const hasPreview = Boolean(src);
      const quality = Number(job.quality_score || 0);
      const status = String(job.status || 'queued');
      const showDownloads = hasPreview && status === 'completed';
      const showComparison = Number(job.book_id || 0) > 0 && status === 'completed';
      const errorText = status === 'failed' ? String(job.error || '').trim() : '';
      const saveRawState = saveRawButtonState(job);
      return `
        <div class="result-card ${hasPreview ? '' : 'result-card-empty'}" ${hasPreview ? `data-view="${job.id}"` : ''}>
          ${hasPreview
            ? `<img class="thumb thumb-front" src="${src}" alt="result" data-fallback-src="${encodeURIComponent(fallbackSrc)}" data-status="${status}" />`
            : `<div class="thumb thumb-fallback">${fallbackCardText(status)}</div>`}
          <div class="card-body">
            <div class="flex justify-between">
              <span class="tag tag-model">${modelIdToLabel(job.model)}</span>
              <span class="tag ${statusTagClass(status)}">${status}</span>
            </div>
            <div class="quality-meter">
              <div class="quality-bar"><div class="quality-fill ${qualityClass(quality)}" style="width:${Math.round(quality * 100)}%"></div></div>
            </div>
            <div class="card-meta">$${Number(job.cost_usd || 0).toFixed(3)} · ${job.style_label || 'Default'}</div>
            ${errorText ? `<div class="card-meta text-danger">${errorText}</div>` : ''}
            <div class="flex gap-4 mt-8">
              <button class="btn btn-secondary btn-sm" data-dl-comp="${job.id}" ${showDownloads ? '' : 'disabled'}>⬇ Download</button>
              <button class="btn btn-secondary btn-sm" data-dl-raw="${job.id}" ${showDownloads ? '' : 'disabled'}>⬇ Raw</button>
              <button class="btn btn-secondary btn-sm" data-view-qa-book="${Number(job.book_id || 0)}" ${showComparison ? '' : 'disabled'}>Compare</button>
              <button class="btn btn-sm" data-save-raw="${job.id}" data-drive-url="${escapeHtml(saveRawState.driveUrl)}" data-save-status="${escapeHtml(saveRawState.status)}" ${showDownloads ? '' : 'disabled'} style="${saveRawState.style}" title="${escapeHtml(saveRawState.title)}">${escapeHtml(saveRawState.label)}</button>
              <button class="btn btn-secondary btn-sm" data-save-prompt="${job.id}">💾 Prompt</button>
            </div>
          </div>
        </div>
      `;
    }).join('');

    grid.querySelectorAll('img.thumb').forEach((img) => {
      img.addEventListener('error', () => {
        if (!img.dataset.fallbackTried) {
          img.dataset.fallbackTried = '1';
          const next = decodeAttrToken(img.dataset.fallbackSrc || '');
          if (next && next !== img.src) {
            img.src = next;
            return;
          }
        }
        const status = String(img.dataset.status || 'completed');
        const card = img.closest('.result-card');
        if (card) {
          card.classList.add('result-card-empty');
          card.removeAttribute('data-view');
        }
        const fallback = document.createElement('div');
        fallback.className = 'thumb thumb-fallback';
        fallback.textContent = fallbackCardText(status);
        img.replaceWith(fallback);
      });
    });

    grid.querySelectorAll('[data-view]').forEach((el) => {
      el.addEventListener('click', (event) => {
        if (event.target.closest('button')) return;
        this.viewFull(el.dataset.view, 'composite');
      });
    });
    grid.querySelectorAll('[data-dl-comp]').forEach((btn) => btn.addEventListener('click', (e) => { e.stopPropagation(); this.downloadComposite(btn.dataset.dlComp); }));
    grid.querySelectorAll('[data-dl-raw]').forEach((btn) => btn.addEventListener('click', (e) => { e.stopPropagation(); this.downloadGenerated(btn.dataset.dlRaw); }));
    grid.querySelectorAll('[data-view-qa-book]').forEach((btn) => btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const book = Number(btn.dataset.viewQaBook || 0);
      if (!Number.isFinite(book) || book <= 0) return;
      window.open(`/api/visual-qa/image/${book}?catalog=classics`, '_blank', 'noopener,noreferrer');
    }));
    grid.querySelectorAll('[data-save-raw]').forEach((btn) => btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await this.saveRaw(btn.dataset.saveRaw, btn);
    }));
    grid.querySelectorAll('[data-save-prompt]').forEach((btn) => btn.addEventListener('click', (e) => { e.stopPropagation(); this.savePromptFromJob(btn.dataset.savePrompt); }));
  },

  viewFull(jobId, mode = 'composite') {
    const job = DB.dbGet('jobs', jobId);
    if (!job) return;
    const composite = resolvePreviewSources(job, 'view-composite', false)[0] || '';
    const raw = resolvePreviewSources(job, 'view-raw', true)[0] || composite;
    const state = { mode };

    const overlay = document.createElement('div');
    overlay.className = 'view-modal';
    overlay.innerHTML = `
      <div class="view-modal-inner">
        <div class="modal-header">
          <h3 class="modal-title">Preview · ${modelIdToLabel(job.model)} · v${job.variant}</h3>
          <button class="close-btn" id="viewCloseBtn">×</button>
        </div>
        <div class="modal-body">
          <div class="tabs">
            <button class="tab ${state.mode === 'composite' ? 'active' : ''}" data-mode="composite">Composite</button>
            <button class="tab ${state.mode === 'raw' ? 'active' : ''}" data-mode="raw">Raw</button>
          </div>
          <img id="viewImg" src="${state.mode === 'composite' ? composite : raw}" style="width:100%;height:auto;border-radius:8px;border:1px solid var(--border)" />
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const update = () => {
      overlay.querySelector('#viewImg').src = state.mode === 'composite' ? composite : raw;
      overlay.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.mode === state.mode));
    };

    overlay.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => {
      state.mode = tab.dataset.mode;
      update();
    }));
    overlay.querySelector('#viewCloseBtn')?.addEventListener('click', () => overlay.remove());
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  },

  async downloadComposite(jobId) {
    const job = DB.dbGet('jobs', jobId);
    if (!job) return;
    const { number, baseName } = resolveBookMetadataForJob(job);
    // Mirror source cover folder naming: "{number}. {file_base}"
    const folderName = `${number}. ${baseName}`;
    const zipName = `${folderName}.zip`;
    const compositeHref = pickFullResolutionSource(job, 'download-composite', false);
    const rawHref = pickFullResolutionSource(job, 'download-raw', true);
    const pdfHref = resolveJobArtifactHref(job, ['composite_pdf_url', 'pdf_url', 'composited_pdf_path', 'pdf_path']);
    const aiHref = resolveJobArtifactHref(job, ['composite_ai_url', 'ai_url', 'composited_ai_path', 'ai_path']);
    const sourceHref = `/api/source-download?catalog=classics&book=${encodeURIComponent(Number(job.book_id || 0))}&variant=${encodeURIComponent(Number(job.variant || 0))}&model=${encodeURIComponent(String(job.model || ''))}`;

    try {
      const JSZip = await ensureJSZip();
      const zip = new JSZip();
      let compositeBlob = (job.composited_image_blob instanceof Blob) ? job.composited_image_blob : null;
      let rawBlob = (job.generated_image_blob instanceof Blob) ? job.generated_image_blob : null;
      if (!compositeBlob) compositeBlob = await fetchDownloadBlob(compositeHref);
      if (!rawBlob) rawBlob = await fetchDownloadBlob(rawHref);
      let sourceBlob = await fetchDownloadBlob(sourceHref);
      let pdfBlob = await fetchDownloadBlob(pdfHref);
      let aiBlob = await fetchDownloadBlob(aiHref);

      if (!compositeBlob || !sourceBlob || !pdfBlob) {
        const fallback = await _extractVariantArchiveAssets({
          bookId: Number(job.book_id || 0),
          variant: Number(job.variant || 0),
          model: String(job.model || ''),
        });
        if (!compositeBlob && fallback.compositeBlob) compositeBlob = fallback.compositeBlob;
        if (!rawBlob && fallback.rawBlob) rawBlob = fallback.rawBlob;
        if (!sourceBlob && fallback.sourceBlob) sourceBlob = fallback.sourceBlob;
        if (!pdfBlob && fallback.pdfBlob) pdfBlob = fallback.pdfBlob;
        if (!aiBlob && fallback.aiBlob) aiBlob = fallback.aiBlob;
      }

      if (!rawBlob && sourceBlob) rawBlob = sourceBlob;
      if (!sourceBlob && rawBlob) sourceBlob = rawBlob;

      if (!compositeBlob && !rawBlob && !sourceBlob && !pdfBlob && !aiBlob) return;

      if (compositeBlob) {
        zip.file(`${folderName}/${baseName}.jpg`, compositeBlob);
      }

      if (rawBlob) {
        const rawExt = _extensionFromPath(rawHref) || _extensionFromBlob(rawBlob, 'png');
        zip.file(`${folderName}/${baseName} (generated raw).${rawExt}`, rawBlob);
      }

      if (sourceBlob) {
        const sourceExt = _extensionFromPath(sourceHref) || _extensionFromBlob(sourceBlob, 'png');
        zip.file(`${folderName}/${baseName} (source raw).${sourceExt}`, sourceBlob);
      }

      if (pdfBlob) {
        zip.file(`${folderName}/${baseName}.pdf`, pdfBlob);
      }

      if (aiBlob) {
        zip.file(`${folderName}/${baseName}.ai`, aiBlob);
      }

      const zipBlob = await zip.generateAsync({ type: 'blob' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(zipBlob);
      a.download = zipName;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      console.error('ZIP download failed:', err);
      if (compositeHref) {
        const a = document.createElement('a');
        a.href = compositeHref;
        a.download = `${baseName}.jpg`;
        a.click();
      }
    }
  },

  downloadGenerated(jobId) {
    const job = DB.dbGet('jobs', jobId);
    if (!job) return;
    const href = pickFullResolutionSource(job, 'download-raw-single', true);
    if (!href) return;
    const { number, baseName } = resolveBookMetadataForJob(job);
    const a = document.createElement('a');
    a.href = href;
    a.download = `${number}. ${baseName} (illustration).jpg`;
    a.click();
  },

  async saveRaw(jobId, button) {
    const job = DB.dbGet('jobs', jobId);
    if (!job || !button) return;
    const existingDriveUrl = String(button.dataset.driveUrl || job.save_raw_drive_url || '').trim();
    if (existingDriveUrl) {
      window.open(existingDriveUrl, '_blank', 'noopener,noreferrer');
      return;
    }
    const backendJobId = backendJobIdForJob(job);
    if (!backendJobId) {
      Toast.error('Save Raw failed: backend job id is missing.');
      return;
    }

    const originalText = String(button.textContent || '💾 Save Raw');
    const originalBackground = button.style.background;
    const originalColor = button.style.color;
    button.disabled = true;
    button.textContent = 'Saving...';

    try {
      const resp = await fetch('/api/save-raw', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: backendJobId }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        throw new Error(data.message || data.error || `HTTP ${resp.status}`);
      }

      const partial = Boolean(data.warning) && !data.drive_url;
      job.save_raw_status = partial ? 'partial' : 'saved';
      job.save_raw_warning = String(data.warning || '').trim();
      job.save_raw_drive_url = String(data.drive_url || '').trim();
      job.save_raw_local_folder = String(data.local_folder || '').trim();
      job.save_raw_saved_files = Array.isArray(data.saved_files) ? data.saved_files : [];
      job.save_raw_saved_at = new Date().toISOString();
      DB.dbPut('jobs', job);
      this.loadExistingResults();

      if (partial) {
        Toast.warning('Saved locally; Google Drive unavailable.');
      } else {
        Toast.success('Saved raw package.');
      }
    } catch (err) {
      button.textContent = '✗ Failed';
      button.style.background = '#d32f2f';
      button.style.color = '#fff';
      button.disabled = false;
      button.dataset.driveUrl = '';
      Toast.error(`Save Raw failed: ${err.message || err}`);
      setTimeout(() => {
        button.textContent = originalText;
        button.style.background = originalBackground;
        button.style.color = originalColor;
      }, 2500);
    }
  },

  refreshPromptDropdown(selectedId = '') {
    const promptSel = document.getElementById('iterPromptSel');
    if (!promptSel) return;
    const prompts = sortPromptsForUI(DB.dbGetAll('prompts'));
    promptSel.innerHTML = [`<option value="">${AUTO_ROTATE_PROMPT_OPTION_LABEL}</option>`]
      .concat(prompts.map((p) => `<option value="${p.id}">${p.name}</option>`))
      .join('');
    if (selectedId) {
      promptSel.value = String(selectedId);
    }
  },

  async savePromptFromJob(jobId) {
    const job = DB.dbGet('jobs', jobId);
    if (!job?.prompt) return;
    const book = DB.dbGet('books', job.book_id);
    const title = String(book?.title || '').trim();
    const author = String(book?.author || '').trim();
    let template = String(job.prompt || '').trim();
    if (title) template = template.replaceAll(title, '{title}');
    if (author) template = template.replaceAll(author, '{author}');
    if (!template.includes('{title}')) {
      template = `For "{title}" by {author}: ${template}`.trim();
    }

    try {
      const response = await fetch('/api/save-prompt?catalog=classics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: `${book?.title || `Book ${job.book_id}`} - ${modelIdToLabel(job.model)} v${job.variant}`,
          prompt_template: template,
          category: 'Saved',
          tags: ['iterative', 'result_card', String(job.model || '').trim().toLowerCase()],
          style_anchors: job.style_id && job.style_id !== 'none' ? [job.style_id] : [],
          notes: `Saved from iterate result card (${job.model} v${job.variant}).`,
        }),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      await DB.loadPrompts('classics');
      this.refreshPromptDropdown();
      Toast.success('Prompt saved');
    } catch (err) {
      Toast.error(`Prompt save failed: ${err.message || err}`);
    }
  },
};
