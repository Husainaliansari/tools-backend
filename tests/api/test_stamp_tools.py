"""E2E tests for the overlay tools: watermark, header & footer, page numbers.

Real PDFs in, real PDFs out — assertions read the stamped text back with
pypdf's text extraction.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from tests.fixtures.factories import make_pdf_bytes

pytestmark = pytest.mark.usefixtures("database")


def _page_texts(content: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(content)).pages]


class TestWatermark:
    async def test_stamps_every_page(self, run_tool, download):
        job = await run_tool(
            "watermark",
            [("Contract.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"text": "CONFIDENTIAL"},
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Contract-watermarked.pdf"

        texts = _page_texts(await download(job["output_files"][0]["download_url"]))
        assert all("CONFIDENTIAL" in text for text in texts)
        assert "Body text 1" in texts[0]  # original content preserved

    async def test_page_range_limits_stamping(self, run_tool, download):
        job = await run_tool(
            "watermark",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"text": "DRAFT", "page_range": "2"},
        )
        texts = _page_texts(await download(job["output_files"][0]["download_url"]))
        assert "DRAFT" not in texts[0]
        assert "DRAFT" in texts[1]
        assert "DRAFT" not in texts[2]

    async def test_tiled_watermark_repeats(self, run_tool, download):
        job = await run_tool(
            "watermark",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"text": "SAMPLE", "tile": True},
        )
        texts = _page_texts(await download(job["output_files"][0]["download_url"]))
        assert texts[0].count("SAMPLE") > 3

    async def test_missing_text_rejected(self, run_tool):
        result = await run_tool(
            "watermark",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {},
        )
        assert result["__response__"].status_code == 422

    async def test_invalid_color_rejected(self, run_tool):
        result = await run_tool(
            "watermark",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"text": "X", "color": "red"},
        )
        assert result["__response__"].status_code == 422


class TestHeaderFooter:
    async def test_header_and_footer_with_placeholders(self, run_tool, download):
        job = await run_tool(
            "header-footer",
            [("Report.pdf", make_pdf_bytes(pages=2), "application/pdf")],
            {
                "header_text": "ACME Corp",
                "footer_text": "Page {page} of {total}",
            },
        )
        assert job["status"] == "completed", job
        texts = _page_texts(await download(job["output_files"][0]["download_url"]))
        assert "ACME Corp" in texts[0]
        assert "Page 1 of 2" in texts[0]
        assert "Page 2 of 2" in texts[1]

    async def test_requires_header_or_footer(self, run_tool):
        result = await run_tool(
            "header-footer",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {},
        )
        assert result["__response__"].status_code == 422


class TestPageNumbers:
    async def test_default_numbering(self, run_tool, download):
        job = await run_tool(
            "page-numbers",
            [("Thesis.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"format": "Page {page} of {total}"},
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Thesis-numbered.pdf"
        texts = _page_texts(await download(job["output_files"][0]["download_url"]))
        assert "Page 1 of 3" in texts[0]
        assert "Page 3 of 3" in texts[2]

    async def test_start_at_and_skip_first(self, run_tool, download):
        job = await run_tool(
            "page-numbers",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"format": "{page}", "start_at": 10, "skip_first": True},
        )
        texts = _page_texts(await download(job["output_files"][0]["download_url"]))
        assert "11" in texts[1]
        assert "12" in texts[2]
        assert "10" not in texts[0]  # cover page left unnumbered

    async def test_format_must_contain_page(self, run_tool):
        result = await run_tool(
            "page-numbers",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"format": "no placeholder"},
        )
        assert result["__response__"].status_code == 422
