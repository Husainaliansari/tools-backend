"""PDF security operations (pypdf + PyMuPDF): watermark removal and encryption.

Watermark removal works in two passes over the document's content streams:

1. an *analysis* pass — a small graphics-state interpreter that measures, for
   every text block and image draw, the traits that distinguish watermarks
   from real content: diagonal rotation, transparency (ExtGState alpha or a
   soft mask), effective size/position on the page, and repetition across
   pages — and decides which text strings and images are watermarks;
2. a *rewrite* pass that surgically drops the identified objects, plus the
   structurally marked kinds (annotations, ``/Artifact`` watermark stamps,
   optional-content layers) that need no heuristics at all.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, NameObject

from app.exceptions.jobs import ProcessingError
from app.logging import get_logger

logger = get_logger(__name__)

#: Case-insensitive marker used to recognise watermark-named objects.
_WATERMARK = "watermark"

#: Operators that show text inside a BT..ET block.
_SHOW_TEXT_OPS = (b"Tj", b"TJ", b"'", b'"')

#: 2D identity transformation matrix (a, b, c, d, e, f).
_IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# ── Detection thresholds ────────────────────────────────────────────────────
#: Alpha below this counts as transparent (1.0 = fully opaque).
_OPAQUE = 0.999
#: Rotation this many degrees away from any 90° multiple counts as diagonal.
_DIAGONAL_TOLERANCE_DEG = 2.5
#: Auto-detected watermark strings must have this many characters...
_MIN_AUTO_TEXT = 2
#: ...and at most this many.
_MAX_AUTO_TEXT = 80
#: Diagonal text this large is a watermark even when opaque (pt).
_STRONG_DIAGONAL_SIZE = 24.0
#: Transparent text this large is a watermark even when horizontal (pt).
_STRONG_ALPHA_SIZE = 30.0
#: Same string/image drawn this often on one page counts as tiled.
_TILE_COUNT = 3
#: Images covering at least this fraction of the page count as large...
_IMAGE_BIG_RATIO = 0.15
#: ...but anything above this fraction is a scan/background, never removed.
_IMAGE_MAX_RATIO = 0.9
#: Never auto-remove more than this many distinct strings/images.
_MAX_AUTO_TARGETS = 8


def _clone(source: Path) -> PdfWriter:
    """Open ``source`` for rewriting, with user-friendly failure messages."""
    try:
        reader = PdfReader(str(source))
    except Exception as exc:
        raise ProcessingError(
            f"Could not read the PDF — it may be corrupted or not a valid PDF: {exc}"
        ) from exc
    if reader.is_encrypted:
        try:
            decrypted = reader.decrypt("")
        except Exception:
            decrypted = 0
        if not decrypted:
            raise ProcessingError(
                "The PDF is password-protected. Unlock it with its password "
                "first (Unlock PDF tool), then run this tool again."
            )
    try:
        if len(reader.pages) == 0:
            raise ProcessingError("The PDF contains no pages.")
        return PdfWriter(clone_from=reader)
    except ProcessingError:
        raise
    except Exception as exc:
        raise ProcessingError(
            f"Could not read the PDF (is it damaged?): {exc}"
        ) from exc


def _deref(value):
    """Resolve an indirect reference to its object (identity for None/direct)."""
    return value.get_object() if hasattr(value, "get_object") else value


def _normalise(text: str) -> str:
    """Whitespace-insensitive, case-insensitive comparison form."""
    return "".join(text.split()).lower()


def _operand_text(operands: list) -> str:
    """Shown text of a Tj/TJ/'/" operator (best effort, latin-1 for bytes)."""
    parts: list[str] = []

    def append(value) -> None:
        if isinstance(value, bytes):
            parts.append(value.decode("latin-1", errors="ignore"))
        elif isinstance(value, str):
            parts.append(value)

    for operand in operands:
        if isinstance(operand, list):  # TJ: strings interleaved with kerning
            for item in operand:
                append(item)
        else:
            append(operand)
    return "".join(parts)


# ── Matrix helpers ──────────────────────────────────────────────────────────
def _matrix(operands) -> tuple[float, ...]:
    try:
        return tuple(float(value) for value in operands[:6])
    except Exception:
        return _IDENTITY


def _mat_mul(m1, m2) -> tuple[float, ...]:
    """Compose transformations: apply ``m1`` first, then ``m2``."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    )


def _mat_scale(m) -> float:
    """Average scale factor of a matrix (for effective font sizes)."""
    return math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))


def _is_diagonal(m) -> bool:
    """True when the matrix rotates away from any 90° multiple."""
    a, b = m[0], m[1]
    if abs(a) < 1e-9 and abs(b) < 1e-9:
        return False
    angle = math.degrees(math.atan2(b, a)) % 90.0
    return _DIAGONAL_TOLERANCE_DEG < angle < 90.0 - _DIAGONAL_TOLERANCE_DEG


# ── Resource helpers ────────────────────────────────────────────────────────
def _looks_like_watermark(annotation: dict) -> bool:
    if str(annotation.get("/Subtype", "")) == "/Watermark":
        return True
    label = " ".join(str(annotation.get(key, "")) for key in ("/NM", "/T", "/Contents"))
    return _WATERMARK in label.lower()


def _resolve_properties(operand, resources) -> DictionaryObject | None:
    """Resolve a BDC properties operand — inline dict or /Properties name."""
    operand = _deref(operand)
    if isinstance(operand, DictionaryObject):
        return operand
    if resources is None:
        return None
    properties = _deref(resources.get("/Properties"))
    if properties is None:
        return None
    return _deref(properties.get(str(operand)))


def _member_ocgs(properties) -> list:
    """The OCG dicts an /OC properties value refers to (OCG or OCMD)."""
    properties = _deref(properties)
    if properties is None:
        return []
    if str(properties.get("/Type", "")) == "/OCMD":
        ocgs = _deref(properties.get("/OCGs"))
        if ocgs is None:
            return []
        if isinstance(ocgs, DictionaryObject):
            return [ocgs]
        return [_deref(item) for item in ocgs]
    return [properties]


def _is_watermark_oc(properties) -> bool:
    return any(
        _WATERMARK in str(group.get("/Name", "")).lower()
        for group in _member_ocgs(properties)
    )


def _is_watermark_artifact(properties) -> bool:
    if properties is None:
        return False
    if str(properties.get("/Subtype", "")) == "/Watermark":
        return True
    return _WATERMARK in str(properties.get("/Name", "")).lower()


def _xobject_named(operands, resources):
    """The XObject dict a Do operator draws, or None."""
    if not operands or resources is None:
        return None
    xobjects = _deref(resources.get("/XObject"))
    if xobjects is None:
        return None
    return _deref(xobjects.get(str(operands[0])))


def _alpha_after_gs(operands, resources, current: float) -> float:
    """Fill alpha after a ``gs`` operator (unchanged if the state omits it)."""
    if not operands or resources is None:
        return current
    states = _deref(resources.get("/ExtGState"))
    if states is None:
        return current
    state = _deref(states.get(str(operands[0])))
    if state is None:
        return current
    for key in ("/ca", "/CA"):
        value = state.get(key)
        if value is not None:
            try:
                return float(value)
            except Exception:
                return current
    return current


def _image_digest(xobject) -> bytes:
    """Stable identity for an image, robust to per-page duplicate objects."""
    digest = hashlib.md5(usedforsecurity=False)
    digest.update(str(xobject.get("/Width", "")).encode())
    digest.update(str(xobject.get("/Height", "")).encode())
    try:
        raw = xobject._data or b""
        digest.update(str(len(raw)).encode())
        digest.update(raw[:4096])
    except Exception:
        digest.update(str(id(xobject)).encode())
    return digest.digest()


def _inline_image_digest(operands) -> bytes | None:
    try:
        data = operands["data"]
    except Exception:
        return None
    return hashlib.md5(b"inline:" + bytes(data), usedforsecurity=False).digest()


# ── Analysis pass: find watermark-like text and images ──────────────────────
@dataclass
class _Detection:
    """What the analysis pass decided to remove."""

    text_needles: set[str] = field(default_factory=set)
    image_digests: set[bytes] = field(default_factory=set)
    #: Per Form XObject (by id): (min alpha, any diagonal) at its draw sites,
    #: so the rewrite of the shared form inherits the page-level traits.
    form_hints: dict[int, tuple[float, bool]] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.text_needles or self.image_digests)


class _DetectionSink:
    """Accumulates trait observations and turns them into removal decisions."""

    def __init__(self, total_pages: int) -> None:
        self.total_pages = total_pages
        self._texts: dict[str, dict] = {}
        self._images: dict[bytes, dict] = {}
        self._form_hints: dict[int, list] = {}

    def text(
        self, page: int, norm: str, diagonal: bool, alpha: float, size: float
    ) -> None:
        if not (_MIN_AUTO_TEXT <= len(norm) <= _MAX_AUTO_TEXT):
            return
        transparent = alpha < _OPAQUE
        if not (diagonal or transparent):  # plain text is never a candidate
            return
        record = self._texts.setdefault(
            norm, {"pages": set(), "counts": Counter(), "strong": False}
        )
        record["pages"].add(page)
        record["counts"][page] += 1
        if (
            (diagonal and transparent)
            or (diagonal and size >= _STRONG_DIAGONAL_SIZE)
            or (transparent and size >= _STRONG_ALPHA_SIZE)
        ):
            record["strong"] = True

    def image(
        self,
        page: int,
        digest: bytes,
        ctm,
        alpha: float,
        has_smask: bool,
        page_box: tuple[float, float, float, float],
    ) -> None:
        x0, y0, x1, y1 = page_box
        page_area = max((x1 - x0) * (y1 - y0), 1.0)
        area = abs(ctm[0] * ctm[3] - ctm[1] * ctm[2])
        ratio = area / page_area
        corners = [
            (ctm[0] * u + ctm[2] * v + ctm[4], ctm[1] * u + ctm[3] * v + ctm[5])
            for u, v in ((0, 0), (1, 0), (0, 1), (1, 1))
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
        centered = (
            min(xs) <= center_x <= max(xs)
            and min(ys) <= center_y <= max(ys)
            and ratio <= _IMAGE_MAX_RATIO
        )
        record = self._images.setdefault(
            digest,
            {
                "pages": set(),
                "counts": Counter(),
                "diagonal": False,
                "transparent": False,
                "centered": False,
                "big": False,
            },
        )
        record["pages"].add(page)
        record["counts"][page] += 1
        record["diagonal"] |= _is_diagonal(ctm)
        record["transparent"] |= alpha < _OPAQUE or has_smask
        record["centered"] |= centered
        record["big"] |= _IMAGE_BIG_RATIO <= ratio <= _IMAGE_MAX_RATIO

    def form(self, key: int, alpha: float, diagonal: bool) -> None:
        hint = self._form_hints.setdefault(key, [1.0, False])
        hint[0] = min(hint[0], alpha)
        hint[1] = hint[1] or diagonal

    def _covers_enough_pages(self, pages: set[int]) -> bool:
        return self.total_pages >= 2 and len(pages) >= max(
            2, (self.total_pages + 1) // 2
        )

    def decide(self) -> _Detection:
        """Apply the watermark rules to everything observed.

        Text is a watermark when any instance is *strongly* watermark-shaped
        (diagonal + transparent, large diagonal, or large transparent), when
        it tiles a page, or when the same trait-bearing string repeats on at
        least half the pages. Images additionally require a size/position
        signal so repeated header logos and full-page scans survive.
        """
        needles = {
            norm
            for norm, record in self._texts.items()
            if record["strong"]
            or any(count >= _TILE_COUNT for count in record["counts"].values())
            or self._covers_enough_pages(record["pages"])
        }
        images = {
            digest
            for digest, record in self._images.items()
            if record["diagonal"]
            or (
                record["transparent"]
                and (
                    record["centered"]
                    or record["big"]
                    or any(count >= _TILE_COUNT for count in record["counts"].values())
                )
            )
            or (
                self._covers_enough_pages(record["pages"])
                and record["centered"]
                and record["big"]
            )
        }
        if len(needles) > _MAX_AUTO_TARGETS:
            ranked = sorted(
                needles, key=lambda n: len(self._texts[n]["pages"]), reverse=True
            )
            needles = set(ranked[:_MAX_AUTO_TARGETS])
        if len(images) > _MAX_AUTO_TARGETS:
            ranked = sorted(
                images, key=lambda d: len(self._images[d]["pages"]), reverse=True
            )
            images = set(ranked[:_MAX_AUTO_TARGETS])
        return _Detection(
            text_needles=needles,
            image_digests=images,
            form_hints={key: (v[0], v[1]) for key, v in self._form_hints.items()},
        )


def _scan_operations(
    operations: list,
    resources,
    writer: PdfWriter,
    sink: _DetectionSink,
    *,
    page: int,
    page_box: tuple[float, float, float, float],
    ctm,
    alpha: float,
    depth: int,
    path: frozenset[int],
) -> None:
    """Walk a content stream, tracking graphics state, feeding the sink."""
    stack: list[tuple[tuple, float]] = []
    tm = _IDENTITY
    font_size = 0.0
    in_text = False
    block_text: list[str] = []
    block_diagonal = False
    block_alpha = 1.0
    block_size = 0.0

    for operands, operator in operations:
        if operator == b"q":
            stack.append((ctm, alpha))
        elif operator == b"Q":
            if stack:
                ctm, alpha = stack.pop()
        elif operator == b"cm":
            ctm = _mat_mul(_matrix(operands), ctm)
        elif operator == b"gs":
            alpha = _alpha_after_gs(operands, resources, alpha)
        elif operator == b"BT":
            in_text = True
            tm = _IDENTITY
            block_text = []
            block_diagonal = False
            block_alpha = alpha
            block_size = 0.0
        elif operator == b"Tm":
            tm = _matrix(operands)
        elif operator == b"Tf" and len(operands) == 2:
            try:
                font_size = float(operands[1])
            except Exception:
                font_size = 0.0
        elif operator in _SHOW_TEXT_OPS and in_text:
            block_text.append(_operand_text(operands))
            render = _mat_mul(tm, ctm)
            block_diagonal = block_diagonal or _is_diagonal(render)
            block_alpha = min(block_alpha, alpha)
            block_size = max(block_size, font_size * _mat_scale(render))
        elif operator == b"ET" and in_text:
            in_text = False
            norm = _normalise("".join(block_text))
            if norm:
                sink.text(page, norm, block_diagonal, block_alpha, block_size)
        elif operator == b"Do":
            xobject = _xobject_named(operands, resources)
            if xobject is None:
                continue
            subtype = str(xobject.get("/Subtype", ""))
            if subtype == "/Image":
                sink.image(
                    page,
                    _image_digest(xobject),
                    ctm,
                    alpha,
                    xobject.get("/SMask") is not None,
                    page_box,
                )
            elif subtype == "/Form" and depth < 6 and id(xobject) not in path:
                sink.form(id(xobject), alpha, _is_diagonal(ctm))
                inner_resources = _deref(xobject.get("/Resources")) or resources
                matrix = xobject.get("/Matrix")
                inner_ctm = _mat_mul(_matrix(matrix) if matrix else _IDENTITY, ctm)
                try:
                    inner_ops = ContentStream(xobject, writer).operations
                except Exception as exc:
                    logger.warning("watermark_scan_form_skipped", error=str(exc))
                    continue
                _scan_operations(
                    inner_ops,
                    inner_resources,
                    writer,
                    sink,
                    page=page,
                    page_box=page_box,
                    ctm=inner_ctm,
                    alpha=alpha,
                    depth=depth + 1,
                    path=path | {id(xobject)},
                )
        elif operator == b"INLINE IMAGE":
            digest = _inline_image_digest(operands)
            if digest is not None:
                sink.image(page, digest, ctm, alpha, False, page_box)


def _analyse_document(writer: PdfWriter) -> _Detection:
    """Detect watermark-like text strings and images across the document."""
    sink = _DetectionSink(total_pages=len(writer.pages))
    for index, page in enumerate(writer.pages):
        contents = page.get_contents()
        if contents is None:
            continue
        box = page.mediabox
        page_box = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        resources = _deref(page.get("/Resources"))
        try:
            operations = ContentStream(contents, writer).operations
        except Exception as exc:
            logger.warning("watermark_scan_page_skipped", page=index, error=str(exc))
            continue
        _scan_operations(
            operations,
            resources,
            writer,
            sink,
            page=index,
            page_box=page_box,
            ctm=_IDENTITY,
            alpha=1.0,
            depth=0,
            path=frozenset(),
        )
    return sink.decide()


# ── Rewrite pass: drop identified watermark content ─────────────────────────
@dataclass(frozen=True)
class _RewritePlan:
    """Everything the rewrite pass needs to decide what to drop."""

    user_needle: str | None
    detection: _Detection
    strip_layers: bool
    #: Traits inherited from the draw sites of the Form XObject being
    #: rewritten (page-level transparency/rotation the form itself can't see).
    hint_alpha: float = 1.0
    hint_diagonal: bool = False


def _filter_operations(
    operations: list,
    resources,
    plan: _RewritePlan,
) -> tuple[list, int, int]:
    """One pass over a content stream's operations, dropping watermark content.

    Removes (a) marked-content blocks tagged ``/Artifact`` with
    ``/Subtype /Watermark``, (b) when ``plan.strip_layers``, ``/OC``
    marked-content blocks and ``Do`` invocations tied to a watermark-named
    optional-content group, (c) BT..ET text blocks matching the user's text
    (contains) or an auto-detected watermark string (exact match, and only
    when the block itself carries a watermark trait — so a heading that
    merely says the same word survives), and (d) draws of auto-detected
    watermark images.

    Returns ``(kept_operations, removed_count, user_text_match_count)``.
    """
    detection = plan.detection
    kept: list = []
    removed = 0
    user_hits = 0
    skip_depth = 0
    block: list | None = None  # buffered BT..ET operations
    block_text: list[str] = []

    stack: list[tuple[tuple, float]] = []
    ctm: tuple = _IDENTITY
    alpha = plan.hint_alpha
    tm = _IDENTITY
    block_diagonal = False
    block_alpha = 1.0

    for operands, operator in operations:
        if skip_depth:
            if operator in (b"BDC", b"BMC"):
                skip_depth += 1
            elif operator == b"EMC":
                skip_depth -= 1
            continue

        # Graphics-state tracking (mirrors the analysis pass).
        if operator == b"q":
            stack.append((ctm, alpha))
        elif operator == b"Q":
            if stack:
                ctm, alpha = stack.pop()
        elif operator == b"cm":
            ctm = _mat_mul(_matrix(operands), ctm)
        elif operator == b"gs":
            alpha = _alpha_after_gs(operands, resources, alpha)
        elif operator == b"Tm":
            tm = _matrix(operands)

        if operator == b"BDC" and len(operands) == 2 and block is None:
            tag = str(operands[0])
            properties = _resolve_properties(operands[1], resources)
            if (tag == "/Artifact" and _is_watermark_artifact(properties)) or (
                plan.strip_layers and tag == "/OC" and _is_watermark_oc(properties)
            ):
                skip_depth = 1
                removed += 1
                continue

        if operator == b"BT" and block is None:
            block = [(operands, operator)]
            block_text = []
            tm = _IDENTITY
            block_diagonal = False
            block_alpha = alpha
            continue
        if block is not None:
            block.append((operands, operator))
            if operator in _SHOW_TEXT_OPS:
                block_text.append(_operand_text(operands))
                block_diagonal = block_diagonal or _is_diagonal(_mat_mul(tm, ctm))
                block_alpha = min(block_alpha, alpha)
            if operator == b"ET":
                norm = _normalise("".join(block_text))
                block_traits = (
                    block_diagonal
                    or plan.hint_diagonal
                    or block_alpha < _OPAQUE
                    or plan.hint_alpha < _OPAQUE
                )
                if plan.user_needle and plan.user_needle in norm:
                    removed += 1
                    user_hits += 1
                elif norm in detection.text_needles and block_traits:
                    removed += 1
                else:
                    kept.extend(block)
                block = None
            continue

        if operator == b"Do":
            xobject = _xobject_named(operands, resources)
            if xobject is not None:
                if plan.strip_layers and _is_watermark_oc(xobject.get("/OC")):
                    removed += 1
                    continue
                if (
                    detection.image_digests
                    and str(xobject.get("/Subtype", "")) == "/Image"
                    and _image_digest(xobject) in detection.image_digests
                ):
                    removed += 1
                    continue
        elif operator == b"INLINE IMAGE" and detection.image_digests:
            digest = _inline_image_digest(operands)
            if digest is not None and digest in detection.image_digests:
                removed += 1
                continue

        kept.append((operands, operator))

    if block is not None:  # unbalanced BT without ET — keep untouched
        kept.extend(block)
    return kept, removed, user_hits


def _serialise(operations: list, writer: PdfWriter) -> bytes:
    stream = ContentStream(None, writer)
    stream.operations = operations
    return stream.get_data()


def _prune_doomed_xobjects(resources, detection: _Detection) -> None:
    """Drop doomed image entries from a resources dict so they GC away."""
    if not detection.image_digests:
        return
    resources = _deref(resources)
    if resources is None:
        return
    xobjects = _deref(resources.get("/XObject"))
    if xobjects is None:
        return
    for name in list(xobjects.keys()):
        try:
            entry = _deref(xobjects.get(name))
            if (
                str(entry.get("/Subtype", "")) == "/Image"
                and _image_digest(entry) in detection.image_digests
            ):
                del xobjects[name]
        except Exception as exc:  # never fail a job over resource cleanup
            logger.warning("watermark_prune_skipped", error=str(exc))
            continue


def _process_form_xobjects(
    resources,
    writer: PdfWriter,
    plan: _RewritePlan,
    visited: set[int],
) -> tuple[int, int]:
    """Filter watermark content inside Form XObjects (recursively).

    Stamping tools frequently draw the watermark inside a Form XObject rather
    than the page stream itself. Streams whose filters pypdf cannot re-encode
    are left untouched (logged, never fatal).
    """
    removed = 0
    user_hits = 0
    resources = _deref(resources)
    if resources is None:
        return 0, 0
    xobjects = _deref(resources.get("/XObject"))
    if xobjects is None:
        return 0, 0

    for reference in xobjects.values():
        xobject = _deref(reference)
        if str(xobject.get("/Subtype", "")) != "/Form" or id(xobject) in visited:
            continue
        visited.add(id(xobject))
        inner_resources = _deref(xobject.get("/Resources"))
        hint_alpha, hint_diagonal = plan.detection.form_hints.get(
            id(xobject), (1.0, False)
        )
        inner_plan = _RewritePlan(
            user_needle=plan.user_needle,
            detection=plan.detection,
            strip_layers=plan.strip_layers,
            hint_alpha=min(plan.hint_alpha, hint_alpha),
            hint_diagonal=plan.hint_diagonal or hint_diagonal,
        )
        try:
            operations = ContentStream(xobject, writer).operations
            kept, dropped, hits = _filter_operations(
                operations, inner_resources, inner_plan
            )
            if dropped:
                xobject.set_data(_serialise(kept, writer))
                removed += dropped
                user_hits += hits
        except Exception as exc:
            logger.warning("watermark_xobject_skipped", error=str(exc))
        _prune_doomed_xobjects(inner_resources, plan.detection)
        nested_removed, nested_hits = _process_form_xobjects(
            inner_resources, writer, inner_plan, visited
        )
        removed += nested_removed
        user_hits += nested_hits
    return removed, user_hits


def _process_page(
    page,
    writer: PdfWriter,
    plan: _RewritePlan,
    visited: set[int],
) -> tuple[int, int]:
    removed = 0
    user_hits = 0
    resources = _deref(page.get("/Resources"))

    contents = page.get_contents()
    if contents is not None:
        stream = ContentStream(contents, writer)
        kept, dropped, hits = _filter_operations(stream.operations, resources, plan)
        if dropped:
            stream.operations = kept
            page.replace_contents(stream)
            removed += dropped
            user_hits += hits

    xobject_removed, xobject_hits = _process_form_xobjects(
        resources, writer, plan, visited
    )
    _prune_doomed_xobjects(resources, plan.detection)
    return removed + xobject_removed, user_hits + xobject_hits


def _strip_watermark_annotations(writer: PdfWriter) -> int:
    removed = 0
    for page in writer.pages:
        annotations = page.get("/Annots")
        if not annotations:
            continue
        kept = ArrayObject()
        for reference in annotations:
            if _looks_like_watermark(reference.get_object()):
                removed += 1
            else:
                kept.append(reference)
        if len(kept) != len(annotations):
            page[NameObject("/Annots")] = kept
    return removed


def _disable_watermark_layers(writer: PdfWriter) -> int:
    """Move watermark-named OCGs to the default config's /OFF list."""
    removed = 0
    oc_properties = writer._root_object.get("/OCProperties")
    if not oc_properties:
        return 0
    oc_properties = oc_properties.get_object()
    groups = oc_properties.get("/OCGs")
    config = oc_properties.get("/D")
    if not groups or config is None:
        return 0
    config = config.get_object()
    marked = [
        ref
        for ref in groups
        if _WATERMARK in str(ref.get_object().get("/Name", "")).lower()
    ]
    if not marked:
        return 0
    off_list = config.get("/OFF")
    off_list = off_list.get_object() if off_list is not None else ArrayObject()
    for reference in marked:
        if reference not in off_list:
            off_list.append(reference)
            removed += 1
    config[NameObject("/OFF")] = off_list
    # Ensure viewers that honour /ON don't re-enable them.
    on_list = config.get("/ON")
    if on_list is not None:
        on_list = on_list.get_object()
        for reference in marked:
            if reference in on_list:
                on_list.remove(reference)
    return removed


def _redact_text_pymupdf(path: Path, text: str) -> int:
    """Fallback text removal via PyMuPDF redactions, in place on ``path``.

    Handles embedded-subset fonts with custom encodings that the
    content-stream matcher cannot decode. Redaction removes every character
    whose box intersects a match, so it only runs when the precise
    content-stream pass found nothing.
    """
    import fitz

    doc = fitz.open(str(path))
    try:
        matches = 0
        kwargs: dict = {"images": fitz.PDF_REDACT_IMAGE_NONE}
        line_art_none = getattr(fitz, "PDF_REDACT_LINE_ART_NONE", None)
        if line_art_none is not None:
            kwargs["graphics"] = line_art_none
        for page in doc:
            quads = page.search_for(text, quads=True)
            if not quads:
                continue
            for quad in quads:
                page.add_redact_annot(quad)
            try:
                page.apply_redactions(**kwargs)
            except TypeError:  # older PyMuPDF without the graphics keyword
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            matches += len(quads)
        if matches:
            data = doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
    if matches:
        path.write_bytes(data)
    return matches


def _garbage_collect(path: Path) -> None:
    """Rewrite ``path`` dropping orphaned objects (best effort)."""
    import fitz

    try:
        doc = fitz.open(str(path))
        try:
            data = doc.tobytes(garbage=3, deflate=True)
        finally:
            doc.close()
        path.write_bytes(data)
    except Exception as exc:
        logger.warning("watermark_gc_skipped", error=str(exc))


def remove_watermarks(
    source: Path,
    destination: Path,
    *,
    mode: str = "both",
    text: str | None = None,
) -> int:
    """Detect and remove every kind of watermark that is technically separable.

    Fully automatic (no input needed):

    * watermark *annotations* (``/Subtype /Watermark`` or watermark-named),
    * content stamped as an ``/Artifact`` with ``/Subtype /Watermark`` —
      how Acrobat-style tools flatten text *and image* watermarks,
    * optional-content *layers* (OCGs) named like a watermark: their
      marked-content blocks and XObject draws are stripped from the content
      and the group is switched off in the viewer configuration,
    * flattened *text* watermarks, detected by their traits — diagonal
      rotation, transparency, tiling, and repetition across pages,
    * flattened *image* watermarks, detected the same way (plus soft masks
      and page coverage); full-page images (scans) are never touched.

    ``text`` additionally force-removes every text block containing it
    (case- and whitespace-insensitive) — a manual override for watermarks
    the heuristics miss. If the content-stream pass cannot decode the
    document's fonts, a PyMuPDF redaction pass takes over for it.

    Watermarks baked into a scanned page's raster image are part of that
    image and cannot be separated.

    Returns how many watermark objects were removed/disabled.
    """
    writer = _clone(source)
    removed = 0
    user_hits = 0
    strip_layers = mode in ("layers", "both")

    detection = _analyse_document(writer) if mode == "both" else _Detection()
    if detection.active:
        logger.info(
            "watermarks_detected",
            texts=len(detection.text_needles),
            images=len(detection.image_digests),
        )

    plan = _RewritePlan(
        user_needle=_normalise(text) if text else None,
        detection=detection,
        strip_layers=strip_layers,
    )

    visited: set[int] = set()
    for page in writer.pages:
        page_removed, page_hits = _process_page(page, writer, plan, visited)
        removed += page_removed
        user_hits += page_hits

    if mode in ("annotations", "both"):
        removed += _strip_watermark_annotations(writer)
    if strip_layers:
        removed += _disable_watermark_layers(writer)

    with destination.open("wb") as handle:
        writer.write(handle)

    if detection.image_digests and removed:
        _garbage_collect(destination)
    if text and user_hits == 0:
        removed += _redact_text_pymupdf(destination, text)
    return removed


def encrypt_pdf(
    source: Path,
    destination: Path,
    *,
    user_password: str,
    owner_password: str | None = None,
    allow_printing: bool = True,
    allow_copying: bool = False,
    allow_modification: bool = False,
) -> None:
    """Encrypt with AES-256 and restrictive default permissions."""
    writer = _clone(source)

    permissions = UserAccessPermissions(0)
    if allow_printing:
        permissions |= (
            UserAccessPermissions.PRINT | UserAccessPermissions.PRINT_TO_REPRESENTATION
        )
    if allow_copying:
        permissions |= UserAccessPermissions.EXTRACT
    if allow_modification:
        permissions |= UserAccessPermissions.MODIFY

    writer.encrypt(
        user_password=user_password,
        owner_password=owner_password or user_password,
        algorithm="AES-256",
        permissions_flag=permissions,
    )
    with destination.open("wb") as handle:
        writer.write(handle)
