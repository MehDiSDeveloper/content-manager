"""English text for every name in `strings.py`. `strings.apply_language("en")` copies it
over the Persian originals at startup; `tests/test_strings.py` keeps the two in step."""

from podcast_workspace.domain.entities import EpisodeStatus
from podcast_workspace.domain.search import SearchKind

LANGUAGE = "en"
RTL = False
QUOTE = "“{text}”"
DECIMAL_SEPARATOR = "."
DIRECTION_MARK = "\u200e"  # LRM

APP_NAME = "Podcast Workspace"
STARTUP_ERROR_TITLE = "Startup error"
STARTUP_ERROR_BODY = "The database could not be opened:\n{error}"

THEME_TO_DARK = "Dark theme"
THEME_TO_LIGHT = "Light theme"
THEME_TOOLTIP = "Switch theme (Ctrl+T)"
NAV_TOOLTIP = "{label} — {keys}"

NAV_EPISODES = "Episodes"
NAV_IDEAS = "Ideas"
NAV_TAGS = "Tags"

NAV_BACK = "Back"
NAV_BACK_TO = "Back to {page}"
NAV_BACK_TOOLTIP = "Back to {page}, right where you were  (Alt+←)"
NAV_BACK_NOTHING = "Nowhere to go back to  (Alt+←)"
SIDEBAR_COLLAPSE = "Collapse sidebar  (Ctrl+B)"
SIDEBAR_EXPAND = "Expand sidebar  (Ctrl+B)"

SEARCH_PLACEHOLDER = "Search…"
SEARCH_TOOLTIP = "Search titles, names and tags; text too with “In content” (Ctrl+K)"
SEARCH_TITLE = "Search results"
SEARCH_EMPTY = "Nothing found. Try part of a word or a tag name."
SEARCH_CORRECTED = "Spelling corrected: {pairs}"
SEARCH_VIA_TAG = "tag “{tag}”"
KIND_LABELS = {
    SearchKind.EPISODE: "Episode",
    SearchKind.IDEA_NOTE: "Text idea",
    SearchKind.EPISODE_NOTE: "Episode note",
    SearchKind.TIMESTAMP_NOTE: "Timestamped note",
    SearchKind.TAG: "Tag",
    SearchKind.VOICE: "Audio idea",
    SearchKind.TRANSCRIPT: "Transcript",
}
UNTITLED_NOTE = "Untitled note"

STATUS_LABELS = {
    EpisodeStatus.IDEA: "Idea",
    EpisodeStatus.OUTLINE: "Outline",
    EpisodeStatus.RECORDED: "Recorded",
    EpisodeStatus.SCRIPT_READY: "Script ready",
    EpisodeStatus.EDITED: "Edited",
    EpisodeStatus.PUBLISHED: "Published",
}

EPISODES_TITLE = "Episodes"
EPISODE_NEW = "New episode"
EPISODE_DEFAULT_TITLE = "New episode"
EPISODE_TITLE_PLACEHOLDER = "Episode title"
EPISODE_STATUS = "Status"
EPISODE_NEXT_ACTION = "Next step"
EPISODE_NEXT_ACTION_PLACEHOLDER = "One sentence: what is the next thing to do for this episode?"
EPISODE_EMPTY = "No episodes yet. Start with “New episode”."
EPISODE_DELETE_CONFIRM = "Delete episode “{title}”? Linked audio and text ideas are kept."
LIST_HIDE = "Hide the list — more room to write  (Ctrl+L)"
LIST_SHOW = "Show the episode list  (Ctrl+L)"
EPISODE_DELETE = "Delete episode"
EPISODE_MORE = "More actions"

SEASON_ALL = "All seasons"
SEASON_NONE = "No season"
SEASON_ITEM = "{title}  ({n})"
SEASON_LABEL = "Season"
SEASON_FILTER_TOOLTIP = "Show the episodes of one season"
SEASON_ACTIONS_TOOLTIP = "Season actions"
SEASON_NEW = "New season…"
SEASON_NEW_TITLE = "New season"
SEASON_NAME_PROMPT = "Season name:"
SEASON_DEFAULT_TITLE = "Season {n}"
SEASON_RENAME = "Rename this season…"
SEASON_RENAME_TITLE = "Rename season"
SEASON_DELETE = "Delete this season"
SEASON_DELETE_CONFIRM = (
    "Delete the season “{title}”? Its episodes are kept; they just belong to no season."
)
SEASON_EMPTY = "This season has no episodes yet. “New episode” creates one right in it."
SEASON_NONE_EMPTY = "Every episode belongs to a season."

NAV_SOURCE = "Audio folder"
SOURCE_TITLE = "Audio folder"
SOURCE_CHOOSE = "Folder…"
SOURCE_CHOOSE_TOOLTIP = "Choose the folder your recording program saves into"
SOURCE_DIALOG = "Audio files folder"
SOURCE_FOLDER_MISSING = "This folder was not found: {path}"
SOURCE_NO_FOLDER = (
    "No folder chosen yet.\n"
    "Press “Folder…” and pick the folder your recordings are saved in. "
    "Every file in it shows up here on its own, to listen to and, if you want, "
    "add to the workspace."
)
SOURCE_EMPTY = "No new files in this folder; everything is in the workspace."
SOURCE_HINT = (
    "This file is not in the workspace yet and nothing about it is stored. "
    "Once added, you can tag it and take notes on it."
)
SOURCE_FILTER_PLACEHOLDER = "Filter by file name…"
SOURCE_ADD = "Add to workspace"
SOURCE_ADD_TOOLTIP = "Adds it to audio ideas; the file stays where it is  (Ctrl+Enter)"
SOURCE_ADD_OPEN = "Add and open"
SOURCE_ADD_OPEN_TOOLTIP = "Add it, then go to Ideas to tag it and take notes"
SOURCE_ADDING = "Adding…"
SOURCE_ADDED = "“{name}” was added to audio ideas"
SOURCE_IN_SUBFOLDER = "in {folder}"
SIZE_MB = "{n} MB"
SIZE_KB = "{n} KB"

VOICE_IMPORT = "Add audio"
VOICE_IMPORT_DIALOG = "Choose audio files"
VOICE_IMPORT_FILTER = "Audio files ({patterns})"
VOICE_IMPORTING = "Importing…"
VOICE_IMPORT_DONE = "{imported} files imported"
VOICE_IMPORT_DUP = "{n} already there"
VOICE_IMPORT_UNSUPPORTED = "{n} not supported"
VOICE_IMPORT_FAILED = "{n} could not be read"
VOICE_MISSING = "The file is no longer at this path."
VOICE_SHOW_IN_FOLDER = "Show in folder"
VOICE_DURATION_UNKNOWN = "Unknown length"
VOICE_PATH_TOOLTIP = "File path — click to copy"
VOICE_PATH_COPIED = "Path copied"
VOICE_NOTE_COUNT = "{n} notes"

IDEAS_TITLE = "Ideas"
IDEA_NEW = "Write idea"
IDEA_PLACEHOLDER = "Write your idea… (saved automatically)"
IDEA_UNSAVED = "New text idea (not saved yet)"

ARCHIVE_SCOPES = {
    "active": "Active",
    "all": "All",
    "archived": "Archived",
}
ARCHIVE_SCOPE_TOOLTIP = "Which to show: active, all, or only archived"
SEARCH_SCOPE_TOOLTIP = "Archived items are searched only when “All” or “Archived” is chosen"
ARCHIVE = "Archive"
UNARCHIVE = "Unarchive"
ARCHIVE_TOOLTIP = "Leaves the active list and everyday search; tags and links stay"
UNARCHIVE_TOOLTIP = "Back to the active list"
ARCHIVED_BADGE = "Archived"
ARCHIVED_NOTE = "Archived — not in the active list or everyday search"
MOVE_TO_TRASH = "Move to trash"
MOVE_TO_TRASH_TOOLTIP = "Kept in the trash for {days} days, restorable from there  (Delete)"

NAV_TRASH = "Trash"
TRASH_TITLE = "Trash"
TRASH_HINT = (
    "Deleted items stay here for {days} days, then are gone for good. Until then they "
    "appear in no list or search, and everything they hold is kept."
)
TRASH_EMPTY = "The trash is empty."
TRASH_FILTER_PLACEHOLDER = "Search the trash…"
TRASH_FILTER_TOOLTIP = "Search the text, names and tags of deleted items  (Ctrl+F)"
TRASH_KINDS = {
    "all": "All",
    "voice": "Audio",
    "idea": "Text",
}
TRASH_RESTORE = "Restore"
TRASH_RESTORE_TOOLTIP = "Put the selected items back where they were  (Enter)"
TRASH_RESTORE_ALL = "Restore all"
TRASH_PURGE = "Delete forever"
TRASH_PURGE_TOOLTIP = "Delete the selected items, with no way back  (Delete)"
TRASH_EMPTY_ALL = "Empty trash"
TRASH_SELECT_ALL = "Select all"
TRASH_SELECT_ALL_TOOLTIP = "Select every item in this list  (Ctrl+A)"
TRASH_SELECTED = "{n} selected"
TRASH_PURGE_CONFIRM = (
    "Delete {n} items forever? Their tagging, notes, transcripts and links go too, and "
    "this cannot be undone. Audio files stay on disk."
)
TRASH_EMPTY_CONFIRM = (
    "Delete all {n} items in the trash forever? This cannot be undone. Audio files stay on disk."
)
TRASH_RESTORE_ALL_CONFIRM = "Restore all {n} items in the trash?"
TRASH_RESTORED = "{n} restored"
TRASH_PURGED = "{n} deleted forever"
TRASH_AUTO_PURGED = "{n} items that spent {days} days in the trash were deleted for good"
TRASH_DAYS_LEFT = "{n} days left"
TRASH_DELETED_AT = "Deleted {when}"
TRASH_FROM_ARCHIVE = "returns to the archive"
TRASH_PREVIEW_EMPTY = "Select an item to see what it holds."
TRASH_PREVIEW_MANY = "{n} selected. Restore or Delete forever applies to all of them."
TRASH_VOICE_HINT = "Restore it to listen and edit."

TAGS_TITLE = "Tags"
TAG_NEW = "New tag"
TAG_FILTER_PLACEHOLDER = "Find a tag…"
TAG_FILTER_TOOLTIP = "Find a tag in this tree  (Ctrl+F)"
TAG_RENAME = "Rename"
TAG_RECOLOR = "Change colour"
TAG_NEST = "Move under…"
TAG_UNNEST = "Move to top level"
TAG_MERGE = "Merge into…"
TAG_DELETE = "Delete"
TAG_EMPTY = "No tags yet. You can also create tags while working on episodes and ideas."
TAG_USAGE_HEADER = "Used"
TAG_ACTIONS = "Actions"
TAG_ACTIONS_TOOLTIP = "Actions for this tag"
TAG_USES_TITLE = "Where it is used"
TAG_USES_EMPTY = "This tag is not used anywhere yet."
TAG_USES_NONE = "Select a tag to see its items here."
TAG_USES_COUNT = "{n} items"
TAG_OPEN_ITEM = "Open (Enter)"
TAG_NAME_HEADER = "Name"
TAG_DELETE_CONFIRM = (
    "Delete tag “{name}”? It is removed from {n} items and its children move up one level."
)
TAG_MERGE_CONFIRM = "Move every use of “{source}” to “{target}” and delete “{source}”?"
TAG_NEST_TITLE = "Move “{name}” under…"
TAG_MERGE_TITLE = "Merge “{name}” into…"
TAG_NEW_TITLE = "New tag"
TAG_NAME_PLACEHOLDER = "Tag name"
TAG_SIMILAR_HINT = "Similar tags already exist — maybe one of these is the same:"
TAG_EXACT_EXISTS = "Tag “{name}” already exists."
TAG_CREATE = "Create"
TAG_CREATE_ANYWAY = "Create anyway"
TAG_PICK = "Choose"

TAG_INPUT_PLACEHOLDER = "Add a tag…"
TAG_INPUT_COUNT = "{n} of {limit}"
TAG_INPUT_FULL = "The {limit}-tag limit is reached"
TAG_INPUT_CREATE = "Create new tag “{name}”"
TAG_INPUT_CREATE_SIMILAR = "Create new tag “{name}” — “{similar}” is similar"
TAG_REMOVE_TOOLTIP = "Remove tag"
TAG_LABEL = "Tags"

FILTER_TOOLTIP = "Filter this list by title and tag  (Ctrl+F)\n“#name” searches tags only"
FILTER_COUNT = "{shown} of {total}"
FILTER_COUNT_TOOLTIP = "Showing {shown} of {total} items"
FILTER_NO_MATCH = "Nothing matches “{query}”.\nTry part of a word, or type “#” and a tag name."
FILTER_CLEAR = "Clear filter (Esc)"
EPISODE_FILTER_PLACEHOLDER = "Filter episodes by title or tag…"

CANCEL = "Cancel"
DELETE = "Delete"
CONFIRM_TITLE = "Confirm"
ERROR_TITLE = "Error"
CREATED_AT = "Created {when}"
UPDATED_AT = "Last changed {when}"
IMPORTED_AT = "Imported {when}"
SELECT_SOMETHING = "Select an item from the list."

ERR_TAG_LIMIT = "An item can have at most {limit} tags."
ERR_DUPLICATE_TAG = "Tag “{name}” already exists."
ERR_NEAR_DUPLICATE = "Similar tags exist: {names}"
ERR_HIERARCHY = "A tag cannot sit under itself or one of its children."
ERR_VALIDATION = "That value is not valid (it cannot be empty, for example)."
ERR_NOT_FOUND = "This item no longer exists."
ERR_UNEXPECTED = "Unexpected error: {error}"

PLAYER_PLAY_TOOLTIP = "Play (Space)"
PLAYER_PAUSE_TOOLTIP = "Pause (Space)"
PLAYER_BACK_TOOLTIP = "Back 10 seconds (←)"
PLAYER_FORWARD_TOOLTIP = "Forward 10 seconds (→)"
PLAYER_SPEED_TOOLTIP = "Playback speed (- and =)"
PLAYER_LOADING = "Reading the file…"
PLAYER_ERROR = "Playback failed: {error}"

TS_TITLE = "Timestamped notes"
TS_COUNT = "{n} notes"
TS_PLACEHOLDER = "A note at this moment…  (Insert)"
TS_ADD = "Add"
TS_CAPTURE_TOOLTIP = "The note's time; click to take the current moment"
TS_GOTO_TOOLTIP = "Go to this moment (Enter)"
TS_EMPTY = "No notes for this audio yet. Press Insert while it plays and start typing."
TS_EDIT = "Edit (F2)"
TS_DELETE = "Delete (Delete)"
TS_DELETE_CONFIRM = "Delete note “{text}”?"

NAV_BOARD = "Board"
BOARD_TITLE = "Production board"
BOARD_COLUMN_COUNT = "{n}"
BOARD_HINT = "Drag cards between columns or press Ctrl+←/→; Enter opens"
BOARD_EMPTY = "No episodes yet. Start with “New episode”, then drag cards between columns."
STALE_BADGE = "Stale: {days} days"
STALE_TOOLTIP = "This episode has not been touched for more than 10 days"

WS_NOTES = "Notes"
WS_NOTE_NEW = "New note"
WS_NOTE_TITLE_PLACEHOLDER = "Note title (optional)"
WS_NOTE_BODY_PLACEHOLDER = "Write… (saved automatically)"
WS_NOTES_EMPTY = "This episode has no notes yet. Start with “New note” (Ctrl+N)."
WS_NOTE_DELETE = "Delete note"
WS_NOTE_DELETE_CONFIRM = "Delete note “{title}”?"
WS_LINK_ADD = "Add…"
WS_LINKED_EMPTY = "—"
WS_VOICES_EMPTY = (
    "No audio ideas are linked to this episode yet. Click “Add…” or pick from the suggestions tab."
)
WS_IDEAS_EMPTY = (
    "No text ideas are linked to this episode yet. Click “Add…” or pick from the suggestions tab."
)
WS_UNLINK = "Unlink (Delete)"
WS_OPEN = "Open (Enter)"
WS_MATERIALS = "Episode material"
WS_TAB_VOICES = "Audio"
WS_TAB_IDEAS = "Text"
WS_TAB_SMART = "Suggested"
WS_TAB_COUNT = "{label} {n}"
WS_SMART = "Same-tag suggestions"
WS_SMART_NO_TAGS = "Tag the episode and audio and text ideas with the same tags show up here."
WS_SMART_NONE = "No idea shares a tag with this episode."
WS_SMART_SUBTITLE = "{kind}, {n} shared tags: {names}"
WS_SMART_LINKED = "Linked ✓"
WS_LINK = "Link"
WS_UNLINK_SHORT = "Unlink"
WS_RECORD = "Record"
WS_RECORD_TOOLTIP = "Launch your recording program — from anywhere in the app (Ctrl+R)"
WS_PICK_VOICE = "Add audio ideas to the episode"
WS_PICK_IDEA = "Add text ideas to the episode"
WS_PICK_FILTER = "Filter…"
WS_PICK_ADD = "Add"
WS_PICK_EMPTY = "Nothing left to add."
KIND_VOICE = "Audio idea"
KIND_IDEA = "Text idea"

RESUME_EYEBROW = "Pick up where you left off"
RESUME_NEXT_ACTION = "Next step"
RESUME_NO_NEXT = "No next step yet."
RESUME_LAST_NOTE = "Last note"
RESUME_NO_NOTE = "No notes yet."
RESUME_CONTINUE = "Continue"
RESUME_SKIP = "All episodes (Esc)"

INBOX_TITLE = "New text idea"
INBOX_PLACEHOLDER = "Write the idea…"
INBOX_HINT = "Enter saves · Shift+Enter new line · Esc closes"

SETTINGS = "Settings"
SETTINGS_TOOLTIP = "Settings (Ctrl+,)"
SETTINGS_RECORDER = "Recording program"
SETTINGS_RECORDER_HINT = (
    "The program you record with. The “Record” button launches it; "
    "this app does not record audio itself."
)
SETTINGS_BROWSE = "Browse…"
SETTINGS_PROGRAM_DIALOG = "Choose the recording program"
SETTINGS_PROGRAM_FILTER = "Programs (*.exe *.lnk *.bat *.cmd);;All files (*)"
SETTINGS_HOTKEY = "Global idea hotkey"
SETTINGS_HOTKEY_OK = "{keys} — opens a small window to jot down an idea, from any program."
SETTINGS_HOTKEY_FAIL = "{keys} is unavailable; another program has taken it."
SAVE = "Save"
RECORDER_MISSING = "The recording program was not found at:\n{path}"

SETTINGS_TAB_GENERAL = "General"
SETTINGS_TAB_BOT = "Bale bot"
SETTINGS_TAB_TRANSCRIPTION = "Transcription"
SETTINGS_TAB_DATA = "Data"

BOT_ENABLE = "Receive text and audio ideas from a Bale bot"
BOT_TOKEN = "Bot token"
BOT_TOKEN_PLACEHOLDER = "The token @botfather gave you in Bale"
BOT_TOKEN_SHOW = "Show"
BOT_TOKEN_CHECK = "Test token"
BOT_TOKEN_CHECKING = "Checking…"
BOT_TOKEN_OK = "The token is valid: {name}"
BOT_TOKEN_BAD = "The token was rejected."
BOT_TOKEN_OFFLINE = "Could not reach Bale; check your internet connection."
BOT_HELP = (
    "Message @botfather in Bale, create a bot and paste its token here. "
    "Every text message to the bot becomes a text idea and every voice message an audio idea "
    "in this workspace; messages sent while the app is closed arrive when it opens."
)
BOT_OWNER = "Bot owner: {name}"
BOT_OWNER_NONE = "Nobody has messaged the bot yet; the first private chat becomes its owner."
BOT_OWNER_RESET = "Release"
BOT_STATUS = {
    "stopped": "off",
    "connecting": "connecting…",
    "online": "connected",
    "offline": "offline; retrying",
    "unauthorized": "token rejected",
}
BOT_SIDEBAR = "Bale: {status}"
BOT_RECEIVED_IDEA = "A new text idea arrived from Bale"
BOT_RECEIVED_VOICE = "A new audio idea arrived from Bale"

TR_TAB_NOTES = "Notes"
TR_TAB_TRANSCRIPT = "Transcript"
TR_RUN = "Transcribe"
TR_RERUN = "Transcribe again"
TR_RUN_TOOLTIP = "Turn this audio's speech into Persian text, offline"
TR_CANCEL = "Cancel"
TR_COPY = "Copy text"
TR_COPIED = "Text copied"
TR_EMPTY = "No transcript yet. “Transcribe” turns this audio into text, on this computer."
TR_NO_SPEECH = "No speech was found in this audio."
TR_RUNNING = "Transcribing… {percent}%"
TR_LOADING_MODEL = "Preparing the model…"
TR_BUSY_ELSEWHERE = "Another audio is being transcribed."
TR_QUEUED = "This audio is waiting in the “Transcribe all” queue."
TR_ALL = "Transcribe all"
TR_ALL_STOP = "Stop transcribing all"
TR_ALL_TOOLTIP = (
    "Queue the audio ideas in this list with no transcript and transcribe them one by one"
)
TR_ALL_NONE = "Every audio idea in this list already has a transcript."
TR_ALL_CONFIRM = (
    "{n} audio ideas have no transcript. Transcribe them one by one in the background?\n"
    "Depending on their length this can take a long time; you can keep using the app meanwhile."
)
TR_ALL_START = "Start transcribing"
TR_ALL_DONE = "Transcribe all finished: {ok} of {total} audio ideas transcribed."
TR_ALL_STOPPED = "Transcribe all stopped: {ok} of {total} audio ideas transcribed."
TR_ALL_SIDEBAR = "Transcribing all: {n} of {total}"
TR_ALL_SIDEBAR_PERCENT = "Transcribing all: {n} of {total}  ·  {percent}%"
TR_META = "{n} segments, {model}, {when}"
TR_NOT_INSTALLED = "faster-whisper is not installed; install it with: pip install .[transcription]"
TR_MODEL_MISSING = (
    "The transcription model is not on this computer yet. Get it in Settings → Transcription."
)
TR_OPEN_SETTINGS = "Transcription settings"
TR_FAILED = "Transcription failed: {error}"
TR_FILE_MISSING = "The audio file was not found."
TR_REPLACE_CONFIRM = "Replace the current transcript with the new result?"
TR_REPLACE = "Replace"
TR_GOTO_TOOLTIP = "Go to this moment (Enter)"
VOICE_HAS_TRANSCRIPT = "Transcript"

TR_MODEL = "Model"
TR_MODELS = {
    "small": "small — fast, less accurate (about 500 MB)",
    "medium": "medium — balanced (about 1.5 GB)",
    "large-v3-turbo": "large-v3-turbo — recommended (about 1.6 GB)",
    "large-v3": "large-v3 — most accurate, slowest (about 3 GB)",
}
TR_MODEL_READY = "The model is ready: {path}"
TR_MODEL_NOT_READY = "This model has not been downloaded yet."
TR_MODEL_DOWNLOAD = "Download model"
TR_MODEL_DOWNLOADING = "Downloading the model… (once; this can take a while)"
TR_MODEL_DOWNLOAD_FAILED = "The model could not be downloaded: {error}"
TR_MODEL_DIR = "Custom model folder (optional)"
TR_MODEL_DIR_PLACEHOLDER = "A folder containing model.bin; empty = the downloaded model"
TR_MODEL_DIR_DIALOG = "Choose a faster-whisper model folder"
TR_MODEL_HELP = (
    "Transcription runs entirely on this computer. Only downloading the model, once, "
    "needs the internet."
)

DATA_EXPORT = "Export…"
DATA_EXPORT_HELP = (
    "Every episode, idea, note, tag, transcript and audio file in one zip file. "
    "Settings (including the bot token) are not included."
)
DATA_EXPORT_DIALOG = "Save export"
DATA_EXPORT_FILTER = "Workspace export (*.zip)"
DATA_EXPORTING = "Exporting… {percent}%"
DATA_EXPORT_DONE = "Export saved: {path}"
DATA_EXPORT_MISSING = "{n} audio files were not found and are not in the export."
DATA_IMPORT = "Restore from export…"
DATA_IMPORT_HELP = (
    "All current data is replaced by the file's contents. Before that, a backup of the "
    "current state is saved in the backups folder."
)
DATA_IMPORT_DIALOG = "Choose an export file"
DATA_IMPORT_CONFIRM = (
    "Replace all current episodes, audio and text ideas and tags with this file's contents?\n"
    "A backup of the current state is saved in the backups folder."
)
DATA_IMPORT_ACTION = "Replace"
DATA_IMPORTING = "Restoring… {percent}%"
DATA_IMPORT_DONE = (
    "Restored: {episodes} episodes, {voices} audio ideas, {ideas} text ideas, {tags} tags."
)
DATA_IMPORT_BAD_FILE = "This file is not an export of this app, or it is damaged."
DATA_FOLDER = "Data folder"
DATA_OPEN_FOLDER = "Open folder"

SETTINGS_LANGUAGE = "App language"
LANGUAGE_NAMES = {"fa": "فارسی", "en": "English"}
LANGUAGE_RESTART_TITLE = "Change language"
LANGUAGE_RESTART = "The new language applies after the app restarts. Restart now?"
LANGUAGE_RESTART_NOW = "Restart"
LANGUAGE_RESTART_LATER = "Later"

BACKUP_REMINDER_TITLE = "Backup reminder"
BACKUP_REMINDER_BODY = "It has been {days} days since your last backup."
BACKUP_REMINDER_NEVER = "You have not backed up your data yet."
BACKUP_REMINDER_HINT = (
    "One export file keeps every episode, note, and audio and text idea. "
    "Keep it on another disk or in cloud storage."
)
BACKUP_NOW = "Back up now"
BACKUP_TOMORROW = "Remind me tomorrow"
BACKUP_LATER = "Later"
SETTINGS_BACKUP_REMINDER = "Backup reminder"
BACKUP_INTERVALS = {
    0: "Off",
    3: "Every 3 days",
    7: "Every week",
    14: "Every two weeks",
    30: "Every month",
}
BACKUP_LAST = "Last backup: {when}"
BACKUP_LAST_NEVER = "No backup yet."

LIST_SEPARATOR = ", "
UNDO = "Undo"
REDO = "Redo"
UNDO_TOOLTIP = "{action}  (Ctrl+Z)"
REDO_TOOLTIP = "{action}  (Ctrl+Y)"
UNDO_NOTHING = "Nothing to undo"
REDO_NOTHING = "Nothing to redo"
UNDO_DONE = "Undone: {action}"
REDO_DONE = "Redone: {action}"
UNDO_FAILED = "This change can no longer be undone; its item was deleted or changed."
REDO_FAILED = "This change can no longer be redone."
UNDO_OFFER = "Done: {action}"

UNDO_TARGETS = {
    "episode": "episode",
    "season": "season",
    "voice": "audio idea",
    "idea": "text idea",
    "tag": "tag",
    "episode_note": "note",
    "timestamp_note": "timestamped note",
}
UNDO_ACTIONS = {
    "create": "Create {target} {quoted}",
    "delete": "Delete {target} {quoted}",
    "edit": "Edit {target} {quoted}",
    "rename": "Rename tag {other} to {quoted}",
    "status": "Change status of {target} {other} to {quoted}",
    "season": "Move {target} {other} to {quoted}",
    "tags_added": "Add tag {quoted} to {target}",
    "tags_removed": "Remove tag {quoted} from {target}",
    "linked": "Link {quoted} to {target}",
    "unlinked": "Unlink {quoted} from {target}",
    "recolor": "Recolour tag {quoted}",
    "reparent": "Move tag {quoted}",
    "merge": "Merge tag {quoted} into {other}",
    "archive": "Archive {target} {quoted}",
    "unarchive": "Unarchive {target} {quoted}",
    "trash": "Move {target} {quoted} to the trash",
}
UNDO_SOMETHING = "The last change"

# The Ideas page: audio and text ideas in one list, and its faceted search
IDEA_KINDS = {"all": "All", "audio": "Audio", "text": "Text"}
IDEA_KIND_TOOLTIP = "Which ideas: all, audio only or text only"
IDEA_NEW_TOOLTIP = "Write a new text idea  (Ctrl+N)"
VOICE_IMPORT_TOOLTIP = (
    "Add audio files as audio ideas  (Ctrl+O)\nYou can also drop files on this page."
)
IDEA_EMPTY = {
    "all": "No ideas yet. Write one with “Write idea”, or drop audio files here.",
    "audio": "No audio ideas yet. Drop files here or click “Add audio”.",
    "text": "No text ideas yet. Write the first one with “Write idea”.",
}
IDEA_ACTIVE_EMPTY = {
    "all": "No active ideas; the rest are archived (“All” or “Archived”).",
    "audio": "No active audio ideas; the rest are archived (“All” or “Archived”).",
    "text": "No active text ideas; the rest are archived (“All” or “Archived”).",
}
IDEA_ARCHIVED_EMPTY = {
    "all": "No archived ideas.",
    "audio": "No archived audio ideas.",
    "text": "No archived text ideas.",
}
IDEA_SEARCH_PLACEHOLDER = "Search ideas…"
IDEA_SEARCH_TOOLTIP = (
    "Searches idea titles and tags  (Ctrl+F)\n"
    "Enter keeps the phrase so you can add another; an idea must match them all.\n"
    '“"two words"” means side by side, and “#name” searches tags only.'
)
IDEA_PIN_HINT = "Enter: keep this phrase and add another"
IDEA_TAG_FILTER_PLACEHOLDER = "Filter by tag…"
IDEA_TAG_FILTER_TOOLTIP = "Only ideas carrying all of these tags; a tag's subtags count too"
CONTENT_SWITCH = "In content"
IDEA_CONTENT_TOOLTIP = "Also search the full text of text ideas and the transcripts of audio ideas"
PHRASE_REMOVE_TOOLTIP = "Remove this phrase"
FACETS_CLEAR = "Clear all"
FACETS_CLEAR_TOOLTIP = "Remove every search phrase and tag"
FACET_COUNT_KINDS = "{audio} audio · {text} text"
FACET_NO_MATCH = "No idea matches all of these.\nRemove one of the phrases or tags."
FACET_NO_MATCH_CONTENT = (
    "No idea matches all of these.\nRemove one of the phrases or tags, or turn on “In content”."
)

# Global search: titles unless the content is asked for, and a filter by kind
SEARCH_CONTENT_TOOLTIP = (
    "Also search the text of notes, ideas and transcripts; off: titles, names and tags only"
)
SEARCH_MORE_IN_CONTENT = "{n} more in content — show them"
SEARCH_KINDS = {"all": "All", "episode": "Episodes", "audio": "Audio", "text": "Text"}
SEARCH_KIND_TAB = "{label} {n}"
SEARCH_KIND_TOOLTIP = "Only one kind of result"
SEARCH_EMPTY_KIND = "Nothing of this kind; see “All”."
