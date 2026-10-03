# Podcast Workspace — architecture (v1.21)

Local-first Windows desktop workspace for a solo Persian podcaster: episodes, voices, ideas,
tags, notes, transcripts. Not a recorder, not an editor: playback only. Python 3.12, PySide6.
Source code: GitHub `MehDiSDeveloper/content-manager` (public).

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
- Episode: title, status, next_action, season_id (nullable), created_at, updated_at, last_opened_at; tags; linked voices + ideas; publish checklist (`publish_done` = ticked `PublishStep`s comma-separated, `published_where` = one place/link per line); script brief (`script_brief` = `ScriptBrief.to_dict()` JSON, "" = defaults); summary (what the episode said, free text); number (nullable: its place in its season)
- Season: title, readme (the producer's: facts, strategy, rules, goals; goes into the script prompt), about (for listeners; not in the prompt), number (nullable), created_at. Ordered by `in_order` (`entities.py`): by number, then the unnumbered by creation. Deleting one keeps its episodes, seasonless
- Voice: file_path (the workspace's own copy in `voices/`, or in place when already inside the data folder, e.g. Bale voices), source_path (the original it was copied from, never touched; "" if not a copy), duration_ms, format, imported_at, archived_at, deleted_at; ≤15 tags
- IdeaNote: free text, created/updated, archived_at, deleted_at; ≤15 tags. Raw material, no timestamp
- TimestampNote: voice_id, position_ms, text. Separate entity from IdeaNote, never merge
- EpisodeNote: episode_id, title, body (unlimited per episode)
- Transcript: voice_id (unique: one per voice, re-run replaces), segments [(start_ms, end_ms, text)] as JSON, joined text column for FTS, model, language
- Tag: name (unique, NOCASE), color. Flat: no parents, no nesting
- Link tables: episode_tags, voice_tags, idea_note_tags, episode_voices, episode_idea_notes. `settings` = key → JSON
- Status pipeline: idea → outline → recorded → script_ready → edited → published
- Migrations: 5c0bcd4c8144 schema · a7f3c2d91e10 FTS · c41e8b7d2f05 status remap · e5a91d3c7b28 transcripts · b8d4e6f1a320 seasons · d2c7f9a4b615 archive/trash · f3a8c1e5d907 idea title · a9e2d5c8f314 flat tags (drops tags.parent_id) · c6e1a8f4b2d7 publish checklist (two ALTER TABLE ADD COLUMNs on episodes) · e8b3f1c6a492 voices.source_path (ALTER TABLE ADD COLUMN) · b3d7a1f9c524 seasons.summary + outline (ALTER TABLE ADD COLUMN) · d4f2b8e6a1c3 episodes.script_brief (ALTER TABLE ADD COLUMN) · e1b7c4a9f2d6 seasons.summary → readme (old outline appended), outline dropped, seasons.about + episodes.summary added · f5c2a8d1e7b4 seasons.number + episodes.number (ALTER TABLE ADD COLUMN)

## Where things live
- Rules: `domain/rules.py` (15-tag limit, names, colors), `entities.py` (Taggable mixin enforces limit)
- Tag matching: `domain/tag_matching.py`; UI entry point `ui/widgets/tag_input.py` (only place tags get attached in the app)
- Search (global): `domain/search.py` (kinds, rowid scheme), `repositories/search_repo.py`, `services/search_service.py`, `ui/pages/search_page.py`
- Filter (one page's own list): `domain/list_filter.py`, the filter box in `ui/pages/base.py` (`ListPage`), `Row.tags` filled by each page in `content_pages.py`
- Navigation history: `ui/navigation.py` (the trail + per-page snapshots), `MainWindow.show_page` / `go_back` / `_sync_back`, and each page's `nav_state` / `restore_nav_state`
- Player: `audio/engine.py`, `audio/waveform.py`, `ui/player/{player_widget,waveform_view,timestamp_panel,transcript_panel}.py`; activation window `domain/activation.py`
- Pause trimming: `audio/silence.py` (detection, cut plan, `Splicer`; tested in `test_silence.py`), state on `Player` (`set_skip_silence` / `set_keep_pause` / `set_pauses`), `ui/player/silence_control.py` (split switch + popup), cut shading in `WaveformView.set_cuts`. Setting `player.trim_silence` (keep only)
- Volume: `Player.set_volume` / `toggle_mute` → `QAudioSink.setVolume` on a log scale; `ui/player/volume_control.py` (speaker button + popup). Setting `player.volume`. Both popups share `ui/player/popup.py`
- Speed: `Player.set_speed` snaps to 5% steps in 0.5–2× (`settle=True` from the slider/wheel: shown at once, sent to ffmpeg once it rests, so a drag doesn't restart the decoder per step); `step_speed` (- / =) walks the `SPEEDS` presets. `ui/player/speed_control.py` (button + popup: slider, −/+, preset chips). Not remembered between runs
- Workspace/board/resume: `ui/pages/{episode_workspace,board_page,resume_page}.py`; smart links `domain/smart_links.py`; stale `domain/pipeline.py`
- Idea → episode: `EpisodeService.set_linked` (several items, one undo step), `create_from` (new episode named after the first item, with all their tags), `episodes_with`, `link_counts` (`EpisodeRepository.link_counts`, one GROUP BY per link table); UI `ui/widgets/episode_links.py` (`EpisodeMenu`, `EpisodeLinksRow`), wired in `IdeasPage` (editor rows, selection pane, row context menu, «in N ep.» in row subtitles) and `MainWindow.open_new_episode`. The list picker is `ui/widgets/picker.py`
- Material preview: `ui/pages/material_preview.py` (`MaterialPreview`), shown by `MaterialsPanel.set_previewing` / `EpisodeWorkspacePage._preview` / `close_preview`; its player is `PlayerWidget(compact=True)` (transport on its own line)
- Voice store: `services/voice_store.py` (`voices_dir()`, `NameChoice`, same-file = size + mtime, `free_name` → «name (2)»). `VoiceService.import_files(paths, choices)` copies files from outside the data folder in; `name_conflicts` finds names a voice already has, asked about by `ui/widgets/name_conflict.py` (Ideas import, audio folder «add»); unasked clashes come in numbered, never overwritten. REPLACE keeps the voice (tags, notes, episodes) and drops its transcript; not undoable. `secure_external` copies older voices in, run at startup by `MainWindow`. Purge deletes the stored copy only. Tested in `test_voice_store.py`
- Publish checklist: `domain/publish.py` (`PublishStep`, `PublishChecklist`, tested in `test_publish_checklist.py`), `EpisodeService.check_publish_step` / `set_published_where`, chip + popup `ui/widgets/publish_checklist.py` in the workspace's stage row
- Untagged filter: `FacetFilter.untagged` (`domain/list_filter.py`), the «بی‌برچسب N» toggle chip in `FacetSearchBar`; `IdeasPage.rows` feeds it the count
- Export as heard: `audio/render.py` (decode → `Splicer` + gain → encode; `trimmed_ms` maps times), `services/voice_render.py` (`VoiceRenderService.save` new/replace, `numbered_name`, `trimmed_for_sending` for the bot), `Player.active_cuts` / `level_gain`, dialog + job `ui/widgets/save_as_heard.py`, button in `VoicePane`. Tested in `test_voice_render.py`
- Script prompt: brief `domain/script_brief.py` (options + `ScriptBrief`), template `domain/script_prompt.py` (`build_prompt`, all prompt wording), material `services/script_prompt.py` (`ScriptPromptService.material`), save + undo `EpisodeService.set_brief`, dialog `ui/widgets/script_prompt.py`, opened by «پرامپت متن» / Ctrl+P in the workspace header. Tested in `test_script_brief.py`
- Idea inbox hotkey: `ui/hotkey.py` (RegisterHotKey, Ctrl+Alt+I), `ui/idea_inbox.py`
- Recorder handoff: `services/recording.py` (os.startfile of the configured program); Ctrl+R is a MainWindow shortcut, so it works on every page
- Shortcuts: app-wide ones in `MainWindow._install_shortcuts`, shown as keycaps (`ui/widgets/key_hint.py`: `KeyHint` beside a button, `attach_key_hint` inside an empty line edit, `NavButton(keys=…)` in the sidebar)
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
- Tests (essential only): tag_matching, tag_limit, activation_window, smart_link_ranking, undo_history, list_filter, navigation_history, publish_checklist, idea_to_episode (plus the feature tests beside them)

## Key decisions (why)
- Audio folder (v1.5): the folder is read, never mirrored into the database. A file becomes a
  Voice only when added, so auditioning a bad take leaves nothing behind; the list is "files
  here minus voices already imported" (paths compared resolved + normcase), which is also why
  a voice removed from the workspace reappears there. No tagging before adding, on purpose:
  that page is for deciding, the Voices page for working. Rows use per-session int ids keyed
  by path; the player gets negative ids so they never collide with a voice's
- Seasons (v1.5): a flat, optional grouping — one season per episode.
  The Episodes list filters by season rather than growing section headers, so selection,
  filter box and Back keep working unchanged; an episode opened from elsewhere switches the
  box to its season so it is never hidden. Filing an episode counts as touching it (stale)
- Season brief (v1.16): two free-text fields, not a template of goals/audience/etc. — the
  placeholders prompt for those without forcing a form. It lives on the Episodes page, not a
  page of its own: a card over the list of the season on show (its first two lines, so the
  direction stays in sight) opens it in the detail pane with no row chosen; choosing an
  episode, or leaving the season, closes it (`EpisodesPage.refresh` keeps that mode across
  rebuilds). Autosaved like a note: one undo step per writing run (`season-brief:{id}`)
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
- Smart links: rank by shared-tag count, then recency, then id; exact tag ids only
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
- Tags page: flat two-column list capped at LIST_WIDTH with usage beside the name, actions in a menu (plus the row's
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
- Keyboard shortcuts (v1.9):
  - Seen, not hidden: every everyday shortcut sits as a keycap beside its control — sidebar
    search Ctrl+K, pages Ctrl+1…6, Back Alt+←, undo Ctrl+Z, «new» buttons Ctrl+N, filter boxes
    Ctrl+F, Ideas search Ctrl+I, «برچسب تازه» Ctrl+T, recorder Ctrl+R, add file Ctrl+Enter.
    A tooltip teaches nothing; a keycap seen a hundred times does
  - App-wide: Ctrl+K search everything, Ctrl+I the Ideas page's search, Ctrl+T new tag (a
    dialog over the current page; only a tag actually made moves to the Tags page), Ctrl+1…6
    pages, Ctrl+Shift+T theme (moved off Ctrl+T)
  - Nothing Windows keeps for itself: no Win key, Alt+Tab/Space/F4, Ctrl+Esc,
    Ctrl+Shift+Esc, Ctrl+Alt (= AltGr on many layouts), bare Ctrl+Shift / Alt+Shift (layout
    switch). The one Ctrl+Alt is the global inbox hotkey, registered on purpose
  - Where a page shortcut and an app-wide one do the same thing (Ctrl+N / Ctrl+T on the Tags
    page, Ctrl+F / Ctrl+I on Ideas) the keycap shows the app-wide one: one key to learn
  - A list column's width floor is a spacer, not a fixed minimum, so a header with keycaps
    widens the column instead of clipping the page title
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
  - Undoable: episode create/edit/status/tags/link/delete (with its notes), the publish
    checklist, ideas put into (or started as) an episode from the Ideas page, episode notes,
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
  - Nothing is saved until the owner taps «ذخیره شود» on the question the bot asks; on yes the
    question message becomes the tag prompt (tag buttons stay optional). A declined text is
    never written; a declined voice goes to the audio source folder. Unanswered questions
    live in the worker's memory only: after a restart their buttons say to send again
  - Text → IdeaNote (hashtags become tags); a hashtag-only message tags the last item; voice/audio/audio-document → file into `bale_voices/`, then a normal voice import. Caption hashtags → tags, rest of caption → TimestampNote at 0:00
  - Free-text tags go through `TagService.resolve_or_create`: exact reuse, near-duplicate reuse (reported to the user as a correction), otherwise create. No tag is created that would then be dropped by the limit
  - Keyboard = 20 most-used tags, frozen per prompt message so buttons do not reorder while tapping; toggles; callback_data self-contained (`t|kind|item|tag`), so old prompts still work
  - First private chat becomes owner (shown/resettable in settings); others get "private" and nothing is saved; groups ignored
  - Offset stored in settings after each update (at-least-once). Updates sent while the app was closed arrive on next start
  - Errors: 401/403 → UNAUTHORIZED, stop until token changes; network/5xx/other → OFFLINE, exponential backoff 3 s → 120 s; per-update exceptions logged, never raised
- Transcription: faster-whisper, CPU int8, language fa, VAD on, condition_on_previous_text off (repetition loops), Persian initial prompt. Audio decoded by our ffmpeg to 16 kHz float32. Model is a local folder: managed download (`models/faster-whisper-<name>`, explicit button, one-time network) or a user folder; loaded with local_files_only. Default model large-v3-turbo. One job at a time; cancel checked per segment. «Transcribe all» (under the Voices list) queues what the switch shows with no transcript and a file on disk; `TranscriptionJobs` runs the queue one by one, cancel skips one voice, a missing model/library ends the batch; progress in the sidebar. 0% is reported only after the model is loaded
- Transcripts are their own entity (not TimestampNotes): the user's notes stay the user's words
- Transcript copy: `domain/transcript_export.py` joins whisper segments into paragraphs (new one
  after a 1.5 s pause, or at a sentence end past 400 chars, or anywhere past 900). «کپی خروجی»
  adds a header (file name, date, length, tags) and each paragraph's time; «کپی متن» is the
  paragraphs alone
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

- Pause trimming (v1.13):
  - Playback only, like the rest of the player: the file is never rewritten. The engine drops
    the cut frames on their way from ffmpeg to the sink and keeps a map from played frames to
    the file's timeline, so every position (clock, notes, transcript, waveform) stays on it
  - Detection reads the waveform's 10 ms RMS: threshold 30 % of the way from the noise floor
    (10th percentile, digital silence ignored) to the speech level (95th); under 12 dB of
    contrast nothing is cut. A ≤30 ms blip is bridged only with 150 ms of quiet on both sides
    (closer to a word it is likely a consonant's burst)
  - «keep» (0–2 s, 0.05 s steps) is the longest pause left, half against each word; 40 ms
    always stays at each word edge, so «0» still leaves ~0.08 s. Joins fade over 6 ms
  - Slider changes show at once (shading, saving) and reach the engine 300 ms after the value
    rests, since each one restarts the decoder. The popup's slider claims the arrow keys
    (ShortcutOverride) from the page's seek shortcuts
  - On by default at every start; the button itself is the switch (S), its ▾ opens the
    popup. Turning it off is for the session: only «keep» is remembered

- Volume (v1.14): a speaker button by the clock drops a slider (mute, level, %); the wheel
  over the button changes it directly, M mutes. The level is remembered, muting is not. The
  slider is a loudness scale (QtAudio.convertVolume log → linear), so 50 % sounds half as loud

- Ideas → episodes (v1.15):
  - The bridge lives on the Ideas page, where the review happens: each editor (audio and
    text) gets an «اپیزودها» row — the episodes it is in, as links that open them — and one
    menu, the same on the editor's button, a row's right-click and the multi-select pane
  - The menu: «اپیزود تازه از این ایده» first (the one thing not possible elsewhere), then
    up to 8 unpublished episodes, most recently worked on first, ticked when the idea is
    already in it; ticking adds, unticking removes — a label menu. With several ideas a tick
    means all of them. Published and older episodes are behind «همهٔ اپیزودها…» (picker)
  - A new episode opens at once with its title selected (it is named after the first idea
    until renamed; Back returns to the list as it was) and carries the ideas' tags, so the
    workspace's suggestions work from the start. Adding to an existing episode stays on
    the Ideas page, says «به «X» اضافه شد» and redraws the rows in place (no reload: a
    selection being worked through must survive)
  - One undo step each (`set_linked` records one LINKED/UNLINKED with every name,
    `create_from` one CREATE). Undoing a link while on the Ideas page refreshes it there
    instead of jumping to the episode
  - Rows say «در N اپیزود»: the weekly review's other question is "used yet?"
- Material preview (v1.15):
  - Opening a linked item or a suggestion in the workspace turns the materials panel into
    it, rather than leaving for the Ideas page (which broke the writing thread) or opening
    a new column (the frame would change under the user). The panel widens to match the
    note (stretch 1:1, 430–640 px); its arrow or Esc turns it back into the lists
  - Read, not edit: text ideas are a read-only, selectable text (copy into the note);
    audio ideas get the player and the transcript (transcribe from there too). «باز کردن در
    ایده‌ها» is the way to edit; a suggestion gets «پیوند دادن» in the preview
  - Player keys ride on the preview's audio view only — in the note, Space is a space. The
    shared player is taken back on show if another page loaded something meanwhile.
    Another episode, or the item going to the trash, closes the preview. Back restores it
- Publish checklist (v1.15):
  - Four ticks (final title, description, clips, cover) and a fifth that is a record rather
    than a tick: where it was published, one place or link per line, done once non-empty
  - A chip in the stage row («انتشار ۲ از ۵», filled when complete) with a popup, not a
    section: for most of an episode's life it is nothing to look at. Ticks save at once;
    «where» saves as typed and coalesces into one undo step. Every change touches the
    episode (stale). Exported and restored; older exports import with an empty checklist
- Untagged filter (v1.15): a toggle chip beside the Ideas tag filter, with the count of
  untagged ideas in the current kind/archive view — the weekly review's to-do number. It
  excludes required tag chips (turning it on empties them; choosing a tag turns it off),
  ANDs with the phrases, lives in the facet state (Back) and resets with «پاک کردن همه».
  An empty result says the review is done rather than "no match"
- Export as heard (v1.17): «خروجی گرفتن…» under an audio idea writes it out with the
  player's pause trimming and volume. Speed is left out on purpose: it is a listening
  choice, and it would move every note. Asks «صوت تازه» (default, loses nothing) or
  «جایگزین کن» (not undoable, the box says so), then renders behind a cancelable progress box
  - The same `Splicer` as playback does the cutting (identical joins and fades); ffmpeg
    decodes and re-encodes in the source's format at generous quality (AMR → M4A: no
    encoder). The volume is the slider's level mute aside — it can only lower (100 = as is)
  - New copy: «name 01», «02»… (a copy of «name 01» counts on from «name» instead of
    growing «01 01»), with the tags, notes and transcript; not the episode links (a copy
    would appear twice in the materials). Imported-like: not undoable, can go to the trash
  - Both ways move note and transcript times back by the cuts before them, so they still
    point at the same words. Replace lets go of the file in the player first (Windows won't
    write over an open file) and retries the swap briefly
  - Audio folder: a stored copy written after its original (trimmed and replaced) still
    marks that original as known, so it isn't offered again
- Bale sends voices trimmed (v1.17): a searched voice goes with its pauses trimmed at the
  remembered keep setting (whether trimming is on in the app is a session thing), rendered
  into a temp dir; note times and length in the caption follow the trimmed audio. The file
  id is cached per (voice, keep setting, file time). Unreadable pauses → the original goes

- Script prompt (v1.19):
  - A fixed template, no AI call: the app only assembles; the user copies the prompt into
    any AI. The prompt is Persian in both UI languages (the podcast is Persian). Order: role,
    episode (title, tags, about, season brief and its other episodes), specs, draft (notes),
    ideas (text; audio = transcript paragraphs + timestamp notes), the human-voice rules,
    then the process: check my claims, research, outline, list the changes, *wait for my
    approval*, only then write the final script
  - The brief is the episode's own (JSON column, one undo step per editing run, exported),
    so the prompt is the same next time. Options regrouped from the user's list: single
    where the choices exclude each other — format (who speaks: monologue / dialogue / panel),
    depth (1–5 ladder: one topic in five episodes, each deeper), register (casual /
    semi-formal / formal: spoken vs written Persian); multi where they combine — narrative
    style (story / recital over music / documentary; none = plain talk), audience, approach,
    mood. Style is not folded into mood: mood is how it feels, style how it is told, and any
    mood goes with any style. «کمی خلاصه/مشروح» and «عمیق» were dropped: length and depth
    cover them. Defaults: monologue, no style, general public, depth 1, conceptual only,
    semi-formal, 15 min. Briefs saved with the first shape (one "formats" list) are split
    on read by `ScriptBrief.from_dict`
  - The draft is the episode's notes, not a new text field: one place to write. The dialog
    ticks notes in or out (`left_out_notes`, kept with the brief) so a to-do note or a script
    pasted back from the AI stays out; new notes are in by default
  - Audio ideas with neither transcript nor notes are named in the dialog as left out
  - A sibling episode's depth is shown only if its brief was ever changed: a default 1
    would mislead the AI about the ladder
  - The preview forces RTL + right alignment on its document: QPlainTextEdit otherwise lays
    out lines that open with a markdown "#"/"-" with the mark at the far end

## Gotchas
- New migration: set `PODCAST_WORKSPACE_HOME=<tmp>` before `alembic revision --autogenerate`, else it diffs your real DB. Replace autogenerated `UTCDateTime()` with `sa.DateTime()`; keep `render_as_batch=True`; `alembic check` must stay clean (env.py ignores `search_*`)
- Migrations run with foreign keys off (`db.migration_connection`, used by `migrate()` and the CLI env), then `PRAGMA foreign_key_check` must come back empty. A table rebuild would otherwise drop the old table under foreign_keys=ON and every CASCADE child would go with it (tag links, notes, transcripts). Adding a column is still best done with a plain `ALTER TABLE … ADD COLUMN` (see b8d4e6f1a320)
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
- `EpisodeService.update` rebuilds the Episode field by field: a new Episode field must be copied
  there too (the checklist was reset by every title edit until it was)
- Removing widgets from a `FlowLayout` for a rebuild: `setParent(None)` before `deleteLater()`,
  or the old widget is still painted (over the new one) until the event loop turns. Take the
  widget from the layout item first: after `setParent(None)` the item no longer holds it
- Palette Highlight is the pastel accent (a fill) and HighlightedText is its dark ink. Row
  selections are the lighter accent_soft, so delegates draw selected text in Text, never
  HighlightedText (unreadable in dark). Lines/focus/markers use the Link role (accent_strong)

## Status
- v1.21: numbers — a season and an episode can each have a number (`NumberBox` before the
  title in the episode workspace and the season page; «#» = none; undoable, not touching,
  exported). Order everywhere = `in_order`: by number, the unnumbered after them by creation.
  It orders the season boxes, the Episodes list when one season is shown (the all / no-season
  views stay by last change), and the season's earlier/later episodes in the script prompt.
  Why by hand: an episode made early can say it is the third. Titles show «۳. عنوان» in the
  list and the season boxes. Numbers are not checked for duplicates; nothing renumbers itself
- v1.20: season readme + episode summary — a season's brief is now «راهنمای فصل» (README:
  strategy, rules, goals; in the script prompt) beside «دربارهٔ فصل» (for listeners, not in
  the prompt); the old summary + structure were merged into the readme. Each episode has a
  «خلاصه» field under its tags (undoable, exported). The script prompt gets its own
  «# فصل» section: the readme, the season's earlier episodes with their summaries, the later
  ones by title, plus a continuity check step. Season order = creation order (v1.21: by
  number). Both are checkboxes in the prompt dialog, saved in the brief (`season_readme`,
  `previous_summaries`)
- v1.19: script prompt — «پرامپت متن» (Ctrl+P) in the episode header opens the episode's
  script brief (about, format, audience, depth ladder, approach, mood, register, length,
  which notes are the draft) beside a live prompt built from a fixed template, with «کپی
  پرامپت». Brief saved on the episode (migration d4f2b8e6a1c3), undoable, exported
- v1.18: audio folder — «حذف از فهرست» (Delete) hides a file, which stays on the disk
  (setting `voices.source_hidden`: path key → mtime, so a new take under the same name is
  listed again; marks of files gone, replaced or added are dropped), «پنهان‌شده‌ها» under the
  list shows them and puts them back; «حذف از دیسک…» (Shift+Delete) sends it to the Windows
  Recycle Bin after a confirmation (player closed first, retried while the decoder lets go;
  permanent only if that fails and the user says so)
- v1.17: «خروجی گرفتن» — an audio idea saved with the player's pause trimming and volume,
  as a new voice («name 01», with tags, notes, transcript) or in place, times moved to
  match; the Bale bot sends searched voices trimmed the same way
- v1.16: season brief — «دربارهٔ فصل» and «ساختار» per season (`ui/pages/season_brief.py`,
  migration b3d7a1f9c524): a card over the season's episodes opens it beside the list, with
  the season's name editable in place and its episodes counted by stage. Undoable, exported
- v1.15: ideas → episodes from the Ideas page (the episodes an idea is in, «add to episode» /
  «new episode from this idea» for one idea or a selection, «in N ep.» on rows); linked
  material previewed inside the workspace's materials panel (text, or player + transcript);
  a publish checklist per episode (chip + popup, migration c6e1a8f4b2d7); «بی‌برچسب» filter
  with a count on the Ideas page
- v1.13: pause trimming while playing: «حذف سکوت» beside the speed button, a 0–2 s «pause
  to keep» slider, skipped stretches shaded on the waveform, saving shown, remembered
- v1.12: search from the Bale bot (`services/bale_search.py`, ranking in
  `domain/pocket_search.py`): «؟ words #tag», /search (tag menu, next text is the query) or
  «🔍 جستجو» under the save question. Same matching as the Ideas page, content always read
  (idea text, voice notes + transcript); named hits before content hits, newest first. Five per
  page; a number sends the idea's text or uploads the voice (file id cached per run); tag
  buttons narrow in place, ✖ loosens. Searches live in memory, archived items included (🗄)
- v1.11: transcript copy as paragraphs, with or without header and times; the Bale bot asks
  before saving a text idea too, and a «no» stores nothing
- v1.10: multi-select on the Ideas page (Ctrl/Shift+click, Ctrl+A): a selection pane
  transcribes, archives, moves to the recycle bin or deletes forever, each one grouped undo
  step (`HistoryService.grouped`, target `ITEMS`). «حذف کامل» (`TrashService.delete_forever`,
  Shift+Delete) skips the trash, same cascade as a purge. Transcription progress follows a
  clock estimate between whisper's 30 s windows, learned per model
  (`transcription.seconds_per_audio_second`). Episode materials: linked lists sorted by
  shared tags, double-click opens everywhere (Space links in suggestions), and the linked
  tabs point to same-tag suggestions. «سطل زباله» → «سطل بازیافت»
- v1.9: tags are flat — the parent/child hierarchy is gone everywhere (model, migration
  a9e2d5c8f314, services, undo, export, tags page, pickers, idea tag filter). Keycaps beside
  the main controls; Ctrl+I (Ideas search) and Ctrl+T (new tag) from anywhere. Emptying the
  sidebar search keeps the caret in it
- v1.8: Voices and Ideas merged into one «ایده‌ها» page (`ui/pages/ideas_page.py`; rows keyed by
  `IdeaKey(kind, id)`, kind switch همه/صوتی/متنی, one editor pane per kind). Its search is a
  `FacetSearchBar`: phrases kept as chips with Enter, required tag chips, all ANDed (`domain/list_filter.FacetFilter`), plus «در محتوا» for idea text and
  transcripts. Global search reads titles only unless «در محتوا» is on (idea first line indexed
  as its title, migration f3a8c1e5d907), counts what the content would add, and has kind tabs
  with counts. One vocabulary everywhere (UI, episode workspace, trash, undo, Bale bot):
  «ایدهٔ صوتی» / «ایدهٔ متنی» (audio idea / text idea); «صوت» for the recording itself
- v1.7: «Transcribe all» queue on the Voices page, progress in the sidebar
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
