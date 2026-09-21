"""All user-visible text, in one place.

The values written here are the Persian originals. `apply_language` swaps every name for
its English counterpart from `strings_en.py` once, at startup, before any widget is
built — so the rest of the UI keeps reading `strings.NAME` and never knows which language
it is showing. Changing the language therefore takes a restart.
"""

from podcast_workspace.domain.entities import EpisodeStatus
from podcast_workspace.domain.search import SearchKind

LANGUAGE = "fa"
RTL = True
# Formatting that differs between the languages as much as the words do.
QUOTE = "«{text}»"
DECIMAL_SEPARATOR = "٫"
DIRECTION_MARK = "\u200f"  # RLM: keeps the base direction of mixed Persian/Latin runs

APP_NAME = "فضای کاری پادکست"
STARTUP_ERROR_TITLE = "خطا در راه‌اندازی"
STARTUP_ERROR_BODY = "پایگاه داده باز نشد:\n{error}"

THEME_TO_DARK = "پوستهٔ تیره"
THEME_TO_LIGHT = "پوستهٔ روشن"
THEME_TOOLTIP = "تغییر پوسته (Ctrl+Shift+T)"
NAV_TOOLTIP = "{label} — {keys}"

NAV_EPISODES = "اپیزودها"
NAV_IDEAS = "ایده‌ها"
NAV_TAGS = "برچسب‌ها"

NAV_BACK = "بازگشت"
NAV_BACK_TO = "بازگشت به {page}"
NAV_BACK_TOOLTIP = "بازگشت به {page} — همان‌جایی که بودید  (Alt+←)"
NAV_BACK_NOTHING = "جایی برای بازگشت نیست  (Alt+←)"
SIDEBAR_COLLAPSE = "جمع کردن نوار کناری  (Ctrl+B)"
SIDEBAR_EXPAND = "باز کردن نوار کناری  (Ctrl+B)"

SEARCH_PLACEHOLDER = "جستجو…"
SEARCH_TOOLTIP = "جستجو در عنوان‌ها، نام‌ها و برچسب‌ها؛ متن‌ها هم با «در محتوا» (Ctrl+K)"
SEARCH_TITLE = "نتایج جستجو"
SEARCH_EMPTY = "چیزی پیدا نشد. بخشی از یک کلمه یا نام برچسب را امتحان کنید."
SEARCH_CORRECTED = "با اصلاح املایی: {pairs}"
SEARCH_VIA_TAG = "برچسب «{tag}»"
KIND_LABELS = {
    SearchKind.EPISODE: "اپیزود",
    SearchKind.IDEA_NOTE: "ایدهٔ متنی",
    SearchKind.EPISODE_NOTE: "یادداشت اپیزود",
    SearchKind.TIMESTAMP_NOTE: "یادداشت زمان‌دار",
    SearchKind.TAG: "برچسب",
    SearchKind.VOICE: "ایدهٔ صوتی",
    SearchKind.TRANSCRIPT: "رونوشت",
}
UNTITLED_NOTE = "یادداشت بی‌عنوان"

STATUS_LABELS = {
    EpisodeStatus.IDEA: "ایده",
    EpisodeStatus.OUTLINE: "طرح کلی",
    EpisodeStatus.RECORDED: "ضبط‌شده",
    EpisodeStatus.SCRIPT_READY: "متن آماده",
    EpisodeStatus.EDITED: "تدوین‌شده",
    EpisodeStatus.PUBLISHED: "منتشرشده",
}

EPISODES_TITLE = "اپیزودها"
EPISODE_NEW = "اپیزود تازه"
EPISODE_DEFAULT_TITLE = "اپیزود تازه"
EPISODE_TITLE_PLACEHOLDER = "عنوان اپیزود"
EPISODE_STATUS = "وضعیت"
EPISODE_NEXT_ACTION = "قدم بعدی"
EPISODE_NEXT_ACTION_PLACEHOLDER = "یک جمله: کار بعدی برای این اپیزود چیست؟"
EPISODE_EMPTY = "هنوز اپیزودی ندارید. با «اپیزود تازه» شروع کنید."
EPISODE_DELETE_CONFIRM = "اپیزود «{title}» حذف شود؟ ایده‌های صوتی و متنی پیوندشده حذف نمی‌شوند."
LIST_HIDE = "پنهان کردن فهرست — فضای بیشتر برای نوشتن  (Ctrl+L)"
LIST_SHOW = "نمایش فهرست اپیزودها  (Ctrl+L)"
EPISODE_DELETE = "حذف اپیزود"
EPISODE_MORE = "کارهای بیشتر"

SEASON_ALL = "همهٔ فصل‌ها"
SEASON_NONE = "بدون فصل"
SEASON_ITEM = "{title}  ({n})"
SEASON_LABEL = "فصل"
SEASON_FILTER_TOOLTIP = "نمایش اپیزودهای یک فصل"
SEASON_ACTIONS_TOOLTIP = "کارهای فصل"
SEASON_NEW = "فصل تازه…"
SEASON_NEW_TITLE = "فصل تازه"
SEASON_NAME_PROMPT = "نام فصل:"
SEASON_DEFAULT_TITLE = "فصل {n}"
SEASON_RENAME = "تغییر نام این فصل…"
SEASON_RENAME_TITLE = "تغییر نام فصل"
SEASON_DELETE = "حذف این فصل"
SEASON_DELETE_CONFIRM = "فصل «{title}» حذف شود؟ اپیزودهایش حذف نمی‌شوند؛ فقط بدون فصل می‌مانند."
SEASON_EMPTY = "این فصل هنوز اپیزودی ندارد. «اپیزود تازه» را بزنید تا در همین فصل ساخته شود."
SEASON_NONE_EMPTY = "همهٔ اپیزودها فصل دارند."

NAV_SOURCE = "پوشهٔ صوت"
SOURCE_TITLE = "پوشهٔ صوت"
SOURCE_CHOOSE = "پوشه…"
SOURCE_CHOOSE_TOOLTIP = "انتخاب پوشه‌ای که برنامهٔ ضبط فایل‌هایش را در آن ذخیره می‌کند"
SOURCE_DIALOG = "پوشهٔ فایل‌های صوتی"
SOURCE_FOLDER_MISSING = "این پوشه پیدا نشد: {path}"
SOURCE_NO_FOLDER = (
    "هنوز پوشه‌ای انتخاب نشده.\n"
    "«پوشه…» را بزنید و پوشه‌ای را که فایل‌های صوتی‌تان در آن ذخیره می‌شود انتخاب کنید. "
    "هر فایلی که آنجا باشد خودبه‌خود اینجا می‌آید تا گوشش کنید و اگر خواستید به فضای کاری بیاوریدش."
)
SOURCE_EMPTY = "فایل تازه‌ای در این پوشه نیست؛ همه‌چیز در فضای کاری است."
SOURCE_HINT = (
    "این فایل هنوز در فضای کاری نیست و چیزی از آن ذخیره نشده. "
    "بعد از افزودن می‌توانید برچسب و یادداشت بگذارید."
)
SOURCE_FILTER_PLACEHOLDER = "پالایش بر پایهٔ نام فایل…"
SOURCE_ADD = "افزودن به فضای کاری"
SOURCE_ADD_TOOLTIP = "به ایده‌های صوتی اضافه می‌شود؛ فایل سر جایش می‌ماند  (Ctrl+Enter)"
SOURCE_ADD_OPEN = "افزودن و باز کردن"
SOURCE_ADD_OPEN_TOOLTIP = "افزودن، و رفتن به ایده‌ها برای برچسب و یادداشت"
SOURCE_ADDING = "در حال افزودن…"
SOURCE_ADDED = "«{name}» به ایده‌های صوتی اضافه شد"
SOURCE_IN_SUBFOLDER = "در {folder}"
SIZE_MB = "{n} مگابایت"
SIZE_KB = "{n} کیلوبایت"

VOICE_IMPORT = "افزودن صوت"
VOICE_IMPORT_DIALOG = "انتخاب فایل‌های صوتی"
VOICE_IMPORT_FILTER = "فایل‌های صوتی ({patterns})"
VOICE_IMPORTING = "در حال وارد کردن…"
VOICE_IMPORT_DONE = "{imported} فایل وارد شد"
VOICE_IMPORT_DUP = "{n} فایل از قبل وجود داشت"
VOICE_IMPORT_UNSUPPORTED = "{n} فایل پشتیبانی نمی‌شود"
VOICE_IMPORT_FAILED = "{n} فایل خوانده نشد"
VOICE_MISSING = "فایل در این مسیر پیدا نشد."
VOICE_SHOW_IN_FOLDER = "نمایش در پوشه"
VOICE_DURATION_UNKNOWN = "مدت نامعلوم"
VOICE_PATH_TOOLTIP = "مسیر فایل — برای کپی کلیک کنید"
VOICE_PATH_COPIED = "مسیر کپی شد"
VOICE_NOTE_COUNT = "{n} یادداشت"

IDEAS_TITLE = "ایده‌ها"
IDEA_NEW = "نوشتن ایده"
IDEA_PLACEHOLDER = "ایده‌تان را بنویسید… (خودکار ذخیره می‌شود)"
IDEA_UNSAVED = "ایدهٔ متنی تازه (هنوز ذخیره نشده)"

# Archive and trash (domain/lifecycle.py)
ARCHIVE_SCOPES = {
    "active": "فعال",
    "all": "همه",
    "archived": "بایگانی",
}
ARCHIVE_SCOPE_TOOLTIP = "کدام‌ها نشان داده شوند: فعال‌ها، همه، یا فقط بایگانی‌شده‌ها"
SEARCH_SCOPE_TOOLTIP = "بایگانی‌شده‌ها فقط وقتی جستجو می‌شوند که «همه» یا «بایگانی» را انتخاب کنید"
ARCHIVE = "بایگانی"
UNARCHIVE = "خروج از بایگانی"
ARCHIVE_TOOLTIP = "از فهرست فعال و جستجوی معمول کنار می‌رود؛ برچسب‌ها و پیوندهایش می‌مانند"
UNARCHIVE_TOOLTIP = "به فهرست فعال برمی‌گردد"
ARCHIVED_BADGE = "بایگانی‌شده"
ARCHIVED_NOTE = "بایگانی‌شده — در فهرست فعال و جستجوی معمول نمی‌آید"
MOVE_TO_TRASH = "انتقال به سطل زباله"
MOVE_TO_TRASH_TOOLTIP = "تا {days} روز در سطل زباله می‌ماند و از آنجا برمی‌گردد  (Delete)"

NAV_TRASH = "سطل زباله"
TRASH_TITLE = "سطل زباله"
TRASH_HINT = (
    "موارد حذف‌شده {days} روز اینجا می‌مانند و بعد برای همیشه پاک می‌شوند. "
    "تا آن وقت در هیچ فهرست و جستجویی نمی‌آیند و همه‌چیزشان محفوظ است."
)
TRASH_EMPTY = "سطل زباله خالی است."
TRASH_FILTER_PLACEHOLDER = "جستجو در سطل زباله…"
TRASH_FILTER_TOOLTIP = "جستجو در متن، نام و برچسب موارد حذف‌شده  (Ctrl+F)"
TRASH_KINDS = {
    "all": "همه",
    "voice": "صوتی",
    "idea": "متنی",
}
TRASH_RESTORE = "بازیابی"
TRASH_RESTORE_TOOLTIP = "برگرداندن موارد انتخاب‌شده به جای قبلی‌شان  (Enter)"
TRASH_RESTORE_ALL = "بازیابی همه"
TRASH_PURGE = "حذف برای همیشه"
TRASH_PURGE_TOOLTIP = "پاک کردن موارد انتخاب‌شده، بی‌بازگشت  (Delete)"
TRASH_EMPTY_ALL = "خالی کردن سطل زباله"
TRASH_SELECT_ALL = "انتخاب همه"
TRASH_SELECT_ALL_TOOLTIP = "انتخاب همهٔ موارد این فهرست  (Ctrl+A)"
TRASH_SELECTED = "{n} مورد انتخاب شده"
TRASH_PURGE_CONFIRM = (
    "{n} مورد برای همیشه پاک شود؟ برچسب‌گذاری‌ها، یادداشت‌ها، رونوشت و پیوندهایشان هم "
    "پاک می‌شود و این کار بازگشت ندارد. فایل‌های صوتی روی دیسک می‌مانند."
)
TRASH_EMPTY_CONFIRM = (
    "همهٔ {n} مورد سطل زباله برای همیشه پاک شود؟ این کار بازگشت ندارد. "
    "فایل‌های صوتی روی دیسک می‌مانند."
)
TRASH_RESTORE_ALL_CONFIRM = "همهٔ {n} مورد سطل زباله بازیابی شود؟"
TRASH_RESTORED = "{n} مورد بازیابی شد"
TRASH_PURGED = "{n} مورد برای همیشه پاک شد"
TRASH_AUTO_PURGED = "{n} مورد که {days} روز در سطل زباله بود برای همیشه پاک شد"
TRASH_DAYS_LEFT = "{n} روز تا پاک شدن"
TRASH_DELETED_AT = "حذف‌شده در {when}"
TRASH_FROM_ARCHIVE = "به بایگانی برمی‌گردد"
TRASH_PREVIEW_EMPTY = "یک مورد را انتخاب کنید تا محتوایش را ببینید."
TRASH_PREVIEW_MANY = "{n} مورد انتخاب شده. «بازیابی» یا «حذف برای همیشه» روی همهٔ آن‌ها اعمال می‌شود."
TRASH_VOICE_HINT = "برای شنیدن و ویرایش، اول بازیابی کنید."

TAGS_TITLE = "برچسب‌ها"
TAG_NEW = "برچسب تازه"
TAG_FILTER_PLACEHOLDER = "پیدا کردن برچسب…"
TAG_FILTER_TOOLTIP = "پیدا کردن برچسب در همین فهرست  (Ctrl+F)"
TAG_RENAME = "تغییر نام"
TAG_RECOLOR = "تغییر رنگ"
TAG_MERGE = "ادغام در…"
TAG_DELETE = "حذف"
TAG_EMPTY = "هنوز برچسبی ندارید. برچسب‌ها را هنگام کار با اپیزودها و ایده‌ها هم می‌توانید بسازید."
TAG_USAGE_HEADER = "کاربرد"
TAG_ACTIONS = "کارها"
TAG_ACTIONS_TOOLTIP = "کارهای این برچسب"
TAG_USES_TITLE = "کجا به کار رفته"
TAG_USES_EMPTY = "هنوز جایی از این برچسب استفاده نشده."
TAG_USES_NONE = "یک برچسب را انتخاب کنید تا موردهایش اینجا بیاید."
TAG_USES_COUNT = "{n} مورد"
TAG_OPEN_ITEM = "باز کردن (Enter)"
TAG_NAME_HEADER = "نام"
TAG_DELETE_CONFIRM = "برچسب «{name}» حذف شود؟ از {n} مورد برداشته می‌شود."
TAG_MERGE_CONFIRM = "همهٔ کاربردهای «{source}» به «{target}» منتقل و «{source}» حذف شود؟"
TAG_MERGE_TITLE = "ادغام «{name}» در…"
TAG_NEW_TITLE = "برچسب تازه"
TAG_NAME_PLACEHOLDER = "نام برچسب"
TAG_SIMILAR_HINT = "برچسب‌های مشابه موجود — شاید یکی از این‌ها همان باشد:"
TAG_EXACT_EXISTS = "برچسب «{name}» از قبل وجود دارد."
TAG_CREATE = "ایجاد"
TAG_CREATE_ANYWAY = "ایجاد با وجود مشابه"
TAG_PICK = "انتخاب"

TAG_INPUT_PLACEHOLDER = "افزودن برچسب…"
TAG_INPUT_COUNT = "{n} از {limit}"
TAG_INPUT_FULL = "سقف {limit} برچسب پر شده است"
TAG_INPUT_CREATE = "ایجاد برچسب تازهٔ «{name}»"
TAG_INPUT_CREATE_SIMILAR = "ایجاد برچسب تازهٔ «{name}» — مشابهِ «{similar}» وجود دارد"
TAG_REMOVE_TOOLTIP = "برداشتن برچسب"
TAG_LABEL = "برچسب‌ها"

FILTER_TOOLTIP = "پالایش همین فهرست بر پایهٔ عنوان و برچسب  (Ctrl+F)\n«#نام» فقط برچسب را می‌گردد"
FILTER_COUNT = "{shown} از {total}"
FILTER_COUNT_TOOLTIP = "{shown} مورد از {total} مورد نشان داده می‌شود"
FILTER_NO_MATCH = (
    "هیچ موردی با «{query}» جور در نیامد.\n"
    "بخشی از یک کلمه را امتحان کنید، یا با «#» نام برچسب را بنویسید."
)
FILTER_CLEAR = "پاک کردن پالایه (Esc)"
EPISODE_FILTER_PLACEHOLDER = "پالایش اپیزودها بر پایهٔ عنوان یا برچسب…"

CANCEL = "انصراف"
DELETE = "حذف"
CONFIRM_TITLE = "تأیید"
ERROR_TITLE = "خطا"
CREATED_AT = "ایجاد: {when}"
UPDATED_AT = "آخرین تغییر: {when}"
IMPORTED_AT = "واردشده: {when}"
SELECT_SOMETHING = "یک مورد را از فهرست انتخاب کنید."

ERR_TAG_LIMIT = "هر مورد حداکثر {limit} برچسب می‌تواند داشته باشد."
ERR_DUPLICATE_TAG = "برچسب «{name}» از قبل وجود دارد."
ERR_NEAR_DUPLICATE = "برچسب‌های مشابه وجود دارد: {names}"
ERR_VALIDATION = "مقدار واردشده معتبر نیست (مثلاً نباید خالی باشد)."
ERR_NOT_FOUND = "این مورد دیگر وجود ندارد."
ERR_UNEXPECTED = "خطای غیرمنتظره: {error}"

PLAYER_PLAY_TOOLTIP = "پخش (Space)"
PLAYER_PAUSE_TOOLTIP = "توقف (Space)"
PLAYER_BACK_TOOLTIP = "۱۰ ثانیه عقب (←)"
PLAYER_FORWARD_TOOLTIP = "۱۰ ثانیه جلو (→)"
PLAYER_SPEED_TOOLTIP = "سرعت پخش (- و =)"
PLAYER_LOADING = "در حال خواندن فایل…"
PLAYER_ERROR = "پخش ممکن نشد: {error}"

TS_TITLE = "یادداشت‌های زمان‌دار"
TS_COUNT = "{n} یادداشت"
TS_PLACEHOLDER = "یادداشت در همین لحظه…  (Insert)"
TS_ADD = "افزودن"
TS_CAPTURE_TOOLTIP = "زمان یادداشت؛ برای گرفتن لحظهٔ فعلی کلیک کنید"
TS_GOTO_TOOLTIP = "رفتن به این لحظه (Enter)"
TS_EMPTY = "هنوز یادداشتی برای این صوت نیست. هنگام پخش Insert را بزنید و بنویسید."
TS_EDIT = "ویرایش (F2)"
TS_DELETE = "حذف (Delete)"
TS_DELETE_CONFIRM = "یادداشت «{text}» حذف شود؟"

NAV_BOARD = "تابلو"
BOARD_TITLE = "تابلوی تولید"
BOARD_COLUMN_COUNT = "{n}"
BOARD_HINT = "کارت‌ها را بین ستون‌ها بکشید یا Ctrl+←/→ بزنید؛ Enter باز می‌کند"
BOARD_EMPTY = "هنوز اپیزودی ندارید. با «اپیزود تازه» شروع کنید؛ بعد کارت‌ها را بین ستون‌ها بکشید."
STALE_BADGE = "راکد: {days} روز"
STALE_TOOLTIP = "بیش از ۱۰ روز است که این اپیزود دست نخورده"

WS_NOTES = "یادداشت‌ها"
WS_NOTE_NEW = "یادداشت تازه"
WS_NOTE_TITLE_PLACEHOLDER = "عنوان یادداشت (اختیاری)"
WS_NOTE_BODY_PLACEHOLDER = "بنویسید… (خودکار ذخیره می‌شود)"
WS_NOTES_EMPTY = "این اپیزود هنوز یادداشتی ندارد. با «یادداشت تازه» (Ctrl+N) شروع کنید."
WS_NOTE_DELETE = "حذف یادداشت"
WS_NOTE_DELETE_CONFIRM = "یادداشت «{title}» حذف شود؟"
WS_LINK_ADD = "افزودن…"
WS_LINKED_EMPTY = "—"
WS_VOICES_EMPTY = (
    "هنوز ایدهٔ صوتی‌ای به این اپیزود پیوند نخورده. "
    "«افزودن…» را بزنید یا از تب پیشنهادها انتخاب کنید."
)
WS_IDEAS_EMPTY = (
    "هنوز ایدهٔ متنی‌ای به این اپیزود پیوند نخورده. "
    "«افزودن…» را بزنید یا از تب پیشنهادها انتخاب کنید."
)
WS_UNLINK = "برداشتن پیوند (Delete)"
WS_OPEN = "باز کردن (Enter)"
WS_MATERIALS = "مواد اپیزود"
WS_TAB_VOICES = "صوتی"
WS_TAB_IDEAS = "متنی"
WS_TAB_SMART = "پیشنهادها"
WS_TAB_COUNT = "{label} {n}"
WS_SMART = "پیشنهادهای هم‌برچسب"
WS_SMART_NO_TAGS = "به اپیزود برچسب بدهید تا ایده‌های صوتی و متنی هم‌برچسب اینجا بیایند."
WS_SMART_NONE = "ایده‌ای با برچسب مشترک پیدا نشد."
WS_SMART_SUBTITLE = "{kind}، {n} برچسب مشترک: {names}"
WS_SMART_LINKED = "پیوندشده ✓"
WS_LINK = "پیوند دادن"
WS_UNLINK_SHORT = "برداشتن پیوند"
WS_RECORD = "ضبط"
WS_RECORD_TOOLTIP = "اجرای برنامهٔ ضبط شما — از هر جای برنامه (Ctrl+R)"
WS_PICK_VOICE = "افزودن ایدهٔ صوتی به اپیزود"
WS_PICK_IDEA = "افزودن ایدهٔ متنی به اپیزود"
WS_PICK_FILTER = "فیلتر…"
WS_PICK_ADD = "افزودن"
WS_PICK_EMPTY = "موردی برای افزودن نیست."
KIND_VOICE = "ایدهٔ صوتی"
KIND_IDEA = "ایدهٔ متنی"

RESUME_EYEBROW = "ادامهٔ کار"
RESUME_NEXT_ACTION = "قدم بعدی"
RESUME_NO_NEXT = "قدم بعدی هنوز تعیین نشده."
RESUME_LAST_NOTE = "آخرین یادداشت"
RESUME_NO_NOTE = "هنوز یادداشتی ندارد."
RESUME_CONTINUE = "ادامه"
RESUME_SKIP = "همهٔ اپیزودها (Esc)"

INBOX_TITLE = "ایدهٔ متنی تازه"
INBOX_PLACEHOLDER = "ایده را بنویسید…"
INBOX_HINT = "Enter ذخیره · Shift+Enter خط تازه · Esc بستن"

SETTINGS = "تنظیمات"
SETTINGS_TOOLTIP = "تنظیمات (Ctrl+,)"
SETTINGS_RECORDER = "برنامهٔ ضبط"
SETTINGS_RECORDER_HINT = (
    "مسیر برنامه‌ای که با آن ضبط می‌کنید. دکمهٔ «ضبط» همان را اجرا می‌کند؛ "
    "این اپلیکیشن خودش صدا ضبط نمی‌کند."
)
SETTINGS_BROWSE = "انتخاب…"
SETTINGS_PROGRAM_DIALOG = "انتخاب برنامهٔ ضبط"
SETTINGS_PROGRAM_FILTER = "برنامه‌ها (*.exe *.lnk *.bat *.cmd);;همهٔ فایل‌ها (*)"
SETTINGS_HOTKEY = "میانبر سراسری ایده"
SETTINGS_HOTKEY_OK = "{keys} — در هر برنامه‌ای یک پنجرهٔ کوچک برای ثبت ایده باز می‌کند."
SETTINGS_HOTKEY_FAIL = "{keys} در دسترس نیست؛ برنامهٔ دیگری آن را گرفته است."
SAVE = "ذخیره"
RECORDER_MISSING = "برنامهٔ ضبط در این مسیر پیدا نشد:\n{path}"

SETTINGS_TAB_GENERAL = "عمومی"
SETTINGS_TAB_BOT = "بازوی بله"
SETTINGS_TAB_TRANSCRIPTION = "رونویسی"
SETTINGS_TAB_DATA = "داده‌ها"

BOT_ENABLE = "دریافت ایدهٔ متنی و صوتی از بازوی بله"
BOT_TOKEN = "توکن بازو"
BOT_TOKEN_PLACEHOLDER = "توکنی که @botfather در بله داده است"
BOT_TOKEN_SHOW = "نمایش"
BOT_TOKEN_CHECK = "آزمایش توکن"
BOT_TOKEN_CHECKING = "در حال بررسی…"
BOT_TOKEN_OK = "توکن معتبر است: {name}"
BOT_TOKEN_BAD = "توکن پذیرفته نشد."
BOT_TOKEN_OFFLINE = "اتصال به بله ممکن نشد؛ اینترنت را بررسی کنید."
BOT_HELP = (
    "در بله به ‎@botfather‎ پیام دهید، یک بازو بسازید و توکنش را اینجا بگذارید. "
    "هر پیام متنی به بازو یک ایدهٔ متنی و هر پیام صوتی یک ایدهٔ صوتی در این فضای کاری می‌شود؛ "
    "پیام‌هایی که وقتی برنامه بسته است می‌فرستید، با باز شدن برنامه دریافت می‌شوند."
)
BOT_OWNER = "صاحب بازو: {name}"
BOT_OWNER_NONE = "هنوز کسی به بازو پیام نداده؛ اولین گفت‌وگوی خصوصی صاحب آن می‌شود."
BOT_OWNER_RESET = "آزاد کردن"
BOT_STATUS = {
    "stopped": "خاموش",
    "connecting": "در حال اتصال…",
    "online": "متصل",
    "offline": "بدون اتصال؛ دوباره تلاش می‌کند",
    "unauthorized": "توکن پذیرفته نشد",
}
BOT_SIDEBAR = "بله: {status}"
BOT_RECEIVED_IDEA = "ایدهٔ متنی تازه از بله رسید"
BOT_RECEIVED_VOICE = "ایدهٔ صوتی تازه از بله رسید"

TR_TAB_NOTES = "یادداشت‌ها"
TR_TAB_TRANSCRIPT = "رونوشت"
TR_RUN = "رونویسی"
TR_RERUN = "رونویسی دوباره"
TR_RUN_TOOLTIP = "تبدیل گفتار این صوت به متن فارسی، بدون اینترنت"
TR_CANCEL = "لغو"
TR_COPY = "کپی متن"
TR_COPIED = "متن کپی شد"
TR_EMPTY = "هنوز رونوشتی نیست. «رونویسی» گفتار این صوت را روی همین رایانه به متن تبدیل می‌کند."
TR_NO_SPEECH = "گفتاری در این صوت پیدا نشد."
TR_RUNNING = "در حال رونویسی… {percent}٪"
TR_LOADING_MODEL = "در حال آماده‌سازی مدل…"
TR_BUSY_ELSEWHERE = "رونویسی صوت دیگری در جریان است."
TR_QUEUED = "این صوت در صف «رونویسی همه» است."
TR_ALL = "رونویسی همه"
TR_ALL_STOP = "توقف رونویسی همه"
TR_ALL_TOOLTIP = "ایده‌های صوتیِ بی‌رونوشتِ این فهرست را در صف می‌گذارد و یکی‌یکی رونویسی می‌کند"
TR_ALL_NONE = "همهٔ ایده‌های صوتی این فهرست رونوشت دارند."
TR_ALL_CONFIRM = (
    "{n} ایدهٔ صوتی رونوشت ندارد. یکی‌یکی و پشت صحنه رونویسی شوند؟\n"
    "بسته به طول صوت‌ها ممکن است زمان زیادی ببرد؛ در این مدت می‌توانید با برنامه کار کنید."
)
TR_ALL_START = "شروع رونویسی"
TR_ALL_DONE = "رونویسی همه تمام شد: {ok} از {total} ایدهٔ صوتی رونویسی شد."
TR_ALL_STOPPED = "رونویسی همه متوقف شد: {ok} از {total} ایدهٔ صوتی رونویسی شد."
TR_ALL_SIDEBAR = "رونویسی همه: {n} از {total}"
TR_ALL_SIDEBAR_PERCENT = "رونویسی همه: {n} از {total}  ·  {percent}٪"
TR_META = "{n} بخش، {model}، {when}"
TR_NOT_INSTALLED = "بستهٔ faster-whisper نصب نیست؛ نصب با: ⁦pip install .[transcription]⁩"
TR_MODEL_MISSING = "مدل رونویسی هنوز روی این رایانه نیست. از تنظیمات ← رونویسی دریافتش کنید."
TR_OPEN_SETTINGS = "تنظیمات رونویسی"
TR_FAILED = "رونویسی ممکن نشد: {error}"
TR_FILE_MISSING = "فایل صوتی پیدا نشد."
TR_REPLACE_CONFIRM = "رونوشت فعلی با نتیجهٔ تازه جایگزین شود؟"
TR_REPLACE = "جایگزین کن"
TR_GOTO_TOOLTIP = "رفتن به این لحظه (Enter)"
VOICE_HAS_TRANSCRIPT = "رونوشت"

TR_MODEL = "مدل"
TR_MODELS = {
    "small": "small — سریع، دقت کم (حدود ۵۰۰ مگابایت)",
    "medium": "medium — متوسط (حدود ۱٫۵ گیگابایت)",
    "large-v3-turbo": "large-v3-turbo — پیشنهادی (حدود ۱٫۶ گیگابایت)",
    "large-v3": "large-v3 — دقیق‌ترین و کندترین (حدود ۳ گیگابایت)",
}
TR_MODEL_READY = "مدل آماده است: {path}"
TR_MODEL_NOT_READY = "این مدل هنوز دریافت نشده."
TR_MODEL_DOWNLOAD = "دریافت مدل"
TR_MODEL_DOWNLOADING = "در حال دریافت مدل… (یک بار؛ ممکن است طول بکشد)"
TR_MODEL_DOWNLOAD_FAILED = "دریافت مدل ممکن نشد: {error}"
TR_MODEL_DIR = "پوشهٔ مدل دلخواه (اختیاری)"
TR_MODEL_DIR_PLACEHOLDER = "پوشه‌ای که model.bin دارد؛ خالی = مدل دریافت‌شده"
TR_MODEL_DIR_DIALOG = "انتخاب پوشهٔ مدل faster-whisper"
TR_MODEL_HELP = (
    "رونویسی کاملاً روی همین رایانه انجام می‌شود. فقط دریافت مدل، یک بار، به اینترنت نیاز دارد."
)

DATA_EXPORT = "خروجی گرفتن…"
DATA_EXPORT_HELP = (
    "همهٔ اپیزودها، ایده‌ها، یادداشت‌ها، برچسب‌ها، رونوشت‌ها و فایل‌های صوتی در یک فایل zip. "
    "تنظیمات (از جمله توکن بازو) در خروجی نیست."
)
DATA_EXPORT_DIALOG = "ذخیرهٔ خروجی"
DATA_EXPORT_FILTER = "خروجی فضای کاری (*.zip)"
DATA_EXPORTING = "در حال خروجی گرفتن… {percent}٪"
DATA_EXPORT_DONE = "خروجی ذخیره شد: {path}"
DATA_EXPORT_MISSING = "{n} فایل صوتی پیدا نشد و در خروجی نیست."
DATA_IMPORT = "بازگردانی از خروجی…"
DATA_IMPORT_HELP = (
    "همهٔ داده‌های فعلی با محتوای فایل جایگزین می‌شود. پیش از آن، یک نسخهٔ پشتیبان "
    "از وضعیت فعلی در پوشهٔ backups ذخیره می‌شود."
)
DATA_IMPORT_DIALOG = "انتخاب فایل خروجی"
DATA_IMPORT_CONFIRM = (
    "همهٔ اپیزودها، ایده‌ها (صوتی و متنی) و برچسب‌های فعلی با محتوای این فایل جایگزین شود؟\n"
    "نسخهٔ پشتیبانی از وضعیت فعلی در پوشهٔ backups ذخیره می‌شود."
)
DATA_IMPORT_ACTION = "جایگزین کن"
DATA_IMPORTING = "در حال بازگردانی… {percent}٪"
DATA_IMPORT_DONE = (
    "بازگردانی شد: {episodes} اپیزود، {voices} ایدهٔ صوتی، {ideas} ایدهٔ متنی، {tags} برچسب."
)
DATA_IMPORT_BAD_FILE = "این فایل خروجیِ این برنامه نیست یا خراب است."
DATA_FOLDER = "پوشهٔ داده‌ها"
DATA_OPEN_FOLDER = "باز کردن پوشه"

SETTINGS_LANGUAGE = "زبان برنامه"
LANGUAGE_NAMES = {"fa": "فارسی", "en": "English"}
LANGUAGE_RESTART_TITLE = "تغییر زبان"
LANGUAGE_RESTART = (
    "زبان تازه پس از راه‌اندازی دوبارهٔ برنامه اعمال می‌شود. همین حالا دوباره راه‌اندازی شود؟"
)
LANGUAGE_RESTART_NOW = "راه‌اندازی دوباره"
LANGUAGE_RESTART_LATER = "بعداً"

BACKUP_REMINDER_TITLE = "یادآوری پشتیبان‌گیری"
BACKUP_REMINDER_BODY = "{days} روز از آخرین پشتیبان‌گیری گذشته است."
BACKUP_REMINDER_NEVER = "هنوز هیچ پشتیبانی از داده‌هایتان نگرفته‌اید."
BACKUP_REMINDER_HINT = (
    "یک فایل خروجی همهٔ اپیزودها، یادداشت‌ها و ایده‌های صوتی و متنی را نگه می‌دارد. "
    "بهتر است آن را روی دیسک یا فضای ابری دیگری نگه دارید."
)
BACKUP_NOW = "پشتیبان‌گیری الان"
BACKUP_TOMORROW = "فردا یادآوری کن"
BACKUP_LATER = "بعداً"
SETTINGS_BACKUP_REMINDER = "یادآوری پشتیبان‌گیری"
BACKUP_INTERVALS = {
    0: "خاموش",
    3: "هر ۳ روز",
    7: "هر هفته",
    14: "هر دو هفته",
    30: "هر ماه",
}
BACKUP_LAST = "آخرین پشتیبان: {when}"
BACKUP_LAST_NEVER = "هنوز پشتیبانی گرفته نشده."

# Undo / redo. The history stores what happened as data (services/history.py); the
# phrases live here. `{quoted}` is what the change names (a tag, a title), `{other}` a
# second name the phrase needs, and both already carry their guillemets or are empty.
LIST_SEPARATOR = "، "
UNDO = "بازگردانی"
REDO = "انجام دوباره"
UNDO_TOOLTIP = "{action}  (Ctrl+Z)"
REDO_TOOLTIP = "{action}  (Ctrl+Y)"
UNDO_NOTHING = "چیزی برای بازگردانی نیست"
REDO_NOTHING = "چیزی برای انجام دوباره نیست"
UNDO_DONE = "بازگردانی شد: {action}"
REDO_DONE = "دوباره انجام شد: {action}"
UNDO_FAILED = "بازگردانی این تغییر دیگر ممکن نیست؛ موردش حذف شده یا عوض شده است."
REDO_FAILED = "انجام دوبارهٔ این تغییر دیگر ممکن نیست."
UNDO_OFFER = "{action} انجام شد"

UNDO_TARGETS = {
    "episode": "اپیزود",
    "season": "فصل",
    "voice": "ایدهٔ صوتی",
    "idea": "ایدهٔ متنی",
    "tag": "برچسب",
    "episode_note": "یادداشت",
    "timestamp_note": "یادداشت زمان‌دار",
}
UNDO_ACTIONS = {
    "create": "ساختن {target} {quoted}",
    "delete": "حذف {target} {quoted}",
    "edit": "ویرایش {target} {quoted}",
    "rename": "تغییر نام برچسب {other} به {quoted}",
    "status": "تغییر وضعیت {target} {other} به {quoted}",
    "season": "انتقال {target} {other} به {quoted}",
    "tags_added": "افزودن برچسب {quoted} به {target}",
    "tags_removed": "برداشتن برچسب {quoted} از {target}",
    "linked": "پیوند {quoted} به {target}",
    "unlinked": "برداشتن پیوند {quoted} از {target}",
    "recolor": "تغییر رنگ برچسب {quoted}",
    "merge": "ادغام برچسب {quoted} در {other}",
    "archive": "بایگانی {target} {quoted}",
    "unarchive": "خروج {target} {quoted} از بایگانی",
    "trash": "انتقال {target} {quoted} به سطل زباله",
}
UNDO_SOMETHING = "آخرین تغییر"

# The Ideas page: audio and text ideas in one list, and its faceted search
IDEA_KINDS = {"all": "همه", "audio": "صوتی", "text": "متنی"}
IDEA_KIND_TOOLTIP = "کدام ایده‌ها: همه، فقط صوتی‌ها یا فقط متنی‌ها"
IDEA_NEW_TOOLTIP = "نوشتن ایدهٔ متنی تازه  (Ctrl+N)"
VOICE_IMPORT_TOOLTIP = (
    "افزودن فایل صوتی به‌عنوان ایدهٔ صوتی  (Ctrl+O)\nفایل‌ها را روی همین صفحه هم می‌شود کشید."
)
IDEA_EMPTY = {
    "all": "هنوز ایده‌ای نیست. با «نوشتن ایده» بنویسید، یا فایل صوتی را اینجا بکشید.",
    "audio": "هنوز ایدهٔ صوتی‌ای نیست. فایل‌ها را اینجا بکشید یا «افزودن صوت» را بزنید.",
    "text": "هنوز ایدهٔ متنی‌ای نیست. با «نوشتن ایده» اولین را بنویسید.",
}
IDEA_ACTIVE_EMPTY = {
    "all": "ایدهٔ فعالی نیست؛ بقیه بایگانی شده‌اند («همه» یا «بایگانی»).",
    "audio": "ایدهٔ صوتی فعالی نیست؛ بقیه بایگانی شده‌اند («همه» یا «بایگانی»).",
    "text": "ایدهٔ متنی فعالی نیست؛ بقیه بایگانی شده‌اند («همه» یا «بایگانی»).",
}
IDEA_ARCHIVED_EMPTY = {
    "all": "ایدهٔ بایگانی‌شده‌ای نیست.",
    "audio": "ایدهٔ صوتی بایگانی‌شده‌ای نیست.",
    "text": "ایدهٔ متنی بایگانی‌شده‌ای نیست.",
}
IDEA_SEARCH_PLACEHOLDER = "جستجو در ایده‌ها…"
IDEA_SEARCH_TOOLTIP = (
    "عنوان و برچسب ایده‌ها را می‌گردد  (Ctrl+F)\n"
    "Enter عبارت را نگه می‌دارد تا عبارت بعدی را هم اضافه کنید؛ هر ایده باید همه را داشته باشد.\n"
    '«"دو کلمه"» یعنی کنار هم، و «#نام» فقط برچسب‌ها را می‌گردد.'
)
IDEA_PIN_HINT = "Enter: نگه‌داشتن این عبارت و افزودن عبارت بعدی"
IDEA_TAG_FILTER_PLACEHOLDER = "پالایش با برچسب…"
IDEA_TAG_FILTER_TOOLTIP = "فقط ایده‌هایی که همهٔ این برچسب‌ها را دارند"
CONTENT_SWITCH = "در محتوا"
IDEA_CONTENT_TOOLTIP = "متن کامل ایده‌های متنی و رونوشت ایده‌های صوتی هم جستجو شود"
PHRASE_REMOVE_TOOLTIP = "برداشتن این عبارت"
FACETS_CLEAR = "پاک کردن همه"
FACETS_CLEAR_TOOLTIP = "برداشتن همهٔ عبارت‌ها و برچسب‌های جستجو"
FACET_COUNT_KINDS = "{audio} صوتی · {text} متنی"
FACET_NO_MATCH = "هیچ ایده‌ای با همهٔ این شرط‌ها جور در نیامد.\nیکی از عبارت‌ها یا برچسب‌ها را بردارید."
FACET_NO_MATCH_CONTENT = (
    "هیچ ایده‌ای با همهٔ این شرط‌ها جور در نیامد.\n"
    "یکی از عبارت‌ها یا برچسب‌ها را بردارید، یا «در محتوا» را روشن کنید."
)

# Global search: titles unless the content is asked for, and a filter by kind
SEARCH_CONTENT_TOOLTIP = (
    "متن یادداشت‌ها، ایده‌ها و رونوشت‌ها هم جستجو شود؛ خاموش: فقط عنوان‌ها، نام‌ها و برچسب‌ها"
)
SEARCH_MORE_IN_CONTENT = "{n} نتیجهٔ دیگر در محتوا — نشان بده"
SEARCH_KINDS = {"all": "همه", "episode": "اپیزود", "audio": "صوتی", "text": "متنی"}
SEARCH_KIND_TAB = "{label} {n}"
SEARCH_KIND_TOOLTIP = "فقط یک نوع از نتایج"
SEARCH_EMPTY_KIND = "در این دسته نتیجه‌ای نیست؛ «همه» را ببینید."


def apply_language(language: str) -> None:
    """Replace every text above with the chosen language's. Call once, before any UI.

    Persian is what this module holds already, so only English has anything to do.
    """
    if language != "en":
        return
    from podcast_workspace.ui import strings_en

    names = {name: value for name, value in vars(strings_en).items() if name.isupper()}
    globals().update(names)
