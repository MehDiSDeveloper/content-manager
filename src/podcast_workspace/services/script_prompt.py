"""Gathers what an episode holds into a `ScriptMaterial` for the script prompt.

Read once when the prompt is opened; the prompt itself is rebuilt from it on every change
of the brief (`domain/script_prompt.build_prompt`), so editing the brief costs no query.
"""

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from podcast_workspace.domain.script_brief import ScriptBrief
from podcast_workspace.domain.script_prompt import (
    DraftNote,
    IdeaMaterial,
    ScriptMaterial,
    SeasonMaterial,
)
from podcast_workspace.domain.transcript_export import paragraphs, render
from podcast_workspace.repositories.unit_of_work import UnitOfWork


class ScriptPromptService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def material(self, episode_id: int) -> ScriptMaterial:
        with UnitOfWork(self._sf) as uow:
            episode = uow.episodes.get(episode_id)
            tags = sorted(t.name for t in uow.tags.list_all() if t.id in episode.tag_ids)
            season = None
            if episode.season_id is not None:
                found = uow.seasons.get(episode.season_id)
                others = sorted(
                    (e for e in uow.episodes.list_all() if e.season_id == found.id),
                    key=lambda e: e.created_at,
                )
                season = SeasonMaterial(
                    found.title,
                    found.summary,
                    found.outline,
                    # A depth only where the brief was filled in: a default 1 would mislead.
                    tuple(
                        (e.title, e.brief.depth if e.brief != ScriptBrief() else 0)
                        for e in others
                        if e.id != episode_id
                    ),
                )
            notes = tuple(
                DraftNote(n.id, n.title, n.body)
                for n in uow.episode_notes.list_for_episode(episode_id)
                if n.id is not None
            )

            # Ideas in the order they came to me, text and audio together.
            dated: list[tuple[float, IdeaMaterial]] = []
            unread: list[str] = []
            for idea_id in episode.idea_note_ids:
                idea = uow.idea_notes.find(idea_id)
                if idea is not None and not idea.in_trash:
                    dated.append((idea.created_at.timestamp(), IdeaMaterial(False, "", idea.text)))
            for voice_id in episode.voice_ids:
                voice = uow.voices.find(voice_id)
                if voice is None or voice.in_trash:
                    continue
                name = Path(voice.file_path).stem
                transcript = uow.transcripts.for_voice(voice_id)
                text = render(paragraphs(transcript.segments)) if transcript else ""
                marks = tuple(n.text for n in uow.timestamp_notes.list_for_voice(voice_id))
                if text or marks:
                    item = IdeaMaterial(True, name, text, marks)
                    dated.append((voice.imported_at.timestamp(), item))
                else:
                    unread.append(name)
        dated.sort(key=lambda pair: pair[0])
        return ScriptMaterial(
            title=episode.title,
            tags=tuple(tags),
            season=season,
            notes=notes,
            ideas=tuple(item for _, item in dated),
            unread_voices=tuple(sorted(unread)),
        )
