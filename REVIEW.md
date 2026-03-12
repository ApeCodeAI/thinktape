# Code Review

Reviewed `DESIGN.md` and all Python files under `braindump/`.

## Findings

1. **High** — `braindump/importer/flomo.py:217-233`
   - `img_src` from the exported HTML is joined directly with `export_dir` and copied without normalization or a boundary check.
   - A tampered export can use `../` segments or absolute paths to copy arbitrary local files into the braindump data directory.

2. **High** — `braindump/database.py:157-162` (also conflicts with `DESIGN.md:15`, `DESIGN.md:85-87`)
   - `rebuild_index()` unlinks the live SQLite database before proving the rebuild can succeed.
   - Any later failure (bad filename, decode error, interrupted run) loses metadata with no backup or rollback path.

3. **High** — `braindump/__main__.py:13`, `braindump/__main__.py:59-61`, `braindump/bot/handlers.py:210-231`, `braindump/bot/handlers.py:254-275`, `braindump/bot/handlers.py:348-362`
   - The CLI advertises `serve` as “Bot + Web + Transcribe Worker”, and bot replies say transcription was queued.
   - In practice, `serve` only starts the web app, `run_bot()` only starts Pyrogram, and no code instantiates/enqueues a `TranscribeWorker`; audio/video notes can stay `pending` forever.

4. **High** — `braindump/config.py:31`, `braindump/web/app.py:35`, `braindump/web/routes.py:98-117`
   - The web server binds to `0.0.0.0`, serves raw `/media`, and exposes delete/restore endpoints with no authentication or authorization checks.
   - If the process is reachable from the network, anyone can read private media and mutate note state.

5. **Medium** — `braindump/web/routes.py:62-65`, `braindump/web/routes.py:103-117`
   - Soft-deleted notes are still directly accessible via `/note/{note_id}` because the detail query does not filter `is_deleted = 0`.
   - Delete/restore also return `{"ok": true}` even when `note_id` does not exist, which hides client errors.

6. **Medium** — `braindump/web/routes.py:145-153`
   - Raw user search input is passed into SQLite FTS `MATCH` with no syntax validation or error handling.
   - Invalid queries such as unmatched quotes will raise `sqlite3.OperationalError` and surface as a 500 instead of a controlled 4xx/empty result.

7. **Medium** — `braindump/transcribe/engine.py:60-82`, `braindump/transcribe/engine.py:150-152`
   - Missing transcription dependencies silently fall back to `MockEngine`, which can write fake transcripts into real notes.
   - Separately, missing media files only log and return, leaving rows stuck in `pending` instead of moving to `failed`.

8. **Medium** — `braindump/config.py:18`, `braindump/bot/handlers.py:31-39`, `braindump/bot/handlers.py:127`, `braindump/importer/flomo.py:162`, `braindump/importer/flomo.py:184-191`, `braindump/importer/flomo.py:223-230`, `DESIGN.md:101`
   - `display_date` respects `day_boundary_hour`, but file placement always uses the real calendar date.
   - Content created before the boundary hour is grouped under the previous day in the UI, yet stored under the current day on disk, which breaks the archive rule described in the design.

9. **Medium** — `braindump/config.py:17`, `braindump/database.py:12`, `braindump/bot/handlers.py:16`, `braindump/importer/flomo.py:21`, `braindump/transcribe/engine.py:12`, `braindump/web/routes.py:18`
   - The configuration exposes `general.timezone`, but the code hardcodes UTC+8 in multiple modules.
   - Non-Asia/Shanghai deployments will compute archive dates, timestamps, and transcript metadata incorrectly.
