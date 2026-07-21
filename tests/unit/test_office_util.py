"""Unit tests for the LibreOffice conversion utility (mocked command layer)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions.jobs import ProcessingError
from app.utils import command as command_mod
from app.utils import office
from app.utils.command import CommandError, CommandResult


def _fake_result(command: list[str]) -> CommandResult:
    return CommandResult(
        command=command, returncode=0, stdout="", stderr="", duration_seconds=0.1
    )


class TestLibreofficeConvert:
    def test_builds_isolated_profile_command(self, tmp_path, monkeypatch):
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "deck.pdf").write_bytes(b"%PDF")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        result = office.libreoffice_convert(source, tmp_path)

        assert result == tmp_path / "deck.pdf"
        command = captured["command"]
        assert "--headless" in command
        assert "--convert-to" in command
        # Profile isolation is non-negotiable for concurrent workers.
        assert any(t.startswith("-env:UserInstallation=") for t in command)

    def test_missing_output_raises_processing_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(command_mod, "run_command", lambda c, **k: _fake_result(c))
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        with pytest.raises(ProcessingError, match="produced no output"):
            office.libreoffice_convert(source, tmp_path)

    def test_missing_binary_becomes_processing_error(self, tmp_path, monkeypatch):
        def fake_run(command, **_kwargs):
            raise CommandError("not found", command=command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        with pytest.raises(ProcessingError, match="not available"):
            office.libreoffice_convert(source, tmp_path)

    def test_command_failure_propagates(self, tmp_path, monkeypatch):
        def fake_run(command, **_kwargs):
            raise CommandError("boom", command=command, returncode=77)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        with pytest.raises(CommandError):
            office.libreoffice_convert(source, tmp_path)

    def test_transient_failure_retried_on_fresh_profile(self, tmp_path, monkeypatch):
        """First attempt crashes (corrupt profile), the retry succeeds."""
        calls = {"count": 0}

        def fake_run(command, **_kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise CommandError("profile crash", command=command, returncode=81)
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "deck.pdf").write_bytes(b"%PDF")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        result = office.libreoffice_convert(source, tmp_path)
        assert result.name == "deck.pdf"
        assert calls["count"] == 2

    def test_encrypted_ooxml_gets_password_message(self, tmp_path, monkeypatch):
        """Password-protected OOXML (OLE wrapper) fails with an actionable
        message instead of the generic no-output one."""
        monkeypatch.setattr(command_mod, "run_command", lambda c, **k: _fake_result(c))
        source = tmp_path / "deck.pptx"
        source.write_bytes(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            + b"\x00" * 64
            + "EncryptedPackage".encode("utf-16-le")
        )

        with pytest.raises(ProcessingError, match="password-protected"):
            office.libreoffice_convert(source, tmp_path)


class TestPasswordProtectedDetection:
    def test_plain_zip_is_not_flagged(self, tmp_path):
        path = tmp_path / "deck.pptx"
        path.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
        assert office.is_password_protected_office(path) is False

    def test_plain_ole_is_not_flagged(self, tmp_path):
        path = tmp_path / "legacy.ppt"
        path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
        assert office.is_password_protected_office(path) is False

    def test_encrypted_ooxml_is_flagged(self, tmp_path):
        path = tmp_path / "locked.xlsx"
        path.write_bytes(
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
            + b"\x00" * 32
            + "EncryptionInfo".encode("utf-16-le")
        )
        assert office.is_password_protected_office(path) is True

    def test_target_with_filter_suffix(self, tmp_path, monkeypatch):
        """Targets like 'pdf:impress_pdf_Export' still produce <stem>.pdf."""

        def fake_run(command, **_kwargs):
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "deck.pdf").write_bytes(b"%PDF")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        result = office.libreoffice_convert(
            source, tmp_path, target="pdf:impress_pdf_Export"
        )
        assert result.name == "deck.pdf"

    def test_filter_options_render_soffice_typed_json(self, tmp_path, monkeypatch):
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            outdir = Path(command[command.index("--outdir") + 1])
            (outdir / "deck.pdf").write_bytes(b"%PDF")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        office.libreoffice_convert(
            source,
            tmp_path,
            filter_name="impress_pdf_Export",
            filter_options={"SelectPdfVersion": 2, "PageRange": "1-3"},
        )

        command = captured["command"]
        target = command[command.index("--convert-to") + 1]
        assert target.startswith("pdf:impress_pdf_Export:")
        assert '"SelectPdfVersion":{"type":"long","value":"2"}' in target
        assert '"PageRange":{"type":"string","value":"1-3"}' in target

    def test_unoconvert_engine_command_shape(self, tmp_path, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "UNOCONVERT_BIN", "unoconvert")
        captured: dict[str, list[str]] = {}

        def fake_run(command, **_kwargs):
            captured["command"] = command
            Path(command[-1]).write_bytes(b"%PDF")
            return _fake_result(command)

        monkeypatch.setattr(command_mod, "run_command", fake_run)
        source = tmp_path / "deck.pptx"
        source.write_bytes(b"PK\x03\x04")

        result = office.libreoffice_convert(
            source,
            tmp_path,
            filter_name="impress_pdf_Export",
            filter_options={"SelectPdfVersion": 2, "Watermark": False},
        )

        command = captured["command"]
        assert command[0] == "unoconvert"
        assert "--headless" not in command  # soffice-only flag
        assert command[command.index("--filter") + 1] == "impress_pdf_Export"
        rendered = [
            command[i + 1]
            for i, token in enumerate(command)
            if token == "--filter-options"
        ]
        assert "SelectPdfVersion=2" in rendered
        assert "Watermark=false" in rendered
        assert command[-1] == str(result)
