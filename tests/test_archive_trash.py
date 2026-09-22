"""Archive and trash: what each hides, what a restore brings back, and what a purge
takes out of the database."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from podcast_workspace.domain.entities import TimestampNote, Transcript, TranscriptSegment, Voice
from podcast_workspace.domain.lifecycle import (
    TRASH_DAYS,
    ArchiveScope,
    TrashKind,
    days_left,
    purge_due,
)
from podcast_workspace.domain.search import SearchKind
from podcast_workspace.domain.smart_links import LinkKind
from podcast_workspace.repositories.db import create_sqlite_engine, make_session_factory, migrate
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.content_services import EpisodeService, IdeaService, VoiceService
from podcast_workspace.services.history import ChangeKind, HistoryService
from podcast_workspace.services.search_service import SearchService
from podcast_workspace.services.tag_service import TagService
from podcast_workspace.services.trash import TrashService

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


# rules ----------------------------------------------------------------------------------
def test_the_switch_shows_active_all_or_archived() -> None:
    assert ArchiveScope.ACTIVE.shows(False) and not ArchiveScope.ACTIVE.shows(True)
    assert ArchiveScope.ARCHIVED.shows(True) and not ArchiveScope.ARCHIVED.shows(False)
    assert ArchiveScope.ALL.shows(True) and ArchiveScope.ALL.shows(False)


def test_days_left_counts_down_to_the_purge() -> None:
    assert days_left(NOW, NOW) == TRASH_DAYS
    assert days_left(NOW, NOW + timedelta(days=29, hours=1)) == 1  # the last day is day 1
    assert days_left(NOW, NOW + timedelta(days=TRASH_DAYS)) == 0
    assert not purge_due(NOW, NOW + timedelta(days=29, hours=23))
    assert purge_due(NOW, NOW + timedelta(days=TRASH_DAYS))


# services -------------------------------------------------------------------------------
@pytest.fixture
def ws(tmp_path):
    engine = create_sqlite_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    migrate(engine)
    factory = make_session_factory(engine)
    history = HistoryService()

    class W:
        pass

    w = W()
    w.factory = factory
    w.history = history
    w.voices = VoiceService(factory, history)
    w.ideas = IdeaService(factory, history)
    w.episodes = EpisodeService(factory, history)
    w.tags = TagService(factory, history)
    w.trash = TrashService(factory)
    w.search = SearchService(factory, _Counter())
    yield w
    engine.dispose()


class _Counter:
    value = 0

    def bump(self) -> None:
        self.value += 1


def _voice(ws, path: str = "a.wav") -> Voice:
    with UnitOfWork(ws.factory) as uow:
        voice = uow.voices.add(Voice(file_path=path))
        uow.timestamp_notes.add(TimestampNote(voice_id=voice.id, position_ms=0, text="شروع"))
        uow.transcripts.add(
            Transcript(voice_id=voice.id, segments=[TranscriptSegment(0, 900, "سلام دنیا")])
        )
    return voice


def _search_ids(ws, query: str, scope=ArchiveScope.ACTIVE) -> set[tuple[SearchKind, int]]:
    hits = ws.search.search(query, scope=scope, in_content=True).hits
    return {(h.kind, h.source_id) for h in hits}


def test_archived_ideas_leave_the_default_list_and_search(ws) -> None:
    idea = ws.ideas.create("کوهنوردی در زمستان")
    ws.ideas.set_archived(idea.id, True)

    assert ws.ideas.list_all(ArchiveScope.ACTIVE) == []
    assert [i.id for i in ws.ideas.list_all(ArchiveScope.ARCHIVED)] == [idea.id]
    assert _search_ids(ws, "کوهنوردی") == set()
    assert (SearchKind.IDEA_NOTE, idea.id) in _search_ids(ws, "کوهنوردی", ArchiveScope.ALL)
    assert (SearchKind.IDEA_NOTE, idea.id) in _search_ids(ws, "کوهنوردی", ArchiveScope.ARCHIVED)

    ws.history.undo()
    assert [i.id for i in ws.ideas.list_all(ArchiveScope.ACTIVE)] == [idea.id]


def test_an_archived_voice_takes_its_notes_and_transcript_with_it(ws) -> None:
    voice = _voice(ws)
    assert _search_ids(ws, "دنیا")  # the transcript is found while the voice is active
    ws.voices.set_archived(voice.id, True)
    assert _search_ids(ws, "دنیا") == set() and _search_ids(ws, "شروع") == set()
    assert _search_ids(ws, "دنیا", ArchiveScope.ALL)


def test_the_trash_hides_an_item_from_everything_but_itself(ws) -> None:
    idea = ws.ideas.create("سفر به شمال")
    tag = ws.tags.create("سفر", allow_similar=True)
    ws.ideas.set_tags(idea.id, [tag.id])
    episode = ws.episodes.create("قسمت اول")
    ws.episodes.set_tags(episode.id, [tag.id])

    ws.ideas.delete(idea.id)
    assert ws.history.peek_undo().kind is ChangeKind.TRASH
    for scope in ArchiveScope:
        assert ws.ideas.list_all(scope) == []
        assert (SearchKind.IDEA_NOTE, idea.id) not in _search_ids(ws, "سفر", scope)
    assert all(link.item_id != idea.id for link in ws.episodes.smart_links(episode.id))
    assert ws.tags.usage_counts()[tag.id] == 1  # only the episode counts now
    assert [i.item_id for i in ws.trash.list()] == [idea.id]

    # Everything it carried is still there.
    assert ws.ideas.get(idea.id).tag_ids == {tag.id}
    ws.trash.restore([(TrashKind.IDEA, idea.id)])
    assert [i.id for i in ws.ideas.list_all()] == [idea.id]
    assert ws.trash.list() == []


def test_undo_takes_an_item_back_out_of_the_trash(ws) -> None:
    voice = _voice(ws)
    ws.voices.delete(voice.id)
    assert ws.voices.list_all() == []
    ws.history.undo()
    assert [v.id for v in ws.voices.list_all()] == [voice.id]


def test_a_restored_archived_item_goes_back_to_the_archive(ws) -> None:
    idea = ws.ideas.create("ایدهٔ قدیمی")
    ws.ideas.set_archived(idea.id, True)
    ws.ideas.delete(idea.id)
    ws.trash.restore([(TrashKind.IDEA, idea.id)])
    assert [i.id for i in ws.ideas.list_all(ArchiveScope.ARCHIVED)] == [idea.id]


def test_purging_a_voice_removes_every_row_that_hung_on_it(ws) -> None:
    voice = _voice(ws)
    tag = ws.tags.create("مصاحبه", allow_similar=True)
    ws.voices.set_tags(voice.id, [tag.id])
    episode = ws.episodes.create("قسمت اول")
    ws.episodes.link(episode.id, LinkKind.VOICE, voice.id, True)
    ws.voices.delete(voice.id)

    report = ws.trash.purge([(TrashKind.VOICE, voice.id)])
    assert report.voices == {voice.id}
    with UnitOfWork(ws.factory) as uow:
        for table, column in (
            ("voices", "id"),
            ("voice_tags", "voice_id"),
            ("timestamp_notes", "voice_id"),
            ("transcripts", "voice_id"),
            ("episode_voices", "voice_id"),
        ):
            count = uow.session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :v"), {"v": voice.id}
            ).scalar()
            assert count == 0, table
    assert ws.tags.get(tag.id) is not None  # the tag itself is shared; it stays
    assert _search_ids(ws, "دنیا", ArchiveScope.ALL) == set()


def test_purge_never_reaches_an_item_outside_the_trash(ws) -> None:
    idea = ws.ideas.create("بماند")
    assert len(ws.trash.purge([(TrashKind.IDEA, idea.id)])) == 0
    assert ws.ideas.get(idea.id) is not None


def test_delete_forever_skips_the_trash_and_takes_every_link(ws) -> None:
    idea = ws.ideas.create("پاک شود")
    tag = ws.tags.create("موقت", allow_similar=True)
    ws.ideas.set_tags(idea.id, [tag.id])
    episode = ws.episodes.create("قسمت دوم")
    ws.episodes.link(episode.id, LinkKind.IDEA, idea.id, True)
    voice = _voice(ws)
    ws.voices.set_archived(voice.id, True)

    report = ws.trash.delete_forever([(TrashKind.IDEA, idea.id), (TrashKind.VOICE, voice.id)])
    assert report.ideas == {idea.id} and report.voices == {voice.id}
    with UnitOfWork(ws.factory) as uow:
        for table, column, item in (
            ("idea_notes", "id", idea.id),
            ("idea_note_tags", "idea_note_id", idea.id),
            ("episode_idea_notes", "idea_note_id", idea.id),
            ("voices", "id", voice.id),
            ("transcripts", "voice_id", voice.id),
        ):
            count = uow.session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :v"), {"v": item}
            ).scalar()
            assert count == 0, table
    assert ws.trash.list() == []
    assert ws.tags.get(tag.id) is not None


def test_a_grouped_change_is_one_undo(ws) -> None:
    ideas = [ws.ideas.create(f"ایدهٔ {n}") for n in range(3)]
    with ws.history.grouped(ChangeKind.TRASH):
        for idea in ideas:
            ws.ideas.delete(idea.id)
    change = ws.history.peek_undo()
    assert change.kind is ChangeKind.TRASH and change.target.item_id == 3
    assert ws.ideas.list_all() == []

    ws.history.undo()
    assert len(ws.ideas.list_all()) == 3
    ws.history.redo()
    assert ws.ideas.list_all() == []


def test_a_group_of_one_stays_a_plain_change(ws) -> None:
    idea = ws.ideas.create("تنها")
    with ws.history.grouped(ChangeKind.ARCHIVE):
        ws.ideas.set_archived(idea.id, True)
    assert ws.history.peek_undo().target.item_id == idea.id


def test_only_items_past_the_period_are_purged(ws) -> None:
    old = ws.ideas.create("قدیمی")
    new = ws.ideas.create("تازه")
    ws.ideas.delete(old.id)
    ws.ideas.delete(new.id)
    with UnitOfWork(ws.factory) as uow:
        item = uow.idea_notes.get(old.id)
        item.deleted_at = NOW - timedelta(days=TRASH_DAYS, minutes=1)
        uow.idea_notes.update(item)
        item = uow.idea_notes.get(new.id)
        item.deleted_at = NOW - timedelta(days=TRASH_DAYS - 1)
        uow.idea_notes.update(item)

    report = ws.trash.purge_expired(NOW)
    assert report.ideas == {old.id}
    assert [i.item_id for i in ws.trash.list()] == [new.id]


def test_importing_a_trashed_file_again_brings_it_back(ws, tmp_path) -> None:
    audio = tmp_path / "take.wav"
    audio.write_bytes(b"")
    with UnitOfWork(ws.factory) as uow:
        voice = uow.voices.add(Voice(file_path=str(audio.resolve())))
    ws.voices.delete(voice.id)
    report = ws.voices.import_files([audio])
    assert [v.id for v in report.imported] == [voice.id]
    assert [v.id for v in ws.voices.list_all()] == [voice.id]


# titles only, unless the content is asked for ----------------------------------------------
def _titles(ws, query: str) -> set[tuple[SearchKind, int]]:
    return {(h.kind, h.source_id) for h in ws.search.search(query).hits}


def test_search_reads_titles_until_the_content_is_asked_for(ws) -> None:
    idea = ws.ideas.create("سفر به شمال\nبا پدر و برادرم رفتیم")
    voice = _voice(ws, "C:/rec/پدر-بزرگ.wav")

    assert _titles(ws, "شمال") == {(SearchKind.IDEA_NOTE, idea.id)}  # the first line
    assert _titles(ws, "برادرم") == set()  # further down: content
    assert (SearchKind.IDEA_NOTE, idea.id) in _search_ids(ws, "برادرم")
    assert (SearchKind.VOICE, voice.id) in _titles(ws, "پدر")  # a file name is a title
    assert _titles(ws, "دنیا") == set()  # transcript
    assert ws.search.search("برادرم").more_in_content == 1
    assert ws.search.search("پدر").more_in_content == 1  # the idea's second line


def test_an_idea_edit_moves_its_title(ws) -> None:
    idea = ws.ideas.create("اول\nدوم")
    ws.ideas.update_text(idea.id, "دوم\nاول")
    assert _titles(ws, "دوم") == {(SearchKind.IDEA_NOTE, idea.id)}
    assert _titles(ws, "اول") == set()
    ws.search.rebuild_index()  # the rebuild indexes titles the way the triggers do
    assert _titles(ws, "دوم") == {(SearchKind.IDEA_NOTE, idea.id)}
