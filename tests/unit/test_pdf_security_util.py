"""Unit tests for pdf_security utilities (OCG layers, modes, content removal)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from app.exceptions.jobs import ProcessingError
from app.utils.pdf_overlay import (
    make_header_footer_draw,
    make_image_watermark_draw,
    make_watermark_draw,
    overlay_pdf,
)
from app.utils.pdf_security import (
    _redact_text_pymupdf,
    encrypt_pdf,
    remove_watermarks,
)
from tests.fixtures.factories import make_image_bytes, make_pdf_bytes


def _extracted_text(path: Path) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(path).pages)


def _write(writer: PdfWriter, path: Path) -> Path:
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _font_name(page) -> str:
    """Name of an existing font resource on the page (reportlab emits one)."""
    fonts = page["/Resources"]["/Font"].get_object()
    return next(iter(fonts.keys()))


def _append_content(writer: PdfWriter, page, extra: bytes) -> None:
    """Append raw operators to a page's content stream."""
    stream = ContentStream(page.get_contents(), writer)
    combined = DecodedStreamObject()
    combined.set_data(stream.get_data() + b"\n" + extra)
    page.replace_contents(combined)


def _pdf_with_app_watermark(
    tmp_path: Path, text: str = "CONFIDENTIAL", *, tile: bool = False
) -> Path:
    """A PDF watermarked by this app's own Add Watermark tool (flattened)."""
    source = tmp_path / "plain.pdf"
    source.write_bytes(make_pdf_bytes(pages=2))
    stamped = tmp_path / "stamped.pdf"
    overlay_pdf(
        source,
        stamped,
        make_watermark_draw(
            text,
            font_size=48,
            opacity=0.3,
            rotation=45,
            color="#ff0000",
            tile=tile,
        ),
    )
    return stamped


def _pdf_with_watermark_layer(tmp_path: Path) -> Path:
    """A PDF whose catalog declares an OCG named 'Watermark'."""
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))

    ocg = DictionaryObject()
    ocg[NameObject("/Type")] = NameObject("/OCG")
    ocg[NameObject("/Name")] = TextStringObject("Watermark Layer")
    ocg_ref = writer._add_object(ocg)

    config = DictionaryObject()
    config[NameObject("/ON")] = ArrayObject([ocg_ref])
    oc_properties = DictionaryObject()
    oc_properties[NameObject("/OCGs")] = ArrayObject([ocg_ref])
    oc_properties[NameObject("/D")] = config
    writer._root_object[NameObject("/OCProperties")] = oc_properties

    path = tmp_path / "layered.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    return path


class TestRemoveWatermarksLayers:
    def test_watermark_layer_moved_to_off(self, tmp_path):
        source = _pdf_with_watermark_layer(tmp_path)
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(source, destination, mode="layers")

        assert removed == 1
        catalog = PdfReader(destination).trailer["/Root"]
        config = catalog["/OCProperties"]["/D"]
        off = [str(ref.get_object()["/Name"]) for ref in config["/OFF"]]
        assert "Watermark Layer" in off
        on = [str(ref.get_object()["/Name"]) for ref in config.get("/ON", [])]
        assert "Watermark Layer" not in on

    def test_annotations_mode_ignores_layers(self, tmp_path):
        source = _pdf_with_watermark_layer(tmp_path)
        destination = tmp_path / "clean.pdf"
        assert remove_watermarks(source, destination, mode="annotations") == 0


def _page_ink(path: Path, index: int = 0) -> int:
    """Non-white pixel count of a rendered page — proxy for visible content."""
    import fitz

    doc = fitz.open(str(path))
    try:
        pix = doc[index].get_pixmap()
        samples, n = pix.samples, pix.n
        return sum(
            1
            for i in range(0, len(samples), n)
            if samples[i : i + 3] != b"\xff\xff\xff"
        )
    finally:
        doc.close()


def _pdf_with_image_watermark(
    tmp_path: Path,
    *,
    pages: int = 2,
    opacity: float = 0.4,
    rotation: int = 0,
    scale: float = 0.5,
    position: str = "center",
) -> Path:
    source = tmp_path / f"plain-{pages}.pdf"
    source.write_bytes(make_pdf_bytes(pages=pages))
    image = tmp_path / "mark.jpg"
    image.write_bytes(make_image_bytes("JPEG", size=(200, 150)))
    stamped = tmp_path / "image-stamped.pdf"
    overlay_pdf(
        source,
        stamped,
        make_image_watermark_draw(
            image, opacity=opacity, rotation=rotation, scale=scale, position=position
        ),
    )
    return stamped


class TestRemoveWatermarksAutoText:
    """Flattened text watermarks removed with NO options at all."""

    def test_transparent_diagonal_watermark_auto_removed(self, tmp_path):
        stamped = _pdf_with_app_watermark(tmp_path)
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(stamped, destination)  # no text given

        assert removed >= 2
        text = _extracted_text(destination)
        assert "CONFIDENTIAL" not in text
        assert "Body text 1" in text and "Body text 2" in text

    def test_tiled_watermark_auto_removed(self, tmp_path):
        stamped = _pdf_with_app_watermark(tmp_path, text="DRAFT", tile=True)
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(stamped, destination)

        assert removed > 2
        assert "DRAFT" not in _extracted_text(destination)
        assert "Body text 1" in _extracted_text(destination)

    def test_single_page_opaque_diagonal_watermark_auto_removed(self, tmp_path):
        """Rotation alone is enough when the text is watermark-sized."""
        source = tmp_path / "plain.pdf"
        source.write_bytes(make_pdf_bytes(pages=1))
        stamped = tmp_path / "stamped.pdf"
        overlay_pdf(
            source,
            stamped,
            make_watermark_draw(
                "SPECIMEN",
                font_size=60,
                opacity=1.0,
                rotation=45,
                color="#cc0000",
                tile=False,
            ),
        )
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(stamped, destination)

        assert removed >= 1
        assert "SPECIMEN" not in _extracted_text(destination)
        assert "Body text 1" in _extracted_text(destination)

    def test_body_text_matching_watermark_word_survives(self, tmp_path):
        """A plain heading saying the same word as the watermark is kept."""
        source = tmp_path / "plain.pdf"
        source.write_bytes(make_pdf_bytes(pages=2, text="draft memo"))
        stamped = tmp_path / "stamped.pdf"
        overlay_pdf(
            source,
            stamped,
            make_watermark_draw(
                "DRAFT MEMO",
                font_size=48,
                opacity=0.3,
                rotation=45,
                color="#888888",
                tile=False,
            ),
        )
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(stamped, destination)

        assert removed >= 2
        text = _extracted_text(destination)
        assert "draft memo 1" in text and "draft memo 2" in text
        assert "DRAFT MEMO" not in text  # the diagonal transparent copy

    def test_repeated_headers_survive(self, tmp_path):
        """Horizontal opaque text repeating on every page is not a watermark."""
        source = tmp_path / "plain.pdf"
        source.write_bytes(make_pdf_bytes(pages=3))
        headed = tmp_path / "headed.pdf"
        overlay_pdf(
            source,
            headed,
            make_header_footer_draw(
                "ACME Corp Annual Report",
                "Internal use",
                font_size=10,
                color="#333333",
                margin_pt=30.0,
                align="center",
            ),
        )
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(headed, destination)

        assert removed == 0
        text = _extracted_text(destination)
        assert "ACME Corp Annual Report" in text
        assert "Internal use" in text


class TestRemoveWatermarksAutoImage:
    """Flattened image watermarks removed with NO options at all."""

    def test_transparent_centered_image_auto_removed(self, tmp_path):
        stamped = _pdf_with_image_watermark(tmp_path)
        destination = tmp_path / "clean.pdf"
        before = _page_ink(stamped)

        removed = remove_watermarks(stamped, destination)

        after = _page_ink(destination)
        assert removed >= 2  # one draw per page
        assert after < before * 0.5, f"ink {before} -> {after}"
        assert "Body text 1" in _extracted_text(destination)

    def test_rotated_image_auto_removed(self, tmp_path):
        stamped = _pdf_with_image_watermark(
            tmp_path, pages=1, opacity=1.0, rotation=30
        )
        destination = tmp_path / "clean.pdf"
        before = _page_ink(stamped)

        removed = remove_watermarks(stamped, destination)

        assert removed >= 1
        assert _page_ink(destination) < before * 0.5

    def test_small_corner_logo_survives(self, tmp_path):
        """An opaque logo repeated in the page corner is not a watermark."""
        stamped = _pdf_with_image_watermark(
            tmp_path, pages=3, opacity=1.0, scale=0.08, position="top-left"
        )
        destination = tmp_path / "clean.pdf"
        before = _page_ink(stamped)

        removed = remove_watermarks(stamped, destination)

        assert removed == 0
        assert _page_ink(destination) >= before * 0.9

    def test_full_page_scan_survives(self, tmp_path):
        """Full-page raster images (scanned documents) are never touched."""
        import fitz

        image = tmp_path / "scan.jpg"
        image.write_bytes(
            make_image_bytes("JPEG", size=(850, 1100), color=(240, 235, 220))
        )
        doc = fitz.open()
        for _ in range(2):
            page = doc.new_page(width=612, height=792)
            page.insert_image(fitz.Rect(0, 0, 612, 792), filename=str(image))
        source = tmp_path / "scanned.pdf"
        doc.save(str(source))
        doc.close()
        destination = tmp_path / "clean.pdf"
        before = _page_ink(source)

        removed = remove_watermarks(source, destination)

        assert removed == 0
        assert _page_ink(destination) >= before * 0.9


class TestRemoveWatermarksText:
    """Flattened text watermarks removed via the ``text`` option."""

    def test_app_added_watermark_removed(self, tmp_path):
        stamped = _pdf_with_app_watermark(tmp_path)
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(stamped, destination, text="CONFIDENTIAL")

        assert removed >= 2  # one block per page
        text = _extracted_text(destination)
        assert "CONFIDENTIAL" not in text
        assert "Body text 1" in text and "Body text 2" in text

    def test_tiled_watermark_removed_everywhere(self, tmp_path):
        stamped = _pdf_with_app_watermark(tmp_path, tile=True)
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(stamped, destination, text="CONFIDENTIAL")

        assert removed > 2  # many tiles per page
        assert "CONFIDENTIAL" not in _extracted_text(destination)
        assert "Body text 1" in _extracted_text(destination)

    def test_matching_is_case_and_whitespace_insensitive(self, tmp_path):
        stamped = _pdf_with_app_watermark(tmp_path, text="Do Not Copy")
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(stamped, destination, text="do  not copy")

        assert removed >= 2
        assert "Do Not Copy" not in _extracted_text(destination)

    def test_text_split_across_show_operators_matches(self, tmp_path):
        """Watermarks drawn as several Tj runs inside one BT block."""
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        page = writer.pages[0]
        font = _font_name(page).encode()
        _append_content(
            writer,
            page,
            b"BT " + font + b" 24 Tf 72 300 Td (CONFID) Tj (ENTIAL) Tj ET",
        )
        source = _write(writer, tmp_path / "split.pdf")
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(source, destination, text="CONFIDENTIAL")

        assert removed == 1
        text = _extracted_text(destination)
        assert "CONFID" not in text
        assert "Body text 1" in text

    def test_watermark_inside_form_xobject_removed(self, tmp_path):
        """Stamps drawn via a Form XObject rather than the page stream."""
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        page = writer.pages[0]
        font = _font_name(page).encode()

        form = DecodedStreamObject()
        form[NameObject("/Type")] = NameObject("/XObject")
        form[NameObject("/Subtype")] = NameObject("/Form")
        form[NameObject("/BBox")] = ArrayObject(
            [NumberObject(0), NumberObject(0), NumberObject(612), NumberObject(792)]
        )
        resources = DictionaryObject()
        resources[NameObject("/Font")] = page["/Resources"]["/Font"]
        form[NameObject("/Resources")] = resources
        form.set_data(b"BT " + font + b" 36 Tf 100 400 Td (SAMPLE) Tj ET")
        form_ref = writer._add_object(form)

        page_resources = page["/Resources"]
        xobjects = DictionaryObject()
        xobjects[NameObject("/WMX")] = form_ref
        page_resources[NameObject("/XObject")] = xobjects
        _append_content(writer, page, b"q /WMX Do Q")
        source = _write(writer, tmp_path / "xobject.pdf")
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(source, destination, text="SAMPLE")

        assert removed == 1
        text = _extracted_text(destination)
        assert "SAMPLE" not in text
        assert "Body text 1" in text

    def test_text_not_found_returns_zero(self, tmp_path):
        source = tmp_path / "plain.pdf"
        source.write_bytes(make_pdf_bytes(pages=1))

        removed = remove_watermarks(source, tmp_path / "out.pdf", text="MISSING")

        assert removed == 0
        assert "Body text 1" in _extracted_text(tmp_path / "out.pdf")

    def test_pymupdf_fallback_removes_text(self, tmp_path):
        """The redaction fallback works standalone on a watermarked file."""
        stamped = _pdf_with_app_watermark(tmp_path)

        matches = _redact_text_pymupdf(stamped, "CONFIDENTIAL")

        assert matches >= 2
        assert "CONFIDENTIAL" not in _extracted_text(stamped)


class TestRemoveWatermarksArtifacts:
    """Acrobat-style /Artifact watermark stamps removed automatically."""

    def test_artifact_watermark_removed_without_text(self, tmp_path):
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        page = writer.pages[0]
        font = _font_name(page).encode()
        _append_content(
            writer,
            page,
            b"/Artifact <</Subtype /Watermark>> BDC\n"
            b"BT " + font + b" 40 Tf 100 500 Td (DRAFT) Tj ET\nEMC",
        )
        source = _write(writer, tmp_path / "artifact.pdf")
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(source, destination)

        assert removed == 1
        text = _extracted_text(destination)
        assert "DRAFT" not in text
        assert "Body text 1" in text

    def test_non_watermark_artifact_kept(self, tmp_path):
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        page = writer.pages[0]
        font = _font_name(page).encode()
        _append_content(
            writer,
            page,
            b"/Artifact <</Subtype /Pagination>> BDC\n"
            b"BT " + font + b" 10 Tf 100 30 Td (Page 1) Tj ET\nEMC",
        )
        source = _write(writer, tmp_path / "pagination.pdf")
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(source, destination)

        assert removed == 0
        assert "Page 1" in _extracted_text(destination)


class TestRemoveWatermarksOcContent:
    """Optional-content watermark blocks are stripped, not just hidden."""

    def test_oc_marked_content_stripped(self, tmp_path):
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        page = writer.pages[0]
        font = _font_name(page).encode()

        ocg = DictionaryObject()
        ocg[NameObject("/Type")] = NameObject("/OCG")
        ocg[NameObject("/Name")] = TextStringObject("Watermark")
        ocg_ref = writer._add_object(ocg)

        config = DictionaryObject()
        config[NameObject("/ON")] = ArrayObject([ocg_ref])
        oc_properties = DictionaryObject()
        oc_properties[NameObject("/OCGs")] = ArrayObject([ocg_ref])
        oc_properties[NameObject("/D")] = config
        writer._root_object[NameObject("/OCProperties")] = oc_properties

        properties = DictionaryObject()
        properties[NameObject("/oc1")] = ocg_ref
        page["/Resources"][NameObject("/Properties")] = properties
        _append_content(
            writer,
            page,
            b"/OC /oc1 BDC\nBT " + font + b" 40 Tf 100 500 Td (SECRET) Tj ET\nEMC",
        )
        source = _write(writer, tmp_path / "layered.pdf")
        destination = tmp_path / "clean.pdf"

        removed = remove_watermarks(source, destination, mode="layers")

        assert removed == 2  # content block stripped + OCG switched off
        assert "SECRET" not in _extracted_text(destination)
        assert "Body text 1" in _extracted_text(destination)


class TestRemoveWatermarksValidation:
    def test_password_protected_source_raises_friendly_error(self, tmp_path):
        source = tmp_path / "locked.pdf"
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        writer.encrypt(user_password="pw", algorithm="AES-256")
        _write(writer, source)

        with pytest.raises(ProcessingError, match="password-protected"):
            remove_watermarks(source, tmp_path / "out.pdf")

    def test_corrupt_source_raises_processing_error(self, tmp_path):
        source = tmp_path / "junk.pdf"
        source.write_bytes(b"this is not a pdf at all")

        with pytest.raises(ProcessingError):
            remove_watermarks(source, tmp_path / "out.pdf")

    def test_page_without_contents_is_tolerated(self, tmp_path):
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        writer.add_blank_page(width=612, height=792)
        source = _write(writer, tmp_path / "blank.pdf")

        removed = remove_watermarks(source, tmp_path / "out.pdf", text="ANY")

        assert removed == 0
        assert len(PdfReader(tmp_path / "out.pdf").pages) == 2


class TestEncryptPdf:
    def test_permissions_and_owner_password(self, tmp_path):
        source = tmp_path / "in.pdf"
        source.write_bytes(make_pdf_bytes(pages=1))
        destination = tmp_path / "out.pdf"

        encrypt_pdf(
            source,
            destination,
            user_password="userpass",
            owner_password="ownerpass",
            allow_printing=True,
            allow_copying=False,
        )

        reader = PdfReader(destination)
        assert reader.is_encrypted
        assert reader.decrypt("ownerpass") != 0

    def test_encrypted_source_raises_processing_error(self, tmp_path):
        source = tmp_path / "locked.pdf"
        writer = PdfWriter(clone_from=io.BytesIO(make_pdf_bytes(pages=1)))
        writer.encrypt(user_password="pw", algorithm="AES-256")
        with source.open("wb") as handle:
            writer.write(handle)

        with pytest.raises(ProcessingError):
            encrypt_pdf(source, tmp_path / "out.pdf", user_password="newpass")
