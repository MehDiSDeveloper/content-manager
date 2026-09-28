"""The publish checklist: what has to be ready before an episode goes out, and where it went.

Four things are ticked by hand — the final title, the description, the clips, the cover —
and the fifth is the answer to "where was it published?", done as soon as it names a
place. That keeps the checklist short enough to glance at, and makes its last line a
record worth having afterwards (the platforms, or the links) rather than one more tick.

A value object, replaced whole on every change, so an undo can simply put the old one back.
"""

from dataclasses import dataclass, replace
from enum import StrEnum

from podcast_workspace.domain.rules import normalize_persian


class PublishStep(StrEnum):
    """The ticked steps, in the order they are shown."""

    TITLE = "title"
    DESCRIPTION = "description"
    CLIPS = "clips"
    COVER = "cover"


def clean_places(text: str) -> str:
    """One place (a platform, a link) per line: trimmed, no blank lines."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return normalize_persian("\n".join(line for line in lines if line))


@dataclass(frozen=True)
class PublishChecklist:
    done: frozenset[PublishStep] = frozenset()
    where: str = ""  # where it was published: one place or link per line

    def __post_init__(self) -> None:
        object.__setattr__(self, "done", frozenset(PublishStep(s) for s in self.done))
        object.__setattr__(self, "where", clean_places(self.where))

    @property
    def total(self) -> int:
        return len(PublishStep) + 1  # the ticked steps, and "where"

    @property
    def completed(self) -> int:
        return len(self.done) + (1 if self.where else 0)

    @property
    def is_complete(self) -> bool:
        return self.completed == self.total

    @property
    def is_empty(self) -> bool:
        return self.completed == 0

    def with_step(self, step: PublishStep, done: bool) -> "PublishChecklist":
        steps = self.done | {step} if done else self.done - {step}
        return replace(self, done=steps)

    def with_where(self, text: str) -> "PublishChecklist":
        return replace(self, where=text)
