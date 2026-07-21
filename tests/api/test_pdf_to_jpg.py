"""E2E tests for the PDF to JPG tool (stub pdftoppm renders 3 pages)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.fixtures.factories import make_pdf_bytes

PDF_BYTES = make_pdf_bytes(pages=3)

pytestmark = pytest.mark.usefixtures("database")


async def _upload_pdf(client: AsyncClient, name: str = "Report.pdf") -> str:
    response = await client.post(
        "/api/v1/files", files=[("files", (name, PDF_BYTES, "application/pdf"))]
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["files"][0]["id"]


class TestPdfToJpg:
    async def test_renders_every_page(self, client: AsyncClient):
        file_id = await _upload_pdf(client)
        response = await client.post(
            "/api/v1/tools/pdf-to-jpg", json={"file_ids": [file_id]}
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["data"]["id"]

        job = (await client.get(f"/api/v1/jobs/{job_id}")).json()["data"]
        assert job["status"] == "completed", job

        outputs = job["output_files"]
        assert [o["original_name"] for o in outputs] == [
            "Report-page-01.jpg",
            "Report-page-02.jpg",
            "Report-page-03.jpg",
        ]
        assert all(o["media_type"] == "image/jpeg" for o in outputs)

        download = await client.get(outputs[0]["download_url"])
        assert download.status_code == 200
        assert download.content.startswith(b"\xff\xd8\xff")

    async def test_options_reach_the_renderer(self, client: AsyncClient):
        file_id = await _upload_pdf(client)
        response = await client.post(
            "/api/v1/tools/pdf-to-jpg",
            json={
                "file_ids": [file_id],
                "options": {"dpi": 300, "quality": 70, "first_page": 2},
            },
        )
        job_id = response.json()["data"]["id"]
        job = (await client.get(f"/api/v1/jobs/{job_id}")).json()["data"]
        assert job["status"] == "completed", job

        outputs = job["output_files"]
        # Stub document has 3 pages; first_page=2 leaves pages 2-3.
        assert [o["original_name"] for o in outputs] == [
            "Report-page-02.jpg",
            "Report-page-03.jpg",
        ]
        content = (await client.get(outputs[0]["download_url"])).content
        assert b"dpi=300" in content
        assert b"quality=70" in content

    async def test_single_page_keeps_clean_name(self, client: AsyncClient):
        file_id = await _upload_pdf(client, "Slide.pdf")
        response = await client.post(
            "/api/v1/tools/pdf-to-jpg",
            json={"file_ids": [file_id], "options": {"first_page": 2, "last_page": 2}},
        )
        job_id = response.json()["data"]["id"]
        job = (await client.get(f"/api/v1/jobs/{job_id}")).json()["data"]
        assert [o["original_name"] for o in job["output_files"]] == ["Slide.jpg"]

    async def test_invalid_options_rejected(self, client: AsyncClient):
        file_id = await _upload_pdf(client)
        response = await client.post(
            "/api/v1/tools/pdf-to-jpg",
            json={
                "file_ids": [file_id],
                "options": {"dpi": 10_000, "first_page": 5, "last_page": 2},
            },
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        fields = {d["field"] for d in body["error"]["details"]}
        assert "dpi" in fields

    async def test_rejects_non_pdf_input(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/files",
            files=[
                ("files", ("img.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png"))
            ],
        )
        file_id = response.json()["data"]["files"][0]["id"]

        response = await client.post(
            "/api/v1/tools/pdf-to-jpg", json={"file_ids": [file_id]}
        )
        assert response.status_code == 415

    async def test_corrupted_pdf_fails_job(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/files",
            files=[("files", ("bad.pdf", PDF_BYTES + b"CRASHMODE", "application/pdf"))],
        )
        file_id = response.json()["data"]["files"][0]["id"]

        response = await client.post(
            "/api/v1/tools/pdf-to-jpg", json={"file_ids": [file_id]}
        )
        job_id = response.json()["data"]["id"]
        job = (await client.get(f"/api/v1/jobs/{job_id}")).json()["data"]
        assert job["status"] == "failed"
        assert job["error"]["code"] == "PROCESSING_FAILED"
