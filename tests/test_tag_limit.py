"""The 15-tag cap on Voice and IdeaNote, in the domain and at the persistence boundary."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.entities import Episode, IdeaNote, Tag, Voice
from podcast_workspace.domain.errors import TagLimitExceededError
from podcast_workspace.domain.rules import MAX_TAGS_PER_ITEM
from podcast_workspace.repositories.db import create_sqlite_engine, make_session_factory, migrate
from podcast_workspace.repositories.unit_of_work import UnitOfWork

LIMIT = MAX_TAGS_PER_ITEM


def test_limit_is_fifteen() -> None:
    assert LIMIT == 15


@pytest.mark.parametrize("make", [lambda: Voice(file_path="a.wav"), lambda: IdeaNote(text="x")])
def test_add_tag_allows_exactly_fifteen_and_rejects_sixteenth(make) -> None:
    item = make()
    for tag_id in range(1, LIMIT + 1):
        item.add_tag(tag_id)
    assert len(item.tag_ids) == LIMIT
    with pytest.raises(TagLimitExceededError):
        item.add_tag(LIMIT + 1)
    assert len(item.tag_ids) == LIMIT  # failed add leaves state untouched


@pytest.mark.parametrize("cls,kwargs", [(Voice, {"file_path": "a.wav"}), (IdeaNote, {"text": "x"})])
def test_constructor_and_set_tags_reject_sixteen(cls, kwargs) -> None:
    with pytest.raises(TagLimitExceededError):
        cls(**kwargs, tag_ids=set(range(LIMIT + 1)))
    item = cls(**kwargs)
    with pytest.raises(TagLimitExceededError):
        item.set_tags(set(range(LIMIT + 1)))


def test_re_adding_existing_tag_at_limit_is_fine() -> None:
    note = IdeaNote(text="x", tag_ids=set(range(LIMIT)))
    note.add_tag(0)
    assert len(note.tag_ids) == LIMIT


def test_episode_has_no_tag_limit() -> None:
    episode = Episode(title="e", tag_ids=set(range(LIMIT + 10)))
    assert len(episode.tag_ids) == LIMIT + 10


@pytest.fixture
def session_factory(tmp_path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    migrate(engine)
    yield make_session_factory(engine)
    engine.dispose()


def test_repository_rejects_in_place_mutation_past_limit(session_factory) -> None:
    with UnitOfWork(session_factory) as uow:
        tag_ids = {uow.tags.add(Tag(name=f"tag {i}")).id for i in range(LIMIT + 1)}
        voice = uow.voices.add(Voice(file_path="a.wav"))

    voice.tag_ids = set(tag_ids)  # bypasses add_tag; the repository must still refuse
    with pytest.raises(TagLimitExceededError), UnitOfWork(session_factory) as uow:
        uow.voices.update(voice)

    with UnitOfWork(session_factory) as uow:
        assert uow.voices.get(voice.id).tag_ids == set()  # rolled back
