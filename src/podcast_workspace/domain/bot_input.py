"""Parsing of messages that reach the workspace through the Bale bot. Pure functions.

Conventions (messenger style):
- `#name` is a tag; `_` inside a hashtag stands for a space (#روان_شناسی -> "روان شناسی").
- A message made only of hashtags tags the last received item instead of creating an idea.
- A free-text tag reply may separate names with commas, «،», «؛», new lines or hashtags.
"""

import re
from dataclasses import dataclass

from podcast_workspace.domain.rules import MAX_TAG_NAME_LENGTH, normalize_persian

# A hashtag starts at a word boundary and runs until whitespace or punctuation (not _ or ZWNJ).
_HASHTAG = re.compile(r"(?:(?<=\s)|^)[#＃]([^\s#＃,،;؛.!?؟:«»()\[\]{}\"']+)")
_LIST_SEPARATORS = re.compile(r"[,،;؛\n\r#＃]+")


@dataclass(frozen=True)
class ParsedText:
    text: str  # message with hashtags removed and whitespace tidied
    tags: list[str]  # tag names in order, de-duplicated

    @property
    def tags_only(self) -> bool:
        return bool(self.tags) and not self.text


def _tag_name(raw: str) -> str:
    name = " ".join(normalize_persian(raw).replace("_", " ").split())
    return name[:MAX_TAG_NAME_LENGTH].strip()


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for name in names:
        if name:
            seen.setdefault(name.casefold(), name)
    return list(seen.values())


def parse_message(text: str) -> ParsedText:
    tags = [_tag_name(m.group(1)) for m in _HASHTAG.finditer(text)]
    rest = _HASHTAG.sub(" ", text)
    lines = [" ".join(line.split()) for line in rest.splitlines()]
    body = "\n".join(line for line in lines if line).strip()
    return ParsedText(body, _dedupe(tags))


def split_tag_list(text: str) -> list[str]:
    """Names from a free-text tag reply: "تاریخ، علم #روان_شناسی" -> 3 names."""
    return _dedupe([_tag_name(part) for part in _LIST_SEPARATORS.split(text)])
