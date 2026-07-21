"""Unit tests for the managed unoserver pool and office engine routing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.config import get_settings
from app.exceptions.jobs import ProcessingError
from app.utils import command as command_mod
from app.utils import office, office_pool
from app.utils.command import CommandResult
from app.utils.office_pool import (
    PoolUnavailable,
    _Launcher,
    filter_option_args,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_FAKE_SERVER = _Launcher([sys.executable, str(_FIXTURES / "fake_unoserver.py")])
_FAKE_CLIENT = _Launcher([sys.executable, str(_FIXTURES / "fake_unoconvert.py")])


@pytest.fixture(autouse=True)
def clean_pool():
    """Pool activation state is process-global and sticky — isolate tests."""
    office_pool.reset_pool_for_tests()
    yield
    office_pool.reset_pool_for_tests()


def _use_fake_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        office_pool, "server_launcher_candidates", lambda: [_FAKE_SERVER]
    )
    monkeypatch.setattr(office_pool, "_client_launcher", lambda: _FAKE_CLIENT)


def _no_engine(monkeypatch) -> None:
    monkeypatch.setattr(office_pool, "server_launcher_candidates", lambda: [])
    monkeypatch.setattr(office_pool, "_client_launcher", lambda: None)


class TestFilterOptionArgs:
    def test_renders_unoconvert_dialect(self):
        args = filter_option_args(
            "impress_pdf_Export", {"SelectPdfVersion": 2, "Watermark": False}
        )
        assert args == [
            "--filter",
            "impress_pdf_Export",
            "--filter-options",
            "SelectPdfVersion=2",
            "--filter-options",
            "Watermark=false",
        ]

    def test_empty_without_filter(self):
        assert filter_option_args(None, None) == []


class TestLauncherResolution:
    def test_explicit_unoserver_bin_is_authoritative(self, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "UNOSERVER_BIN", '"C:\\tools\\python.exe" -m unoserver.server'
        )
        candidates = office_pool.server_launcher_candidates()
        assert len(candidates) == 1
        assert candidates[0].argv == ["C:\\tools\\python.exe", "-m", "unoserver.server"]


class TestPoolConvert:
    def test_converts_through_leased_server(self, tmp_path, monkeypatch):
        _use_fake_engine(monkeypatch)
        monkeypatch.setattr(get_settings(), "OFFICE_ENGINE", "auto")
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        result = office.libreoffice_convert(source, tmp_path)

        assert result == tmp_path / "deck.pdf"
        assert b"fake unoconvert" in result.read_bytes()
        pool = office_pool._pool
        assert pool is not None
        assert pool._servers[0] is not None
        assert pool._servers[0].process.poll() is None  # server stays warm

    def test_respawns_dead_server(self, tmp_path, monkeypatch):
        _use_fake_engine(monkeypatch)
        monkeypatch.setattr(get_settings(), "OFFICE_ENGINE", "auto")
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")
        office.libreoffice_convert(source, tmp_path)

        server = office_pool._pool._servers[0]
        server.process.kill()
        server.process.wait(timeout=10)

        again = office.libreoffice_convert(source, tmp_path)
        assert again.is_file()
        respawned = office_pool._pool._servers[0]
        assert respawned.process.pid != server.process.pid

    def test_startup_failure_falls_back_to_soffice(self, tmp_path, monkeypatch):
        """A launcher that resolves but cannot start must not break 'auto'."""
        _use_fake_engine(monkeypatch)
        monkeypatch.setenv("FAKE_UNOSERVER_EXIT", "1")
        monkeypatch.setattr(get_settings(), "OFFICE_ENGINE", "auto")
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        # Falls through to the (stubbed) soffice engine and still converts.
        result = office.libreoffice_convert(source, tmp_path)
        assert result.is_file()
        assert office_pool.pool_available() is False  # disabled, sticky

    def test_forced_unoserver_unavailable_is_processing_error(
        self, tmp_path, monkeypatch
    ):
        _no_engine(monkeypatch)
        monkeypatch.setattr(get_settings(), "OFFICE_ENGINE", "unoserver")
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        with pytest.raises(ProcessingError, match="not available"):
            office.libreoffice_convert(source, tmp_path)

    def test_engine_crash_falls_back_to_soffice(self, tmp_path, monkeypatch):
        """LibreOffice dying on a conversion (both attempts) must not fail
        the job in 'auto' — the classic soffice engine finishes it."""
        _use_fake_engine(monkeypatch)
        monkeypatch.setenv("FAKE_UNOSERVER_ONESHOT", "1")
        monkeypatch.setattr(get_settings(), "OFFICE_ENGINE", "auto")
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04 UNOCRASH")  # crashes unoconvert only

        result = office.libreoffice_convert(source, tmp_path)

        assert result.is_file()  # produced by the soffice fallback
        assert office_pool._engine_strikes == office_pool._STRIKE_COST

    def test_repeated_engine_crashes_disable_pool(self, tmp_path, monkeypatch):
        _use_fake_engine(monkeypatch)
        monkeypatch.setenv("FAKE_UNOSERVER_ONESHOT", "1")
        monkeypatch.setattr(get_settings(), "OFFICE_ENGINE", "auto")

        for index in range(office_pool._STRIKE_LIMIT // office_pool._STRIKE_COST):
            source = tmp_path / f"deck{index}.pptx"
            source.write_bytes(b"PK\x03\x04 UNOCRASH")
            office.libreoffice_convert(source, tmp_path)

        assert office_pool.pool_available() is False
        assert office.office_engine() == "soffice"


class TestEngineRouting:
    def test_auto_without_engine_uses_soffice(self, tmp_path, monkeypatch):
        _no_engine(monkeypatch)
        monkeypatch.setattr(get_settings(), "OFFICE_ENGINE", "auto")
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "deck.pdf").write_bytes(b"%PDF")
            return CommandResult(
                command=command, returncode=0, stdout="", stderr="",
                duration_seconds=0.1,
            )

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        office.libreoffice_convert(source, tmp_path)
        assert "--headless" in captured["command"]

    def test_conversion_slots_follow_engine(self, monkeypatch):
        settings = get_settings()

        monkeypatch.setattr(settings, "OFFICE_ENGINE", "soffice")
        assert office.office_conversion_slots() == settings.SOFFICE_PROFILE_POOL_SIZE

        monkeypatch.setattr(settings, "UNOCONVERT_BIN", "unoconvert")
        assert office.office_conversion_slots() == 1
        monkeypatch.setattr(settings, "UNOCONVERT_BIN", "")

        _use_fake_engine(monkeypatch)
        monkeypatch.setattr(settings, "OFFICE_ENGINE", "auto")
        assert office.office_conversion_slots() == settings.UNOSERVER_POOL_SIZE
