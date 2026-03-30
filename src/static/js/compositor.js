const ANALYSIS_W = 420;
const COARSE_STEP = 4;
const FINE_STEP = 1;
const OPENING_RATIO = 0.96;
const OPENING_MIN = 360;
const OPENING_MAX = 530;
const CONFIDENCE_MIN = 4.0;
const OPENING_MARGIN = 6;
const OPENING_SAFETY_INSET = 18;
const KNOWN_DEFAULT_CX = 2864;
const KNOWN_DEFAULT_CY = 1620;
const KNOWN_DEFAULT_RADIUS = 500;

// Geometry registry sourced from /api/cover-regions.
let _regionRegistry = null;
let _consensusRegion = { cx: KNOWN_DEFAULT_CX, cy: KNOWN_DEFAULT_CY, radius: KNOWN_DEFAULT_RADIUS };

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value)));
}

function ringSamples(count) {
  const out = [];
  const n = Math.max(8, Number(count || 8));
  for (let i = 0; i < n; i += 1) {
    const angle = (i / n) * Math.PI * 2;
    out.push([Math.cos(angle), Math.sin(angle)]);
  }
  return out;
}

const COARSE_SAMPLES = ringSamples(96);
const FINE_SAMPLES = ringSamples(180);

function createCanvas(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width));
  canvas.height = Math.max(1, Math.round(height));
  return canvas;
}

function normalizedImageSize(img) {
  const w = Number(img?.naturalWidth || img?.width || 0);
  const h = Number(img?.naturalHeight || img?.height || 0);
  return {
    width: Math.max(1, w),
    height: Math.max(1, h),
  };
}

function sampleArray(arr, width, height, x, y) {
  const ix = clamp(Math.round(x), 0, width - 1);
  const iy = clamp(Math.round(y), 0, height - 1);
  return arr[(iy * width) + ix];
}

function scoreRing({ warm, sat, contrast, width, height, cx, cy, radius, samples, includeContrast }) {
  if (radius < 8) return Number.NEGATIVE_INFINITY;
  let warmSum = 0;
  let satSum = 0;
  let contrastSum = 0;
  const total = samples.length;
  for (let i = 0; i < total; i += 1) {
    const [cosA, sinA] = samples[i];
    const px = cx + (radius * cosA);
    const py = cy + (radius * sinA);
    warmSum += sampleArray(warm, width, height, px, py);
    satSum += sampleArray(sat, width, height, px, py);
    if (includeContrast) {
      contrastSum += sampleArray(contrast, width, height, px, py);
    }
  }
  const ringWarm = warmSum / Math.max(1, total);
  const ringSat = satSum / Math.max(1, total);
  if (includeContrast) {
    const ringContrast = contrastSum / Math.max(1, total);
    return ringWarm + (0.24 * ringSat) + (0.60 * ringContrast);
  }
  return ringWarm + (0.26 * ringSat);
}

function ringPeakConfidence({ warm, sat, contrast, width, height, cx, cy, radius }) {
  const probes = [
    [-10, 0, 0],
    [10, 0, 0],
    [0, -10, 0],
    [0, 10, 0],
    [-8, -8, 0],
    [8, 8, 0],
    [0, 0, -10],
    [0, 0, 10],
  ];
  const best = scoreRing({
    warm,
    sat,
    contrast,
    width,
    height,
    cx,
    cy,
    radius,
    samples: FINE_SAMPLES,
    includeContrast: false,
  });
  const local = [];
  for (let i = 0; i < probes.length; i += 1) {
    const [dx, dy, dr] = probes[i];
    const s = scoreRing({
      warm,
      sat,
      contrast,
      width,
      height,
      cx: cx + dx,
      cy: cy + dy,
      radius: Math.max(12, radius + dr),
      samples: FINE_SAMPLES,
      includeContrast: false,
    });
    if (Number.isFinite(s)) local.push(s);
  }
  if (!local.length || !Number.isFinite(best)) return 0;
  local.sort((a, b) => a - b);
  const median = local[Math.floor(local.length / 2)];
  return Math.max(0, best - median);
}

function openingBounds(width, height) {
  if (width === 3784 && height === 2777) return [OPENING_MIN, OPENING_MAX];
  const base = Math.min(width, height);
  return [Math.max(16, Math.round(base * 0.12)), Math.max(24, Math.round(base * 0.46))];
}

function fallbackGeometry({ width, height, hintCx, hintCy, hintRadius }) {
  let cx;
  let cy;
  let outer;
  if (width === 3784 && height === 2777) {
    cx = KNOWN_DEFAULT_CX;
    cy = KNOWN_DEFAULT_CY;
    outer = KNOWN_DEFAULT_RADIUS;
  } else {
    cx = Number.isFinite(hintCx) ? hintCx : Math.round(width * 0.76);
    cy = Number.isFinite(hintCy) ? hintCy : Math.round(height * 0.58);
    outer = Math.max(20, Number.isFinite(hintRadius) ? hintRadius : Math.round(Math.min(width, height) * 0.19));
  }
  const [minOpen, maxOpen] = openingBounds(width, height);
  const opening = Math.min(
    clamp(Math.round(outer * OPENING_RATIO), minOpen, maxOpen),
    Math.max(20, outer - OPENING_MARGIN),
  );
  return {
    cx: clamp(Math.round(cx), 0, width - 1),
    cy: clamp(Math.round(cy), 0, height - 1),
    outerRadius: Math.max(20, Math.round(outer)),
    openingRadius: Math.max(20, Math.round(opening)),
    confidence: 0,
    score: 0,
    fallbackUsed: true,
  };
}

function imageDataForDetection(img) {
  const { width, height } = normalizedImageSize(img);
  const scale = Math.min(1, ANALYSIS_W / Math.max(width, height));
  const scanW = Math.max(1, Math.round(width * scale));
  const scanH = Math.max(1, Math.round(height * scale));
  const canvas = createCanvas(scanW, scanH);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, scanW, scanH);
  const rgba = ctx.getImageData(0, 0, scanW, scanH).data;

  const size = scanW * scanH;
  const warm = new Float32Array(size);
  const sat = new Float32Array(size);
  const gray = new Float32Array(size);
  const contrast = new Float32Array(size);

  for (let y = 0; y < scanH; y += 1) {
    for (let x = 0; x < scanW; x += 1) {
      const i = (y * scanW) + x;
      const idx = i * 4;
      const r = rgba[idx];
      const g = rgba[idx + 1];
      const b = rgba[idx + 2];
      warm[i] = (r - b) + (0.45 * (g - b));
      sat[i] = Math.max(r, g, b) - Math.min(r, g, b);
      gray[i] = (0.299 * r) + (0.587 * g) + (0.114 * b);
    }
  }

  for (let y = 0; y < scanH; y += 1) {
    for (let x = 0; x < scanW; x += 1) {
      const i = (y * scanW) + x;
      const right = x < (scanW - 1) ? Math.abs(gray[i + 1] - gray[i]) : 0;
      const down = y < (scanH - 1) ? Math.abs(gray[i + scanW] - gray[i]) : 0;
      contrast[i] = right + down;
    }
  }

  return {
    warm,
    sat,
    contrast,
    width,
    height,
    scanW,
    scanH,
    scale,
  };
}

function detectMedallionGeometry(coverImg, hints = {}) {
  const { width, height } = normalizedImageSize(coverImg);
  if (width <= 0 || height <= 0) {
    return fallbackGeometry({ width: 3784, height: 2777 });
  }

  const detected = imageDataForDetection(coverImg);
  const {
    warm,
    sat,
    contrast,
    scanW,
    scanH,
    scale,
  } = detected;

  const hintCx = Number(hints.cx);
  const hintCy = Number(hints.cy);
  const hintRadius = Number(hints.radius);

  const cx0 = (Number.isFinite(hintCx) ? hintCx : KNOWN_DEFAULT_CX) * scale;
  const cy0 = (Number.isFinite(hintCy) ? hintCy : KNOWN_DEFAULT_CY) * scale;
  const r0 = Math.max(20, (Number.isFinite(hintRadius) ? hintRadius : KNOWN_DEFAULT_RADIUS) * scale);

  const searchX = Math.max(30, Math.round(scanW * 0.15));
  const searchY = Math.max(30, Math.round(scanH * 0.15));
  const coarseRMin = Math.max(24, Math.round(r0 * 0.65));
  let coarseRMax = Math.min(Math.round(Math.min(scanW, scanH) * 0.49), Math.round(r0 * 1.40));
  if (coarseRMax <= coarseRMin) coarseRMax = coarseRMin + 24;

  let best = {
    score: Number.NEGATIVE_INFINITY,
    cx: Math.round(cx0),
    cy: Math.round(cy0),
    r: Math.round(r0),
  };

  const minCy = Math.max(12, Math.round(cy0) - searchY);
  const maxCy = Math.min(scanH - 12, Math.round(cy0) + searchY + 1);
  const minCx = Math.max(12, Math.round(cx0) - searchX);
  const maxCx = Math.min(scanW - 12, Math.round(cx0) + searchX + 1);

  for (let cy = minCy; cy < maxCy; cy += COARSE_STEP) {
    for (let cx = minCx; cx < maxCx; cx += COARSE_STEP) {
      for (let radius = coarseRMin; radius <= coarseRMax; radius += COARSE_STEP) {
        const score = scoreRing({
          warm,
          sat,
          contrast,
          width: scanW,
          height: scanH,
          cx,
          cy,
          radius,
          samples: COARSE_SAMPLES,
          includeContrast: true,
        });
        if (score > best.score) {
          best = { score, cx, cy, r: radius };
        }
      }
    }
  }

  let fineBest = { ...best };
  const fineRMin = Math.max(20, best.r - 16);
  const fineRMax = Math.min(Math.round(Math.min(scanW, scanH) * 0.50), best.r + 16);

  for (let cy = Math.max(10, best.cy - 16); cy < Math.min(scanH - 10, best.cy + 17); cy += FINE_STEP) {
    for (let cx = Math.max(10, best.cx - 16); cx < Math.min(scanW - 10, best.cx + 17); cx += FINE_STEP) {
      for (let radius = fineRMin; radius <= fineRMax; radius += FINE_STEP) {
        const score = scoreRing({
          warm,
          sat,
          contrast,
          width: scanW,
          height: scanH,
          cx,
          cy,
          radius,
          samples: FINE_SAMPLES,
          includeContrast: false,
        });
        if (score > fineBest.score) {
          fineBest = { score, cx, cy, r: radius };
        }
      }
    }
  }

  const inv = 1 / Math.max(1e-6, scale);
  const centerX = Math.round(fineBest.cx * inv);
  const centerY = Math.round(fineBest.cy * inv);
  const outerRadius = Math.max(20, Math.round(fineBest.r * inv));
  const confidence = ringPeakConfidence({
    warm,
    sat,
    contrast,
    width: scanW,
    height: scanH,
    cx: fineBest.cx,
    cy: fineBest.cy,
    radius: fineBest.r,
  });

  const fallback = fallbackGeometry({
    width,
    height,
    hintCx,
    hintCy,
    hintRadius,
  });

  let useDetected = Number.isFinite(confidence) && confidence >= CONFIDENCE_MIN && Number.isFinite(fineBest.score);
  if (Number.isFinite(hintCx) && Number.isFinite(hintCy) && Number.isFinite(hintRadius) && hintRadius > 0) {
    const dx = centerX - hintCx;
    const dy = centerY - hintCy;
    const offset = Math.sqrt((dx * dx) + (dy * dy));
    const maxOffset = Math.max(80, hintRadius * 0.55);
    if (offset > maxOffset) useDetected = false;
  }

  const outer = useDetected ? outerRadius : fallback.outerRadius;
  const cx = useDetected ? centerX : fallback.cx;
  const cy = useDetected ? centerY : fallback.cy;
  const [minOpen, maxOpen] = openingBounds(width, height);
  const opening = Math.min(
    clamp(Math.round(outer * OPENING_RATIO), minOpen, maxOpen),
    Math.max(20, outer - OPENING_MARGIN),
  );

  const result = {
    cx: Math.round(cx),
    cy: Math.round(cy),
    outerRadius: Math.round(outer),
    openingRadius: Math.round(opening),
    confidence: Number(confidence || 0),
    score: Number(fineBest.score || 0),
    fallbackUsed: !useDetected,
  };
  return result;
}

function sampleCoverBackground({ coverImg, geo }) {
  const { width, height } = normalizedImageSize(coverImg);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(coverImg, 0, 0, width, height);
  const data = ctx.getImageData(0, 0, width, height).data;
  const inner = Math.max(12, geo.outerRadius * 1.42);
  const outer = Math.min(Math.max(width, height), geo.outerRadius * 1.92);

  const samples = [];
  const rings = 120;
  for (let i = 0; i < rings; i += 1) {
    const angle = (i / rings) * Math.PI * 2;
    const dist = inner + (((outer - inner) * (i % 9)) / 8);
    const x = Math.round(geo.cx + (Math.cos(angle) * dist));
    const y = Math.round(geo.cy + (Math.sin(angle) * dist));
    if (x < 0 || y < 0 || x >= width || y >= height) continue;
    const idx = ((y * width) + x) * 4;
    const r = data[idx];
    const g = data[idx + 1];
    const b = data[idx + 2];
    const sat = Math.max(r, g, b) - Math.min(r, g, b);
    const dark = ((r + g + b) / 3) < 135;
    const cool = b >= (r - 6);
    if (sat < 95 && dark && cool) samples.push([r, g, b]);
  }
  if (!samples.length) return [20, 33, 58];
  samples.sort((a, b) => (a[0] + a[1] + a[2]) - (b[0] + b[1] + b[2]));
  const mid = samples[Math.floor(samples.length / 2)];
  return [mid[0], mid[1], mid[2]];
}

function detectSparseContent(generatedImg) {
  const { width, height } = normalizedImageSize(generatedImg);
  const maxSide = 320;
  const scale = Math.min(1, maxSide / Math.max(width, height));
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));

  const canvas = createCanvas(w, h);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(generatedImg, 0, 0, w, h);
  const rgba = ctx.getImageData(0, 0, w, h).data;

  let minAlpha = 255;
  for (let i = 3; i < rgba.length; i += 4) minAlpha = Math.min(minAlpha, rgba[i]);

  let fg = null;
  if (minAlpha < 20) {
    fg = new Uint8Array(w * h);
    for (let i = 0; i < (w * h); i += 1) {
      fg[i] = rgba[(i * 4) + 3] > 32 ? 1 : 0;
    }
  } else {
    const border = Math.max(4, Math.round(Math.min(w, h) * 0.03));
    let sumR = 0;
    let sumG = 0;
    let sumB = 0;
    let count = 0;
    for (let y = 0; y < h; y += 1) {
      for (let x = 0; x < w; x += 1) {
        if (x >= border && x < (w - border) && y >= border && y < (h - border)) continue;
        const idx = ((y * w) + x) * 4;
        sumR += rgba[idx];
        sumG += rgba[idx + 1];
        sumB += rgba[idx + 2];
        count += 1;
      }
    }
    const bgR = sumR / Math.max(1, count);
    const bgG = sumG / Math.max(1, count);
    const bgB = sumB / Math.max(1, count);
    fg = new Uint8Array(w * h);
    for (let y = 0; y < h; y += 1) {
      for (let x = 0; x < w; x += 1) {
        const i = (y * w) + x;
        const idx = i * 4;
        const r = rgba[idx];
        const g = rgba[idx + 1];
        const b = rgba[idx + 2];
        const diff = Math.abs(r - bgR) + Math.abs(g - bgG) + Math.abs(b - bgB);
        const sat = Math.max(r, g, b) - Math.min(r, g, b);
        fg[i] = (diff > 54 || (sat > 30 && diff > 32)) ? 1 : 0;
      }
    }
  }

  let minX = w;
  let minY = h;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      if (fg[(y * w) + x] !== 1) continue;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }

  if (maxX < minX || maxY < minY) return { sparse: false, bbox: null };
  const boxW = (maxX - minX) + 1;
  const boxH = (maxY - minY) + 1;
  const area = (boxW * boxH) / Math.max(1, w * h);
  if (area >= 0.78) return { sparse: false, bbox: null };

  return {
    sparse: area < 0.40,
    bbox: {
      x: minX / w,
      y: minY / h,
      w: boxW / w,
      h: boxH / h,
      area,
    },
  };
}

function sourceCropForGenerated(generatedImg) {
  const { width, height } = normalizedImageSize(generatedImg);
  const side = Math.min(width, height);
  const sx = Math.round((width - side) / 2);
  const sy = Math.round((height - side) / 2);

  return {
    sx,
    sy,
    sw: side,
    sh: side,
  };
}

async function buildCoverTemplate(coverImg, geo) {
  const { width, height } = normalizedImageSize(coverImg);
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(coverImg, 0, 0, width, height);
  ctx.save();
  ctx.globalCompositeOperation = 'destination-out';
  ctx.beginPath();
  const punchRadius = geo.openingRadius + 4;
  ctx.arc(geo.cx, geo.cy, punchRadius, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  return canvas;
}

window.Compositor = {
  COVER_WIDTH: 3784,
  COVER_HEIGHT: 2777,
  DEFAULT_CX: KNOWN_DEFAULT_CX,
  DEFAULT_CY: KNOWN_DEFAULT_CY,
  DEFAULT_RADIUS: KNOWN_DEFAULT_RADIUS,

  async loadRegions() {
    try {
      const resp = await fetch('/api/cover-regions?catalog=classics', { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      _regionRegistry = {};
      const consensus = data?.consensus_region || {};
      const consensusCx = Number(consensus.center_x);
      const consensusCy = Number(consensus.center_y);
      const consensusRadius = Number(consensus.radius);
      _consensusRegion = {
        cx: Number.isFinite(consensusCx) && consensusCx > 0 ? consensusCx : KNOWN_DEFAULT_CX,
        cy: Number.isFinite(consensusCy) && consensusCy > 0 ? consensusCy : KNOWN_DEFAULT_CY,
        radius: Number.isFinite(consensusRadius) && consensusRadius > 0 ? consensusRadius : KNOWN_DEFAULT_RADIUS,
      };
      (Array.isArray(data?.covers) ? data.covers : []).forEach((row) => {
        const coverId = String(row?.cover_id || '').trim();
        const cx = Number(row?.center_x);
        const cy = Number(row?.center_y);
        const radius = Number(row?.radius);
        if (!coverId) return;
        _regionRegistry[coverId] = {
          cx: Number.isFinite(cx) && cx > 0 ? cx : _consensusRegion.cx,
          cy: Number.isFinite(cy) && cy > 0 ? cy : _consensusRegion.cy,
          radius: Number.isFinite(radius) && radius > 0 ? radius : _consensusRegion.radius,
        };
      });
      const count = Object.keys(_regionRegistry).length;
      console.log(`[Compositor] Loaded geometry for ${count} covers`);
    } catch (err) {
      _regionRegistry = {};
      _consensusRegion = { cx: KNOWN_DEFAULT_CX, cy: KNOWN_DEFAULT_CY, radius: KNOWN_DEFAULT_RADIUS };
      console.warn('[Compositor] Failed to load regions, using consensus fallback:', err?.message || err);
    }
  },

  getKnownGeometry(bookId) {
    const key = String(bookId || '').trim();
    const known = (_regionRegistry && key && _regionRegistry[key]) ? _regionRegistry[key] : _consensusRegion;
    return {
      cx: Number(known?.cx || this.DEFAULT_CX),
      cy: Number(known?.cy || this.DEFAULT_CY),
      radius: Number(known?.radius || this.DEFAULT_RADIUS),
    };
  },

  detectMedallionGeometry(coverImg, hints = {}) {
    return detectMedallionGeometry(coverImg, {
      cx: Number.isFinite(Number(hints.cx)) ? Number(hints.cx) : this.DEFAULT_CX,
      cy: Number.isFinite(Number(hints.cy)) ? Number(hints.cy) : this.DEFAULT_CY,
      radius: Number.isFinite(Number(hints.radius)) ? Number(hints.radius) : this.DEFAULT_RADIUS,
    });
  },

  detectSparseContent(generatedImg) {
    return detectSparseContent(generatedImg);
  },

  async buildCoverTemplate(coverImg, geo) {
    return buildCoverTemplate(coverImg, geo);
  },

  async smartComposite({ coverImg, generatedImg, bookId }) {
    if (!coverImg || !generatedImg) {
      throw new Error('coverImg and generatedImg are required for smartComposite');
    }

    const { width, height } = normalizedImageSize(coverImg);
    const canvas = createCanvas(width, height);
    const ctx = canvas.getContext('2d');

    // Use known geometry from cover_regions.json; detection path is intentionally bypassed.
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

    const fill = sampleCoverBackground({ coverImg, geo });
    ctx.fillStyle = `rgb(${fill[0]}, ${fill[1]}, ${fill[2]})`;
    ctx.fillRect(0, 0, width, height);

    const crop = sourceCropForGenerated(generatedImg);
    const clipRadius = Math.max(14, geo.openingRadius - OPENING_SAFETY_INSET);
    console.log(
      `[Compositor v12] Using known geometry for book ${String(bookId || '?')}: cx=${geo.cx}, cy=${geo.cy}, outer=${geo.outerRadius}, opening=${geo.openingRadius}`,
    );
    console.log(`[Compositor v12] Clip radius: ${clipRadius}`);

    ctx.save();
    ctx.beginPath();
    ctx.arc(geo.cx, geo.cy, clipRadius, 0, Math.PI * 2);
    ctx.clip();
    ctx.drawImage(
      generatedImg,
      crop.sx,
      crop.sy,
      crop.sw,
      crop.sh,
      geo.cx - clipRadius,
      geo.cy - clipRadius,
      clipRadius * 2,
      clipRadius * 2,
    );
    ctx.restore();

    const coverTemplate = await this.buildCoverTemplate(coverImg, geo);
    ctx.drawImage(coverTemplate, 0, 0, width, height);

    canvas.__compositorMeta = geo;
    return canvas;
  },
};
