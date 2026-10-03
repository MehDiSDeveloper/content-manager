"""The script prompt: everything about an episode, as one prompt for an AI to write from.

A fixed template filled in with the episode's material and its brief; nothing here calls
a model. The prompt is Persian whatever the UI language, since the podcast is.

Its order follows how a long prompt is best read: who the AI is and what it is for, then
the material (the episode, its specs, my draft, the ideas), then the rules of writing,
and last what to do — check and propose first, write only once I have agreed.
"""

from dataclasses import dataclass

from podcast_workspace.domain.script_brief import (
    DEPTHS,
    Approach,
    Audience,
    Mood,
    Register,
    ScriptBrief,
    ScriptFormat,
)

WORDS_PER_MINUTE = 130  # Persian speech at an ordinary pace

FORMATS = {
    ScriptFormat.MONOLOGUE: (
        "تک‌گویی",
        "یک گوینده، خودم، رو به شنونده حرف می‌زنم.",
    ),
    ScriptFormat.DIALOGUE: (
        "گفت‌وگوی دونفره",
        "دو گوینده، با نام هر کدام اول نوبتش. گفت‌وگو واقعی باشد: بپرسند، حرف هم را کامل "
        "کنند، گاهی مخالفت کنند؛ نه دو سخنرانی نوبتی.",
    ),
    ScriptFormat.PANEL: (
        "میزگرد",
        "یک گرداننده و دست‌کم سه گوینده با دیدگاه‌های متفاوت، با نام هر کدام اول نوبتش. "
        "اختلاف نظر واقعی و محترمانه باشد و گرداننده بحث را جلو ببرد.",
    ),
    ScriptFormat.STORY: (
        "روایت داستانی",
        "موضوع در دل یک روایت پیش برود: آدم، صحنه، کشمکش و گره‌گشایی. ایده‌ها از دل "
        "داستان بیرون بیایند؛ داستان بهانهٔ سخنرانی نباشد.",
    ),
    ScriptFormat.RECITAL: (
        "دکلمه",
        "نثری ادبی و آهنگین برای خواندن روی موسیقی بی‌کلام: جمله‌های کوتاه و تصویری، با "
        "مکث‌های عمدی. جای موسیقی و مکث را در کروشه نشان بده، مثل [موسیقی اوج می‌گیرد] یا [مکث].",
    ),
}

AUDIENCES = {
    Audience.GENERAL: "عموم مردم",
    Audience.YOUNG: "نوجوانان و جوانان",
    Audience.ENTHUSIASTS: "علاقه‌مندانی که با موضوع آشنا هستند",
    Audience.STUDENTS: "دانشجویان و پژوهشگران",
    Audience.EXPERTS: "متخصصان این حوزه",
}

DEPTH_LEVELS = {
    1: (
        "آشنایی",
        "شنونده هیچ پیش‌زمینه‌ای ندارد. موضوع را با تجربه‌های روزمره و مثال‌های ملموس باز "
        "کن، اصطلاح تخصصی نیاور مگر با توضیحی ساده، و فقط یکی دو ایدهٔ اصلی را خوب جا بینداز.",
    ),
    2: (
        "فهم",
        "شنونده با موضوع کمی آشناست. چرایی و سازوکار را توضیح بده: مفهوم‌های کلیدی، "
        "رابطه‌هایشان، و یکی دو برداشت نادرست رایج و پاسخشان.",
    ),
    3: (
        "کاوش",
        "به لایه‌های کمتر دیده‌شده برو: ظرافت‌ها، استثناها، دیدگاه‌های رقیب و پیوند موضوع با "
        "حوزه‌های دیگر. اصطلاح‌های دقیق را به کار ببر و کوتاه تعریفشان کن.",
    ),
    4: (
        "تحلیل",
        "در حد گفت‌وگو با اهل فن: نظریه‌ها و شواهد را بسنج، نقدها و محدودیت‌ها را بیاور و "
        "استدلال را دقیق و گام‌به‌گام پیش ببر. ساده‌سازی را کنار بگذار.",
    ),
    5: (
        "ژرفا",
        "بنیادی‌ترین و انتزاعی‌ترین لایه: پیش‌فرض‌ها، پرسش‌های فلسفی و مرز دانسته‌ها. با "
        "شنونده‌ای بسیار فهیم حرف بزن؛ متن چگال، دقیق و تأمل‌برانگیز باشد، حتی اگر شنوندهٔ "
        "عام همراه نشود.",
    ),
}

APPROACHES = {
    Approach.CONCEPTUAL: (
        "مفهومی",
        "بر مفهوم و معنا تکیه کن: ایده‌ها را باز کن و پیوندشان را نشان بده، نه انبوه داده.",
    ),
    Approach.SCIENTIFIC: (
        "علمی",
        "بر شواهد و پژوهش تکیه کن؛ دقیق باش و برای ادعاهای مهم منبع داشته باش.",
    ),
    Approach.PRACTICAL: (
        "کاربردی",
        "شنونده باید چیزی با خودش ببرد که بتواند در زندگی‌اش به کار ببندد.",
    ),
    Approach.PHILOSOPHICAL: (
        "فلسفی",
        "پرسش‌های بنیادین را پیش بکش و شنونده را به اندیشیدن دعوت کن.",
    ),
    Approach.CRITICAL: (
        "انتقادی",
        "باورها و فرض‌های رایج را به چالش بکش و منصفانه نقد کن.",
    ),
}

MOODS = {
    Mood.CALM: "آرام و تأمل‌برانگیز",
    Mood.WARM: "گرم و صمیمی",
    Mood.HUMOROUS: "شوخ‌طبع",
    Mood.COOL: "باحال و بی‌تکلف",
    Mood.ENERGETIC: "پرانرژی",
    Mood.EXCITING: "هیجان‌انگیز",
    Mood.EMOTIONAL: "احساسی",
    Mood.INSPIRING: "انگیزشی",
    Mood.SOMBER: "اندوهگین",
}

REGISTERS = {
    Register.CASUAL: (
        "خودمونی (محاوره)",
        "به زبان گفتاری بنویس، همان‌طور که حرف می‌زنیم: «می‌رم، می‌گه، اینه که…». شکستهٔ "
        "طبیعی، نه لاتی و نه بیش از اندازه عامیانه.",
    ),
    Register.SEMI_FORMAL: (
        "نیمه‌رسمی",
        "گفتاریِ پاکیزه، مثل گوینده‌ای که با احترام اما بی‌تکلف حرف می‌زند: فعل‌ها می‌توانند "
        "کمی شکسته باشند ولی واژه‌ها عامیانه نباشند. در سراسر متن یکدست بمان.",
    ),
    Register.FORMAL: (
        "رسمی (کتابی)",
        "فارسی معیار نوشتاری، روان و خوش‌آهنگ؛ بی‌واژهٔ ثقیل و جملهٔ اداری، چون باز هم قرار "
        "است شنیده شود.",
    ),
}

INTRO = (
    "تو نویسنده و پژوهشگر پادکست فارسی من هستی. می‌خواهم متن (اسکریپت) یک اپیزود را با "
    "هم آماده کنیم. هرچه از این اپیزود دارم پایین آمده: اطلاعات اپیزود، مشخصات متن، "
    "پیش‌نویس خودم و ایده‌هایی که برایش جمع کرده‌ام. قاعده‌های نوشتن و روند کار در انتهاست."
)

LADDER = (
    "هر موضوع در این پادکست می‌تواند در پنج اپیزود گفته شود، از پلهٔ ۱ تا ۵؛ هر پله "
    "ژرف‌تر، دقیق‌تر و انتزاعی‌تر از پلهٔ پیش، تا شنونده پله‌به‌پله تا عمق موضوع همراه بیاید."
)
LADDER_ABOVE = (
    "فرض کن شنونده پله‌های پیشین را شنیده است: پایه‌ها را دوباره درس نده، در حد یادآوری یک‌جمله‌ای."
)
LADDER_BELOW = "آنچه جایش در پله‌های بالاتر است، فقط اشاره کن."

HUMAN_VOICE = "\n".join(
    [
        "# صدای انسانی — مهم‌ترین قاعده",
        "لحن هرچه باشد، متن باید صدای یک آدم واقعی باشد، نه متنی ماشینی:",
        "- برای گوش بنویس، نه برای چشم: جمله‌های کوتاه و بلند در هم، با ریتم طبیعی گفتار. "
        "جملهٔ تودرتو و فهرست شماره‌دار در متن نهایی نیاید.",
        "- با «من» حرف بزن و شنونده را مستقیم خطاب کن. جاهایی که در پیش‌نویس از تجربه و نظر "
        "خودم گفته‌ام، با صدای خودم نگه دار.",
        "- کلیشه‌های متن‌های ماشینی ممنوع: شروع با «در دنیای امروز…» یا «تا حالا شده…؟»، "
        "«بیایید با هم…»، «در پایان می‌توان گفت…»، جمع‌بندی تکراری آخر هر بخش، سه‌تایی‌های "
        "تصنعی، صفت‌های پرطمطراق و تعریف‌های فرهنگ‌لغتی.",
        "- به جای ادعای کلی، مثال و تصویر و جزئیات مشخص بیاور.",
        "- گاهی مکث، تردید، شوخی کوچک یا پرسشی واقعی از شنونده، همان‌طور که آدم‌ها حرف "
        "می‌زنند؛ بی‌اغراق.",
        "- عددها و نام‌ها را طوری بنویس که راحت خوانده شوند.",
        "- فارسی درست با نیم‌فاصله‌های درست؛ واژهٔ فرنگی فقط وقتی معادل جاافتاده‌ای ندارد.",
    ]
)

MIXED_FORMATS = "این قالب‌ها را در یک اپیزود ترکیب کن و در ساختار پیشنهادی‌ات بگو هر کدام کجاست."

STEP_ONE = "## گام ۱ — بررسی و پیشنهاد (هنوز متن نهایی را ننویس)"
CHECK = (
    "درستی‌سنجی: هر ادعا، عدد، تاریخ، نام و نقل‌قولی را که در «پیش‌نویس من» و «ایده‌ها» "
    "آمده بسنج. هرجا نادرست، نادقیق یا محل بحث است بگو چه گفته‌ام، درستش چیست و از کجا "
    "می‌دانی. جایی که مطمئن نیستی صریح بگو؛ حدس را جای واقعیت ننشان."
)
RESEARCH = (
    "پژوهش: روی موضوع پژوهش کن و آنچه متن را غنی‌تر می‌کند پیشنهاد بده: مفهوم، مثال، "
    "داستان، یافتهٔ پژوهشی، دیدگاه مخالف؛ به اندازهٔ پلهٔ عمق و مخاطب. برای هر مورد مهم "
    "منبع بیاور."
)
OUTLINE = "ساختار: نقشهٔ اپیزود را بده: قلاب آغاز، بخش‌ها به ترتیب با زمان تقریبی هر کدام، و پایان."
CHANGES = (
    "فهرست تغییرها، جدا و روشن: «اصلاح‌ها» (کدام گفته‌ام درست شد و چرا)، «افزوده‌ها»، "
    "«حذف‌ها و جابه‌جایی‌ها»."
)
WAIT = "بعد بایست و منتظر تأیید یا نظر من بمان."
STEP_TWO = "\n".join(
    [
        "## گام ۲ — متن نهایی (فقط پس از تأیید من)",
        "متن کامل و آمادهٔ ضبط را بنویس، با همان تغییرهایی که تأیید کرده‌ام. اگر در این میان "
        "چیز تازه‌ای به نظرت رسید، اول بپرس.",
        "خروجی فقط خود متن باشد، بخش‌ها با تیتری کوتاه از هم جدا؛ نشانه‌های اجرایی مثل [مکث] "
        "یا [موسیقی] کم و فقط جایی که لازم است.",
    ]
)


@dataclass(frozen=True)
class DraftNote:
    note_id: int
    title: str
    body: str


@dataclass(frozen=True)
class IdeaMaterial:
    audio: bool
    name: str  # an audio idea's file name; "" for a text idea
    text: str  # the idea's text, or the transcript as paragraphs
    notes: tuple[str, ...] = ()  # my notes on an audio idea


@dataclass(frozen=True)
class SeasonMaterial:
    title: str
    summary: str = ""
    outline: str = ""
    # The season's other episodes: (title, depth), depth 0 where it was never set.
    others: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class ScriptMaterial:
    """What the episode holds, gathered by `services/script_prompt.py`."""

    title: str
    tags: tuple[str, ...] = ()
    season: SeasonMaterial | None = None
    notes: tuple[DraftNote, ...] = ()
    ideas: tuple[IdeaMaterial, ...] = ()
    # Linked audio ideas with nothing to read (no transcript, no notes): left out.
    unread_voices: tuple[str, ...] = ()


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


def _section(title: str, *lines: str) -> str:
    return "\n".join([title, *lines])


def _options[K](chosen: frozenset[K], table: dict[K, tuple[str, str]]) -> list[str]:
    return [f"- {label}: {guide}" for key, (label, guide) in table.items() if key in chosen]


def drafted(material: ScriptMaterial, brief: ScriptBrief) -> list[DraftNote]:
    """The notes that go in as my draft: those with text, not left out in the brief."""
    return [
        n
        for n in material.notes
        if n.note_id not in brief.left_out_notes and (n.title.strip() or n.body.strip())
    ]


def build_prompt(material: ScriptMaterial, brief: ScriptBrief) -> str:
    parts = [INTRO, _episode(material, brief), _specs(brief)]
    notes = drafted(material, brief)
    if notes:
        parts.append(_draft(notes))
    if material.ideas:
        parts.append(_ideas(material.ideas))
    parts.append(HUMAN_VOICE)
    parts.append(_process(has_mine=bool(notes or material.ideas)))
    return "\n\n".join(parts) + "\n"


def _episode(material: ScriptMaterial, brief: ScriptBrief) -> str:
    lines = [f"عنوان: {material.title}"]
    if material.tags:
        lines.append("برچسب‌ها: " + "، ".join(material.tags))
    if brief.about.strip():
        lines += ["", "## دربارهٔ اپیزود", brief.about.strip()]
    season = material.season
    if season is not None:
        lines += ["", f"## فصل «{season.title}»"]
        if season.summary.strip():
            lines += ["دربارهٔ فصل:", season.summary.strip()]
        if season.outline.strip():
            lines += ["ساختار فصل:", season.outline.strip()]
        if season.others:
            lines.append("اپیزودهای دیگر این فصل:")
            lines += [
                f"- {title} (پلهٔ عمق {_fa(depth)})" if depth else f"- {title}"
                for title, depth in season.others
            ]
    return _section("# اطلاعات اپیزود", *lines)


def _specs(brief: ScriptBrief) -> str:
    blocks: list[str] = []
    if brief.formats:
        lines = _options(brief.formats, FORMATS)
        if len(brief.formats) > 1:
            lines.append(
                "این قالب‌ها را در یک اپیزود ترکیب کن و در ساختار پیشنهادی‌ات بگو هر کدام کجاست."
            )
        blocks.append(_section("## قالب", *lines))
    if brief.minutes:
        blocks.append(
            _section(
                "## مدت",
                f"حدود {_fa(brief.minutes)} دقیقه، یعنی تقریباً "
                f"{_fa(brief.minutes * WORDS_PER_MINUTE)} کلمه "
                f"(با آهنگ معمول گفتار، حدود {_fa(WORDS_PER_MINUTE)} کلمه در دقیقه).",
            )
        )
    if brief.audiences:
        names = [label for key, label in AUDIENCES.items() if key in brief.audiences]
        more = " متن باید برای همهٔ این‌ها کار کند." if len(names) > 1 else ""
        blocks.append(_section("## مخاطب", "، ".join(names) + "." + more))
    name, guide = DEPTH_LEVELS[brief.depth]
    blocks.append(
        _section(
            f"## عمق: پلهٔ {_fa(brief.depth)} از {_fa(DEPTHS[-1])} — {name}",
            guide,
            LADDER,
            *([LADDER_ABOVE] if brief.depth > DEPTHS[0] else []),
            *([LADDER_BELOW] if brief.depth < DEPTHS[-1] else []),
        )
    )
    if brief.approaches:
        blocks.append(_section("## رویکرد", *_options(brief.approaches, APPROACHES)))
    if brief.moods:
        names = [label for key, label in MOODS.items() if key in brief.moods]
        blocks.append(
            _section(
                "## حال‌وهوا",
                "، ".join(names) + ". این حال‌وهوا را با انتخاب مثال‌ها، ریتم جمله‌ها و "
                "لحظه‌ها بساز، نه با صفت و علامت تعجب.",
            )
        )
    label, guide = REGISTERS[brief.register]
    blocks.append(_section(f"## زبان: {label}", guide))
    return "# مشخصات متن\n" + "\n\n".join(blocks)


def _draft(notes: list[DraftNote]) -> str:
    lines = [
        "متنی که خودم نوشته‌ام؛ ممکن است ناقص، پراکنده یا جاهایی نادرست باشد. ایده‌ها و "
        "صدای من را نگه دار، نه لزوماً جمله‌هایم را."
    ]
    for number, note in enumerate(notes, 1):
        title = note.title.strip() or f"یادداشت {_fa(number)}"
        lines += ["", f"## {title}", note.body.strip()]
    return _section("# پیش‌نویس من", *lines)


def _ideas(ideas: tuple[IdeaMaterial, ...]) -> str:
    lines = ["تکه‌هایی که در طول زمان برای این اپیزود جمع کرده‌ام، نوشته یا ضبط‌شده."]
    for number, idea in enumerate(ideas, 1):
        if idea.audio:
            lines += ["", f"## ایدهٔ صوتی {_fa(number)} — {idea.name}"]
            if idea.text.strip():
                lines += [
                    "(متن پیاده‌شده از صدای خودم؛ ممکن است خطای رونویسی داشته باشد)",
                    idea.text.strip(),
                ]
            if idea.notes:
                lines.append("یادداشت‌هایم روی این صوت:")
                lines += [f"- {note}" for note in idea.notes]
        else:
            lines += ["", f"## ایدهٔ متنی {_fa(number)}", idea.text.strip()]
    return _section("# ایده‌ها", *lines)


def _process(has_mine: bool) -> str:
    steps = [CHECK, RESEARCH, OUTLINE, CHANGES] if has_mine else [RESEARCH, OUTLINE, CHANGES]
    numbered = [f"{_fa(i)}. {step}" for i, step in enumerate(steps, 1)]
    return "\n".join(["# روند کار", STEP_ONE, *numbered, WAIT, "", STEP_TWO])
