"""E2E tests for the Organize tools: merge, split, rotate, delete, extract,
reorder. Real PDFs end to end."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from tests.fixtures.factories import make_pdf_bytes

pytestmark = pytest.mark.usefixtures("database")


def _reader(content: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(content))


class TestMerge:
    async def test_merges_in_upload_order(self, run_tool, download):
        job = await run_tool(
            "merge",
            [
                ("First.pdf", make_pdf_bytes(pages=2, text="First"), "application/pdf"),
                (
                    "Second.pdf",
                    make_pdf_bytes(pages=3, text="Second"),
                    "application/pdf",
                ),
            ],
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "merged.pdf"
        reader = _reader(await download(job["output_files"][0]["download_url"]))
        assert len(reader.pages) == 5
        assert "First 1" in reader.pages[0].extract_text()
        assert "Second 1" in reader.pages[2].extract_text()

    async def test_requires_two_files(self, run_tool):
        result = await run_tool(
            "merge", [("One.pdf", make_pdf_bytes(pages=1), "application/pdf")]
        )
        assert result["__response__"].status_code == 422


class TestSplit:
    async def test_split_by_ranges(self, run_tool, download):
        job = await run_tool(
            "split",
            [("Doc.pdf", make_pdf_bytes(pages=4), "application/pdf")],
            {"mode": "ranges", "ranges": ["1-2", "3-4"]},
        )
        assert job["status"] == "completed", job
        outputs = job["output_files"]
        assert len(outputs) == 2
        assert outputs[0]["original_name"] == "Doc-pages-1-2.pdf"
        reader = _reader(await download(outputs[0]["download_url"]))
        assert len(reader.pages) == 2

    async def test_split_every_page(self, run_tool):
        job = await run_tool(
            "split",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"mode": "every_page"},
        )
        assert job["status"] == "completed", job
        assert len(job["output_files"]) == 3

    async def test_ranges_required_in_ranges_mode(self, run_tool):
        result = await run_tool(
            "split",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"mode": "ranges"},
        )
        assert result["__response__"].status_code == 422

    async def test_out_of_range_fails_job(self, run_tool):
        job = await run_tool(
            "split",
            [("Doc.pdf", make_pdf_bytes(pages=2), "application/pdf")],
            {"mode": "ranges", "ranges": ["1-9"]},
        )
        assert job["status"] == "failed"
        assert "out of range" in job["error"]["message"]


class TestRotate:
    async def test_rotates_selected_pages(self, run_tool, download):
        job = await run_tool(
            "rotate",
            [("Doc.pdf", make_pdf_bytes(pages=2), "application/pdf")],
            {"angle": 180, "pages": "1"},
        )
        assert job["status"] == "completed", job
        reader = _reader(await download(job["output_files"][0]["download_url"]))
        assert reader.pages[0].rotation == 180
        assert reader.pages[1].rotation == 0

    async def test_invalid_angle_rejected(self, run_tool):
        result = await run_tool(
            "rotate",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"angle": 45},
        )
        assert result["__response__"].status_code == 422


class TestDeleteExtractReorder:
    async def test_delete_pages(self, run_tool, download):
        job = await run_tool(
            "delete-pages",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"pages": "2"},
        )
        assert job["status"] == "completed", job
        reader = _reader(await download(job["output_files"][0]["download_url"]))
        assert len(reader.pages) == 2

    async def test_extract_pages(self, run_tool, download):
        job = await run_tool(
            "extract-pages",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"pages": "3,1"},
        )
        assert job["status"] == "completed", job
        reader = _reader(await download(job["output_files"][0]["download_url"]))
        assert "Body text 3" in reader.pages[0].extract_text()

    async def test_reorder(self, run_tool, download):
        job = await run_tool(
            "reorder",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"order": [3, 2, 1]},
        )
        assert job["status"] == "completed", job
        reader = _reader(await download(job["output_files"][0]["download_url"]))
        assert "Body text 3" in reader.pages[0].extract_text()

    async def test_bad_permutation_fails_job(self, run_tool):
        job = await run_tool(
            "reorder",
            [("Doc.pdf", make_pdf_bytes(pages=3), "application/pdf")],
            {"order": [1, 2]},
        )
        assert job["status"] == "failed"
        assert "permutation" in job["error"]["message"]
