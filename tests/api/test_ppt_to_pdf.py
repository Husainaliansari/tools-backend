"""E2E tests for the PPT to PDF tool.

Runs the real pipeline — upload endpoint, tool endpoint, eager Celery worker,
subprocess invocation (stub soffice from conftest), output registration,
status API, download — against the isolated test database.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

PPTX_BYTES = b"PK\x03\x04" + b"\x00" * 64  # OOXML container signature
PPT_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64  # OLE2 signature
PDF_BYTES = b"%PDF-1.4 test\n%%EOF"

pytestmark = pytest.mark.usefixtures("database")


async def _upload(client: AsyncClient, *files: tuple[str, bytes, str]) -> list[str]:
    response = await client.post(
        "/api/v1/files",
        files=[("files", item) for item in files],
    )
    assert response.status_code == 201, response.text
    return [f["id"] for f in response.json()["data"]["files"]]


class TestPptToPdf:
    async def test_converts_multiple_presentations(self, client: AsyncClient):
        file_ids = await _upload(
            client,
            ("Quarterly Review.pptx", PPTX_BYTES, "application/octet-stream"),
            ("legacy deck.ppt", PPT_BYTES, "application/octet-stream"),
        )

        response = await client.post(
            "/api/v1/tools/ppt-to-pdf", json={"file_ids": file_ids}
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["data"]["id"]

        status = await client.get(f"/api/v1/jobs/{job_id}")
        job = status.json()["data"]
        assert job["status"] == "completed", job
        assert job["progress"] == 100

        outputs = job["output_files"]
        assert [o["original_name"] for o in outputs] == [
            "Quarterly Review.pdf",
            "legacy deck.pdf",
        ]
        assert all(o["media_type"] == "application/pdf" for o in outputs)

        download = await client.get(outputs[0]["download_url"])
        assert download.status_code == 200
        assert download.content.startswith(b"%PDF")

    async def test_accepts_pdf_a_and_slide_range_options(self, client: AsyncClient):
        file_ids = await _upload(
            client, ("Deck.pptx", PPTX_BYTES, "application/octet-stream")
        )
        response = await client.post(
            "/api/v1/tools/ppt-to-pdf",
            json={
                "file_ids": file_ids,
                "options": {"pdf_a": True, "slide_range": "1-2,5"},
            },
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["data"]["id"]
        job = (await client.get(f"/api/v1/jobs/{job_id}")).json()["data"]
        assert job["status"] == "completed", job

    async def test_rejects_malformed_slide_range(self, client: AsyncClient):
        file_ids = await _upload(
            client, ("Deck.pptx", PPTX_BYTES, "application/octet-stream")
        )
        response = await client.post(
            "/api/v1/tools/ppt-to-pdf",
            json={"file_ids": file_ids, "options": {"slide_range": "three-five"}},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_rejects_non_presentation_input(self, client: AsyncClient):
        file_ids = await _upload(client, ("doc.pdf", PDF_BYTES, "application/pdf"))
        response = await client.post(
            "/api/v1/tools/ppt-to-pdf", json={"file_ids": file_ids}
        )
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    async def test_rejects_unknown_file_id(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/tools/ppt-to-pdf",
            json={"file_ids": ["00000000-0000-0000-0000-000000000000"]},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "FILE_NOT_FOUND"

    async def test_rejects_too_many_inputs(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/tools/ppt-to-pdf",
            json={
                "file_ids": [
                    f"00000000-0000-0000-0000-0000000000{i:02d}" for i in range(11)
                ]
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_silent_converter_failure_fails_job(self, client: AsyncClient):
        # The FAILMODE marker makes the stub exit 0 without producing output.
        file_ids = await _upload(
            client,
            ("fail.pptx", PPTX_BYTES + b"FAILMODE", "application/octet-stream"),
        )
        response = await client.post(
            "/api/v1/tools/ppt-to-pdf", json={"file_ids": file_ids}
        )
        job_id = response.json()["data"]["id"]

        status = await client.get(f"/api/v1/jobs/{job_id}")
        job = status.json()["data"]
        assert job["status"] == "failed"
        assert job["error"]["code"] == "PROCESSING_FAILED"
        assert "no output" in job["error"]["message"]

    async def test_converter_crash_fails_job(self, client: AsyncClient):
        # The CRASHMODE marker makes the stub exit 77.
        file_ids = await _upload(
            client,
            ("crash.pptx", PPTX_BYTES + b"CRASHMODE", "application/octet-stream"),
        )
        response = await client.post(
            "/api/v1/tools/ppt-to-pdf", json={"file_ids": file_ids}
        )
        job_id = response.json()["data"]["id"]

        status = await client.get(f"/api/v1/jobs/{job_id}")
        job = status.json()["data"]
        assert job["status"] == "failed"
        assert job["error"]["code"] == "PROCESSING_FAILED"
