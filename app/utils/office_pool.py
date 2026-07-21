"""Managed unoserver pool — long-lived LibreOffice conversion engine.

Starting ``soffice`` costs 1.5–3 s per conversion before any real work
happens. `unoserver <https://github.com/unoconv/unoserver>`_ keeps a
LibreOffice instance alive behind a small XML-RPC server, so a warm
conversion costs only the document work itself. This module owns a pool of
such servers inside the current process:

* **spawn** — each slot lazily launches one ``unoserver`` on a free
  localhost port (free ports, not fixed ones, so several worker processes on
  one machine never collide),
* **lease** — conversions borrow a slot under a lock; one LibreOffice never
  handles two documents at once,
* **heal** — a slot whose server died is respawned and the conversion
  retried once,
* **fall back** — when no way to launch unoserver exists on this machine,
  the pool reports :class:`PoolUnavailable` and callers use classic
  ``soffice`` instead.

Cross-platform launcher resolution (first match wins):

1. ``UNOSERVER_BIN`` setting — explicit and authoritative.
2. ``unoserver`` console script on PATH (typical Linux install:
   ``apt install python3-uno && pip install unoserver``).
3. LibreOffice's bundled Python next to ``SOFFICE_BIN`` running the
   ``unoserver`` package from *this* interpreter's site-packages via
   ``PYTHONPATH`` (the Windows story: ``pip install unoserver`` into the
   backend venv is all that's needed — unoserver is pure Python, and only
   LibreOffice's Python has the ``uno`` bridge on Windows).
4. The current interpreter, when it can import both ``unoserver`` and
   ``uno`` (Linux venv created with ``--system-site-packages``).

The ``unoconvert`` *client* is pure stdlib XML-RPC and may run under any
Python; it resolves independently of the server.
"""

from __future__ import annotations

import atexit
import importlib.util
import itertools
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings
from app.logging import get_logger
from app.utils.command import CommandError, run_tool_command, split_launcher

logger = get_logger(__name__)

#: Wall-clock budget for a freshly spawned server to open its port. First
#: run on a cold machine bootstraps a LibreOffice user profile (slow).
_STARTUP_TIMEOUT_SECONDS = 90.0
_STARTUP_POLL_SECONDS = 0.25

FilterValue = str | int | bool


class PoolUnavailable(Exception):
    """No unoserver launcher works on this machine (or startup failed)."""


class PoolCrashed(PoolUnavailable):
    """LibreOffice died on both attempts at one conversion.

    The engine, not the document, is the suspect (a genuinely bad document
    fails the client while the server survives). Carries the underlying
    failure so forced-``unoserver`` mode can surface it.
    """

    def __init__(self, original: CommandError) -> None:
        super().__init__(str(original))
        self.original = original


#: Engine-health score: a conversion that kills LibreOffice costs
#: ``_STRIKE_COST``, a success repays 1 (never below 0). Some LibreOffice
#: builds (portable installs especially) cannot run reliably under UNO
#: control and crash on many or all documents; once the score reaches
#: ``_STRIKE_LIMIT`` the pool disables itself for the process and soffice
#: takes over for good. Weighting crashes over successes makes even a
#: crash-half-the-time build converge on disabled instead of oscillating.
_STRIKE_COST = 2
_STRIKE_LIMIT = 6


def filter_option_args(
    filter_name: str | None,
    filter_options: dict[str, FilterValue] | None,
) -> list[str]:
    """Render export-filter options in ``unoconvert`` CLI syntax.

    Shared with the external-``UNOCONVERT_BIN`` engine in ``office.py`` so
    both unoserver paths speak the exact same dialect.
    """
    args: list[str] = []
    if filter_name:
        args += ["--filter", filter_name]
    for name, value in (filter_options or {}).items():
        rendered = ("true" if value else "false") if isinstance(value, bool) else value
        args += ["--filter-options", f"{name}={rendered}"]
    return args


# ─── Launcher resolution ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Launcher:
    """An argv prefix plus the environment overrides it needs."""

    argv: list[str]
    extra_env: dict[str, str] = field(default_factory=dict)


def _soffice_executable() -> str | None:
    """Resolve SOFFICE_BIN's first token to a concrete executable path."""
    token = split_launcher(get_settings().SOFFICE_BIN)[0]
    if Path(token).is_file():
        return token
    return shutil.which(token)


def _lo_python() -> Path | None:
    """LibreOffice's bundled Python interpreter (next to soffice)."""
    soffice = _soffice_executable()
    if not soffice:
        return None
    program_dir = Path(soffice).resolve().parent
    for name in ("python.exe", "python"):
        candidate = program_dir / name
        if candidate.is_file():
            return candidate
    return None


def _unoserver_package_root() -> str | None:
    """site-packages dir containing ``unoserver``, for PYTHONPATH injection."""
    try:
        spec = importlib.util.find_spec("unoserver")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    return str(Path(spec.origin).parent.parent)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _pythonpath_env(package_root: str) -> dict[str, str]:
    existing = os.environ.get("PYTHONPATH", "")
    joined = f"{package_root}{os.pathsep}{existing}" if existing else package_root
    return {"PYTHONPATH": joined}


def server_launcher_candidates() -> list[_Launcher]:
    """Possible ways to start ``unoserver`` on this machine, best first."""
    settings = get_settings()
    if settings.UNOSERVER_BIN:
        return [_Launcher(split_launcher(settings.UNOSERVER_BIN))]

    candidates: list[_Launcher] = []
    on_path = shutil.which("unoserver")
    if on_path:
        candidates.append(_Launcher([on_path]))
    package_root = _unoserver_package_root()
    lo_python = _lo_python()
    if lo_python and package_root:
        candidates.append(
            _Launcher(
                [str(lo_python), "-m", "unoserver.server"],
                _pythonpath_env(package_root),
            )
        )
    if package_root and _has_module("uno"):
        candidates.append(_Launcher([sys.executable, "-m", "unoserver.server"]))
    return candidates


#: ``unoserver.client`` has no ``__main__`` guard — ``python -m`` runs it as
#: a silent no-op (exit 0!). Invoke the entry point explicitly instead.
_CLIENT_ENTRY = "from unoserver.client import converter_main; converter_main()"


def _client_launcher() -> _Launcher | None:
    """How to run the ``unoconvert`` client (pure XML-RPC, any Python)."""
    # Console script installed next to this interpreter (venv layout) — the
    # venv's Scripts/bin dir is usually NOT on PATH for spawned processes.
    scripts_dir = Path(sys.executable).parent
    for name in ("unoconvert.exe", "unoconvert"):
        script = scripts_dir / name
        if script.is_file():
            return _Launcher([str(script)])
    on_path = shutil.which("unoconvert")
    if on_path:
        return _Launcher([on_path])
    package_root = _unoserver_package_root()
    if package_root:
        if _has_module("unoserver"):
            return _Launcher([sys.executable, "-c", _CLIENT_ENTRY])
        lo_python = _lo_python()
        if lo_python:
            return _Launcher(
                [str(lo_python), "-c", _CLIENT_ENTRY],
                _pythonpath_env(package_root),
            )
    return None


# ─── Server lifecycle ────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


@dataclass
class _Server:
    process: subprocess.Popen[bytes]
    port: int


def _server_died(server: _Server, grace_seconds: float = 2.0) -> bool:
    """Did this server die? unoserver notices LibreOffice's death and exits
    shortly *after* the client sees its conversion fail — grant a grace
    period so the race doesn't misattribute an engine crash to the document.
    """
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            return True
        time.sleep(0.1)
    return server.process.poll() is not None


def _spawn_server(launcher: _Launcher) -> _Server:
    """Start one unoserver and wait until its XML-RPC port accepts."""
    port = _free_port()
    uno_port = _free_port()
    command = [
        *launcher.argv,
        "--interface",
        "127.0.0.1",
        "--port",
        str(port),
        "--uno-interface",
        "127.0.0.1",
        "--uno-port",
        str(uno_port),
    ]
    soffice = _soffice_executable()
    if soffice:
        command += ["--executable", soffice]

    env = {**os.environ, **launcher.extra_env}
    logger.info("unoserver_starting", command=command[0], port=port)
    # S603: argv execution of an operator-configured binary; user data never
    # reaches this command line.
    process = subprocess.Popen(  # noqa: S603
        command,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PoolUnavailable(
                f"unoserver exited with code {process.returncode} during startup"
            )
        if _port_open(port):
            logger.info("unoserver_ready", port=port)
            return _Server(process=process, port=port)
        time.sleep(_STARTUP_POLL_SECONDS)
    process.terminate()
    raise PoolUnavailable(
        f"unoserver did not open port {port} within "
        f"{_STARTUP_TIMEOUT_SECONDS:.0f}s"
    )


class UnoServerPool:
    """A fixed-size pool of unoserver instances owned by this process."""

    def __init__(self, size: int, launcher: _Launcher, client: _Launcher) -> None:
        self._launcher = launcher
        self._client = client
        self._slots = [threading.Lock() for _ in range(max(1, size))]
        self._servers: list[_Server | None] = [None] * len(self._slots)
        self._round_robin = itertools.count()

    @property
    def size(self) -> int:
        return len(self._slots)

    def _ensure_server(self, slot: int) -> _Server:
        """Start (or restart) the slot's server. Caller holds the slot lock."""
        server = self._servers[slot]
        if server is not None and server.process.poll() is None:
            return server
        if server is not None:
            logger.warning(
                "unoserver_died", slot=slot, returncode=server.process.returncode
            )
        self._servers[slot] = _spawn_server(self._launcher)
        return self._servers[slot]  # type: ignore[return-value]

    def prewarm(self) -> None:
        """Start every slot's server (used at worker boot)."""
        for slot, lock in enumerate(self._slots):
            with lock:
                self._ensure_server(slot)

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        *,
        extension: str,
        filter_name: str | None = None,
        filter_options: dict[str, FilterValue] | None = None,
        timeout: int | None = None,
    ) -> None:
        """Convert one document on a leased server, healing a dead one once."""
        # Prefer an idle slot; when all are busy, block round-robin on one so
        # concurrency stays capped at the pool size.
        slot = next(
            (index for index, lock in enumerate(self._slots) if not lock.locked()),
            None,
        )
        if slot is None:
            slot = next(self._round_robin) % len(self._slots)
        with self._slots[slot]:
            server = self._ensure_server(slot)
            try:
                self._run_client(server, input_path, output_path,
                                 extension=extension, filter_name=filter_name,
                                 filter_options=filter_options, timeout=timeout)
            except CommandError as exc:
                # A dead server means the *engine* crashed, not that the
                # document is bad (a bad document fails the client while the
                # server survives — that failure propagates as-is). Don't
                # retry here: the caller's soffice fallback is the retry,
                # and it converts instead of gambling on another crash.
                if exc.timed_out or not _server_died(server):
                    raise
                _record_engine_strike()
                raise PoolCrashed(exc) from exc
            _record_engine_success()

    def _run_client(
        self,
        server: _Server,
        input_path: Path,
        output_path: Path,
        *,
        extension: str,
        filter_name: str | None,
        filter_options: dict[str, FilterValue] | None,
        timeout: int | None,
    ) -> None:
        command = [
            *self._client.argv,
            "--host",
            "127.0.0.1",
            "--port",
            str(server.port),
            "--convert-to",
            extension,
            *filter_option_args(filter_name, filter_options),
            str(input_path),
            str(output_path),
        ]
        env_patch = self._client.extra_env
        if env_patch:
            # run_tool_command has no env parameter; patch/restore around the
            # call. Conversions run in worker processes where this is safe.
            saved = {key: os.environ.get(key) for key in env_patch}
            os.environ.update(env_patch)
            try:
                run_tool_command(command, tool_label="document converter",
                                 timeout=timeout)
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        else:
            run_tool_command(command, tool_label="document converter",
                             timeout=timeout)

    def shutdown(self) -> None:
        for server in self._servers:
            if server is not None and server.process.poll() is None:
                server.process.terminate()
        self._servers = [None] * len(self._slots)


# ─── Process-wide pool singleton ─────────────────────────────────────────────

_pool_lock = threading.Lock()
_pool: UnoServerPool | None = None
_pool_disabled = False
_engine_strikes = 0


def _record_engine_strike() -> None:
    """Score a conversion that killed LibreOffice; disable past the limit."""
    global _engine_strikes, _pool, _pool_disabled
    with _pool_lock:
        _engine_strikes += _STRIKE_COST
        if _engine_strikes < _STRIKE_LIMIT or _pool_disabled:
            return
        logger.error(
            "unoserver_pool_disabled",
            reason="conversions keep crashing LibreOffice — this build "
            "cannot run reliably under UNO control; falling back to "
            "soffice for this process (set OFFICE_ENGINE=soffice to "
            "skip the probing entirely)",
        )
        _pool_disabled = True
        if _pool is not None:
            _pool.shutdown()
            _pool = None


def _record_engine_success() -> None:
    global _engine_strikes
    _engine_strikes = max(0, _engine_strikes - 1)


def _activate_pool() -> UnoServerPool:
    """Create the pool, trying launcher candidates until one server boots.

    A candidate that resolves but cannot actually start a working server
    (e.g. a Python without ``uno`` bindings) is skipped in favour of the
    next. Failure is sticky for the process — don't re-pay the startup
    timeout on every conversion of a busy worker.
    """
    global _pool, _pool_disabled
    with _pool_lock:
        if _pool is not None:
            return _pool
        if _pool_disabled:
            raise PoolUnavailable("unoserver pool is disabled for this process")

        client = _client_launcher()
        candidates = server_launcher_candidates()
        if client is None or not candidates:
            _pool_disabled = True
            raise PoolUnavailable("no unoserver launcher found on this machine")

        settings = get_settings()
        for launcher in candidates:
            probe = UnoServerPool(settings.UNOSERVER_POOL_SIZE, launcher, client)
            try:
                with probe._slots[0]:
                    probe._ensure_server(0)
            except (PoolUnavailable, OSError) as exc:
                logger.warning(
                    "unoserver_launcher_rejected",
                    launcher=launcher.argv[0],
                    error=str(exc),
                )
                continue
            _pool = probe
            atexit.register(probe.shutdown)
            logger.info(
                "unoserver_pool_active",
                launcher=launcher.argv[0],
                size=probe.size,
            )
            return _pool

        _pool_disabled = True
        raise PoolUnavailable("every unoserver launcher candidate failed to start")


def pool_available() -> bool:
    """Cheap check: could/does the managed engine run here?"""
    if _pool is not None:
        return True
    if _pool_disabled:
        return False
    return bool(server_launcher_candidates()) and _client_launcher() is not None


def pool_convert(
    input_path: Path,
    output_path: Path,
    *,
    extension: str,
    filter_name: str | None = None,
    filter_options: dict[str, FilterValue] | None = None,
    timeout: int | None = None,
) -> None:
    """Convert through the managed pool, activating it on first use."""
    _activate_pool().convert(
        input_path,
        output_path,
        extension=extension,
        filter_name=filter_name,
        filter_options=filter_options,
        timeout=timeout,
    )


def pool_prewarm() -> None:
    """Boot all pool servers now (worker startup) — best-effort."""
    try:
        _activate_pool().prewarm()
    except PoolUnavailable as exc:
        logger.info("unoserver_pool_unavailable", reason=str(exc))


def reset_pool_for_tests() -> None:
    """Discard pool state (unit-test hook)."""
    global _pool, _pool_disabled, _engine_strikes
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown()
        _pool = None
        _pool_disabled = False
        _engine_strikes = 0
