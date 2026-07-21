"""E2E tests for the ad-hoc file archive download (GET /files/archive).

The frontend's "Download all" uses this when a batch run produced results
across several independent per-file jobs, so no single job owns them all.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from tests.fixtures.factories import make_pdf_bytes

PDF_BYTES = make_pdf_bytes(pages=1)

pytestmark = pytest.mark.usefixtures("database")


async def _upload(client: AsyncClient, name: str) -> str:
    response = await client.post(
        "/api/v1/files", files=[("files", (name, PDF_BYTES, "application/pdf"))]
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["files"][0]["id"]


class TestFileArchive:
    async def test_multiple_ids_download_as_zip(self, client: AsyncClient):
        first = await _upload(client, "report.pdf")
        second = await _upload(client, "invoice.pdf")

        response = await client.get(f"/api/v1/files/archive?ids={first},{second}")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert (
            f"converted-2-files-{today}.zip" in response.headers["content-disposition"]
        )

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert sorted(archive.namelist()) == ["invoice.pdf", "report.pdf"]
        assert archive.read("report.pdf") == PDF_BYTES

    async def test_zip_named_after_tool_count_and_date(self, client: AsyncClient):
        first = await _upload(client, "deck1.pdf")
        second = await _upload(client, "deck2.pdf")

        response = await client.get(
            f"/api/v1/files/archive?ids={first},{second}&tool=ppt-to-pdf"
        )
        assert response.status_code == 200, response.text
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert (
            f"ppt-to-pdf-2-files-{today}.zip"
            in response.headers["content-disposition"]
        )

    async def test_unknown_tool_falls_back_to_generic_name(self, client: AsyncClient):
        """The tool param lands in a response header — junk must not."""
        first = await _upload(client, "a.pdf")
        second = await _upload(client, "b.pdf")

        response = await client.get(
            f"/api/v1/files/archive?ids={first},{second}&tool=..%2Fetc%2Fpasswd"
        )
        assert response.status_code == 200, response.text
        disposition = response.headers["content-disposition"]
        assert "passwd" not in disposition
        assert "converted-2-files-" in disposition

    async def test_duplicate_names_are_deduped(self, client: AsyncClient):
        first = await _upload(client, "scan.pdf")
        second = await _upload(client, "scan.pdf")

        response = await client.get(f"/api/v1/files/archive?ids={first},{second}")
        assert response.status_code == 200
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert sorted(archive.namelist()) == ["scan (1).pdf", "scan.pdf"]

    async def test_single_id_downloads_directly(self, client: AsyncClient):
        file_id = await _upload(client, "only.pdf")

        response = await client.get(f"/api/v1/files/archive?ids={file_id}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == PDF_BYTES

    async def test_malformed_id_rejected(self, client: AsyncClient):
        response = await client.get("/api/v1/files/archive?ids=not-a-uuid")
        assert response.status_code == 422

    async def test_unknown_id_is_not_found(self, client: AsyncClient):
        file_id = await _upload(client, "real.pdf")
        missing = uuid.uuid4()

        response = await client.get(f"/api/v1/files/archive?ids={file_id},{missing}")
        assert response.status_code == 404
