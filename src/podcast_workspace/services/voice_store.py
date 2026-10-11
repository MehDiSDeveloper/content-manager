"""The workspace's own audio store: where added files are copied to.

A voice added from anywhere outside the data folder is copied into `voices_dir()` and
plays from the copy; the original is remembered as the voice's `source_path` and never
touched. Files the workspace already keeps (Bale voices, audio restored from a backup)
stay where they are.

A file is "the same file" as a stored copy when size and modification time match: the
copy keeps the original's modification time, and a recorder that reuses a name writes a
new file with a new time.
"""

import os
import re
import shutil
from dataclasses import dataclass
from enum import Enum, Flag, auto
from pathlib import Path

from podcast_workspace.paths import data_dir, voices_dir

STORE_DIR = "voices"  # voices_dir()'s name, for checks that must not create it

MTIME_SLACK_S = 2.0  # FAT and some network drives keep times to 2 s
_NUMBER = re.compile(r"^(.*) (\d{2,})$")


class NameChoice(Enum):
    """What to do with a file whose name a voice in the workspace already has."""

    REPLACE = auto()  # the existing voice gets the new audio
    KEEP_BOTH = auto()  # the new one comes in as «name 02»
    SKIP = auto()


class Detail(Flag):
    """What a voice carries besides its sound (`services/voice_details.py`)."""

    NONE = 0
    TAGS = auto()
    NOTES = auto()  # timestamp notes
    TRANSCRIPT = auto()
    EPISODES = auto()  # the episodes it is linked to
    ALL = TAGS | NOTES | TRANSCRIPT | EPISODES


@dataclass(frozen=True)
class NameAnswer:
    """The user's answer about one clashing file. `details`: what a new copy takes from
    the existing voice, or what a replaced voice keeps."""

    choice: NameChoice
    details: Detail = Detail.NONE


def path_key(path: Path | str) -> str:
    """Windows paths compare case-insensitively and with either slash."""
    return os.path.normcase(str(Path(path).resolve()))


def name_key(path: Path | str) -> str:
    return Path(path).name.casefold()


def is_kept(path: Path) -> bool:
    """Already inside the workspace's data folder: nothing to copy."""
    try:
        path.resolve().relative_to(data_dir().resolve())
    except ValueError:
        return False
    return True


def is_stored(path: Path | str) -> bool:
    """One of the store's own copies (the only audio the workspace may delete)."""
    try:
        Path(path).resolve().relative_to((data_dir() / STORE_DIR).resolve())
    except ValueError:
        return False
    return True


def same_file(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
    except OSError:
        return False
    return sa.st_size == sb.st_size and abs(sa.st_mtime - sb.st_mtime) <= MTIME_SLACK_S


def free_name(name: str, taken: set[str], numbered: bool = False) -> str:
    """`name`, or «stem 02.ext», «stem 03.ext», … — the first one not in `taken`
    (casefolded names) and not already a file in the store. `numbered` always adds the
    number (a copy beside its original). A name that is already one of these numbered
    copies («stem 02», beside a «stem») counts on from its original's name instead of
    growing another number."""
    folder = voices_dir()

    def free(candidate: str) -> bool:
        return candidate.casefold() not in taken and not (folder / candidate).exists()

    if not numbered and free(name):
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    match = _NUMBER.match(stem)
    if match and match.group(1).casefold() in {Path(t).stem for t in taken}:
        stem = match.group(1)
    n = 2
    while not free(candidate := f"{stem} {n:02d}{suffix}"):
        n += 1
    return candidate


def store(source: Path, target: Path) -> Path:
    """Copy `source` to `target` in the store, replacing what is there only once the copy
    is complete (a failed copy leaves the old file as it was)."""
    partial = target.with_name(f".{target.name}.partial")
    try:
        shutil.copy2(source, partial)
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return target


def discard(path: Path | str) -> None:
    """Delete one of the store's copies. Anything outside the store is left alone."""
    if is_stored(path):
        Path(path).unlink(missing_ok=True)
