"""An episode's script brief: what it is about and how its script should be written.

It is what the script prompt (`domain/script_prompt.py`) is made of, besides the
material the episode already holds (notes, linked ideas, tags, season). Kept apart from
those on purpose: the brief says *how* to write, the material *what* to write from.

The options are combinable wherever combining makes sense — a monologue with a recital
in it, an audience of students and specialists, a conceptual and critical approach that
is calm and a little funny. Depth and register are single choices: an episode sits on one
rung of the depth ladder, and speaks in one register.

A value object, replaced whole on every change, so an undo can simply put the old one back.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from podcast_workspace.domain.rules import normalize_persian


class ScriptFormat(StrEnum):
    MONOLOGUE = "monologue"
    DIALOGUE = "dialogue"
    PANEL = "panel"
    STORY = "story"
    RECITAL = "recital"  # literary prose read over background music


class Audience(StrEnum):
    GENERAL = "general"
    YOUNG = "young"
    ENTHUSIASTS = "enthusiasts"
    STUDENTS = "students"
    EXPERTS = "experts"


class Approach(StrEnum):
    CONCEPTUAL = "conceptual"
    SCIENTIFIC = "scientific"
    PRACTICAL = "practical"
    PHILOSOPHICAL = "philosophical"
    CRITICAL = "critical"


class Mood(StrEnum):
    CALM = "calm"
    WARM = "warm"
    HUMOROUS = "humorous"
    COOL = "cool"
    ENERGETIC = "energetic"
    EXCITING = "exciting"
    EMOTIONAL = "emotional"
    INSPIRING = "inspiring"
    SOMBER = "somber"


class Register(StrEnum):
    """How spoken the language is: Persian writes and speaks quite differently."""

    CASUAL = "casual"
    SEMI_FORMAL = "semi_formal"
    FORMAL = "formal"


DEPTHS = (1, 2, 3, 4, 5)  # the depth ladder: one topic, five episodes, each deeper
MAX_MINUTES = 180  # 0 = no target length


@dataclass(frozen=True)
class ScriptBrief:
    about: str = ""
    formats: frozenset[ScriptFormat] = frozenset({ScriptFormat.MONOLOGUE})
    audiences: frozenset[Audience] = frozenset({Audience.GENERAL})
    depth: int = 1
    approaches: frozenset[Approach] = frozenset({Approach.CONCEPTUAL})
    moods: frozenset[Mood] = frozenset()
    register: Register = Register.SEMI_FORMAL
    minutes: int = 15
    # Notes of the episode the prompt leaves out (a to-do list, a script pasted back in);
    # every other note, including ones written later, goes in as the draft.
    left_out_notes: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        put = object.__setattr__
        put(self, "about", normalize_persian(self.about))
        put(self, "formats", frozenset(ScriptFormat(v) for v in self.formats))
        put(self, "audiences", frozenset(Audience(v) for v in self.audiences))
        put(self, "approaches", frozenset(Approach(v) for v in self.approaches))
        put(self, "moods", frozenset(Mood(v) for v in self.moods))
        put(self, "register", Register(self.register))
        put(self, "depth", min(max(int(self.depth), DEPTHS[0]), DEPTHS[-1]))
        put(self, "minutes", min(max(int(self.minutes), 0), MAX_MINUTES))
        put(self, "left_out_notes", frozenset(int(n) for n in self.left_out_notes))

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON, every set in its enum's order, so the same brief is the same text."""
        return {
            "about": self.about,
            "formats": [v.value for v in ScriptFormat if v in self.formats],
            "audiences": [v.value for v in Audience if v in self.audiences],
            "depth": self.depth,
            "approaches": [v.value for v in Approach if v in self.approaches],
            "moods": [v.value for v in Mood if v in self.moods],
            "register": self.register.value,
            "minutes": self.minutes,
            "left_out_notes": sorted(self.left_out_notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ScriptBrief":
        """Missing keys keep their defaults; values a later version may add are dropped."""
        if not data:
            return cls()
        default = cls()

        def known[E: StrEnum](enum: type[E], key: str, fallback: frozenset[E]) -> frozenset[E]:
            if key not in data:
                return fallback
            values = {v.value for v in enum}
            return frozenset(enum(v) for v in data[key] if v in values)

        register = data.get("register", default.register.value)
        return cls(
            about=str(data.get("about", "")),
            formats=known(ScriptFormat, "formats", default.formats),
            audiences=known(Audience, "audiences", default.audiences),
            depth=int(data.get("depth", default.depth)),
            approaches=known(Approach, "approaches", default.approaches),
            moods=known(Mood, "moods", default.moods),
            register=register if register in {r.value for r in Register} else default.register,
            minutes=int(data.get("minutes", default.minutes)),
            left_out_notes=frozenset(data.get("left_out_notes", ())),
        )
