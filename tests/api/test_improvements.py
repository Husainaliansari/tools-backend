"""E2E tests for the cross-cutting improvements: unlock tool, image
watermarks, targeted text watermark removal, SSE progress, thumbnails."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter

from tests.fixtures.factories import make_image_bytes, make_pdf_bytes

pytestmark = pytest.mark.usefixtures("database")


def _encrypted_pdf(password: str) -> bytes:
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=2)))
    writer.encrypt(user_password=password, algorithm="AES-256")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestUnlock:
    async def test_unlocks_with_correct_password(self, run_tool, download):
        job = await run_tool(
            "unlock",
            [("locked.pdf", _encrypted_pdf("open-sesame"), "application/pdf")],
            {"password": "open-sesame"},
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "locked-unlocked.pdf"
        content = await download(job["output_files"][0]["download_url"])
        reader = PdfReader(io.BytesIO(content))
        assert not reader.is_encrypted
        assert "Body text 1" in reader.pages[0].extract_text()

    async def test_wrong_password_fails_job(self, run_tool):
        job = await run_tool(
            "unlock",
            [("locked.pdf", _encrypted_pdf("right"), "application/pdf")],
            {"password": "wrong"},
        )
        assert job["status"] == "failed"
        assert "Incorrect password" in job["error"]["message"]


class TestImageWatermark:
    async def test_stamps_image_watermark(self, run_tool, download):
        job = await run_tool(
            "watermark",
            [
                ("Doc.pdf", make_pdf_bytes(pages=2), "application/pdf"),
                ("logo.png", make_image_bytes("PNG"), "image/png"),
            ],
            {"mode": "image", "opacity": 0.3, "scale": 0.4},
        )
        assert job["status"] == "completed", job
        # Only the PDF is stamped; the logo is consumed, not output.
        assert [o["original_name"] for o in job["output_files"]] == [
            "Doc-watermarked.pdf"
        ]
        content = await download(job["output_files"][0]["download_url"])
        page = PdfReader(io.BytesIO(content)).pages[0]
        xobjects = page["/Resources"].get("/XObject", {})
        assert xobjects, "expected an image XObject on the stamped page"

    async def test_image_mode_without_image_fails(self, run_tool):
        job = await run_tool(
            "watermark",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"mode": "image"},
        )
        assert job["status"] == "failed"
        assert "requires a JPG or PNG" in job["error"]["message"]


class TestTargetedTextRemoval:
    async def test_watermark_then_remove_roundtrip(self, run_tool, download):
        # Stamp with our own watermark tool...
        stamped = await run_tool(
            "watermark",
            [("Doc.pdf", make_pdf_bytes(pages=2), "application/pdf")],
            {"text": "TOPSECRET", "opacity": 0.5},
        )
        assert stamped["status"] == "completed"
        stamped_bytes = await download(stamped["output_files"][0]["download_url"])
        texts = [p.extract_text() for p in PdfReader(io.BytesIO(stamped_bytes)).pages]
        assert all("TOPSECRET" in t for t in texts)

        # ...then remove it via targeted content-stream removal.
        cleaned = await run_tool(
            "remove-watermark",
            [("stamped.pdf", stamped_bytes, "application/pdf")],
            {"text": "TOPSECRET"},
        )
        assert cleaned["status"] == "completed", cleaned
        cleaned_bytes = await download(cleaned["output_files"][0]["download_url"])
        cleaned_reader = PdfReader(io.BytesIO(cleaned_bytes))
        for page in cleaned_reader.pages:
            text = page.extract_text()
            assert "TOPSECRET" not in text
            assert "Body text" in text  # original content untouched


class TestJobEventsSse:
    async def test_terminal_job_emits_final_event(self, client, run_tool):
        job = await run_tool(
            "extract-pages",
            [("Doc.pdf", make_pdf_bytes(pages=2), "application/pdf")],
            {"pages": "1"},
        )
        response = await client.get(f"/api/v1/jobs/{job['id']}/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"status": "completed"' in response.text
        assert '"progress": 100' in response.text

    async def test_unknown_job_emits_error_event(self, client):
        response = await client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/events"
        )
        assert "JOB_NOT_FOUND" in response.text


class TestThumbnails:
    async def test_image_thumbnail(self, client):
        upload = await client.post(
            "/api/v1/files",
            files=[
                (
                    "files",
                    (
                        "photo.png",
                        make_image_bytes("PNG", size=(900, 600)),
                        "image/png",
                    ),
                )
            ],
        )
        file_id = upload.json()["data"]["files"][0]["id"]

        response = await client.get(f"/api/v1/files/{file_id}/thumbnail")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content.startswith(b"\xff\xd8\xff")

        # Second request hits the cache (same bytes back).
        again = await client.get(f"/api/v1/files/{file_id}/thumbnail")
        assert again.content == response.content

    async def test_pdf_thumbnail(self, client):
        upload = await client.post(
            "/api/v1/files",
            files=[("files", ("doc.pdf", make_pdf_bytes(pages=1), "application/pdf"))],
        )
        file_id = upload.json()["data"]["files"][0]["id"]

        response = await client.get(f"/api/v1/files/{file_id}/thumbnail")
        assert response.status_code == 200
        assert response.content.startswith(b"\xff\xd8\xff")
