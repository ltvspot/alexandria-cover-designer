# PROMPT-07B — Compositor Centering Fix, Z-Order Verification & UI Polish

**Priority:** CRITICAL — The compositor is BROKEN. Generated art bleeds past the gold ornamental frame.

**Branch:** `master`
**Commit after all fixes:** `git add -A && git commit -m "fix: compositor centering, model grid, backend style sync (07B)" && git push`

---

## ⚠️ DESIGN PRESERVATION — DO NOT CHANGE

Only modify the specific files listed in this prompt. Do NOT touch `index.html`, sidebar, navigation, color scheme, page layouts, or any file not listed.

---

## THE BUG — READ THIS CAREFULLY

Look at the current composited output. The compositor is BROKEN in three ways:

1. **Art bleeds past the gold frame.** The generated illustration extends BEYOND the medallion opening where the ornamental scrollwork is thin. You can see the art poking through at the top, sides, and bottom of the frame. This means the clip circle is LARGER than the actual medallion opening, or it's misaligned.

2. **Art is not centered.** The generated illustration is offset from the true medallion center. You can see more of the original cover background peeking through on one side than the other.

3. **Original cover background visible.** Cream/tan diagonal texture from the original cover is visible in the gaps, meaning the art doesn't fully fill the opening either.

**Root cause:** The `detectMedallionGeometry()` function in `src/static/js/compositor.js` has a search window of only ±4.5% of image dimensions (~18px on a 420px scan). This is far too narrow. When the actual medallion center differs from the hardcoded default (2850, 1350), the detector locks onto whatever warm-gold pixels happen to be nearby — which may be frame decorations, NOT the actual medallion ring. This produces wrong cx, cy, and radius values.

Additionally, `OPENING_SAFETY_INSET = 6` is too small. Any detection error larger than 6px means art will overlap the frame.

---

## FIX 1 — Widen the Detection Search Window (CRITICAL)

**File:** `src/static/js/compositor.js`

### 1A. Increase search radius

The current search scans only ±4.5% around the hint center. This is far too narrow for covers where the medallion position varies.

**Find this code:**
```js
const searchX = Math.max(18, Math.round(scanW * 0.045));
const searchY = Math.max(18, Math.round(scanH * 0.045));
```

**Replace with:**
```js
const searchX = Math.max(30, Math.round(scanW * 0.15));
const searchY = Math.max(30, Math.round(scanH * 0.15));
```

### 1B. Widen the radius search range

**Find:**
```js
const coarseRMin = Math.max(24, Math.round(r0 * 0.84));
let coarseRMax = Math.min(Math.round(Math.min(scanW, scanH) * 0.49), Math.round(r0 * 1.18));
```

**Replace with:**
```js
const coarseRMin = Math.max(24, Math.round(r0 * 0.65));
let coarseRMax = Math.min(Math.round(Math.min(scanW, scanH) * 0.49), Math.round(r0 * 1.40));
```

### 1C. Increase OPENING_SAFETY_INSET

The clip circle must be well inside the frame edge. 6px is not enough.

**Find:**
```js
const OPENING_SAFETY_INSET = 6;
```

**Replace with:**
```js
const OPENING_SAFETY_INSET = 18;
```

### 1D. Widen the fine scan window

**Find:**
```js
for (let cy = Math.max(10, best.cy - 8); cy < Math.min(scanH - 10, best.cy + 9); cy += FINE_STEP) {
  for (let cx = Math.max(10, best.cx - 8); cx < Math.min(scanW - 10, best.cx + 9); cx += FINE_STEP) {
```

**Replace with:**
```js
for (let cy = Math.max(10, best.cy - 16); cy < Math.min(scanH - 10, best.cy + 17); cy += FINE_STEP) {
  for (let cx = Math.max(10, best.cx - 16); cx < Math.min(scanW - 10, best.cx + 17); cx += FINE_STEP) {
```

### 1E. Relax the maxOffset guard

**Find:**
```js
const maxOffset = Math.max(32, hintRadius * 0.34);
```

**Replace with:**
```js
const maxOffset = Math.max(80, hintRadius * 0.55);
```

### 1F. Add detailed console logging

After the geometry return statement in `smartComposite`, add visible logging so we can verify values:

```js
console.log(`[Compositor v9] Detected: cx=${geo.cx}, cy=${geo.cy}, outer=${geo.outerRadius}, opening=${geo.openingRadius}, confidence=${geo.confidence?.toFixed(2)}, fallback=${geo.fallbackUsed}`);
console.log(`[Compositor v9] Clip radius used: ${clipRadius}`);
```

---

## FIX 2 — Python Backend Compositor (MUST MATCH)

**File:** `src/cover_compositor.py`

Apply identical search window fixes:

1. Find the equivalent search window size and widen to 15% of image dimensions.
2. Widen the radius search range (0.65x to 1.40x).
3. Change `OPENING_SAFETY_INSET_PX = 6` to `OPENING_SAFETY_INSET_PX = 18`.
4. Widen the fine scan window.
5. Relax the maxOffset guard to 55% of hint radius.
6. Add logging: `logger.info("Compositor detected: cx=%d cy=%d outer=%d opening=%d", ...)`.

**Both compositors (JS and Python) must use the same parameters.**

---

## FIX 3 — Model Display Layout

**Files:** `src/static/css/style.css` + `src/static/js/pages/iterate.js`

The 20+ model checkboxes are a cluttered wall of text. Fix:

**Add to `src/static/css/style.css`:**
```css
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 6px;
}

.model-grid .checkbox-item {
  padding: 5px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  transition: border-color 0.15s;
}

.model-grid .checkbox-item:hover {
  border-color: var(--gold);
}

.model-grid .checkbox-item:has(input:checked) {
  border-color: var(--gold);
  background: rgba(196, 164, 105, 0.08);
}
```

**In `src/static/js/pages/iterate.js`, change:**
```html
<div class="checkbox-group">${renderModelCheckboxes()}</div>
```
**to:**
```html
<div class="model-grid">${renderModelCheckboxes()}</div>
```

---

## FIX 4 — Sync Backend Style Modifiers

**File:** `src/prompt_generator.py`

The frontend `style-diversifier.js` now has enriched paragraph-length modifiers (~80-120 words each). The backend `prompt_generator.py` must match.

1. Replace all 20 `STYLE_POOL` entries in `prompt_generator.py` with the exact same enriched modifiers from `src/static/js/style-diversifier.js`.
2. Replace `renaissance-fresco` with `persian-miniature`.
3. Check `src/intelligent_prompter.py` — if it has its own style pool, sync it too.

---

## MANDATORY VERIFICATION — DO NOT SKIP

After implementing all fixes, you MUST do the following verification. **Do not claim the work is done until every check passes.**

### Step 1: Generate a test cover

1. Open the app at the deployed URL.
2. Select Book #1 (A Room with a View).
3. Select Nano Banana Pro (cheapest model).
4. Generate 1 variant.
5. Wait for the composite result to appear.

### Step 2: Visual verification (CRITICAL)

Look at the composited cover image and answer these questions honestly:

- **Q1:** Is the generated art COMPLETELY INSIDE the gold ornamental frame? There should be ZERO pixels of generated art visible outside the medallion circle. The scrollwork, flowers, and decorative elements of the frame must be 100% intact with no art bleeding through.

- **Q2:** Is the art CENTERED within the medallion opening? The gap between the art edge and the frame should be roughly equal on all sides (top, bottom, left, right). There should NOT be more background visible on one side than the other.

- **Q3:** Does the art FILL the medallion opening? There should be no large visible areas of the original cover's cream/tan background inside the medallion circle.

**If ANY of these answers is NO, the fix is not complete. Go back and adjust the detection parameters.**

### Step 3: Console check

Open browser console. Verify you see:
```
[Compositor v9] Detected: cx=XXXX, cy=XXXX, outer=XXX, opening=XXX, confidence=X.XX, fallback=false
```

The `fallback=false` confirms auto-detection worked. If it says `fallback=true`, the detection failed.

### Step 4: Repeat with 2 more books

Repeat Steps 1-3 with Book #9 (Right Ho, Jeeves) and Book #25 (The Eyes Have It). All three must pass.

### Step 5: Model grid check

Verify the model checkboxes display as organized cards in a grid, not a wall of flowing text.

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `src/static/js/compositor.js` | **FIX** | Widen detection (4.5%→15%), increase safety inset (6→18px), widen radius range, relax guards |
| `src/cover_compositor.py` | **FIX** | Same detection parameter fixes for Python backend |
| `src/static/css/style.css` | **ADD** | `.model-grid` card-style layout |
| `src/static/js/pages/iterate.js` | **FIX** | Use `model-grid` class |
| `src/prompt_generator.py` | **SYNC** | Enriched paragraph-length style modifiers |
| `src/intelligent_prompter.py` | **VERIFY** | Sync style pool if separate |
