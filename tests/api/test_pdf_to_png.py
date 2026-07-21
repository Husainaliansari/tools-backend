"""E2E tests for the PDF to PNG tool (stub pdftoppm) + grayscale option."""

from __future__ import annotations

import pytest

from tests.fixtures.factories import make_pdf_bytes

PDF_BYTES = make_pdf_bytes(pages=3)

pytestmark = pytest.mark.usefixtures("database")


class TestPdfToPng:
    async def test_renders_pages_as_png(self, run_tool, download):
        job = await run_tool(
            "pdf-to-png", [("Diagram.pdf", PDF_BYTES, "application/pdf")]
        )
        assert job["status"] == "completed", job
        outputs = job["output_files"]
        assert [o["original_name"] for o in outputs] == [
            "Diagram-page-01.png",
            "Diagram-page-02.png",
            "Diagram-page-03.png",
        ]
        assert all(o["media_type"] == "image/png" for o in outputs)
        content = await download(outputs[0]["download_url"])
        assert content.startswith(b"\x89PNG")

    async def test_grayscale_option_reaches_renderer(self, run_tool, download):
        job = await run_tool(
            "pdf-to-png",
            [("Doc.pdf", PDF_BYTES, "application/pdf")],
            {"grayscale": True, "first_page": 1, "last_page": 1},
        )
        assert job["status"] == "completed", job
        content = await download(job["output_files"][0]["download_url"])
        assert b"gray" in content

    async def test_rejects_non_pdf(self, run_tool):
        result = await run_tool(
            "pdf-to-png",
            [("x.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 16, "image/jpeg")],
        )
        assert result["__response__"].status_code == 415
