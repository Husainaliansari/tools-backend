"""Unit tests for OCR language validation and Latin-script classification."""

from __future__ import annotations

import pytest

from app.utils.ocr_language import (
    MAX_OCR_LANGUAGES,
    classify_latin_text,
    validate_ocr_languages,
)


class TestValidateOcrLanguages:
    def test_single_and_combined_pass(self):
        assert validate_ocr_languages("eng") == "eng"
        assert validate_ocr_languages("eng+deu") == "eng+deu"
        assert validate_ocr_languages("chi_sim+eng") == "chi_sim+eng"

    def test_unknown_language_rejected(self):
        with pytest.raises(ValueError, match="Unsupported OCR language"):
            validate_ocr_languages("xyz")
        with pytest.raises(ValueError, match="klingon"):
            validate_ocr_languages("eng+klingon")

    def test_duplicates_rejected(self):
        with pytest.raises(ValueError, match="Duplicate"):
            validate_ocr_languages("eng+eng")

    def test_too_many_languages_rejected(self):
        too_many = "+".join(["eng", "deu", "fra", "spa", "ita"])
        assert len(too_many.split("+")) > MAX_OCR_LANGUAGES
        with pytest.raises(ValueError, match="At most"):
            validate_ocr_languages(too_many)


class TestClassifyLatinText:
    def test_german(self):
        text = (
            "Der schnelle braune Fuchs springt über den faulen Hund und die "
            "Rechnung wurde heute vollständig bezahlt bitte kontaktieren Sie "
            "unseren Kundendienst für weitere Fragen das ist ein wichtiges "
            "Dokument und eine Bestätigung für Sie"
        )
        assert classify_latin_text(text) == "deu"

    def test_french(self):
        text = (
            "Le renard brun rapide saute par-dessus le chien paresseux la "
            "facture a été payée intégralement aujourd'hui veuillez contacter "
            "notre service client pour plus de détails dans les meilleurs "
            "délais cette confirmation est une preuve pour vous"
        )
        assert classify_latin_text(text) == "fra"

    def test_english(self):
        text = (
            "The quick brown fox jumps over the lazy dog and the invoice was "
            "paid in full today please contact support with any questions "
            "about this document and the confirmation that was attached"
        )
        assert classify_latin_text(text) == "eng"

    def test_thin_sample_is_inconclusive(self):
        assert classify_latin_text("Invoice 42") is None

    def test_numbers_only_is_inconclusive(self):
        assert classify_latin_text("42 17 2026 3.14 99 100 200 300 400 500") is None
