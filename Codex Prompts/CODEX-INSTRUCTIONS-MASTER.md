# Codex Master Instructions — Alexandria Cover Designer

**Upload all numbered prompt files to Codex. Paste the chatbox message from below.**

---

## MASTER TASK: Implement Prompts 1A through 5

You have implementation prompts to execute in strict sequence. Each builds on the previous one. Read `Project state Alexandria Cover designer.md` first for full context.

### Execution Order (STRICT — do not reorder)

1. **Prompt 1A** — Cover Analysis → Detect the center illustration region in input covers
2. **Prompt 1B** — Prompt Engineering → Build book-specific AI prompts for all 99 titles × 5 variants
3. **Prompt 2A** — Image Generation Pipeline → Batch-generate 495 illustrations via AI API
4. **Prompt 2B** — Quality Gate → Auto-score and filter generated images
5. **Prompt 3A** — Cover Composition → Composite new illustrations into cover templates
6. **Prompt 3B** — Format Export → Export as .ai, .jpg, .pdf matching input specs
7. **Prompt 4A** — Batch Orchestration → End-to-end pipeline from input to output
8. **Prompt 4B** — Google Drive Sync → Upload outputs to Google Drive
9. **Prompt 5** — Visual QA Tool → Side-by-side comparison for Tim's review

### Why This Order Matters

- **1A must be first**: Can't composite without knowing where the center region is
- **1B before 2A**: Need prompts before generating images
- **2B after 2A**: Quality gate filters bad generations
- **3A needs 1A + 2A**: Compositing requires both the template mask and the new illustration
- **3B after 3A**: Export needs the composited cover
- **4A wraps everything**: Orchestrator connects all phases
- **4B after 4A**: Upload requires completed outputs
- **5 last**: QA tool reviews everything

### For Each Prompt

1. Read the prompt file (e.g., `Codex Prompts/PROMPT-1A-COVER-ANALYSIS.md`)
2. Read `Project state Alexandria Cover designer.md` for architecture context
3. Implement ALL features described in the prompt
4. Run ALL verification checks from the prompt's checklist — ACTUAL execution, not code review
5. If ANY check fails → fix → re-run ALL checks → repeat until 100% PASS
6. Write output record to `Codex Output Answers/PROMPT-{ID}-OUTPUT.md`
7. Commit and push to master after each prompt passes all checks
8. Move to the next prompt

### Commit Strategy

- One commit per prompt
- Commit messages:
  - `feat: Prompt 1A — Cover analysis (center region detection)`
  - `feat: Prompt 1B — Prompt engineering (99 books × 5 variants)`
  - `feat: Prompt 2A — Image generation pipeline (FLUX.1 batch)`
  - `feat: Prompt 2B — Quality gate (scoring + filtering)`
  - `feat: Prompt 3A — Cover composition (illustration compositing)`
  - `feat: Prompt 3B — Format export (.ai/.jpg/.pdf)`
  - `feat: Prompt 4A — Batch orchestration (end-to-end pipeline)`
  - `feat: Prompt 4B — Google Drive sync`
  - `feat: Prompt 5 — Visual QA tool`

### Golden Rules (Apply to ALL Prompts)

1. **NEVER modify files in `Input Covers/`** — read-only
2. **NEVER modify `Project state Alexandria Cover designer.md`** — managed by Cowork/Tim only
3. **NEVER change ornamental borders, text, or layout** — only the center illustration
4. **Output filenames must match input filenames** (folders without " copy" suffix)
5. **All outputs: 3784×2777, 300 DPI**
6. **Handle Unicode in filenames** (accents, em-dashes, curly quotes)
7. **Quality over speed** — illustrations must look like real oil paintings

### ⛔ MANDATORY DEPLOYMENT + HUMAN-LIKE TESTING (Apply to ALL Prompts)

**This overrides everything above. No prompt is complete without deployment verification.**

After EVERY implementation, you MUST:

1. **`git add` + `git commit` + `git push`** to main/master branch
2. **Wait for Railway deployment** to complete
3. **Open the LIVE production webapp** at `https://web-production-900a7.up.railway.app`
4. **Use the webapp like a human would:**
   - Navigate to `/iterate`
   - Select a book, select a model, click Generate
   - WAIT for generation to complete or fail
   - If it FAILS → diagnose, fix, push again, re-test on production
   - If it SUCCEEDS → verify the cover is relevant to the book
5. **Test at least 3 different books** on the LIVE webapp
6. **Provide the direct deployed webapp link** in your response
7. **Include screenshots** of the actual live webapp showing successful generations

**What is NOT acceptable:**
- ❌ "Tests pass locally" without deploying
- ❌ Running a local server and calling that "verification"
- ❌ Claiming generation works without showing actual covers from PRODUCTION
- ❌ Skipping deployment because "the code looks correct"

**Read VISUAL-REQUIREMENTS.md before ANY code change — it contains ALL 6 non-negotiable rules.**

### Style ≠ Scene (Critical — Apply to ALL Prompts)

- **Style** = art technique, palette, rendering (UNIVERSAL — same for every book)
- **Scene** = characters, settings, narrative moments (BOOK-SPECIFIC — from enrichment data via `{SCENE}`)
- NEVER mix them. If a style says "sunflower fields", every book gets sunflower fields. WRONG.
- The 5 base prompt `style_name`/`style_description` values are LOCKED. See VISUAL-REQUIREMENTS.md.
- The catalog has **2,000+ books** (continuously growing), NOT 99.
