"""Utilities package.

Stateless helper functions and small, framework-free building blocks:
filename sanitisation, content hashing, and the safe external-command runner
used by every PDF tool.
"""

from __future__ import annotations

from app.utils.command import CommandError, CommandResult, run_command
from app.utils.filenames import (
    file_extension,
    generate_stored_name,
    human_readable_size,
    sanitize_filename,
)
from app.utils.hashing import sha256_file

__all__ = [
    "CommandError",
    "CommandResult",
    "file_extension",
    "generate_stored_name",
    "human_readable_size",
    "run_command",
    "sanitize_filename",
    "sha256_file",
]
