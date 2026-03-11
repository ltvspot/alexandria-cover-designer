# PROMPT-07E — Fix Compositor: Art Too Small + Not Centered + Original Cover Visible

**Priority:** CRITICAL — Four rounds of fixes have failed (07B x2, 07C, 07D). This prompt takes the simplest possible approach with aggressive sizing.

**Branch:** `master`

---

## ⚠️ DESIGN PRESERVATION — DO NOT CHANGE

Only modify the specific files listed in this prompt. Do NOT touch `index.html`, sidebar, navigation, color scheme, page layouts, or any file not listed.

---

## THE ACTUAL PROBLEMS (From Visual Inspection of Screenshots)

1. **Art is too small** — generated art appears as a small circle inside the medallion instead of filling it
2. **Art appears off-center** — each generated image has different visual centering within the medallion
3. **Original cover visible** — the original cover's background artwork shows through around and behind the ornaments
4. **Different edge ratios** — each cover shows different gaps between the art edge and the frame

**Root cause chain:**
1. `config/compositing_mask.png` restricts the art to ~380px radius — FAR too small for the ~460px frame opening
2. `_smart_square_crop()` uses content-aware foreground detection that shifts the crop center based on image content — this makes each image appear differently positioned within the circle
3. The cover overlay's punch radius (462) is SMALLER than the art clip radius (464), so 2px of original cover artwork shows through
4. `OPENING_SAFETY_INSET_PX = 18` makes art 18px smaller than the opening
5. `OVERLAY_PUNCH_INSET_PX = 20` makes the punch 20px smaller than the opening

---

## THE FIX — FOUR CHANGES

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
DETECTION_OPENING_RATIO = 0.96
OPENING_SAFETY_INSET_PX = 0
OVERLAY_PUNCH_INSET_PX = -4
```

**Why these values:**
- `DETECTION_OPENING_RATIO = 0.96` → With outer_radius=500, `opening_radius = round(500 * 0.96) = 480`
- `OPENING_SAFETY_INSET_PX = 0` → `clip_radius = 480 - 0 = 480` (art fills to 480px — covers ALL ornamental scrollwork)
- `OVERLAY_PUNCH_INSET_PX = -4` (NEGATIVE!) → `punch_radius = 480 + 4 = 484` (cover overlay is transparent to 484px)

**The punch is 4px BIGGER than the art circle.** This means:
- Art fills from center to **480px** (was ~380px with mask — 26% larger)
- Cover overlay is transparent from center to 484px
- The 4px gap (480-484) shows background fill color (navy) — invisible against the navy cover
- Cover overlay is opaque beyond 484px (shows outer frame ring)
- **ZERO original cover artwork visible anywhere**

**Frame preservation:** Only the outermost 16px ring (484-500px) shows the original cover — this is the thick outer gold border with beading. The inner ornamental scrollwork (380-480px) is replaced by art, which is an acceptable tradeoff for a clean result.

### 3. Fix content-aware cropping to ALWAYS use image center (`src/cover_compositor.py`)

The function `_smart_square_crop()` currently detects foreground subjects and shifts the crop center to follow them. This causes each AI-generated image to appear differently positioned within the medallion circle, making the art look off-center and giving different edge ratios per image.

**Replace the entire `_smart_square_crop()` function** with a simple center crop:

```python
def _smart_square_crop(image: Image.Image) -> Image.Image:
    """Crop image to a centered square.

    Always crops from the exact center of the image to ensure consistent
    visual centering when composited into the medallion frame.
    """
    src = image.convert("RGBA")
    img_w, img_h = src.size
    if img_w <= 1 or img_h <= 1:
        return src
    side = min(img_w, img_h)
    left = (img_w - side) // 2
    top = (img_h - side) // 2
    return src.crop((left, top, left + side, top + side))
```

**Why:** The old version detected foreground bounding boxes and energy centers, shifting the crop to follow the subject. This meant every AI-generated image got cropped differently, appearing off-center in the medallion. A simple center crop ensures ALL images are consistently centered within the circle.

### 4. Fix JavaScript frontend constants (`src/static/js/compositor.js`)

Find and change these constants (near the top of the file, around lines 4-9):

```javascript
// OLD VALUES:
const OPENING_RATIO = 0.965;
const OPENING_MARGIN = 6;
const OPENING_SAFETY_INSET = 18;

// NEW VALUES:
const OPENING_RATIO = 0.96;
const OPENING_MARGIN = 6;
const OPENING_SAFETY_INSET = 0;
```

**Also fix `buildCoverTemplate()`** (around line 523-534). Currently it punches at `geo.openingRadius` which doesn't match the Python backend. Change it to punch at `geo.openingRadius + 4` to match:

```javascript
async function buildCoverTemplate(coverImg, geo) {
  const { width, height } = normalizedImageSize(coverImg);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(coverImg, 0, 0, width, height);
  ctx.save();
  ctx.globalCompositeOperation = 'destination-out';
  ctx.beginPath();
  // Punch slightly BIGGER than openingRadius to ensure no original cover shows
  const punchRadius = geo.openingRadius + 4;
  ctx.arc(geo.cx, geo.cy, punchRadius, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  return canvas;
}
```

**Also fix `smartComposite()` content-aware crop in JS** — find the `_smartSquareCrop` or equivalent crop logic in `smartComposite()`. If it does content-aware cropping (energy center, foreground detection), simplify it to always crop from the image center, matching the Python change above.

**Version bump:** Change the `[Compositor v10]` log strings to `[Compositor v12]`.

---

## WHAT THIS ACHIEVES

| Before (broken) | After (fixed) |
|---|---|
| Art restricted to ~380px by compositing mask | Art fills to **480px** (53% larger diameter) |
| Content-aware crop shifts visual center per image | Simple center crop — all images consistently centered |
| 2px gap shows original cover artwork | 4px gap shows navy fill (invisible) |
| Different edge ratios per generated image | Uniform edge ratios — same circle for all |
| Original medallion art visible around edges | ZERO original cover visible |
| Outer ~38px frame ring preserved | Outer **16px** frame ring preserved (thick gold border with beading) |

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

### Step 2: Confirm _smart_square_crop is simplified

Run a quick check:

```bash
grep -c "foreground\|energy_center\|_detect_foreground" src/cover_compositor.py
```

If the count is > 0, the old content-aware logic may still be present. The new `_smart_square_crop()` should have ZERO references to foreground detection.

### Step 3: Check Railway logs after deploy

Look for compositor log lines. You should see opening_radius around 480, clip_radius around 480. You should NOT see any "compositing mask loaded" messages.

### Step 4: Generate test covers and LOOK AT THEM

1. Select Book #1 (A Room with a View), any model, generate 1 variant.
2. **LOOK AT THE OUTPUT:**
   - Does the generated art **FILL** most of the medallion area? (Should fill to ~480px from center)
   - Is there **ANY** visible original cover artwork showing around the generated art? (Should be NONE)
   - Is there a **thin gold frame border** visible around the art? (Should be ~16px wide)
   - Is the art **CENTERED** consistently within the medallion? (Should be perfectly centered at cx=2864, cy=1620)

3. Generate another variant for Book #9 and Book #25. All three should show:
   - Same circle size
   - Same centering
   - Same edge ratios
   - Only difference should be the art content itself

4. If the art appears off-center or at different sizes, the `_smart_square_crop()` was not simplified correctly.

### Step 5: Visual comparison across multiple covers

Generate variants for 3 different books. Compare the edge gaps. They should be **identical** (same distance from art edge to frame ring on all sides of all covers).

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `config/compositing_mask.png` | **RENAME** to `.disabled` | Disable the over-restrictive mask |
| `src/cover_compositor.py` | **MODIFY 3 constants** | DETECTION_OPENING_RATIO=0.96, OPENING_SAFETY_INSET_PX=0, OVERLAY_PUNCH_INSET_PX=-4 |
| `src/cover_compositor.py` | **REPLACE `_smart_square_crop()`** | Simple center crop instead of content-aware |
| `src/static/js/compositor.js` | **MODIFY 2 constants + 1 function** | OPENING_RATIO=0.96, OPENING_SAFETY_INSET=0, fix buildCoverTemplate punch |
| `src/static/css/style.css` | **ADD** | `.model-grid` card-style layout |
| `src/static/js/pages/iterate.js` | **MODIFY** | Use `model-grid` class |

---

## WHY THIS WILL WORK

1. **No mask interference** — the compositing_mask was the primary cause of the "tiny art" problem
2. **Aggressive sizing** — art fills to 480px, covering ALL ornamental scrollwork. Only the outermost 16px thick gold border ring is preserved.
3. **Consistent centering** — simple center crop means every image is positioned identically within the circle. No more content-aware shifting.
4. **Matched circles** — art (480px) and punch (484px) are within 4px, with punch being BIGGER. No original cover can show through.
5. **Uniform edge ratios** — without content-aware crop shifting, all covers will have identical edge distances.
6. **Minimal code changes** — rename one file, change 5 constants, simplify 1 function, fix 1 function. Low risk.
