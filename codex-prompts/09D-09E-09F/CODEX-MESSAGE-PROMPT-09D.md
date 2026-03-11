# Codex Task — PROMPT-09D: Frame Protection & Anti-Border Directives

## Priority: CRITICAL — Deploy Immediately

## Context

After PROMPT-09A/09B/09C deployment, the AI-generated art includes its own decorative circular borders (floral vines, scrollwork) that visually overpower the original gold filigree ornaments. The SMask compositing works at the data level, but AI art bleeds through the semi-transparent zone.

## What To Do

Follow **PROMPT-09D-FRAME-PROTECTION.md** exactly:

1. **`src/pdf_compositor.py`** — Add frame zone hard-masking: zero out AI art pixels in the frame ring (SMask 5–250) and outer zone (SMask <5) BEFORE compositing. This ensures nothing from the AI art can show through the gold ornament zone.

2. **`src/prompt_generator.py`** — Strengthen anti-border directives: expand `REQUIRED_PHRASE_NO_FRAME`, add canvas directive to `build_diversified_prompt()`, extend negative prompt with specific border terms.

3. **`config/prompt_templates.json`** — Update negative prompt if applicable.

## Verification

After changes, run:
```bash
python scripts/verify_composite.py <output.jpg> --source-pdf <source.pdf> --output-pdf <output.pdf> --strict
```
ALL checks must PASS. Do not commit if any fail.

## Final Step

```bash
git add -A && git commit -m "PROMPT-09D: Hard-mask frame zone + stronger anti-border directives" && git push
```

Railway will auto-deploy after push.
