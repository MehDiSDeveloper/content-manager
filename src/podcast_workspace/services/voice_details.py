"""What a voice carries besides its sound: tags, timestamp notes, transcript and its place
in episodes (`Detail`).

When a voice's audio is replaced, or a new copy of it is made (an import under a name it
already has, «خروجی گرفتن»), the user ticks which of these go with it: a new copy takes
the ticked ones from the original (`copy_details`), a replaced voice keeps the ticked ones
and loses the rest (`keep_details`). Times move back by the pauses cut from the audio
(`audio/render.trimmed_ms`), so notes and transcript lines still point at the same words.

None of it is recorded for undo: it is part of a replace or a copy, which are not either.
"""

from podcast_workspace.audio.render import trimmed_ms
from podcast_workspace.audio.silence import Span
from podcast_workspace.domain.entities import (
    TimestampNote,
    Transcript,
    TranscriptSegment,
    Voice,
)
from podcast_workspace.repositories.unit_of_work import UnitOfWork
from podcast_workspace.services.voice_store import Detail


def _shift_notes(notes: list[TimestampNote], cuts: tuple[Span, ...]) -> None:
    for note in notes:
        note.move_to(trimmed_ms(note.position_ms, cuts))


def _shift_segments(
    segments: list[TranscriptSegment], cuts: tuple[Span, ...]
) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(trimmed_ms(s.start_ms, cuts), trimmed_ms(s.end_ms, cuts), s.text)
        for s in segments
    ]


def copy_details(
    uow: UnitOfWork, source_id: int, copy: Voice, details: Detail, cuts: tuple[Span, ...] = ()
) -> Voice:
    """Give `copy` the `details` of voice `source_id`. Episodes it joins are touched, as
    any link is."""
    assert copy.id is not None
    if Detail.TAGS in details:
        copy.set_tags(uow.voices.get(source_id).tag_ids)
        copy = uow.voices.update(copy)
    if Detail.NOTES in details:
        notes = uow.timestamp_notes.list_for_voice(source_id)
        _shift_notes(notes, cuts)
        for note in notes:
            uow.timestamp_notes.add(
                TimestampNote(copy.id, note.position_ms, note.text, note.created_at)
            )
    if Detail.TRANSCRIPT in details:
        transcript = uow.transcripts.for_voice(source_id)
        if transcript is not None:
            uow.transcripts.add(
                Transcript(
                    voice_id=copy.id,
                    segments=_shift_segments(transcript.segments, cuts),
                    language=transcript.language,
                    model=transcript.model,
                    created_at=transcript.created_at,
                )
            )
    if Detail.EPISODES in details:
        for episode in uow.episodes.list_all():
            if source_id in episode.voice_ids:
                episode.voice_ids.add(copy.id)
                episode.touch()
                uow.episodes.update(episode)
    return copy


def keep_details(
    uow: UnitOfWork, voice_id: int, details: Detail, cuts: tuple[Span, ...] = ()
) -> Voice:
    """After a voice's audio was replaced: drop what is not in `details`, and move the
    times of the notes and transcript that stay back by `cuts`."""
    voice = uow.voices.get(voice_id)
    if Detail.TAGS not in details and voice.tag_ids:
        voice.set_tags(set())
        voice = uow.voices.update(voice)
    for note in uow.timestamp_notes.list_for_voice(voice_id):
        if Detail.NOTES not in details:
            assert note.id is not None
            uow.timestamp_notes.delete(note.id)
        elif cuts:
            _shift_notes([note], cuts)
            uow.timestamp_notes.update(note)
    transcript = uow.transcripts.for_voice(voice_id)
    if transcript is not None and transcript.id is not None:
        if Detail.TRANSCRIPT not in details:
            uow.transcripts.delete(transcript.id)
        elif cuts:
            transcript.segments = _shift_segments(transcript.segments, cuts)
            uow.transcripts.update(transcript)
    if Detail.EPISODES not in details:
        for episode in uow.episodes.list_all():
            if voice_id in episode.voice_ids:
                episode.voice_ids.discard(voice_id)
                episode.touch()
                uow.episodes.update(episode)
    return voice
