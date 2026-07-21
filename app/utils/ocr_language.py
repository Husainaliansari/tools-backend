"""OCR language support: the installed-language registry, automatic
document-language detection, and the subprocess environment that lets
OCRmyPDF/Tesseract find their per-user binaries and traineddata.

Detection strategy (fast — samples at most a few pages):

1. Render sample pages to grayscale PNGs with PyMuPDF (in-process, no
   external rasteriser needed).
2. Ask Tesseract's OSD (orientation & script detection) which *script*
   the page uses. Non-Latin scripts map straight to a language pack
   (Arabic -> ara, Cyrillic -> rus, Han -> chi_sim+chi_tra, ...).
3. Latin script is shared by dozens of languages, so run a quick
   English-model OCR pass on the sample and classify the result by
   language-specific stopwords.

Detection must never fail a job: any error degrades to the caller's
fallback language with a logged warning.
"""

from __future__ import annotations

import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.logging import get_logger
from app.utils.command import CommandError, run_command, split_launcher

logger = get_logger(__name__)

#: Tesseract language packs installed alongside the app (see .env.example).
#: Keep in sync with the frontend's OCR language picker.
SUPPORTED_OCR_LANGUAGES: frozenset[str] = frozenset(
    {
        "eng",  # English
        "ara",  # Arabic
        "chi_sim",  # Chinese (Simplified)
        "chi_tra",  # Chinese (Traditional)
        "deu",  # German
        "ell",  # Greek
        "fra",  # French
        "heb",  # Hebrew
        "hin",  # Hindi
        "ita",  # Italian
        "jpn",  # Japanese
        "kor",  # Korean
        "nld",  # Dutch
        "pol",  # Polish
        "por",  # Portuguese
        "rus",  # Russian
        "spa",  # Spanish
        "tha",  # Thai
        "tur",  # Turkish
        "urd",  # Urdu
        "vie",  # Vietnamese
    }
)

#: Tesseract slows roughly linearly per extra language model.
MAX_OCR_LANGUAGES = 4

#: OSD script name -> language pack(s). Scripts absent here (or "Latin")
#: fall through to stopword classification / the fallback language.
_SCRIPT_LANGUAGES: dict[str, str] = {
    "Arabic": "ara",
    "Cyrillic": "rus",
    "Devanagari": "hin",
    "Greek": "ell",
    "Hebrew": "heb",
    "Thai": "tha",
    "Han": "chi_sim+chi_tra",
    "HanS": "chi_sim",
    "HanT": "chi_tra",
    "HanS_vert": "chi_sim",
    "HanT_vert": "chi_tra",
    "Japanese": "jpn",
    "Japanese_vert": "jpn",
    "Katakana": "jpn",
    "Hiragana": "jpn",
    "Hangul": "kor",
    "Hangul_vert": "kor",
}

#: High-frequency words that are near-unique per Latin-script language.
#: Deliberately excludes forms shared across Romance languages ("de", "la").
_LATIN_STOPWORDS: dict[str, frozenset[str]] = {
    "eng": frozenset(
        "the and was are this that with from have been will your which "
        "their would there".split()
    ),
    "deu": frozenset(
        "der die das und ist nicht mit ein eine für auf den dem sie wir "
        "werden wurde bitte sind einen oder auch beim über".split()
    ),
    "fra": frozenset(
        "les des est une dans pour que qui avec sur pas nous vous être "
        "par cette aux ont été plus votre".split()
    ),
    "spa": frozenset(
        "los las una para con por del como más pero sus este esta hay "
        "muy fue entre también usted".split()
    ),
    "ita": frozenset(
        "gli che per sono della delle una questo questa anche più nel "
        "alla degli come sia stato essere".split()
    ),
    "por": frozenset(
        "uma para com não por dos das mais este esta são você está foi "
        "como pelo seus também".split()
    ),
    "nld": frozenset(
        "het een van dat niet met voor aan zijn deze ook naar wordt "
        "worden bij als maar door onze".split()
    ),
    "pol": frozenset(
        "nie się jest że jak ale przez dla tego oraz jego były został "
        "które można bardzo".split()
    ),
    "tur": frozenset(
        "bir bu için ile olarak daha çok gibi olan kadar sonra ancak "
        "değil var tarafından".split()
    ),
    "vie": frozenset(
        "của và các cho không được người trong những này với ngày "
        "chúng tôi".split()
    ),
}

#: Minimum stopword hits before trusting a non-English classification.
_MIN_STOPWORD_HITS = 4

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

#: Well-known Windows install locations, tried when the configured binary
#: is a bare name that isn't on PATH (per-user setups often skip PATH).
_TESSERACT_FALLBACKS = (
    Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
    Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
    Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
)


@dataclass(frozen=True)
class LanguageDetection:
    """Outcome of automatic language detection."""

    language: str
    script: str | None = None
    detected: bool = False  # False -> fallback was used


def resolve_tesseract_launcher() -> list[str]:
    """Argv prefix for invoking Tesseract, honouring TESSERACT_BIN and
    falling back to well-known install locations."""
    settings = get_settings()
    launcher = split_launcher(settings.TESSERACT_BIN)
    if launcher[0] != "tesseract" or shutil.which("tesseract"):
        return launcher
    for candidate in _TESSERACT_FALLBACKS:
        if candidate.is_file():
            return [str(candidate)]
    return launcher


def ocr_subprocess_env() -> dict[str, str]:
    """Environment for OCR subprocesses: prepends the Tesseract and
    Ghostscript directories to PATH (OCRmyPDF discovers both by name) and
    points TESSDATA_PREFIX at the configured language-pack directory."""
    settings = get_settings()
    env = os.environ.copy()

    tesseract_exe = resolve_tesseract_launcher()[0]
    ghostscript_exe = (
        split_launcher(settings.GHOSTSCRIPT_BIN)[0] if settings.GHOSTSCRIPT_BIN else ""
    )
    additions: list[str] = []
    for exe in (tesseract_exe, ghostscript_exe):
        parent = Path(exe).parent
        if parent.name:  # bare command names have no directory
            additions.append(str(parent))
    if additions:
        env["PATH"] = os.pathsep.join([*additions, env.get("PATH", "")])
    if settings.TESSDATA_DIR:
        env["TESSDATA_PREFIX"] = settings.TESSDATA_DIR
    return env


def validate_ocr_languages(language: str) -> str:
    """Validate a '+'-joined Tesseract language string against the
    installed packs. Returns the value; raises ValueError otherwise."""
    parts = language.split("+")
    unknown = [part for part in parts if part not in SUPPORTED_OCR_LANGUAGES]
    if unknown:
        supported = ", ".join(sorted(SUPPORTED_OCR_LANGUAGES))
        raise ValueError(
            f"Unsupported OCR language(s): {', '.join(unknown)}. "
            f"Supported: {supported}."
        )
    if len(parts) != len(set(parts)):
        raise ValueError("Duplicate OCR language codes.")
    if len(parts) > MAX_OCR_LANGUAGES:
        raise ValueError(
            f"At most {MAX_OCR_LANGUAGES} languages can be combined per document."
        )
    return language


def classify_latin_text(text: str) -> str | None:
    """Guess the language of Latin-script OCR text via stopword counts.

    Returns a language code, or None when the sample is too thin or too
    ambiguous to beat the English fallback.
    """
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if len(words) < 10:
        return None
    counts = Counter(words)
    scores = {
        lang: sum(count for word, count in counts.items() if word in stopwords)
        for lang, stopwords in _LATIN_STOPWORDS.items()
    }
    best_lang, best_hits = max(scores.items(), key=lambda item: item[1])
    if best_hits < _MIN_STOPWORD_HITS:
        return None
    if best_lang != "eng" and best_hits < 1.5 * scores["eng"]:
        return None  # not clearly ahead of English — stay with the fallback
    return best_lang


def _render_sample(pdf_path: Path, workspace: Path, *, max_pages: int) -> list[Path]:
    """Render up to ``max_pages`` pages to grayscale PNGs for detection."""
    import fitz  # PyMuPDF — deferred: heavy import, workers only

    images: list[Path] = []
    with fitz.open(pdf_path) as doc:
        if doc.needs_pass:
            return []
        for number in range(min(len(doc), max_pages)):
            target = workspace / f"lang-sample-{number}.png"
            pix = doc[number].get_pixmap(dpi=150, colorspace=fitz.csGRAY)
            pix.save(target)
            images.append(target)
    return images


def _tesseract(args: list[str], env: dict[str, str]) -> str:
    launcher = resolve_tesseract_launcher()
    result = run_command([*launcher, *args], timeout=60, env=env)
    return result.stdout


def _detect_script(image: Path, env: dict[str, str]) -> tuple[str | None, int]:
    """OSD pass: returns (script name, rotation-to-apply degrees)."""
    output = _tesseract([str(image), "stdout", "--psm", "0"], env)
    script = None
    rotate = 0
    for line in output.splitlines():
        if line.startswith("Script:"):
            script = line.split(":", 1)[1].strip()
        elif line.startswith("Rotate:"):
            try:
                rotate = int(line.split(":", 1)[1].strip())
            except ValueError:
                rotate = 0
    return script, rotate


def _sample_text(image: Path, rotate: int, env: dict[str, str]) -> str:
    """Quick English-model OCR of a sample image (for Latin classification)."""
    if rotate:
        from PIL import Image

        with Image.open(image) as img:
            corrected = img.rotate(-rotate, expand=True, fillcolor=255)
            corrected.save(image)
    return _tesseract([str(image), "stdout", "-l", "eng", "--psm", "3"], env)


def detect_document_language(
    pdf_path: Path,
    workspace: Path,
    *,
    fallback: str = "eng",
    max_pages: int = 2,
) -> LanguageDetection:
    """Best-effort automatic language detection for a PDF.

    Never raises: every failure path returns the fallback language so the
    OCR job proceeds regardless.
    """
    env = ocr_subprocess_env()
    try:
        images = _render_sample(pdf_path, workspace, max_pages=max_pages)
    except Exception:
        logger.warning("ocr_language_render_failed", file=pdf_path.name)
        return LanguageDetection(language=fallback)
    if not images:
        return LanguageDetection(language=fallback)

    scripts: list[str] = []
    latin_langs: list[str] = []
    for image in images:
        try:
            script, rotate = _detect_script(image, env)
        except CommandError:
            continue  # e.g. blank page: "Too few characters"
        if script in _SCRIPT_LANGUAGES:
            scripts.append(script)
            continue
        if script == "Latin":
            scripts.append(script)
            try:
                text = _sample_text(image, rotate, env)
            except CommandError:
                continue
            guess = classify_latin_text(text)
            if guess:
                latin_langs.append(guess)

    if not scripts:
        logger.info("ocr_language_undetected", file=pdf_path.name, used=fallback)
        return LanguageDetection(language=fallback)

    script = Counter(scripts).most_common(1)[0][0]
    if script != "Latin":
        language = _SCRIPT_LANGUAGES[script]
    else:
        # Union the per-page guesses (multi-language documents); English
        # last as the safety net for names, numbers and boilerplate.
        ordered = [lang for lang, _ in Counter(latin_langs).most_common()]
        if "eng" not in ordered:
            ordered.append("eng")
        language = "+".join(ordered[:MAX_OCR_LANGUAGES])

    logger.info(
        "ocr_language_detected",
        file=pdf_path.name,
        script=script,
        language=language,
    )
    return LanguageDetection(language=language, script=script, detected=True)
