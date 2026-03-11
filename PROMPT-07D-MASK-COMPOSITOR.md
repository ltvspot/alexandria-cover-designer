# PROMPT-07D — Pixel-Perfect Frame Mask Compositing

**Priority:** CRITICAL — Three rounds of fixes have failed (07B x2, 07C). This prompt takes a fundamentally different approach using a pre-computed pixel-perfect mask.

**Branch:** `master`
**Commit after all fixes:** `git add -A && git commit -m "fix: use pixel-perfect frame mask for compositing, kill circular clip (07D)" && git push`

---

## ⚠️ DESIGN PRESERVATION — DO NOT CHANGE

Only modify the specific files listed in this prompt. Do NOT touch `index.html`, sidebar, navigation, color scheme, page layouts, or any file not listed.

---

## WHY ALL PREVIOUS APPROACHES FAILED

### The actual root cause (discovered via pixel-level analysis):

The gold ornamental frame is **NOT a perfect circle**. It has decorative scrollwork that creates an **irregular opening** with varying radius:
- **Minimum opening radius: ~380px** (at the tightest scrollwork points, around 285°)
- **Maximum opening radius: ~460px** (at the widest points, around 255°)

All previous approaches used **circular clipping** with `OPENING_RATIO = 0.965`, which computes:
- `openingRadius = round(500 * 0.965) = 482`
- `clipRadius = 482 - 18 = 464`

**464px exceeds the actual frame opening at most angles.** At the tightest points (380px), art overflows by **84 pixels**. This is why art always bleeds past the frame.

### The solution:

A pre-computed **pixel-perfect mask** (`config/compositing_mask.png`) has been created by:
1. Detecting gold-colored pixels in the frame zone (r > 400px to r < 580px from center)
2. Flood-filling the opening from the center through non-gold pixels
3. Eroding the opening boundary by 15px for safety margin

This mask matches the actual irregular frame shape, not an idealized circle.

**THE MASK FILE `config/compositing_mask.png` IS ALREADY IN THE REPO.** It was updated with the correct pixel-perfect version. It is an RGBA PNG where:
- **Alpha = 255** → art shows through (the opening)
- **Alpha = 0** → frame blocks (art is hidden)

---

## THE NEW APPROACH — MASK-BASED COMPOSITING

### Philosophy
1. **The mask is the source of truth** for where art can appear. Not a circle. Not a ratio.
2. The Python backend ALREADY has infrastructure for this: `_load_global_compositing_mask()` reads `config/compositing_mask.png` and combines it with the clip mask via `np.minimum()`.
3. The JS compositor needs a similar mask-based approach for preview consistency.
4. As belt-and-suspenders, we also reduce the circular clip radius to a **conservative 370px** (well inside the 380px minimum opening), so even without the mask, art stays inside.

---

## FIX 1 — Reduce Circular Clip Radius (Belt-and-Suspenders)

Even though the mask is the primary fix, reduce the circular clip radius so it never exceeds the frame opening even without the mask.

### 1A. JavaScript (`src/static/js/compositor.js`)

**Change line 4:**
```js
// OLD:
const OPENING_RATIO = 0.965;
// NEW:
const OPENING_RATIO = 0.74;
```

This produces `openingRadius = round(500 * 0.74) = 370`, which is safely inside the 380px minimum opening at all angles. The 10px gap will be invisible since the mask provides the actual clipping boundary.

**Also change OPENING_SAFETY_INSET (line 9):**
```js
// OLD:
const OPENING_SAFETY_INSET = 18;
// NEW:
const OPENING_SAFETY_INSET = 4;
```

With the conservative ratio, we don't need a large inset. `clipRadius = 370 - 4 = 366`.

### 1B. Python (`src/cover_compositor.py`)

Find the line where `DETECTION_OPENING_RATIO` or `OPENING_RATIO` equivalent is defined (used in `_resolve_medallion_geometry()`). Change it to match:

```python
DETECTION_OPENING_RATIO = 0.74
```

Also reduce `OPENING_SAFETY_INSET_PX`:
```python
OPENING_SAFETY_INSET_PX = 4
```

And `OVERLAY_PUNCH_INSET_PX`:
```python
OVERLAY_PUNCH_INSET_PX = 4
```

---

## FIX 2 — JS Compositor: Load and Use Frame Mask

The JS compositor should load the frame mask and use it for clipping instead of (or in addition to) the circular clip.

### 2A. Add mask loading to the Compositor object

In `compositor.js`, add a mask loader alongside the existing `loadRegions()`:

```js
let _frameMask = null;

window.Compositor.loadFrameMask = async function () {
  try {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    const loaded = new Promise((resolve, reject) => {
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Failed to load frame mask'));
    });
    img.src = '/static/img/frame_mask.png';
    const maskImg = await loaded;

    // Draw mask to canvas to get pixel data
    const c = document.createElement('canvas');
    c.width = maskImg.naturalWidth || maskImg.width;
    c.height = maskImg.naturalHeight || maskImg.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(maskImg, 0, 0);
    _frameMask = ctx.getImageData(0, 0, c.width, c.height);
    console.log(`[Compositor] Loaded frame mask: ${c.width}x${c.height}`);
  } catch (err) {
    console.warn('[Compositor] Failed to load frame mask, falling back to circular clip:', err.message);
    _frameMask = null;
  }
};
```

### 2B. Call loadFrameMask at startup

In `src/static/js/app.js`, alongside the existing `Compositor.loadRegions()` call, add:
```js
Compositor.loadFrameMask();
```

### 2C. Use mask in smartComposite

Replace the circular clipping section in `smartComposite`. The new approach:
1. First draws the generated art onto a temporary canvas (clipped to the conservative circle for safety)
2. Then applies the frame mask: for every pixel where `frame_mask = 255` (frame), makes the art pixel transparent
3. This ensures art only appears where the mask says "opening"

Replace the art-drawing section of `smartComposite` (the part between the background fill and the cover template overlay) with:

```js
    // Step 2: Draw generated art
    const sparseInfo = this.detectSparseContent(generatedImg);
    const crop = sourceCropForGenerated(generatedImg, sparseInfo);

    // Use conservative circular clip as baseline
    const clipRadius = Math.max(14, geo.openingRadius - OPENING_SAFETY_INSET);
    console.log(`[Compositor v11] Using known geometry for book ${String(bookId || '?')}: cx=${geo.cx}, cy=${geo.cy}, clipRadius=${clipRadius}`);

    // Draw art clipped to circle
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

    // Step 2b: Apply pixel-perfect frame mask (if loaded)
    if (_frameMask && _frameMask.width === width && _frameMask.height === height) {
      console.log('[Compositor v11] Applying pixel-perfect frame mask');
      const artData = ctx.getImageData(0, 0, width, height);
      const maskData = _frameMask.data;  // RGBA
      const pixels = artData.data;
      // frame_mask.png: 0 = opening (art OK), 255 = frame (block art)
      // The mask is grayscale stored as RGBA, so R channel = the mask value
      for (let i = 0; i < pixels.length; i += 4) {
        const maskVal = maskData[i]; // R channel of mask (0=opening, 255=frame)
        if (maskVal > 128) {
          // This pixel is in the frame zone — replace with background fill
          pixels[i] = fill[0];
          pixels[i + 1] = fill[1];
          pixels[i + 2] = fill[2];
          pixels[i + 3] = 255;
        }
      }
      ctx.putImageData(artData, 0, 0);
    } else {
      console.log('[Compositor v11] No frame mask available, using circular clip only');
    }
```

**IMPORTANT:** The `frame_mask.png` in `src/static/img/` uses the ORIGINAL convention: **0 = opening, 255 = frame**. The code above reads the R channel and treats `> 128` as "frame" (block art). This is correct.

### 2D. Update `buildCoverTemplate` to use mask for punch

Replace `buildCoverTemplate` to also use the mask when available:

```js
async function buildCoverTemplate(coverImg, geo) {
  const { width, height } = normalizedImageSize(coverImg);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(coverImg, 0, 0, width, height);

  if (_frameMask && _frameMask.width === width && _frameMask.height === height) {
    // Use pixel-perfect mask: punch out where mask says "opening" (mask R = 0)
    const imgData = ctx.getImageData(0, 0, width, height);
    const maskData = _frameMask.data;
    const pixels = imgData.data;
    for (let i = 0; i < pixels.length; i += 4) {
      const maskVal = maskData[i]; // R channel: 0=opening, 255=frame
      if (maskVal < 128) {
        // Opening: make cover transparent here so art shows through
        pixels[i + 3] = 0; // alpha = 0
      }
    }
    ctx.putImageData(imgData, 0, 0);
  } else {
    // Fallback: circular punch (conservative radius)
    ctx.save();
    ctx.globalCompositeOperation = 'destination-out';
    ctx.beginPath();
    ctx.arc(geo.cx, geo.cy, geo.openingRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  return canvas;
}
```

---

## FIX 3 — Ensure `compositing_mask.png` is properly formatted

The `config/compositing_mask.png` file has already been updated with the correct pixel-perfect mask. **DO NOT regenerate or modify it.** It was created from careful gold-color analysis of the actual cover frames.

Format: RGBA PNG, 3784x2777
- Alpha = 255 → opening (art allowed)
- Alpha = 0 → frame (art blocked)

The Python backend's `_load_global_compositing_mask()` (line 1269-1287 of `cover_compositor.py`) already:
1. Reads this file from `config/compositing_mask.png`
2. Extracts the alpha channel
3. Validates it's not all-opaque or all-transparent
4. Returns it as `strict_window_mask`

And `strict_window_mask` is already combined with the circular clip mask via `_combine_masks()` (using `np.minimum` — most restrictive wins). So the Python backend fix is essentially: **the new mask file + conservative clip radius = done.**

---

## FIX 4 — Ensure `frame_mask.png` serves correctly for JS

The `src/static/img/frame_mask.png` must be served correctly as a static file. It's a grayscale PNG (L mode), 3784x2777:
- 0 = opening (art shows)
- 255 = frame (art blocked)

Verify this file is accessible at `/static/img/frame_mask.png` by loading it in a browser. If it's not served, ensure the Flask static file configuration includes the `img` subdirectory.

---

## FIX 5 — Model Grid Layout (carried over from 07B/07C)

**Files:** `src/static/css/style.css` + `src/static/js/pages/iterate.js`

Add `.model-grid` CSS class for card-style layout of model checkboxes:

```css
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
  padding: 8px 0;
}
.model-grid label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.model-grid label:hover {
  border-color: #888;
  background: #f9f9f9;
}
.model-grid input[type="checkbox"]:checked + span,
.model-grid input[type="radio"]:checked + span {
  font-weight: 600;
}
```

In `iterate.js`, change the model container class from `checkbox-group` to `model-grid`.

---

## MANDATORY VERIFICATION

### Step 1: Check mask loading (Python backend)

Deploy and check the Railway logs. You MUST see:
```
Compositor using known geometry: cx=2864 cy=1620 outer=500 opening=370
```

The `opening=370` (not 482!) confirms the conservative ratio is active.

Also verify the backend loads the compositing mask — look for any mask-related log messages. If `_load_global_compositing_mask` doesn't log, add a temporary log line.

### Step 2: Check mask loading (JS frontend)

Open browser console. You MUST see:
```
[Compositor] Loaded geometry for 99 covers
[Compositor] Loaded frame mask: 3784x2777
```

When generating a cover:
```
[Compositor v11] Using known geometry for book X: cx=2864, cy=1620, clipRadius=366
[Compositor v11] Applying pixel-perfect frame mask
```

### Step 3: Generate test covers

1. Select Book #1 (A Room with a View), Nano Banana Pro, generate 1 variant.
2. **HONESTLY examine the output.** Answer these questions TRUTHFULLY:
   - Is the art COMPLETELY INSIDE the gold frame with ZERO bleed-through at ALL angles?
   - Is there any art visible where the decorative scrollwork/ornaments are?
   - Is the art CENTERED within the medallion?
   - Does the art FILL the opening area?
3. Repeat with Book #9 (Right Ho, Jeeves) and Book #25 (The Eyes Have It).

**If art still bleeds past the frame:** The mask file may not be loading correctly. Check:
- Does `config/compositing_mask.png` exist and have the correct alpha values?
- Does the Python backend log indicate the mask was loaded?
- Is the JS `frame_mask.png` accessible at `/static/img/frame_mask.png`?

**DO NOT go back to tuning detection parameters or circular clip ratios.** The mask IS the solution. Debug mask loading if it doesn't work.

### Step 4: Compare before/after

The difference should be dramatic:
- **Before:** Art visibly bleeds past the gold frame at decorative scrollwork points
- **After:** Art is perfectly contained within the irregular frame opening with a clean boundary

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `src/static/js/compositor.js` | **MODIFY** | Reduce OPENING_RATIO to 0.74, add mask loading, use mask in smartComposite and buildCoverTemplate |
| `src/static/js/app.js` | **ADD LINE** | Call `Compositor.loadFrameMask()` at startup |
| `src/cover_compositor.py` | **MODIFY** | Reduce DETECTION_OPENING_RATIO to 0.74, reduce safety insets |
| `config/compositing_mask.png` | **ALREADY UPDATED** | Pixel-perfect RGBA mask — DO NOT modify |
| `src/static/img/frame_mask.png` | **ALREADY EXISTS** | Grayscale mask for JS compositor — DO NOT modify |
| `src/static/css/style.css` | **ADD** | `.model-grid` card-style layout |
| `src/static/js/pages/iterate.js` | **MODIFY** | Use `model-grid` class |

---

## WHY THIS WILL WORK

1. **Pixel-perfect mask** matches the actual irregular frame shape, not an idealized circle. It was derived from gold-color detection on the real cover images with a 15px safety erosion.
2. **Conservative circular clip (r=366)** as belt-and-suspenders backup ensures art stays well inside even without the mask.
3. **Python backend already has mask infrastructure** (`_load_global_compositing_mask` + `_combine_masks`). Our new mask file drops right in.
4. **Double protection**: circular clip at 366px (inside the 380px minimum opening) AND pixel-perfect mask. Both must allow a pixel for art to show there.
5. **No detection, no ratio tuning, no parameter widening.** The frame shape is what it is — we measured it and encoded it in a mask.
