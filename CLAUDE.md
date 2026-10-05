# CLAUDE.md

Local Windows desktop app (Python 3.12, PySide6) for a solo Persian podcaster.
**Read `PROJECT_LOG.md` first**: architecture, data model, where things live, decisions. Record every change there.

## Principles (apply to every change)

- **Simple code:** the simplest solution that works; no needless abstraction or complexity.
- **Scalable:** structure code and data so they grow without rewrites.
- **Consistent, high-quality UX:** every screen behaves and looks like the rest of the product.
- **Clean, beautiful UI:** minimal, friendly, self-explanatory, following proven global patterns.
- **Short user paths:** fewest steps and clicks to finish a task; cut any step that isn't needed.
- **Stay on task:** do only what the task needs; no unrelated extras unless truly required.

## Run
- App: `.venv\Scripts\python -m podcast_workspace`
- Tests: `.venv\Scripts\python -m pytest` · lint: `ruff check src tests`, `ruff format src tests`

## Rules
- Layers: `domain/` (pure) → `repositories/` (SQLAlchemy) → `services/` → `ui/` (PySide6). The UI only calls services.
- A schema change needs an Alembic migration in `repositories/migrations/versions/`.
- UI text lives in `ui/strings.py` and `ui/strings_en.py`, with the same names in both.
- Never write the real data folder (`%APPDATA%\PodcastWorkspace`) while testing. Set `PODCAST_WORKSPACE_HOME` to a temp folder.
- Commits: short human messages, no AI trailers.
