window.Pages = window.Pages || {};

let _selectedBookId = null;
let _unsubscribe = null;
let _selectedModelIds = new Set();
let _defaultModelId = null;
let _lastVisibleModelIds = [];
const PREFERRED_DEFAULT_MODELS = [
  'openrouter/google/gemini-2.5-flash-image',
  'google/gemini-2.5-flash-image',
  'nano-banana-pro',
];

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

function resolvePreviewSources(job, keyPrefix = 'display', preferRaw = false) {
  const sources = [];
  const seen = new Set();
  const pushSource = (value, suffix) => {
    if (!isRenderableImageSource(value)) return;
    const src = getBlobUrl(value, `${job.id}-${keyPrefix}-${suffix}`);
    if (!src || seen.has(src)) return;
    seen.add(src);
    sources.push(src);
    if (typeof value === 'string') {
      const normalized = src || '';
      const isDirectPath = normalized.startsWith('/') && !normalized.startsWith('//');
      if (isDirectPath && !normalized.startsWith('/api/thumbnail')) {
        const rel = normalized.replace(/^\/+/, '');
        const thumb = `/api/thumbnail?path=${encodeURIComponent(rel)}&size=large`;
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
    const src = getBlobUrl(value, `${job.id}-${keyPrefix}-${suffix}`);
    if (!src || seen.has(src)) return;
    seen.add(src);
    sources.push(src);
    if (typeof value === 'string') {
      const normalized = src || '';
      const isDirectPath = normalized.startsWith('/') && !normalized.startsWith('//');
      if (isDirectPath && !normalized.startsWith('/api/thumbnail')) {
        const rel = normalized.replace(/^\/+/, '');
        const thumb = `/api/thumbnail?path=${encodeURIComponent(rel)}&size=large`;
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
  try {
    const response = await fetch(source, { cache: 'no-store' });
    if (!response.ok) return null;
    return await response.blob();
  } catch {
    return null;
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

function applyPromptPlaceholders(promptText, book) {
  return String(promptText || '')
    .replaceAll('{title}', String(book?.title || ''))
    .replaceAll('{author}', String(book?.author || ''));
}

function resolvePrompt(templateObj, book, customPrompt) {
  const custom = String(customPrompt || '').trim();
  if (custom) {
    return applyPromptPlaceholders(custom, book).trim();
  }
  const base = templateObj?.prompt_template || `Create a colorful circular medallion illustration for "{title}" by {author}.`;
  return `${applyPromptPlaceholders(base, book)} No text, no letters, no logos, no border, no frame, colorful and richly detailed, no empty space.`.trim();
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
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
  return token.includes('nano-banana') || token.includes('gemini-2.5-flash-image');
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
  const preferred = PREFERRED_DEFAULT_MODELS.find((id) => models.some((model) => normalizedModelId(model) === id));
  if (!preferred) return Array.from(new Set(top));
  return [preferred].concat(top.filter((id) => id !== preferred));
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
    let books = DB.dbGetAll('books');
    if (!books.length) books = await DB.loadBooks('classics');
    if (!books.length) {
      try {
        books = await Drive.syncCatalog();
      } catch {
        // no-op
      }
    }
    await DB.loadPrompts('classics');

    const prompts = DB.dbGetAll('prompts');
    const options = books
      .sort((a, b) => Number(a.number || 0) - Number(b.number || 0))
      .map((book) => `<option value="${book.id}">${book.number}. ${book.title}</option>`)
      .join('');
    const promptOptions = ['<option value="">Default auto</option>']
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
          <select class="form-select" id="iterBookSelect">
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
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Custom prompt</label>
            <textarea class="form-textarea" id="iterPrompt" rows="4" placeholder="Override the prompt. Use {title} and {author} placeholders..."></textarea>
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
    const syncBtn = document.getElementById('iterSyncBooksBtn');
    const syncStatus = document.getElementById('iterBookSyncStatus');
    const modeToggle = document.getElementById('iterModeToggle');
    const advanced = document.getElementById('iterAdvanced');
    const variantsEl = document.getElementById('iterVariants');
    const promptSelEl = document.getElementById('iterPromptSel');
    const customPromptEl = document.getElementById('iterPrompt');
    const modelSearchEl = document.getElementById('iterModelSearch');
    const modelGridEl = document.getElementById('iterModelGrid');
    const modelSummaryEl = document.getElementById('iterModelSummary');
    const modelFilterButtons = Array.from(content.querySelectorAll('[data-model-filter]'));
    const modelActionButtons = Array.from(content.querySelectorAll('[data-model-action]'));

    const preferred = PREFERRED_DEFAULT_MODELS.find((id) => OpenRouter.MODELS.some((model) => normalizedModelId(model) === id));
    _defaultModelId = preferred || normalizedModelId(OpenRouter.MODELS[0] || null) || null;
    _selectedModelIds = new Set(_defaultModelId ? [_defaultModelId] : []);
    _lastVisibleModelIds = [];
    let activeModelFilter = 'recommended';
    let modelSearchText = '';

    modeToggle?.addEventListener('change', () => {
      advanced.classList.toggle('hidden', !modeToggle.checked);
    });

    selectEl?.addEventListener('change', () => {
      _selectedBookId = Number(selectEl.value || 0) || null;
      this.loadExistingResults();
    });

    syncBtn?.addEventListener('click', async () => {
      const previous = syncBtn.textContent;
      syncBtn.disabled = true;
      syncBtn.textContent = 'Syncing...';
      try {
        const synced = await Drive.syncCatalog();
        const sorted = [...(Array.isArray(synced) ? synced : [])]
          .sort((a, b) => Number(a.number || 0) - Number(b.number || 0));
        const current = Number(selectEl?.value || 0);
        if (selectEl) {
          selectEl.innerHTML = ['<option value="">— Select a book —</option>']
            .concat(sorted.map((book) => `<option value="${book.id}">${book.number}. ${book.title}</option>`))
            .join('');
          if (current > 0 && sorted.some((book) => Number(book.id) === current)) {
            selectEl.value = String(current);
          }
        }
        if (syncStatus) syncStatus.textContent = `${sorted.length} books loaded (catalog).`;
        updateHeader();
        Toast.success(`Catalog synced: ${sorted.length} books`);
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
      if (est) {
        const worst = total * 3;
        est.textContent = `Est. cost: $${total.toFixed(3)} · worst-case $${worst.toFixed(3)}`;
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
      const defaultLabel = _defaultModelId ? modelIdToLabel(_defaultModelId) : 'first model';
      modelSummaryEl.textContent = `${_selectedModelIds.size} model selected · showing ${rendered.visibleCount}/${OpenRouter.MODELS.length}. Default: ${defaultLabel} only. Selected: ${selectedLabels || 'none'}${selectedSuffix}.`;
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
    promptSelEl?.addEventListener('change', () => {
      if (!customPromptEl) return;
      const promptId = String(promptSelEl.value || '').trim();
      if (!promptId) {
        customPromptEl.value = '';
        return;
      }
      const selected = DB.dbGet('prompts', promptId);
      if (selected?.prompt_template) {
        customPromptEl.value = String(selected.prompt_template);
      }
    });
    renderModels();

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
    const books = DB.dbGetAll('books');
    const book = books.find((b) => Number(b.id) === bookId);
    if (!book) return;

    const templateObj = promptId ? DB.dbGet('prompts', promptId) : null;
    const styleSelections = StyleDiversifier.selectDiverseStyles(selectedModels.length * variantCount);
    const selectedCoverId = String(book.cover_jpg_id || book.drive_cover_id || '').trim();
    const selectedCoverBookNumber = Number(book.number || book.id || bookId || 0);

    const jobs = [];
    let styleIndex = 0;
    selectedModels.forEach((model) => {
      for (let variant = 1; variant <= variantCount; variant += 1) {
        const style = styleSelections[styleIndex % styleSelections.length];
        styleIndex += 1;
        const basePrompt = resolvePrompt(templateObj, book, customPrompt);
        const prompt = StyleDiversifier.buildDiversifiedPrompt(book.title, book.author, style) + ' ' + basePrompt;
        jobs.push({
          id: uuid(),
          book_id: bookId,
          model,
          variant,
          status: 'queued',
          prompt,
          style_id: style?.id || 'none',
          style_label: style?.label || 'Default',
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
      const errorText = status === 'failed' ? String(job.error || '').trim() : '';
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

    if (!compositeHref && !rawHref && !pdfHref && !aiHref) return;

    try {
      const JSZip = await ensureJSZip();
      const zip = new JSZip();

      if (compositeHref) {
        const compositeBlob = await fetchDownloadBlob(compositeHref);
        if (compositeBlob) {
          zip.file(`${folderName}/${baseName}.jpg`, compositeBlob);
        }
      }

      if (rawHref) {
        const rawBlob = await fetchDownloadBlob(rawHref);
        if (rawBlob) {
          zip.file(`${folderName}/${baseName} (illustration).jpg`, rawBlob);
        }
      }

      if (pdfHref) {
        const pdfBlob = await fetchDownloadBlob(pdfHref);
        if (pdfBlob) {
          zip.file(`${folderName}/${baseName}.pdf`, pdfBlob);
        }
      }

      if (aiHref) {
        const aiBlob = await fetchDownloadBlob(aiHref);
        if (aiBlob) {
          zip.file(`${folderName}/${baseName}.ai`, aiBlob);
        }
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

  refreshPromptDropdown(selectedId = '') {
    const promptSel = document.getElementById('iterPromptSel');
    if (!promptSel) return;
    const prompts = DB.dbGetAll('prompts');
    promptSel.innerHTML = ['<option value="">Default auto</option>']
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
