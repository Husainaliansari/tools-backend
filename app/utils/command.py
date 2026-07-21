"""Safe external-command execution.

Every PDF tool ultimately shells out to a CLI (Ghostscript, QPDF, Poppler,
LibreOffice, ...). This wrapper is the single place such invocations happen,
guaranteeing:

* argument-list execution only (``shell=False`` — no injection surface),
* a hard wall-clock timeout with process cleanup,
* captured, size-capped stdout/stderr for diagnostics,
* structured logging of every invocation.

Runs synchronously — external tools execute inside Celery workers, never in
the API event loop.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_MAX_CAPTURED_OUTPUT = 64 * 1024


class CommandError(Exception):
    """An external command failed (non-zero exit or timeout)."""

    def __init__(
        self,
        message: str,
        *,
        command: list[str],
        returncode: int | None = None,
        stderr: str = "",
        timed_out: bool = False,
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        self.timed_out = timed_out


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a successful command invocation."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


def split_launcher(value: str) -> list[str]:
    """Split a launcher setting into argv tokens.

    Accepts a bare name (``soffice``), a quoted absolute path
    (``"C:\\Program Files\\...\\soffice.exe"``) or a wrapper command with
    arguments. posix=False keeps Windows backslashes intact but retains
    surrounding quotes, so quotes are stripped per token.
    """
    import shlex

    return [token.strip('"') for token in shlex.split(value, posix=False)]


def run_tool_command(
    command: list[str],
    *,
    tool_label: str,
    cwd: Path | None = None,
    timeout: int | None = None,
    ok_returncodes: tuple[int, ...] = (0,),
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run an external PDF tool, translating a missing binary into a
    user-appropriate error instead of an internal one.

    Deliberately lazy import to avoid a circular dependency: this module is
    imported by the exceptions' consumers, not vice versa.
    """
    from app.exceptions.jobs import ProcessingError

    try:
        return run_command(
            command, cwd=cwd, timeout=timeout, ok_returncodes=ok_returncodes, env=env
        )
    except CommandError as exc:
        if exc.returncode is None and not exc.timed_out:
            # Binary not found — an operational problem, not a bad input.
            raise ProcessingError(
                f"The {tool_label} is not available on this server."
            ) from exc
        raise


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    check: bool = True,
    ok_returncodes: tuple[int, ...] = (0,),
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run an external tool and return its captured output.

    ``ok_returncodes`` accommodates tools like QPDF that use exit code 3 for
    "succeeded with warnings".
    """
    settings = get_settings()
    timeout = timeout or settings.TOOL_COMMAND_TIMEOUT_SECONDS
    started = time.monotonic()

    logger.info("external_command_start", command=command[0], args=command[1:])
    try:
        # S603: argument-list execution with shell=False against binaries we
        # choose; user data only ever appears as file paths, never parsed by
        # a shell.
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        logger.error(
            "external_command_timeout",
            command=command[0],
            timeout_seconds=timeout,
            duration_seconds=round(duration, 2),
        )
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise CommandError(
            f"Command '{command[0]}' timed out after {timeout}s.",
            command=command,
            stderr=stderr[:_MAX_CAPTURED_OUTPUT],
            timed_out=True,
        ) from exc
    except FileNotFoundError as exc:
        raise CommandError(
            f"Command '{command[0]}' not found. Is it installed and on PATH?",
            command=command,
        ) from exc

    duration = time.monotonic() - started
    stdout = completed.stdout[:_MAX_CAPTURED_OUTPUT]
    stderr = completed.stderr[:_MAX_CAPTURED_OUTPUT]

    if check and completed.returncode not in ok_returncodes:
        logger.error(
            "external_command_failed",
            command=command[0],
            returncode=completed.returncode,
            stderr=stderr[:500],
            duration_seconds=round(duration, 2),
        )
        raise CommandError(
            f"Command '{command[0]}' exited with code {completed.returncode}.",
            command=command,
            returncode=completed.returncode,
            stderr=stderr,
        )

    logger.info(
        "external_command_finished",
        command=command[0],
        returncode=completed.returncode,
        duration_seconds=round(duration, 2),
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration,
    )
