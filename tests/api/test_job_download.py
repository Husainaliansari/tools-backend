"""E2E tests for the job-level download endpoint (single file vs ZIP)."""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from httpx import AsyncClient

from tests.fixtures.factories import make_pdf_bytes

PDF_BYTES = make_pdf_bytes(pages=3)
PPTX_BYTES = b"PK\x03\x04" + b"\x00" * 64

pytestmark = pytest.mark.usefixtures("database")


async def _run_job(client: AsyncClient, tool: str, file_ids: list[str]) -> dict:
    response = await client.post(f"/api/v1/tools/{tool}", json={"file_ids": file_ids})
    assert response.status_code == 202, response.text
    job_id = response.json()["data"]["id"]
    return (await client.get(f"/api/v1/jobs/{job_id}")).json()["data"]


async def _upload(client: AsyncClient, name: str, content: bytes, ctype: str) -> str:
    response = await client.post(
        "/api/v1/files", files=[("files", (name, content, ctype))]
    )
    return response.json()["data"]["files"][0]["id"]


class TestJobDownload:
    async def test_multi_output_job_downloads_as_zip(self, client: AsyncClient):
        file_id = await _upload(client, "Deck.pdf", PDF_BYTES, "application/pdf")
        job = await _run_job(client, "pdf-to-jpg", [file_id])
        assert job["status"] == "completed"
        assert len(job["output_files"]) == 3

        response = await client.get(f"/api/v1/jobs/{job['id']}/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert ".zip" in response.headers["content-disposition"]

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert sorted(archive.namelist()) == [
            "Deck-page-01.jpg",
            "Deck-page-02.jpg",
            "Deck-page-03.jpg",
        ]
        assert archive.read("Deck-page-01.jpg").startswith(b"\xff\xd8\xff")

    async def test_single_output_job_downloads_directly(self, client: AsyncClient):
        file_id = await _upload(
            client, "Deck.pptx", PPTX_BYTES, "application/octet-stream"
        )
        job = await _run_job(client, "ppt-to-pdf", [file_id])
        assert job["status"] == "completed"

        response = await client.get(f"/api/v1/jobs/{job['id']}/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        assert "Deck.pdf" in response.headers["content-disposition"]

    async def test_unfinished_job_returns_conflict(self, client: AsyncClient):
        file_id = await _upload(
            client, "fail.pptx", PPTX_BYTES + b"FAILMODE", "application/octet-stream"
        )
        job = await _run_job(client, "ppt-to-pdf", [file_id])
        assert job["status"] == "failed"

        response = await client.get(f"/api/v1/jobs/{job['id']}/download")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "JOB_NOT_COMPLETED"

    async def test_unknown_job_returns_not_found(self, client: AsyncClient):
        response = await client.get(f"/api/v1/jobs/{uuid.uuid4()}/download")
        assert response.status_code == 404

    async def test_zip_temp_file_is_cleaned_up(self, client: AsyncClient):
        from app.config import get_settings

        file_id = await _upload(client, "Doc.pdf", PDF_BYTES, "application/pdf")
        job = await _run_job(client, "pdf-to-jpg", [file_id])
        response = await client.get(f"/api/v1/jobs/{job['id']}/download")
        assert response.status_code == 200

        leftovers = list(get_settings().TEMP_DIR.glob("job-*.zip"))
        assert not leftovers, leftovers
