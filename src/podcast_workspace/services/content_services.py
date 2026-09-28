"""Episode, IdeaNote and Voice use cases.

Undoable use cases record their own inverse (`services/history.py`): the snapshot a
change needs in order to be taken back is captured here, beside the operation that made
it, so the UI never has to know how to reverse anything. Snapshots hold ids and the few
fields that change — never a copy of the database.

What is not recorded, and why: importing voices (additive, and the files stay on disk),
`open()` and `set_duration` (bookkeeping, not edits), and anything the Bale bot does
(it runs inside `history.suspended()`: the user's stack is for the user's own actions).

Voices and ideas are never deleted from here: `delete` puts them in the trash
(`domain/lifecycle.py`), which keeps everything they carry. Emptying the trash — by
hand or after 30 days — is `services/trash.py`, and is the only real delete.
"""

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import (
    Episode,
    EpisodeNote,
    EpisodeStatus,
    IdeaNote,
    Season,
    TimestampNote,
    Voice,
    utcnow,
)
from podcast_workspace.domain.errors import DomainError
from podcast_workspace.domain.lifecycle import ArchiveScope
from podcast_workspace.domain.publish import PublishChecklist, PublishStep
from podcast_workspace.domain.smart_links import (
    LinkCandidate,
    LinkKind,
    SmartLink,
    rank_smart_links,
)
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.audio_probe import SUPPORTED_EXTENSIONS, probe
from podcast_workspace.services.history import ChangeKind, HistoryService, Target, TargetKind


def _short(text: str, width: int = 60) -> str:
    """A name for an undo entry: the first line, shortened."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= width else line[:width].rstrip() + "…"


# An item in an episode, as the Ideas page and the episode workspace both name it.
ItemRef = tuple[LinkKind, int]


def _tag_names(uow: UnitOfWork, tag_ids: Iterable[int]) -> tuple[str, ...]:
    wanted = set(tag_ids)
    return tuple(t.name for t in uow.tags.list_all() if t.id in wanted)


def _known_tags(uow: UnitOfWork, tag_ids: Iterable[int]) -> set[int]:
    """Tags of the snapshot that still exist (one deleted since must not block an undo)."""
    alive = {t.id for t in uow.tags.list_all()}
    return {t for t in tag_ids if t in alive}


def _relink(
    uow: UnitOfWork, episode_ids: frozenset[int], kind: LinkKind, item_id: int | None
) -> None:
    """Put a restored voice / idea back into the episodes that referenced it."""
    if item_id is None:
        return
    for episode_id in episode_ids:
        episode = uow.episodes.find(episode_id)
        if episode is None:
            continue
        ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
        ids.add(item_id)
        uow.episodes.update(episode)


def _shelve(
    sf: sessionmaker[Session], repo: str, item_id: int, field_name: str, when: datetime | None
) -> None:
    """Set one voice's or idea's `archived_at` / `deleted_at` (the inverse of archiving
    or trashing it)."""
    with UnitOfWork(sf) as uow:
        items = getattr(uow, repo)
        item = items.get(item_id)
        setattr(item, field_name, when)
        items.update(item)


class EpisodeService:
    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_all(self) -> list[Episode]:
        with UnitOfWork(self._sf) as uow:
            return uow.episodes.list_all()

    def get(self, episode_id: int) -> Episode:
        with UnitOfWork(self._sf) as uow:
            return uow.episodes.get(episode_id)

    def open(self, episode_id: int) -> Episode:
        """Fetch and record that the user opened it (drives 'recently opened')."""
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.mark_opened()
            return uow.episodes.update(episode)

    def create(self, title: str, season_id: int | None = None) -> Episode:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.add(Episode(title=title, season_id=season_id))
        assert episode.id is not None
        snapshot = deepcopy(episode)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.EPISODE, episode.id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot, ()),
            details=(episode.title,),
            weight=len(episode.title),
        )
        return episode

    def update(
        self, episode_id: int, *, title: str, status: EpisodeStatus, next_action: str
    ) -> Episode:
        with UnitOfWork(self._sf) as uow:
            current = uow.episodes.get(episode_id)
            edited = Episode(
                id=current.id,
                title=title,
                status=status,
                next_action=next_action,
                season_id=current.season_id,
                created_at=current.created_at,
                updated_at=current.updated_at,
                last_opened_at=current.last_opened_at,
                tag_ids=current.tag_ids,
                voice_ids=current.voice_ids,
                idea_note_ids=current.idea_note_ids,
                publish=current.publish,
            )
            if (edited.title, edited.status, edited.next_action) == (
                current.title,
                current.status,
                current.next_action,
            ):
                return current
            before = (current.title, current.status, current.next_action, current.updated_at)
            edited.touch()
            saved = uow.episodes.update(edited)
        after = (saved.title, saved.status, saved.next_action, saved.updated_at)
        # One step per run of typing, not one per field committed.
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_fields(episode_id, before),
            redo=lambda: self._set_fields(episode_id, after),
            details=(saved.title,),
            weight=len(saved.title) + len(saved.next_action),
            merge_key=f"episode-fields:{episode_id}",
        )
        return saved

    def set_tags(self, episode_id: int, tag_ids: Iterable[int]) -> Episode:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            before, after = set(episode.tag_ids), set(tag_ids)
            if before == after:
                return episode
            stamp = episode.updated_at
            episode.set_tags(after)
            episode.touch()
            saved = uow.episodes.update(episode)
            removed = before - after
            names = _tag_names(uow, removed or (after - before))
        touched = saved.updated_at
        self._history.record(
            ChangeKind.TAGS_REMOVED if removed else ChangeKind.TAGS_ADDED,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_tags(episode_id, before, stamp),
            redo=lambda: self._set_tags(episode_id, after, touched),
            details=names,
            weight=sum(len(n) for n in names),
        )
        return saved

    def set_status(self, episode_id: int, status: EpisodeStatus) -> Episode:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            if episode.status is status:
                return episode
            before, stamp = episode.status, episode.updated_at
            episode.status = status
            episode.touch()
            saved = uow.episodes.update(episode)
        touched, title = saved.updated_at, saved.title
        self._history.record(
            ChangeKind.STATUS,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_status(episode_id, before, stamp),
            redo=lambda: self._set_status(episode_id, status, touched),
            details=(status.value, title),
            weight=len(title),
        )
        return saved

    def set_season(self, episode_id: int, season_id: int | None) -> Episode:
        """File the episode under a season (None: no season). Counts as touching it."""
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            if episode.season_id == season_id:
                return episode
            before, stamp = episode.season_id, episode.updated_at
            episode.season_id = season_id
            episode.touch()
            saved = uow.episodes.update(episode)
            season = uow.seasons.find(season_id) if season_id is not None else None
        touched, title = saved.updated_at, saved.title
        self._history.record(
            ChangeKind.SEASON,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_season(episode_id, before, stamp),
            redo=lambda: self._set_season(episode_id, season_id, touched),
            details=(season.title if season is not None else "", title),
            weight=len(title),
        )
        return saved

    def link(self, episode_id: int, kind: LinkKind, item_id: int, linked: bool) -> Episode:
        """Attach or detach a Voice / IdeaNote. Counts as touching the episode."""
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
            if (item_id in ids) == linked:
                return episode
            stamp = episode.updated_at
            if linked:
                ids.add(item_id)
            else:
                ids.discard(item_id)
            episode.touch()
            saved = uow.episodes.update(episode)
            name = self._item_name(uow, kind, item_id)
        touched = saved.updated_at
        self._history.record(
            ChangeKind.LINKED if linked else ChangeKind.UNLINKED,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_link(episode_id, kind, item_id, not linked, stamp),
            redo=lambda: self._set_link(episode_id, kind, item_id, linked, touched),
            details=(name,),
            weight=len(name),
        )
        return saved

    def set_linked(self, episode_id: int, items: Iterable[ItemRef], linked: bool) -> Episode:
        """Put several voices / ideas into the episode, or take them out, as one step.

        The Ideas page's way in: the ones already where they are asked to be are left
        alone, and nothing is recorded when that is all of them.
        """
        wanted = list(dict.fromkeys(items))
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            stamp = episode.updated_at
            moved: list[ItemRef] = []
            for kind, item_id in wanted:
                ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
                if (item_id in ids) != linked:
                    if linked:
                        ids.add(item_id)
                    else:
                        ids.discard(item_id)
                    moved.append((kind, item_id))
            if not moved:
                return episode
            episode.touch()
            saved = uow.episodes.update(episode)
            names = tuple(self._item_name(uow, k, i) for k, i in moved)
        touched = saved.updated_at
        self._history.record(
            ChangeKind.LINKED if linked else ChangeKind.UNLINKED,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_links(episode_id, moved, not linked, stamp),
            redo=lambda: self._set_links(episode_id, moved, linked, touched),
            details=names,
            weight=sum(len(n) for n in names),
        )
        return saved

    def create_from(self, items: Iterable[ItemRef], season_id: int | None = None) -> Episode:
        """A new episode that starts out holding these voices / ideas.

        It is named after the first of them and carries all of their tags, so the
        workspace's suggestions have something to go on from the start. One undo step:
        taking it back takes back the episode, and its links with it.
        """
        wanted = list(dict.fromkeys(items))
        if not wanted:
            raise ValueError("an episode needs at least one item to start from")
        with UnitOfWork(self._sf) as uow:
            tag_ids: set[int] = set()
            voice_ids: set[int] = set()
            idea_ids: set[int] = set()
            for kind, item_id in wanted:
                if kind is LinkKind.VOICE:
                    tag_ids |= uow.voices.get(item_id).tag_ids
                    voice_ids.add(item_id)
                else:
                    tag_ids |= uow.idea_notes.get(item_id).tag_ids
                    idea_ids.add(item_id)
            episode = uow.episodes.add(
                Episode(
                    title=self._item_title(uow, *wanted[0]),
                    season_id=season_id,
                    tag_ids=tag_ids,
                    voice_ids=voice_ids,
                    idea_note_ids=idea_ids,
                )
            )
        assert episode.id is not None
        snapshot = deepcopy(episode)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.EPISODE, episode.id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot, ()),
            details=(episode.title,),
            weight=len(episode.title),
        )
        return episode

    def episodes_with(self, kind: LinkKind, item_id: int) -> list[Episode]:
        """The episodes a voice / idea is used in, most recently worked on first."""
        with UnitOfWork(self._sf) as uow:
            episodes = uow.episodes.list_all()
        return [
            e
            for e in episodes
            if item_id in (e.voice_ids if kind is LinkKind.VOICE else e.idea_note_ids)
        ]

    def link_counts(self) -> dict[ItemRef, int]:
        """How many episodes each linked voice / idea is in (one query, for whole lists)."""
        with UnitOfWork(self._sf) as uow:
            return uow.episodes.link_counts()

    def check_publish_step(self, episode_id: int, step: PublishStep, done: bool) -> Episode:
        with UnitOfWork(self._sf) as uow:
            current = uow.episodes.get(episode_id).publish
        return self._change_publish(episode_id, current.with_step(step, done))

    def set_published_where(self, episode_id: int, text: str) -> Episode:
        """Typed: one undo step per run of typing, like the other text fields."""
        with UnitOfWork(self._sf) as uow:
            current = uow.episodes.get(episode_id).publish
        return self._change_publish(
            episode_id, current.with_where(text), merge_key=f"episode-publish:{episode_id}"
        )

    def _change_publish(
        self, episode_id: int, checklist: PublishChecklist, merge_key: str | None = None
    ) -> Episode:
        """Counts as touching the episode: getting it out is work on it."""
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            before, stamp = episode.publish, episode.updated_at
            if checklist == before:
                return episode
            episode.publish = checklist
            episode.touch()
            saved = uow.episodes.update(episode)
        touched, title = saved.updated_at, saved.title
        self._history.record(
            ChangeKind.CHECKLIST,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._set_publish(episode_id, before, stamp),
            redo=lambda: self._set_publish(episode_id, checklist, touched),
            details=(title,),
            weight=len(title) + len(checklist.where),
            merge_key=merge_key,
        )
        return saved

    @staticmethod
    def _item_title(uow: UnitOfWork, kind: LinkKind, item_id: int) -> str:
        """What an episode started from an item is called: the file's name without its
        extension, or the idea's first line."""
        if kind is LinkKind.VOICE:
            return Path(uow.voices.get(item_id).file_path).stem
        return _short(uow.idea_notes.get(item_id).text)

    @staticmethod
    def _item_name(uow: UnitOfWork, kind: LinkKind, item_id: int) -> str:
        if kind is LinkKind.VOICE:
            voice = uow.voices.find(item_id)
            return "" if voice is None else Path(voice.file_path).name
        idea = uow.idea_notes.find(item_id)
        return "" if idea is None else _short(idea.text)

    def smart_links(self, episode_id: int) -> list[SmartLink]:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            candidates = [
                LinkCandidate(LinkKind.VOICE, v.id, frozenset(v.tag_ids), v.imported_at)
                for v in uow.voices.list_all()
                if v.id is not None and not v.archived
            ] + [
                LinkCandidate(LinkKind.IDEA, i.id, frozenset(i.tag_ids), i.updated_at)
                for i in uow.idea_notes.list_all()
                if i.id is not None and not i.archived
            ]
        return rank_smart_links(episode.tag_ids, candidates)

    def resume(self) -> "ResumeInfo | None":
        """The last opened episode and its most recently edited note."""
        with UnitOfWork(self._sf) as uow:
            opened = [e for e in uow.episodes.list_all() if e.last_opened_at is not None]
            if not opened:
                return None
            episode = max(opened, key=lambda e: e.last_opened_at or e.updated_at)
            assert episode.id is not None
            notes = uow.episode_notes.list_for_episode(episode.id)
        note = max(notes, key=lambda n: n.updated_at) if notes else None
        return ResumeInfo(episode, note)

    def delete(self, episode_id: int) -> None:
        """The episode and its notes go together, so undo brings both back."""
        with UnitOfWork(self._sf) as uow:
            episode = deepcopy(uow.episodes.get(episode_id))
            notes = tuple(deepcopy(n) for n in uow.episode_notes.list_for_episode(episode_id))
            uow.episodes.delete(episode_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.EPISODE, episode_id),
            undo=lambda: self._restore(episode, notes),
            redo=lambda: self._erase(episode_id),
            details=(episode.title,),
            weight=len(episode.title) + sum(len(n.title) + len(n.body) for n in notes),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_fields(
        self, episode_id: int, values: tuple[str, EpisodeStatus, str, datetime]
    ) -> None:
        title, status, next_action, updated_at = values
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.title, episode.status, episode.next_action = title, status, next_action
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_tags(self, episode_id: int, tag_ids: set[int], updated_at: datetime) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.set_tags(_known_tags(uow, tag_ids))
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_status(self, episode_id: int, status: EpisodeStatus, updated_at: datetime) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.status = status
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_season(self, episode_id: int, season_id: int | None, updated_at: datetime) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            if season_id is not None and uow.seasons.find(season_id) is None:
                season_id = None  # the season itself is gone
            episode.season_id = season_id
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_link(
        self, episode_id: int, kind: LinkKind, item_id: int, linked: bool, updated_at: datetime
    ) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
            item = (
                uow.voices.find(item_id) if kind is LinkKind.VOICE else uow.idea_notes.find(item_id)
            )
            if linked:
                if item is None:
                    return  # the item itself is gone: there is nothing to link back
                ids.add(item_id)
            else:
                ids.discard(item_id)
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_links(
        self, episode_id: int, items: list[ItemRef], linked: bool, updated_at: datetime
    ) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            for kind, item_id in items:
                ids = episode.voice_ids if kind is LinkKind.VOICE else episode.idea_note_ids
                if not linked:
                    ids.discard(item_id)
                elif (uow.voices if kind is LinkKind.VOICE else uow.idea_notes).find(item_id):
                    ids.add(item_id)  # one gone meanwhile has nothing to link back
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _set_publish(
        self, episode_id: int, checklist: PublishChecklist, updated_at: datetime
    ) -> None:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            episode.publish = checklist
            episode.updated_at = updated_at
            uow.episodes.update(episode)

    def _restore(self, episode: Episode, notes: tuple[EpisodeNote, ...]) -> None:
        with UnitOfWork(self._sf) as uow:
            restored = deepcopy(episode)
            restored.tag_ids = _known_tags(uow, restored.tag_ids)
            if restored.season_id is not None and uow.seasons.find(restored.season_id) is None:
                restored.season_id = None
            # A link to an item in the trash is kept: restoring the item brings it back.
            restored.voice_ids &= {v.id for v in uow.voices.list_all(include_trashed=True)}
            restored.idea_note_ids &= {i.id for i in uow.idea_notes.list_all(include_trashed=True)}
            uow.episodes.add(restored)
            for note in notes:
                uow.episode_notes.add(deepcopy(note))

    def _erase(self, episode_id: int | None) -> None:
        if episode_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            uow.episodes.delete(episode_id)


class SeasonService:
    """Seasons group episodes. Removing one never removes an episode."""

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_all(self) -> list[Season]:
        """In the order they were made: season one first."""
        with UnitOfWork(self._sf) as uow:
            return uow.seasons.list_all()

    def create(self, title: str) -> Season:
        with UnitOfWork(self._sf) as uow:
            season = uow.seasons.add(Season(title=title))
        assert season.id is not None
        snapshot = deepcopy(season)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.SEASON, season.id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot, frozenset()),
            details=(season.title,),
            weight=len(season.title),
        )
        return season

    def rename(self, season_id: int, title: str) -> Season:
        with UnitOfWork(self._sf) as uow:
            season = uow.seasons.get(season_id)
            before = season.title
            season.rename(title)
            if season.title == before:
                return season
            saved = uow.seasons.update(season)
        after = saved.title
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.SEASON, season_id),
            undo=lambda: self._set_title(season_id, before),
            redo=lambda: self._set_title(season_id, after),
            details=(after,),
            weight=len(after),
        )
        return saved

    def delete(self, season_id: int) -> None:
        """Its episodes stay, in no season; undo files them back under it."""
        with UnitOfWork(self._sf) as uow:
            season = deepcopy(uow.seasons.get(season_id))
            episodes = frozenset(uow.episodes.ids_in_season(season_id))
            uow.seasons.delete(season_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.SEASON, season_id),
            undo=lambda: self._restore(season, episodes),
            redo=lambda: self._erase(season_id),
            details=(season.title,),
            weight=len(season.title),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_title(self, season_id: int, title: str) -> None:
        with UnitOfWork(self._sf) as uow:
            season = uow.seasons.get(season_id)
            season.rename(title)
            uow.seasons.update(season)

    def _restore(self, season: Season, episodes: frozenset[int]) -> None:
        with UnitOfWork(self._sf) as uow:
            restored = uow.seasons.add(deepcopy(season))
            assert restored.id is not None
            uow.episodes.move_to_season(set(episodes), restored.id)

    def _erase(self, season_id: int | None) -> None:
        if season_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            uow.seasons.delete(season_id)


@dataclass(frozen=True)
class ResumeInfo:
    episode: Episode
    note: EpisodeNote | None


class EpisodeNoteService:
    """Long-form notes inside an episode. Every change touches the episode (stale marker)."""

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_for_episode(self, episode_id: int) -> list[EpisodeNote]:
        with UnitOfWork(self._sf) as uow:
            return uow.episode_notes.list_for_episode(episode_id)

    def get(self, note_id: int) -> EpisodeNote:
        with UnitOfWork(self._sf) as uow:
            return uow.episode_notes.get(note_id)

    def create(self, episode_id: int, title: str = "", body: str = "") -> EpisodeNote:
        with UnitOfWork(self._sf) as uow:
            stamp = self._touch(uow, episode_id)
            note = uow.episode_notes.add(EpisodeNote(episode_id=episode_id, title=title, body=body))
        assert note.id is not None
        snapshot = deepcopy(note)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.EPISODE_NOTE, note.id, episode_id),
            undo=lambda: self._erase(snapshot.id, stamp),
            redo=lambda: self._restore(snapshot),
            details=(_short(note.title or note.body),),
            weight=len(note.title) + len(note.body),
        )
        return note

    def update(self, note_id: int, title: str, body: str) -> EpisodeNote:
        with UnitOfWork(self._sf) as uow:
            note = uow.episode_notes.get(note_id)
            if (note.title, note.body) == (title.strip(), body):
                return note
            before = (note.title, note.body, note.updated_at)
            stamp = self._touch(uow, note.episode_id)
            note.edit(title, body)
            saved = uow.episode_notes.update(note)
        after = (saved.title, saved.body, saved.updated_at)
        # The editor's own Ctrl+Z covers keystrokes; this step covers a whole writing run.
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.EPISODE_NOTE, note_id, saved.episode_id),
            undo=lambda: self._set_text(note_id, before, stamp),
            redo=lambda: self._set_text(note_id, after, None),
            details=(_short(saved.title or saved.body),),
            weight=len(saved.title) + len(saved.body),
            merge_key=f"episode-note:{note_id}",
        )
        return saved

    def delete(self, note_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            note = deepcopy(uow.episode_notes.get(note_id))
            stamp = self._touch(uow, note.episode_id)
            uow.episode_notes.delete(note_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.EPISODE_NOTE, note_id, note.episode_id),
            undo=lambda: self._restore(note, stamp),
            redo=lambda: self._erase(note_id, None),
            details=(_short(note.title or note.body),),
            weight=len(note.title) + len(note.body),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_text(
        self, note_id: int, values: tuple[str, str, datetime], stamp: datetime | None
    ) -> None:
        title, body, updated_at = values
        with UnitOfWork(self._sf) as uow:
            note = uow.episode_notes.get(note_id)
            note.title, note.body, note.updated_at = title, body, updated_at
            uow.episode_notes.update(note)
            self._touch(uow, note.episode_id, stamp)

    def _restore(self, note: EpisodeNote, stamp: datetime | None = None) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.episodes.get(note.episode_id)  # the episode must still be there
            uow.episode_notes.add(deepcopy(note))
            self._touch(uow, note.episode_id, stamp)

    def _erase(self, note_id: int | None, stamp: datetime | None) -> None:
        if note_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            note = uow.episode_notes.get(note_id)
            uow.episode_notes.delete(note_id)
            self._touch(uow, note.episode_id, stamp)

    @staticmethod
    def _touch(uow: UnitOfWork, episode_id: int, when: datetime | None = None) -> datetime:
        """Mark the episode edited (or put its old mark back). Returns the previous value."""
        episode = uow.episodes.find(episode_id)
        if episode is None:
            return utcnow()
        before = episode.updated_at
        if when is None:
            episode.touch()
        else:
            episode.updated_at = when
        uow.episodes.update(episode)
        return before


class IdeaService:
    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_all(self, scope: ArchiveScope = ArchiveScope.ALL) -> list[IdeaNote]:
        """Ideas outside the trash, narrowed by the archive switch."""
        with UnitOfWork(self._sf) as uow:
            return [i for i in uow.idea_notes.list_all() if scope.shows(i.archived)]

    def list_trashed(self) -> list[IdeaNote]:
        with UnitOfWork(self._sf) as uow:
            return uow.idea_notes.list_trashed()

    def get(self, idea_id: int) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            return uow.idea_notes.get(idea_id)

    def create(self, text: str, tag_ids: Iterable[int] = ()) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.add(IdeaNote(text=text, tag_ids=set(tag_ids)))
        assert idea.id is not None
        snapshot = deepcopy(idea)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.IDEA, idea.id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot, frozenset()),
            details=(_short(idea.text),),
            weight=len(idea.text),
        )
        return idea

    def update_text(self, idea_id: int, text: str) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            if idea.text == text.strip():
                return idea
            before = (idea.text, idea.updated_at)
            idea.edit(text)
            saved = uow.idea_notes.update(idea)
        after = (saved.text, saved.updated_at)
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.IDEA, idea_id),
            undo=lambda: self._set_text(idea_id, before),
            redo=lambda: self._set_text(idea_id, after),
            details=(_short(saved.text),),
            weight=len(saved.text),
            merge_key=f"idea-text:{idea_id}",
        )
        return saved

    def set_tags(self, idea_id: int, tag_ids: Iterable[int]) -> IdeaNote:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            before, after = set(idea.tag_ids), set(tag_ids)
            if before == after:
                return idea
            idea.set_tags(after)
            saved = uow.idea_notes.update(idea)
            removed = before - after
            names = _tag_names(uow, removed or (after - before))
        self._history.record(
            ChangeKind.TAGS_REMOVED if removed else ChangeKind.TAGS_ADDED,
            Target(TargetKind.IDEA, idea_id),
            undo=lambda: self._set_tags(idea_id, before),
            redo=lambda: self._set_tags(idea_id, after),
            details=names,
            weight=sum(len(n) for n in names),
        )
        return saved

    def set_archived(self, idea_id: int, archived: bool) -> IdeaNote:
        """Put away, or bring back. Not an edit: `updated_at` stays."""
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            if idea.archived == archived:
                return idea
            before = idea.archived_at
            idea.archived_at = utcnow() if archived else None
            saved = uow.idea_notes.update(idea)
        after = saved.archived_at
        self._history.record(
            ChangeKind.ARCHIVE if archived else ChangeKind.UNARCHIVE,
            Target(TargetKind.IDEA, idea_id),
            undo=lambda: _shelve(self._sf, "idea_notes", idea_id, "archived_at", before),
            redo=lambda: _shelve(self._sf, "idea_notes", idea_id, "archived_at", after),
            details=(_short(saved.text),),
            weight=len(saved.text),
        )
        return saved

    def delete(self, idea_id: int) -> None:
        """Into the trash: hidden everywhere, kept whole until it is emptied."""
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            if idea.in_trash:
                return
            idea.deleted_at = utcnow()
            uow.idea_notes.update(idea)
        when = idea.deleted_at
        self._history.record(
            ChangeKind.TRASH,
            Target(TargetKind.IDEA, idea_id),
            undo=lambda: _shelve(self._sf, "idea_notes", idea_id, "deleted_at", None),
            redo=lambda: _shelve(self._sf, "idea_notes", idea_id, "deleted_at", when),
            details=(_short(idea.text),),
            weight=len(idea.text),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_text(self, idea_id: int, values: tuple[str, datetime]) -> None:
        text, updated_at = values
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            idea.text, idea.updated_at = text, updated_at
            uow.idea_notes.update(idea)

    def _set_tags(self, idea_id: int, tag_ids: set[int]) -> None:
        with UnitOfWork(self._sf) as uow:
            idea = uow.idea_notes.get(idea_id)
            idea.set_tags(_known_tags(uow, tag_ids))
            uow.idea_notes.update(idea)

    def _restore(self, idea: IdeaNote, episodes: frozenset[int]) -> None:
        with UnitOfWork(self._sf) as uow:
            restored = deepcopy(idea)
            restored.tag_ids = _known_tags(uow, restored.tag_ids)
            uow.idea_notes.add(restored)
            _relink(uow, episodes, LinkKind.IDEA, idea.id)

    def _erase(self, idea_id: int | None) -> None:
        if idea_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            uow.idea_notes.delete(idea_id)


@dataclass
class ImportReport:
    imported: list[Voice] = field(default_factory=list)
    already_present: list[Path] = field(default_factory=list)
    unsupported: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


class VoiceService:
    """Voices reference files in place; the workspace never copies, moves or deletes audio."""

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_all(
        self, scope: ArchiveScope = ArchiveScope.ALL, include_trashed: bool = False
    ) -> list[Voice]:
        """Voices outside the trash, narrowed by the archive switch. `include_trashed` is
        for the audio folder, which must not offer a file the workspace still holds."""
        with UnitOfWork(self._sf) as uow:
            voices = uow.voices.list_all(include_trashed=include_trashed)
        return [v for v in voices if v.in_trash or scope.shows(v.archived)]

    def list_trashed(self) -> list[Voice]:
        with UnitOfWork(self._sf) as uow:
            return uow.voices.list_trashed()

    def get(self, voice_id: int) -> Voice:
        with UnitOfWork(self._sf) as uow:
            return uow.voices.get(voice_id)

    def import_files(self, paths: Iterable[Path]) -> ImportReport:
        """Blocking (runs ffprobe per file). Call it off the UI thread."""
        report = ImportReport()
        for raw in paths:
            path = raw.resolve()
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                report.unsupported.append(path)
                continue
            try:
                with UnitOfWork(self._sf) as uow:
                    known = uow.voices.find_by_path(str(path))
                    if known is not None and known.in_trash:
                        # Imported again on purpose: it comes back out of the trash.
                        known.deleted_at = None
                        report.imported.append(uow.voices.update(known))
                        continue
                    if known is not None:
                        report.already_present.append(path)
                        continue
                info = probe(path)
                voice = Voice(file_path=str(path), duration_ms=info.duration_ms, format=info.format)
                with UnitOfWork(self._sf) as uow:
                    report.imported.append(uow.voices.add(voice))
            except (OSError, DomainError) as exc:
                report.failed.append((path, str(exc)))
        return report

    def set_tags(self, voice_id: int, tag_ids: Iterable[int]) -> Voice:
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            before, after = set(voice.tag_ids), set(tag_ids)
            if before == after:
                return voice
            voice.set_tags(after)
            saved = uow.voices.update(voice)
            removed = before - after
            names = _tag_names(uow, removed or (after - before))
        self._history.record(
            ChangeKind.TAGS_REMOVED if removed else ChangeKind.TAGS_ADDED,
            Target(TargetKind.VOICE, voice_id),
            undo=lambda: self._set_tags(voice_id, before),
            redo=lambda: self._set_tags(voice_id, after),
            details=names,
            weight=sum(len(n) for n in names),
        )
        return saved

    def set_duration(self, voice_id: int, duration_ms: int) -> Voice:
        """Store the exact duration measured by a full decode (import-time probes can be off)."""
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            if abs(voice.duration_ms - duration_ms) < 50:
                return voice
            voice.duration_ms = duration_ms
            return uow.voices.update(voice)

    def set_archived(self, voice_id: int, archived: bool) -> Voice:
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            if voice.archived == archived:
                return voice
            before = voice.archived_at
            voice.archived_at = utcnow() if archived else None
            saved = uow.voices.update(voice)
        after, name = saved.archived_at, Path(saved.file_path).name
        self._history.record(
            ChangeKind.ARCHIVE if archived else ChangeKind.UNARCHIVE,
            Target(TargetKind.VOICE, voice_id),
            undo=lambda: _shelve(self._sf, "voices", voice_id, "archived_at", before),
            redo=lambda: _shelve(self._sf, "voices", voice_id, "archived_at", after),
            details=(name,),
            weight=len(name),
        )
        return saved

    def delete(self, voice_id: int) -> None:
        """Into the trash. The audio file stays on disk, and the voice keeps its timestamp
        notes, transcript and episode links until the trash is emptied: losing a
        transcript to a mis-click would cost a long re-run."""
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            if voice.in_trash:
                return
            voice.deleted_at = utcnow()
            uow.voices.update(voice)
        when, name = voice.deleted_at, Path(voice.file_path).name
        self._history.record(
            ChangeKind.TRASH,
            Target(TargetKind.VOICE, voice_id),
            undo=lambda: _shelve(self._sf, "voices", voice_id, "deleted_at", None),
            redo=lambda: _shelve(self._sf, "voices", voice_id, "deleted_at", when),
            details=(name,),
            weight=len(name),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_tags(self, voice_id: int, tag_ids: set[int]) -> None:
        with UnitOfWork(self._sf) as uow:
            voice = uow.voices.get(voice_id)
            voice.set_tags(_known_tags(uow, tag_ids))
            uow.voices.update(voice)


class TimestampNoteService:
    """Notes pinned to a position inside one Voice. Separate from IdeaNote by design."""

    def __init__(self, session_factory: sessionmaker[Session], history: HistoryService) -> None:
        self._sf = session_factory
        self._history = history

    def list_for_voice(self, voice_id: int) -> list[TimestampNote]:
        """Sorted by position_ms (then id)."""
        with UnitOfWork(self._sf) as uow:
            notes = uow.timestamp_notes.list_for_voice(voice_id)
        return sorted(notes, key=lambda n: (n.position_ms, n.id or 0))

    def counts_by_voice(self) -> dict[int, int]:
        with UnitOfWork(self._sf) as uow:
            return uow.timestamp_notes.counts_by_voice()

    def texts_by_voice(self) -> dict[int, str]:
        with UnitOfWork(self._sf) as uow:
            return uow.timestamp_notes.texts_by_voice()

    def add(self, voice_id: int, position_ms: int, text: str) -> TimestampNote:
        with UnitOfWork(self._sf) as uow:
            uow.voices.get(voice_id)  # NotFoundError if the voice is gone
            note = uow.timestamp_notes.add(
                TimestampNote(voice_id=voice_id, position_ms=position_ms, text=text)
            )
        assert note.id is not None
        snapshot = deepcopy(note)
        self._history.record(
            ChangeKind.CREATE,
            Target(TargetKind.TIMESTAMP_NOTE, note.id, voice_id),
            undo=lambda: self._erase(snapshot.id),
            redo=lambda: self._restore(snapshot),
            details=(_short(note.text),),
            weight=len(note.text),
        )
        return note

    def edit(self, note_id: int, text: str) -> TimestampNote:
        with UnitOfWork(self._sf) as uow:
            note = uow.timestamp_notes.get(note_id)
            if note.text == text.strip():
                return note
            before, voice_id = note.text, note.voice_id
            note.edit(text)
            saved = uow.timestamp_notes.update(note)
        after = saved.text
        self._history.record(
            ChangeKind.EDIT,
            Target(TargetKind.TIMESTAMP_NOTE, note_id, voice_id),
            undo=lambda: self._set_text(note_id, before),
            redo=lambda: self._set_text(note_id, after),
            details=(_short(after),),
            weight=len(after),
            merge_key=f"stamp:{note_id}",
        )
        return saved

    def delete(self, note_id: int) -> None:
        with UnitOfWork(self._sf) as uow:
            note = deepcopy(uow.timestamp_notes.get(note_id))
            uow.timestamp_notes.delete(note_id)
        self._history.record(
            ChangeKind.DELETE,
            Target(TargetKind.TIMESTAMP_NOTE, note_id, note.voice_id),
            undo=lambda: self._restore(note),
            redo=lambda: self._erase(note_id),
            details=(_short(note.text),),
            weight=len(note.text),
        )

    # inverses ---------------------------------------------------------------------------
    def _set_text(self, note_id: int, text: str) -> None:
        with UnitOfWork(self._sf) as uow:
            note = uow.timestamp_notes.get(note_id)
            note.edit(text)
            uow.timestamp_notes.update(note)

    def _restore(self, note: TimestampNote) -> None:
        with UnitOfWork(self._sf) as uow:
            uow.voices.get(note.voice_id)  # the voice must still be there
            uow.timestamp_notes.add(deepcopy(note))

    def _erase(self, note_id: int | None) -> None:
        if note_id is None:
            return
        with UnitOfWork(self._sf) as uow:
            uow.timestamp_notes.delete(note_id)
