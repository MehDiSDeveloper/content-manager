"""Export everything to one .zip (data.json + audio files) and restore it.

Import REPLACES all user data (it is a restore, not a merge): ids are kept, so every link,
note and transcript lands exactly where it was. Before replacing anything the current
database is snapshotted to backups/, and the whole replacement is one transaction.
Settings are not exported: they are per machine and include the bot token.
"""

import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.backup_reminder import BackupReminder, backup_reminder
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
from podcast_workspace.domain.errors import ValidationError
from podcast_workspace.domain.publish import PublishChecklist, PublishStep
from podcast_workspace.paths import backups_dir, library_dir
from podcast_workspace.repositories.db import WriteCounter
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.settings_service import SettingsService
from podcast_workspace.services.tag_service import TagService

FORMAT = "podcast-workspace-export"
FORMAT_VERSION = 1
DATA_NAME = "data.json"
AUDIO_DIR = "audio/"
CHUNK = 1024 * 1024

Progress = Callable[[float], None]


class ExportFormatError(ValueError):
    """The file is not an export of this app (or of a newer, unknown version)."""


@dataclass
class ExportReport:
    path: Path
    counts: dict[str, int]
    missing_audio: list[str] = field(default_factory=list)


@dataclass
class RestoreReport:
    counts: dict[str, int]
    snapshot: Path
    missing_audio: list[str] = field(default_factory=list)


def _dt(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValidationError(f"naive datetime in export: {value}")
    return parsed


def _req_dt(value: str) -> datetime:
    parsed = _parse_dt(value)
    assert parsed is not None
    return parsed


def _safe_name(path: str) -> str:
    name = PureWindowsPath(path).name
    return "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in name) or "audio"


@dataclass
class _Snapshot:
    tags: list[Tag]
    voices: list[Voice]
    ideas: list[IdeaNote]
    episodes: list[Episode]
    episode_notes: list[EpisodeNote]
    timestamp_notes: list[TimestampNote]
    transcripts: list[Transcript]
    seasons: list[Season]

    def counts(self) -> dict[str, int]:
        return {
            "tags": len(self.tags),
            "voices": len(self.voices),
            "ideas": len(self.ideas),
            "episodes": len(self.episodes),
            "episode_notes": len(self.episode_notes),
            "timestamp_notes": len(self.timestamp_notes),
            "transcripts": len(self.transcripts),
            "seasons": len(self.seasons),
        }


class BackupService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        tags: TagService,
        writes: WriteCounter,
        settings: SettingsService,
    ) -> None:
        self._sf = session_factory
        self._tags = tags
        self._writes = writes
        self._settings = settings

    # reminder --------------------------------------------------------------------------
    def reminder(self, now: datetime | None = None) -> BackupReminder | None:
        """The backup reminder due at startup, if any (`domain/backup_reminder.py`)."""
        now = now or datetime.now(UTC)
        settings = self._settings
        return backup_reminder(
            now,
            settings.first_run_at(now),
            settings.last_backup_at(),
            settings.backup_snoozed_until(),
            settings.backup_interval_days(),
        )

    def snooze_reminder(self, days: int = 1, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self._settings.set_backup_snoozed_until(now + timedelta(days=days))

    # export ----------------------------------------------------------------------------
    def _read_all(self) -> _Snapshot:
        with UnitOfWork(self._sf) as uow:
            voices = uow.voices.list_all(include_trashed=True)  # the trash is data too
            episodes = uow.episodes.list_all()
            episode_notes = [
                n
                for e in episodes
                if e.id is not None
                for n in uow.episode_notes.list_for_episode(e.id)
            ]
            timestamp_notes = [
                n
                for v in voices
                if v.id is not None
                for n in uow.timestamp_notes.list_for_voice(v.id)
            ]
            transcripts = [
                t
                for v in voices
                if v.id is not None
                if (t := uow.transcripts.for_voice(v.id)) is not None
            ]
            return _Snapshot(
                tags=uow.tags.list_all(),
                voices=voices,
                ideas=uow.idea_notes.list_all(include_trashed=True),
                episodes=episodes,
                episode_notes=episode_notes,
                timestamp_notes=timestamp_notes,
                transcripts=transcripts,
                seasons=uow.seasons.list_all(),
            )

    def export(self, target: Path, progress: Progress | None = None) -> ExportReport:
        """Blocking; run off the UI thread. Writes `target` atomically (.part, then rename)."""
        report_progress = progress or (lambda _f: None)
        snap = self._read_all()
        missing: list[str] = []
        audio_entries: dict[int, tuple[Path, str]] = {}
        for voice in snap.voices:
            assert voice.id is not None
            source = Path(voice.file_path)
            if source.is_file():
                audio_entries[voice.id] = (
                    source,
                    f"{AUDIO_DIR}{voice.id:05d}_{_safe_name(voice.file_path)}",
                )
            else:
                missing.append(voice.file_path)
        data = self._to_json(snap, {vid: arc for vid, (_src, arc) in audio_entries.items()})

        total = sum(src.stat().st_size for src, _arc in audio_entries.values()) or 1
        done = 0
        partial = target.with_name(target.name + ".part")
        try:
            with zipfile.ZipFile(partial, "w", allowZip64=True) as archive:
                archive.writestr(
                    DATA_NAME,
                    json.dumps(data, ensure_ascii=False, indent=1),
                    compress_type=zipfile.ZIP_DEFLATED,
                )
                for source, arcname in audio_entries.values():
                    # Audio is already compressed: store it, and stream it in chunks.
                    info = zipfile.ZipInfo.from_file(source, arcname)
                    info.compress_type = zipfile.ZIP_STORED
                    with source.open("rb") as src, archive.open(info, "w", force_zip64=True) as dst:
                        while chunk := src.read(CHUNK):
                            dst.write(chunk)
                            done += len(chunk)
                            report_progress(min(1.0, done / total))
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        # A finished export is a backup: the reminder starts counting again from here.
        self._settings.set_last_backup_at(datetime.now(UTC))
        self._settings.set_backup_snoozed_until(None)
        report_progress(1.0)
        return ExportReport(target, snap.counts(), missing)

    @staticmethod
    def _to_json(snap: _Snapshot, archive_names: dict[int, str]) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "exported_at": datetime.now().astimezone().isoformat(),
            "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in snap.tags],
            "voices": [
                {
                    "id": v.id,
                    "file_path": v.file_path,
                    "archive_path": archive_names.get(v.id or 0),
                    "duration_ms": v.duration_ms,
                    "format": v.format,
                    "imported_at": _dt(v.imported_at),
                    "archived_at": _dt(v.archived_at),
                    "deleted_at": _dt(v.deleted_at),
                    "tag_ids": sorted(v.tag_ids),
                }
                for v in snap.voices
            ],
            "idea_notes": [
                {
                    "id": i.id,
                    "text": i.text,
                    "created_at": _dt(i.created_at),
                    "updated_at": _dt(i.updated_at),
                    "archived_at": _dt(i.archived_at),
                    "deleted_at": _dt(i.deleted_at),
                    "tag_ids": sorted(i.tag_ids),
                }
                for i in snap.ideas
            ],
            "seasons": [
                {"id": s.id, "title": s.title, "created_at": _dt(s.created_at)}
                for s in snap.seasons
            ],
            "episodes": [
                {
                    "id": e.id,
                    "title": e.title,
                    "season_id": e.season_id,
                    "status": e.status.value,
                    "next_action": e.next_action,
                    "created_at": _dt(e.created_at),
                    "updated_at": _dt(e.updated_at),
                    "last_opened_at": _dt(e.last_opened_at),
                    "tag_ids": sorted(e.tag_ids),
                    "voice_ids": sorted(e.voice_ids),
                    "idea_note_ids": sorted(e.idea_note_ids),
                    "publish_done": sorted(s.value for s in e.publish.done),
                    "published_where": e.publish.where,
                }
                for e in snap.episodes
            ],
            "episode_notes": [
                {
                    "id": n.id,
                    "episode_id": n.episode_id,
                    "title": n.title,
                    "body": n.body,
                    "created_at": _dt(n.created_at),
                    "updated_at": _dt(n.updated_at),
                }
                for n in snap.episode_notes
            ],
            "timestamp_notes": [
                {
                    "id": n.id,
                    "voice_id": n.voice_id,
                    "position_ms": n.position_ms,
                    "text": n.text,
                    "created_at": _dt(n.created_at),
                }
                for n in snap.timestamp_notes
            ],
            "transcripts": [
                {
                    "id": t.id,
                    "voice_id": t.voice_id,
                    "language": t.language,
                    "model": t.model,
                    "created_at": _dt(t.created_at),
                    "segments": [[s.start_ms, s.end_ms, s.text] for s in t.segments],
                }
                for t in snap.transcripts
            ],
        }

    # import ----------------------------------------------------------------------------
    def restore(self, source: Path, progress: Progress | None = None) -> RestoreReport:
        """Blocking; run off the UI thread. Replaces ALL user data with the export's."""
        report_progress = progress or (lambda _f: None)
        with zipfile.ZipFile(source) as archive:
            try:
                data = json.loads(archive.read(DATA_NAME).decode("utf-8"))
            except (KeyError, ValueError) as exc:
                raise ExportFormatError(str(exc)) from exc
            if data.get("format") != FORMAT or data.get("version") != FORMAT_VERSION:
                raise ExportFormatError(f"{data.get('format')} v{data.get('version')}")
            try:
                snap = self._from_json(data)  # validates every entity before touching anything
            except (KeyError, TypeError, ValueError) as exc:
                raise ExportFormatError(str(exc)) from exc
            archive_paths = {int(v["id"]): v.get("archive_path") for v in data["voices"]}
            missing = self._place_audio(archive, snap.voices, archive_paths, report_progress)

        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        snapshot = backups_dir() / f"before-import_{stamp}.db"
        with UnitOfWork(self._sf) as uow:
            uow.maintenance.snapshot_to(snapshot)
        with UnitOfWork(self._sf) as uow:  # one transaction: all or nothing
            uow.maintenance.wipe_user_data()
            for tag in snap.tags:
                uow.tags.add(tag)
            for voice in snap.voices:
                uow.voices.add(voice)
            for idea in snap.ideas:
                uow.idea_notes.add(idea)
            for season in snap.seasons:
                uow.seasons.add(season)
            for episode in snap.episodes:
                uow.episodes.add(episode)
            for note in snap.episode_notes:
                uow.episode_notes.add(note)
            for ts_note in snap.timestamp_notes:
                uow.timestamp_notes.add(ts_note)
            for transcript in snap.transcripts:
                uow.transcripts.add(transcript)
        self._tags.invalidate()
        self._writes.bump()
        report_progress(1.0)
        return RestoreReport(snap.counts(), snapshot, missing)

    @staticmethod
    def _place_audio(
        archive: zipfile.ZipFile,
        voices: list[Voice],
        archive_paths: dict[int, str | None],
        progress: Progress,
    ) -> list[str]:
        """Point each voice at a real file: the original path if it still holds the same
        file, otherwise the copy extracted into library/. Returns paths left missing."""
        members = {info.filename: info for info in archive.infolist()}
        total = sum(members[a].file_size for a in archive_paths.values() if a in members) or 1
        done = 0
        missing: list[str] = []
        target_dir = library_dir()
        for voice in voices:
            assert voice.id is not None
            arcname = archive_paths.get(voice.id)
            info = members.get(arcname) if arcname else None
            original = Path(voice.file_path)
            if info is None:
                if not original.is_file():
                    missing.append(voice.file_path)
                continue
            if original.is_file() and original.stat().st_size == info.file_size:
                done += info.file_size
                continue
            destination = target_dir / PureWindowsPath(info.filename).name
            if not (destination.is_file() and destination.stat().st_size == info.file_size):
                with archive.open(info) as src, destination.open("wb") as dst:
                    while chunk := src.read(CHUNK):
                        dst.write(chunk)
                        done += len(chunk)
                        progress(min(0.99, done / total))
            voice.file_path = str(destination)
        return missing

    @staticmethod
    def _from_json(data: dict[str, Any]) -> _Snapshot:
        return _Snapshot(
            tags=[Tag(id=t["id"], name=t["name"], color=t["color"]) for t in data["tags"]],
            voices=[
                Voice(
                    id=v["id"],
                    file_path=v["file_path"],
                    duration_ms=int(v.get("duration_ms") or 0),
                    format=v.get("format") or "",
                    imported_at=_req_dt(v["imported_at"]),
                    tag_ids=set(v.get("tag_ids") or ()),
                    # Exports made before archive/trash existed have neither.
                    archived_at=_parse_dt(v.get("archived_at")),
                    deleted_at=_parse_dt(v.get("deleted_at")),
                )
                for v in data["voices"]
            ],
            ideas=[
                IdeaNote(
                    id=i["id"],
                    text=i["text"],
                    created_at=_req_dt(i["created_at"]),
                    updated_at=_req_dt(i["updated_at"]),
                    tag_ids=set(i.get("tag_ids") or ()),
                    archived_at=_parse_dt(i.get("archived_at")),
                    deleted_at=_parse_dt(i.get("deleted_at")),
                )
                for i in data["idea_notes"]
            ],
            episodes=[
                Episode(
                    id=e["id"],
                    title=e["title"],
                    status=EpisodeStatus(e["status"]),
                    next_action=e.get("next_action") or "",
                    season_id=e.get("season_id"),
                    created_at=_req_dt(e["created_at"]),
                    updated_at=_req_dt(e["updated_at"]),
                    last_opened_at=_parse_dt(e.get("last_opened_at")),
                    tag_ids=set(e.get("tag_ids") or ()),
                    voice_ids=set(e.get("voice_ids") or ()),
                    idea_note_ids=set(e.get("idea_note_ids") or ()),
                    # Exports made before the checklist existed start with an empty one.
                    publish=PublishChecklist(
                        frozenset(PublishStep(s) for s in e.get("publish_done") or ()),
                        e.get("published_where") or "",
                    ),
                )
                for e in data["episodes"]
            ],
            episode_notes=[
                EpisodeNote(
                    id=n["id"],
                    episode_id=n["episode_id"],
                    title=n.get("title") or "",
                    body=n.get("body") or "",
                    created_at=_req_dt(n["created_at"]),
                    updated_at=_req_dt(n["updated_at"]),
                )
                for n in data["episode_notes"]
            ],
            timestamp_notes=[
                TimestampNote(
                    id=n["id"],
                    voice_id=n["voice_id"],
                    position_ms=int(n["position_ms"]),
                    text=n["text"],
                    created_at=_req_dt(n["created_at"]),
                )
                for n in data["timestamp_notes"]
            ],
            transcripts=[
                Transcript(
                    id=t["id"],
                    voice_id=t["voice_id"],
                    language=t.get("language") or "fa",
                    model=t.get("model") or "",
                    created_at=_req_dt(t["created_at"]),
                    segments=[
                        TranscriptSegment(int(a), int(b), str(s)) for a, b, s in t["segments"]
                    ],
                )
                for t in data.get("transcripts", [])
            ],
            # Exports made before seasons existed simply have none.
            seasons=[
                Season(id=s["id"], title=s["title"], created_at=_req_dt(s["created_at"]))
                for s in data.get("seasons") or ()
            ],
        )
