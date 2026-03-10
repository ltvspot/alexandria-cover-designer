window.Pages = window.Pages || {};

let _selectedBookId = null;
let _unsubscribe = null;
let _selectedModelIds = new Set();
let _defaultModelId = null;
let _lastVisibleModelIds = [];
let _defaultSelectedModelIds = [];
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
const GENRE_PROMPT_MAP = {
  religious: { base: 'BASE 1 — Classical Devotion', wildcards: ['WILDCARD 3 — Illuminated Manuscript', 'WILDCARD 5 — Temple of Knowledge'] },
  apocryphal: { base: 'BASE 1 — Classical Devotion', wildcards: ['WILDCARD 3 — Illuminated Manuscript', 'WILDCARD 5 — Temple of Knowledge'] },
  biblical: { base: 'BASE 1 — Classical Devotion', wildcards: ['WILDCARD 3 — Illuminated Manuscript', 'WILDCARD 5 — Temple of Knowledge'] },
  philosophy: { base: 'BASE 2 — Philosophical Gravitas', wildcards: ['WILDCARD 4 — Celestial Cartography', 'WILDCARD 1 — Dramatic Graphic Novel'] },
  'self-help': { base: 'BASE 2 — Philosophical Gravitas', wildcards: ['WILDCARD 4 — Celestial Cartography', 'WILDCARD 1 — Dramatic Graphic Novel'] },
  strategy: { base: 'BASE 2 — Philosophical Gravitas', wildcards: ['WILDCARD 4 — Celestial Cartography', 'WILDCARD 1 — Dramatic Graphic Novel'] },
  horror: { base: 'BASE 3 — Gothic Atmosphere', wildcards: ['WILDCARD 4 — Celestial Cartography', 'WILDCARD 2 — Vintage Travel Poster'] },
  gothic: { base: 'BASE 3 — Gothic Atmosphere', wildcards: ['WILDCARD 4 — Celestial Cartography', 'WILDCARD 2 — Vintage Travel Poster'] },
  supernatural: { base: 'BASE 3 — Gothic Atmosphere', wildcards: ['WILDCARD 4 — Celestial Cartography', 'WILDCARD 2 — Vintage Travel Poster'] },
  literature: { base: 'BASE 4 — Romantic Realism', wildcards: ['WILDCARD 2 — Vintage Travel Poster', 'WILDCARD 1 — Dramatic Graphic Novel'] },
  novels: { base: 'BASE 4 — Romantic Realism', wildcards: ['WILDCARD 2 — Vintage Travel Poster', 'WILDCARD 1 — Dramatic Graphic Novel'] },
  drama: { base: 'BASE 4 — Romantic Realism', wildcards: ['WILDCARD 2 — Vintage Travel Poster', 'WILDCARD 1 — Dramatic Graphic Novel'] },
  occult: { base: 'BASE 5 — Esoteric Mysticism', wildcards: ['WILDCARD 5 — Temple of Knowledge', 'WILDCARD 3 — Illuminated Manuscript'] },
  mystical: { base: 'BASE 5 — Esoteric Mysticism', wildcards: ['WILDCARD 5 — Temple of Knowledge', 'WILDCARD 3 — Illuminated Manuscript'] },
  esoteric: { base: 'BASE 5 — Esoteric Mysticism', wildcards: ['WILDCARD 5 — Temple of Knowledge', 'WILDCARD 3 — Illuminated Manuscript'] },
  collections: { base: 'BASE 2 — Philosophical Gravitas', wildcards: ['WILDCARD 4 — Celestial Cartography'] },
  anthologies: { base: 'BASE 2 — Philosophical Gravitas', wildcards: ['WILDCARD 4 — Celestial Cartography'] },
};
const GENRE_PROMPT_ALIASES = {
  'literary-fiction': 'literature',
  'classic-literature': 'literature',
  literary: 'literature',
  fiction: 'literature',
  novel: 'novels',
  collection: 'collections',
  anthology: 'anthologies',
  religion: 'religious',
  sacred: 'religious',
  gnostic: 'apocryphal',
  'biblical-studies': 'biblical',
  spirituality: 'mystical',
  mysticism: 'mystical',
};
const ALEXANDRIA_AUTO_ROTATE_PROMPT_IDS = [
  'alexandria-base-classical-devotion',
  'alexandria-base-philosophical-gravitas',
  'alexandria-base-gothic-atmosphere',
  'alexandria-base-romantic-realism',
  'alexandria-base-esoteric-mysticism',
  'alexandria-wildcard-edo-meets-alexandria',
  'alexandria-wildcard-pre-raphaelite-garden',
  'alexandria-wildcard-illuminated-manuscript',
  'alexandria-wildcard-celestial-cartography',
  'alexandria-wildcard-temple-of-knowledge',
];
const ALEXANDRIA_PROMPT_ID_BY_NAME = {
  'BASE 1 — Classical Devotion': 'alexandria-base-classical-devotion',
  'BASE 2 — Philosophical Gravitas': 'alexandria-base-philosophical-gravitas',
  'BASE 3 — Gothic Atmosphere': 'alexandria-base-gothic-atmosphere',
  'BASE 4 — Romantic Realism': 'alexandria-base-romantic-realism',
  'BASE 5 — Esoteric Mysticism': 'alexandria-base-esoteric-mysticism',
  'WILDCARD 1 — Dramatic Graphic Novel': 'alexandria-wildcard-edo-meets-alexandria',
  'WILDCARD 2 — Vintage Travel Poster': 'alexandria-wildcard-pre-raphaelite-garden',
  'WILDCARD 3 — Illuminated Manuscript': 'alexandria-wildcard-illuminated-manuscript',
  'WILDCARD 4 — Celestial Cartography': 'alexandria-wildcard-celestial-cartography',
  'WILDCARD 5 — Temple of Knowledge': 'alexandria-wildcard-temple-of-knowledge',
};
const ALEXANDRIA_WILDCARD_IDS = [
  'alexandria-wildcard-edo-meets-alexandria',
  'alexandria-wildcard-pre-raphaelite-garden',
  'alexandria-wildcard-illuminated-manuscript',
  'alexandria-wildcard-celestial-cartography',
  'alexandria-wildcard-temple-of-knowledge',
];
const DEFAULT_GENRE_BASE_PROMPT_NAME = 'BASE 4 — Romantic Realism';
const AUTO_ROTATE_PROMPT_OPTION_LABEL = 'Smart rotation (genre-matched + scene variety)';
const AUTO_ROTATE_PROMPT_INFO = 'Each variant uses the best prompt for this book\'s genre with a different scene — truly unique covers';

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

function defaultSceneForBook(book) {
  const enrichment = _bookEnrichment(book);
  const iconicScenes = Array.isArray(enrichment.iconic_scenes) ? enrichment.iconic_scenes : [];
  const firstScene = iconicScenes.find((item) => String(item || '').trim());
  return String(
    book?.scene
    || enrichment.scene
    || firstScene
    || book?.description
    || book?.default_prompt
    || `A pivotal dramatic moment from the literary work "${book?.title || 'an ancient text'}"${book?.author ? ` by ${book.author}` : ''}, depicting the central emotional conflict with period-accurate setting, costume, and atmosphere`
  ).trim();
}

function defaultMoodForBook(book) {
  const enrichment = _bookEnrichment(book);
  return String(
    book?.mood
    || enrichment.emotional_tone
    || enrichment.mood
    || 'classical, timeless, evocative'
  ).trim();
}

function defaultEraForBook(book) {
  const enrichment = _bookEnrichment(book);
  if (Array.isArray(enrichment.era)) {
    const first = enrichment.era.find((item) => String(item || '').trim());
    return String(first || '').trim();
  }
  return String(book?.era || enrichment.era || '').trim();
}

function buildScenePool(book, count) {
  const total = Math.max(1, Number(count || 1));
  const enrichment = _bookEnrichment(book);
  const promptComponents = (book && typeof book.prompt_components === 'object' && book.prompt_components) ? book.prompt_components : {};
  const pool = [];
  const seen = new Set();
  const genericPattern = /iconic turning point|central protagonist|atmospheric setting moment|dramatic emotional conflict/i;
  const pushUnique = (value) => {
    const trimmed = String(value || '').replace(/\s+/g, ' ').trim();
    if (!trimmed || trimmed.length < 20 || genericPattern.test(trimmed)) return;
    const token = trimmed.toLowerCase();
    if (seen.has(token)) return;
    seen.add(token);
    pool.push(trimmed);
  };

  if (Array.isArray(enrichment.iconic_scenes)) {
    enrichment.iconic_scenes.forEach((scene) => pushUnique(scene));
  }

  const protagonist = String(enrichment.protagonist || '').trim();
  const settingPrimary = String(enrichment.setting_primary || '').trim();
  const settingDetails = Array.isArray(enrichment.setting_details)
    ? enrichment.setting_details.map((item) => String(item || '').trim()).filter(Boolean).join(', ')
    : String(enrichment.setting_details || '').trim();

  if (protagonist) {
    pushUnique(
      `${protagonist} in a pivotal moment — ${settingPrimary ? `set in ${settingPrimary}` : 'a defining scene from the story'}`,
    );
  }

  if (settingPrimary) {
    pushUnique(`${settingPrimary}${settingDetails ? `, ${settingDetails}` : ''} — establishing atmosphere of the story's world`);
  }

  const motifs = Array.isArray(enrichment.visual_motifs) ? enrichment.visual_motifs.filter(Boolean) : [];
  const symbols = Array.isArray(enrichment.symbolic_elements) ? enrichment.symbolic_elements.filter(Boolean) : [];
  const symbolicPool = [...motifs, ...symbols]
    .map((item) => String(item || '').trim())
    .filter(Boolean)
    .slice(0, 4);
  if (symbolicPool.length >= 2) {
    pushUnique(`symbolic arrangement of ${symbolicPool.join(', ')} — visual metaphor for the story's themes`);
  }

  const keyCharacters = Array.isArray(enrichment.key_characters)
    ? enrichment.key_characters.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  if (keyCharacters.length >= 2) {
    pushUnique(`${keyCharacters.slice(0, 3).join(', ')} — a dramatic ensemble scene from the story`);
  }

  const titleKeywords = Array.isArray(promptComponents.title_keywords)
    ? promptComponents.title_keywords.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  if (titleKeywords.length) {
    pushUnique(`narrative tableau shaped by ${titleKeywords.slice(0, 3).join(', ')} — a defining moment from ${book?.title || 'the story'}`);
    if (titleKeywords.length >= 2) {
      pushUnique(`setting-focused scene built around ${titleKeywords.slice(-2).join(' and ')} with period atmosphere`);
    }
    if (titleKeywords.length >= 3) {
      pushUnique(`symbolic arrangement of ${titleKeywords.slice(0, 4).join(', ')} — thematic emblem for ${book?.title || 'the story'}`);
    }
  }

  if (!pool.length) {
    pushUnique(defaultSceneForBook(book));
  }

  const variationPrefixes = [
    '',
    'intimate close-up view of ',
    'wide panoramic establishing shot of ',
    'dramatic chiaroscuro lighting on ',
    'serene contemplative depiction of ',
    'dynamic action-filled moment of ',
  ];

  const results = [];
  for (let index = 0; index < total; index += 1) {
    if (index < pool.length) {
      results.push(pool[index]);
      continue;
    }
    const baseScene = pool[index % pool.length] || defaultSceneForBook(book);
    const prefix = variationPrefixes[Math.floor(index / pool.length) % variationPrefixes.length] || '';
    results.push(prefix ? `${prefix}${baseScene}` : baseScene);
  }
  return results;
}

function cleanupResolvedPrompt(promptText) {
  return String(promptText || '')
    .replace(/Era reference:\s*(?:\.|,|;|:)?/gi, '')
    .replace(/\s+([,.;:!?])/g, '$1')
    .replace(/([.?!])\s*\./g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

const GENERIC_SCENE_PATTERN = /A pivotal dramatic moment from the literary work\s+"[^"]*"(?:\s+by\s+[^,."]+)?(?:,\s*depicting the central emotional conflict[^.]*\.?)?/gi;
const GENERIC_MOOD_PATTERN = /classical,\s+timeless,\s+evocative/gi;

function applyPromptPlaceholders(promptText, book, sceneOverride, moodOverride, eraOverride) {
  const scene = String(sceneOverride || defaultSceneForBook(book)).trim();
  const mood = String(moodOverride || defaultMoodForBook(book)).trim();
  const era = String(eraOverride || defaultEraForBook(book)).trim();
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

function ensureEnrichedPrompt(promptText, book, sceneOverride = '') {
  const prompt = String(promptText || '').trim();
  const enrichment = _bookEnrichment(book);
  const populatedScenes = (Array.isArray(enrichment.iconic_scenes) ? enrichment.iconic_scenes : [])
    .map((item) => String(item || '').trim())
    .filter(Boolean);
  const selectedScene = String(sceneOverride || populatedScenes[0] || '').trim();
  const sceneSentence = selectedScene.replace(/[.!?]+$/g, '');
  const protagonist = String(enrichment.protagonist || '').trim();
  const setting = String(enrichment.setting_primary || '').trim();
  const emotionalTone = String(enrichment.emotional_tone || enrichment.mood || '').trim();
  const era = String(enrichment.era || '').trim();

  let result = emotionalTone ? prompt.replace(GENERIC_MOOD_PATTERN, emotionalTone) : prompt;
  if (!selectedScene) {
    return cleanupResolvedPrompt(result);
  }

  result = result.replace(GENERIC_SCENE_PATTERN, selectedScene);
  const lowered = result.toLowerCase();
  const sceneNeedle = selectedScene.substring(0, 30).trim().toLowerCase();
  const hasScene = Boolean(sceneNeedle) && lowered.includes(sceneNeedle);
  if (!hasScene) {
    const enrichmentParts = [`The illustration must depict: ${sceneSentence || selectedScene}.`];
    if (protagonist) enrichmentParts.push(`Character: ${protagonist}.`);
    if (setting) enrichmentParts.push(`Setting: ${setting}.`);
    if (emotionalTone) enrichmentParts.push(`Mood: ${emotionalTone}.`);
    if (era) enrichmentParts.push(`Era: ${era}.`);
    const prefix = result.trim();
    const normalizedPrefix = prefix && !/[.!?]$/.test(prefix) ? `${prefix}.` : prefix;
    result = [normalizedPrefix, ...enrichmentParts].filter(Boolean).join(' ');
  }
  if (emotionalTone) {
    result = result.replace(GENERIC_MOOD_PATTERN, emotionalTone);
  }
  return cleanupResolvedPrompt(result);
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
  const prompt = ensureEnrichedPrompt(
    usesStandalonePrompt
      ? basePrompt
      : `${StyleDiversifier.buildDiversifiedPrompt(book.title, book.author, style)} ${basePrompt}`.trim(),
    book,
    sceneVal,
  );
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

window.__ITERATE_TEST_HOOKS__ = window.__ITERATE_TEST_HOOKS__ || {};
window.__ITERATE_TEST_HOOKS__.buildGenerationJobPrompt = buildGenerationJobPrompt;
window.__ITERATE_TEST_HOOKS__.ensureEnrichedPrompt = ({ promptText, book, sceneOverride }) => ensureEnrichedPrompt(promptText, book, sceneOverride);
window.__ITERATE_TEST_HOOKS__.defaultMoodForBook = (book) => defaultMoodForBook(book);
window.__ITERATE_TEST_HOOKS__.buildScenePool = ({ book, count, ...rawBook }) => {
  const targetBook = book && typeof book === 'object' ? book : rawBook;
  return buildScenePool(targetBook, count);
};

function isAutoRotateSelection(promptId, customPrompt = '') {
  return !String(promptId || '').trim() && !String(customPrompt || '').trim();
}

function autoRotatePromptAssignments(variantCount) {
  const total = Math.max(1, Number(variantCount || 1));
  return Array.from({ length: total }, (_, index) => ALEXANDRIA_AUTO_ROTATE_PROMPT_IDS[index % ALEXANDRIA_AUTO_ROTATE_PROMPT_IDS.length]);
}

window.__ITERATE_TEST_HOOKS__.autoRotatePromptAssignments = autoRotatePromptAssignments;

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

function normalizedPromptText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function promptCategoryToken(prompt) {
  return String(prompt?.category || '').trim().toLowerCase();
}

function promptHasTag(prompt, tag) {
  const needle = String(tag || '').trim().toLowerCase();
  if (!needle) return false;
  return (Array.isArray(prompt?.tags) ? prompt.tags : [])
    .map((item) => String(item || '').trim().toLowerCase())
    .includes(needle);
}

function filterPromptsForIterate(prompts, filterId = 'all') {
  const token = String(filterId || 'all').trim().toLowerCase() || 'all';
  const rows = Array.isArray(prompts) ? prompts : [];
  if (token === 'winner') {
    return rows.filter((prompt) => promptCategoryToken(prompt) === 'winner');
  }
  if (token === 'alexandria') {
    return rows.filter((prompt) => promptHasTag(prompt, 'alexandria'));
  }
  return rows;
}

function findPromptByName(name) {
  const token = normalizedPromptName(name);
  if (!token) return null;
  return sortPromptsForUI(DB.dbGetAll('prompts')).find((prompt) => normalizedPromptName(prompt?.name) === token) || null;
}

function findPromptById(id) {
  const token = String(id || '').trim();
  if (!token) return null;
  return DB.dbGet('prompts', token)
    || sortPromptsForUI(DB.dbGetAll('prompts')).find((prompt) => String(prompt?.id || '').trim() === token)
    || null;
}

function promptIdForName(name) {
  const prompt = findPromptByName(name);
  return String(prompt?.id || ALEXANDRIA_PROMPT_ID_BY_NAME[String(name || '').trim()] || '').trim();
}

function genrePromptConfigForBook(book) {
  const enrichment = _bookEnrichment(book);
  const rawTokens = [
    String(book?.genre || ''),
    String(enrichment.genre || ''),
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

function buildGenreAwareRotation(book, variantCount) {
  const total = Math.max(1, Number(variantCount || 1));
  const genreConfig = genrePromptConfigForBook(book) || GENRE_PROMPT_MAP.literature || null;
  const basePromptName = String(genreConfig?.base || DEFAULT_GENRE_BASE_PROMPT_NAME).trim() || DEFAULT_GENRE_BASE_PROMPT_NAME;
  const basePromptId = promptIdForName(basePromptName) || ALEXANDRIA_PROMPT_ID_BY_NAME[DEFAULT_GENRE_BASE_PROMPT_NAME];
  const recommendedWildcardIds = (Array.isArray(genreConfig?.wildcards) ? genreConfig.wildcards : [])
    .map((name) => promptIdForName(name))
    .filter(Boolean);
  const orderedWildcards = Array.from(new Set(recommendedWildcardIds.concat(
    ALEXANDRIA_WILDCARD_IDS.filter((id) => !recommendedWildcardIds.includes(id)),
  )));
  const scenes = buildScenePool(book, total);
  const promptIds = [];

  if (total <= 1) {
    promptIds.push(basePromptId);
  } else if (total <= 5) {
    promptIds.push(basePromptId);
    for (let index = 1; index < total; index += 1) {
      promptIds.push(orderedWildcards[(index - 1) % orderedWildcards.length] || basePromptId);
    }
  } else {
    const baseCount = Math.ceil(total / 2);
    const wildcardCount = total - baseCount;
    const bases = Array.from({ length: baseCount }, () => basePromptId);
    const wildcards = Array.from({ length: wildcardCount }, (_, index) => orderedWildcards[index % orderedWildcards.length] || basePromptId);
    while (promptIds.length < total) {
      if (bases.length) promptIds.push(bases.shift());
      if (promptIds.length >= total) break;
      if (wildcards.length) promptIds.push(wildcards.shift());
    }
  }

  return promptIds.map((promptId, index) => ({
    promptId: promptId || basePromptId,
    sceneOverride: String(scenes[index] || scenes[0] || defaultSceneForBook(book)).trim(),
  }));
}

window.__ITERATE_TEST_HOOKS__.buildGenreAwareRotation = ({ book, variantCount }) => buildGenreAwareRotation(book, variantCount);

function suggestedWildcardPromptForBook(book) {
  const config = genrePromptConfigForBook(book);
  const names = Array.isArray(config?.wildcards) ? config.wildcards : [];
  if (!names.length) return null;
  const seed = Number(book?.number || book?.id || 0);
  const index = Math.abs(seed || 0) % names.length;
  return findPromptByName(names[index]);
}

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

function backendResultRowForJob(job) {
  try {
    const parsed = JSON.parse(String(job?.results_json || '{}'));
    return parsed?.result && typeof parsed.result === 'object' ? parsed.result : null;
  } catch {
    return null;
  }
}

function saveRawRequestPayloadForJob(job) {
  const row = backendResultRowForJob(job) || {};
  return {
    job_id: backendJobIdForJob(job),
    expected_variant: Number(row?.variant || job?.variant || 0) || 0,
    expected_model: String(row?.model || job?.model || '').trim(),
    expected_raw_art_path: String(row?.raw_art_path || '').trim(),
    expected_saved_composited_path: String(row?.saved_composited_path || '').trim(),
  };
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function resultCardPromptLabel(job) {
  return String(job?.prompt_name || job?.style_label || 'Default').trim() || 'Default';
}

function sceneSnippetText(value, maxLength = 84) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
}

function saveRawButtonState(job) {
  const status = String(job?.save_raw_status || '').trim().toLowerCase();
  const driveUrl = String(job?.save_raw_drive_url || '').trim();
  const warning = String(job?.save_raw_drive_warning || job?.save_raw_warning || '').trim();
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
      label: '↻ Retry Drive',
      style: 'background:#d4af37;color:#0a1628;font-weight:600;',
      title: truncatedWarning || 'Files could not be saved to Google Drive. Retry the upload.',
      driveUrl,
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

function applySaveRawPayloadToJob(job, data) {
  if (!job || !data || typeof data !== 'object') return;
  job.save_raw_status = String(data.status || (data.drive_ok ? 'saved' : 'partial') || '').trim();
  job.save_raw_warning = String(data.warning || '').trim();
  job.save_raw_drive_warning = String(data.drive_warning || data.warning || '').trim();
  job.save_raw_drive_url = String(data.drive_url || '').trim();
  job.save_raw_drive_folder_id = String(data.drive_folder_id || '').trim();
  job.save_raw_local_folder = String(data.local_folder || '').trim();
  job.save_raw_saved_files = Array.isArray(data.saved_files) ? data.saved_files : [];
  job.save_raw_missing_files = Array.isArray(data.missing_files) ? data.missing_files : [];
  job.save_raw_drive_uploaded = Array.isArray(data.drive_uploaded) ? data.drive_uploaded : [];
  job.save_raw_drive_failed = Array.isArray(data.drive_failed) ? data.drive_failed : [];
  job.save_raw_retry_available = Boolean(data.retry_available);
  job.save_raw_saved_at = new Date().toISOString();
}

function savedPromptForJob(job) {
  const explicitId = String(job?.save_prompt_id || '').trim();
  if (explicitId) {
    const direct = DB.dbGet('prompts', explicitId);
    if (direct) return direct;
  }
  const promptText = normalizedPromptText(job?.prompt);
  if (!promptText) return null;
  return DB.dbGetAll('prompts').find((prompt) => normalizedPromptText(prompt?.prompt_template) === promptText) || null;
}

function savePromptButtonState(job) {
  const status = String(job?.status || '').trim().toLowerCase();
  const promptText = normalizedPromptText(job?.prompt);
  const savedPrompt = savedPromptForJob(job);
  if (savedPrompt) {
    return {
      label: '✅ Saved',
      title: `Saved to prompt library as ${String(savedPrompt.name || 'winner prompt')}.`,
      disabled: true,
      promptId: String(savedPrompt.id || '').trim(),
      className: 'save-prompt-btn saved',
    };
  }
  return {
    label: '💾 Save Prompt',
    title: promptText && status === 'completed' ? 'Save this prompt to your library' : 'Complete a generation first.',
    disabled: !(promptText && status === 'completed'),
    promptId: '',
    className: 'save-prompt-btn',
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

function debounce(fn, wait = 50) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), Math.max(0, Number(wait || 0)));
  };
}

function normalizeBookSearchText(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[’']/g, '')
    .toLowerCase()
    .trim();
}

function bookOptionLabel(book) {
  const number = String(book?.number || book?.id || '').trim();
  const title = String(book?.title || '').trim() || `Book ${number || '?'}`;
  const author = String(book?.author || '').trim();
  return `${number}. ${title}${author ? ` — ${author}` : ''}`.trim();
}

function filterBooksForCombobox(books, query, limit = 80) {
  const rows = [...(Array.isArray(books) ? books : [])]
    .filter(Boolean)
    .sort((left, right) => Number(left?.number || 0) - Number(right?.number || 0));
  const trimmed = String(query || '').trim();
  if (!trimmed) return rows.slice(0, Math.max(1, Number(limit || 80)));

  const normalizedQuery = normalizeBookSearchText(trimmed);
  const numericQuery = /^\d+$/.test(trimmed) ? trimmed : '';
  const matches = rows.map((book) => {
    const numberText = String(book?.number || book?.id || '').trim();
    const titleText = normalizeBookSearchText(book?.title || '');
    const authorText = normalizeBookSearchText(book?.author || '');
    const labelText = normalizeBookSearchText(bookOptionLabel(book));
    let score = Number.POSITIVE_INFINITY;

    if (numericQuery) {
      if (numberText === numericQuery) score = 0;
      else if (numberText.startsWith(numericQuery)) score = 1;
      else if (labelText.includes(normalizedQuery)) score = 6;
    }

    if (!Number.isFinite(score)) {
      if (titleText.startsWith(normalizedQuery)) score = 2;
      else if (authorText.startsWith(normalizedQuery)) score = 3;
      else if (titleText.includes(normalizedQuery)) score = 4;
      else if (authorText.includes(normalizedQuery)) score = 5;
      else if (labelText.includes(normalizedQuery)) score = 6;
    }

    return { book, score };
  }).filter((item) => Number.isFinite(item.score));

  return matches
    .sort((left, right) => left.score - right.score || Number(left.book?.number || 0) - Number(right.book?.number || 0))
    .slice(0, Math.max(1, Number(limit || 80)))
    .map((item) => item.book);
}

window.__ITERATE_TEST_HOOKS__.filterBooksForCombobox = ({ books, query, limit }) => filterBooksForCombobox(books, query, limit);

window.Pages.iterate = {
  async render() {
    const content = document.getElementById('content');
    const catalogId = 'classics';
    await OpenRouter.init().catch(() => OpenRouter.MODELS);
    let books = DB.dbGetAll('books');
    if (!books.length || books.some((book) => !DB.bookHasPromptEnrichment(book))) {
      books = await DB.loadBooks(catalogId);
    }
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
      .map((book) => `<option value="${book.id}">${escapeHtml(bookOptionLabel(book))}</option>`)
      .join('');
    const promptOptions = [`<option value="">${AUTO_ROTATE_PROMPT_OPTION_LABEL}</option>`]
      .concat(prompts.map((p) => `<option value="${p.id}">${p.name}</option>`))
      .join('');

    content.innerHTML = `
      <div class="card">
        <div class="card-header"><h3 class="card-title">Generate Illustrations</h3>
          <div class="filters-bar">
            <span class="text-muted">Quick</span>
            <label class="checkbox-item"><input id="iterModeToggle" type="checkbox" checked /> <span>Advanced</span></label>
          </div>
        </div>

        <div class="form-group">
          <div class="flex justify-between items-center">
            <label class="form-label">Book</label>
            <button class="btn btn-secondary btn-sm" id="iterSyncBooksBtn">Sync</button>
          </div>
          <div class="book-combobox" id="iterBookCombobox">
            <input
              class="form-input"
              id="iterBookSearch"
              type="text"
              placeholder="Type book number or title to search..."
              autocomplete="off"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded="false"
              aria-controls="iterBookResults"
            />
            <div class="book-combobox-dropdown hidden" id="iterBookResults" role="listbox"></div>
          </div>
          <select class="form-select hidden" id="iterBookSelect" aria-hidden="true" tabindex="-1">
            <option value="">— Select a book —</option>
            ${options}
          </select>
          <p class="text-xs text-muted mt-8" id="iterBookSyncStatus">${books.length ? `${books.length} books loaded (catalog).` : 'No books loaded yet'}</p>
        </div>

        <div id="iterAdvanced">
          <div class="form-group">
            <label class="form-label">Models (best → budget, top → bottom)</label>
            <input class="form-input model-search-input" id="iterModelSearch" placeholder="Search model name / provider / id..." />
            <div class="model-toolbar mt-8">
              <button class="filter-chip active" data-model-filter="recommended">Recommended</button>
              <button class="filter-chip" data-model-filter="all">All</button>
              <button class="filter-chip" data-model-filter="openrouter">OpenRouter</button>
              <button class="filter-chip" data-model-filter="gemini">Gemini</button>
              <button class="filter-chip" data-model-filter="nano">Nano Pro only</button>
              <button class="filter-chip" data-model-action="select-visible">Select visible</button>
              <button class="filter-chip" data-model-action="clear">Clear</button>
            </div>
            <p class="text-xs text-muted mt-8" id="iterModelSummary"></p>
            <p class="text-xs text-muted mt-8" id="iterCostBreakdown"></p>
            <div class="model-card-grid" id="iterModelGrid"></div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Variants per model</label>
              <select class="form-select" id="iterVariants">${Array.from({ length: 10 }, (_, i) => `<option value="${i + 1}" ${i === 0 ? 'selected' : ''}>${i + 1}</option>`).join('')}</select>
            </div>
            <div class="form-group">
              <label class="form-label">Prompt template</label>
              <select class="form-select" id="iterPromptSel">${promptOptions}</select>
              <div class="filters-bar mt-8" id="iterPromptFilterBar">
                <button class="filter-chip active" type="button" data-prompt-filter="all">All</button>
                <button class="filter-chip" type="button" data-prompt-filter="alexandria">Alexandria</button>
                <button class="filter-chip" type="button" data-prompt-filter="winner">Winners</button>
              </div>
              <div class="text-xs text-muted mt-8 hidden" id="iterPromptRotationInfo">${escapeHtml(AUTO_ROTATE_PROMPT_INFO)}</div>
              <div class="text-xs text-muted mt-8" id="iterWildcardSuggestion"></div>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Custom prompt</label>
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
        </div>

        <div class="flex justify-between items-center">
          <span class="text-muted" id="iterCostEst">Est. cost: $0.000</span>
          <div class="flex gap-8">
            <button class="btn btn-secondary" id="iterCancelBtn">Cancel All</button>
            <button class="btn btn-primary" id="iterGenBtn">Generate</button>
          </div>
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
    const bookComboboxEl = document.getElementById('iterBookCombobox');
    const bookSearchEl = document.getElementById('iterBookSearch');
    const bookResultsEl = document.getElementById('iterBookResults');
    const syncBtn = document.getElementById('iterSyncBooksBtn');
    const syncStatus = document.getElementById('iterBookSyncStatus');
    const modeToggle = document.getElementById('iterModeToggle');
    const advanced = document.getElementById('iterAdvanced');
    const variantsEl = document.getElementById('iterVariants');
    const promptSelEl = document.getElementById('iterPromptSel');
    const promptRotationInfoEl = document.getElementById('iterPromptRotationInfo');
    const wildcardSuggestionEl = document.getElementById('iterWildcardSuggestion');
    const customPromptEl = document.getElementById('iterPrompt');
    const varFieldsEl = document.getElementById('iterVarFields');
    const sceneEl = document.getElementById('iterScene');
    const moodEl = document.getElementById('iterMood');
    const eraEl = document.getElementById('iterEra');
    const modelSearchEl = document.getElementById('iterModelSearch');
    const modelGridEl = document.getElementById('iterModelGrid');
    const modelSummaryEl = document.getElementById('iterModelSummary');
    const modelFilterButtons = Array.from(content.querySelectorAll('[data-model-filter]'));
    const modelActionButtons = Array.from(content.querySelectorAll('[data-model-action]'));
    const promptFilterButtons = Array.from(content.querySelectorAll('[data-prompt-filter]'));

    const selectedBook = () => {
      const bookId = Number(selectEl?.value || 0);
      return books.find((row) => Number(row.id) === bookId) || null;
    };

    let visibleBookOptions = [];
    let activeBookOptionIndex = -1;

    const closeBookResults = () => {
      activeBookOptionIndex = -1;
      visibleBookOptions = [];
      if (bookResultsEl) {
        bookResultsEl.innerHTML = '';
        bookResultsEl.classList.add('hidden');
      }
      bookSearchEl?.setAttribute('aria-expanded', 'false');
      bookSearchEl?.removeAttribute('aria-activedescendant');
    };

    const syncBookSearchFromSelection = () => {
      if (!bookSearchEl) return;
      const book = selectedBook();
      bookSearchEl.value = book ? bookOptionLabel(book) : '';
      bookSearchEl.dataset.selectedValue = bookSearchEl.value;
    };

    const setActiveBookOption = (nextIndex) => {
      if (!bookResultsEl || !visibleBookOptions.length) return;
      activeBookOptionIndex = Math.max(0, Math.min(nextIndex, visibleBookOptions.length - 1));
      Array.from(bookResultsEl.querySelectorAll('.book-combobox-option')).forEach((node, index) => {
        const isActive = index === activeBookOptionIndex;
        node.classList.toggle('active', isActive);
        node.setAttribute('aria-selected', isActive ? 'true' : 'false');
        if (isActive) {
          bookSearchEl?.setAttribute('aria-activedescendant', node.id);
          node.scrollIntoView({ block: 'nearest' });
        }
      });
    };

    const renderBookResults = (rows) => {
      if (!bookResultsEl || !bookSearchEl) return;
      visibleBookOptions = Array.isArray(rows) ? rows : [];
      activeBookOptionIndex = visibleBookOptions.length ? 0 : -1;
      if (!visibleBookOptions.length) {
        bookResultsEl.innerHTML = '<div class="book-combobox-empty">No matching books</div>';
        bookResultsEl.classList.remove('hidden');
        bookSearchEl.setAttribute('aria-expanded', 'true');
        bookSearchEl.removeAttribute('aria-activedescendant');
        return;
      }
      bookResultsEl.innerHTML = visibleBookOptions.map((book, index) => {
        const active = index === activeBookOptionIndex;
        return `
          <button
            class="book-combobox-option ${active ? 'active' : ''}"
            id="iterBookOption-${escapeHtml(String(book.id || book.number || index))}"
            type="button"
            role="option"
            aria-selected="${active ? 'true' : 'false'}"
            data-book-id="${escapeHtml(String(book.id || ''))}"
          >
            <span class="book-combobox-number">${escapeHtml(String(book.number || book.id || ''))}.</span>
            <span class="book-combobox-text">
              <span class="book-combobox-title">${escapeHtml(String(book.title || `Book ${book.number || '?'}`))}</span>
              <span class="book-combobox-meta">${escapeHtml(String(book.author || 'Unknown author'))}</span>
            </span>
          </button>
        `;
      }).join('');
      bookResultsEl.classList.remove('hidden');
      bookSearchEl.setAttribute('aria-expanded', 'true');
      const activeNode = bookResultsEl.querySelector('.book-combobox-option.active');
      if (activeNode) {
        bookSearchEl.setAttribute('aria-activedescendant', activeNode.id);
      } else {
        bookSearchEl.removeAttribute('aria-activedescendant');
      }
    };

    const openBookResults = (query = String(bookSearchEl?.value || '')) => {
      renderBookResults(filterBooksForCombobox(books, query, 80));
    };

    const applyBookSelection = (book, { focusInput = false } = {}) => {
      if (!book || !selectEl) return;
      const bookId = String(book.id || book.number || '').trim();
      if (!bookId) return;
      selectEl.value = bookId;
      syncBookSearchFromSelection();
      closeBookResults();
      if (focusInput) bookSearchEl?.focus();
      selectEl.dispatchEvent(new Event('change'));
    };

    const scheduleBookSearch = debounce(() => {
      openBookResults(String(bookSearchEl?.value || ''));
    }, 50);

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

    const updateVariableFields = (templateObj, { forceDefaults = false, promptId = '', customPrompt = '' } = {}) => {
      if (!varFieldsEl || !sceneEl || !moodEl || !eraEl) return;
      const book = selectedBook();
      const activePromptText = String(templateObj?.prompt_template || customPrompt || customPromptEl?.value || '').trim();
      const usesAlexandriaFields = Boolean(book) && (isAutoRotateSelection(promptId, customPrompt) || activePromptText.includes('{SCENE}'));
      varFieldsEl.classList.toggle('hidden', !usesAlexandriaFields);
      if (!book) {
        if (forceDefaults) {
          sceneEl.value = '';
          moodEl.value = '';
          eraEl.value = '';
        }
        return;
      }
      if (forceDefaults || !String(sceneEl.value || '').trim()) sceneEl.value = defaultSceneForBook(book);
      if (forceDefaults || !String(moodEl.value || '').trim()) moodEl.value = defaultMoodForBook(book);
      if (forceDefaults || !String(eraEl.value || '').trim()) eraEl.value = defaultEraForBook(book);
    };

    const syncPromptRotationInfo = (promptId = String(promptSelEl?.value || '').trim(), customPrompt = String(customPromptEl?.value || '').trim()) => {
      if (!promptRotationInfoEl) return;
      const shouldShow = Boolean(selectedBook()) && isAutoRotateSelection(promptId, customPrompt);
      promptRotationInfoEl.classList.toggle('hidden', !shouldShow);
    };

    const applyPromptSelection = (promptId, { forceAlexandriaDefaults = false } = {}) => {
      const promptIdToken = String(promptId || '').trim();
      const selected = promptIdToken ? DB.dbGet('prompts', promptIdToken) : null;
      if (selected?.prompt_template && customPromptEl) {
        customPromptEl.value = String(selected.prompt_template);
      } else if (!promptIdToken && customPromptEl) {
        customPromptEl.value = '';
      }
      updateVariableFields(selected, {
        forceDefaults: forceAlexandriaDefaults,
        promptId: promptIdToken,
        customPrompt: String(customPromptEl?.value || '').trim(),
      });
      syncPromptRotationInfo(promptIdToken, String(customPromptEl?.value || '').trim());
      updateWildcardSuggestion(selectedBook());
      return selected;
    };

    const autoSelectGenrePrompt = () => {
      const book = selectedBook();
      if (!promptSelEl) {
        updateVariableFields(null, { forceDefaults: true, promptId: '', customPrompt: '' });
        updateWildcardSuggestion(book);
        syncPromptRotationInfo('', '');
        return;
      }
      promptSelEl.value = '';
      if (variantsEl) variantsEl.value = '10';
      applyPromptSelection('', { forceAlexandriaDefaults: true });
      updateCost();
    };

    _defaultSelectedModelIds = defaultSelectedModelIds(OpenRouter.MODELS);
    _defaultModelId = _defaultSelectedModelIds[0] || normalizedModelId(OpenRouter.MODELS[0] || null) || null;
    _selectedModelIds = new Set(_defaultSelectedModelIds);
    _lastVisibleModelIds = [];
    let activeModelFilter = 'recommended';
    let modelSearchText = '';
    let activePromptFilter = 'all';
    document.body.dataset.iterPromptFilter = activePromptFilter;

    const syncPromptFilterButtons = () => {
      promptFilterButtons.forEach((btn) => {
        btn.classList.toggle('active', String(btn.dataset.promptFilter || 'all') === activePromptFilter);
      });
    };

    modeToggle?.addEventListener('change', () => {
      advanced.classList.toggle('hidden', !modeToggle.checked);
    });

    selectEl?.addEventListener('change', () => {
      _selectedBookId = Number(selectEl.value || 0) || null;
      syncBookSearchFromSelection();
      autoSelectGenrePrompt();
      this.loadExistingResults();
    });

    bookSearchEl?.addEventListener('focus', () => {
      openBookResults(String(bookSearchEl.value || ''));
    });
    bookSearchEl?.addEventListener('click', () => {
      openBookResults(String(bookSearchEl.value || ''));
    });
    bookSearchEl?.addEventListener('input', () => {
      scheduleBookSearch();
    });
    bookSearchEl?.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (bookResultsEl?.classList.contains('hidden')) openBookResults(String(bookSearchEl.value || ''));
        else setActiveBookOption(activeBookOptionIndex + 1);
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (bookResultsEl?.classList.contains('hidden')) openBookResults(String(bookSearchEl.value || ''));
        else setActiveBookOption(activeBookOptionIndex - 1);
        return;
      }
      if (event.key === 'Enter') {
        if (bookResultsEl?.classList.contains('hidden')) return;
        event.preventDefault();
        const book = visibleBookOptions[activeBookOptionIndex] || visibleBookOptions[0] || null;
        if (book) applyBookSelection(book, { focusInput: true });
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        syncBookSearchFromSelection();
        closeBookResults();
      }
    });
    bookResultsEl?.addEventListener('mousemove', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const option = target?.closest('.book-combobox-option');
      if (!option) return;
      const nextIndex = Array.from(bookResultsEl.querySelectorAll('.book-combobox-option')).indexOf(option);
      if (nextIndex >= 0 && nextIndex !== activeBookOptionIndex) {
        setActiveBookOption(nextIndex);
      }
    });
    bookResultsEl?.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const option = target?.closest('.book-combobox-option');
      if (!option) return;
      const bookId = Number(option.dataset.bookId || 0);
      const book = books.find((row) => Number(row.id) === bookId) || null;
      if (book) applyBookSelection(book, { focusInput: true });
    });
    if (this._bookClickAwayHandler) {
      document.removeEventListener('click', this._bookClickAwayHandler);
    }
    this._bookClickAwayHandler = (event) => {
      const target = event.target instanceof Node ? event.target : null;
      if (!target || !bookComboboxEl?.contains(target)) {
        syncBookSearchFromSelection();
        closeBookResults();
      }
    };
    document.addEventListener('click', this._bookClickAwayHandler);

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
            .concat(sorted.map((book) => `<option value="${book.id}">${escapeHtml(bookOptionLabel(book))}</option>`))
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
        syncBookSearchFromSelection();
        if (document.activeElement === bookSearchEl) {
          openBookResults(String(bookSearchEl?.value || ''));
        }
        updateHeader();
        if (driveTotal > 0) {
          Toast.success(`Catalog synced: ${sorted.length} books (Drive found ${driveTotal})`);
        } else {
          Toast.success(`Catalog synced: ${sorted.length} books`);
        }
        autoSelectGenrePrompt();
      } catch (err) {
        if (syncStatus) syncStatus.textContent = 'Sync failed';
        Toast.error(`Sync failed: ${err.message || err}`);
      } finally {
        syncBtn.disabled = false;
        syncBtn.textContent = previous || 'Sync';
      }
    });

    const updateCost = () => {
      const variants = Number(variantsEl?.value || 1);
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

    variantsEl?.addEventListener('change', updateCost);
    promptFilterButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        activePromptFilter = String(btn.dataset.promptFilter || 'all').trim().toLowerCase() || 'all';
        document.body.dataset.iterPromptFilter = activePromptFilter;
        syncPromptFilterButtons();
        const currentPromptId = String(promptSelEl?.value || '').trim();
        this.refreshPromptDropdown(currentPromptId);
        const nextPromptId = String(promptSelEl?.value || '').trim();
        applyPromptSelection(nextPromptId, { forceAlexandriaDefaults: activePromptFilter !== 'winner' });
      });
    });
    promptSelEl?.addEventListener('change', () => {
      const promptId = String(promptSelEl.value || '').trim();
      if (variantsEl) {
        if (!promptId) variantsEl.value = '10';
        else if (String(variantsEl.value || '').trim() === '10') variantsEl.value = '1';
        updateCost();
      }
      applyPromptSelection(promptId, { forceAlexandriaDefaults: true });
    });
    customPromptEl?.addEventListener('input', () => {
      const promptId = String(promptSelEl?.value || '').trim();
      const selected = promptId ? DB.dbGet('prompts', promptId) : null;
      const customPrompt = String(customPromptEl?.value || '').trim();
      updateVariableFields(selected, { forceDefaults: false, promptId, customPrompt });
      syncPromptRotationInfo(promptId, customPrompt);
    });
    renderModels();
    this.refreshPromptDropdown(String(promptSelEl?.value || '').trim());
    syncPromptFilterButtons();
    syncPromptRotationInfo();

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
      syncBookSearchFromSelection();
      autoSelectGenrePrompt();
    } else {
      syncBookSearchFromSelection();
      updateWildcardSuggestion(null);
      updateVariableFields(null, { forceDefaults: false });
    }
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

    const variantCount = Number(document.getElementById('iterVariants')?.value || 1);
    const promptId = String(document.getElementById('iterPromptSel')?.value || '').trim();
    const customPrompt = document.getElementById('iterPrompt')?.value || '';
    const sceneVal = document.getElementById('iterScene')?.value || '';
    const moodVal = document.getElementById('iterMood')?.value || '';
    const eraVal = document.getElementById('iterEra')?.value || '';
    const books = DB.dbGetAll('books');
    const book = books.find((b) => Number(b.id) === bookId);
    if (!book) return;

    const templateObj = promptId ? findPromptById(promptId) : null;
    const resolvedScene = String(sceneVal || defaultSceneForBook(book)).trim();
    const resolvedMood = String(moodVal || defaultMoodForBook(book)).trim();
    const resolvedEra = String(eraVal || defaultEraForBook(book)).trim();
    const trimmedCustomPrompt = String(customPrompt || '').trim();
    const defaultScene = String(defaultSceneForBook(book)).trim();
    const hasManualSceneOverride = Boolean(String(sceneVal || '').trim()) && String(sceneVal || '').trim() !== defaultScene;
    const scenePool = buildScenePool(book, variantCount);
    const styleSelections = StyleDiversifier.selectDiverseStyles(selectedModels.length * variantCount);
    const rotateAssignments = isAutoRotateSelection(promptId, trimmedCustomPrompt)
      ? buildGenreAwareRotation(book, variantCount)
      : [];
    const rotateTemplates = rotateAssignments.map((assignment) => ({
      promptId: String(assignment?.promptId || '').trim(),
      sceneOverride: String(assignment?.sceneOverride || '').trim(),
      templateObj: findPromptById(assignment?.promptId),
    }));
    if (rotateTemplates.some((row) => !row.templateObj)) {
      Toast.error('Prompt rotation is unavailable because one or more Alexandria prompts are missing from the library.');
      return;
    }
    const selectedCoverId = String(book.cover_jpg_id || book.drive_cover_id || '').trim();
    const selectedCoverBookNumber = Number(book.number || book.id || bookId || 0);

    const jobs = [];
    let styleIndex = 0;
    selectedModels.forEach((model) => {
      for (let variant = 1; variant <= variantCount; variant += 1) {
        const style = styleSelections[styleIndex % styleSelections.length];
        styleIndex += 1;
        const assignment = rotateTemplates[variant - 1] || null;
        const assignedPromptId = String(assignment?.promptId || promptId).trim();
        const assignedTemplate = assignment?.templateObj || templateObj || null;
        const rotatedScene = hasManualSceneOverride
          ? resolvedScene
          : String(scenePool[(variant - 1) % scenePool.length] || resolvedScene).trim();
        const assignedScene = String(assignment?.sceneOverride || rotatedScene || resolvedScene).trim();
        const promptPayload = buildGenerationJobPrompt({
          book,
          templateObj: assignedTemplate,
          promptId: assignedPromptId,
          customPrompt: assignment ? '' : customPrompt,
          sceneVal: assignedScene,
          moodVal,
          eraVal,
          style,
        });
        jobs.push({
          id: uuid(),
          book_id: bookId,
          model,
          fallback_models: selectedModels.filter((candidate) => candidate !== model),
          variant,
          status: 'queued',
          prompt: promptPayload.prompt,
          style_id: promptPayload.styleId,
          style_label: promptPayload.styleLabel,
          prompt_source: promptPayload.promptSource,
          backend_prompt_source: promptPayload.backendPromptSource,
          compose_prompt: promptPayload.composePrompt,
          preserve_prompt_text: promptPayload.preservePromptText,
          library_prompt_id: promptPayload.libraryPromptId,
          prompt_name: String(assignedTemplate?.name || promptPayload.styleLabel || '').trim(),
          prompt_negative_prompt: String(assignedTemplate?.negative_prompt || '').trim(),
          scene_description: assignedScene,
          mood: resolvedMood,
          era: resolvedEra,
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
      }
    });

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
      const savePromptState = savePromptButtonState(job);
      const promptLabel = resultCardPromptLabel(job);
      const sceneText = String(job.scene_description || '').replace(/\s+/g, ' ').trim();
      const sceneSnippet = sceneSnippetText(sceneText);
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
            <div class="result-card-prompt-badge" title="${escapeHtml(promptLabel)}">${escapeHtml(promptLabel)}</div>
            ${sceneSnippet ? `<div class="result-card-scene-snippet" title="${escapeHtml(sceneText)}">${escapeHtml(sceneSnippet)}</div>` : ''}
            <div class="card-meta result-card-cost">$${Number(job.cost_usd || 0).toFixed(3)}</div>
            ${errorText ? `<div class="card-meta text-danger">${errorText}</div>` : ''}
            <div class="result-card-actions mt-8">
              <button class="btn btn-secondary btn-sm" data-dl-comp="${job.id}" ${showDownloads ? '' : 'disabled'}>⬇ Download</button>
              <button class="btn btn-secondary btn-sm" data-dl-raw="${job.id}" ${showDownloads ? '' : 'disabled'}>⬇ Raw</button>
              <button class="btn btn-secondary btn-sm" data-view-qa-book="${Number(job.book_id || 0)}" ${showComparison ? '' : 'disabled'}>Compare</button>
              <button class="btn btn-sm" data-save-raw="${job.id}" data-drive-url="${escapeHtml(saveRawState.driveUrl)}" data-save-status="${escapeHtml(saveRawState.status)}" ${showDownloads ? '' : 'disabled'} style="${saveRawState.style}" title="${escapeHtml(saveRawState.title)}">${escapeHtml(saveRawState.label)}</button>
              <button class="btn btn-sm ${escapeHtml(savePromptState.className)}" data-save-prompt="${job.id}" data-prompt-id="${escapeHtml(savePromptState.promptId)}" ${savePromptState.disabled ? 'disabled' : ''} title="${escapeHtml(savePromptState.title)}">${escapeHtml(savePromptState.label)}</button>
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
      window.open(`/#visual-qa?book=${encodeURIComponent(String(book))}&open=1`, '_blank', 'noopener,noreferrer');
    }));
    grid.querySelectorAll('[data-save-raw]').forEach((btn) => btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await this.saveRaw(btn.dataset.saveRaw, btn);
    }));
    grid.querySelectorAll('[data-save-prompt]').forEach((btn) => btn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.savePromptFromJob(btn.dataset.savePrompt, btn);
    }));
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
    const currentStatus = String(button.dataset.saveStatus || job.save_raw_status || '').trim().toLowerCase();
    const existingDriveUrl = String(button.dataset.driveUrl || job.save_raw_drive_url || '').trim();
    if (currentStatus === 'saved' && existingDriveUrl) {
      window.open(existingDriveUrl, '_blank', 'noopener,noreferrer');
      return;
    }
    const requestPayload = saveRawRequestPayloadForJob(job);
    if (!requestPayload.job_id) {
      Toast.error('Save Raw failed: backend job id is missing.');
      return;
    }
    if (!requestPayload.expected_raw_art_path && !requestPayload.expected_saved_composited_path) {
      Toast.error('Save Raw refused: this result does not have immutable saved artifacts. Regenerate it before saving.');
      return;
    }

    const retryMode = currentStatus === 'partial';
    const originalText = String(button.textContent || '💾 Save Raw');
    const originalBackground = button.style.background;
    const originalColor = button.style.color;
    button.disabled = true;
    button.textContent = retryMode ? 'Retrying...' : 'Saving...';

    try {
      const resp = await fetch(retryMode ? '/api/retry-drive-upload' : '/api/save-raw', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestPayload),
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        throw new Error(data.message || data.error || `HTTP ${resp.status}`);
      }

      applySaveRawPayloadToJob(job, data);
      DB.dbPut('jobs', job);
      this.loadExistingResults();

      if (String(data.status || '').trim().toLowerCase() === 'partial') {
        Toast.error(String(data.drive_warning || 'Files could not be saved to Google Drive. Saved locally only.').trim());
      } else if (retryMode) {
        Toast.success('Google Drive upload completed.');
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
    const prompts = filterPromptsForIterate(sortPromptsForUI(DB.dbGetAll('prompts')), document.body?.dataset.iterPromptFilter || 'all');
    promptSel.innerHTML = [`<option value="">${AUTO_ROTATE_PROMPT_OPTION_LABEL}</option>`]
      .concat(prompts.map((p) => `<option value="${p.id}">${p.name}</option>`))
      .join('');
    if (selectedId && prompts.some((prompt) => String(prompt.id || '') === String(selectedId))) {
      promptSel.value = String(selectedId);
    } else {
      promptSel.value = '';
    }
  },

  async savePromptFromJob(jobId, button) {
    const job = DB.dbGet('jobs', jobId);
    if (!job?.prompt) return;
    const existing = savedPromptForJob(job);
    if (existing) {
      job.save_prompt_id = String(existing.id || '').trim();
      job.save_prompt_status = 'saved';
      DB.dbPut('jobs', job);
      this.loadExistingResults();
      return;
    }

    const backendJobId = backendJobIdForJob(job) || String(job.id || '').trim();
    const originalText = String(button?.textContent || '💾 Save Prompt');
    if (button) {
      button.disabled = true;
      button.textContent = 'Saving...';
    }

    try {
      const response = await fetch('/api/save-prompt?catalog=classics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: backendJobId,
          book_id: String(job.book_id || '').trim(),
          prompt_text: String(job.prompt || '').trim(),
          scene_description: String(job.scene_description || '').trim(),
          mood: String(job.mood || '').trim(),
          era: String(job.era || '').trim(),
          model_id: String(job.model || '').trim(),
          library_prompt_id: String(job.library_prompt_id || '').trim(),
          quality_score: job.quality_score ?? null,
          notes: '',
          negative_prompt: String(job.prompt_negative_prompt || '').trim(),
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.message || data.error || `HTTP ${response.status}`);
      }
      job.save_prompt_id = String(data.prompt_id || '').trim();
      job.save_prompt_status = 'saved';
      job.save_prompt_saved_at = new Date().toISOString();
      job.save_prompt_already_exists = Boolean(data.already_exists);
      DB.dbPut('jobs', job);
      await DB.loadPrompts('classics');
      this.refreshPromptDropdown(String(document.getElementById('iterPromptSel')?.value || '').trim());
      this.loadExistingResults();
      Toast.success(data.already_exists ? 'Prompt already saved' : 'Prompt saved');
    } catch (err) {
      if (button) {
        button.disabled = false;
        button.textContent = originalText;
      }
      Toast.error(`Prompt save failed: ${err.message || err}`);
    }
  },
};
