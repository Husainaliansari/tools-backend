"""E2E tests for the final tool batch: OCR, Repair, Compress-scanned,
Metadata, Compare, Redact, Fill Forms, Sign."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from tests.fixtures.factories import (
    make_form_pdf_bytes,
    make_image_bytes,
    make_pdf_bytes,
)

pytestmark = pytest.mark.usefixtures("database")


def _reader(content: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(content))


class TestOcr:
    async def test_options_reach_the_engine(self, run_tool, download):
        job = await run_tool(
            "ocr",
            [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"language": "eng+deu", "deskew": True, "auto_detect_language": False},
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Scan-ocr.pdf"
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert meta.get("/OCRLang") == "eng+deu"
        assert "--deskew" in meta.get("/OCRFlags", "")
        assert "--skip-text" in meta.get("/OCRFlags", "")
        assert "--rotate-pages" in meta.get("/OCRFlags", "")

    async def test_force_ocr_flag(self, run_tool, download):
        job = await run_tool(
            "ocr",
            [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"force_ocr": True, "auto_detect_language": False},
        )
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert "--force-ocr" in meta.get("/OCRFlags", "")

    async def test_rotate_pages_can_be_disabled(self, run_tool, download):
        job = await run_tool(
            "ocr",
            [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"rotate_pages": False, "auto_detect_language": False},
        )
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert "--rotate-pages" not in meta.get("/OCRFlags", "")

    async def test_bad_language_rejected(self, run_tool):
        result = await run_tool(
            "ocr",
            [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"language": "English!"},
        )
        assert result["__response__"].status_code == 422

    async def test_uninstalled_language_rejected(self, run_tool):
        result = await run_tool(
            "ocr",
            [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"language": "xyz", "auto_detect_language": False},
        )
        assert result["__response__"].status_code == 422

    async def test_auto_detect_default_reaches_engine(self, run_tool, download):
        # The fake tesseract reports Latin script + English text, so the
        # detector settles on 'eng' and OCR proceeds with it.
        job = await run_tool(
            "ocr", [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")], {}
        )
        assert job["status"] == "completed", job
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert meta.get("/OCRLang") == "eng"

    async def test_auto_detect_non_latin_script(self, run_tool, download, monkeypatch):
        monkeypatch.setenv("FAKE_TESSERACT_SCRIPT", "Arabic")
        job = await run_tool(
            "ocr", [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")], {}
        )
        assert job["status"] == "completed", job
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert meta.get("/OCRLang") == "ara"

    async def test_auto_detect_failure_falls_back(self, run_tool, download, monkeypatch):
        monkeypatch.setenv("FAKE_TESSERACT_FAIL", "1")
        job = await run_tool(
            "ocr",
            [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"language": "fra"},
        )
        assert job["status"] == "completed", job
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert meta.get("/OCRLang") == "fra"

    async def test_engine_failure_is_reported(self, run_tool):
        job = await run_tool(
            "ocr",
            [("Scan.pdf", make_pdf_bytes(pages=1) + b"CRASHMODE", "application/pdf")],
            {"auto_detect_language": False},
        )
        assert job["status"] == "failed"
        assert "selectable text" in job["error"]["message"]


def _break_startxref(data: bytes) -> bytes:
    """Point startxref at a bogus offset — a real, recoverable corruption
    (libqpdf reconstructs the xref by scanning for objects)."""
    idx = data.rfind(b"startxref")
    return data[:idx] + b"startxref\n999999\n%%EOF\n"


class TestRepair:
    async def test_rewrites_document(self, run_tool, download):
        job = await run_tool(
            "repair", [("Broken.pdf", make_pdf_bytes(pages=2), "application/pdf")]
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Broken-repaired.pdf"
        content = await download(job["output_files"][0]["download_url"])
        assert len(_reader(content).pages) == 2

    async def test_recovers_broken_xref_preserving_content(self, run_tool, download):
        source = make_pdf_bytes(pages=2, text="Important content")
        job = await run_tool(
            "repair", [("Damaged.pdf", _break_startxref(source), "application/pdf")]
        )
        assert job["status"] == "completed", job
        reader = _reader(await download(job["output_files"][0]["download_url"]))
        assert len(reader.pages) == 2
        # Content and page order survive the structural rewrite.
        assert "Important content 1" in (reader.pages[0].extract_text() or "")
        assert "Important content 2" in (reader.pages[1].extract_text() or "")

    async def test_recovers_appended_garbage(self, run_tool, download):
        # Junk bytes after %%EOF (e.g. a truncated re-download) are common.
        job = await run_tool(
            "repair",
            [("warn.pdf", make_pdf_bytes(pages=1) + b"\n%%trailing junk\n",
              "application/pdf")],
        )
        assert job["status"] == "completed", job
        assert len(_reader(await download(
            job["output_files"][0]["download_url"])).pages) == 1

    async def test_unrecoverable_fails_cleanly(self, run_tool):
        # Only the first 55% of a PDF: the trailer/root is gone for good.
        source = make_pdf_bytes(pages=1)
        job = await run_tool(
            "repair",
            [("dead.pdf", source[: len(source) * 55 // 100], "application/pdf")],
        )
        assert job["status"] == "failed"
        assert "too damaged" in job["error"]["message"]

    async def test_partial_truncation_never_returns_broken_output(self, run_tool):
        # Regression: libqpdf opens a moderately-truncated file in recovery
        # mode and writes a *structurally broken* PDF without raising. The
        # tool must validate the result and fail — never report success with
        # a "repaired" file that still will not open.
        source = make_pdf_bytes(pages=3)
        job = await run_tool(
            "repair",
            [("half.pdf", source[: len(source) * 85 // 100], "application/pdf")],
        )
        assert job["status"] == "failed", job
        assert "too damaged" in job["error"]["message"]
        assert not job.get("output_files")

    async def test_header_only_garbage_fails_cleanly(self, run_tool):
        # Passes upload sniffing (has the %PDF marker) but has no usable
        # objects/trailer — libqpdf gives up and we report it cleanly.
        job = await run_tool(
            "repair",
            [("notpdf.pdf", b"%PDF-1.7\n" + b"this is not real pdf structure\n" * 40,
              "application/pdf")],
        )
        assert job["status"] == "failed"
        assert "not a valid PDF" in job["error"]["message"]

    async def test_password_protected_message(self, run_tool):
        import io as _io

        import pikepdf

        buffer = _io.BytesIO()
        with pikepdf.open(_io.BytesIO(make_pdf_bytes(pages=1))) as pdf:
            pdf.save(buffer, encryption=pikepdf.Encryption(user="pw", owner="pw"))
        job = await run_tool(
            "repair", [("locked.pdf", buffer.getvalue(), "application/pdf")]
        )
        assert job["status"] == "failed"
        assert "password-protected" in job["error"]["message"]


class TestCompressScanned:
    async def test_defaults_to_extreme_preset(self, run_tool, download):
        job = await run_tool(
            "compress-scanned",
            [("Scan.pdf", make_pdf_bytes(pages=1), "application/pdf")],
        )
        assert job["status"] == "completed", job
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert meta.get("/GSPreset") == "/screen"


class TestMetadata:
    async def test_sets_document_info(self, run_tool, download):
        job = await run_tool(
            "metadata",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"title": "Annual Report", "author": "ACME"},
        )
        assert job["status"] == "completed", job
        meta = _reader(await download(job["output_files"][0]["download_url"])).metadata
        assert meta.title == "Annual Report"
        assert meta.author == "ACME"

    async def test_empty_options_rejected(self, run_tool):
        result = await run_tool(
            "metadata", [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")], {}
        )
        assert result["__response__"].status_code == 422


class TestCompare:
    async def test_reports_changed_pages(self, run_tool, download):
        job = await run_tool(
            "compare",
            [
                ("v1.pdf", make_pdf_bytes(pages=2, text="Alpha"), "application/pdf"),
                ("v2.pdf", make_pdf_bytes(pages=2, text="Beta"), "application/pdf"),
            ],
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "comparison-report.pdf"
        report = await download(job["output_files"][0]["download_url"])
        text = " ".join(p.extract_text() for p in _reader(report).pages)
        assert "Changed pages: 2 of 2" in text
        assert "Page 1" in text

    async def test_identical_documents(self, run_tool, download):
        same = make_pdf_bytes(pages=1)
        job = await run_tool(
            "compare",
            [("a.pdf", same, "application/pdf"), ("b.pdf", same, "application/pdf")],
        )
        report = await download(job["output_files"][0]["download_url"])
        text = " ".join(p.extract_text() for p in _reader(report).pages)
        assert "textually identical" in text

    async def test_requires_exactly_two(self, run_tool):
        result = await run_tool(
            "compare", [("a.pdf", make_pdf_bytes(pages=1), "application/pdf")]
        )
        assert result["__response__"].status_code == 422


class TestRedact:
    async def test_removes_text_permanently(self, run_tool, download):
        job = await run_tool(
            "redact",
            [
                (
                    "Doc.pdf",
                    make_pdf_bytes(pages=2, text="Secret Code"),
                    "application/pdf",
                )
            ],
            {"texts": ["Secret Code"]},
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Doc-redacted.pdf"
        content = await download(job["output_files"][0]["download_url"])
        for page in _reader(content).pages:
            assert "Secret Code" not in (page.extract_text() or "")

    async def test_text_not_found_fails(self, run_tool):
        job = await run_tool(
            "redact",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"texts": ["does-not-exist-anywhere"]},
        )
        assert job["status"] == "failed"
        assert "were found" in job["error"]["message"]

    async def test_partial_match_fails_safe_and_names_missing_term(self, run_tool):
        """If any requested term is absent, the job fails rather than handing
        back a file the user wrongly believes is fully redacted."""
        job = await run_tool(
            "redact",
            [("Doc.pdf", make_pdf_bytes(pages=1, text="Secret"), "application/pdf")],
            {"texts": ["Secret", "totally-absent-term"]},
        )
        assert job["status"] == "failed", job
        message = job["error"]["message"]
        assert "totally-absent-term" in message
        assert "Secret" not in message  # the found term is not reported as missing

    async def test_redacts_multiple_terms(self, run_tool, download):
        buffer = io.BytesIO()
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen.canvas import Canvas

        canvas = Canvas(buffer, pagesize=LETTER)
        canvas.setFont("Helvetica", 14)
        canvas.drawString(72, 700, "Name: Jane Roe")
        canvas.drawString(72, 660, "SSN: 111-22-3333")
        canvas.save()

        job = await run_tool(
            "redact",
            [("Record.pdf", buffer.getvalue(), "application/pdf")],
            {"texts": ["Jane Roe", "111-22-3333"]},
        )
        assert job["status"] == "completed", job
        text = _reader(
            await download(job["output_files"][0]["download_url"])
        ).pages[0].extract_text() or ""
        assert "Jane Roe" not in text
        assert "111-22-3333" not in text

    async def test_area_redaction_on_scanned_page(self, run_tool, download):
        """A page with no text layer can still be redacted by area."""
        from tests.fixtures.factories import make_image_only_pdf_bytes

        job = await run_tool(
            "redact",
            [("Scan.pdf", make_image_only_pdf_bytes(), "application/pdf")],
            {"areas": [{"page": 1, "x0": 20, "y0": 20, "x1": 150, "y1": 100}]},
        )
        assert job["status"] == "completed", job
        # The output is a valid, single-page PDF.
        content = await download(job["output_files"][0]["download_url"])
        assert len(_reader(content).pages) == 1

    async def test_area_out_of_range_fails_with_guidance(self, run_tool):
        job = await run_tool(
            "redact",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"areas": [{"page": 9, "x0": 0, "y0": 0, "x1": 10, "y1": 10}]},
        )
        assert job["status"] == "failed", job
        assert "page 9" in job["error"]["message"]

    async def test_empty_options_rejected(self, run_tool):
        result = await run_tool(
            "redact",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"texts": [], "areas": []},
        )
        assert result["__response__"].status_code == 422

    async def test_password_protected_input_fails_cleanly(self, run_tool):
        from pypdf import PdfWriter

        encrypted = io.BytesIO()
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        writer.encrypt(user_password="secret", algorithm="AES-256")
        writer.write(encrypted)

        job = await run_tool(
            "redact",
            [("Locked.pdf", encrypted.getvalue(), "application/pdf")],
            {"texts": ["anything"]},
        )
        assert job["status"] == "failed", job
        assert "password-protected" in job["error"]["message"]


class TestFillForms:
    async def test_fills_acroform_fields(self, run_tool, download):
        job = await run_tool(
            "fill-forms",
            [("Form.pdf", make_form_pdf_bytes(("name", "email")), "application/pdf")],
            {"fields": {"name": "Jane Doe", "email": "jane@example.com"}},
        )
        assert job["status"] == "completed", job
        content = await download(job["output_files"][0]["download_url"])
        fields = _reader(content).get_fields()
        assert fields["name"]["/V"] == "Jane Doe"
        assert fields["email"]["/V"] == "jane@example.com"

    async def test_pdf_without_form_fails(self, run_tool):
        job = await run_tool(
            "fill-forms",
            [("Plain.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"fields": {"name": "X"}},
        )
        assert job["status"] == "failed"
        assert "no fillable form fields" in job["error"]["message"]


class TestSign:
    async def test_stamps_signature_on_last_page(self, run_tool, download):
        job = await run_tool(
            "sign",
            [
                ("Contract.pdf", make_pdf_bytes(pages=3), "application/pdf"),
                ("signature.png", make_image_bytes("PNG"), "image/png"),
            ],
            {"position": "bottom-right", "scale": 0.2},
        )
        assert job["status"] == "completed", job
        assert [o["original_name"] for o in job["output_files"]] == [
            "Contract-signed.pdf"
        ]
        reader = _reader(await download(job["output_files"][0]["download_url"]))
        # Image XObject lands on the last page only (default target).
        last_resources = reader.pages[2]["/Resources"].get("/XObject", {})
        first_resources = reader.pages[0]["/Resources"].get("/XObject", {})
        assert last_resources
        assert not first_resources

    async def test_requires_signature_image(self, run_tool):
        job = await run_tool(
            "sign",
            [
                ("a.pdf", make_pdf_bytes(pages=1), "application/pdf"),
                ("b.pdf", make_pdf_bytes(pages=1), "application/pdf"),
            ],
        )
        assert job["status"] == "failed"
        assert "signature" in job["error"]["message"].lower()
