# Prompt 4B — Google Drive Sync

**Priority**: MEDIUM — Delivers output to Google Drive
**Scope**: `src/gdrive_sync.py`
**Depends on**: Prompt 4A (outputs must exist locally)
**Estimated time**: 30 minutes

---

## Context

Read `PROJECT-STATE.md`. Output covers are generated locally in `Output Covers/`. Tim wants the final output uploaded to Google Drive at: https://drive.google.com/drive/folders/1Vr184ZsX3k38xpmZkd8g2vwB5y9LYMRC

---

## Task

Create `src/gdrive_sync.py` that:

1. Authenticates via Google Drive API (OAuth2 or service account)
2. Creates subfolder structure in Drive matching local output
3. Uploads all variant files (.ai, .jpg, .pdf) per book
4. Skips already-uploaded files (resume support)
5. Reports progress and any upload failures

### Alternative: If Google API setup is too complex, provide a simple rsync/rclone-based approach with setup instructions.

---

## Verification Checklist

1. `py_compile` passes — PASS/FAIL
2. Authentication works (OAuth flow or service account) — PASS/FAIL
3. Upload 1 test file to the target Drive folder — PASS/FAIL
4. Create subfolder structure for 1 book (5 variants) — PASS/FAIL
5. Resume mode skips existing files — PASS/FAIL
6. Upload progress reported — PASS/FAIL
