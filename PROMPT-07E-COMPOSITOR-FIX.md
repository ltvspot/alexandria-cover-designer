# PROMPT-07E — Fix Compositor: Art Too Small + Original Cover Visible

**Priority:** CRITICAL — Four rounds of fixes have failed (07B x2, 07C, 07D). This prompt takes the simplest possible approach.

**Branch:** `master`

---

## ⚠️ DESIGN PRESERVATION — DO NOT CHANGE

Only modify the specific files listed in this prompt. Do NOT touch `index.html`, sidebar, navigation, color scheme, page layouts, or any file not listed.

---

## THE ACTUAL PROBLEM (From Visual Inspection)

The generated art appears as a **small circle inside the medallion** with the **original cover's background image clearly visible** around it. The art is NOT filling the medallion opening, and the original cover artwork (from the input covers) is showing through in the gap.

**Root cause chain:**
1. `config/compositing_mask.png` restricts the art to ~380px radius — FAR too small
2. The cover overlay's punch radius is SMALLER than the art circle, so the original cover's pixels show between the art edge and the frame
3. `OPENING_SAFETY_INSET_PX = 18` makes art 18px smaller than the opening
4. `OVERLAY_PUNCH_INSET_PX = 20` makes the punch 20px smaller than the opening (2px smaller than the art!)

**The 2px gap (punch=462 < art=464) is where the original cover's medallion artwork bleeds through.**

---

## THE FIX — THREE SIMPLE CHANGES

### 1. DISABLE the compositing mask

**Rename** `config/compositing_mask.png` to `config/compositing_mask.png.disabled`:

```bash
mv config/compositing_mask.png config/compositing_mask.png.disabled
```

The `_load_global_compositing_mask()` function in `cover_compositor.py` looks for `config/compositing_mask.png`. By renaming it, the function returns `None` and the mask is not used. **DO NOT delete it** — we may need it later.

This is the **most critical change.** The current mask restricts art to ~380px radius, making it look tiny inside the frame.

### 2. Fix Python backend constants (`src/cover_compositor.py`)

Find and change these constants (they're near the top of the file, around lines 30-35):

```python
# OLD VALUES:
DETECTION_OPENING_RATIO = 0.965
OPENING_SAFETY_INSET_PX = 18
OVERLAY_PUNCH_INSET_PX = 20

# NEW VALUES:
DETECTION_OPENING_RATIO = 0.92
OPENING_SAFETY_INSET_PX = 2
OVERLAY_PUNCH_INSET_PX = -2
```

**Why these values:**
- `DETECTION_OPENING_RATIO = 0.92` → With outer_radius=500, `opening_radius = round(500 * 0.92) = 460`
- `OPENING_SAFETY_INSET_PX = 2` → `clip_radius = 460 - 2 = 458` (art fills to 458px)
- `OVERLAY_PUNCH_INSET_PX = -2` (NEGATIVE!) → `punch_radius = 460 + 2 = 462` (cover is transparent to 462px)

**The punch is now 4px BIGGER than the art circle.** This means:
- Art fills from center to 458px
- Cover overlay is transparent from center to 462px
- The 4px gap (458-462) shows background fill color (navy) — invisible against the navy cover
- Cover overlay is opaque beyond 462px (shows outer frame ring + navy background)
- **ZERO original cover artwork visible anywhere**

**Frame preservation:** Ornaments from 462-500px (the outer ~38px ring) are preserved. This includes the thick outer decorative border. Inner scrollwork (380-462px) is replaced by art.

### 3. Fix JavaScript frontend constants (`src/static/js/compositor.js`)

Find and change these constants (near the top of the file, around lines 4-9):

```javascript
// OLD VALUES:
const OPENING_RATIO = 0.965;
const OPENING_MARGIN = 6;
const OPENING_SAFETY_INSET = 18;

// NEW VALUES:
const OPENING_RATIO = 0.92;
const OPENING_MARGIN = 6;
const OPENING_SAFETY_INSET = 2;
```

**Also fix `buildCoverTemplate()`** (around line 523-534). Currently it punches at `geo.openingRadius` which is BIGGER than `clipRadius`, creating a gap where the original cover shows. Change it to punch at `geo.openingRadius + 4` to match the Python backend's approach:

```javascript
async function buildCoverTemplate(coverImg, geo) {
  const { width, height } = normalizedImageSize(coverImg);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(coverImg, 0, 0, width, height);
  ctx.save();
  ctx.globalCompositeOperation = 'destination-out';
  ctx.beginPath();
  // Punch slightly BIGGER than openingRadius to match clip behavior
  const punchRadius = geo.openingRadius + 4;
  ctx.arc(geo.cx, geo.cy, punchRadius, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  return canvas;
}
```

**Version bump:** Change the `[Compositor v10]` log strings to `[Compositor v12]`.

---

## WHAT THIS ACHIEVES

| Before (broken) | After (fixed) |
|---|---|
| Art restricted to ~380px by compositing mask | Art fills to 458px (27% larger diameter) |
| 2px gap shows original cover artwork | 4px gap shows navy fill (invisible) |
| Original medallion art visible around edges | ZERO original cover visible |
| Ornamental scrollwork partially visible but art behind it is original | Outer 38px frame ring preserved, clean border |

---

## Model Grid Layout (carried over from 07B/07C/07D)

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

### Step 1: Confirm mask is disabled

```bash
ls config/compositing_mask.png 2>/dev/null && echo "ERROR: mask still active!" || echo "OK: mask disabled"
ls config/compositing_mask.png.disabled 2>/dev/null && echo "OK: backup exists"
```

### Step 2: Check Railway logs after deploy

Look for compositor log lines. You should see opening_radius around 460, clip_radius around 458. You should NOT see any "compositing mask loaded" messages.

### Step 3: Generate test covers

1. Select Book #1 (A Room with a View), any model, generate 1 variant.
2. **LOOK AT THE OUTPUT HONESTLY:**
   - Does the generated art **FILL** most of the medallion area? (Should fill to ~458px from center)
   - Is there **ANY** visible original cover artwork showing around the generated art? (Should be NONE)
   - Is there a **thin gold frame border** visible around the art? (Should be ~38px wide at 462-500px)
   - Is the art **CENTERED** within the medallion? (Should be centered at cx=2864, cy=1620)

3. If the original cover's artwork (illustrations, scenery) is STILL visible around the generated art, the compositing_mask.png was NOT disabled. Check that the rename happened.

4. Repeat with Book #9 and Book #25.

### Step 4: Visual comparison

Take a screenshot of the composited output. The result should show:
- Generated art filling most of the circular medallion area
- A thin gold ornamental border around the art (outer frame ring)
- Navy background outside the frame
- NO original cover artwork visible anywhere

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `config/compositing_mask.png` | **RENAME** to `.disabled` | Disable the over-restrictive mask |
| `src/cover_compositor.py` | **MODIFY 3 constants** | DETECTION_OPENING_RATIO=0.92, OPENING_SAFETY_INSET_PX=2, OVERLAY_PUNCH_INSET_PX=-2 |
| `src/static/js/compositor.js` | **MODIFY 2 constants + 1 function** | OPENING_RATIO=0.92, OPENING_SAFETY_INSET=2, fix buildCoverTemplate punch |
| `src/static/css/style.css` | **ADD** | `.model-grid` card-style layout |
| `src/static/js/pages/iterate.js` | **MODIFY** | Use `model-grid` class |

---

## WHY THIS WILL WORK

1. **No mask interference** — the compositing_mask was the primary cause of the "tiny art" problem
2. **Matched circles** — art and punch are within 4px of each other (458 vs 462), with the punch being BIGGER. No original cover can show in the gap.
3. **Conservative approach** — we're not trying to perfectly match an irregular frame shape. We accept that some inner ornamental detail is lost in exchange for a CLEAN result with no artifacts.
4. **Outer frame preserved** — the outermost 38px of the ornamental frame (462-500px) provides a visible gold border around the art.
5. **Simplest possible fix** — rename one file, change 5 constants, fix 1 function. Minimal risk of side effects.
