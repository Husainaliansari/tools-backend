"""Tests for the WebSocket job-progress endpoint."""

from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from tests.fixtures.factories import make_pdf_bytes

pytestmark = pytest.mark.usefixtures("database")


def _run_extract_job(client: TestClient) -> str:
    upload = client.post(
        "/api/v1/files",
        files=[("files", ("Doc.pdf", make_pdf_bytes(pages=2), "application/pdf"))],
    )
    file_id = upload.json()["data"]["files"][0]["id"]
    response = client.post(
        "/api/v1/tools/extract-pages",
        json={"file_ids": [file_id], "options": {"pages": "1"}},
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["id"]


class TestJobWebSocket:
    def test_terminal_job_pushes_final_state_and_closes(self, app):
        with TestClient(app) as client:
            job_id = _run_extract_job(client)
            with client.websocket_connect(f"/api/v1/jobs/{job_id}/ws") as ws:
                message = ws.receive_json()
                assert message["status"] == "completed"
                assert message["progress"] == 100

    def test_unknown_job_reports_error(self, app):
        with (
            TestClient(app) as client,
            client.websocket_connect(f"/api/v1/jobs/{uuid.uuid4()}/ws") as ws,
        ):
            message = ws.receive_json()
            assert message["error"] == "JOB_NOT_FOUND"
