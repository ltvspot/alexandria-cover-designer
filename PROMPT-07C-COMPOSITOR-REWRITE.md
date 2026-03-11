# PROMPT-07C — Kill Auto-Detection, Use Known Geometry

**Priority:** CRITICAL — Two rounds of parameter tuning have FAILED. This prompt takes a fundamentally different approach.

**Branch:** `master`
**Commit after all fixes:** `git add -A && git commit -m "fix: compositor uses cover_regions.json geometry, kill auto-detection (07C)" && git push`

---

## ⚠️ DESIGN PRESERVATION — DO NOT CHANGE

Only modify the specific files listed in this prompt. Do NOT touch `index.html`, sidebar, navigation, color scheme, page layouts, or any file not listed.

---

## WHY DETECTION KEEPS FAILING

The `detectMedallionGeometry()` warm-gold ring scanner has been tuned twice and STILL produces broken output:
- Art bleeds past the gold frame
- Art is offset / not centered
- In some cases, TWO separate circles appear (one from the actual frame, one from the misaligned detection)

**The fundamental problem:** The hardcoded fallback center is `cy=1350` but the ACTUAL medallion center (verified across all 99 covers) is `cy=1620` — **270 pixels off**. The detection algorithm starts from this wrong point and locks onto frame decoration pixels instead of the actual ring. No amount of parameter widening fixes this because the starting point is wrong.

**The solution:** We already have `config/cover_regions.json` with **pre-computed, verified geometry for all 99 covers**. Every single cover uses template `navy_gold_medallion` with the medallion at approximately `cx=2864, cy=1620, radius=500`. The detection algorithm is unnecessary.

---

## THE NEW APPROACH — DIRECT GEOMETRY LOOKUP

### Philosophy
1. **NEVER auto-detect.** Always use known coordinates from `cover_regions.json`.
2. If a book is not in `cover_regions.json`, use the **consensus geometry** (also in that file).
3. Delete or bypass `detectMedallionGeometry()` entirely — it is the source of all bugs.

---

## FIX 1 — JavaScript Compositor (`src/static/js/compositor.js`)

### 1A. Add a geometry registry loaded from the backend

Add a module-level geometry registry that the app loads once at startup:

```js
// --- Geometry Registry (loaded from cover_regions.json via API) ---
let _regionRegistry = null;
let _consensusRegion = { cx: 2864, cy: 1620, radius: 500 };

window.Compositor.loadRegions = async function () {
  try {
    const resp = await fetch('/api/cover-regions');
    const data = await resp.json();
    _regionRegistry = {};
    if (data.consensus_region) {
      _consensusRegion = {
        cx: data.consensus_region.center_x,
        cy: data.consensus_region.center_y,
        radius: data.consensus_region.radius,
      };
    }
    (data.covers || []).forEach((c) => {
      _regionRegistry[String(c.cover_id)] = {
        cx: c.center_x,
        cy: c.center_y,
        radius: c.radius,
      };
    });
    console.log(`[Compositor] Loaded geometry for ${Object.keys(_regionRegistry).length} covers`);
  } catch (err) {
    console.warn('[Compositor] Failed to load regions, using consensus fallback:', err.message);
  }
};

window.Compositor.getKnownGeometry = function (bookId) {
  const key = String(bookId);
  const known = _regionRegistry?.[key] || _consensusRegion;
  return { ...known };
};
```

### 1B. Create a new API endpoint to serve cover_regions.json

**File:** `src/app.py` (or wherever Flask/FastAPI routes are defined)

Add a GET endpoint:
```python
@app.route('/api/cover-regions')
def api_cover_regions():
    regions_path = config.cover_regions_path(catalog_id=runtime.catalog_id, config_dir=runtime.config_dir)
    if regions_path.exists():
        return flask.send_file(regions_path, mimetype='application/json')
    return flask.jsonify({"covers": [], "consensus_region": {"center_x": 2864, "center_y": 1620, "radius": 500}})
```

### 1C. Replace `smartComposite` to use known geometry instead of detection

Replace the entire `smartComposite` method. The new version:

1. Looks up geometry from the registry (by book ID) instead of detecting
2. Falls back to consensus geometry if the book isn't found
3. NEVER calls `detectMedallionGeometry()`

```js
async smartComposite({ coverImg, generatedImg, bookId }) {
  if (!coverImg || !generatedImg) {
    throw new Error('coverImg and generatedImg are required for smartComposite');
  }

  const { width, height } = normalizedImageSize(coverImg);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');

  // --- USE KNOWN GEOMETRY, NOT DETECTION ---
  const known = this.getKnownGeometry(bookId);
  const outerRadius = Math.max(20, known.radius);
  const [minOpen, maxOpen] = openingBounds(width, height);
  const openingRadius = Math.min(
    clamp(Math.round(outerRadius * OPENING_RATIO), minOpen, maxOpen),
    Math.max(20, outerRadius - OPENING_MARGIN),
  );
  const geo = {
    cx: known.cx,
    cy: known.cy,
    outerRadius,
    openingRadius,
    confidence: 99,
    score: 99,
    fallbackUsed: false,
  };

  console.log(`[Compositor v10] Using known geometry for book ${bookId}: cx=${geo.cx}, cy=${geo.cy}, outer=${geo.outerRadius}, opening=${geo.openingRadius}`);

  const clipRadius = Math.max(14, geo.openingRadius - OPENING_SAFETY_INSET);
  console.log(`[Compositor v10] Clip radius: ${clipRadius}`);

  // Step 1: Fill background
  const fill = sampleCoverBackground({ coverImg, geo });
  ctx.fillStyle = `rgb(${fill[0]}, ${fill[1]}, ${fill[2]})`;
  ctx.fillRect(0, 0, width, height);

  // Step 2: Draw generated art, clipped to medallion circle
  const sparseInfo = this.detectSparseContent(generatedImg);
  const crop = sourceCropForGenerated(generatedImg, sparseInfo);
  ctx.save();
  ctx.beginPath();
  ctx.arc(geo.cx, geo.cy, clipRadius, 0, Math.PI * 2);
  ctx.clip();
  ctx.drawImage(
    generatedImg,
    crop.sx, crop.sy, crop.sw, crop.sh,
    geo.cx - clipRadius, geo.cy - clipRadius,
    clipRadius * 2, clipRadius * 2,
  );
  ctx.restore();

  // Step 3: Draw cover template with punched-out medallion ON TOP
  const coverTemplate = await this.buildCoverTemplate(coverImg, geo);
  ctx.drawImage(coverTemplate, 0, 0, width, height);

  canvas.__compositorMeta = geo;
  return canvas;
},
```

### 1D. Update smartComposite callers to pass bookId

Anywhere `smartComposite` is called, make sure it passes `bookId` (the book number). Search the codebase for all calls to `smartComposite` and add the `bookId` parameter.

### 1E. Call loadRegions at app startup

In the main app initialization (likely `src/static/js/app.js`), add:
```js
// Load compositor geometry registry on startup
Compositor.loadRegions();
```

### 1F. Fix the hardcoded fallback constants

Even though we're not using detection anymore, fix the constants so any residual code paths don't produce garbage:

**Change:**
```js
DEFAULT_CX: 2850,
DEFAULT_CY: 1350,
DEFAULT_RADIUS: 520,
```

**To:**
```js
DEFAULT_CX: 2864,
DEFAULT_CY: 1620,
DEFAULT_RADIUS: 500,
```

And in `fallbackGeometry()`:
```js
if (width === 3784 && height === 2777) {
  cx = 2864;
  cy = 1620;
  outer = 500;
}
```

---

## FIX 2 — Python Backend Compositor (`src/cover_compositor.py`)

### 2A. Fix the hardcoded fallback constants

**Change lines 42-44:**
```python
FALLBACK_CENTER_X = 2864
FALLBACK_CENTER_Y = 1620
FALLBACK_RADIUS = 500
```

### 2B. Make `_resolve_medallion_geometry` prefer region hints over detection

In `_resolve_medallion_geometry()`, if the region has valid `center_x`, `center_y`, and `radius` (all > 0), **skip detection entirely** and use the region values directly:

```python
def _resolve_medallion_geometry(*, cover: Image.Image, cover_path: Path, region: Region) -> dict[str, int]:
    # If we have known geometry from cover_regions.json, USE IT DIRECTLY
    if region.center_x > 0 and region.center_y > 0 and region.radius > 0:
        outer = int(region.radius)
        min_open, max_open = _dynamic_opening_bounds(*cover.size)
        opening = int(np.clip(round(outer * DETECTION_OPENING_RATIO), min_open, max_open))
        opening = min(opening, max(20, outer - MIN_OPENING_MARGIN_PX))
        result = {
            "center_x": int(region.center_x),
            "center_y": int(region.center_y),
            "outer_radius": outer,
            "opening_radius": opening,
            "confidence": 99.0,
            "score": 99.0,
            "fallback_used": False,
        }
        logger.info("Compositor using known geometry: cx=%d cy=%d outer=%d opening=%d",
                     result["center_x"], result["center_y"], result["outer_radius"], result["opening_radius"])
        key = _geometry_cache_key(cover_path)
        _GEOMETRY_CACHE[key] = result
        return result

    # Only fall back to detection if NO region hints exist
    fallback = _fallback_geometry_for_cover(cover=cover, region=region)
    # ... rest of existing detection code ...
```

This means: if `cover_regions.json` provides coordinates (which it does for all 99 books), detection is **never called**.

---

## FIX 3 — Model Display Layout (same as 07B)

**Files:** `src/static/css/style.css` + `src/static/js/pages/iterate.js`

Add `.model-grid` CSS class and change the model checkboxes container from `checkbox-group` to `model-grid`. (See PROMPT-07B for the exact CSS — it was not implemented in the 07B commit.)

---

## MANDATORY VERIFICATION

After implementing:

### Step 1: Check the geometry source

Open browser console. You should see:
```
[Compositor] Loaded geometry for 99 covers
```

When generating a cover, you should see:
```
[Compositor v10] Using known geometry for book X: cx=2864, cy=1620, outer=500, opening=...
```

You should **NOT** see any `[Compositor v9] Detection:` messages. Detection is dead.

### Step 2: Generate test covers

1. Select Book #1 (A Room with a View), Nano Banana Pro, generate 1 variant.
2. Verify:
   - Art is COMPLETELY INSIDE the gold frame (zero bleed)
   - Art is CENTERED (equal gap on all sides)
   - Art FILLS the medallion (no cream/tan background)
3. Repeat with Book #9 (Right Ho, Jeeves) and Book #25 (The Eyes Have It).

**If ANY of these fail, something is wrong with the geometry lookup — do NOT adjust detection parameters. Debug the registry loading instead.**

### Step 3: Check Python backend

Verify the backend logs show:
```
Compositor using known geometry: cx=2864 cy=1620 outer=500 opening=...
```

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `src/static/js/compositor.js` | **REWRITE** | Add geometry registry, replace smartComposite to use known coords, fix fallback constants |
| `src/app.py` (or routes file) | **ADD** | `/api/cover-regions` endpoint serving `cover_regions.json` |
| `src/static/js/app.js` | **ADD** | Call `Compositor.loadRegions()` at startup |
| `src/cover_compositor.py` | **FIX** | Fix fallback constants (cy=1620), skip detection when region hints exist |
| `src/static/css/style.css` | **ADD** | `.model-grid` card-style layout |
| `src/static/js/pages/iterate.js` | **FIX** | Pass `bookId` to smartComposite, use `model-grid` class |

---

## WHY THIS WILL WORK

1. **No detection = no detection bugs.** The warm-gold ring scanner has failed twice. We're removing it from the compositing path entirely.
2. **Known coordinates are verified.** `cover_regions.json` was computed with high confidence (0.96) across all 99 covers. They all share the same template.
3. **The Y-offset bug (1350 vs 1620) is eliminated.** We're using the actual value of 1620.
4. **Consensus fallback is safe.** Even for books not in the registry, `cx=2864, cy=1620, radius=500` is correct because all covers use the same template.
