"""Benchmark the Convert-to-PDF tools' core conversion functions.

Times the *engine* layer (below the job/DB/HTTP machinery) so the numbers
isolate conversion cost. Two groups:

* **Images (JPG/PNG -> PDF).** Fully self-contained: synthesises sample images
  and times :func:`app.utils.images.images_to_pdf` for albums of several
  sizes. Also reports the parallel-vs-serial preprocessing speedup and peak
  memory, so the effect of the parallel/streaming change is measurable here
  without any external binary.

* **Office (Word/Excel/PowerPoint -> PDF).** Requires a configured
  ``SOFFICE_BIN`` (see backend/.env) and real sample documents. Point it at a
  folder of .docx/.xlsx/.pptx files with ``--office-samples DIR``; each file is
  converted ``--repeats`` times via :func:`app.utils.office.libreoffice_convert`
  (warm-profile pool), reporting min/median/mean. Skipped with a message when
  no binary or samples are available.

Usage (from backend/, with the venv active)::

    python -m scripts.benchmark_convert
    python -m scripts.benchmark_convert --repeats 7 --office-samples ./samples
    python -m scripts.benchmark_convert --image-sizes 800x600,3000x2000

The script mutates nothing in the app; all work happens in a temp dir.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

# Allow ``python scripts/benchmark_convert.py`` as well as ``-m``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("APP_ENV", "development")

from PIL import Image  # noqa: E402

from app.utils.images import _normalise, images_to_pdf  # noqa: E402


def _fmt_ms(values: list[float]) -> str:
    ms = [v * 1000 for v in values]
    return (
        f"min={min(ms):8.1f}  median={statistics.median(ms):8.1f}  "
        f"mean={statistics.fmean(ms):8.1f}  (n={len(ms)})"
    )


def _time(fn, repeats: int) -> list[float]:
    """Run ``fn`` ``repeats`` times, returning per-run wall times (seconds)."""
    times: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return times


# ─── Sample generation ───────────────────────────────────────────────────────


def _make_jpg(path: Path, size: tuple[int, int]) -> None:
    width, height = size
    image = Image.new("RGB", size)
    # A non-uniform gradient so JPEG has real content to encode.
    pixels = image.load()
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            colour = ((x * 255) // width, (y * 255) // height, 128)
            for dy in range(4):
                for dx in range(4):
                    if x + dx < width and y + dy < height:
                        pixels[x + dx, y + dy] = colour
    image.save(path, format="JPEG", quality=85)


def _make_png_alpha(path: Path, size: tuple[int, int]) -> None:
    # RGBA forces the flatten-and-re-encode path in _normalise (the expensive,
    # now-parallelised case).
    image = Image.new("RGBA", size, (200, 120, 60, 180))
    image.save(path, format="PNG")


# ─── Image benchmark ─────────────────────────────────────────────────────────


def bench_images(
    scratch: Path,
    *,
    sizes: list[tuple[int, int]],
    batches: list[int],
    repeats: int,
) -> None:
    print("\n=== Images -> PDF (img2pdf) ===")
    for size in sizes:
        dims = f"{size[0]}x{size[1]}"
        jpg = scratch / f"sample-{dims}.jpg"
        png = scratch / f"sample-alpha-{dims}.png"
        _make_jpg(jpg, size)
        _make_png_alpha(png, size)

        for label, src in (("JPG (passthrough)", jpg), ("PNG+alpha (re-encode)", png)):
            print(f"\n  {label}  @ {dims}")
            for count in batches:
                paths = [src] * count
                out = scratch / "out.pdf"

                full = _time(
                    lambda p=paths, o=out: images_to_pdf(list(p), o), repeats
                )
                print(f"    album x{count:<3d} full   : {_fmt_ms(full)}")

                # Isolate preprocessing: parallel (current) vs forced serial.
                par = _time(
                    lambda p=paths: [None for _ in _parallel_norm(p)], repeats
                )
                ser = _time(
                    lambda p=paths: [_normalise(x) for x in p], repeats
                )
                speedup = statistics.median(ser) / max(statistics.median(par), 1e-9)
                print(
                    f"                preproc: parallel median="
                    f"{statistics.median(par) * 1000:8.1f}ms  "
                    f"serial median={statistics.median(ser) * 1000:8.1f}ms  "
                    f"speedup={speedup:4.2f}x"
                )

        # Peak memory of the largest album (streamed output vs. the old
        # build-bytes-then-write approach).
        big = [png] * max(batches)
        out = scratch / "out-mem.pdf"
        tracemalloc.start()
        images_to_pdf(list(big), out)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"\n    peak python heap, album x{len(big)} @ {dims}: {peak/1e6:6.1f} MB")


def _parallel_norm(paths: list[Path]) -> list[bytes]:
    from app.utils.images import _normalise_all

    return _normalise_all(list(paths))


# ─── Office benchmark ────────────────────────────────────────────────────────


def bench_office(scratch: Path, samples_dir: Path | None, repeats: int) -> None:
    print("\n=== Office -> PDF (LibreOffice) ===")
    from app.config import get_settings
    from app.utils.command import split_launcher
    from app.utils.office import libreoffice_convert, office_engine

    settings = get_settings()
    launcher = split_launcher(settings.SOFFICE_BIN)[0]
    resolved = Path(launcher).is_file() or __import__("shutil").which(launcher)
    if not resolved:
        print(f"  SKIPPED: SOFFICE_BIN ({settings.SOFFICE_BIN!r}) not found.")
        return
    if samples_dir is None:
        print(
            "  SKIPPED: pass --office-samples DIR with real .docx/.xlsx/.pptx "
            "files to benchmark office conversion."
        )
        return

    exts = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
    files = sorted(p for p in samples_dir.iterdir() if p.suffix.lower() in exts)
    if not files:
        print(f"  SKIPPED: no office documents in {samples_dir}.")
        return

    print(f"  engine={office_engine()}  (first run pays warm-up; ignore it)")
    for src in files:
        out_dir = scratch / f"office-{src.stem}"
        out_dir.mkdir(exist_ok=True)

        def run(s=src, d=out_dir) -> None:
            for existing in d.glob("*"):
                existing.unlink()
            libreoffice_convert(s, d, display_name=s.name)

        times = _time(run, repeats + 1)[1:]  # drop the cold first run
        size_kb = src.stat().st_size / 1024
        print(f"  {src.name:<40s} ({size_kb:7.1f} KB): {_fmt_ms(times)}")


# ─── Entry point ─────────────────────────────────────────────────────────────


def _parse_sizes(raw: str) -> list[tuple[int, int]]:
    sizes: list[tuple[int, int]] = []
    for token in raw.split(","):
        width, height = token.lower().split("x")
        sizes.append((int(width), int(height)))
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--image-sizes",
        default="1200x900,3000x2000",
        help="Comma-separated WxH image dimensions to benchmark.",
    )
    parser.add_argument(
        "--image-batches",
        default="1,5,20",
        help="Comma-separated album sizes (image counts) to benchmark.",
    )
    parser.add_argument(
        "--office-samples",
        type=Path,
        default=None,
        help="Directory of real office documents to benchmark (optional).",
    )
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--skip-office", action="store_true")
    args = parser.parse_args()

    sizes = _parse_sizes(args.image_sizes)
    batches = [int(x) for x in args.image_batches.split(",")]

    print(f"CPU cores: {os.cpu_count()}   repeats: {args.repeats}")
    with tempfile.TemporaryDirectory(prefix="convert-bench-") as tmp:
        scratch = Path(tmp)
        if not args.skip_images:
            bench_images(scratch, sizes=sizes, batches=batches, repeats=args.repeats)
        if not args.skip_office:
            bench_office(scratch, args.office_samples, args.repeats)
    print("\nDone.")


if __name__ == "__main__":
    main()
