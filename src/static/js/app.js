window.Pages = window.Pages || {};

const PAGES = {
  iterate: { title: 'Iterate', render: () => window.Pages.iterate.render() },
  batch: { title: 'Batch', render: () => window.Pages.batch.render() },
  jobs: { title: 'Jobs', render: () => window.Pages.jobs.render() },
  review: { title: 'Review', render: () => window.Pages.review.render() },
  compare: { title: 'Compare', render: () => window.Pages.compare.render() },
  similarity: { title: 'Similarity', render: () => window.Pages.similarity.render() },
  mockups: { title: 'Mockups', render: () => window.Pages.mockups.render() },
  dashboard: { title: 'Dashboard', render: () => window.Pages.dashboard.render() },
  history: { title: 'History', render: () => window.Pages.history.render() },
  analytics: { title: 'Analytics', render: () => window.Pages.analytics.render() },
  catalogs: { title: 'Catalogs', render: () => window.Pages.catalogs.render() },
  prompts: { title: 'Prompts', render: () => window.Pages.prompts.render() },
  settings: { title: 'Settings', render: () => window.Pages.settings.render() },
  'api-docs': { title: 'API Docs', render: () => window.Pages['api-docs'].render() },
};

function getPageFromHash() {
  const hashPage = location.hash.slice(1).split('?')[0];
  return hashPage || window.__INITIAL_PAGE__ || 'iterate';
}

async function renderPage() {
  const page = getPageFromHash();
  const config = PAGES[page];
  if (!config) {
    location.hash = '#iterate';
    return;
  }

  const titleEl = document.getElementById('pageTitle');
  if (titleEl) titleEl.textContent = config.title;

  document.querySelectorAll('.nav-link').forEach((link) => {
    link.classList.toggle('active', link.dataset.page === page);
  });

  const content = document.getElementById('content');
  if (!content) return;
  content.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:200px"><div class="spinner"></div></div>';

  try {
    await config.render();
  } catch (err) {
    console.error('Page render error:', err);
    content.innerHTML = `<div class="card"><p class="text-muted">Failed to render page: ${err.message}</p></div>`;
  }

  if (window.innerWidth <= 768) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    sidebar?.classList.remove('mobile-open');
    overlay?.classList.remove('visible');
  }
}

window.Toast = {
  show(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('removing');
      setTimeout(() => toast.remove(), 220);
    }, duration);
  },
  success(msg, dur) { this.show(msg, 'success', dur); },
  error(msg, dur) { this.show(msg, 'error', dur || 6000); },
  warning(msg, dur) { this.show(msg, 'warning', dur); },
  info(msg, dur) { this.show(msg, 'info', dur); },
};

window.CoverCache = {
  _cache: new Map(),
  _pending: new Map(),
  MAX_SIZE: 20,

  async load(bookId) {
    if (this._cache.has(bookId)) {
      const entry = this._cache.get(bookId);
      this._cache.delete(bookId);
      this._cache.set(bookId, entry);
      return entry;
    }
    if (this._pending.has(bookId)) return this._pending.get(bookId);
    const promise = this._fetch(bookId).finally(() => this._pending.delete(bookId));
    this._pending.set(bookId, promise);
    return promise;
  },

  async _fetch(bookId) {
    const entry = await Drive.downloadCoverForBook(bookId, 'catalog');
    const detected = Drive.validateCoverTemplate(entry.img);
    const cx = detected?.valid ? detected.medallion.cx : DB.getSetting('medallion_cx');
    const cy = detected?.valid ? detected.medallion.cy : DB.getSetting('medallion_cy');
    const radius = detected?.valid ? detected.medallion.radius : DB.getSetting('medallion_radius');
    const cached = { img: entry.img, cx: Number(cx), cy: Number(cy), radius: Number(radius) };
    if (this._cache.size >= this.MAX_SIZE) {
      this._cache.delete(this._cache.keys().next().value);
    }
    this._cache.set(bookId, cached);
    return cached;
  },
};

window.JobQueue = {
  MAX_CONCURRENT: 2,
  GENERATION_TIMEOUT: 480000,
  COVER_TIMEOUT: 20000,
  COMPOSITE_TIMEOUT: 15000,
  RETRY_THRESHOLD: 0.35,
  MAX_RETRIES: 2,
  DEAD_JOB_TIMEOUT: 180000,

  queue: [],
  running: new Map(),
  paused: false,
  _listeners: [],

  add(job) {
    this.queue.push(job);
    DB.dbPut('jobs', job);
    this.notify();
    this._fillSlots();
  },

  addBatch(jobs) {
    jobs.forEach((job) => {
      this.queue.push(job);
      DB.dbPut('jobs', job);
    });
    this.notify();
    this._fillSlots();
  },

  pause() {
    this.paused = true;
    this.notify();
  },

  resume() {
    this.paused = false;
    this.notify();
    this._fillSlots();
  },

  abortJob(jobId, reason = 'Cancelled') {
    if (this.running.has(jobId)) {
      const entry = this.running.get(jobId);
      entry.abortController.abort();
      const job = entry.job;
      job.status = 'failed';
      job.error = reason;
      job.completed_at = new Date().toISOString();
      DB.dbPut('jobs', job);
      this.running.delete(jobId);
      this.notify();
      this._fillSlots();
      return;
    }
    const idx = this.queue.findIndex((j) => j.id === jobId);
    if (idx >= 0) {
      const [job] = this.queue.splice(idx, 1);
      job.status = 'failed';
      job.error = reason;
      job.completed_at = new Date().toISOString();
      DB.dbPut('jobs', job);
      this.notify();
    }
  },

  cancelAll() {
    for (const [jobId] of this.running) {
      this.abortJob(jobId, 'Cancelled all');
    }
    while (this.queue.length > 0) {
      const job = this.queue.shift();
      job.status = 'failed';
      job.error = 'Cancelled all';
      job.completed_at = new Date().toISOString();
      DB.dbPut('jobs', job);
    }
    this.notify();
  },

  onChange(fn) {
    this._listeners.push(fn);
    return () => {
      this._listeners = this._listeners.filter((listener) => listener !== fn);
    };
  },

  _snapshot() {
    const now = Date.now();
    const allJobs = DB.dbGetAll('jobs');
    const allById = new Map(allJobs.map((job) => [job.id, job]));
    for (const [jobId, entry] of this.running.entries()) {
      const base = allById.get(jobId) || {};
      const elapsed = Number(entry.job?._elapsed || Math.floor((now - entry.startTime) / 1000));
      allById.set(jobId, { ...base, ...entry.job, _elapsed: elapsed });
    }
    return {
      queue: [...this.queue],
      running: [...this.running.values()].map((entry) => entry.job),
      all: Array.from(allById.values()),
      paused: this.paused,
    };
  },

  notify() {
    const snap = this._snapshot();
    this._listeners.forEach((fn) => {
      try {
        fn(snap);
      } catch (err) {
        console.warn('Job listener error:', err.message);
      }
    });
  },

  resumeStuckJobs() {
    DB.dbGetAll('jobs').forEach((job) => {
      if (!['completed', 'failed', 'queued'].includes(job.status)) {
        job.status = 'failed';
        job.error = 'Interrupted by page reload';
        job.completed_at = new Date().toISOString();
        DB.dbPut('jobs', job);
      }
    });
  },

  _fillSlots() {
    while (!this.paused && this.running.size < this.MAX_CONCURRENT && this.queue.length > 0) {
      const job = this.queue.shift();
      this._executeJob(job);
    }
    this.notify();
  },

  _heartbeat() {
    const now = Date.now();
    for (const [jobId, entry] of this.running.entries()) {
      const elapsedMs = now - entry.startTime;
      entry.job._elapsed = Math.floor(elapsedMs / 1000);
      const backendStamp = Date.parse(String(entry.job._backendLastUpdateAt || ''));
      const backendAge = Number.isFinite(backendStamp) && backendStamp > 0
        ? Math.floor(Math.max(0, now - backendStamp) / 1000)
        : Math.floor(elapsedMs / 1000);
      entry.job._backendHeartbeatAge = backendAge;
      if ((entry.job.status === 'generating' || entry.job.status === 'retrying') && backendAge >= 20) {
        entry.job._subStatus = `Waiting on backend queue (${backendAge}s since update)`;
      }
      if (elapsedMs > this.DEAD_JOB_TIMEOUT) {
        entry.abortController.abort();
        entry.job.status = 'failed';
        entry.job.error = 'Job timed out';
        entry.job.completed_at = new Date().toISOString();
        DB.dbPut('jobs', entry.job);
        this.running.delete(jobId);
      }
    }
    this.notify();
    updateHeader();
  },

  async _executeJob(job) {
    const abortController = new AbortController();
    this.running.set(job.id, { job, abortController, startTime: Date.now() });
    job.started_at = new Date().toISOString();
    job.cost_usd = Number(job.cost_usd || 0);

    const setStatus = (status, sub = '') => {
      job.status = status;
      job._subStatus = sub;
      DB.dbPut('jobs', job);
      this.notify();
    };

    try {
      setStatus('downloading_cover');
      try {
        await Promise.race([
          CoverCache.load(job.book_id),
          new Promise((_, reject) => setTimeout(() => reject(new Error('Cover timeout')), this.COVER_TIMEOUT)),
        ]);
      } catch (coverErr) {
        job._coverFailed = true;
        job._coverError = coverErr.message;
      }

      setStatus('generating');
      let best = null;
      let bestScore = -1;
      let attempts = 0;

      while (attempts < this.MAX_RETRIES + 1) {
        attempts += 1;
        const retryPrompt = attempts > 1
          ? `${job.prompt} IMPORTANT: This must be a circular vignette illustration centered and fully contained.`
          : job.prompt;

        let result;
        try {
          result = await OpenRouter.generateImage(
            retryPrompt,
            job.model,
            DB.getSetting('openrouter_key'),
            abortController.signal,
            this.GENERATION_TIMEOUT,
            {
              book_id: job.book_id,
              catalog: 'classics',
              prompt_source: 'custom',
              cover_source: 'drive',
              selected_cover_id: String(job.selected_cover_id || '').trim(),
              selected_cover_book_number: Number(job.selected_cover_book_number || job.book_id || 0),
              variant: Number(job.variant || 1),
              variants: 1,
              max_attempts: 5,
              idempotency_key: `${job.id}-attempt-${attempts}`,
              onProgress: (backendJob) => {
                const backendStatus = String(backendJob?.status || '').trim().toLowerCase();
                const backendUpdatedAt = String(backendJob?.updated_at || backendJob?.started_at || '').trim();
                const stages = backendJob?.result?.stages || backendJob?.stages || {};
                let stageToken = '';
                if (stages && typeof stages === 'object') {
                  const activeStage = Object.entries(stages).find(([, value]) => {
                    const token = String(value?.status || '').trim().toLowerCase();
                    return token === 'running' || token === 'active';
                  });
                  if (activeStage) {
                    stageToken = String(activeStage[0] || '').trim().toLowerCase();
                  }
                }
                const labelMap = {
                  queued: 'queued',
                  running: 'running',
                  retrying: 'retrying',
                  generate: 'generating',
                  composite: 'compositing',
                  persist: 'persisting',
                  sync: 'syncing',
                  deliver: 'delivering',
                };
                const shown = labelMap[stageToken] || labelMap[backendStatus] || backendStatus || 'running';
                job._backendStatus = backendStatus || 'running';
                job._backendStage = stageToken || backendStatus || '';
                job._backendLastUpdateAt = backendUpdatedAt || new Date().toISOString();
                if (job.status === 'generating' || job.status === 'retrying') {
                  setStatus(job.status, `backend ${shown}`);
                } else {
                  job._subStatus = `backend ${shown}`;
                  DB.dbPut('jobs', job);
                  this.notify();
                }
              },
            }
          );
        } catch (err) {
          const message = String(err?.message || err || '');
          if (message === 'RATE_LIMITED') {
            attempts -= 1;
            await new Promise((resolve) => setTimeout(resolve, Math.min((attempts + 1) * 5000, 30000)));
            continue;
          }
          const transient = /timed out|timeout|missing image payload|polling failed: http 5\d\d|temporarily unavailable/i.test(message);
          if (transient && attempts < this.MAX_RETRIES + 1) {
            setStatus('retrying', `Transient error, retry ${attempts}/${this.MAX_RETRIES}`);
            await new Promise((resolve) => setTimeout(resolve, Math.min((attempts + 1) * 4000, 30000)));
            continue;
          }
          throw err;
        }

        const row = result.result || {};
        const imagePath = row.image_path ? `/${String(row.image_path).replace(/^\/+/, '')}` : '';
        const compositedPath = row.composited_path ? `/${String(row.composited_path).replace(/^\/+/, '')}` : '';
        const compositedPdfPath = row.composited_pdf_path
          ? `/${String(row.composited_pdf_path).replace(/^\/+/, '')}`
          : (row.composite_pdf_url ? `/${String(row.composite_pdf_url).replace(/^\/+/, '')}` : '');
        const compositedAiPath = row.composited_ai_path
          ? `/${String(row.composited_ai_path).replace(/^\/+/, '')}`
          : (row.composite_ai_url ? `/${String(row.composite_ai_url).replace(/^\/+/, '')}` : '');
        const dryRun = Boolean(row.dry_run);
        if (dryRun || (!imagePath && !compositedPath)) {
          const reason = dryRun
            ? 'Generation ran in dry-run mode (missing or blocked provider key).'
            : 'Generation completed without an output image.';
          throw new Error(reason);
        }
        const score = Number(row.quality_score || row.distinctiveness_score || 0);
        if (score > bestScore) {
          bestScore = score;
          best = { row, imagePath, compositedPath, compositedPdfPath, compositedAiPath, score };
        }

        job.cost_usd += Number(row.cost || OpenRouter.MODEL_COSTS[job.model] || 0);

        if (score >= this.RETRY_THRESHOLD || attempts >= this.MAX_RETRIES + 1) {
          break;
        }

        setStatus('retrying', `Retry ${attempts}/${this.MAX_RETRIES}`);
      }

      if (!best) throw new Error('No successful generation result');

      setStatus('scoring');
      const rawSource = best.imagePath || best.compositedPath;
      const img = await loadImage(rawSource);
      const detailed = await Quality.getDetailedScores(img);
      job.quality_score = Number(detailed.overall || best.score || 0);
      job.results_json = JSON.stringify({ scores: detailed, result: best.row });

      setStatus('compositing');
      const rawBlob = await fetchImageBlob(rawSource, abortController.signal);
      const fullResCompositeSource = resolveFullResolutionCompositeSource(best.compositedPath);
      if (best.compositedPath && fullResCompositeSource !== best.compositedPath) {
        console.warn('Resolved thumbnail composite path to full-resolution source.', {
          original: best.compositedPath,
          resolved: fullResCompositeSource,
        });
      }
      const backendCompositedBlob = fullResCompositeSource
        ? await fetchImageBlob(fullResCompositeSource, abortController.signal, { retries: 60, delayMs: 1000 })
        : null;
      if (!backendCompositedBlob && !fullResCompositeSource) {
        throw new Error('Backend composite unavailable; refusing raw fallback to preserve medallion layering.');
      }
      if (backendCompositedBlob) warnIfSuspiciousCompositeBlob(backendCompositedBlob, fullResCompositeSource);
      job.generated_image_blob = rawBlob || rawSource;
      job.composited_image_blob = backendCompositedBlob || fullResCompositeSource || null;
      job.composite_pdf_url = best.compositedPdfPath || '';
      job.composite_ai_url = best.compositedAiPath || '';
      job.pdf_url = best.compositedPdfPath || '';
      job.ai_url = best.compositedAiPath || '';
      job.compositor_mode = String(best.row?.compositor_mode || '').trim() || '';
      job._compositeFailed = false;
      job._compositeError = null;
      if (backendCompositedBlob) job._compositeSource = 'backend-blob';
      else if (fullResCompositeSource) job._compositeSource = 'backend-path';
      else job._compositeSource = 'missing';
      job.compositor_geometry = null;

      setStatus('completed');
      job.completed_at = new Date().toISOString();
      DB.dbPut('jobs', job);
      DB.dbPut('cost_ledger', {
        model: job.model,
        cost_usd: Number(job.cost_usd || 0),
        job_id: job.id,
        book_id: job.book_id,
        recorded_at: new Date().toISOString(),
      });
    } catch (err) {
      if (abortController.signal.aborted) {
        job.error = job.error || 'Cancelled';
      } else {
        job.error = err.message;
      }
      job.status = 'failed';
      job.completed_at = new Date().toISOString();
      DB.dbPut('jobs', job);
    } finally {
      this.running.delete(job.id);
      this.notify();
      this._fillSlots();
    }
  },
};

window.uuid = () => {
  if (crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : ((r & 0x3) | 0x8)).toString(16);
  });
};

window.formatDate = (iso) => new Date(iso).toLocaleString('en-US', {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
});

window.timeAgo = (iso) => {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
};

window.normalizeAssetUrl = (value) => {
  const token = String(value || '').trim();
  if (!token) return '';
  if (token.startsWith('blob:') || token.startsWith('data:') || /^https?:\/\//i.test(token)) return token;
  if (token.startsWith('/')) return token;
  return `/${token.replace(/^\.?\//, '')}`;
};

window.blobUrls = new Map();
window.getBlobUrl = (data, key) => {
  if (!data) return '';
  if (typeof data === 'string') return window.normalizeAssetUrl(data);

  const blob = data instanceof Blob ? data : new Blob([data]);
  if (blob.type && !blob.type.startsWith('image/')) return '';

  if (key && window.blobUrls.has(key)) {
    const cached = window.blobUrls.get(key);
    if (cached?.data === data && cached?.url) return cached.url;
    if (cached?.url) {
      try {
        URL.revokeObjectURL(cached.url);
      } catch {
        // ignore
      }
    }
    window.blobUrls.delete(key);
  }

  const url = URL.createObjectURL(blob);
  if (key) window.blobUrls.set(key, { data, url });
  return url;
};

function resolveFullResolutionCompositeSource(source) {
  const normalized = window.normalizeAssetUrl(source);
  if (!normalized) return '';
  if (!normalized.toLowerCase().startsWith('/api/thumbnail')) return normalized;
  try {
    const url = new URL(normalized, window.location.origin);
    const rawPath = String(url.searchParams.get('path') || '').trim();
    if (!rawPath) return normalized;
    return `/${rawPath.replace(/^\/+/, '')}`;
  } catch {
    return normalized;
  }
}

function warnIfSuspiciousCompositeBlob(blob, source) {
  if (!(blob instanceof Blob)) return;
  const size = Number(blob.size || 0);
  if (size > 0 && size < 700 * 1024) {
    console.warn('Composite blob appears suspiciously small; verify full-resolution output path.', {
      source,
      bytes: size,
    });
  }
}

async function loadImage(src) {
  if (!src) throw new Error('Missing image source');
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load image: ${src}`));
    img.src = src;
  });
}

async function fetchImageBlob(src, signal, options = {}) {
  if (!src || typeof src !== 'string') return null;
  const retries = Math.max(0, Number(options.retries || 0));
  const delayMs = Math.max(0, Number(options.delayMs || 0));
  const looksLikeImagePath = /\.(png|jpe?g|webp|gif|bmp|avif)(\?|$)/i.test(src);
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const response = await fetch(src, { cache: 'no-store', signal });
      if (response.ok) {
        const contentType = String(response.headers.get('content-type') || '').toLowerCase();
        const blob = await response.blob();
        const blobType = String(blob.type || '').toLowerCase();
        const isImage = blobType.startsWith('image/');
        const likelyImage = looksLikeImagePath && (!blobType || blobType === 'application/octet-stream');
        const headerSuggestsImage = contentType.startsWith('image/');
        if (headerSuggestsImage && !blob.type) {
          return new Blob([blob], { type: contentType.split(';', 1)[0] || 'image/jpeg' });
        }
        if (isImage || likelyImage || headerSuggestsImage) return blob;
      }
    } catch {
      // Ignore transient network errors; retry loop handles backoff.
    }
    if (attempt < retries && delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }
  return null;
}

async function canvasToBlob(canvas, type = 'image/jpeg', quality = 0.96) {
  return new Promise((resolve) => {
    try {
      canvas.toBlob((blob) => resolve(blob || null), type, quality);
    } catch {
      resolve(null);
    }
  });
}

window.loadImage = loadImage;

function updateHeader() {
  const budgetBadge = document.getElementById('budgetBadge');
  const syncStatus = document.getElementById('syncStatus');
  const ledger = DB.dbGetAll('cost_ledger');
  const spent = ledger.reduce((sum, row) => sum + Number(row.cost_usd || 0), 0);
  let inFlight = 0;
  for (const entry of JobQueue.running.values()) {
    inFlight += Number(entry.job.cost_usd || 0);
  }
  const total = spent + inFlight;
  const budget = Number(DB.getSetting('budget_limit', 50));
  if (budgetBadge) budgetBadge.textContent = `$${total.toFixed(2)} / $${budget.toFixed(2)}`;
  if (syncStatus) syncStatus.textContent = `${DB.dbCount('books')} books`;
}

window.updateHeader = updateHeader;

async function autoSync() {
  try {
    const status = await Drive.catalogCacheStatus();
    if (status.cached) {
      await Drive.loadCachedCatalog();
      updateHeader();
      if (status.stale) {
        Drive.refreshCatalogCache().catch(() => undefined);
      }
    } else {
      await Drive.syncCatalog();
      updateHeader();
    }
  } catch (err) {
    console.warn('Auto-sync failed:', err.message);
  }
}

function initSidebar() {
  const sidebar = document.getElementById('sidebar');
  const sidebarToggle = document.getElementById('sidebarToggle');
  const mobileBtn = document.getElementById('mobileMenuBtn');
  const overlay = document.getElementById('sidebarOverlay');

  sidebarToggle?.addEventListener('click', () => {
    sidebar?.classList.toggle('collapsed');
  });

  mobileBtn?.addEventListener('click', () => {
    sidebar?.classList.toggle('mobile-open');
    overlay?.classList.toggle('visible');
  });

  overlay?.addEventListener('click', () => {
    sidebar?.classList.remove('mobile-open');
    overlay?.classList.remove('visible');
  });

  document.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        sidebar?.classList.remove('mobile-open');
        overlay?.classList.remove('visible');
      }
    });
  });
}

async function init() {
  await DB.openDB();
  await DB.initDefaults();
  await DB.loadPrompts('classics');
  await OpenRouter.init();
  if (window.Compositor?.loadRegions) {
    await window.Compositor.loadRegions();
  }
  JobQueue.resumeStuckJobs();
  initSidebar();
  updateHeader();
  window.addEventListener('hashchange', renderPage);
  await renderPage();
  autoSync();
  setInterval(() => JobQueue._heartbeat(), 1000);
}

window.addEventListener('DOMContentLoaded', () => setTimeout(init, 100));
