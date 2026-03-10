# VISUAL PROOF REPORT

Date: 2026-03-10

Prompt: `PROMPT-38-SCENE-FIRST-PROMPT-RESTRUCTURE`

Release branch/worktree: `/private/tmp/alexandria-prompt39-scene-first`

Functional release commit: `b33e7a8`

Proof-report commit: `63e8dbd`

Latest deployed app:

- [https://web-production-900a7.up.railway.app](https://web-production-900a7.up.railway.app)

Latest Railway deployment:

- `de4da62d-cf5a-43fc-8c2a-00d1bf1ef0c0`
- status: `SUCCESS`

Runtime note:

- `de4da62d-cf5a-43fc-8c2a-00d1bf1ef0c0` is the report-tip deploy.
- The functional scene-first rollout was `cb98d244-b344-4967-9c5b-8abefde57d0b`.
- The final report-tip deploy is runtime-equivalent for the PROMPT-38 code path.

## What was verified live

1. `GET /api/health` returned `status=ok`, `healthy=true`, `books_cataloged=2397`.
2. Live prompt library for `alexandria-base-romantic-realism` contains the new scene-first template starting with `Book cover illustration only` and placing `{SCENE}` in the first block.
3. On the deployed Iterate page for book `4` (`Emma`), `BASE 4 — Romantic Realism` shows:
   - specific scene text for Emma
   - specific mood text
   - specific era text
4. Live `POST /api/generate` dry-run for book `4` resolved the full prompt from enrichment without generic placeholders.
5. A real live generation job completed on production for book `4` with:
   - job id `7e44b9bf-cbdf-4526-a807-925a183f5264`
   - model `openrouter/google/gemini-3-pro-image-preview`
   - `library_prompt_id=alexandria-base-romantic-realism`
   - `compositor_mode=pdf`

## Live resolved prompt proof

Excerpt from the deployed dry-run payload:

> Book cover illustration only — no text, no title, no author name, no lettering of any kind. No border, no frame, no ornamental elements. This circular medallion illustration MUST depict the following specific scene: Emma Woodhouse, standing in the drawing room of Hartfield, confidently declaring her matchmaking plans to her father, Mr. Woodhouse, who sits in a chair looking concerned. The main character is Emma Woodhouse — a young woman with a fair complexion, lively eyes, and dressed in fashionable early 19th-century attire, often in light colors. ... The mood is Witty, light-hearted, and ultimately reflective. Era reference: Early 19th century, specifically the 1810s.

Saved response artifact:

- [`prompt38_dry_run_response.json`](/private/tmp/alexandria-prompt39-scene-first/output/playwright/prompt38_dry_run_response.json)

## Visual artifacts

Combined proof sheet:

- [`live-proof-sheet-prompt38.png`](/private/tmp/alexandria-prompt39-scene-first/output/playwright/live-proof-sheet-prompt38.png)

Underlying screenshots:

- [`page-2026-03-10T17-03-18-469Z.png`](/private/tmp/alexandria-prompt39-scene-first/.playwright-cli/page-2026-03-10T17-03-18-469Z.png)
- [`live-book4-variant2-raw-proof.png`](/private/tmp/alexandria-prompt39-scene-first/output/playwright/live-book4-variant2-raw-proof.png)

## Honest residual issue observed during proof

The live app resolved the scene-first prompt correctly and completed at least one real production Emma job, but two older artifact surfaces are still inconsistent:

1. The result card preview showed `No preview yet` even after completion for one completed card.
2. `GET /api/variant-download?book=4&variant=2...` and `GET /api/visual-qa/image/4?catalog=classics` did not return the completed generated artifact for this proof run.

Those issues did not block prompt-resolution verification, but they are separate runtime artifact-delivery gaps and should not be misrepresented as fixed by PROMPT-38.
