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

## Demo data (promo captures)
A full demo podcast (3 seasons, 17 episodes, ideas, synthesised voices, transcripts, an audio folder) lives in its
own folder, `G:\Repos\promo\podcast-workspace\demo-home\` (gitignored there); the real `%APPDATA%\PodcastWorkspace`
is never touched. `scripts/seed_demo.py` builds it.
- Create: `.venv\Scripts\python scripts\seed_demo.py` (`--fresh` rebuilds it from scratch)
- Open the app on it: `$env:PODCAST_WORKSPACE_HOME="G:\Repos\promo\podcast-workspace\demo-home"; .venv\Scripts\python -m podcast_workspace`
- Remove: `.venv\Scripts\python scripts\seed_demo.py --remove` (deletes that folder, nothing else)
- The promo capture (`G:\Repos\promo\podcast-workspace\capture.py`, see its `NOTES.md`) reseeds it before each run.
`scripts/seed_mock_data.py` is the older, smaller mock set that adds to (and `--clear`s from) the current workspace.

## Rules
- Layers: `domain/` (pure) → `repositories/` (SQLAlchemy) → `services/` → `ui/` (PySide6). The UI only calls services.
- A schema change needs an Alembic migration in `repositories/migrations/versions/`, and `HEAD_REVISION` in `repositories/db.py` set to it.
- Data access: count and find with queries, never `len(list_all())` or filtering `list_all()` in Python; no per-row queries. See «Performance (v1.25)» in `PROJECT_LOG.md`.
- Multi-line text boxes are `ui/widgets/text_editor.TextEditor` (per-paragraph RTL/LTR), never QPlainTextEdit.
- UI text lives in `ui/strings.py` and `ui/strings_en.py`, with the same names in both.
- Never write the real data folder (`%APPDATA%\PodcastWorkspace`) while testing. Set `PODCAST_WORKSPACE_HOME` to a temp folder.
- Commits: short human messages, no AI trailers.
