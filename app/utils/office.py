"""LibreOffice document conversion.

Shared by every Office-format converter (PPT/PPTX, DOC/DOCX, XLS/XLSX → PDF).
Three execution engines behind one function, selected by ``OFFICE_ENGINE``:

* **managed unoserver pool** (``auto``/``unoserver``) — this process owns a
  pool of long-lived LibreOffice instances (see ``office_pool.py``). Warm
  conversions skip the ~2s soffice startup entirely; ``auto`` falls back to
  soffice when unoserver cannot run on this machine.
* **soffice** (``soffice``, and the ``auto`` fallback) — one
  ``soffice --headless --convert-to`` process per conversion, with an
  isolated user profile (``-env:UserInstallation``) so concurrent workers
  never deadlock on the shared profile.
* **external unoconvert** (``UNOCONVERT_BIN``) — client of an *externally
  managed* `unoserver <https://github.com/unoconv/unoserver>`_ instance;
  takes precedence over ``OFFICE_ENGINE``.

All engines share the same failure handling: a missing binary and the
LibreOffice "exit 0 but no output" mode are surfaced as
:class:`ProcessingError` with a user-appropriate message.

Export filter options (PDF/A, page ranges, ...) are passed as a plain dict;
each engine renders them in its own syntax.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings
from app.exceptions.jobs import ProcessingError
from app.logging import get_logger
from app.utils.command import CommandError, run_tool_command, split_launcher
from app.utils.office_pool import (
    PoolCrashed,
    PoolUnavailable,
    filter_option_args,
    pool_available,
    pool_convert,
    pool_prewarm,
)

logger = get_logger(__name__)

FilterValue = str | int | bool

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

#: How much of the file's head and tail to scan for OLE encryption stream
#: names. The compound-file directory (where stream names live) sits at the
#: start or end of the file in practice.
_ENCRYPTION_SCAN_BYTES = 4 * 1024 * 1024


def is_password_protected_office(path: Path) -> bool:
    """Detect password-protected OOXML (docx/xlsx/pptx).

    Encrypted OOXML is an OLE compound file whose directory names an
    ``EncryptedPackage``/``EncryptionInfo`` stream (names stored UTF-16LE).
    Cheap byte scan — no OLE parser needed. Legacy binary encryption
    (.doc/.xls/.ppt) is not detectable this way and returns False.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.read(_ENCRYPTION_SCAN_BYTES)
            tail = b""
            if size > _ENCRYPTION_SCAN_BYTES:
                handle.seek(max(size - _ENCRYPTION_SCAN_BYTES, 0))
                tail = handle.read(_ENCRYPTION_SCAN_BYTES)
    except OSError:
        return False
    if not head.startswith(_OLE2_MAGIC):
        return False
    blob = head + tail
    return any(
        marker.encode("utf-16-le") in blob
        for marker in ("EncryptedPackage", "EncryptionInfo")
    )

# Warm-profile pool: soffice bootstraps its user profile on first run with a
# fresh -env:UserInstallation (seconds of pure overhead per conversion when
# every job gets a throwaway profile). Slots are leased under a lock so
# concurrent conversions never share a live profile, and persist across
# conversions so the bootstrap cost is paid once per slot per process.
_pool_lock = threading.Lock()
_profile_slots: list[threading.Lock] = []
_round_robin = itertools.count()


def _purge_stale_profiles(pool_root: Path, *, max_age_hours: int = 24) -> None:
    """Best-effort removal of profiles orphaned by dead worker processes.

    Live workers touch their profiles on every conversion, so anything not
    modified in a day belongs to a process that no longer exists. Keeps the
    cache from growing by pool-size x restarts. The bootstrap template is
    never purged — it is what makes restarts cheap.
    """
    if not pool_root.is_dir():
        return
    cutoff = time.time() - max_age_hours * 3600
    prefix = f"{os.getpid()}-"
    for entry in pool_root.iterdir():
        try:
            if (
                entry.name.startswith(("template", prefix))
                or entry.stat().st_mtime >= cutoff
            ):
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)


def _seed_template(pool_root: Path, profile: Path) -> None:
    """Publish a bootstrapped profile as the clone source for future slots.

    soffice's first run with an empty profile costs tens of seconds (font
    cache, extension registry, ...); copying a finished profile costs about a
    second. Staged copy + rename so concurrent seeders can't publish a
    half-written template — the race's loser just fails the rename and moves
    on.
    """
    template = pool_root / "template"
    if template.exists():
        return
    staging = pool_root / f"template-staging-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        shutil.copytree(profile, staging)
        staging.rename(template)
        logger.info("lo_profile_template_seeded")
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)


@contextmanager
def _warm_profile() -> Iterator[Path]:
    """Lease a persistent LibreOffice profile directory.

    Directories live under ``<storage>/cache/lo-profiles/<pid>-<slot>`` —
    per process, because prefork Celery workers must not share profiles
    across process boundaries. A failed conversion discards its profile
    (it may be corrupted); the next lease bootstraps a fresh one.
    """
    settings = get_settings()
    with _pool_lock:
        if not _profile_slots:
            size = max(1, settings.SOFFICE_PROFILE_POOL_SIZE)
            _profile_slots.extend(threading.Lock() for _ in range(size))
            _purge_stale_profiles(settings.CACHE_DIR / "lo-profiles")
    # Prefer an idle slot; when all are busy, block round-robin on one so
    # concurrency stays capped at the pool size.
    slot = next(
        (index for index, lock in enumerate(_profile_slots) if not lock.locked()),
        None,
    )
    if slot is None:
        slot = next(_round_robin) % len(_profile_slots)
    with _profile_slots[slot]:
        pool_root = settings.CACHE_DIR / "lo-profiles"
        profile = pool_root / f"{os.getpid()}-{slot}"
        template = pool_root / "template"
        if not profile.exists() and template.is_dir():
            try:
                shutil.copytree(template, profile)
            except OSError:
                shutil.rmtree(profile, ignore_errors=True)
        profile.mkdir(parents=True, exist_ok=True)
        try:
            yield profile
        except Exception:
            shutil.rmtree(profile, ignore_errors=True)
            raise
        else:
            _seed_template(pool_root, profile)


def _soffice_target(
    target: str,
    filter_name: str | None,
    filter_options: dict[str, FilterValue] | None,
) -> str:
    """Render soffice's ``--convert-to`` argument, e.g.
    ``pdf:impress_pdf_Export:{"SelectPdfVersion":{"type":"long","value":"2"}}``.
    """
    if not filter_name:
        return target
    if not filter_options:
        return f"{target}:{filter_name}"

    def typed(value: FilterValue) -> dict[str, str]:
        if isinstance(value, bool):
            return {"type": "boolean", "value": "true" if value else "false"}
        if isinstance(value, int):
            return {"type": "long", "value": str(value)}
        return {"type": "string", "value": value}

    payload = json.dumps(
        {name: typed(value) for name, value in filter_options.items()},
        separators=(",", ":"),
    )
    return f"{target}:{filter_name}:{payload}"


def office_engine() -> str:
    """Engine used by conversions in this process.

    ``'external'`` (operator-managed unoserver via ``UNOCONVERT_BIN``),
    ``'pool'`` (managed unoserver pool) or ``'soffice'`` (per-conversion
    process).
    """
    settings = get_settings()
    if settings.UNOCONVERT_BIN:
        return "external"
    if settings.OFFICE_ENGINE == "soffice":
        return "soffice"
    if settings.OFFICE_ENGINE == "unoserver":
        return "pool"
    return "pool" if pool_available() else "soffice"


def office_conversion_slots() -> int:
    """How many Office conversions this process can usefully run at once.

    Multi-file tasks size their thread pools with this: the managed engine
    converts on ``UNOSERVER_POOL_SIZE`` live servers, the soffice engine on
    ``SOFFICE_PROFILE_POOL_SIZE`` leased profiles. One external unoserver
    handles a single document at a time, so parallel clients would only
    queue against it.
    """
    settings = get_settings()
    engine = office_engine()
    if engine == "external":
        return 1
    if engine == "pool":
        return max(1, settings.UNOSERVER_POOL_SIZE)
    return max(1, settings.SOFFICE_PROFILE_POOL_SIZE)


def libreoffice_convert(
    input_path: Path,
    output_dir: Path,
    *,
    target: str = "pdf",
    filter_name: str | None = None,
    filter_options: dict[str, FilterValue] | None = None,
    profile_dir: Path | None = None,
    timeout: int | None = None,
    display_name: str | None = None,
) -> Path:
    """Convert one document; return the produced file's path.

    ``display_name`` is the user-facing name used in error messages (the
    on-disk ``input_path`` is a storage UUID the user has never seen).
    """
    settings = get_settings()
    extension = target.split(":", 1)[0]
    expected = output_dir / f"{input_path.stem}.{extension}"

    def convert_with_soffice() -> None:
        def run_soffice(active_profile: Path) -> CommandError | None:
            """One conversion attempt; returns the failure instead of raising
            so the caller can decide whether a retry is worthwhile."""
            command = [
                *split_launcher(settings.SOFFICE_BIN),
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                f"-env:UserInstallation={active_profile.resolve().as_uri()}",
                "--convert-to",
                _soffice_target(target, filter_name, filter_options),
                "--outdir",
                str(output_dir),
                str(input_path),
            ]
            try:
                run_tool_command(
                    command, tool_label="document converter", timeout=timeout
                )
            except CommandError as exc:
                if exc.timed_out:
                    raise
                return exc
            return None

        @contextmanager
        def explicit_profile() -> Iterator[Path]:
            profile_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
            yield profile_dir  # type: ignore[misc]

        lease = explicit_profile() if profile_dir is not None else _warm_profile()
        with lease as active_profile:
            failure = run_soffice(active_profile)
            if failure is not None or not expected.is_file():
                # Retry once on a pristine profile: a corrupted user profile
                # is the leading cause of intermittent soffice failures
                # (crashes and the "exit 0, no output" mode alike).
                logger.warning(
                    "soffice_retry_fresh_profile",
                    input=input_path.name,
                    reason=str(failure) if failure else "no output produced",
                )
                shutil.rmtree(active_profile, ignore_errors=True)
                active_profile.mkdir(parents=True, exist_ok=True)
                failure = run_soffice(active_profile)
            if failure is not None:
                raise failure

    if settings.UNOCONVERT_BIN:
        command = [
            *split_launcher(settings.UNOCONVERT_BIN),
            "--convert-to",
            extension,
            *filter_option_args(filter_name, filter_options),
            str(input_path),
            str(expected),
        ]
        run_tool_command(command, tool_label="document converter", timeout=timeout)
    elif office_engine() == "pool":
        try:
            pool_convert(
                input_path,
                expected,
                extension=extension,
                filter_name=filter_name,
                filter_options=filter_options,
                timeout=timeout,
            )
        except PoolCrashed as exc:
            if settings.OFFICE_ENGINE == "unoserver":
                # Forced mode: surface the real conversion failure.
                raise exc.original from exc
            logger.warning("office_pool_fallback_soffice", reason=str(exc))
            convert_with_soffice()
        except PoolUnavailable as exc:
            if settings.OFFICE_ENGINE == "unoserver":
                # Forced mode surfaces misconfiguration instead of silently
                # degrading to 10x slower conversions under load.
                raise ProcessingError(
                    "The document converter service is not available on "
                    "this server."
                ) from exc
            logger.warning("office_pool_fallback_soffice", reason=str(exc))
            convert_with_soffice()
    else:
        convert_with_soffice()

    if not expected.is_file():
        display = display_name or input_path.name
        if is_password_protected_office(input_path):
            raise ProcessingError(
                f"'{display}' is password-protected. Remove the password in "
                "PowerPoint/Excel/Word (File → Info → Protect) and try again."
            )
        raise ProcessingError(
            f"Conversion produced no output for '{display}'. "
            "The file may be corrupted or use unsupported features."
        )
    return expected


_prewarm_started = False


def prewarm_office_runtime() -> None:
    """Bootstrap the conversion engine in the background at startup.

    Managed-pool engine: boot every unoserver instance now, so the first
    user conversion finds a warm LibreOffice. soffice engine: convert a
    throwaway document, paying the first-run profile bootstrap (tens of
    seconds — font cache, registry) and seeding the clone template. Either
    way, no user conversion pays a cold start. Best-effort and idempotent;
    a no-op under an external unoserver (it keeps its own warm instance).
    """
    global _prewarm_started
    settings = get_settings()
    if settings.UNOCONVERT_BIN or _prewarm_started:
        return
    _prewarm_started = True

    def warm() -> None:
        import tempfile

        try:
            if office_engine() == "pool":
                pool_prewarm()
            # Re-evaluate: a pool that failed to activate has disabled
            # itself, and 'auto' now resolves to the soffice fallback —
            # which then deserves its own warmup.
            if office_engine() == "soffice":
                with tempfile.TemporaryDirectory(prefix="lo-warmup-") as scratch:
                    seed = Path(scratch) / "warmup.txt"
                    seed.write_text("warmup", encoding="utf-8")
                    libreoffice_convert(seed, Path(scratch), display_name="warmup.txt")
            logger.info("office_runtime_prewarmed", engine=office_engine())
        except Exception as exc:  # prewarm must never break startup
            logger.warning("office_prewarm_failed", error=str(exc))

    threading.Thread(target=warm, name="office-prewarm", daemon=True).start()
