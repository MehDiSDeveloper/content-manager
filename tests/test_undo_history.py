"""Undo/redo: how the stack behaves, and that the inverses really put data back."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import Tag, Voice
from podcast_workspace.repositories.db import create_sqlite_engine, make_session_factory, migrate
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.content_services import EpisodeService, IdeaService, VoiceService
from podcast_workspace.services.history import (
    MAX_ENTRIES,
    ChangeKind,
    HistoryService,
    Target,
    TargetKind,
)
from podcast_workspace.services.tag_service import TagService

TARGET = Target(TargetKind.IDEA, 1)


def noop() -> None:
    pass


def record(history: HistoryService, mark: list[str], name: str, **kwargs) -> None:
    history.record(
        ChangeKind.EDIT,
        TARGET,
        undo=lambda: mark.append(f"undo {name}"),
        redo=lambda: mark.append(f"redo {name}"),
        **kwargs,
    )


# the stack ------------------------------------------------------------------------------
def test_undo_then_redo_runs_both_sides_once() -> None:
    history, mark = HistoryService(), []
    record(history, mark, "a")
    history.undo()
    history.redo()
    assert mark == ["undo a", "redo a"]
    assert history.can_undo() and not history.can_redo()


def test_a_new_change_drops_the_redo_branch() -> None:
    history, mark = HistoryService(), []
    record(history, mark, "a")
    history.undo()
    record(history, mark, "b")
    assert not history.can_redo()


def test_typing_in_one_field_collapses_into_a_single_step() -> None:
    history, mark = HistoryService(), []
    for i in range(5):
        record(history, mark, f"edit{i}", merge_key="idea-text:1")
    history.undo()
    # The oldest "before" and the newest "after" survive: one step for the whole run.
    assert mark == ["undo edit0"]
    history.redo()
    assert mark == ["undo edit0", "redo edit4"]


def test_changes_to_different_fields_stay_separate() -> None:
    history, mark = HistoryService(), []
    record(history, mark, "a", merge_key="idea-text:1")
    record(history, mark, "b", merge_key="idea-text:2")
    history.undo()
    history.undo()
    assert mark == ["undo b", "undo a"]


def test_the_stack_is_capped_by_depth_and_by_remembered_text() -> None:
    history, mark = HistoryService(), []
    for i in range(MAX_ENTRIES + 20):
        record(history, mark, str(i))
    assert len(history._undo) == MAX_ENTRIES

    history = HistoryService()
    for i in range(40):
        record(history, mark, str(i), weight=100_000)
    assert 0 < len(history._undo) < 40  # the budget evicted the oldest entries


def test_suspended_work_never_reaches_the_stack() -> None:
    history, mark = HistoryService(), []
    with history.suspended():
        record(history, mark, "bot")
    assert not history.can_undo()


def test_an_inverse_does_not_record_itself() -> None:
    history = HistoryService()
    seen: list[bool] = []
    history.record(
        ChangeKind.EDIT,
        TARGET,
        undo=lambda: seen.append(history.recording),
        redo=noop,
    )
    history.undo()
    assert seen == [False]


def test_a_change_that_can_no_longer_be_applied_is_dropped() -> None:
    history, mark = HistoryService(), []
    record(history, mark, "old")
    history.record(ChangeKind.DELETE, TARGET, undo=_boom, redo=noop)
    with pytest.raises(RuntimeError):
        history.undo()
    assert not history.can_redo()  # it is gone, not left to fail again
    history.undo()
    assert mark == ["undo old"]  # what was under it still works


def _boom() -> None:
    raise RuntimeError("the item is gone")


# the inverses ---------------------------------------------------------------------------
@pytest.fixture
def factory(tmp_path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    migrate(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def services(factory):
    history = HistoryService()
    return (
        history,
        VoiceService(factory, history),
        TagService(factory, history),
        EpisodeService(factory, history),
        IdeaService(factory, history),
        factory,
    )


def test_undoing_a_tag_removal_puts_that_tag_back(services) -> None:
    history, voices, tags, _episodes, _ideas, factory = services
    with UnitOfWork(factory) as uow:
        voice = uow.voices.add(Voice(file_path="a.wav"))
    sport = tags.create("ورزش", allow_similar=True)
    health = tags.create("سلامت", allow_similar=True)
    voices.set_tags(voice.id, [sport.id, health.id])

    voices.set_tags(voice.id, [health.id])
    assert voices.get(voice.id).tag_ids == {health.id}

    change = history.undo()
    assert voices.get(voice.id).tag_ids == {sport.id, health.id}
    assert change.kind is ChangeKind.TAGS_REMOVED
    assert change.details == ("ورزش",)  # the UI can name what came back

    history.redo()
    assert voices.get(voice.id).tag_ids == {health.id}


def test_undoing_a_tag_deletion_restores_everything_it_was_on(services) -> None:
    history, voices, tags, episodes, _ideas, factory = services
    with UnitOfWork(factory) as uow:
        voice = uow.voices.add(Voice(file_path="a.wav"))
    tag = tags.create("ورزش", allow_similar=True)
    episode = episodes.create("قسمت اول")
    voices.set_tags(voice.id, [tag.id])
    episodes.set_tags(episode.id, [tag.id])

    tags.delete(tag.id)
    assert tags.get(tag.id) is None and voices.get(voice.id).tag_ids == set()

    history.undo()
    assert tags.get(tag.id) is not None
    assert voices.get(voice.id).tag_ids == {tag.id}
    assert episodes.get(episode.id).tag_ids == {tag.id}


def test_undoing_a_merge_separates_the_two_tags_again(services) -> None:
    history, voices, tags, episodes, _ideas, factory = services
    with UnitOfWork(factory) as uow:
        voice = uow.voices.add(Voice(file_path="a.wav"))
    source = tags.create("ورزش", allow_similar=True)
    target = tags.create("سلامت", allow_similar=True)
    episode = episodes.create("قسمت اول")
    voices.set_tags(voice.id, [source.id])
    episodes.set_tags(episode.id, [source.id, target.id])

    tags.merge(source.id, target.id)
    assert voices.get(voice.id).tag_ids == {target.id}

    history.undo()
    assert tags.get(source.id) is not None
    assert voices.get(voice.id).tag_ids == {source.id}  # and not the target it gained
    assert episodes.get(episode.id).tag_ids == {source.id, target.id}


def test_undoing_an_episode_deletion_brings_its_notes_and_links_back(factory) -> None:
    from podcast_workspace.domain.smart_links import LinkKind
    from podcast_workspace.services.content_services import EpisodeNoteService

    history = HistoryService()
    episodes = EpisodeService(factory, history)
    notes = EpisodeNoteService(factory, history)
    with UnitOfWork(factory) as uow:
        voice = uow.voices.add(Voice(file_path="a.wav"))
        tag = uow.tags.add(Tag(name="ورزش"))
    episode = episodes.create("قسمت اول")
    episodes.set_tags(episode.id, [tag.id])
    episodes.link(episode.id, LinkKind.VOICE, voice.id, True)
    notes.create(episode.id, "طرح", "متن")

    episodes.delete(episode.id)
    assert episodes.list_all() == []

    history.undo()
    restored = episodes.get(episode.id)
    assert restored.title == "قسمت اول"
    assert restored.tag_ids == {tag.id} and restored.voice_ids == {voice.id}
    assert [n.body for n in notes.list_for_episode(episode.id)] == ["متن"]


def test_an_undo_leaves_no_trace_on_when_the_episode_was_last_edited(factory) -> None:
    history = HistoryService()
    episodes = EpisodeService(factory, history)
    episode = episodes.create("قسمت اول")
    before = episodes.get(episode.id).updated_at

    from podcast_workspace.domain.entities import EpisodeStatus

    episodes.set_status(episode.id, EpisodeStatus.RECORDED)
    history.undo()
    # The stale marker reads updated_at: an undone change must not look like an edit.
    assert episodes.get(episode.id).updated_at == before
