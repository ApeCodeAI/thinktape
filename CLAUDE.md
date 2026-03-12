# CLAUDE.md — Instructions for Claude Code

## Your Task
Read TASK.md and execute the full frontend rewrite. Follow every detail precisely.

## Key References
- **Claude Theme CSS**: Copy CSS variables from `/Users/cwd/.openclaw/workspace/apecode-web/src/app/globals.css` (the `:root` and `.dark` sections + `@theme inline` block)
- **Existing backend code**: `braindump/` directory (Python, don't break it)
- **Test data**: Start the backend first (`uv run python -m braindump web`) to test against real data (~900 notes)

## Rules
1. **Use `uv`** for Python (not pip). Use `npm` for frontend.
2. **Git commits**: `git -c user.name=apecode -c user.email=me@apecode.ai commit -m "..."`
3. **Small commits**: Commit after each meaningful step (Phase 1, Phase 2, etc.)
4. **Test everything**: After each phase, verify it works. Run playwright tests at the end.
5. **Don't break the backend**: The bot/transcribe/importer code should not be touched.
6. **Playwright E2E tests**: Write tests in `tests/test_frontend_e2e.py` using pytest-playwright. Take screenshots of every page (desktop + mobile). Screenshots go to `/tmp/braindump-frontend-screenshots/`.

## Development Flow
1. Start backend: `cd /tmp/braindump-t0 && uv run python -m braindump web` (port 8080)
2. Start frontend dev: `cd /tmp/braindump-t0/frontend && npm run dev` (port 5173)
3. Test via http://localhost:5173

## Playwright Test Requirements
```bash
cd /tmp/braindump-t0
uv run python -m pytest tests/test_frontend_e2e.py -x -v
```
Tests should cover:
- Timeline page loads, shows notes, infinite scroll works
- Search and filter work
- Note detail page loads, markdown renders
- Dashboard page loads, charts render
- Calendar page loads, date selection works
- Dark mode toggle works
- Mobile responsive layout works
- Create/Edit/Delete note works

## Data
The SQLite database is at `~/braindump-data/braindump.db` with ~900 real notes. Config at `~/braindump-data/config.toml`. Don't modify the data.
