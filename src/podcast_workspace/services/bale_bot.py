"""Bale bot: a pocket inbox for the workspace, polled from a background thread.

- Text message -> IdeaNote (hashtags in it become its tags).
- Voice / audio message -> downloaded into the voice library (caption hashtags become tags,
  the rest of the caption becomes a TimestampNote at 0:00).
- Everything is saved on arrival; the tag keyboard that follows is optional.
- Tags: inline keyboard of the 20 most-used tags (toggle), or free text / hashtags, which go
  through TagService.resolve_or_create so no near-duplicate tag is ever created.
- The first private chat to message the bot becomes its owner; anyone else is refused.
- Network or API trouble never escapes the worker: it reports a status and retries.
"""

import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from podcast_workspace.domain.bot_input import parse_message, split_tag_list
from podcast_workspace.domain.errors import DomainError, NotFoundError
from podcast_workspace.domain.rules import MAX_TAGS_PER_ITEM
from podcast_workspace.integrations.bale_api import (
    MAX_DOWNLOAD_BYTES,
    BaleApiError,
    BaleClient,
    BaleError,
    BaleUnauthorizedError,
)
from podcast_workspace.paths import bale_voices_dir
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS
from podcast_workspace.services.content_services import (
    IdeaService,
    TimestampNoteService,
    VoiceService,
)
from podcast_workspace.services.history import HistoryService
from podcast_workspace.services.settings_service import BotOwner, SettingsService
from podcast_workspace.services.tag_service import TagService

log = logging.getLogger(__name__)

POLL_TIMEOUT_S = 25
BACKOFF_START_S = 3.0
BACKOFF_MAX_S = 120.0
KEYBOARD_TAGS = 20
KEYBOARD_COLUMNS = 2
MAX_PROMPTS_REMEMBERED = 50

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_MIME_EXTENSIONS = {
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/amr": ".amr",
    "audio/webm": ".webm",
}
_UNSAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

# Bot-facing text (Persian). The desktop UI keeps its own strings in ui/strings.py.
T_WELCOME = (
    "سلام! این بازو به «فضای کاری پادکست» شما وصل شد.\n\n"
    "• هر پیام متنی یک ایدهٔ متنی ذخیره می‌شود.\n"
    "• هر پیام صوتی یک ایدهٔ صوتی ذخیره می‌شود.\n"
    "• برچسب: روی دکمه‌ها بزنید یا نامش را با # بفرستید (مثلاً #روان_شناسی).\n"
    "• پیامی که فقط هشتگ دارد، به آخرین مورد برچسب می‌زند.\n"
    "/cancel لغو انتظار برای برچسب"
)
T_PRIVATE = "این بازو خصوصی است."
T_ONLY_TEXT_AND_VOICE = "فقط پیام متنی (ایدهٔ متنی) و صوتی (ایدهٔ صوتی) ذخیره می‌شود."
T_IDEA_SAVED = "✅ ایدهٔ متنی ذخیره شد"
T_VOICE_SAVED = "✅ ایدهٔ صوتی ذخیره شد"
T_TAGS_UPDATED = "🏷 برچسب‌ها به‌روز شد"
T_ASK_TAGS = "برچسب اضافه شود؟ روی برچسب‌ها بزنید یا نامشان را با # بفرستید."
T_NO_TAGS_YET = "هنوز برچسبی ندارید؛ نام برچسب را با # بفرستید تا ساخته شود."
T_TAGS_LINE = "برچسب‌ها ({n} از {limit}): {names}"
T_TAGS_NONE = "بدون برچسب"
T_FINAL = "✅ ذخیره شد — {kind}: {summary}\n{tags}"
T_KIND_IDEA = "ایدهٔ متنی"
T_KIND_VOICE = "ایدهٔ صوتی"
T_CREATED = "برچسب تازه: {names}"
T_CORRECTED = "به برچسب موجود وصل شد: {pairs}"
T_DROPPED = "سقف {limit} برچسب پر است؛ اضافه نشد: {names}"
T_INVALID = "نام نامعتبر: {names}"
T_FREE_PROMPT = "نام برچسب‌ها را بفرستید، با ویرگول یا # جدا کنید. (/cancel لغو)"
T_CANCELLED = "لغو شد."
T_NOTHING_TO_TAG = "هنوز موردی دریافت نشده که برچسب بخورد."
T_LIMIT_ALERT = "هر مورد حداکثر {limit} برچسب می‌تواند داشته باشد."
T_TAG_ADDED = "«{name}» اضافه شد"
T_TAG_REMOVED = "«{name}» برداشته شد"
T_TAG_GONE = "این برچسب دیگر وجود ندارد."
T_ITEM_GONE = "این مورد دیگر در فضای کاری نیست."
T_DONE = "ذخیره شد"
T_BUTTON_FREE = "✏️ برچسب دلخواه"
T_BUTTON_DONE = "✔️ تمام"
T_TOO_LARGE = "حجم فایل بیش از ۲۰ مگابایت است و بازوها نمی‌توانند آن را دریافت کنند."
T_UNSUPPORTED_AUDIO = "این قالب صوتی پشتیبانی نمی‌شود."
T_VOICE_FAILED = "دریافت فایل صوتی ممکن نشد؛ دوباره بفرستید."
T_SAVE_FAILED = "ذخیره ممکن نشد: {error}"


class BotStatus(StrEnum):
    STOPPED = "stopped"
    CONNECTING = "connecting"
    ONLINE = "online"
    OFFLINE = "offline"  # no network / server trouble; retrying
    UNAUTHORIZED = "unauthorized"  # token rejected; waits for a new token


class ItemKind(StrEnum):
    IDEA = "i"
    VOICE = "v"


@dataclass(frozen=True)
class ItemRef:
    kind: ItemKind
    item_id: int


StatusCallback = Callable[[BotStatus, str], None]
ItemCallback = Callable[[ItemRef], None]


@dataclass
class TagReport:
    created: list[str] = field(default_factory=list)
    corrected: list[tuple[str, str]] = field(default_factory=list)  # requested -> used
    dropped: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out: list[str] = []
        if self.created:
            out.append(T_CREATED.format(names="، ".join(self.created)))
        if self.corrected:
            pairs = "، ".join(f"{a} ← {b}" for a, b in self.corrected)
            out.append(T_CORRECTED.format(pairs=pairs))
        if self.dropped:
            out.append(
                T_DROPPED.format(limit=_fa(MAX_TAGS_PER_ITEM), names="، ".join(self.dropped))
            )
        if self.invalid:
            out.append(T_INVALID.format(names="، ".join(self.invalid)))
        return out


@dataclass
class _Prompt:
    message_id: int
    ref: ItemRef
    tag_ids: list[int]  # keyboard content, frozen so buttons don't move under the finger


@dataclass
class _ChatState:
    last_item: ItemRef | None = None
    awaiting_tags: ItemRef | None = None
    active_prompt: _Prompt | None = None
    prompts: dict[int, _Prompt] = field(default_factory=dict)


def _fa(value: object) -> str:
    return str(value).translate(_FA_DIGITS)


def _shorten(text: str, width: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[:width].rstrip() + "…"


class BaleBotService:
    """Owns the polling thread. start/stop/restart are called from the UI thread;
    callbacks arrive on the worker thread (the UI relays them to its own)."""

    def __init__(
        self,
        settings: SettingsService,
        ideas: IdeaService,
        voices: VoiceService,
        tags: TagService,
        timestamp_notes: TimestampNoteService,
        history: HistoryService,
    ) -> None:
        self._settings = settings
        self._ideas = ideas
        self._voices = voices
        self._tags = tags
        self._notes = timestamp_notes
        self.history = history
        self._worker: _Worker | None = None
        self.status = BotStatus.STOPPED

    def start(self, on_status: StatusCallback, on_item: ItemCallback) -> bool:
        """Start polling if enabled and a token is set. Returns whether it started."""
        self.stop()
        token = self._settings.bale_token()
        if not token or not self._settings.bale_enabled():
            return False

        def status(value: BotStatus, detail: str) -> None:
            self.status = value
            on_status(value, detail)

        self._worker = _Worker(self, BaleClient(token), status, on_item)
        self._worker.start()
        return True

    def stop(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.stop()
        self.status = BotStatus.STOPPED

    @staticmethod
    def check_token(token: str) -> str:
        """Blocking getMe; returns the bot's @username (or name). Raises BaleError."""
        client = BaleClient(token)
        try:
            me = client.get_me()
        finally:
            client.close()
        username = me.get("username")
        return f"@{username}" if username else str(me.get("first_name") or "")


class _Worker(threading.Thread):
    def __init__(
        self,
        service: BaleBotService,
        client: BaleClient,
        on_status: StatusCallback,
        on_item: ItemCallback,
    ) -> None:
        super().__init__(name="bale-bot", daemon=True)
        self._svc = service
        self._client = client
        self._on_status = on_status
        self._on_item = on_item
        self._stop_event = threading.Event()
        self._status: BotStatus | None = None
        self._chats: dict[int, _ChatState] = {}

    def stop(self) -> None:
        self._stop_event.set()
        if self._status is not None:
            self._on_status(BotStatus.STOPPED, "")

    # loop ------------------------------------------------------------------------------
    def _report(self, status: BotStatus, detail: str = "") -> None:
        if self._stop_event.is_set():
            return
        if status != self._status:
            self._status = status
            try:
                self._on_status(status, detail)
            except Exception:
                log.exception("bot status callback failed")

    def run(self) -> None:
        self._report(BotStatus.CONNECTING)
        settings = self._svc._settings
        offset = settings.bale_offset()
        webhook_cleared = False
        backoff = BACKOFF_START_S
        try:
            while not self._stop_event.is_set():
                try:
                    if not webhook_cleared:  # getUpdates is refused while a webhook is set
                        self._client.delete_webhook()
                        webhook_cleared = True
                    updates = self._client.get_updates(offset, POLL_TIMEOUT_S)
                except BaleUnauthorizedError:
                    self._report(BotStatus.UNAUTHORIZED)
                    return
                except Exception as exc:  # BaleError or anything unexpected: wait and retry
                    if not isinstance(exc, BaleError):
                        log.exception("bot polling failed")
                    if isinstance(exc, BaleApiError) and exc.code == 409:
                        webhook_cleared = False
                    self._report(BotStatus.OFFLINE, str(exc))
                    self._stop_event.wait(backoff)
                    backoff = min(backoff * 2, BACKOFF_MAX_S)
                    continue
                backoff = BACKOFF_START_S
                self._report(BotStatus.ONLINE)
                if self._stop_event.is_set():
                    return  # unacknowledged; the next worker fetches these again
                for update in updates:
                    offset = int(update.get("update_id", 0)) + 1
                    try:
                        self._handle(update)
                    except Exception:
                        log.exception("bot update failed: %s", update.get("update_id"))
                    try:
                        settings.set_bale_offset(offset)
                    except Exception:
                        log.exception("could not store bot offset")
        finally:
            self._client.close()

    # dispatch --------------------------------------------------------------------------
    def _handle(self, update: dict[str, Any]) -> None:
        # Items arriving from the phone are not the user's own doing at the keyboard:
        # they must not land on (or flush) the undo stack in front of them.
        with self._svc.history.suspended():
            if "callback_query" in update:
                self._on_callback(update["callback_query"])
            elif "message" in update:
                self._on_message(update["message"])

    def _send(self, chat_id: int, text: str, markup: dict[str, Any] | None = None) -> int | None:
        try:
            return int(self._client.send_message(chat_id, text, markup)["message_id"])
        except (BaleError, KeyError, TypeError, ValueError):
            log.warning("sendMessage failed", exc_info=True)
            return None

    def _edit(
        self, chat_id: int, message_id: int, text: str, markup: dict[str, Any] | None = None
    ) -> None:
        try:
            self._client.edit_message_text(chat_id, message_id, text, markup)
        except BaleError:
            log.warning("editMessageText failed", exc_info=True)

    def _answer(self, callback_id: str, text: str | None = None, alert: bool = False) -> None:
        try:
            self._client.answer_callback_query(callback_id, text, alert)
        except BaleError:
            log.warning("answerCallbackQuery failed", exc_info=True)

    def _authorized(self, chat: dict[str, Any], greet: bool = True) -> bool:
        if chat.get("type", "private") != "private":
            return False  # groups/channels are never an inbox
        chat_id = int(chat["id"])
        settings = self._svc._settings
        owner = settings.bale_owner()
        if owner is None:
            name = " ".join(
                str(chat.get(k) or "") for k in ("first_name", "last_name")
            ).strip() or str(chat.get("username") or chat_id)
            settings.set_bale_owner(BotOwner(chat_id, name))
            if greet:  # a command gets its own reply; don't welcome twice
                self._send(chat_id, T_WELCOME)
            return True
        if owner.chat_id != chat_id:
            self._send(chat_id, T_PRIVATE)
            return False
        return True

    def _state(self, chat_id: int) -> _ChatState:
        return self._chats.setdefault(chat_id, _ChatState())

    # messages --------------------------------------------------------------------------
    def _on_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        text = message.get("text")
        is_command = isinstance(text, str) and text.startswith("/")
        if "id" not in chat or not self._authorized(chat, greet=not is_command):
            return
        chat_id = int(chat["id"])
        if is_command:
            self._on_command(chat_id, text)
            return
        audio = self._audio_of(message)
        if audio is not None:
            self._receive_voice(chat_id, audio, str(message.get("caption") or ""))
        elif isinstance(text, str) and text.strip():
            self._receive_text(chat_id, text)
        else:
            self._send(chat_id, T_ONLY_TEXT_AND_VOICE)

    def _on_command(self, chat_id: int, text: str) -> None:
        command = text.split()[0].split("@")[0].lower()
        state = self._state(chat_id)
        if command == "/cancel":
            state.awaiting_tags = None
            self._send(chat_id, T_CANCELLED)
        else:  # /start, /help and anything unknown
            self._send(chat_id, T_WELCOME)

    @staticmethod
    def _audio_of(message: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("voice", "audio"):
            if isinstance(message.get(key), dict):
                return {**message[key], "_kind": key}
        document = message.get("document")
        if isinstance(document, dict):
            mime = str(document.get("mime_type") or "")
            suffix = Path(str(document.get("file_name") or "")).suffix.lower()
            if mime.startswith("audio/") or suffix in SUPPORTED_EXTENSIONS:
                return {**document, "_kind": "document"}
        return None

    def _receive_text(self, chat_id: int, text: str) -> None:
        state = self._state(chat_id)
        if state.awaiting_tags is not None:
            target, state.awaiting_tags = state.awaiting_tags, None
            names = split_tag_list(text)
            if names:
                self._tag_by_names(chat_id, target, names)
                return
        parsed = parse_message(text)
        if parsed.tags_only:
            if state.last_item is None:
                self._send(chat_id, T_NOTHING_TO_TAG)
            else:
                self._tag_by_names(chat_id, state.last_item, parsed.tags)
            return
        try:
            idea = self._svc._ideas.create(parsed.text)
        except DomainError as exc:
            self._send(chat_id, T_SAVE_FAILED.format(error=exc))
            return
        assert idea.id is not None
        ref = ItemRef(ItemKind.IDEA, idea.id)
        report = self._add_tags(ref, parsed.tags) if parsed.tags else TagReport()
        self._delivered(ref)
        self._send_prompt(chat_id, ref, T_IDEA_SAVED, report)

    def _receive_voice(self, chat_id: int, audio: dict[str, Any], caption: str) -> None:
        size = int(audio.get("file_size") or 0)
        if size > MAX_DOWNLOAD_BYTES:
            self._send(chat_id, T_TOO_LARGE)
            return
        try:
            info = self._client.get_file(str(audio["file_id"]))
            remote_path = str(info["file_path"])
        except (BaleError, KeyError, TypeError):
            log.warning("getFile failed", exc_info=True)
            self._send(chat_id, T_VOICE_FAILED)
            return
        suffix = self._suffix_for(audio, remote_path)
        if suffix is None:
            self._send(chat_id, T_UNSUPPORTED_AUDIO)
            return
        target = self._target_path(audio, suffix)
        try:
            self._client.download(remote_path, target)
        except (BaleError, OSError):
            log.warning("voice download failed", exc_info=True)
            self._send(chat_id, T_VOICE_FAILED)
            return
        report = self._svc._voices.import_files([target])
        if not report.imported:
            reason = report.failed[0][1] if report.failed else target.name
            self._send(chat_id, T_SAVE_FAILED.format(error=reason))
            return
        voice = report.imported[0]
        assert voice.id is not None
        ref = ItemRef(ItemKind.VOICE, voice.id)
        parsed = parse_message(caption)
        tag_report = self._add_tags(ref, parsed.tags) if parsed.tags else TagReport()
        if parsed.text:
            try:
                self._svc._notes.add(voice.id, 0, parsed.text)
            except DomainError:
                log.warning("caption note not saved", exc_info=True)
        self._delivered(ref)
        self._send_prompt(chat_id, ref, T_VOICE_SAVED, tag_report)

    @staticmethod
    def _suffix_for(audio: dict[str, Any], remote_path: str) -> str | None:
        for candidate in (
            Path(remote_path).suffix.lower(),
            Path(str(audio.get("file_name") or "")).suffix.lower(),
            _MIME_EXTENSIONS.get(str(audio.get("mime_type") or "").split(";")[0].lower(), ""),
        ):
            if candidate in SUPPORTED_EXTENSIONS:
                return candidate
        return ".ogg" if audio.get("_kind") == "voice" else None  # Bale voice notes are Opus

    @staticmethod
    def _target_path(audio: dict[str, Any], suffix: str) -> Path:
        stem = Path(str(audio.get("file_name") or "")).stem or str(audio.get("title") or "")
        stem = _UNSAFE_NAME.sub("_", stem).strip(" ._")[:60] or "bale-voice"
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        folder = bale_voices_dir()
        target = folder / f"{stamp}_{stem}{suffix}"
        counter = 2
        while target.exists():
            target = folder / f"{stamp}_{stem}-{counter}{suffix}"
            counter += 1
        return target

    def _delivered(self, ref: ItemRef) -> None:
        try:
            self._on_item(ref)
        except Exception:
            log.exception("bot item callback failed")

    # tags ------------------------------------------------------------------------------
    def _item_tags(self, ref: ItemRef) -> set[int]:
        if ref.kind is ItemKind.IDEA:
            return set(self._svc._ideas.get(ref.item_id).tag_ids)
        return set(self._svc._voices.get(ref.item_id).tag_ids)

    def _set_item_tags(self, ref: ItemRef, tag_ids: set[int]) -> None:
        if ref.kind is ItemKind.IDEA:
            self._svc._ideas.set_tags(ref.item_id, tag_ids)
        else:
            self._svc._voices.set_tags(ref.item_id, tag_ids)

    def _add_tags(self, ref: ItemRef, names: list[str]) -> TagReport:
        """Resolve names to tags (never creating near-duplicates) and attach them, stopping
        at the 15-tag limit. No tag is created that would then be dropped."""
        tags = self._svc._tags
        report = TagReport()
        current = self._item_tags(ref)
        for name in names:
            known = tags.find_exact(name)
            if known is not None and known.id in current:
                continue
            if len(current) >= MAX_TAGS_PER_ITEM:
                report.dropped.append(name)
                continue
            try:
                resolution = tags.resolve_or_create(name)
            except DomainError:
                report.invalid.append(name)
                continue
            if resolution.tag.id is None:
                continue
            if resolution.created:
                report.created.append(resolution.tag.name)
            elif resolution.corrected:
                report.corrected.append((name, resolution.tag.name))
            current.add(resolution.tag.id)
        self._set_item_tags(ref, current)  # the domain enforces the limit once more
        return report

    def _tag_by_names(self, chat_id: int, ref: ItemRef, names: list[str]) -> None:
        try:
            report = self._add_tags(ref, names)
        except NotFoundError:
            self._send(chat_id, T_ITEM_GONE)
            return
        self._delivered(ref)
        self._send_prompt(chat_id, ref, T_TAGS_UPDATED, report)

    # prompt with inline keyboard -------------------------------------------------------
    def _summary(self, ref: ItemRef) -> str:
        if ref.kind is ItemKind.IDEA:
            return f"«{_shorten(self._svc._ideas.get(ref.item_id).text)}»"
        voice = self._svc._voices.get(ref.item_id)
        seconds = voice.duration_ms // 1000
        return f"{Path(voice.file_path).name} ({_fa(f'{seconds // 60}:{seconds % 60:02d}')})"

    def _tags_line(self, tag_ids: set[int]) -> str:
        names = [t.name for t in self._svc._tags.by_ids(tag_ids)]
        if not names:
            return T_TAGS_NONE
        return T_TAGS_LINE.format(
            n=_fa(len(names)), limit=_fa(MAX_TAGS_PER_ITEM), names="، ".join(sorted(names))
        )

    def _prompt_text(self, ref: ItemRef, header: str, report: TagReport | None) -> str:
        tag_ids = self._item_tags(ref)
        lines = [f"{header}: {self._summary(ref)}", *(report.lines() if report else [])]
        lines += ["", self._tags_line(tag_ids), ""]
        lines.append(T_ASK_TAGS if self._svc._tags.list_all() else T_NO_TAGS_YET)
        return "\n".join(lines)

    def _final_text(self, ref: ItemRef) -> str:
        kind = T_KIND_IDEA if ref.kind is ItemKind.IDEA else T_KIND_VOICE
        return T_FINAL.format(
            kind=kind, summary=self._summary(ref), tags=self._tags_line(self._item_tags(ref))
        )

    def _keyboard(self, ref: ItemRef, tag_ids: list[int]) -> dict[str, Any]:
        selected = self._item_tags(ref)
        names = {t.id: t.name for t in self._svc._tags.by_ids(tag_ids)}
        buttons = [
            {
                "text": f"✓ {names[tag_id]}" if tag_id in selected else names[tag_id],
                "callback_data": f"t|{ref.kind.value}|{ref.item_id}|{tag_id}",
            }
            for tag_id in tag_ids
            if tag_id in names
        ]
        rows = [buttons[i : i + KEYBOARD_COLUMNS] for i in range(0, len(buttons), KEYBOARD_COLUMNS)]
        rows.append(
            [
                {"text": T_BUTTON_FREE, "callback_data": f"f|{ref.kind.value}|{ref.item_id}"},
                {"text": T_BUTTON_DONE, "callback_data": f"d|{ref.kind.value}|{ref.item_id}"},
            ]
        )
        return {"inline_keyboard": rows}

    def _send_prompt(self, chat_id: int, ref: ItemRef, header: str, report: TagReport) -> None:
        state = self._state(chat_id)
        state.last_item = ref
        previous = state.active_prompt
        if previous is not None:  # one live keyboard at a time; the old one is settled
            try:
                self._edit(chat_id, previous.message_id, self._final_text(previous.ref))
            except NotFoundError:
                self._edit(chat_id, previous.message_id, T_ITEM_GONE)
            state.active_prompt = None
        tag_ids = [t.id for t in self._svc._tags.most_used(KEYBOARD_TAGS) if t.id is not None]
        message_id = self._send(
            chat_id, self._prompt_text(ref, header, report), self._keyboard(ref, tag_ids)
        )
        if message_id is None:
            return
        prompt = _Prompt(message_id, ref, tag_ids)
        state.active_prompt = prompt
        state.prompts[message_id] = prompt
        while len(state.prompts) > MAX_PROMPTS_REMEMBERED:
            state.prompts.pop(next(iter(state.prompts)))

    # buttons ---------------------------------------------------------------------------
    def _on_callback(self, query: dict[str, Any]) -> None:
        callback_id = str(query.get("id") or "")
        message = query.get("message") or {}
        chat = message.get("chat") or {}
        owner = self._svc._settings.bale_owner()
        if "id" not in chat or owner is None or owner.chat_id != int(chat["id"]):
            self._answer(callback_id, T_PRIVATE)
            return
        chat_id, message_id = int(chat["id"]), int(message.get("message_id") or 0)
        parts = str(query.get("data") or "").split("|")
        try:
            ref = ItemRef(ItemKind(parts[1]), int(parts[2]))
        except (IndexError, ValueError):
            self._answer(callback_id)
            return
        state = self._state(chat_id)
        try:
            match parts[0]:
                case "t" if len(parts) == 4:
                    self._toggle(callback_id, chat_id, message_id, ref, int(parts[3]))
                case "f":
                    state.awaiting_tags = ref
                    self._answer(callback_id)
                    self._send(chat_id, T_FREE_PROMPT)
                case "d":
                    self._edit(chat_id, message_id, self._final_text(ref))
                    if state.active_prompt and state.active_prompt.message_id == message_id:
                        state.active_prompt = None
                    self._answer(callback_id, T_DONE)
                case _:
                    self._answer(callback_id)
        except NotFoundError:
            self._answer(callback_id, T_ITEM_GONE, alert=True)
            self._edit(chat_id, message_id, T_ITEM_GONE)

    def _toggle(
        self, callback_id: str, chat_id: int, message_id: int, ref: ItemRef, tag_id: int
    ) -> None:
        tag = self._svc._tags.get(tag_id)
        if tag is None:
            self._answer(callback_id, T_TAG_GONE, alert=True)
            return
        current = self._item_tags(ref)
        if tag_id in current:
            current.discard(tag_id)
            note = T_TAG_REMOVED.format(name=tag.name)
        elif len(current) >= MAX_TAGS_PER_ITEM:
            self._answer(callback_id, T_LIMIT_ALERT.format(limit=_fa(MAX_TAGS_PER_ITEM)), True)
            return
        else:
            current.add(tag_id)
            note = T_TAG_ADDED.format(name=tag.name)
        self._set_item_tags(ref, current)
        self._delivered(ref)
        self._answer(callback_id, note)
        prompt = self._state(chat_id).prompts.get(message_id)
        tag_ids = (
            prompt.tag_ids
            if prompt is not None
            else [t.id for t in self._svc._tags.most_used(KEYBOARD_TAGS) if t.id is not None]
        )
        header = T_VOICE_SAVED if ref.kind is ItemKind.VOICE else T_IDEA_SAVED
        self._edit(
            chat_id, message_id, self._prompt_text(ref, header, None), self._keyboard(ref, tag_ids)
        )
