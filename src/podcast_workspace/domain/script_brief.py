"""An episode's script brief: what it is about and how its script should be written.

It is what the script prompt (`domain/script_prompt.py`) is made of, besides the
material the episode already holds (notes, linked ideas, tags, season). Kept apart from
those on purpose: the brief says *how* to write, the material *what* to write from.

The options are combinable wherever combining makes sense — a story with a recited
passage in it, an audience of students and specialists, a conceptual and critical approach
that is calm and a little funny. Format, depth and register are single choices: an episode
is a monologue or a conversation or a panel, sits on one rung of the depth ladder, and
speaks in one register.

Format (who speaks) and narrative style (how it is told) are separate on purpose: a story
or a recital can be a monologue or a dialogue, and neither is a mood — any mood goes with
either.

A value object, replaced whole on every change, so an undo can simply put the old one back.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from podcast_workspace.domain.rules import normalize_persian


class ScriptFormat(StrEnum):
    """Who speaks."""

    MONOLOGUE = "monologue"
    DIALOGUE = "dialogue"
    PANEL = "panel"


class NarrativeStyle(StrEnum):
    """How it is told, beyond plain explaining (none chosen = plain talk)."""

    STORY = "story"
    RECITAL = "recital"  # literary prose read over background music
    DOCUMENTARY = "documentary"


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
    format: ScriptFormat = ScriptFormat.MONOLOGUE
    styles: frozenset[NarrativeStyle] = frozenset()
    audiences: frozenset[Audience] = frozenset({Audience.GENERAL})
    depth: int = 1
    approaches: frozenset[Approach] = frozenset({Approach.CONCEPTUAL})
    moods: frozenset[Mood] = frozenset()
    register: Register = Register.SEMI_FORMAL
    minutes: int = 15
    # Notes of the episode the prompt leaves out (a to-do list, a script pasted back in);
    # every other note, including ones written later, goes in as the draft.
    left_out_notes: frozenset[int] = field(default_factory=frozenset)
    # What of the season goes in: the producer's readme, and what the season's earlier
    # episodes said (their summaries). Their titles go in either way.
    season_readme: bool = True
    previous_summaries: bool = True

    def __post_init__(self) -> None:
        put = object.__setattr__
        put(self, "about", normalize_persian(self.about))
        put(self, "format", ScriptFormat(self.format))
        put(self, "styles", frozenset(NarrativeStyle(v) for v in self.styles))
        put(self, "audiences", frozenset(Audience(v) for v in self.audiences))
        put(self, "approaches", frozenset(Approach(v) for v in self.approaches))
        put(self, "moods", frozenset(Mood(v) for v in self.moods))
        put(self, "register", Register(self.register))
        put(self, "depth", min(max(int(self.depth), DEPTHS[0]), DEPTHS[-1]))
        put(self, "minutes", min(max(int(self.minutes), 0), MAX_MINUTES))
        put(self, "left_out_notes", frozenset(int(n) for n in self.left_out_notes))
        put(self, "season_readme", bool(self.season_readme))
        put(self, "previous_summaries", bool(self.previous_summaries))

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON, every set in its enum's order, so the same brief is the same text."""
        return {
            "about": self.about,
            "format": self.format.value,
            "styles": [v.value for v in NarrativeStyle if v in self.styles],
            "audiences": [v.value for v in Audience if v in self.audiences],
            "depth": self.depth,
            "approaches": [v.value for v in Approach if v in self.approaches],
            "moods": [v.value for v in Mood if v in self.moods],
            "register": self.register.value,
            "minutes": self.minutes,
            "left_out_notes": sorted(self.left_out_notes),
            "season_readme": self.season_readme,
            "previous_summaries": self.previous_summaries,
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

        def one[E: StrEnum](enum: type[E], value: object, fallback: E) -> E:
            return enum(value) if value in {v.value for v in enum} else fallback

        # The first briefs kept format and style in one list, "formats": split it.
        old = data.get("formats") or ()
        if "format" not in data:
            data = {
                **data,
                "format": next((v for v in old if v in {f.value for f in ScriptFormat}), None),
            }
        if "styles" not in data and old:
            data = {**data, "styles": old}
        return cls(
            about=str(data.get("about", "")),
            format=one(ScriptFormat, data.get("format"), default.format),
            styles=known(NarrativeStyle, "styles", default.styles),
            audiences=known(Audience, "audiences", default.audiences),
            depth=int(data.get("depth", default.depth)),
            approaches=known(Approach, "approaches", default.approaches),
            moods=known(Mood, "moods", default.moods),
            register=one(Register, data.get("register"), default.register),
            minutes=int(data.get("minutes", default.minutes)),
            left_out_notes=frozenset(data.get("left_out_notes", ())),
            season_readme=bool(data.get("season_readme", default.season_readme)),
            previous_summaries=bool(data.get("previous_summaries", default.previous_summaries)),
        )
