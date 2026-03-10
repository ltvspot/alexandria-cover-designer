window.Pages = window.Pages || {};

let _selectedBooks = new Set();
let _batchUnsub = null;

function _batchEnrichment(book) {
  return (book && typeof book.enrichment === 'object' && book.enrichment) ? book.enrichment : {};
}

function _batchDefaultScene(book) {
  const row = (book && typeof book === 'object') ? book : {};
  return `A pivotal dramatic moment from the literary work "${String(row.title || 'the story').trim()}" by ${String(row.author || 'Unknown author').trim()}`;
}

function _batchScenePool(book, count = 1) {
  const total = Math.max(1, Number(count || 1));
  const row = (book && typeof book === 'object') ? book : {};
  const enrichment = _batchEnrichment(row);
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

  const iconicScenes = Array.isArray(enrichment.iconic_scenes) ? enrichment.iconic_scenes : [];
  iconicScenes.forEach((scene) => pushUnique(scene));

  const protagonist = String(enrichment.protagonist || '').trim();
  const setting = String(enrichment.setting_primary || '').trim();
  const settingDetails = Array.isArray(enrichment.setting_details)
    ? enrichment.setting_details.map((item) => String(item || '').trim()).filter(Boolean).join(', ')
    : String(enrichment.setting_details || '').trim();
  if (protagonist) {
    pushUnique(`${protagonist} in a pivotal moment${setting ? ` set in ${setting}` : ' from the story'}`);
  }
  if (setting) {
    pushUnique(`${setting}${settingDetails ? `, ${settingDetails}` : ''} — establishing atmosphere of the story's world`);
  }

  if (!pool.length) {
    pushUnique(_batchDefaultScene(row));
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
    const baseScene = pool[index % pool.length] || _batchDefaultScene(row);
    const prefix = variationPrefixes[Math.floor(index / pool.length) % variationPrefixes.length] || '';
    results.push(prefix ? `${prefix}${baseScene}` : baseScene);
  }
  return results;
}

function defaultBatchPrompt(book, variant = 1, variantCount = 1) {
  const row = (book && typeof book === 'object') ? book : {};
  const enrichment = _batchEnrichment(row);
  const title = String(row.title || 'the story').trim();
  const author = String(row.author || 'Unknown author').trim();
  const protagonist = String(enrichment.protagonist || '').trim();
  const setting = String(enrichment.setting_primary || '').trim();
  const mood = String(enrichment.emotional_tone || 'dramatic, atmospheric').trim();
  const era = String(enrichment.era || '').trim();
  const scenePool = _batchScenePool(row, variantCount);
  const resolvedScene = scenePool[Math.max(0, Number(variant || 1) - 1)] || scenePool[0] || _batchDefaultScene(row);

  let sceneDescription = String(resolvedScene || `a pivotal scene from "${title}"`).trim();
  if (protagonist && setting && !sceneDescription.toLowerCase().includes(protagonist.toLowerCase())) {
    sceneDescription = `${protagonist} in ${setting}, depicting: ${sceneDescription}`;
  }

  return `Create a beautiful, highly detailed circular medallion illustration for "${title}" by ${author}. The illustration must depict: ${sceneDescription}. Mood: ${mood}.${era ? ` Era: ${era}.` : ''} The subject must be centred and fully contained within the circle, edges fading softly into empty space. Highly detailed, painterly, suitable for a luxury book cover. No text, no letters, no words.`;
}

function buildBatchJob(book, model, variant, variantCount = 1) {
  return {
    id: uuid(),
    book_id: Number(book?.id || 0),
    model,
    variant,
    status: 'queued',
    prompt: defaultBatchPrompt(book, variant, variantCount),
    prompt_source: 'custom',
    backend_prompt_source: 'custom',
    compose_prompt: false,
    style_id: 'batch-default',
    style_label: 'Batch',
    quality_score: null,
    cost_usd: 0,
    created_at: new Date().toISOString(),
  };
}

window.__BATCH_TEST_HOOKS__ = window.__BATCH_TEST_HOOKS__ || {};
window.__BATCH_TEST_HOOKS__.defaultBatchPrompt = ({ book, variant, variantCount, ...rawBook }) => {
  const targetBook = book && typeof book === 'object' ? book : rawBook;
  return defaultBatchPrompt(targetBook, variant, variantCount);
};
window.__BATCH_TEST_HOOKS__.buildBatchJob = ({ book, model, variant, variantCount }) => buildBatchJob(book, model, variant, variantCount);

window.Pages.batch = {
  async render() {
    let books = DB.dbGetAll('books');
    if (!books.length || books.some((book) => !DB.bookHasPromptEnrichment(book))) {
      books = await DB.loadBooks('classics');
    }
    const modelOptions = OpenRouter.MODELS.map((m) => `<option value="${m.id}">${m.label}</option>`).join('');

    const content = document.getElementById('content');
    content.innerHTML = `
      <div class="card">
        <div class="batch-controls flex gap-8 items-center" style="flex-wrap:wrap">
          <select class="form-select" id="batchModel" style="max-width:320px">${modelOptions}</select>
          <select class="form-select" id="batchVariants" style="max-width:120px">${[1,2,3,4,5].map((v)=>`<option value="${v}">${v} variant${v>1?'s':''}</option>`).join('')}</select>
          <button class="btn btn-secondary" id="batchSelectAll">Select All</button>
          <button class="btn btn-secondary" id="batchDeselectAll">Deselect All</button>
          <button class="btn btn-primary" id="batchRunBtn">Run Batch</button>
        </div>
        <div id="batchProgress" class="hidden mt-16">
          <div class="progress-bar"><div class="progress-fill" id="batchProgressFill" style="width:0%"></div></div>
          <div class="flex justify-between mt-8">
            <span class="text-muted" id="batchProgressText">0 / 0 books</span>
            <div class="flex gap-8">
              <button class="btn btn-secondary btn-sm" id="batchPauseBtn">Pause</button>
              <button class="btn btn-danger btn-sm" id="batchCancelBtn">Cancel</button>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="card-title">Book Selection</h3><span class="text-muted" id="batchBookCount">0 selected</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th><th>#</th><th>Title</th><th>Author</th><th>Status</th></tr></thead>
            <tbody id="batchBooksBody"></tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="card-title">Recent Batches</h3></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Books</th><th>Model</th><th>Variants</th><th>Status</th><th>Date</th></tr></thead>
            <tbody id="batchRecentBody"></tbody>
          </table>
        </div>
      </div>
    `;

    this._renderBooks(books);
    this._renderRecent();
    this._bind(books);
  },

  _renderBooks(books) {
    const body = document.getElementById('batchBooksBody');
    if (!body) return;
    body.innerHTML = books
      .sort((a, b) => Number(a.number || 0) - Number(b.number || 0))
      .map((book) => {
        const winner = DB.dbGet('winners', book.id);
        const jobCount = DB.dbGetByIndex('jobs', 'book_id', book.id).length;
        return `
          <tr>
            <td><input type="checkbox" data-book-id="${book.id}" ${_selectedBooks.has(book.id) ? 'checked' : ''} /></td>
            <td>${book.number}</td>
            <td>${book.title}</td>
            <td>${book.author || ''}</td>
            <td>${winner ? '<span class="tag tag-gold">Winner</span>' : `<span class="text-muted">${jobCount} jobs</span>`}</td>
          </tr>
        `;
      }).join('');

    body.querySelectorAll('input[data-book-id]').forEach((cb) => {
      cb.addEventListener('change', () => {
        const id = Number(cb.dataset.bookId);
        if (cb.checked) _selectedBooks.add(id);
        else _selectedBooks.delete(id);
        this._updateSelectedCount();
      });
    });

    this._updateSelectedCount();
  },

  _renderRecent() {
    const body = document.getElementById('batchRecentBody');
    if (!body) return;
    const batches = DB.dbGetAll('batches')
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 10);
    if (!batches.length) {
      body.innerHTML = '<tr><td colspan="6" class="text-muted">No batch runs yet.</td></tr>';
      return;
    }
    body.innerHTML = batches.map((b) => `
      <tr>
        <td>${b.name}</td>
        <td>${b.book_ids?.length || 0}</td>
        <td>${b.model || ''}</td>
        <td>${b.variant_count || 1}</td>
        <td><span class="tag ${b.status === 'running' ? 'tag-pending' : (b.status === 'failed' ? 'tag-failed' : 'tag-success')}">${b.status}</span></td>
        <td>${formatDate(b.created_at)}</td>
      </tr>
    `).join('');
  },

  _updateSelectedCount() {
    const el = document.getElementById('batchBookCount');
    if (el) el.textContent = `${_selectedBooks.size} selected`;
  },

  _bind(books) {
    document.getElementById('batchSelectAll')?.addEventListener('click', () => {
      _selectedBooks = new Set(books.map((b) => Number(b.id)));
      this._renderBooks(books);
    });
    document.getElementById('batchDeselectAll')?.addEventListener('click', () => {
      _selectedBooks.clear();
      this._renderBooks(books);
    });
    document.getElementById('batchRunBtn')?.addEventListener('click', () => this.handleBatch(books));
    document.getElementById('batchPauseBtn')?.addEventListener('click', () => {
      const paused = JobQueue.paused;
      if (paused) JobQueue.resume();
      else JobQueue.pause();
      document.getElementById('batchPauseBtn').textContent = paused ? 'Pause' : 'Resume';
    });
    document.getElementById('batchCancelBtn')?.addEventListener('click', () => JobQueue.cancelAll());
  },

  handleBatch(books) {
    if (_selectedBooks.size < 1) {
      Toast.warning('Select at least one book.');
      return;
    }

    const model = document.getElementById('batchModel')?.value;
    const variantCount = Number(document.getElementById('batchVariants')?.value || 1);
    const batch = {
      id: uuid(),
      name: `Batch ${new Date().toLocaleString()}`,
      book_ids: [..._selectedBooks],
      model,
      variant_count: variantCount,
      status: 'running',
      completed_books: [],
      failed_books: [],
      created_at: new Date().toISOString(),
    };
    DB.dbPut('batches', batch);

    const jobs = [];
    [..._selectedBooks].forEach((bookId) => {
      const book = books.find((b) => Number(b.id) === Number(bookId));
      if (!book) return;
      for (let variant = 1; variant <= variantCount; variant += 1) {
        jobs.push(buildBatchJob(book, model, variant, variantCount));
      }
    });

    JobQueue.addBatch(jobs);
    document.getElementById('batchProgress')?.classList.remove('hidden');

    if (_batchUnsub) _batchUnsub();
    _batchUnsub = JobQueue.onChange((snap) => {
      const tracked = snap.all.filter((j) => _selectedBooks.has(Number(j.book_id)));
      const completedBooks = new Set(tracked.filter((j) => j.status === 'completed').map((j) => Number(j.book_id)));
      const done = completedBooks.size;
      const total = _selectedBooks.size;
      const percent = total > 0 ? Math.round((done / total) * 100) : 0;
      const fill = document.getElementById('batchProgressFill');
      const txt = document.getElementById('batchProgressText');
      if (fill) fill.style.width = `${percent}%`;
      if (txt) txt.textContent = `${done} / ${total} books`;
      if (done === total && total > 0) {
        batch.status = 'completed';
        batch.completed_books = [...completedBooks];
        DB.dbPut('batches', batch);
        this._renderRecent();
      }
    });

    Toast.success(`${jobs.length} batch jobs queued.`);
  },
};
