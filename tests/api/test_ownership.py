"""E2E tests for per-user file/job ownership."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.fixtures.factories import make_pdf_bytes

pytestmark = pytest.mark.usefixtures("database")


async def _account(client: AsyncClient) -> dict[str, str]:
    email = f"owner-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/auth/register",
        json={"name": "Owner", "email": email, "password": "s3cret-pw"},
    )
    token = response.json()["data"]["tokens"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _upload_pdf(client: AsyncClient, headers: dict | None = None) -> str:
    response = await client.post(
        "/api/v1/files",
        files=[("files", ("Doc.pdf", make_pdf_bytes(pages=2), "application/pdf"))],
        headers=headers or {},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["files"][0]["id"]


class TestFileOwnership:
    async def test_owned_file_hidden_from_anonymous_and_others(
        self, client: AsyncClient
    ):
        owner = await _account(client)
        stranger = await _account(client)
        file_id = await _upload_pdf(client, owner)

        assert (
            await client.get(f"/api/v1/files/{file_id}", headers=owner)
        ).status_code == 200
        assert (await client.get(f"/api/v1/files/{file_id}")).status_code == 404
        assert (
            await client.get(f"/api/v1/files/{file_id}", headers=stranger)
        ).status_code == 404

    async def test_anonymous_file_hidden_from_authenticated_user(
        self, client: AsyncClient
    ):
        owner = await _account(client)
        file_id = await _upload_pdf(client)  # anonymous upload
        assert (await client.get(f"/api/v1/files/{file_id}")).status_code == 200
        assert (
            await client.get(f"/api/v1/files/{file_id}", headers=owner)
        ).status_code == 404

    async def test_list_returns_only_own_files(self, client: AsyncClient):
        owner = await _account(client)
        other = await _account(client)
        mine = await _upload_pdf(client, owner)
        await _upload_pdf(client, other)

        response = await client.get("/api/v1/files", headers=owner)
        ids = [f["id"] for f in response.json()["data"]]
        assert ids == [mine]

    async def test_list_requires_auth(self, client: AsyncClient):
        assert (await client.get("/api/v1/files")).status_code == 401


class TestJobOwnership:
    async def test_job_and_outputs_belong_to_owner(self, client: AsyncClient):
        owner = await _account(client)
        stranger = await _account(client)
        file_id = await _upload_pdf(client, owner)

        response = await client.post(
            "/api/v1/tools/extract-pages",
            json={"file_ids": [file_id], "options": {"pages": "1"}},
            headers=owner,
        )
        assert response.status_code == 202, response.text
        job_id = response.json()["data"]["id"]

        job = (await client.get(f"/api/v1/jobs/{job_id}", headers=owner)).json()["data"]
        assert job["status"] == "completed"

        # Status and downloads are invisible to strangers/anonymous.
        assert (await client.get(f"/api/v1/jobs/{job_id}")).status_code == 404
        assert (
            await client.get(f"/api/v1/jobs/{job_id}", headers=stranger)
        ).status_code == 404

        output_url = job["output_files"][0]["download_url"]
        assert (
            await client.get(output_url, headers=owner)
        ).status_code == 200  # outputs inherit ownership
        assert (await client.get(output_url)).status_code == 404
        assert (
            await client.get(f"/api/v1/jobs/{job_id}/download", headers=stranger)
        ).status_code == 404

    async def test_cannot_use_someone_elses_file_as_input(self, client: AsyncClient):
        owner = await _account(client)
        thief = await _account(client)
        file_id = await _upload_pdf(client, owner)

        response = await client.post(
            "/api/v1/tools/extract-pages",
            json={"file_ids": [file_id], "options": {"pages": "1"}},
            headers=thief,
        )
        assert response.status_code == 404

    async def test_job_list_returns_only_own(self, client: AsyncClient):
        owner = await _account(client)
        file_id = await _upload_pdf(client, owner)
        await client.post(
            "/api/v1/tools/extract-pages",
            json={"file_ids": [file_id], "options": {"pages": "1"}},
            headers=owner,
        )
        response = await client.get("/api/v1/jobs", headers=owner)
        assert response.status_code == 200
        jobs = response.json()["data"]
        assert len(jobs) == 1
        assert jobs[0]["tool"] == "extract-pages"
