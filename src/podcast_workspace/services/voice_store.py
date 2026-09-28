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
import shutil
from enum import Enum, auto
from pathlib import Path

from podcast_workspace.paths import data_dir, voices_dir

STORE_DIR = "voices"  # voices_dir()'s name, for checks that must not create it

MTIME_SLACK_S = 2.0  # FAT and some network drives keep times to 2 s


class NameChoice(Enum):
    """What to do with a file whose name a voice in the workspace already has."""

    REPLACE = auto()  # the existing voice gets the new audio; its tags and links stay
    KEEP_BOTH = auto()  # the new one comes in as «name (2)»
    SKIP = auto()


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


def free_name(name: str, taken: set[str]) -> str:
    """`name`, or «stem (2).ext», «stem (3).ext», … — the first one not in `taken`
    (casefolded names) and not already a file in the store."""
    folder = voices_dir()
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, n = name, 2
    while candidate.casefold() in taken or (folder / candidate).exists():
        candidate = f"{stem} ({n}){suffix}"
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
