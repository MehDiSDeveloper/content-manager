"""The Bale bot's search: reaching your own ideas from the phone.

Three ways in, all ending in the same result message:
- «؟ خواب #سلامت» — a message starting with ؟ (or ?) searches at once;
- /search — the most-used tags as buttons, and the next message is taken as the words;
- «🔍 جستجو» under the «save it?» question — that text is searched instead of saved.

Hashtags in a query pick tags (the nearest existing name, so a typo still finds it); every
other word is looked for in titles, tag names and content (`domain/pocket_search.py`).

A result message lists five per page, numbered across pages. A number opens its item: an
idea comes back as its full text, a voice as the audio itself (uploaded once, then resent by
Bale's file id). The voice goes with its pauses trimmed the way the player trims them, at
the remembered pause setting (`services/voice_render.py`), and the note times in its
caption follow the trimmed audio. One whose pauses cannot be read goes as it is.

Tag buttons narrow the results in the same message, ✖ loosens them again; taking the last
one away leads back to the tag menu.

Searches are remembered per message, in memory only: after a restart their tag and page
buttons ask for a new search. Opening an item still works, since its button names the item.
"""

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from podcast_workspace.audio.render import trimmed_ms
from podcast_workspace.audio.silence import Span, total_ms
from podcast_workspace.domain.bot_input import (
    ItemKind,
    ItemRef,
    parse_message,
    persian_digits,
    shorten,
)
from podcast_workspace.domain.errors import NotFoundError
from podcast_workspace.domain.lifecycle import ArchiveScope
from podcast_workspace.domain.list_filter import parse_list_filter
from podcast_workspace.domain.pocket_search import Entry, Found, find, narrowing_tags
from podcast_workspace.domain.text import make_snippet
from podcast_workspace.integrations.bale_api import (
    MAX_UPLOAD_BYTES,
    BaleApiError,
    BaleClient,
    BaleError,
)
from podcast_workspace.services.content_services import (
    IdeaService,
    TimestampNoteService,
    VoiceService,
)
from podcast_workspace.services.tag_service import TagService
from podcast_workspace.services.transcription import TranscriptionService
from podcast_workspace.services.voice_render import trimmed_for_sending

log = logging.getLogger(__name__)

PREFIX = "s"  # callback data: s|o|<kind>|<id> open, s|t|<tag id> tag, s|p|<page> page
PAGE_SIZE = 5
MENU_TAGS = 10
NARROWING_TAGS = 4
TAG_COLUMNS = 2
MAX_SEARCHES = 20
MAX_MESSAGE = 3500  # Bale allows 4096; leaves room for the tag line
MAX_CAPTION = 1000  # Bale allows 1024
_UPLOAD_FIELDS = {".ogg": "voice", ".opus": "voice", ".mp3": "audio", ".m4a": "audio"}

T_MENU = "🔍 جستجو در ایده‌ها\nکلمه‌ای بفرستید{tags}."
T_MENU_TAGS = " یا برچسبی را بزنید"
T_MENU_TIP = "میان‌بر: پیامی که با ؟ شروع شود جستجو می‌شود، مثلاً «؟ خواب #سلامت»."
T_COUNT = "{n} مورد"
T_PAGE = "صفحهٔ {page} از {pages}"
T_NOTHING = "چیزی پیدا نشد."
T_LOOSEN = "با ✖ برچسبی را بردارید تا دامنه بازتر شود."
T_BUTTON_PREV = "قبلی"
T_BUTTON_NEXT = "بعدی"
T_EXPIRED = "این جستجو قدیمی شده؛ دوباره جستجو کنید."
T_GONE = "این مورد دیگر در فضای کاری نیست."
T_SENDING = "در حال فرستادن…"
T_FILE_MISSING = "فایل این ایدهٔ صوتی روی رایانه پیدا نشد:\n{name}"
T_FILE_TOO_LARGE = "این فایل بیش از ۵۰ مگابایت است و بازو نمی‌تواند آن را بفرستد:\n{name}"
T_SEND_FAILED = "فرستادن فایل ممکن نشد؛ دوباره امتحان کنید."
T_TAGS = "🏷 {names}"
T_ARCHIVED = "🗄 بایگانی‌شده"
T_TRIMMED = "✂️ مکث‌ها کوتاه شد: {saved} کمتر"
ICON_IDEA = "💡"
ICON_VOICE = "🎙"
ICON_ARCHIVED = "🗄"

Send = Callable[[int, str, dict[str, Any] | None], int | None]
Edit = Callable[[int, int, str, dict[str, Any] | None], bool]
Answer = Callable[[str, str | None, bool], None]


@dataclass(frozen=True)
class _Item:
    ref: ItemRef
    label: str  # how the result list names it
    archived: bool


@dataclass
class _Search:
    words: str
    tag_ids: frozenset[int]
    found: list[Found[_Item]] = field(default_factory=list)
    page: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.words and not self.tag_ids

    @property
    def pages(self) -> int:
        return max(1, -(-len(self.found) // PAGE_SIZE))


def _clock(ms: int) -> str:
    seconds = ms // 1000
    return persian_digits(f"{seconds // 60}:{seconds % 60:02d}")


def _split_idea(text: str) -> tuple[str, str]:
    """An idea's title (its first line) and the rest, so a snippet never repeats the title."""
    title, _, rest = text.strip().partition("\n")
    return title.strip(), rest.strip()


def _button(text: str, *data: object) -> dict[str, str]:
    return {"text": text, "callback_data": "|".join(str(d) for d in (PREFIX, *data))}


class SearchFlow:
    """Runs on the bot's worker thread, replying through the worker's own send/edit/answer."""

    def __init__(
        self,
        client: BaleClient,
        send: Send,
        edit: Edit,
        answer: Answer,
        ideas: IdeaService,
        voices: VoiceService,
        tags: TagService,
        notes: TimestampNoteService,
        transcripts: TranscriptionService,
        keep_pause_ms: Callable[[], int],
    ) -> None:
        self._client = client
        self._send = send
        self._edit = edit
        self._answer = answer
        self._ideas = ideas
        self._voices = voices
        self._tags = tags
        self._notes = notes
        self._transcripts = transcripts
        self._keep_pause_ms = keep_pause_ms
        self._searches: dict[tuple[int, int], _Search] = {}  # by (chat, message)
        # What Bale already has, by (voice id, pause setting, file time): the upload field,
        # Bale's file id, and the stretches that upload left out.
        self._sent: dict[tuple[int, int, int], tuple[str, str, tuple[Span, ...]]] = {}

    # entry points ----------------------------------------------------------------------
    def menu(self, chat_id: int) -> None:
        self._show(chat_id, _Search("", frozenset()))

    def search(self, chat_id: int, text: str, reuse_message_id: int | None = None) -> None:
        self._show(chat_id, self._parse(text), reuse_message_id)

    def on_callback(self, callback_id: str, chat_id: int, message_id: int, args: list[str]) -> None:
        try:
            match args:
                case ["o", kind, item_id]:
                    self._open(callback_id, chat_id, ItemRef(ItemKind(kind), int(item_id)))
                case ["t", tag_id]:
                    self._toggle_tag(callback_id, chat_id, message_id, int(tag_id))
                case ["p", page]:
                    self._turn_page(callback_id, chat_id, message_id, int(page))
                case _:
                    self._answer(callback_id, None, False)
        except ValueError:
            self._answer(callback_id, None, False)

    # searching -------------------------------------------------------------------------
    def _parse(self, text: str) -> _Search:
        """Hashtags become tags (the nearest existing one); a name matching no tag at all is
        kept as a word, so it can still turn up in titles and content."""
        parsed = parse_message(text)
        words = [parsed.text]
        tag_ids: set[int] = set()
        for name in parsed.tags:
            tag = self._tags.find_exact(name) or next(
                (m.tag for m in self._tags.suggest(name, limit=1)), None
            )
            if tag is not None and tag.id is not None:
                tag_ids.add(tag.id)
            else:
                words.append(name)
        return _Search(" ".join(w for w in words if w), frozenset(tag_ids))

    def _entries(self) -> list[Entry[_Item]]:
        """Every idea and voice outside the trash, archived ones included (and marked)."""
        names = {t.id: t.name for t in self._tags.list_all()}
        entries: list[Entry[_Item]] = []
        for idea in self._ideas.list_all(ArchiveScope.ALL):
            assert idea.id is not None
            title, rest = _split_idea(idea.text)
            entries.append(
                Entry(
                    _Item(ItemRef(ItemKind.IDEA, idea.id), shorten(title, 60), idea.archived),
                    title,
                    rest,
                    frozenset(idea.tag_ids),
                    tuple(names[t] for t in idea.tag_ids if t in names),
                    idea.updated_at,
                )
            )
        notes = self._notes.texts_by_voice()
        transcripts = self._transcripts.texts()
        for voice in self._voices.list_all(ArchiveScope.ALL):
            assert voice.id is not None
            name = Path(voice.file_path).name
            content = "\n".join(t for t in (notes.get(voice.id), transcripts.get(voice.id)) if t)
            label = f"{shorten(name, 45)} · {_clock(voice.duration_ms)}"
            entries.append(
                Entry(
                    _Item(ItemRef(ItemKind.VOICE, voice.id), label, voice.archived),
                    name,
                    content,
                    frozenset(voice.tag_ids),
                    tuple(names[t] for t in voice.tag_ids if t in names),
                    voice.imported_at,
                )
            )
        return entries

    def _show(self, chat_id: int, search: _Search, message_id: int | None = None) -> None:
        """Run `search` and show it: in `message_id` when given and still editable."""
        if not search.is_empty:
            search.found = find(self._entries(), search.words, search.tag_ids)
        text, markup = self._render(search)
        if message_id is None or not self._edit(chat_id, message_id, text, markup):
            message_id = self._send(chat_id, text, markup)
        if message_id is None:
            return
        self._searches.pop((chat_id, message_id), None)  # re-inserted as the newest
        self._searches[(chat_id, message_id)] = search
        while len(self._searches) > MAX_SEARCHES:
            self._searches.pop(next(iter(self._searches)))

    def _toggle_tag(self, callback_id: str, chat_id: int, message_id: int, tag_id: int) -> None:
        current = self._searches.get((chat_id, message_id))
        if current is None:
            self._answer(callback_id, T_EXPIRED, False)
            return
        self._answer(callback_id, None, False)
        tag_ids = current.tag_ids ^ {tag_id}
        if self._tags.get(tag_id) is None:  # deleted since; just leave it out
            tag_ids -= {tag_id}
        self._show(chat_id, _Search(current.words, tag_ids), message_id)

    def _turn_page(self, callback_id: str, chat_id: int, message_id: int, page: int) -> None:
        current = self._searches.get((chat_id, message_id))
        if current is None:
            self._answer(callback_id, T_EXPIRED, False)
            return
        self._answer(callback_id, None, False)
        current.page = max(0, min(page, current.pages - 1))
        self._edit(chat_id, message_id, *self._render(current))

    # rendering -------------------------------------------------------------------------
    def _render(self, search: _Search) -> tuple[str, dict[str, Any]]:
        names = {t.id: t.name for t in self._tags.list_all()}
        if search.is_empty:
            top = [t.id for t in self._tags.most_used(MENU_TAGS) if t.id is not None]
            text = T_MENU.format(tags=T_MENU_TAGS if top else "") + "\n\n" + T_MENU_TIP
            return text, {"inline_keyboard": self._tag_rows(top, {}, names)}

        what = [f"«{search.words}»"] if search.words else []
        what += [
            f"#{names[t]}"
            for t in sorted(search.tag_ids, key=lambda t: names.get(t, ""))
            if t in names
        ]
        lines = ["🔍 " + " ".join(what)]
        rows: list[list[dict[str, str]]] = []
        if not search.found:
            lines += ["", T_NOTHING]
            if search.tag_ids:
                lines.append(T_LOOSEN)
        else:
            count = T_COUNT.format(n=persian_digits(len(search.found)))
            if search.pages > 1:
                count += " · " + T_PAGE.format(
                    page=persian_digits(search.page + 1), pages=persian_digits(search.pages)
                )
            lines.append(count)
            terms = list(parse_list_filter(search.words).free_terms)
            first = search.page * PAGE_SIZE
            numbers: list[dict[str, str]] = []
            for number, found in enumerate(search.found[first : first + PAGE_SIZE], first + 1):
                item = found.entry.key
                icon = ICON_IDEA if item.ref.kind is ItemKind.IDEA else ICON_VOICE
                mark = f" {ICON_ARCHIVED}" if item.archived else ""
                lines += ["", f"{persian_digits(number)}. {icon} {item.label}{mark}"]
                if found.in_content:
                    lines.append(f"    «{make_snippet(found.entry.content, terms, 70)}»")
                numbers.append(
                    _button(persian_digits(number), "o", item.ref.kind.value, item.ref.item_id)
                )
            rows.append(numbers)
        narrowing = narrowing_tags(search.found, search.tag_ids, NARROWING_TAGS)
        rows += self._tag_rows(
            [t for t, _ in narrowing], dict(narrowing), names, chosen=search.tag_ids
        )
        paging: list[dict[str, str]] = []
        if search.page > 0:
            paging.append(_button(T_BUTTON_PREV, "p", search.page - 1))
        if search.page < search.pages - 1:
            paging.append(_button(T_BUTTON_NEXT, "p", search.page + 1))
        if paging:
            rows.append(paging)
        return "\n".join(lines), {"inline_keyboard": rows}

    @staticmethod
    def _tag_rows(
        offered: list[int],
        counts: dict[int, int],
        names: dict[int | None, str],
        chosen: frozenset[int] = frozenset(),
    ) -> list[list[dict[str, str]]]:
        """Chosen tags first (✖ takes one away), then the offered ones (tap adds one)."""
        buttons = [_button(f"✖ {names[t]}", "t", t) for t in sorted(chosen) if t in names]
        for tag_id in offered:
            if tag_id in names:
                n = counts.get(tag_id)
                label = f"{names[tag_id]} ({persian_digits(n)})" if n else names[tag_id]
                buttons.append(_button(f"🏷 {label}", "t", tag_id))
        return [buttons[i : i + TAG_COLUMNS] for i in range(0, len(buttons), TAG_COLUMNS)]

    # opening ---------------------------------------------------------------------------
    def _open(self, callback_id: str, chat_id: int, ref: ItemRef) -> None:
        try:
            item = (
                self._ideas.get(ref.item_id)
                if ref.kind is ItemKind.IDEA
                else self._voices.get(ref.item_id)
            )
        except NotFoundError:
            item = None
        if item is None or item.in_trash:
            self._answer(callback_id, T_GONE, True)
            return
        extra = []
        names = sorted(t.name for t in self._tags.by_ids(item.tag_ids))
        if names:
            extra.append(T_TAGS.format(names="، ".join(names)))
        if item.archived:
            extra.append(T_ARCHIVED)
        if ref.kind is ItemKind.IDEA:
            self._answer(callback_id, None, False)
            body = item.text if len(item.text) <= MAX_MESSAGE else item.text[:MAX_MESSAGE] + "…"
            self._send(chat_id, "\n\n".join([f"{ICON_IDEA} {body}", *extra]), None)
            return
        self._answer(callback_id, T_SENDING, False)
        path = Path(item.file_path)
        try:
            key = (ref.item_id, self._keep_pause_ms(), path.stat().st_mtime_ns)
        except OSError:
            self._send(chat_id, T_FILE_MISSING.format(name=path.name), None)
            return
        cached = self._sent.get(key)
        if cached is not None:
            upload_field, file_id, cuts = cached
            caption = self._caption(ref.item_id, path, item.duration_ms, cuts, extra)
            try:
                self._client.send_file(chat_id, upload_field, file_id, caption)
                return
            except BaleError:
                log.warning("resending by file id failed; uploading again", exc_info=True)
                self._sent.pop(key, None)
        with tempfile.TemporaryDirectory(prefix="bale-send-") as folder:
            try:
                upload, cuts = trimmed_for_sending(path, key[1], Path(folder))
            except Exception:  # pauses that cannot be read must not keep the voice back
                log.warning("could not trim %s; sending it as it is", path, exc_info=True)
                upload, cuts = path, ()
            caption = self._caption(ref.item_id, path, item.duration_ms, cuts, extra)
            sent = self._upload(chat_id, upload, caption)
        if sent is not None:
            self._sent[key] = (*sent, cuts)

    def _caption(
        self, voice_id: int, path: Path, duration_ms: int, cuts: tuple[Span, ...], extra: list[str]
    ) -> str:
        """Name, length, tags and notes, with the times as they fall in the audio sent."""
        notes = [
            f"{_clock(trimmed_ms(n.position_ms, cuts))} {n.text}"
            for n in self._notes.list_for_voice(voice_id)
        ]
        saved = total_ms(cuts)
        head = f"{ICON_VOICE} {path.name} · {_clock(duration_ms - saved)}"
        if saved:
            head += "\n" + T_TRIMMED.format(saved=_clock(saved))
        caption = "\n\n".join(p for p in [head, "\n".join(extra), "\n".join(notes)] if p)
        if len(caption) > MAX_CAPTION:
            caption = caption[:MAX_CAPTION].rstrip() + "…"
        return caption

    def _upload(self, chat_id: int, path: Path, caption: str) -> tuple[str, str] | None:
        """Send `path` as a voice, an audio or a plain file. The field and Bale's file id,
        when Bale says what it stored."""
        try:
            size = path.stat().st_size
        except OSError:
            self._send(chat_id, T_FILE_MISSING.format(name=path.name), None)
            return None
        if size > MAX_UPLOAD_BYTES:
            self._send(chat_id, T_FILE_TOO_LARGE.format(name=path.name), None)
            return None
        preferred = _UPLOAD_FIELDS.get(path.suffix.lower(), "document")
        for upload_field in dict.fromkeys((preferred, "document")):
            try:
                sent = self._client.send_file(chat_id, upload_field, path, caption)
            except BaleApiError:  # e.g. a format sendVoice won't take: try as a plain file
                log.warning("send%s refused", upload_field.capitalize(), exc_info=True)
                continue
            except (BaleError, OSError):
                log.warning("voice upload failed", exc_info=True)
                break
            file_id = self._file_id(sent, upload_field)
            return (upload_field, file_id) if file_id else None
        self._send(chat_id, T_SEND_FAILED, None)
        return None

    @staticmethod
    def _file_id(message: Any, upload_field: str) -> str | None:
        if not isinstance(message, dict):
            return None
        for key in (upload_field, "document", "audio", "voice"):
            media = message.get(key)
            if isinstance(media, dict) and media.get("file_id"):
                return str(media["file_id"])
        return None
