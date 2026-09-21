"""Developer-only mock data: fills an empty workspace so every screen has something to show.

Not part of the app and not imported by it. Run it from the repo root with the project venv:

    .venv\\Scripts\\python scripts\\seed_mock_data.py            # create
    .venv\\Scripts\\python scripts\\seed_mock_data.py --clear     # remove exactly what it created

Everything written is listed in the `dev.mock_data` setting, so `--clear` deletes the mock
rows and the generated audio files and leaves anything real in the workspace untouched.

Audio is synthesised with the bundled ffmpeg into `<data dir>/mock_audio`, so the player,
the waveform and the seek path all work on real files.
"""

import argparse
import subprocess
import sys
from collections.abc import Iterable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine

from podcast_workspace.audio.ffmpeg import NO_WINDOW, require_ffmpeg
from podcast_workspace.domain.entities import (
    Episode,
    EpisodeNote,
    EpisodeStatus,
    IdeaNote,
    Tag,
    TimestampNote,
    Transcript,
    TranscriptSegment,
    Voice,
)
from podcast_workspace.domain.errors import NotFoundError
from podcast_workspace.paths import data_dir, database_path
from podcast_workspace.repositories.db import engine_for_file, make_session_factory, migrate
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.audio_probe import probe

MANIFEST_KEY = "dev.mock_data"
AUDIO_DIR_NAME = "mock_audio"

NOW = datetime.now(UTC)


def ago(days: float = 0, hours: float = 0) -> datetime:
    return NOW - timedelta(days=days, hours=hours)


# --------------------------------------------------------------------------- tags

# (key, name, color, parent key)
TAGS: tuple[tuple[str, str, str, str | None], ...] = (
    ("topic", "موضوع", "#3b82f6", None),
    ("city", "شهر", "#10b981", "topic"),
    ("history", "تاریخ", "#f59e0b", "topic"),
    ("philosophy", "فلسفه", "#8b5cf6", "topic"),
    ("tech", "تکنولوژی", "#6366f1", "topic"),
    ("psych", "روانشناسی", "#ec4899", "topic"),
    ("source", "منبع", "#14b8a6", None),
    ("field", "ضبط میدانی", "#84cc16", "source"),
    ("guest", "مصاحبه مهمان", "#f97316", "source"),
    ("personal", "یادداشت شخصی", "#ef4444", "source"),
    ("state", "وضعیت", "#6b7280", None),
    ("needs_edit", "نیاز به تدوین", "#f43f5e", "state"),
    ("needs_research", "پژوهش لازم", "#0ea5e9", "state"),
    ("ready", "آماده انتشار", "#22c55e", "state"),
    ("s1", "فصل اول", "#94a3b8", None),
    ("s2", "فصل دوم", "#a855f7", None),
)

# --------------------------------------------------------------------------- audio

# (key, file name, seconds, base frequency, ffmpeg encoder args)
AUDIO: tuple[tuple[str, str, int, int, tuple[str, ...]], ...] = (
    ("bookshop", "کتاب‌فروشی-انقلاب.mp3", 150, 190, ("-c:a", "libmp3lame", "-b:a", "96k")),
    ("night", "bale_voice_2026-09-12.ogg", 45, 240, ("-c:a", "libvorbis", "-q:a", "3")),
    ("guest", "مصاحبه-آقای-رحیمی.m4a", 200, 160, ("-c:a", "aac", "-b:a", "96k")),
    ("miktest", "mic-test-02.wav", 20, 330, ("-c:a", "pcm_s16le")),
    ("phone", "bale_voice_2026-09-17.opus", 70, 210, ("-c:a", "libopus", "-b:a", "48k")),
    ("radio", "روایت-اول-رادیو.mp3", 120, 175, ("-c:a", "libmp3lame", "-b:a", "128k")),
)


ENCODERS = {name: encoder for _, name, _, _, encoder in AUDIO}

VOICE_TAGS: dict[str, tuple[str, ...]] = {
    "bookshop": ("field", "city", "s2"),
    "night": ("personal", "city"),
    "guest": ("guest", "history"),
    "miktest": (),
    "phone": ("personal", "tech"),
    "radio": ("needs_edit", "history", "s2"),
}


def synthesise(path: Path, seconds: int, frequency: int) -> None:
    """A tone with a speech-like amplitude envelope, so the waveform is not a flat block."""
    args = [
        str(require_ffmpeg()),
        "-hide_banner",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=44100:duration={seconds}",
        "-af",
        "volume='0.12+0.88*abs(sin(2*PI*t/3.7))*abs(sin(2*PI*t/0.9))':eval=frame",
        "-ac",
        "1",
    ]
    args += [*ENCODERS[path.name], str(path)]
    subprocess.run(args, check=True, capture_output=True, creationflags=NO_WINDOW)


# --------------------------------------------------------------------------- content

IDEAS: tuple[tuple[str, tuple[str, ...], float], ...] = (
    (
        "شهر شب‌ها یک زبان دیگر حرف می‌زند. صدای کرکره‌ها، صدای جارو، صدای موتورهای پیک. "
        "شاید کل یک قسمت را بشود فقط با صدای شب ساخت.",
        ("city", "needs_research"),
        1.2,
    ),
    (
        "کتاب‌فروش خیابان انقلاب می‌گفت پنجاه سال است سر یک چهارراه ایستاده و مشتری‌هایش "
        "سه نسل عوض شده‌اند. این جمله باید جایی در قسمت بیاید.",
        ("city", "field"),
        2.5,
    ),
    (
        "رادیو اولین شبکه اجتماعی بود: همه هم‌زمان یک چیز را می‌شنیدند و فردا صبح درباره‌اش "
        "حرف می‌زدند. تفاوتش با الان فقط در سرعت نیست، در هم‌زمانی است.",
        ("history", "tech"),
        5.0,
    ),
    (
        "ترس از ماشین‌های جدید همیشه تکرار می‌شود: از ماشین بافندگی تا هوش مصنوعی. "
        "دنبال نقل قول‌های روزنامه‌های قدیمی بگرد.",
        ("tech", "philosophy", "needs_research"),
        7.0,
    ),
    (
        "آپارتمان‌های بلند، همسایه‌های نادیده. سه نفر را پیدا کن که ده سال در یک ساختمان "
        "زندگی کرده‌اند و اسم همسایه روبه‌رویی را نمی‌دانند.",
        ("psych", "city"),
        8.5,
    ),
    ("تیتراژ قسمت جدید را با صدای ضبط‌شده‌ی باران روی حلبی امتحان کن.", ("personal",), 0.4),
    (
        "یک قسمت کوتاه درباره‌ی ساعت‌های عمومی شهر: چه کسی آن‌ها را کوک می‌کند؟",
        ("city", "history"),
        11.0,
    ),
    (
        "جمله‌ی خوب برای شروع: «حافظه‌ی یک خیابان در ویترین مغازه‌هایش نگه داشته می‌شود.»",
        ("history",),
        14.0,
    ),
    (
        "برای فصل دوم حداقل دو مهمان لازم است. لیست پیشنهادی را همین هفته بنویس.",
        ("guest", "s2"),
        3.2,
    ),
    (
        "پرسش باز برای پایان قسمت: اگر فردا همه‌ی چراغ‌های شهر خاموش شوند، اول کجا را روشن می‌کنی؟",
        ("philosophy", "city"),
        0.8,
    ),
)

# (key, title, status, next action, tags, updated days ago, last opened hours ago or None)
EPISODES: tuple[tuple[str, str, EpisodeStatus, str, tuple[str, ...], float, float | None], ...] = (
    (
        "night",
        "شب‌گردی: شهر وقتی می‌خوابد",
        EpisodeStatus.IDEA,
        "سه سؤال اصلی قسمت را بنویس",
        ("city", "needs_research", "s2"),
        1.0,
        None,
    ),
    (
        "towers",
        "تنهایی در آپارتمان‌های بلند",
        EpisodeStatus.IDEA,
        "با سه نفر از ساکن‌های برج حرف بزن",
        ("psych", "city", "needs_research"),
        8.0,
        None,
    ),
    (
        "bookshop",
        "کتاب‌فروشی‌های خیابان انقلاب",
        EpisodeStatus.OUTLINE,
        "ضبط میدانی جمعه ساعت ۵ عصر",
        ("city", "field", "s2"),
        0.3,
        3.0,
    ),
    (
        "radio",
        "رادیو؛ اولین شبکه اجتماعی",
        EpisodeStatus.RECORDED,
        "صداها را برش بزن و بهترین ده دقیقه را جدا کن",
        ("history", "tech", "needs_edit", "s2"),
        4.0,
        30.0,
    ),
    (
        "street",
        "حافظه‌ی جمعی یک خیابان",
        EpisodeStatus.SCRIPT_READY,
        "متن نهایی را با صدای بلند بخوان و زمان بگیر",
        ("history", "city", "s1"),
        21.0,
        None,
    ),
    (
        "fears",
        "ترس‌های قدیمی از ماشین‌های جدید",
        EpisodeStatus.EDITED,
        "موسیقی تیتراژ را جایگزین کن",
        ("tech", "philosophy", "needs_edit", "s1"),
        12.0,
        None,
    ),
    (
        "zero",
        "قسمت صفر: چرا این پادکست؟",
        EpisodeStatus.PUBLISHED,
        "",
        ("s1", "ready"),
        45.0,
        None,
    ),
)

# episode key -> (voice keys, idea indexes)
LINKS: dict[str, tuple[tuple[str, ...], tuple[int, ...]]] = {
    "bookshop": (("bookshop",), (1, 7)),
    "radio": (("radio", "guest"), (2,)),
    "night": (("night",), (0, 9)),
    "fears": (("phone",), (3,)),
    "towers": ((), (4,)),
    "street": ((), (6, 7)),
}

# episode key -> (title, body)
EPISODE_NOTES: dict[str, tuple[tuple[str, str], ...]] = {
    "bookshop": (
        (
            "طرح اولیه",
            "شروع با صدای خیابان · معرفی سه کتاب‌فروشی · گفت‌وگوی کوتاه با فروشنده‌ی قدیمی\n"
            "میانه: چرا همه‌ی کتاب‌فروشی‌ها یک خیابان را انتخاب کردند؟\n"
            "پایان: ویترینی که هنوز کتاب سال ۱۳۵۷ را دارد.",
        ),
        (
            "سؤال‌های مصاحبه",
            "۱. اولین روزی که این مغازه را باز کردید یادتان هست؟\n"
            "۲. کتابی هست که دیگر کسی نمی‌خرد؟\n"
            "۳. مشتری‌ها چه چیزی را عوض کرده‌اند، نه شما؟",
        ),
    ),
    "radio": (
        (
            "متن راوی",
            "«یک شب زمستان سال ۱۳۱۹، صدایی از یک جعبه‌ی چوبی بیرون آمد و خانه‌ها را به هم وصل کرد.»\n"
            "بعد از این جمله سه ثانیه سکوت، بعد آرشیو.",
        ),
    ),
    "street": (
        (
            "اسکریپت نهایی",
            "نسخه‌ی خوانده‌شده ۱۸ دقیقه شد؛ دو دقیقه بیشتر از هدف. بخش میانی درباره‌ی پلاک‌ها "
            "را می‌شود کوتاه کرد.",
        ),
        ("کارهای باقی‌مانده", "افکت صدای قدم · تصحیح تلفظ اسم خیابان · گرفتن اجازه‌ی آرشیو"),
    ),
}

# voice key -> ((position seconds, text), ...)
TIMESTAMP_NOTES: dict[str, tuple[tuple[int, str], ...]] = {
    "bookshop": (
        (8, "صدای زمینه خیلی خوب است، همین را برای تیتراژ نگه دار"),
        (47, "اینجا جمله‌ی «سه نسل مشتری» گفته شد — حتماً در قسمت بیاید"),
        (96, "نویز موتور؛ این چند ثانیه باید حذف شود"),
    ),
    "guest": (
        (25, "مهمان تازه گرم شده، از اینجا به بعد قابل استفاده است"),
        (140, "نقل قول اصلی مصاحبه همین‌جاست"),
    ),
    "radio": (
        (12, "شروع را دوباره ضبط کن، نفس‌نفس می‌زنم"),
        (64, "این برداشت بهترین است"),
    ),
    "phone": ((5, "ایده‌ی وسط خیابان؛ بعداً پیاده‌سازی شود"),),
}

TRANSCRIPTS: dict[str, tuple[tuple[int, int, str], ...]] = {
    "night": (
        (0, 4200, "یادداشت شبانه، دوازدهم شهریور."),
        (4200, 11500, "امشب از خیابان که رد می‌شدم فهمیدم شهر بعد از نیمه‌شب صدای دیگری دارد."),
        (11500, 20000, "صدای کرکره‌ها، صدای جارو، و یک موتور که از دور می‌آید و رد می‌شود."),
        (20000, 30500, "شاید بشود یک قسمت کامل فقط با همین صداها ساخت، بدون هیچ روایتی."),
        (30500, 44000, "اگر فردا یادم رفت، همین فایل را دوباره گوش کن."),
    ),
    "radio": (
        (0, 6000, "برداشت اول، قسمت رادیو."),
        (6000, 15500, "یک شب زمستان سال هزار و سیصد و نوزده، صدایی از یک جعبه‌ی چوبی بیرون آمد."),
        (15500, 26000, "مردم دور آن جعبه جمع شدند، همان‌طور که امروز دور یک صفحه‌ی روشن جمع می‌شویم."),
        (26000, 38000, "رادیو اولین شبکه‌ی اجتماعی بود؛ همه هم‌زمان یک چیز را می‌شنیدند."),
        (38000, 52000, "فردای آن شب، حرف همه‌ی شهر یکی بود. این هم‌زمانی را ما از دست داده‌ایم."),
        (52000, 66000, "در این قسمت دنبال همان هم‌زمانی گم‌شده می‌گردیم."),
        (66000, 80000, "با آرشیو صدای سازمان، و با خاطره‌ی کسانی که آن شب‌ها را یادشان است."),
        (80000, 95000, "اسم این قسمت را گذاشته‌ام: رادیو، اولین شبکه‌ی اجتماعی."),
    ),
}


# --------------------------------------------------------------------------- seeding


def seed(uow: UnitOfWork) -> dict[str, list[int] | list[str]]:
    audio_dir = data_dir() / AUDIO_DIR_NAME
    audio_dir.mkdir(parents=True, exist_ok=True)

    tags: dict[str, int] = {}
    for key, name, color, parent in TAGS:
        tag = uow.tags.add(Tag(name=name, color=color, parent_id=tags.get(parent or "")))
        assert tag.id is not None
        tags[key] = tag.id

    def tag_ids(keys: Iterable[str]) -> set[int]:
        return {tags[key] for key in keys}

    voices: dict[str, int] = {}
    files: list[str] = []
    for index, (key, filename, seconds, frequency, _) in enumerate(AUDIO):
        path = audio_dir / filename
        print(f"  ffmpeg → {filename}")
        synthesise(path, seconds, frequency)
        files.append(str(path))
        info = probe(path)
        voice = uow.voices.add(
            Voice(
                file_path=str(path),
                duration_ms=info.duration_ms,
                format=info.format,
                imported_at=ago(days=index * 2.5 + 0.5),
                tag_ids=tag_ids(VOICE_TAGS[key]),
            )
        )
        assert voice.id is not None
        voices[key] = voice.id

    ideas: list[int] = []
    for text, keys, days in IDEAS:
        idea = uow.idea_notes.add(
            IdeaNote(
                text=text,
                created_at=ago(days=days + 0.5),
                updated_at=ago(days=days),
                tag_ids=tag_ids(keys),
            )
        )
        assert idea.id is not None
        ideas.append(idea.id)

    episodes: dict[str, int] = {}
    for key, title, status, next_action, keys, days, opened in EPISODES:
        voice_keys, idea_indexes = LINKS.get(key, ((), ()))
        episode = uow.episodes.add(
            Episode(
                title=title,
                status=status,
                next_action=next_action,
                created_at=ago(days=days + 14),
                updated_at=ago(days=days),
                last_opened_at=None if opened is None else ago(hours=opened),
                tag_ids=tag_ids(keys),
                voice_ids={voices[v] for v in voice_keys},
                idea_note_ids={ideas[i] for i in idea_indexes},
            )
        )
        assert episode.id is not None
        episodes[key] = episode.id

    episode_notes: list[int] = []
    for key, notes in EPISODE_NOTES.items():
        for offset, (title, body) in enumerate(notes):
            note = uow.episode_notes.add(
                EpisodeNote(
                    episode_id=episodes[key],
                    title=title,
                    body=body,
                    created_at=ago(days=offset + 2),
                    updated_at=ago(days=offset + 1),
                )
            )
            assert note.id is not None
            episode_notes.append(note.id)

    timestamp_notes: list[int] = []
    for key, notes in TIMESTAMP_NOTES.items():
        for position, text in notes:
            note = uow.timestamp_notes.add(
                TimestampNote(
                    voice_id=voices[key],
                    position_ms=position * 1000,
                    text=text,
                    created_at=ago(days=1),
                )
            )
            assert note.id is not None
            timestamp_notes.append(note.id)

    transcripts: list[int] = []
    for key, segments in TRANSCRIPTS.items():
        transcript = uow.transcripts.add(
            Transcript(
                voice_id=voices[key],
                segments=[TranscriptSegment(a, b, t) for a, b, t in segments],
                language="fa",
                model="large-v3-turbo",
                created_at=ago(days=1),
            )
        )
        assert transcript.id is not None
        transcripts.append(transcript.id)

    return {
        "tags": list(tags.values()),
        "voices": list(voices.values()),
        "ideas": ideas,
        "episodes": list(episodes.values()),
        "episode_notes": episode_notes,
        "timestamp_notes": timestamp_notes,
        "transcripts": transcripts,
        "files": files,
    }


# --------------------------------------------------------------------------- clearing


def clear(uow: UnitOfWork, manifest: dict[str, list]) -> None:
    """Delete children before parents so the FTS triggers fire for every row."""
    order = (
        ("transcripts", uow.transcripts),
        ("timestamp_notes", uow.timestamp_notes),
        ("episode_notes", uow.episode_notes),
        ("episodes", uow.episodes),
        ("ideas", uow.idea_notes),
        ("voices", uow.voices),
        ("tags", uow.tags),
    )
    for name, repo in order:
        for entity_id in manifest.get(name, []):
            # Already gone means the user deleted it in the app; that is fine.
            with suppress(NotFoundError):
                repo.delete(entity_id)

    for raw in manifest.get("files", []):
        Path(raw).unlink(missing_ok=True)
    audio_dir = data_dir() / AUDIO_DIR_NAME
    if audio_dir.is_dir() and not any(audio_dir.iterdir()):
        audio_dir.rmdir()


# --------------------------------------------------------------------------- entry point


def finalize(engine: Engine) -> None:
    """Fold the write-ahead log into workspace.db, then close the engine.

    The database runs in WAL mode, so committing alone leaves the new rows in
    `workspace.db-wal`. The app opens the database from another process and can start
    from the pre-seed snapshot and show an empty workspace; checkpointing here puts
    everything in the database file itself, where it cannot be missed.
    """
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="remove the mock data again")
    parser.add_argument("--force", action="store_true", help="seed even if mock data exists")
    args = parser.parse_args()

    created: dict[str, list] = {}
    engine = engine_for_file(database_path())
    try:
        migrate(engine)
        session_factory = make_session_factory(engine)

        with UnitOfWork(session_factory) as uow:
            manifest = uow.settings.get(MANIFEST_KEY)

            if args.clear:
                if manifest is None:
                    print("No mock data recorded; nothing to remove.")
                    return 0
                clear(uow, manifest)
                uow.settings.set(MANIFEST_KEY, None)
                print("Mock data removed.")
                return 0

            if manifest is not None and not args.force:
                print("Mock data is already there. --clear removes it, --force adds another set.")
                return 1

            print(f"Seeding {database_path()}")
            created = seed(uow)
            uow.settings.set(MANIFEST_KEY, created)
    finally:
        finalize(engine)

    counts = ", ".join(f"{len(v)} {k}" for k, v in created.items() if k != "files")
    print(f"Done: {counts}.")
    print("Close the app if it is open, then start it again to see the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
