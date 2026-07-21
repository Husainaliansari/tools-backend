"""E2E tests for Compress (stub Ghostscript), Word/Excel→PDF (stub soffice)
and PDF→Word (real pdf2docx)."""

from __future__ import annotations

import io
import zipfile

import pytest
from pypdf import PdfReader

from tests.fixtures.factories import make_pdf_bytes

DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 64
XLSX_BYTES = b"PK\x03\x04" + b"\x00" * 64

pytestmark = pytest.mark.usefixtures("database")


class TestCompress:
    async def test_compresses_with_selected_preset(self, run_tool, download):
        job = await run_tool(
            "compress",
            [("Big Report.pdf", make_pdf_bytes(pages=2), "application/pdf")],
            {"quality": "extreme"},
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Big Report-compressed.pdf"

        content = await download(job["output_files"][0]["download_url"])
        reader = PdfReader(io.BytesIO(content))
        assert len(reader.pages) == 2
        # The stub records the Ghostscript preset it received as metadata.
        assert reader.metadata.get("/GSPreset") == "/screen"

    async def test_default_quality_is_recommended(self, run_tool, download):
        job = await run_tool(
            "compress", [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")]
        )
        content = await download(job["output_files"][0]["download_url"])
        assert PdfReader(io.BytesIO(content)).metadata.get("/GSPreset") == "/ebook"

    async def test_invalid_quality_rejected(self, run_tool):
        result = await run_tool(
            "compress",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"quality": "maximum"},
        )
        assert result["__response__"].status_code == 422

    async def test_crash_fails_job(self, run_tool):
        job = await run_tool(
            "compress",
            [("bad.pdf", make_pdf_bytes(pages=1) + b"CRASHMODE", "application/pdf")],
        )
        assert job["status"] == "failed"


class TestOfficeToPdf:
    async def test_word_to_pdf(self, run_tool, download):
        job = await run_tool(
            "word-to-pdf",
            [("Proposal.docx", DOCX_BYTES, "application/octet-stream")],
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Proposal.pdf"
        content = await download(job["output_files"][0]["download_url"])
        assert content.startswith(b"%PDF")

    async def test_excel_to_pdf_rejects_docx(self, run_tool):
        result = await run_tool(
            "excel-to-pdf",
            [("Proposal.docx", DOCX_BYTES, "application/octet-stream")],
        )
        assert result["__response__"].status_code == 415

    async def test_excel_to_pdf(self, run_tool):
        job = await run_tool(
            "excel-to-pdf",
            [("Budget.xlsx", XLSX_BYTES, "application/octet-stream")],
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Budget.pdf"


class TestPdfToWord:
    async def test_converts_to_editable_docx(self, run_tool, download):
        job = await run_tool(
            "pdf-to-word",
            [("Thesis.pdf", make_pdf_bytes(pages=2), "application/pdf")],
        )
        assert job["status"] == "completed", job
        output = job["output_files"][0]
        assert output["original_name"] == "Thesis.docx"
        assert "wordprocessingml" in output["media_type"]

        content = await download(output["download_url"])
        # A DOCX is a ZIP containing word/document.xml with the extracted text.
        archive = zipfile.ZipFile(io.BytesIO(content))
        document = archive.read("word/document.xml").decode("utf-8")
        assert "Body text 1" in document
