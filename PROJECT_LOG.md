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

## Session 3 — audio player, timestamp notes (v0.3-player)
Done:
- Playback-only player on the Voices page: waveform (peaks, played part in accent, note markers, hover time, click/drag seek), −10/+10 s, play/pause, speed 0.5–2× (atempo, pitch kept), clock
- All decoding through ffmpeg (mp3, wav, m4a/aac, flac, ogg, opus, wma verified); nothing uses Windows codecs
- Engine on its own QThread; ffmpeg stdout read on a reader thread; UI thread only gets queued position/state signals
- Exact seeking verified sample-accurate for all formats (see seek cache)
- TimestampNote panel under the player: composer, notes in time order, go-to button per row, inline edit (F2/double-click), delete, context menu
- Activation window [pos−5 s, pos+10 s]: row highlight + accent, waveform marker accent, auto-scroll; several active at once
- Waveform pass stores the exact duration back to the Voice; search hits on timestamp notes open the voice with the note focused
- Keys (Voices page): Space / Ctrl+Space play-pause, ←/→ ∓10 s, - / = speed, Insert or Ctrl+Enter new note at playhead; note rows: Enter go-to, F2, Del, ↑/↓
- Tests: tests/test_activation_window.py
Key files:
- src/podcast_workspace/audio/ffmpeg.py — binary lookup (resources/bin → imageio-ffmpeg → PATH), probe via ffmpeg stderr
- src/podcast_workspace/audio/engine.py — _Decoder, _Engine (QAudioSink push mode), Player facade
- src/podcast_workspace/audio/waveform.py — peak/RMS extraction, npz cache, FLAC seek cache
- src/podcast_workspace/domain/activation.py — LEAD_MS/TRAIL_MS, ActivationTracker (bisect, entered/left diff)
- src/podcast_workspace/services/content_services.py — TimestampNoteService, VoiceService.set_duration
- src/podcast_workspace/ui/player/{player_widget,waveform_view,timestamp_panel,icons}.py
Decisions:
- ffmpeg comes from the imageio-ffmpeg wheel (gyan.dev 7.1 essentials, has rubberband, no soxr); a resources/bin/ffmpeg.exe overrides it for packaging
- Output runs at the device mix rate as float32; if the file differs, ffmpeg resamples once (swr filter_size=64; soxr if the build has it) instead of leaving it to the shared-mode mixer
- Position = segment start + QAudioSink.processedUSecs × speed; every seek/speed change restarts ffmpeg with -ss before -i. Seek generation numbers drop stale position reports
- VBR mp3 and wma seek up to ~70 ms off in ffmpeg. The waveform pass writes a 16-bit dithered FLAC copy for those (data_dir/cache/waveforms, LRU 4 GB) and the engine decodes from it once ready
- Note position is captured at the first keystroke / Insert, not at Enter, so typing time does not shift it
- Media timeline and transport are always LTR (not mirrored) inside the RTL UI
- One Player for the whole app (MainWindow.player); PlayerWidget.is_current() tells whether it holds this voice
Gotchas:
- PySide 6.11: compare sink states with QtAudio.State, not QAudio.State (different enums, == is always False)
- Letter shortcuts don't fire with the Persian keyboard layout; player keys are layout-free (Space, arrows, -, =, Insert)
- Notes panel uses QScrollArea + VBox rows (not QListWidget item widgets) because word-wrapped rows need heightForWidth
- Waveform/npz and FLAC caches key on path+size+mtime; editing the file invalidates them automatically
- First engine use costs ~1 s (WASAPI init + ffmpeg -buildconf); Player warms up on construction
Next session needs:
- MainWindow.player is the shared engine; VoicesPage.select(voice_id) opens a voice in the player, open_note(voice_id, note_id) also focuses a note
- Player API: load/play/pause/toggle/seek/skip/set_speed, signals position_changed/state_changed

## Session 4 — episode workspace, pipeline, inbox (v0.4-workspace)
Done:
- Episode workspace page (off-nav): title, status, next_action, tags, EpisodeNotes as tabs + autosaving editor (Ctrl+N new, Ctrl+Tab cycle), linked voices / ideas lists (click/Enter opens, Del unlinks, "افزودن…" picker with filter), Record button (Ctrl+R)
- Clicking a linked voice opens it on the Voices page in the player; Alt+← (or the back button) returns
- Smart-link side panel: voices + ideas sharing ≥1 tag with the episode, ranked; Enter/double-click or button links/unlinks, "باز کردن" opens
- Resume screen at startup (last opened episode, its most recently edited note, next_action, one "ادامه" button; Esc → episodes). Continue opens the workspace with the cursor in that note
- Status pipeline idea → outline → recorded → script_ready → edited → published; Kanban page (nav "تابلو"): drag & drop between columns, ←/→ between columns, Ctrl+←/→ moves the card, Enter opens
- Stale marker (>10 days since updated_at, never for published) on board cards, Episodes list rows, workspace header, resume card
- Idea Inbox: global Ctrl+Alt+I (RegisterHotKey) opens a small always-on-top window; Enter saves an IdeaNote and closes, Shift+Enter newline, Esc closes
- Settings dialog (sidebar, Ctrl+,): recorder program path (+browse), hotkey status. Record launches it via os.startfile; the app never records
- Nav is now Episodes, Board, Voices, Ideas, Tags = Ctrl+1..5; search hits on episode notes open the workspace at that note
- Tests: tests/test_smart_link_ranking.py
Key files:
- src/podcast_workspace/domain/smart_links.py — LinkKind, LinkCandidate, rank_smart_links
- src/podcast_workspace/domain/pipeline.py — PIPELINE order, STALE_AFTER, is_stale, days_untouched
- src/podcast_workspace/repositories/migrations/versions/20260919_c41e8b7d2f05_status_pipeline.py — status value remap
- src/podcast_workspace/services/content_services.py — EpisodeService.set_status/link/smart_links/resume, ResumeInfo, EpisodeNoteService
- src/podcast_workspace/services/recording.py — launch_recorder
- src/podcast_workspace/ui/pages/{episode_workspace,board_page,resume_page}.py
- src/podcast_workspace/ui/{hotkey,idea_inbox,settings_dialog}.py
- src/podcast_workspace/ui/main_window.py — show_page/go_back history, open_episode/open_voice/open_idea
Decisions:
- Ranking: shared-tag count, then recency (voice imported_at / idea updated_at), then id. Exact tag ids only; parent/child tags do not count as shared
- Smart panel lists linked items too (marked "پیوندشده ✓") so it doubles as a link/unlink surface
- Stale = updated_at older than 10 days; note edits, link changes and status moves touch the episode, just opening it does not
- Migration maps outlining→outline, recording→recorded, editing→edited, archived→published (no archived state in the new pipeline)
- "Last edited note" is derived (max EpisodeNote.updated_at of the last opened episode); nothing extra stored
- Hotkey registered on the main window HWND, caught with a native event filter; virtual-key codes so it works on the Persian layout. Only while the app is running (no tray yet)
- Existing Episodes list page kept; it gains "ورود به فضای کار" (Ctrl+Enter / double-click)
Gotchas:
- Board columns: QListWidget's default sizeHint (256 px) forced horizontal scrolling; _Column overrides sizeHint/minimumSizeHint
- Board cards paint with QApplication.palette(): the column's stylesheet makes its own palette transparent (cards rendered black)
- Board drop: the status change is deferred with QTimer.singleShot(0) because the refresh clears the source list while its drag loop is still running
- "·" next to Persian digits reads as ۰ (Persian zero is a dot); new strings use "،" or ":" instead
- EpisodeWorkspacePage ignores its own data_changed emits (_own_change) to avoid refreshing links on every autosave
- Inbox is a parentless Qt.Tool window: it does not keep the app alive and has no taskbar entry
Next session needs:
- Bale bot can create ideas through Workspace.ideas.create and emit AppEvents.data_changed on the GUI thread (use run_async / queued signals)
- Transcription can hang off VoicesPage (voice id + file path) and store text as TimestampNotes (TimestampNoteService.add)
- Export: EpisodeService.get + EpisodeNoteService.list_for_episode + linked voice/idea ids give everything an episode holds
