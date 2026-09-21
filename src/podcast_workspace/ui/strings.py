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
THEME_TOOLTIP = "تغییر پوسته (Ctrl+T)"
NAV_TOOLTIP = "{label} — {keys}"

NAV_EPISODES = "اپیزودها"
NAV_VOICES = "صداها"
NAV_IDEAS = "ایده‌ها"
NAV_TAGS = "برچسب‌ها"

NAV_BACK = "بازگشت"
NAV_BACK_TO = "بازگشت به {page}"
NAV_BACK_TOOLTIP = "بازگشت به {page} — همان‌جایی که بودید  (Alt+←)"
NAV_BACK_NOTHING = "جایی برای بازگشت نیست  (Alt+←)"
SIDEBAR_COLLAPSE = "جمع کردن نوار کناری  (Ctrl+B)"
SIDEBAR_EXPAND = "باز کردن نوار کناری  (Ctrl+B)"

SEARCH_PLACEHOLDER = "جستجو…"
SEARCH_TOOLTIP = "جستجو در عنوان‌ها، یادداشت‌ها، رونوشت‌ها و برچسب‌ها (Ctrl+K)"
SEARCH_TITLE = "نتایج جستجو"
SEARCH_EMPTY = "چیزی پیدا نشد. بخشی از یک کلمه یا نام برچسب را امتحان کنید."
SEARCH_CORRECTED = "با اصلاح املایی: {pairs}"
SEARCH_VIA_TAG = "برچسب «{tag}»"
SEARCH_COUNT = "{n} نتیجه"
KIND_LABELS = {
    SearchKind.EPISODE: "اپیزود",
    SearchKind.IDEA_NOTE: "ایده",
    SearchKind.EPISODE_NOTE: "یادداشت اپیزود",
    SearchKind.TIMESTAMP_NOTE: "یادداشت زمان‌دار",
    SearchKind.TAG: "برچسب",
    SearchKind.VOICE: "صدا",
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
EPISODE_DELETE_CONFIRM = "اپیزود «{title}» حذف شود؟ صداها و ایده‌های پیوندشده حذف نمی‌شوند."
LIST_HIDE = "پنهان کردن فهرست — فضای بیشتر برای نوشتن  (Ctrl+L)"
LIST_SHOW = "نمایش فهرست اپیزودها  (Ctrl+L)"
EPISODE_DELETE = "حذف اپیزود"
EPISODE_MORE = "کارهای بیشتر"

VOICES_TITLE = "صداها"
VOICE_IMPORT = "وارد کردن صدا"
VOICE_IMPORT_DIALOG = "انتخاب فایل‌های صوتی"
VOICE_IMPORT_FILTER = "فایل‌های صوتی ({patterns})"
VOICE_IMPORTING = "در حال وارد کردن…"
VOICE_IMPORT_DONE = "{imported} فایل وارد شد"
VOICE_IMPORT_DUP = "{n} فایل از قبل وجود داشت"
VOICE_IMPORT_UNSUPPORTED = "{n} فایل پشتیبانی نمی‌شود"
VOICE_IMPORT_FAILED = "{n} فایل خوانده نشد"
VOICE_EMPTY = "هنوز صدایی وارد نکرده‌اید. فایل‌ها را اینجا بکشید یا «وارد کردن صدا» را بزنید."
VOICE_MISSING = "فایل در این مسیر پیدا نشد."
VOICE_SHOW_IN_FOLDER = "نمایش در پوشه"
VOICE_DELETE = "حذف از فضای کاری"
VOICE_DELETE_CONFIRM = "«{name}» از فضای کاری حذف شود؟ فایل صوتی روی دیسک باقی می‌ماند."
VOICE_DURATION_UNKNOWN = "مدت نامعلوم"
VOICE_PATH_TOOLTIP = "مسیر فایل — برای کپی کلیک کنید"
VOICE_PATH_COPIED = "مسیر کپی شد"
VOICE_NOTE_COUNT = "{n} یادداشت"

IDEAS_TITLE = "ایده‌ها"
IDEA_NEW = "ایدهٔ تازه"
IDEA_PLACEHOLDER = "ایده‌تان را بنویسید… (خودکار ذخیره می‌شود)"
IDEA_EMPTY = "هنوز ایده‌ای ثبت نشده. با «ایدهٔ تازه» اولین را بنویسید."
IDEA_DELETE_CONFIRM = "این ایده حذف شود؟"
IDEA_UNSAVED = "ایدهٔ تازه (هنوز ذخیره نشده)"

TAGS_TITLE = "برچسب‌ها"
TAG_NEW = "برچسب تازه"
TAG_FILTER_PLACEHOLDER = "پیدا کردن برچسب…"
TAG_FILTER_TOOLTIP = "پیدا کردن برچسب در همین درخت  (Ctrl+F)"
TAG_RENAME = "تغییر نام"
TAG_RECOLOR = "تغییر رنگ"
TAG_NEST = "انتقال به زیرِ…"
TAG_UNNEST = "انتقال به ریشه"
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
TAG_DELETE_CONFIRM = (
    "برچسب «{name}» حذف شود؟ از {n} مورد برداشته می‌شود و زیرمجموعه‌هایش یک سطح بالا می‌روند."
)
TAG_MERGE_CONFIRM = "همهٔ کاربردهای «{source}» به «{target}» منتقل و «{source}» حذف شود؟"
TAG_NEST_TITLE = "انتقال «{name}» به زیرِ…"
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
VOICE_FILTER_PLACEHOLDER = "پالایش صداها بر پایهٔ نام یا برچسب…"
IDEA_FILTER_PLACEHOLDER = "پالایش ایده‌ها بر پایهٔ متن یا برچسب…"

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
ERR_HIERARCHY = "یک برچسب نمی‌تواند زیرِ خودش یا زیرمجموعه‌هایش قرار بگیرد."
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
TS_EMPTY = "هنوز یادداشتی برای این صدا نیست. هنگام پخش Insert را بزنید و بنویسید."
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
    "هنوز صدایی به این اپیزود پیوند نخورده. «افزودن…» را بزنید یا از تب پیشنهادها انتخاب کنید."
)
WS_IDEAS_EMPTY = (
    "هنوز ایده‌ای به این اپیزود پیوند نخورده. «افزودن…» را بزنید یا از تب پیشنهادها انتخاب کنید."
)
WS_UNLINK = "برداشتن پیوند (Delete)"
WS_OPEN = "باز کردن (Enter)"
WS_MATERIALS = "مواد اپیزود"
WS_TAB_VOICES = "صداها"
WS_TAB_IDEAS = "ایده‌ها"
WS_TAB_SMART = "پیشنهادها"
WS_TAB_COUNT = "{label} {n}"
WS_SMART = "پیشنهادهای هم‌برچسب"
WS_SMART_NO_TAGS = "به اپیزود برچسب بدهید تا صداها و ایده‌های هم‌برچسب اینجا بیایند."
WS_SMART_NONE = "صدا یا ایده‌ای با برچسب مشترک پیدا نشد."
WS_SMART_SUBTITLE = "{kind}، {n} برچسب مشترک: {names}"
WS_SMART_LINKED = "پیوندشده ✓"
WS_LINK = "پیوند دادن"
WS_UNLINK_SHORT = "برداشتن پیوند"
WS_RECORD = "ضبط"
WS_RECORD_TOOLTIP = "اجرای برنامهٔ ضبط شما (Ctrl+R)"
WS_PICK_VOICE = "افزودن صدا به اپیزود"
WS_PICK_IDEA = "افزودن ایده به اپیزود"
WS_PICK_FILTER = "فیلتر…"
WS_PICK_ADD = "افزودن"
WS_PICK_EMPTY = "موردی برای افزودن نیست."
KIND_VOICE = "صدا"
KIND_IDEA = "ایده"

RESUME_EYEBROW = "ادامهٔ کار"
RESUME_NEXT_ACTION = "قدم بعدی"
RESUME_NO_NEXT = "قدم بعدی هنوز تعیین نشده."
RESUME_LAST_NOTE = "آخرین یادداشت"
RESUME_NO_NOTE = "هنوز یادداشتی ندارد."
RESUME_CONTINUE = "ادامه"
RESUME_SKIP = "همهٔ اپیزودها (Esc)"

INBOX_TITLE = "ایدهٔ تازه"
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

BOT_ENABLE = "دریافت ایده و صدا از بازوی بله"
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
    "هر پیام متنی به بازو یک ایده و هر پیام صوتی یک صدا در این فضای کاری می‌شود؛ "
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
BOT_RECEIVED_IDEA = "ایدهٔ تازه از بله رسید"
BOT_RECEIVED_VOICE = "صدای تازه از بله رسید"

TR_TAB_NOTES = "یادداشت‌ها"
TR_TAB_TRANSCRIPT = "رونوشت"
TR_RUN = "رونویسی"
TR_RERUN = "رونویسی دوباره"
TR_RUN_TOOLTIP = "تبدیل گفتار این صدا به متن فارسی، بدون اینترنت"
TR_CANCEL = "لغو"
TR_COPY = "کپی متن"
TR_COPIED = "متن کپی شد"
TR_EMPTY = "هنوز رونوشتی نیست. «رونویسی» گفتار این صدا را روی همین رایانه به متن تبدیل می‌کند."
TR_NO_SPEECH = "گفتاری در این صدا پیدا نشد."
TR_RUNNING = "در حال رونویسی… {percent}٪"
TR_LOADING_MODEL = "در حال آماده‌سازی مدل…"
TR_BUSY_ELSEWHERE = "رونویسی صدای دیگری در جریان است."
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
    "همهٔ اپیزودها، صداها، ایده‌ها و برچسب‌های فعلی با محتوای این فایل جایگزین شود؟\n"
    "نسخهٔ پشتیبانی از وضعیت فعلی در پوشهٔ backups ذخیره می‌شود."
)
DATA_IMPORT_ACTION = "جایگزین کن"
DATA_IMPORTING = "در حال بازگردانی… {percent}٪"
DATA_IMPORT_DONE = "بازگردانی شد: {episodes} اپیزود، {voices} صدا، {ideas} ایده، {tags} برچسب."
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
    "یک فایل خروجی همهٔ اپیزودها، یادداشت‌ها، ایده‌ها و صداها را نگه می‌دارد. "
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
    "voice": "صدا",
    "idea": "ایده",
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
    "tags_added": "افزودن برچسب {quoted} به {target}",
    "tags_removed": "برداشتن برچسب {quoted} از {target}",
    "linked": "پیوند {quoted} به {target}",
    "unlinked": "برداشتن پیوند {quoted} از {target}",
    "recolor": "تغییر رنگ برچسب {quoted}",
    "reparent": "جابه‌جایی برچسب {quoted}",
    "merge": "ادغام برچسب {quoted} در {other}",
}
UNDO_SOMETHING = "آخرین تغییر"


def apply_language(language: str) -> None:
    """Replace every text above with the chosen language's. Call once, before any UI.

    Persian is what this module holds already, so only English has anything to do.
    """
    if language != "en":
        return
    from podcast_workspace.ui import strings_en

    names = {name: value for name, value in vars(strings_en).items() if name.isupper()}
    globals().update(names)
