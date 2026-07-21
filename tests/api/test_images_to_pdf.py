"""E2E tests for JPG→PDF and PNG→PDF (real images, real PDF output)."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from tests.fixtures.factories import make_image_bytes

pytestmark = pytest.mark.usefixtures("database")


class TestJpgToPdf:
    async def test_combines_multiple_jpgs_into_one_pdf(self, run_tool, download):
        job = await run_tool(
            "jpg-to-pdf",
            [
                ("photo1.jpg", make_image_bytes("JPEG"), "image/jpeg"),
                ("photo2.jpg", make_image_bytes("JPEG", size=(300, 200)), "image/jpeg"),
            ],
        )
        assert job["status"] == "completed", job
        outputs = job["output_files"]
        assert [o["original_name"] for o in outputs] == ["images.pdf"]

        content = await download(outputs[0]["download_url"])
        reader = PdfReader(io.BytesIO(content))
        assert len(reader.pages) == 2

    async def test_single_image_keeps_its_name(self, run_tool):
        job = await run_tool(
            "jpg-to-pdf",
            [("Holiday Snap.jpeg", make_image_bytes("JPEG"), "image/jpeg")],
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Holiday Snap.pdf"

    async def test_fixed_page_size_produces_a4_pages(self, run_tool, download):
        job = await run_tool(
            "jpg-to-pdf",
            [("photo.jpg", make_image_bytes("JPEG"), "image/jpeg")],
            {"page_size": "a4", "margin_mm": 10},
        )
        assert job["status"] == "completed", job
        content = await download(job["output_files"][0]["download_url"])
        page = PdfReader(io.BytesIO(content)).pages[0]
        # A4 = 595.3 x 841.9 pt
        assert round(float(page.mediabox.width)) in (595, 596)
        assert round(float(page.mediabox.height)) in (841, 842)

    async def test_rejects_png_input(self, run_tool):
        result = await run_tool(
            "jpg-to-pdf", [("img.png", make_image_bytes("PNG"), "image/png")]
        )
        assert result["__response__"].status_code == 415


class TestPngToPdf:
    async def test_flattens_alpha_channel(self, run_tool, download):
        job = await run_tool(
            "png-to-pdf",
            [("logo.png", make_image_bytes("PNG", alpha=True), "image/png")],
        )
        assert job["status"] == "completed", job
        content = await download(job["output_files"][0]["download_url"])
        assert len(PdfReader(io.BytesIO(content)).pages) == 1

    async def test_landscape_orientation(self, run_tool, download):
        job = await run_tool(
            "png-to-pdf",
            [("chart.png", make_image_bytes("PNG"), "image/png")],
            {"page_size": "letter", "orientation": "landscape"},
        )
        assert job["status"] == "completed", job
        content = await download(job["output_files"][0]["download_url"])
        page = PdfReader(io.BytesIO(content)).pages[0]
        assert float(page.mediabox.width) > float(page.mediabox.height)
