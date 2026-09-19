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

## Session 2 — CRUD screens, tag system, search (v0.2-crud)
Done:
- Sidebar nav (Ctrl+1..4): Episodes, Voices, Ideas, Tags pages; global search bar (Ctrl+K / Ctrl+F) above the page stack
- Episodes: create (Ctrl+N, focuses title), list, autosave edit (title/status/next_action), tags, delete (Del + confirm)
- Voices: import via dialog (Ctrl+N/Ctrl+O) or drag-drop files/folders, off the UI thread; dedupe by path; tags (15 max); show in Explorer; delete = remove from workspace only, file untouched
- Ideas: draft-until-first-text, debounced autosave (700 ms), flush on page hide/close, tags (15 max), delete
- Tag manager: create (dialog lists similar tags, blocks exact dupes), rename (F2 inline), recolor, nest/unnest, merge, delete (children move up one level), fuzzy filter; usage counts
- TagInput widget: the only place tags get attached; live fuzzy suggestions, Enter picks highlighted existing tag, "create" row is always last and warns when similar exists; Backspace removes last chip; counter + read-only at 15
- Search: FTS5 over episode title/next_action, idea text, episode notes, timestamp notes, tag names, voice paths; tag hits also pull in items carrying that tag; typo correction; results page with kind badge + highlighted snippet, Enter opens item in its page
- Dates in Jalali calendar with Persian digits
- Tests: tests/test_tag_matching.py (fuzzy behaviour only)
Key files:
- src/podcast_workspace/domain/tag_matching.py — scoring, gate, rank_tags, find_exact, near_duplicates
- src/podcast_workspace/domain/text.py — normalize_for_match / normalize_for_index, query_terms, find_spans, make_snippet
- src/podcast_workspace/domain/search.py — SearchKind codes, rowid scheme, SearchHit/SearchResult
- src/podcast_workspace/repositories/migrations/versions/20260919_a7f3c2d91e10_search_index.py — FTS tables + triggers
- src/podcast_workspace/repositories/search_repo.py — raw FTS queries, vocabulary, rebuild
- src/podcast_workspace/services/{tag_service,content_services,search_service,audio_probe}.py
- src/podcast_workspace/ui/widgets/tag_input.py — TagInput; tag_widgets.py (chip, SuggestionList); tag_dialogs.py
- src/podcast_workspace/ui/pages/base.py — ListPage master/detail + TwoLineDelegate; content_pages.py; tags_page.py; search_page.py
- src/podcast_workspace/ui/support.py — Jalali/duration formatting, error text, confirm, AppEvents, run_async
Decisions:
- Tag score = max(token_set_ratio, partial_ratio, word_prefix); non-substring hits must pass a per-word OSA typo budget (1 edit ≤6 letters, 2 beyond), else token_set_ratio × matched-word fraction. Reason: partial_ratio alone scored روان vs ایران 86
- "Exact" tag match compares with spaces/ZWNJ removed: روانشناسی == روان‌شناسی; create refuses exact dupes, near-dupes (≥88) need explicit consent
- FTS rowid = source_id*8 + kind; triggers call pw_norm() (Python, registered per connection) so index text is normalized (Arabic ي/ك, diacritics, digits, ZWNJ removed)
- Two FTS tables: search_word (unicode61, prefix queries, bm25 title weight 4) and search_sub (trigram, substrings ≥3 chars); typo pass only when <5 hits, corrects terms against fts5vocab
- Vocabulary cached, invalidated by WriteCounter (SQLAlchemy after_flush); warmed in background 1.5 s after writes
- Search runs synchronously on the UI thread (90 ms debounce): 1–40 ms on 3k notes / 30k-term vocab
- Voices never copy audio; duration via ffprobe (resources/bin/ffprobe.exe or PATH), stdlib wave fallback, else 0
- TagService caches all tags in memory for instant suggestions; invalidated on its own writes
Gotchas:
- Any connection writing to source tables needs pw_norm(); only engines from repositories/db.create_sqlite_engine have it. Batch-altering a source table drops its triggers — recreate with the helper in migration a7f3c2d91e10
- env.py ignores tables named search_* in autogenerate; `alembic check` must stay clean
- QTest.keyClicks with Persian text crashes the process (0xC0000409); send QKeyEvent(KeyPress, 0, NoModifier, ch) instead
- QLocale.toString has no (QDateTime, str, QCalendar) overload in PySide6; Jalali built via QCalendar.partsFromDate + monthName
- Mixed Persian/Latin/digit lines need RLM marks (see ui/pages/base.py _rtl) or digits jump to the wrong side
- QListWidget item widgets report size before layout; search rows use explicit font-based heights
- run_async callbacks arrive on the GUI thread (relay QObject); verified
- Creating an Episode on "new" writes a placeholder title "اپیزود تازه" immediately (Ideas instead wait for text)
Next session needs:
- Voice page editor has room below tags for a player; VoiceService.get gives file_path/duration_ms
- TimestampNote repository + FTS triggers already exist; search opens TIMESTAMP_NOTE hits on the owning voice (owner_id)
- AppEvents.data_changed must be emitted after new writes so search vocabulary refreshes
- ffmpeg/ffprobe still not bundled; drop binaries into src/podcast_workspace/resources/bin/
