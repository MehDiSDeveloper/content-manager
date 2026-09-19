"""Recording handoff: launch the user's own recording program. This app never records audio."""

import os
from pathlib import Path


class RecorderNotConfiguredError(Exception):
    pass


def launch_recorder(program_path: str) -> None:
    """Start the program detached. Accepts .exe, .lnk and anything Explorer can open."""
    if not program_path.strip():
        raise RecorderNotConfiguredError
    path = Path(program_path.strip().strip('"'))
    if not path.exists():
        raise FileNotFoundError(str(path))
    os.startfile(str(path))
