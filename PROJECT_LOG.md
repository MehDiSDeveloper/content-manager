# PROJECT_LOG

## Session 1 — foundation (v0.1-foundation)
Done:
- src layout, four layers (domain/repositories/services/ui), pyproject (hatchling), Ruff config, .venv on Python 3.12
- Domain entities: Episode, Voice, IdeaNote, TimestampNote, EpisodeNote, Tag (+ EpisodeStatus enum); rules module
- 15-tag limit enforced in domain (Taggable mixin, TAG_LIMIT) and re-checked in Voice/IdeaNote repositories
- ORM rows + 5 link tables + settings table; Alembic initial migration; app migrates to head on every start
- Repositories with get/find/list_all/add/update/delete for every entity; UnitOfWork (commit on clean exit, rollback on error)
- SettingsService (theme, window geometry) stored as JSON in `settings` table
- App shell: RTL main window, empty sidebar (right), empty content stack, light/dark toggle (button + Ctrl+T), dark native title bar, geometry persisted, clean close
- Tests: tests/test_tag_limit.py (domain + repository boundary)
Key files:
- src/podcast_workspace/domain/entities.py — entities, Taggable mixin
- src/podcast_workspace/domain/rules.py — tag limit, name/color normalization, parent-cycle check, normalize_persian
- src/podcast_workspace/repositories/models.py — ORM rows, UTCDateTime type, link tables
- src/podcast_workspace/repositories/repos.py — all repositories + SettingsRepository
- src/podcast_workspace/repositories/unit_of_work.py — UnitOfWork
- src/podcast_workspace/repositories/db.py — engine, pragmas, migrate()
- src/podcast_workspace/repositories/migrations/ — Alembic env + versions
- src/podcast_workspace/services/workspace.py — composition root (Workspace.open/close)
- src/podcast_workspace/ui/{app,main_window,theme,strings}.py — shell, theming, Persian strings
- src/podcast_workspace/paths.py — %APPDATA%\PodcastWorkspace, PODCAST_WORKSPACE_HOME override
Decisions:
- Separate ORM rows and domain dataclasses (not imperative mapping): UI gets detached plain objects, no lazy-load surprises across threads
- Entities hold relations as id sets (tag_ids, voice_ids, idea_note_ids); repos resolve them to rows and raise NotFoundError for unknown ids
- Settings in SQLite (one file to back up), not JSON
- Datetimes: aware UTC in domain, naive UTC in SQLite via UTCDateTime; naive input raises
- Arabic ي/ك/ى normalized to Persian at entity construction so equality/search work
- Tag.name unique with NOCASE collation
- Fusion style + palette + QSS instead of the "windows11" style: the latter ignores custom palettes, breaking dark mode
- Font: loads any .ttf/.otf in resources/fonts (intended: Vazirmatn, OFL, not bundled yet — no downloads this session); falls back to Segoe UI
- Python 3.12 obtained via uv (machine only had 3.14); uv installed with `python -m pip install --user uv`
Gotchas:
- Run the app: `.venv\Scripts\python -m podcast_workspace`; tests: `.venv\Scripts\python -m pytest`
- New migration: `set PODCAST_WORKSPACE_HOME=<tmpdir>` then `.venv\Scripts\alembic revision --autogenerate -m "..."` — otherwise it autogenerates against your real DB
- SQLite ALTER limits: env.py uses render_as_batch=True; keep it
- Autogenerate emits `podcast_workspace...UTCDateTime()` in migrations; replace with sa.DateTime() (migrations must not import app code)
- Repositories re-check the tag limit because callers can mutate `entity.tag_ids` in place
- Ruff ignores RUF001-003 (Persian letters flagged as ambiguous unicode)
- ffmpeg not bundled yet
- Printing Persian to the console needs PYTHONIOENCODING=utf-8 (cp1252 default crashes)
- QTimer.singleShot before QApplication exists never fires (bit the smoke script)
Next session needs:
- Workspace is the only thing the UI receives; add new services onto it
- MainWindow.content is a QStackedWidget ready for screens; sidebar has a stretch placeholder for nav items
