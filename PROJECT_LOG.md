# Podcast Workspace — architecture (v1.6)

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
- Episode: title, status, next_action, season_id (nullable), created_at, updated_at, last_opened_at; tags; linked voices + ideas
- Season: title, created_at. Ordered by id (season one first). Deleting one keeps its episodes, seasonless
- Voice: file_path (referenced in place, never copied/moved/deleted), duration_ms, format, imported_at, archived_at, deleted_at; ≤15 tags
- IdeaNote: free text, created/updated, archived_at, deleted_at; ≤15 tags. Raw material, no timestamp
- TimestampNote: voice_id, position_ms, text. Separate entity from IdeaNote, never merge
- EpisodeNote: episode_id, title, body (unlimited per episode)
- Transcript: voice_id (unique: one per voice, re-run replaces), segments [(start_ms, end_ms, text)] as JSON, joined text column for FTS, model, language
- Tag: name (unique, NOCASE), color, parent_id (hierarchy)
- Link tables: episode_tags, voice_tags, idea_note_tags, episode_voices, episode_idea_notes. `settings` = key → JSON
- Status pipeline: idea → outline → recorded → script_ready → edited → published
- Migrations: 5c0bcd4c8144 schema · a7f3c2d91e10 FTS · c41e8b7d2f05 status remap · e5a91d3c7b28 transcripts · b8d4e6f1a320 seasons · d2c7f9a4b615 archive/trash

## Where things live
- Rules: `domain/rules.py` (15-tag limit, names, colors, hierarchy), `entities.py` (Taggable mixin enforces limit)
- Tag matching: `domain/tag_matching.py`; UI entry point `ui/widgets/tag_input.py` (only place tags get attached in the app)
- Search (global): `domain/search.py` (kinds, rowid scheme), `repositories/search_repo.py`, `services/search_service.py`, `ui/pages/search_page.py`
- Filter (one page's own list): `domain/list_filter.py`, the filter box in `ui/pages/base.py` (`ListPage`), `Row.tags` filled by each page in `content_pages.py`
- Navigation history: `ui/navigation.py` (the trail + per-page snapshots), `MainWindow.show_page` / `go_back` / `_sync_back`, and each page's `nav_state` / `restore_nav_state`
- Player: `audio/engine.py`, `audio/waveform.py`, `ui/player/{player_widget,waveform_view,timestamp_panel,transcript_panel}.py`; activation window `domain/activation.py`
- Workspace/board/resume: `ui/pages/{episode_workspace,board_page,resume_page}.py`; smart links `domain/smart_links.py`; stale `domain/pipeline.py`
- Idea inbox hotkey: `ui/hotkey.py` (RegisterHotKey, Ctrl+Alt+I), `ui/idea_inbox.py`
- Recorder handoff: `services/recording.py` (os.startfile of the configured program); Ctrl+R is a MainWindow shortcut, so it works on every page
- Audio folder (review before import): `services/source_folder.py` (scan, add), `ui/pages/source_page.py` (QFileSystemWatcher on the folder + subfolders, 400 ms debounce). Setting `voices.source_folder`
- Seasons: `SeasonService` in `services/content_services.py`, `EpisodeService.set_season`; the season box over the Episodes list (`ui/pages/content_pages.py`, choice kept in `ui.episode_season_filter`) and beside the status in the workspace; name prompts in `ui/seasons.py`
- Archive / trash: rules in `domain/lifecycle.py` (ArchiveScope, 30-day period, tested in `test_archive_trash.py`); `set_archived` / `delete` (= move to trash) in `IdeaService` / `VoiceService`; `services/trash.py` (list, restore, purge, purge_expired); `ShelfListPage` in `ui/pages/content_pages.py`; switch widget `ui/widgets/scope_switch.py`; `ui/pages/trash_page.py`; hourly purge timer in MainWindow
- Bale bot: `integrations/bale_api.py` (HTTP), `domain/bot_input.py` (hashtag/tag-list parsing), `services/bale_bot.py` (worker + conversation), `ui/bot_controller.py` (Qt relay)
- Transcription: `services/transcription.py`, `ui/player/transcript_panel.py` (`TranscriptionJobs` + panel)
- Export/import: `services/backup.py`, `repositories/maintenance.py` (snapshot, wipe)
- Undo/redo: `services/history.py` (the stacks), the `record(...)` calls inside the content and
  tag services (each beside the operation it inverts), `ui/toast.py`, `describe_change` in
  `ui/support.py`, `UNDO_*` in `ui/strings.py`, and MainWindow (`undo`/`redo`, `_reveal`,
  `TextEditorKeys`)
- Settings: `services/settings_service.py`, `ui/settings_dialog.py` (tabs: general, bot, transcription, data)
- All Persian UI text: `ui/strings.py`; bot-facing text: top of `services/bale_bot.py`
- Shell chrome: `ui/main_window.py` (sidebar = title + search + nav + undo/redo + settings/theme), nav/chrome icons painted in `ui/icons.py`
- Tests (essential only): tag_matching, tag_limit, activation_window, smart_link_ranking, undo_history, list_filter, navigation_history

## Key decisions (why)
- Audio folder (v1.5): the folder is read, never mirrored into the database. A file becomes a
  Voice only when added, so auditioning a bad take leaves nothing behind; the list is "files
  here minus voices already imported" (paths compared resolved + normcase), which is also why
  a voice removed from the workspace reappears there. No tagging before adding, on purpose:
  that page is for deciding, the Voices page for working. Rows use per-session int ids keyed
  by path; the player gets negative ids so they never collide with a voice's
- Seasons (v1.5): a flat, optional grouping — one season per episode, no numbering stored.
  The Episodes list filters by season rather than growing section headers, so selection,
  filter box and Back keep working unchanged; an episode opened from elsewhere switches the
  box to its season so it is never hidden. Filing an episode counts as touching it (stale)
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
- Layout rules (v1.1): search lives in the sidebar, not over the page, so each page opens with its own
  title; one accent button per screen, on the action taken most (Episodes: «enter workspace», not
  «new episode»); lists flex between LIST_MIN/MAX_WIDTH instead of a fixed 340; text results cap at a
  readable measure (search: 880 px)
- Episodes page shows what an episode holds (notes / linked voices / linked ideas, each clickable);
  Enter on the list opens the workspace — the page is for choosing, the workspace for writing
- Episode workspace: one `MaterialsPanel` with three tabs (voices / ideas / suggestions) replaces the
  two boxes under the editor plus a separate suggestion rail, so the note editor keeps the full column
- Tags page: tree capped at TREE_WIDTH with usage beside the name, actions in a menu (plus the row's
  context menu) instead of a six-button bar, and a panel listing what carries the selected tag
- Nav counts come from `MainWindow._refresh_counts` on a 250 ms debounce after data/tags changes
- Navigation (v1.3):
  - Back carries state, not just a page: leaving snapshots the page (`nav_state`), returning hands
    the snapshot back. Every page reloads itself in `showEvent`, so a Back that only restored the
    page would land on a reset filter box, a reset scroll and sometimes a different row
  - A page opts in by implementing the two methods; one that does not is still reachable by Back,
    which is why `ui/navigation.py` treats the snapshot as opaque and never inspects it
  - The Back control lives in the sidebar, always present and disabled when there is nowhere to go
    (like undo), and names its destination — «بازگشت به برچسب‌ها». Discoverability was the whole
    problem: Alt+← existed and only the episode workspace had a visible way back
  - Search results and the startup resume screen are never recorded. Search has its own way home
    (`_before_search`), and opening a hit hands that snapshot to the history, so Back after a hit
    returns to where the search started rather than nowhere
- Filtering a list (v1.3):
  - Two different jobs, deliberately not merged: Ctrl+K searches everything written in the
    workspace and answers on its own page; Ctrl+F narrows the list already in front of you, by
    title and tag only, and never brings in a row from elsewhere
  - `domain/list_filter.py` is pure: terms are ANDed (every keystroke narrows), `#name` restricts a
    term to tag names, matching is substring on `normalize_for_index` so ZWNJ, Arabic ی/ک, harakat,
    Persian digits and case never decide what is shown
  - A row the caller asked for is pinned past the filter (`refresh(select_id=…)`), and creating,
    importing or jumping empties the box first — an item the user was sent to must be visible
  - The count pill («۳ از ۲۴») only appears while filtering: it is the promise that nothing was
    deleted, only hidden
- Undo/redo (v1.2):
  - Inverse operations, not snapshots: a change records the pair of calls that move it back and
    forth. A whole-database snapshot per step would be simpler and far too heavy for a workspace
    that holds audio-length transcripts
  - Recorded in the services, beside the operation they invert, so the UI never learns how to
    reverse anything and every caller (page, hotkey, dialog) gets undo for free
  - Undoable: episode create/edit/status/tags/link/delete (with its notes), episode notes,
    ideas, voice tags and voice delete (with its timestamp notes, transcript and links),
    timestamp notes, and every tag action including delete and merge — the two that quietly
    change many items at once
  - Not undoable, on purpose: importing voices (additive, files untouched), transcription
    (a re-run replaces it anyway), export/import (has its own backup), settings, and anything
    the Bale bot does — the worker wraps each update in `history.suspended()` (per-thread), so
    an item arriving from the phone never lands on, or flushes, the stack in front of the user
  - Memory: 60 entries, capped again at ~1 M characters of remembered text; the oldest go
    first. Text edits coalesce per field while typing flows (8 s gaps, 60 s span), so a writing
    session is a handful of steps, not one per autosave
  - An undo restores `updated_at` too: an undone change must not leave the episode looking stale
  - Snapshots are pruned on the way back (tags/voices/ideas deleted meanwhile are dropped from
    the sets) so one missing reference cannot block a restore; an inverse that still fails drops
    its entry and the ones under it stay usable
  - Restores reuse the original ids — `SqlRepository.add` keeps a preset id, and the FTS
    triggers reindex the row on insert
  - UI: Ctrl+Z / Ctrl+Y (and Ctrl+Shift+Z), a sidebar row beside settings whose tooltip names
    the exact change, and a toast for changes that take something away (delete, tag removed,
    unlink, merge) with «بازگردانی» on it. After a step the page holding the touched item is
    brought up — or just refreshed when it is already in front — because a change you cannot
    see is a change you cannot trust
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

- Archive and trash (v1.6):
  - Timestamps, not flags: `archived_at` / `deleted_at` on voices and ideas only (episodes keep
    their hard delete with undo). The purge counts 30 days from `deleted_at`
  - Archived = put away: out of the default («فعال») list, search, smart links and the link
    picker; still shown where it is already linked (with a badge) and on the tags page. The
    three-way switch starts on «فعال» every run; search's own switch resets when a search ends.
    Anything reached from elsewhere widens the page switch to «همه» rather than stay hidden
  - Trashed = gone from everywhere except the trash page: repos' `list_all()` leave it out
    unless `include_trashed` (export, the audio folder's known-files check, restoring episode
    links), tag usage counts skip it, `SearchRepository.hidden` drops it along with its
    timestamp notes and transcript. Everything it carries stays in the database until purge
  - Delete on Voices/Ideas asks nothing: it is a move to the trash with an undo toast. The
    trash page asks before "delete forever" / "empty". Restore and purge are not on the undo
    stack (restore is undone by deleting again; purge is final)
  - Purge = real row delete; the CASCADEs take tag links, timestamp notes, transcript and
    episode links. Tags themselves stay (shared). Runs at startup and hourly
  - Importing the file of a trashed voice brings that voice back out of the trash
  - Exports carry both timestamps (older exports import with neither)

## Gotchas
- New migration: set `PODCAST_WORKSPACE_HOME=<tmp>` before `alembic revision --autogenerate`, else it diffs your real DB. Replace autogenerated `UTCDateTime()` with `sa.DateTime()`; keep `render_as_batch=True`; `alembic check` must stay clean (env.py ignores `search_*`)
- NEVER batch-alter `episodes`, `voices`, `idea_notes` or `tags`: the rebuild drops the old table under foreign_keys=ON and every CASCADE child goes with it (tag links, notes, transcripts). Add columns with a plain `ALTER TABLE … ADD COLUMN` and no foreign key (see b8d4e6f1a320); keep the reference valid in the repository
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
- Styling a QComboBox with QSS makes Qt draw the drop-down as a separate square hanging outside the
  rounded frame in RTL; leave the combo to Fusion (only min-width/padding are set)
- QPainter.drawText(rect, AlignLeft) follows the string's own direction, so Persian digits land at the
  trailing edge. NavButton lays out icon/label/count as child widgets (WA_TransparentForMouseEvents)
  and overrides sizeHint from the layout — a QPushButton with no text of its own collapses otherwise
- QSS cannot reach a button's child labels: NavButton mirrors the :checked look by hand
- Offscreen screenshots have no system fonts (Persian renders as tofu); render with the real platform
  and `WA_DontShowOnScreen` instead
- Board: columns override sizeHint (default 256 px forces scrolling); cards paint with QApplication.palette(); drops defer the status change with singleShot(0). Card titles wrap to 2 lines: `_CardDelegate.sizeHint` must reserve the 3 px the card is inset from the item rect at top and bottom, or the next action spills past the border
- Notes/transcript rows are QScrollArea + VBox rows, not QListWidget item widgets (word-wrap needs heightForWidth)
- EpisodeWorkspacePage ignores its own data_changed emits (_own_change); IdeasPage.external_change never refreshes over a draft or pending autosave
- Inbox is a parentless Qt.Tool window: no taskbar entry, does not keep the app alive; hotkey only while the app runs (no tray)
- ffmpeg first use costs ~1 s (WASAPI init + -buildconf); Player warms up on construction
- A focused QLineEdit / QPlainTextEdit claims Ctrl+Z through ShortcutOverride *even with an empty
  undo stack*, so a window-level shortcut never fires while text has focus. `TextEditorKeys`
  swallows that claim only when the editor has nothing of its own to take back; it rides on the
  focused widget (via `focusChanged`), never on the whole application — an app-wide Python event
  filter would run for every mouse move
- Installing an event filter twice moves it instead of duplicating it, and removing it would take
  the page's own filter with it: `self.search` keeps MainWindow's filter, the key filter is its
  own QObject
- Qt stores item data as a QVariant and hands a Python enum back as the plain `str`/`int` behind it,
  so `item.data(role) is LinkKind.VOICE` is always False — every voice in the tags page's usage
  panel opened an idea instead. Put the value back through its enum on read, never compare raw
- A NavButton whose label is set at runtime must not let that label decide its width: it reports
  `sizeHint().width() == 0` and elides the text to whatever the rail gives it (the full text goes
  in the tooltip), or a long episode title would widen the sidebar
- Palette Highlight is the pastel accent (a fill) and HighlightedText is its dark ink. Row
  selections are the lighter accent_soft, so delegates draw selected text in Text, never
  HighlightedText (unreadable in dark). Lines/focus/markers use the Link role (accent_strong)

## Status
- v1.6: archive (active/all/archived switch on Voices, Ideas and search) and a 30-day trash
  page (select, restore, delete forever, restore all, empty, search inside the trash)
- v1.5: Ctrl+R opens the recorder from anywhere. Audio folder page: the recording folder read
  live, files played and reviewed without being stored, added one at a time («افزودن به فضای
  کاری», Ctrl+Enter; the next file takes its place) — tags and notes only once added. Seasons:
  one optional season per episode, a season box over the Episodes list (all / a season / no
  season, with counts; «اپیزود تازه» lands in the season shown) and a season picker in the
  workspace; create/rename/delete and moves are undoable. Exports carry seasons (older exports
  import with none)
- v1.4: Visual pass — pastel lavender theme (light + dark), bundled Vazirmatn, a hue per
  sidebar section (glyph tiles) and per pipeline stage (tinted board columns + dot), soft
  selections instead of solid accent fills, pill tabs, lifted board cards. All colours live in
  `ui/theme.py`: pastels are fills only, each has an ink for text/strokes; painted widgets read
  `theme.colors()` / the palette's Link role for strong accents
- v1.3: Back that restores page state (sidebar control naming its destination), per-page filter by
  title and tag on Episodes/Voices/Ideas, tags page opening the right kind of item
- v1.2: undo/redo for the actions that deserve it (see the decisions above)
- v1.1: UI/UX pass — sidebar search + nav counts + icons, episode contents on the Episodes page,
  tabbed materials panel in the workspace, wrapping board cards, tag usage panel, styled scrollbars
- v1.0: CRUD, tags, FTS search, player + timestamp notes, episode workspace, smart links, resume, Kanban + stale, idea inbox hotkey, recorder handoff, Bale bot, offline transcription, export/import
- Bundled: Vazirmatn 4 weights in `resources/fonts` (OFL, licence alongside). Not bundled: ffmpeg exe (comes from imageio-ffmpeg), whisper models (downloaded on demand)
- Possible next steps: tray icon (hotkey + bot while window closed), packaging (PyInstaller), transcript editing, merge-mode import

## v1.4 — layout, English, backup reminder
- Layout: an episode opens as the detail pane of the Episodes page (`EpisodesPage` embeds `EpisodeWorkspacePage`); board/tags/search/resume all route there via `MainWindow.open_episode`. List pane hides with Ctrl+L, sidebar folds to an icon rail with Ctrl+B; both remembered in settings (`ui.episode_list_hidden`, `ui.sidebar_compact`). List pages carry title + "new" button in the list column
- Language: `ui/strings.py` (Persian originals) + `ui/strings_en.py`; `strings.apply_language` swaps them at startup, `ui/language.py` sets direction/locale, asks on first run, restarts on change. `tests/test_strings.py` keeps names and placeholders in step. Bale bot text stays Persian
- Backup reminder: rule in `domain/backup_reminder.py` (tested), state in settings (`backup.*`, `app.first_run_at`), `BackupService.reminder/snooze_reminder`; export records the time. Shown by `MainWindow._check_backup` on startup; interval in Settings → Data (default weekly)
