"""Shared helpers for tool E2E tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.fixture()
def run_tool(client: AsyncClient):
    """Upload files, run a tool, poll the job once (eager mode = final)."""

    async def _run(
        tool: str,
        files: list[tuple[str, bytes, str]],
        options: dict | None = None,
    ) -> dict:
        response = await client.post(
            "/api/v1/files", files=[("files", item) for item in files]
        )
        assert response.status_code == 201, response.text
        file_ids = [f["id"] for f in response.json()["data"]["files"]]

        response = await client.post(
            f"/api/v1/tools/{tool}",
            json={"file_ids": file_ids, "options": options or {}},
        )
        if response.status_code != 202:
            return {"__response__": response}
        job_id = response.json()["data"]["id"]
        return (await client.get(f"/api/v1/jobs/{job_id}")).json()["data"]

    return _run


@pytest.fixture()
def download(client: AsyncClient):
    async def _download(url: str) -> bytes:
        response = await client.get(url)
        assert response.status_code == 200, response.status_code
        return response.content

    return _download
