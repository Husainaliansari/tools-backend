"""E2E tests for Remove Watermark and Protect PDF."""

from __future__ import annotations

import io
import uuid

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from tests.fixtures.factories import make_pdf_bytes

pytestmark = pytest.mark.usefixtures("database")


def _pdf_with_watermark_annotation() -> bytes:
    """A real PDF carrying a /Watermark annotation plus a normal text one."""
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
    page = writer.pages[0]

    def annotation(subtype: str, name: str) -> DictionaryObject:
        obj = DictionaryObject()
        obj[NameObject("/Type")] = NameObject("/Annot")
        obj[NameObject("/Subtype")] = NameObject(subtype)
        obj[NameObject("/NM")] = TextStringObject(name)
        obj[NameObject("/Rect")] = ArrayObject(
            [NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(50)]
        )
        return obj

    page[NameObject("/Annots")] = ArrayObject(
        [
            writer._add_object(annotation("/Watermark", "wm-1")),
            writer._add_object(annotation("/Text", "note-1")),
        ]
    )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestRemoveWatermark:
    async def test_strips_watermark_annotations_keeps_others(self, run_tool, download):
        job = await run_tool(
            "remove-watermark",
            [("Stamped.pdf", _pdf_with_watermark_annotation(), "application/pdf")],
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Stamped-no-watermark.pdf"

        content = await download(job["output_files"][0]["download_url"])
        page = PdfReader(io.BytesIO(content)).pages[0]
        annotations = page.get("/Annots") or []
        subtypes = [str(a.get_object().get("/Subtype")) for a in annotations]
        assert "/Watermark" not in subtypes
        assert "/Text" in subtypes  # unrelated annotation preserved

    async def test_clean_pdf_passes_through(self, run_tool, download):
        job = await run_tool(
            "remove-watermark",
            [("Plain.pdf", make_pdf_bytes(pages=2), "application/pdf")],
        )
        assert job["status"] == "completed", job
        content = await download(job["output_files"][0]["download_url"])
        assert len(PdfReader(io.BytesIO(content)).pages) == 2

    async def test_flattened_watermarks_removed_automatically(
        self, run_tool, download, tmp_path
    ):
        """Text AND image watermarks vanish with no options at all."""
        from app.utils.pdf_overlay import (
            make_image_watermark_draw,
            make_watermark_draw,
            overlay_pdf,
        )
        from tests.fixtures.factories import make_image_bytes

        source = tmp_path / "plain.pdf"
        source.write_bytes(make_pdf_bytes(pages=2))
        text_stamped = tmp_path / "text-stamped.pdf"
        overlay_pdf(
            source,
            text_stamped,
            make_watermark_draw(
                "CONFIDENTIAL",
                font_size=48,
                opacity=0.3,
                rotation=45,
                color="#ff0000",
                tile=False,
            ),
        )
        image = tmp_path / "mark.jpg"
        image.write_bytes(make_image_bytes("JPEG", size=(200, 150)))
        both_stamped = tmp_path / "both-stamped.pdf"
        overlay_pdf(
            text_stamped,
            both_stamped,
            make_image_watermark_draw(image, opacity=0.4, rotation=0, scale=0.5),
        )

        job = await run_tool(
            "remove-watermark",
            [("Stamped.pdf", both_stamped.read_bytes(), "application/pdf")],
        )
        assert job["status"] == "completed", job

        content = await download(job["output_files"][0]["download_url"])
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "CONFIDENTIAL" not in text
        assert "Body text 1" in text and "Body text 2" in text
        # The watermark image XObject is gone from every page's resources.
        for page in reader.pages:
            xobjects = (page.get("/Resources") or {}).get("/XObject")
            if xobjects:
                subtypes = [
                    str(entry.get_object().get("/Subtype", ""))
                    for entry in xobjects.get_object().values()
                ]
                assert "/Image" not in subtypes

    async def test_flattened_text_watermark_removed_via_text_option(
        self, run_tool, download, tmp_path
    ):
        from app.utils.pdf_overlay import make_watermark_draw, overlay_pdf

        source = tmp_path / "plain.pdf"
        source.write_bytes(make_pdf_bytes(pages=2))
        stamped = tmp_path / "stamped.pdf"
        overlay_pdf(
            source,
            stamped,
            make_watermark_draw(
                "CONFIDENTIAL",
                font_size=48,
                opacity=0.3,
                rotation=45,
                color="#ff0000",
                tile=True,
            ),
        )

        job = await run_tool(
            "remove-watermark",
            [("Stamped.pdf", stamped.read_bytes(), "application/pdf")],
            {"text": "CONFIDENTIAL"},
        )
        assert job["status"] == "completed", job

        content = await download(job["output_files"][0]["download_url"])
        text = "\n".join(
            page.extract_text() for page in PdfReader(io.BytesIO(content)).pages
        )
        assert "CONFIDENTIAL" not in text
        assert "Body text 1" in text and "Body text 2" in text

    async def test_text_not_found_fails_with_guidance(self, run_tool):
        job = await run_tool(
            "remove-watermark",
            [("Plain.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"text": "NOT-IN-THE-FILE"},
        )
        assert job["status"] == "failed"
        assert "NOT-IN-THE-FILE" in job["error"]["message"]
        assert "was found" in job["error"]["message"]

    async def test_password_protected_input_fails_cleanly(self, run_tool):
        encrypted = io.BytesIO()
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        writer.encrypt(user_password="secret", algorithm="AES-256")
        writer.write(encrypted)

        job = await run_tool(
            "remove-watermark",
            [("Locked.pdf", encrypted.getvalue(), "application/pdf")],
        )
        assert job["status"] == "failed"
        assert "password-protected" in job["error"]["message"]


class TestProtect:
    async def test_encrypts_with_aes256(self, run_tool, download):
        job = await run_tool(
            "protect",
            [("Secret.pdf", make_pdf_bytes(pages=2), "application/pdf")],
            {"user_password": "hunter22", "allow_printing": False},
        )
        assert job["status"] == "completed", job
        assert job["output_files"][0]["original_name"] == "Secret-protected.pdf"

        content = await download(job["output_files"][0]["download_url"])
        reader = PdfReader(io.BytesIO(content))
        assert reader.is_encrypted
        assert reader.decrypt("wrong-password") == 0
        assert reader.decrypt("hunter22") != 0
        assert "Body text 1" in reader.pages[0].extract_text()

    async def test_password_redacted_from_job_row(self, run_tool):
        job = await run_tool(
            "protect",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"user_password": "super-secret-pw"},
        )
        assert job["status"] == "completed", job

        from app.db.sync_session import sync_session
        from app.repositories.job import SyncJobRepository

        with sync_session() as session:
            row = SyncJobRepository(session).get(uuid.UUID(job["id"]))
            assert row is not None
            assert row.options["user_password"] == "[redacted]"
            assert "super-secret-pw" not in str(row.options)

    async def test_short_password_rejected(self, run_tool):
        result = await run_tool(
            "protect",
            [("Doc.pdf", make_pdf_bytes(pages=1), "application/pdf")],
            {"user_password": "abc"},
        )
        assert result["__response__"].status_code == 422

    async def test_encrypted_input_fails_cleanly(self, run_tool):
        # Protecting an already-protected PDF should fail the job, not crash.
        encrypted = io.BytesIO()
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        writer.encrypt(user_password="already", algorithm="AES-256")
        writer.write(encrypted)

        job = await run_tool(
            "protect",
            [("locked.pdf", encrypted.getvalue(), "application/pdf")],
            {"user_password": "newpass1"},
        )
        assert job["status"] == "failed"
        assert job["error"]["code"] == "PROCESSING_FAILED"
