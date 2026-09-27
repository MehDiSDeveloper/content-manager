"""A transcript as text to paste elsewhere: whisper's segments merged into paragraphs.

Whisper cuts wherever its 30 s windows and short pauses fall, often mid-sentence, so one
segment per line reads like a list of fragments. Segments are joined into a paragraph until
the speaker pauses, or the paragraph has grown long and a sentence has just ended; a
paragraph that never finds either is cut at a segment boundary anyway.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from podcast_workspace.domain.entities import TranscriptSegment

PAUSE_MS = 1500  # a silence this long starts a new paragraph
SOFT_MAX_CHARS = 400  # past this, the next sentence end closes the paragraph
HARD_MAX_CHARS = 900  # past this, the next segment boundary does
SENTENCE_ENDS = (".", "!", "?", "؟", "…")


@dataclass(frozen=True)
class Paragraph:
    start_ms: int
    text: str


def paragraphs(segments: Iterable[TranscriptSegment]) -> list[Paragraph]:
    out: list[Paragraph] = []
    start = 0
    parts: list[str] = []
    length = 0
    previous_end = 0
    for seg in segments:
        if parts:
            paused = seg.start_ms - previous_end >= PAUSE_MS
            sentence_over = parts[-1].endswith(SENTENCE_ENDS)
            if paused or length >= HARD_MAX_CHARS or (length >= SOFT_MAX_CHARS and sentence_over):
                out.append(Paragraph(start, " ".join(parts)))
                parts, length = [], 0
        if not parts:
            start = seg.start_ms
        parts.append(seg.text)
        length += len(seg.text) + 1
        previous_end = seg.end_ms
    if parts:
        out.append(Paragraph(start, " ".join(parts)))
    return out


def render(
    items: Sequence[Paragraph],
    header: Sequence[str] = (),
    clock: Callable[[int], str] | None = None,
) -> str:
    """Header lines, a blank line, then the paragraphs a blank line apart; each paragraph
    opens with its time in brackets when `clock` is given."""
    body = [f"[{clock(p.start_ms)}] {p.text}" if clock else p.text for p in items]
    blocks = ["\n".join(header)] if header else []
    return "\n\n".join([*blocks, *body])
