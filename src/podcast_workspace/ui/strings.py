"""All user-visible Persian text, in one place."""

from podcast_workspace.domain.entities import EpisodeStatus
from podcast_workspace.domain.search import SearchKind

APP_NAME = "فضای کاری پادکست"
STARTUP_ERROR_TITLE = "خطا در راه‌اندازی"
STARTUP_ERROR_BODY = "پایگاه داده باز نشد:\n{error}"

THEME_TO_DARK = "پوستهٔ تیره"
THEME_TO_LIGHT = "پوستهٔ روشن"
THEME_TOOLTIP = "تغییر پوسته (Ctrl+T)"

NAV_EPISODES = "اپیزودها"
NAV_VOICES = "صداها"
NAV_IDEAS = "ایده‌ها"
NAV_TAGS = "برچسب‌ها"

SEARCH_PLACEHOLDER = "جستجو در عنوان‌ها، یادداشت‌ها و برچسب‌ها…  (Ctrl+K)"
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
}
UNTITLED_NOTE = "یادداشت بی‌عنوان"

STATUS_LABELS = {
    EpisodeStatus.IDEA: "ایده",
    EpisodeStatus.OUTLINING: "طرح‌ریزی",
    EpisodeStatus.RECORDING: "ضبط",
    EpisodeStatus.EDITING: "تدوین",
    EpisodeStatus.PUBLISHED: "منتشرشده",
    EpisodeStatus.ARCHIVED: "بایگانی",
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

IDEAS_TITLE = "ایده‌ها"
IDEA_NEW = "ایدهٔ تازه"
IDEA_PLACEHOLDER = "ایده‌تان را بنویسید… (خودکار ذخیره می‌شود)"
IDEA_EMPTY = "هنوز ایده‌ای ثبت نشده. با «ایدهٔ تازه» اولین را بنویسید."
IDEA_DELETE_CONFIRM = "این ایده حذف شود؟"
IDEA_UNSAVED = "ایدهٔ تازه (هنوز ذخیره نشده)"

TAGS_TITLE = "برچسب‌ها"
TAG_NEW = "برچسب تازه"
TAG_FILTER_PLACEHOLDER = "پیدا کردن برچسب…"
TAG_RENAME = "تغییر نام"
TAG_RECOLOR = "تغییر رنگ"
TAG_NEST = "انتقال به زیرِ…"
TAG_UNNEST = "انتقال به ریشه"
TAG_MERGE = "ادغام در…"
TAG_DELETE = "حذف"
TAG_EMPTY = "هنوز برچسبی ندارید. برچسب‌ها را هنگام کار با اپیزودها و ایده‌ها هم می‌توانید بسازید."
TAG_USAGE_HEADER = "کاربرد"
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
