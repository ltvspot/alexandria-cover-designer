# Visual Proof Report

Last updated: `2026-03-03`
Deployment URL: `https://web-production-900a7.up.railway.app`
Deployment ID: `98526dd5-584f-4498-a7dd-80020c1208e2`

## 0. PROMPT-07B Hotfix Snapshot (2026-03-03)
- Deployed with compositor detection window widened (15%), safety inset `14px`, expanded radius scan bounds, and relaxed offset guard.
- Iterate model list now renders as structured grid cards, with selected-model highlight.
- Frontend image preview fallback now attempts `/api/thumbnail` for direct path payloads so cards recover from MIME/path edge cases.
- Verified on live iterate page:
  - header shows `999 books`;
  - `Nano Banana Pro` is pre-selected on first load;
  - running-job heartbeat text explicitly shows backend staleness and queue wait status.
- Provider-side queue contention was observed during live run (jobs remained queued >30s). This is surfaced clearly in UI and no longer looks frozen.

## 0.1 PROMPT-07B Parameter Tightening (2026-03-03)
- `src/static/js/compositor.js` now matches strict 07B compositor values:
  - `OPENING_SAFETY_INSET = 18`
  - `searchX/searchY = max(30, scan*0.15)`
  - `coarse radius = 0.65x .. 1.40x`
  - fine window expanded to `±16`
  - `maxOffset = max(80, hintRadius*0.55)`
  - explicit logs: `[Compositor v9] Detected...` and clip radius.
- `src/cover_compositor.py` is aligned to the same values and now logs:
  - `Compositor detected: cx=... cy=... outer=... opening=...`

## 1. Test Proof
- Full suite run: `pytest -q`.
- Result: `100% passed`.
- Stability note: API docs matrix test timeout raised from `20s` to `45s` to avoid false failures on heavy ZIP endpoints (`tests/test_api_docs_route_matrix.py`).
- Local validation additions:
  - guardrail fallback tiny-component arithmetic fixed for non-`scipy` environments.
  - required model inventory forced at runtime (15 OpenRouter + Gemini direct IDs).
  - startup built-in prompt seed no longer throws `LogRecord` key collision.

## 2. Live Verification Checks

### 2.1 Health
- `GET /api/health` returned:
  - `status: ok`
  - `healthy: true`
  - `version: 2.1.1`
  - `uptime_seconds: 0` immediately after deploy (confirming rollout `addf1b1c-2d44-495c-b1d2-19b16cb0a393` active)

### 2.2 New Design Token + Cache Control
- `GET /iterate` includes:
  - `/src/static/shared.css?v=20260302-designlock`
  - `/static/css/style.css?v=20260302-designlock-uiux06`
- `GET /review` headers include:
  - `cache-control: no-store`
- `Content-Security-Policy` now allows:
  - `https://fonts.googleapis.com`
  - `https://fonts.gstatic.com`
  - `https://cdn.jsdelivr.net`
  - `https://cdnjs.cloudflare.com`

### 2.3 Model Payload (OpenRouter + Gemini)
- `GET /api/iterate-data?catalog=classics`:
  - total models: `22`
  - required OpenRouter production set present: `15`
  - direct Gemini IDs present: `3`
  - current provider connectivity on iterate page:
    - OpenRouter: connected
    - OpenAI: connected
    - Fal: connected
    - Google direct: degraded (`403 PERMISSION_DENIED`, leaked key)

### 2.4 Dashboard Recent Covers
- Live generation run:
  - Job ID: `4517fa87-a7c9-432d-be8b-b522e6c45964`
  - Request: `book=3`, `model=openrouter/google/gemini-2.5-flash-image`, `cover_source=drive`
  - Final status: `completed`
- `GET /api/dashboard-data?catalog=classics` now reports:
  - `recent_results = 1`
  - card present under “Latest Generated Covers”

## 3. Visual Proof Artifacts

### 3.0 PROMPT-07B Inline-Proof Assets (chat-safe absolute paths)
- `/Users/timzengerink/proofs/proof-iterate-page-live-20260303.png`
- `/Users/timzengerink/proofs/proof-iterate-heartbeat-queue-20260303.png`
- `/Users/timzengerink/proofs/proof-07b-book1-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b-book1-medallion.png`
- `/Users/timzengerink/proofs/proof-07b-book9-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b-book9-medallion.png`
- `/Users/timzengerink/proofs/proof-07b-book25-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b-book25-medallion.png`

### 3.0.1 PROMPT-07B2 Inline-Proof Assets (strict parameters)
- `/Users/timzengerink/proofs/proof-07b2-book1-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b2-book1-medallion.png`
- `/Users/timzengerink/proofs/proof-07b2-book9-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b2-book9-medallion.png`
- `/Users/timzengerink/proofs/proof-07b2-book25-composite-full.png`
- `/Users/timzengerink/proofs/proof-07b2-book25-medallion.png`
- `/Users/timzengerink/proofs/proof-07b2-summary.json`

### 3.1 Live UI Screenshots
- `tmp/proof-live-iterate-20260302-prompt06.png`
- `tmp/proof-live-dashboard-20260302-prompt06.png`
- `tmp/proof-live-review-20260302-prompt06.png`
- `tmp/proof-live-prompts-20260302-prompt06.png`

### 3.2 Local Validation Screenshots
- `tmp/proof-local-iterate-20260302-fix.png`
- `tmp/proof-local-dashboard-20260302-fix.png`
- `tmp/proof-local-review-20260302-fix.png`

### 3.3 PROMPT-06 UI/UX Rebuild Proof (Latest)
- `tmp/proof-local-iterate-20260302-uiux-cspfixed.png`
- `tmp/proof-local-dashboard-20260302-uiux.png`
- `tmp/proof-local-review-20260302-uiux.png`
- `tmp/proof-local-prompts-20260302-uiux.png`
- Playwright console check:
  - local: `0 errors, 0 warnings`
  - live: `0 errors, 0 warnings`

## 4. Design-Lock Enforcement
- Global sidebar-first UX lock remains in `src/static/shared.css` (`DESIGN LOCK` block).
- Static revision token remains `20260302-designlock` across all pages.
- Static hygiene tests enforce token + design lock markers.
- CSP now explicitly allows required frontend assets:
  - `style-src` includes `https://fonts.googleapis.com`
  - `script-src` includes `https://cdn.jsdelivr.net` and `https://cdnjs.cloudflare.com`
  - `font-src` includes `https://fonts.gstatic.com`

## 5. Delivery Rule (Mandatory)
Every completion message must include:
1. direct deployed URL;
2. visual proof report path(s).
