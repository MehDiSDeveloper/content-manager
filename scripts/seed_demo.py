"""Demo workspace for promo captures: a full, real-looking podcast in its own data folder.

Not part of the app. It never touches the real workspace (%APPDATA%\\PodcastWorkspace): it
writes only into the demo folder, and removing the demo is deleting that folder.

    .venv\\Scripts\\python scripts\\seed_demo.py            # create (refuses if it exists)
    .venv\\Scripts\\python scripts\\seed_demo.py --fresh    # delete and create again
    .venv\\Scripts\\python scripts\\seed_demo.py --remove   # delete the demo folder

The folder is `--home` (default: G:\\Repos\\promo\\podcast-workspace\\demo-home). Open the app
on it with PODCAST_WORKSPACE_HOME set to that folder.

Audio is synthesised (a speech-like voice of harmonics with syllables, words and pauses, so
waveforms and pause trimming look real), never anyone's recording.
"""

import argparse
import os
import shutil
import subprocess
import sys
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

DEFAULT_HOME = Path(__file__).resolve().parents[2] / "promo" / "podcast-workspace" / "demo-home"
RATE = 22050
NOW = datetime.now(UTC)


def ago(days: float = 0, hours: float = 0) -> datetime:
    return NOW - timedelta(days=days, hours=hours)


# --------------------------------------------------------------------------- content

# key: (name, colour)
TAGS = {
    "city": ("شهر", "#10b981"),
    "tehran": ("تهران", "#14b8a6"),
    "history": ("تاریخ", "#f59e0b"),
    "memory": ("خاطره", "#fb923c"),
    "philosophy": ("فلسفه", "#8b5cf6"),
    "tech": ("تکنولوژی", "#6366f1"),
    "psych": ("روانشناسی", "#ec4899"),
    "science": ("علم", "#0ea5e9"),
    "music": ("موسیقی", "#d946ef"),
    "books": ("کتاب", "#a16207"),
    "field": ("ضبط میدانی", "#84cc16"),
    "guest": ("مصاحبه", "#f97316"),
    "personal": ("یادداشت شخصی", "#ef4444"),
    "needs_edit": ("نیاز به تدوین", "#f43f5e"),
    "research": ("پژوهش لازم", "#0284c7"),
    "intro": ("تیتراژ", "#64748b"),
}

# key: (number, title, readme, about)
SEASONS = {
    "s1": (
        1,
        "شهر و خاطره",
        "هدف فصل: نشان دادن این‌که شهر فقط ساختمان نیست؛ آدم‌ها و صداها حافظه‌اش را می‌سازند.\n"
        "قاعده: هر قسمت دست‌کم یک ضبط میدانی دارد و با یک صدای واقعی از خیابان شروع می‌شود.\n"
        "لحن: گرم و آرام، مثل قدم زدن با یک دوست. بدون آمار خشک.\n"
        "طول هر قسمت: ۲۰ تا ۲۵ دقیقه.",
        "در فصل اول شب‌گرد در خیابان‌های قدیمی تهران قدم می‌زنیم و از آدم‌هایی می‌شنویم که "
        "شهر را به یاد دارند.",
    ),
    "s2": (
        2,
        "صداهای فراموش‌شده",
        "ایده‌ی اصلی: صداهایی که روزی همه‌جا بودند و حالا نیستند؛ رادیو، دست‌فروش‌ها، کاست.\n"
        "هر قسمت با آرشیو صوتی همان دوره شروع می‌شود.\n"
        "دست‌کم یک مهمان در هر قسمت. سؤال‌ها از قبل برای مهمان فرستاده شود.\n"
        "پایان هر قسمت یک پرسش باز برای شنونده.",
        "فصل دوم درباره‌ی صداهایی است که از زندگی‌مان رفته‌اند و چیزی که با خودشان بردند.",
    ),
    "s3": (
        3,
        "ماشین و انسان",
        "فصل در حال طراحی. محور: هر فناوری تازه یک ترس قدیمی را بیدار می‌کند.\n"
        "منابع: روزنامه‌های قدیمی، مصاحبه با دو پژوهشگر.\n"
        "نباید شبیه پادکست‌های تکنولوژی شود؛ داستان آدم‌ها اول است.",
        "",
    ),
}

# Audio ideas: key: (file name, seconds, voice pitch, days ago, tags, folder)
VOICES = {
    "bookshop": ("کتاب‌فروشی-انقلاب-جمعه.mp3", 214, 120, 3, ("field", "books", "tehran"), "voices"),
    "rahimi": ("مصاحبه-آقای-رحیمی.m4a", 286, 105, 9, ("guest", "history", "memory"), "voices"),
    "radio2": ("روایت-رادیو-برداشت-۲.mp3", 168, 135, 5, ("needs_edit", "history"), "voices"),
    "bazaar": ("صدای-بازار-تجریش.wav", 95, 150, 12, ("field", "city", "tehran"), "voices"),
    "metro": ("یادداشت-صبح-مترو.m4a", 64, 140, 1, ("personal", "city"), "voices"),
    "peddler": ("دست‌فروش-مترو-ولیعصر.mp3", 132, 160, 16, ("field", "memory"), "voices"),
    "cassette": ("کاست-پدربزرگ-۱۳۶۲.mp3", 245, 98, 7, ("memory", "music"), "voices"),
    "sadri": ("گفت‌وگو-با-خانم-صدری.m4a", 302, 190, 20, ("guest", "psych"), "voices"),
    "roof": ("غروب-پشت‌بام.wav", 78, 125, 26, ("field", "tehran"), "voices"),
    "intro": ("ایده-تیتراژ-فصل-سه.ogg", 41, 170, 2, ("intro", "music"), "voices"),
    "night": ("bale_voice_2026-10-14.ogg", 57, 130, 2, ("personal", "city"), "bale_voices"),
    "ai": ("bale_voice_2026-10-11.ogg", 83, 145, 5, ("tech", "philosophy"), "bale_voices"),
    "clock": ("ساعت-میدان-توپخانه.mp3", 118, 115, 33, ("history", "tehran"), "voices"),
    "mic": ("تست-میکروفون.wav", 22, 155, 0.2, (), "voices"),
}
ARCHIVED_VOICES = ("roof",)
TRASHED_VOICES = ("mic",)

# Text ideas: (text, tags, days ago). The first line is the idea's title.
IDEAS = [
    (
        "شهر بعد از نیمه‌شب\nشهر شب‌ها یک زبان دیگر حرف می‌زند: صدای کرکره‌ها، جارو، موتورهای "
        "پیک. شاید یک قسمت کامل را بشود فقط با صدای شب ساخت، بدون راوی.",
        ("city", "field"),
        0.3,
    ),
    (
        "جمله‌ی کتاب‌فروش\nکتاب‌فروش خیابان انقلاب می‌گفت پنجاه سال است سر یک چهارراه ایستاده و "
        "مشتری‌هایش سه نسل عوض شده‌اند. این جمله باید در قسمت بیاید.",
        ("books", "tehran", "memory"),
        2.5,
    ),
    (
        "رادیو و هم‌زمانی\nرادیو اولین شبکه‌ی اجتماعی بود: همه هم‌زمان یک چیز را می‌شنیدند و "
        "فردا صبح درباره‌اش حرف می‌زدند. فرقش با امروز در سرعت نیست، در هم‌زمانی است.",
        ("history", "tech"),
        5,
    ),
    (
        "ترس از ماشین‌ها تکرار می‌شود\nاز ماشین بافندگی تا هوش مصنوعی، هر بار همان جمله‌ها. "
        "در آرشیو روزنامه‌های دهه‌ی ۴۰ دنبال نقل قول درباره‌ی تلویزیون بگرد.",
        ("tech", "philosophy", "research"),
        6,
    ),
    (
        "همسایه‌های نادیده\nسه نفر را پیدا کن که ده سال در یک ساختمان زندگی کرده‌اند و اسم همسایه‌ی "
        "روبه‌رویی را نمی‌دانند. چرا؟",
        ("psych", "city"),
        8.5,
    ),
    (
        "تیتراژ با صدای باران\nتیتراژ قسمت تازه را با صدای باران روی حلبی امتحان کن.",
        ("intro", "music"),
        0.8,
    ),
    (
        "چه کسی ساعت‌ها را کوک می‌کند؟\nیک قسمت کوتاه درباره‌ی ساعت‌های عمومی شهر. ساعت میدان "
        "توپخانه هنوز کار می‌کند؟",
        ("tehran", "history"),
        11,
    ),
    (
        "شروع خوب\n«حافظه‌ی یک خیابان در ویترین مغازه‌هایش نگه داشته می‌شود.»",
        ("memory", "city"),
        14,
    ),
    (
        "مهمان‌های فصل سه\nدست‌کم دو مهمان لازم است: یک پژوهشگر تاریخ فناوری و یک برنامه‌نویس "
        "که با هوش مصنوعی کار می‌کند. فهرست را این هفته بنویس.",
        ("guest", "tech"),
        3.2,
    ),
    (
        "پرسش پایانی\nاگر فردا همه‌ی چراغ‌های شهر خاموش شوند، اول کجا را روشن می‌کنی؟",
        ("philosophy", "city"),
        1.1,
    ),
    (
        "کاست‌های خانوادگی\nهر خانواده‌ای یک جعبه کاست دارد که کسی گوشش نمی‌دهد. از شنونده‌ها "
        "بخواه صدای یکی را برایمان بفرستند.",
        ("memory", "music"),
        4,
    ),
    (
        "دست‌فروش‌های مترو\nهر خط مترو آهنگ خودش را دارد. «جوراب، جوراب، سه جفت صد» را ضبط کن.",
        ("field", "city"),
        16,
    ),
    (
        "حافظه در عصر گوشی\nوقتی همه‌چیز عکس دارد، دیگر چه چیزی را به خاطر می‌سپاریم؟ "
        "پژوهش‌های تازه درباره‌ی «اثر گوگل» را بخوان.",
        ("science", "psych", "research"),
        2,
    ),
    (
        "پشت‌بام‌ها\nتابستان‌های قدیم همه روی پشت‌بام می‌خوابیدند. از مادربزرگ بپرس شب‌ها "
        "درباره‌ی چه حرف می‌زدند.",
        ("tehran", "memory"),
        21,
    ),
    (
        "کافه نادری\nروایت کافه‌های لاله‌زار بدون کافه نادری کامل نیست. ساعت‌های خلوتش را بپرس.",
        ("tehran", "history"),
        30,
    ),
    (
        "الگوریتم‌ها چه می‌شنوند؟\nدستیارهای صوتی فارسی را چقدر خوب می‌فهمند؟ با لهجه‌های مختلف "
        "امتحان کن و نتیجه را در قسمت بگو.",
        ("tech", "science"),
        9,
    ),
    (
        "صدای بوق‌ها\nبوق تاکسی در تهران فقط هشدار نیست؛ سلام است، تشکر است، دعواست. یک فرهنگ "
        "لغت کوچک بوق بساز.",
        ("city", "field"),
        12,
    ),
    (
        "هفت‌سین صد سال\nسفره‌ی هفت‌سین در صد سال گذشته چقدر عوض شده؟ عکس‌های خانوادگی شنونده‌ها "
        "را جمع کن.",
        ("history", "memory"),
        18,
    ),
    (
        "موسیقی متن\nبرای فصل دوم یک قطعه‌ی پیانوی آرام لازم است. با آهنگساز درباره‌ی مجوز حرف بزن.",
        ("music",),
        6.5,
    ),
    (
        "نامه‌ی یک شنونده\nخانم «م» از شیراز نوشته بود که پادکست را در راه سرکار گوش می‌دهد. "
        "قسمت گفت‌وگو با شنونده‌ها را با نامه‌ی او شروع کن.",
        ("personal",),
        1.6,
    ),
    (
        "صف نانوایی\nصف نانوایی سنگکی صبح جمعه، بهترین جا برای شنیدن حرف‌های واقعی مردم است.",
        ("field", "tehran"),
        24,
    ),
    (
        "اثر صدا بر حافظه\nچرا یک آهنگ قدیمی ما را دقیقاً به همان سال برمی‌گرداند؟ "
        "مقاله‌ی دانشگاه کالیفرنیا درباره‌ی حافظه‌ی شنیداری را پیدا کن.",
        ("science", "music", "memory"),
        10,
    ),
    ("رنگ شهر\nاگر تهران یک رنگ داشت، چه رنگی بود؟ از ده نفر بپرس.", (), 0.5),
    ("ساختار قسمت‌ها\nشاید هر قسمت سه بخش ثابت داشته باشد: صدا، قصه، پرسش.", (), 2.2),
]
ARCHIVED_IDEAS = (14, 20)  # indexes into IDEAS
TRASHED_IDEAS = [
    ("یادداشت تکراری\nهمان ایده‌ی صدای شب، این بار با جزئیات کمتر.", ("city",), 4),
    ("فهرست خرید میکروفون\nکاندنسر یا داینامیک؟ فعلاً لازم نیست.", (), 7),
]

# key: (season, number, title, status, next action, tags, days since update, summary)
EPISODES = {
    "zero": (
        "s1",
        0,
        "قسمت صفر: چرا شب‌گرد؟",
        "published",
        "",
        ("personal", "city"),
        120,
        "معرفی پادکست: چرا شهر را با صدا روایت می‌کنیم و چه چیزی در راه است.",
    ),
    "street": (
        "s1",
        1,
        "حافظه‌ی جمعی یک خیابان",
        "published",
        "",
        ("history", "city", "memory"),
        96,
        "خیابان لاله‌زار از چشم سه نسل؛ از سینماها تا مغازه‌های لوازم برقی.",
    ),
    "clocks": (
        "s1",
        2,
        "ساعت‌های عمومی شهر",
        "published",
        "",
        ("history", "tehran"),
        75,
        "ساعت‌های میدان‌ها و کسانی که هنوز کوکشان می‌کنند؛ زمان مشترک یک شهر.",
    ),
    "cafes": (
        "s1",
        3,
        "کافه‌های قدیمی لاله‌زار",
        "published",
        "",
        ("tehran", "history", "memory"),
        54,
        "کافه نادری و هم‌نسل‌هایش: جایی که نویسنده‌ها و نقاش‌ها هم را پیدا می‌کردند.",
    ),
    "roofs": (
        "s1",
        4,
        "پشت‌بام‌های تهران",
        "edited",
        "کاور را نهایی کن و توضیح قسمت را بنویس",
        ("tehran", "memory", "field"),
        6,
        "شب‌های تابستان روی پشت‌بام؛ خاطره‌ی شهری که آسمان داشت.",
    ),
    "radio": (
        "s2",
        1,
        "رادیو؛ اولین شبکه‌ی اجتماعی",
        "published",
        "",
        ("history", "tech"),
        30,
        "از اولین پخش رادیو تهران تا امروز؛ هم‌زمانی‌ای که از دست داده‌ایم.",
    ),
    "peddlers": (
        "s2",
        2,
        "صدای دست‌فروش‌ها",
        "edited",
        "موسیقی تیتراژ را جایگزین کن",
        ("field", "city", "needs_edit"),
        4,
        "آوازهای کوچه و مترو؛ تبلیغاتی که از گلو می‌آمد.",
    ),
    "bookshops": (
        "s2",
        3,
        "کتاب‌فروشی‌های خیابان انقلاب",
        "recorded",
        "صداها را برش بزن و بهترین ده دقیقه را جدا کن",
        ("books", "tehran", "field"),
        0.4,
        "",
    ),
    "night": (
        "s2",
        4,
        "شب‌گردی: شهر وقتی می‌خوابد",
        "script_ready",
        "متن نهایی را با صدای بلند بخوان و زمان بگیر",
        ("city", "field"),
        2,
        "",
    ),
    "cassette": (
        "s2",
        5,
        "نوارهای کاست خانوادگی",
        "outline",
        "از سه شنونده کاست بگیر",
        ("memory", "music", "research"),
        3,
        "",
    ),
    "horns": ("s2", 6, "زبان بوق‌ها", "idea", "ده نوع بوق را ضبط و دسته‌بندی کن", ("city",), 12, ""),
    "fears": (
        "s3",
        1,
        "ترس‌های قدیمی از ماشین‌های جدید",
        "outline",
        "نقل قول‌های روزنامه را پیدا کن",
        ("tech", "philosophy", "research"),
        5,
        "",
    ),
    "phone": (
        "s3",
        2,
        "حافظه در عصر گوشی",
        "idea",
        "سه مقاله‌ی اصلی را بخوان",
        ("science", "psych"),
        2,
        "",
    ),
    "algo": ("s3", None, "الگوریتم‌ها چه می‌شنوند؟", "idea", "", ("tech", "science"), 9, ""),
    "towers": (
        None,
        None,
        "تنهایی در آپارتمان‌های بلند",
        "idea",
        "با سه نفر از ساکن‌های برج حرف بزن",
        ("psych", "city"),
        15,
        "",
    ),
    "nowruz": (
        None,
        None,
        "ویژه‌ی نوروز: هفت‌سین در صد سال",
        "outline",
        "عکس‌های شنونده‌ها را جمع کن",
        ("history", "memory"),
        18,
        "",
    ),
    "listeners": (
        None,
        None,
        "گفت‌وگو با شنونده‌ها",
        "recorded",
        "نامه‌ها را به ترتیب بچین",
        ("personal", "guest"),
        1,
        "",
    ),
}
LAST_OPENED = "bookshops"  # the startup «continue» offer

# episode key: (voice keys, idea indexes)
LINKS = {
    "bookshops": (("bookshop", "rahimi"), (1, 7)),
    "radio": (("radio2",), (2,)),
    "night": (("night", "metro"), (0, 9)),
    "peddlers": (("peddler", "bazaar"), (11, 16)),
    "cassette": (("cassette",), (10, 21)),
    "fears": (("ai",), (3, 8)),
    "phone": ((), (12,)),
    "clocks": (("clock",), (6,)),
    "roofs": (("roof",), (13,)),
    "towers": (("sadri",), (4,)),
    "algo": ((), (15,)),
    "nowruz": ((), (17,)),
    "listeners": ((), (19,)),
}

PUBLISHED_WHERE = "کست‌باکس\nاسپاتیفای\nاپل پادکست\nکانال تلگرام شب‌گرد"
PUBLISH = {  # episodes not yet published but partly ready: (steps done, where)
    "roofs": (("title", "description", "clips"), ""),
    "peddlers": (("title",), ""),
}

# episode key: [(title, body)]
EPISODE_NOTES = {
    "bookshops": [
        (
            "طرح کلی",
            "شروع با صدای خیابان انقلاب، جمعه عصر.\n"
            "بخش اول: سه کتاب‌فروشی، سه نسل.\n"
            "بخش دوم: گفت‌وگو با آقای رحیمی؛ پنجاه سال پشت یک پیشخوان.\n"
            "بخش سوم: چرا همه‌ی کتاب‌فروشی‌ها یک خیابان را انتخاب کردند؟\n"
            "پایان: ویترینی که هنوز کتاب سال ۱۳۵۷ را دارد.",
        ),
        (
            "سؤال‌های مصاحبه",
            "۱. اولین روزی که این مغازه را باز کردید یادتان هست؟\n"
            "۲. کتابی هست که دیگر کسی نمی‌خرد؟\n"
            "۳. مشتری‌ها چه چیزی را عوض کرده‌اند؟\n"
            "۴. اگر یک کتاب را به همه پیشنهاد کنید، کدام است؟",
        ),
        (
            "کارهای باقی‌مانده",
            "- اجازه‌ی پخش صدای مصاحبه\n- عکس ویترین برای کاور\n- چک کردن سال تأسیس",
        ),
    ],
    "radio": [
        (
            "متن راوی",
            "«یک شب زمستان سال ۱۳۱۹، صدایی از یک جعبه‌ی چوبی بیرون آمد و خانه‌ها را به هم وصل کرد.»\n"
            "بعد از این جمله سه ثانیه سکوت، بعد آرشیو.",
        ),
    ],
    "night": [
        (
            "متن نهایی",
            "ساعت دوازده و نیم شب است. آخرین مترو رفته و خیابان ولیعصر نفس می‌کشد.\n"
            "صدای جاروی رفتگر، کرکره‌ای که پایین می‌آید، و موتوری که از دور می‌آید.\n"
            "امشب می‌خواهم شهر را از زبان همین صداها بشنویم.",
        ),
        ("صداهای لازم", "کرکره · جارو · موتور پیک · اذان صبح · نانوایی ساعت پنج"),
    ],
    "peddlers": [
        ("ترتیب صداها", "۱. بازار تجریش\n۲. مترو ولیعصر\n۳. آرشیو: «نمکی» دهه‌ی ۵۰"),
    ],
    "fears": [
        (
            "فهرست ترس‌ها",
            "- چاپ: «کتاب حافظه را نابود می‌کند»\n- تلفن: «دیگر کسی به دیدن هم نمی‌رود»\n"
            "- تلویزیون: «بچه‌ها کتاب نمی‌خوانند»\n- هوش مصنوعی: ؟",
        ),
    ],
    "cassette": [
        ("طرح", "شروع با صدای کاست پدربزرگ، ۱۳۶۲. بعد سه کاست از سه خانواده."),
    ],
    "roofs": [
        (
            "توضیح قسمت (پیش‌نویس)",
            "تابستان‌های تهران، پشت‌بام‌ها پر از رختخواب بود. در این قسمت از کسانی می‌شنویم "
            "که زیر آسمان پرستاره‌ی شهر بزرگ شدند.",
        ),
    ],
}

# voice key: [(seconds, note)]
TIMESTAMP_NOTES = {
    "bookshop": [
        (8, "صدای زمینه‌ی خیابان عالی است؛ برای شروع قسمت"),
        (47, "جمله‌ی «سه نسل مشتری» اینجاست"),
        (96, "نویز موتور؛ این چند ثانیه حذف شود"),
        (161, "پایان خوب برای بخش اول"),
    ],
    "rahimi": [
        (25, "مهمان تازه گرم شده، از اینجا قابل استفاده است"),
        (112, "خاطره‌ی سال ۵۷"),
        (198, "نقل قول اصلی مصاحبه"),
    ],
    "radio2": [(12, "شروع را دوباره ضبط کن"), (64, "این برداشت بهترین است")],
    "cassette": [
        (30, "صدای پدربزرگ: «این نوار را برای نوه‌ام پر می‌کنم»"),
        (140, "آهنگ قدیمی؛ مجوز؟"),
    ],
    "sadri": [(40, "تعریف تنهایی شهری"), (210, "پیشنهاد کتاب")],
    "night": [(3, "ایده‌ی وسط خیابان؛ بعداً کاملش کن")],
    "peddler": [(18, "آواز «جوراب، جوراب»"), (77, "گفت‌وگوی کوتاه با فروشنده")],
}

TRANSCRIPTS = {
    "bookshop": [
        "جمعه عصر است و خیابان انقلاب هنوز شلوغ است.",
        "روبه‌روی دانشگاه، ویترین کتاب‌فروشی‌ها یکی پس از دیگری روشن می‌شوند.",
        "آقای رحیمی می‌گوید پنجاه سال است پشت همین پیشخوان ایستاده.",
        "مشتری‌هایش سه نسل عوض شده‌اند، اما بعضی کتاب‌ها هیچ‌وقت از قفسه پایین نیامده‌اند.",
        "می‌پرسم پرفروش‌ترین کتاب این روزها چیست. می‌خندد و می‌گوید: هنوز هم دیوان حافظ.",
        "صدای ورق زدن، صدای ترمز یک تاکسی، و کسی که اسم یک کتاب را بلند می‌پرسد.",
        "اینجا هنوز آدم‌ها کتاب را دست می‌گیرند، بو می‌کنند و بعد می‌خرند.",
        "شاید همین است که این خیابان را زنده نگه داشته.",
    ],
    "rahimi": [
        "من سال پنجاه و دو این مغازه را از پدرم تحویل گرفتم.",
        "آن وقت‌ها کتاب‌ها را با گاری از ناصرخسرو می‌آوردیم.",
        "دانشجوها صبح زود صف می‌کشیدند که چاپ تازه‌ی یک کتاب را بخرند.",
        "سال پنجاه و هفت، این ویترین شده بود تابلوی اعلانات شهر.",
        "حالا مشتری‌ها اول در گوشی‌شان قیمت را نگاه می‌کنند، بعد می‌آیند.",
        "ولی هنوز کسی هست که فقط برای حرف زدن می‌آید.",
        "کتاب‌فروشی فقط جای خرید نیست؛ جای پیدا کردن آدم‌هاست.",
    ],
    "radio2": [
        "برداشت دوم، قسمت رادیو.",
        "یک شب زمستان سال هزار و سیصد و نوزده، صدایی از یک جعبه‌ی چوبی بیرون آمد.",
        "مردم دور آن جعبه جمع شدند، همان‌طور که امروز دور یک صفحه‌ی روشن جمع می‌شویم.",
        "رادیو اولین شبکه‌ی اجتماعی بود؛ همه هم‌زمان یک چیز را می‌شنیدند.",
        "فردای آن شب، حرف همه‌ی شهر یکی بود.",
        "در این قسمت دنبال همان هم‌زمانی گم‌شده می‌گردیم.",
    ],
    "night": [
        "یادداشت شبانه، چهاردهم مهر.",
        "امشب از خیابان که رد می‌شدم فهمیدم شهر بعد از نیمه‌شب صدای دیگری دارد.",
        "صدای کرکره‌ها، صدای جارو، و یک موتور که از دور می‌آید و رد می‌شود.",
        "شاید بشود یک قسمت کامل فقط با همین صداها ساخت.",
    ],
    "cassette": [
        "این نوار مال پاییز شصت و دو است.",
        "پدربزرگم آن را برای نوه‌اش پر کرده؛ یعنی برای من.",
        "اول اسم همه را می‌گوید، بعد یک شعر می‌خواند.",
        "وسط شعر صدای مادربزرگ می‌آید که می‌گوید چای حاضر است.",
        "چهل سال بعد، این تنها صدایی است که از او مانده.",
    ],
    "ai": [
        "یک فکر توی راه: هر بار ماشین تازه‌ای آمده، گفته‌ایم این بار فرق دارد.",
        "شاید فرقش این است که این بار ماشین حرف هم می‌زند.",
        "باید ببینم روزنامه‌های قدیمی درباره‌ی تلویزیون چه نوشته بودند.",
    ],
}

BRIEFS = {
    "bookshops": {
        "about": "روایت سه نسل کتاب‌فروشی در خیابان انقلاب، با تکیه بر مصاحبه‌ی آقای رحیمی.",
        "format": "monologue",
        "styles": ["story", "documentary"],
        "audiences": ["general", "enthusiasts"],
        "depth": 2,
        "approaches": ["conceptual", "critical"],
        "moods": ["warm", "emotional"],
        "register": "semi_formal",
        "minutes": 22,
    },
    "night": {
        "about": "شهر بعد از نیمه‌شب، فقط با صداهایش.",
        "format": "monologue",
        "styles": ["recital"],
        "moods": ["calm", "warm"],
        "register": "casual",
        "minutes": 18,
    },
}

# The audio folder: takes the recording program saved and nobody reviewed yet.
RECORDINGS = [
    ("ضبط-۱۴۰۵-۰۷-۲۳-صبح.wav", 52, 135),
    ("ضبط-۱۴۰۵-۰۷-۲۳-عصر.wav", 88, 128),
    ("ضبط-۱۴۰۵-۰۷-۲۴.wav", 36, 150),
    ("برداشت-تیتراژ-۳.wav", 24, 165),
    ("مصاحبه-خیابان-ولیعصر.wav", 140, 112),
]


# --------------------------------------------------------------------------- audio


def speech(seconds: float, pitch: float, seed: int) -> np.ndarray:
    """A voice-like signal: harmonics on a drifting pitch, cut into syllables, words and
    phrases with real pauses between them over a quiet room tone."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    env = np.zeros(n)
    t = 0.25 + rng.uniform(0, 0.4)
    while t < seconds - 0.5:
        phrase_gain = rng.uniform(0.55, 1.0)
        for _word in range(int(rng.integers(3, 11))):
            for _syl in range(int(rng.integers(1, 4))):
                length = rng.uniform(0.11, 0.24)
                a, b = int(t * RATE), int(min(t + length, seconds) * RATE)
                if b <= a:
                    break
                env[a:b] = np.maximum(
                    env[a:b], np.hanning(b - a) * phrase_gain * rng.uniform(0.45, 1)
                )
                t += length * rng.uniform(0.85, 1.05)
            t += rng.uniform(0.03, 0.12)
            phrase_gain *= 0.97  # declination
        t += rng.uniform(0.4, 1.6) if rng.random() < 0.8 else rng.uniform(1.8, 3.0)
    # Pitch: a slow wander plus a per-phrase fall.
    drift = np.interp(np.arange(n), np.linspace(0, n, 40), rng.uniform(0.85, 1.2, 40))
    f0 = pitch * drift
    phase = np.cumsum(2 * np.pi * f0 / RATE)
    voice = sum(np.sin(k * phase) / k**1.2 for k in range(1, 14))
    hiss = rng.normal(0, 0.25, n)
    signal = (voice * 0.8 + hiss * 0.2) * env
    signal += rng.normal(0, 0.004, n)  # room tone
    return signal / np.max(np.abs(signal)) * 0.85


def write_audio(path: Path, seconds: float, pitch: float, seed: int, ffmpeg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (speech(seconds, pitch, seed) * 32767).astype("<i2")
    target = path if path.suffix == ".wav" else path.with_suffix(".tmp.wav")
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm.tobytes())
    if target == path:
        return
    codec = {
        ".mp3": ["-c:a", "libmp3lame", "-b:a", "96k"],
        ".m4a": ["-c:a", "aac", "-b:a", "96k"],
        ".ogg": ["-c:a", "libopus", "-b:a", "48k"],
    }[path.suffix]
    subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", str(target), *codec, str(path)],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    target.unlink()


# --------------------------------------------------------------------------- seeding


def seed(home: Path) -> None:
    # Imported here: they read PODCAST_WORKSPACE_HOME, which main() has just set.
    from podcast_workspace.audio.ffmpeg import require_ffmpeg
    from podcast_workspace.domain.entities import (
        Episode,
        EpisodeNote,
        EpisodeStatus,
        IdeaNote,
        Season,
        Tag,
        TimestampNote,
        Transcript,
        TranscriptSegment,
        Voice,
    )
    from podcast_workspace.domain.publish import PublishChecklist
    from podcast_workspace.domain.script_brief import ScriptBrief
    from podcast_workspace.paths import database_path
    from podcast_workspace.repositories.db import engine_for_file, make_session_factory, migrate
    from podcast_workspace.repositories.unit_of_work import UnitOfWork
    from podcast_workspace.services.audio_probe import probe
    from podcast_workspace.services.settings_service import Language, SettingsService, Theme

    ffmpeg = str(require_ffmpeg())
    engine = engine_for_file(database_path())
    migrate(engine)
    session_factory = make_session_factory(engine)

    with UnitOfWork(session_factory) as uow:
        tags = {}
        for key, (name, color) in TAGS.items():
            tags[key] = uow.tags.add(Tag(name=name, color=color)).id

        def tag_ids(keys: tuple[str, ...]) -> set[int]:
            return {tags[k] for k in keys}

        seasons = {}
        for key, (number, title, readme, about) in SEASONS.items():
            season = Season(
                title=title,
                readme=readme,
                about=about,
                number=number,
                created_at=ago(days=200 - number * 50),
            )
            seasons[key] = uow.seasons.add(season).id

        voices = {}
        for seed_no, (key, (name, seconds, pitch, days, keys, folder)) in enumerate(VOICES.items()):
            path = home / folder / name
            print(f"  audio: {name}")
            write_audio(path, seconds, pitch, seed_no + 1, ffmpeg)
            info = probe(path)
            voice = Voice(
                file_path=str(path),
                duration_ms=info.duration_ms,
                format=info.format,
                imported_at=ago(days=days),
                tag_ids=tag_ids(keys),
                archived_at=ago(days=days / 2) if key in ARCHIVED_VOICES else None,
                deleted_at=ago(days=1) if key in TRASHED_VOICES else None,
            )
            voices[key] = uow.voices.add(voice).id

        ideas = []
        for index, (text, keys, days) in enumerate(IDEAS):
            idea = IdeaNote(
                text=text,
                created_at=ago(days=days + 0.2),
                updated_at=ago(days=days),
                tag_ids=tag_ids(keys),
                archived_at=ago(days=days / 2) if index in ARCHIVED_IDEAS else None,
            )
            ideas.append(uow.idea_notes.add(idea).id)
        for text, keys, days in TRASHED_IDEAS:
            uow.idea_notes.add(
                IdeaNote(
                    text=text,
                    created_at=ago(days=days + 3),
                    updated_at=ago(days=days + 3),
                    tag_ids=tag_ids(keys),
                    deleted_at=ago(days=days),
                )
            )

        episodes = {}
        for key, (season, number, title, status, action, keys, days, summary) in EPISODES.items():
            voice_keys, idea_indexes = LINKS.get(key, ((), ()))
            if status == "published":
                publish = PublishChecklist(
                    done=frozenset({"title", "description", "clips", "cover"}),
                    where=PUBLISHED_WHERE,
                )
            else:
                done, where = PUBLISH.get(key, ((), ""))
                publish = PublishChecklist(done=frozenset(done), where=where)
            episode = Episode(
                title=title,
                status=EpisodeStatus(status),
                next_action=action,
                season_id=seasons[season] if season else None,
                number=number,
                summary=summary,
                created_at=ago(days=days + 20),
                updated_at=ago(days=days),
                last_opened_at=ago(hours=5) if key == LAST_OPENED else None,
                tag_ids=tag_ids(keys),
                voice_ids={voices[v] for v in voice_keys},
                idea_note_ids={ideas[i] for i in idea_indexes},
                publish=publish,
                brief=ScriptBrief.from_dict(BRIEFS[key]) if key in BRIEFS else ScriptBrief(),
            )
            episodes[key] = uow.episodes.add(episode).id

        for key, notes in EPISODE_NOTES.items():
            for offset, (title, body) in enumerate(notes):
                when = ago(days=EPISODES[key][6] + offset * 0.1)
                uow.episode_notes.add(
                    EpisodeNote(
                        episode_id=episodes[key],
                        title=title,
                        body=body,
                        created_at=when,
                        updated_at=when,
                    )
                )

        for key, notes in TIMESTAMP_NOTES.items():
            for seconds, text in notes:
                uow.timestamp_notes.add(
                    TimestampNote(
                        voice_id=voices[key],
                        position_ms=seconds * 1000,
                        text=text,
                        created_at=ago(days=1),
                    )
                )

        for key, sentences in TRANSCRIPTS.items():
            total = VOICES[key][1] * 1000
            step = total // len(sentences)
            segments = [
                TranscriptSegment(i * step, min((i + 1) * step - 300, total), text)
                for i, text in enumerate(sentences)
            ]
            uow.transcripts.add(
                Transcript(
                    voice_id=voices[key],
                    segments=segments,
                    language="fa",
                    model="large-v3-turbo",
                    created_at=ago(days=1),
                )
            )

    recordings = home / "recordings"
    for seed_no, (name, seconds, pitch) in enumerate(RECORDINGS):
        print(f"  audio: recordings/{name}")
        write_audio(recordings / name, seconds, pitch, 100 + seed_no, ffmpeg)

    settings = SettingsService(session_factory)
    settings.set_language(Language.FA)
    settings.set_theme(Theme.LIGHT)
    settings.first_run_at(ago(days=150))
    settings.set_last_backup_at(ago(days=1))  # no backup reminder over the demo
    settings.set_source_folder(str(recordings))
    settings.set_player_volume(80)

    with engine.begin() as connection:  # fold the WAL into the file
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    engine.dispose()


def real_workspace() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "PodcastWorkspace"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="the demo data folder")
    parser.add_argument("--fresh", action="store_true", help="delete the demo folder first")
    parser.add_argument("--remove", action="store_true", help="delete the demo folder and stop")
    args = parser.parse_args()
    home = args.home.resolve()
    if home == real_workspace().resolve():
        print("Refusing: that is the real workspace.")
        return 2

    if args.remove or args.fresh:
        if home.exists():
            shutil.rmtree(home)
            print(f"Removed {home}")
        if args.remove:
            return 0
    if (home / "workspace.db").exists():
        print(f"{home} already holds a workspace. --fresh rebuilds it, --remove deletes it.")
        return 1

    home.mkdir(parents=True, exist_ok=True)
    os.environ["PODCAST_WORKSPACE_HOME"] = str(home)
    print(f"Seeding the demo into {home}")
    seed(home)
    print("Done. Open it with PODCAST_WORKSPACE_HOME set to that folder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
