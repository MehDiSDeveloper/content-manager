# CLAUDE.md

Local Windows desktop app (Python 3.12, PySide6) for a solo Persian podcaster.
**Read `PROJECT_LOG.md` first**: architecture, data model, where things live, decisions. Record every change there.

## Run
- App: `.venv\Scripts\python -m podcast_workspace`
- Tests: `.venv\Scripts\python -m pytest` · lint: `ruff check src tests`, `ruff format src tests`

## Rules
- Layers: `domain/` (pure) → `repositories/` (SQLAlchemy) → `services/` → `ui/` (PySide6). The UI only calls services.
- A schema change needs an Alembic migration in `repositories/migrations/versions/`.
- UI text lives in `ui/strings.py` and `ui/strings_en.py`, with the same names in both.
- Never write the real data folder (`%APPDATA%\PodcastWorkspace`) while testing. Set `PODCAST_WORKSPACE_HOME` to a temp folder.
- Commits: short human messages, no AI trailers.
