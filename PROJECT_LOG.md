# Podcast Workspace — architecture (v1.0)

Local-first Windows desktop workspace for a solo Persian podcaster: episodes, voices, ideas,
tags, notes, transcripts. Not a recorder, not an editor: playback only. Python 3.12, PySide6.

## Run
- App: `.venv\Scripts\python -m podcast_workspace` · tests: `.venv\Scripts\python -m pytest` · lint: `ruff check src tests`, `ruff format src`
- Data dir: `%APPDATA%\PodcastWorkspace` (override: `PODCAST_WORKSPACE_HOME`). Holds `workspace.db`, `cache/waveforms`, `bale_voices/`, `library/`, `backups/`, `models/`
- Transcription is an optional extra: `pip install .[transcription]` (faster-whisper; installed in .venv)
- Python 3.12 came from uv (`python -m uv ...`); the machine's default python is 3.14

## Layers (never violate)
- `domain/` — dataclass entities + pure rules. No I/O, no Qt, no SQLAlchemy
- `repositories/` — SQLAlchemy rows, mapping to/from entities, Alembic, FTS SQL. `UnitOfWork` = one session + all repos, commit on clean exit
- `services/` — use cases; the only thing the UI calls. `services/workspace.py` is the composition root (`Workspace.open()`)
- `ui/` — PySide6. Receives a `Workspace`; never touches ORM/DB
- Infrastructure beside the layers: `audio/` (ffmpeg, waveform, playback engine), `integrations/` (Bale HTTP client). Used by services (and the player UI for audio) only
- Off the UI thread: voice import, search warm-up, waveform, playback engine (own QThread), transcription (thread pool), export/import (thread pool), model download (daemon thread), Bale polling (daemon thread)

## Data model
- Episode: title, status, next_action, created_at, updated_at, last_opened_at; tags; linked voices + ideas
- Voice: file_path (referenced in place, never copied/moved/deleted), duration_ms, format, imported_at; ≤15 tags
- IdeaNote: free text, created/updated; ≤15 tags. Raw material, no timestamp
- TimestampNote: voice_id, position_ms, text. Separate entity from IdeaNote, never merge
- EpisodeNote: episode_id, title, body (unlimited per episode)
- Transcript: voice_id (unique: one per voice, re-run replaces), segments [(start_ms, end_ms, text)] as JSON, joined text column for FTS, model, language
- Tag: name (unique, NOCASE), color, parent_id (hierarchy)
- Link tables: episode_tags, voice_tags, idea_note_tags, episode_voices, episode_idea_notes. `settings` = key → JSON
- Status pipeline: idea → outline → recorded → script_ready → edited → published
- Migrations: 5c0bcd4c8144 schema · a7f3c2d91e10 FTS · c41e8b7d2f05 status remap · e5a91d3c7b28 transcripts

## Where things live
- Rules: `domain/rules.py` (15-tag limit, names, colors, hierarchy), `entities.py` (Taggable mixin enforces limit)
- Tag matching: `domain/tag_matching.py`; UI entry point `ui/widgets/tag_input.py` (only place tags get attached in the app)
- Search: `domain/search.py` (kinds, rowid scheme), `repositories/search_repo.py`, `services/search_service.py`, `ui/pages/search_page.py`
- Player: `audio/engine.py`, `audio/waveform.py`, `ui/player/{player_widget,waveform_view,timestamp_panel,transcript_panel}.py`; activation window `domain/activation.py`
- Workspace/board/resume: `ui/pages/{episode_workspace,board_page,resume_page}.py`; smart links `domain/smart_links.py`; stale `domain/pipeline.py`
- Idea inbox hotkey: `ui/hotkey.py` (RegisterHotKey, Ctrl+Alt+I), `ui/idea_inbox.py`
- Recorder handoff: `services/recording.py` (os.startfile of the configured program)
- Bale bot: `integrations/bale_api.py` (HTTP), `domain/bot_input.py` (hashtag/tag-list parsing), `services/bale_bot.py` (worker + conversation), `ui/bot_controller.py` (Qt relay)
- Transcription: `services/transcription.py`, `ui/player/transcript_panel.py` (`TranscriptionJobs` + panel)
- Export/import: `services/backup.py`, `repositories/maintenance.py` (snapshot, wipe)
- Settings: `services/settings_service.py`, `ui/settings_dialog.py` (tabs: general, bot, transcription, data)
- All Persian UI text: `ui/strings.py`; bot-facing text: top of `services/bale_bot.py`
- Tests (essential only): tag_matching, tag_limit, activation_window, smart_link_ranking

## Key decisions (why)
- Entities are plain dataclasses, separate from ORM rows: UI gets detached objects, no lazy loads across threads
- Relations held as id sets on entities; repos resolve ids and raise NotFoundError on unknown ids
- 15-tag limit checked in the entity AND again in the repository (callers can mutate `tag_ids` in place)
- Datetimes: aware UTC in domain, naive UTC in SQLite (UTCDateTime); naive input raises
- Arabic ي/ك/ى normalized to Persian at entity construction so equality and search work
- Tag "exact" = equal after removing spaces/ZWNJ/case/Arabic forms; near-duplicate = rank score ≥ 88
- Tag score = max(token_set_ratio, partial_ratio, word_prefix) + per-word OSA typo gate (partial_ratio alone scored روان vs ایران 86)
- FTS5: two tables (unicode61 words with prefixes, trigram substrings), rowid = source_id*8 + kind, maintained by triggers calling Python `pw_norm()`; typo pass against fts5vocab only when < 5 hits. Search is synchronous on the UI thread (1–40 ms)
- All decoding via ffmpeg (imageio-ffmpeg wheel; `resources/bin/ffmpeg.exe` overrides); never Windows codecs. Output at device mix rate, float32
- Seeking restarts ffmpeg with -ss; VBR mp3/wma get a FLAC seek copy (LRU 4 GB cache) because ffmpeg seeks them ~70 ms off
- One Player for the whole app; media timeline/transport always LTR inside the RTL UI
- Smart links: rank by shared-tag count, then recency, then id; exact tag ids only (parent/child do not count)
- Stale = updated_at older than 10 days, never for published; note edits, links and status moves touch the episode, opening does not
- Fusion style + palette + QSS (the windows11 style ignores palettes → broken dark mode)
- Bale bot:
  - Everything is saved on arrival; tag buttons are optional follow-up
  - Text → IdeaNote (hashtags become tags); a hashtag-only message tags the last item; voice/audio/audio-document → file into `bale_voices/`, then a normal voice import. Caption hashtags → tags, rest of caption → TimestampNote at 0:00
  - Free-text tags go through `TagService.resolve_or_create`: exact reuse, near-duplicate reuse (reported to the user as a correction), otherwise create. No tag is created that would then be dropped by the limit
  - Keyboard = 20 most-used tags, frozen per prompt message so buttons do not reorder while tapping; toggles; callback_data self-contained (`t|kind|item|tag`), so old prompts still work
  - First private chat becomes owner (shown/resettable in settings); others get "private" and nothing is saved; groups ignored
  - Offset stored in settings after each update (at-least-once). Updates sent while the app was closed arrive on next start
  - Errors: 401/403 → UNAUTHORIZED, stop until token changes; network/5xx/other → OFFLINE, exponential backoff 3 s → 120 s; per-update exceptions logged, never raised
- Transcription: faster-whisper, CPU int8, language fa, VAD on, condition_on_previous_text off (repetition loops), Persian initial prompt. Audio decoded by our ffmpeg to 16 kHz float32. Model is a local folder: managed download (`models/faster-whisper-<name>`, explicit button, one-time network) or a user folder; loaded with local_files_only. Default model large-v3-turbo. One job at a time; cancel checked per segment
- Transcripts are their own entity (not TimestampNotes): the user's notes stay the user's words
- Export = one zip: `data.json` (all entities, ids kept) + `audio/<id>_<name>` stored uncompressed. Settings not exported (per machine, bot token is a secret)
- Import = full restore, not merge: validate every entity first, extract audio, snapshot DB to `backups/before-import_*.db`, then wipe + insert in one transaction. Voice keeps its original path if a same-size file is still there, else points into `library/`

## Gotchas
- New migration: set `PODCAST_WORKSPACE_HOME=<tmp>` before `alembic revision --autogenerate`, else it diffs your real DB. Replace autogenerated `UTCDateTime()` with `sa.DateTime()`; keep `render_as_batch=True`; `alembic check` must stay clean (env.py ignores `search_*`)
- Every connection that writes needs `pw_norm()` (only engines from `repositories/db.create_sqlite_engine`). Batch-altering an indexed table drops its FTS triggers: recreate them in the same migration. A new FTS kind needs: SearchKind value, trigger migration, `_SOURCE_SQL` entry, `KIND_LABELS`, MainWindow `_open_hit`
- `SqlRepository.add` keeps a preset id (restore relies on it); new entities must have `id=None`
- TagService cache is shared with the bot thread; guarded by an RLock. After raw writes call `tags.invalidate()` / `writes.bump()`
- Bot callbacks fire on the worker thread; BotController re-emits them as Qt signals (queued). Never touch widgets from the worker
- Thread pool threads block app exit; anything uncancellable (model download) uses `run_detached` (daemon thread)
- HF hub draws tqdm bars on stderr, which is None under pythonw: `HF_HUB_DISABLE_PROGRESS_BARS=1` is set in transcription.py before import
- Model download is slow on this connection (~115 KB/s measured: tiny 75 MB ≈ 11 min; large-v3-turbo ≈ 1.6 GB). Settings shows MB so far; HF resumes partial downloads
- Printing Persian to the console needs `PYTHONIOENCODING=utf-8`
- QTest.keyClicks with Persian text crashes the process; send QKeyEvent(KeyPress, 0, NoModifier, ch)
- Letter shortcuts don't fire on the Persian keyboard layout; use layout-free keys (Space, arrows, Insert, -, =) and virtual-key codes for the global hotkey
- Mixed Persian/Latin/digit text: use RLM around separators (`ui/pages/base.py _rtl`) and U+2066/U+2069 isolates for Latin commands; "·" next to Persian digits reads as ۰, use "،"
- Heredoc-generated Python with `"\n"` literals got real newlines on this machine; check syntax after scripted edits
- PySide 6.11: compare sink states with QtAudio.State, not QAudio.State
- QTimer.singleShot before QApplication exists never fires
- Board: columns override sizeHint (default 256 px forces scrolling); cards paint with QApplication.palette(); drops defer the status change with singleShot(0)
- Notes/transcript rows are QScrollArea + VBox rows, not QListWidget item widgets (word-wrap needs heightForWidth)
- EpisodeWorkspacePage ignores its own data_changed emits (_own_change); IdeasPage.external_change never refreshes over a draft or pending autosave
- Inbox is a parentless Qt.Tool window: no taskbar entry, does not keep the app alive; hotkey only while the app runs (no tray)
- ffmpeg first use costs ~1 s (WASAPI init + -buildconf); Player warms up on construction

## Status
- v1.0: CRUD, tags, FTS search, player + timestamp notes, episode workspace, smart links, resume, Kanban + stale, idea inbox hotkey, recorder handoff, Bale bot, offline transcription, export/import
- Not bundled: Vazirmatn font (drop .ttf into `resources/fonts`), ffmpeg exe (comes from imageio-ffmpeg), whisper models (downloaded on demand)
- Possible next steps: tray icon (hotkey + bot while window closed), packaging (PyInstaller), transcript editing, merge-mode import
