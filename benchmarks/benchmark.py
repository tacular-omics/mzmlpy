#!/usr/bin/env python
"""Reproducible benchmark: mzmlpy vs pyteomics vs pymzml.

Three benchmark groups:

1. **Format support / correctness** — runs against the small re-encoded corpus in
   ``tests/data/`` (committed, so this group runs anywhere). Verifies each library
   decodes zlib, zstd, and MS-Numpress arrays to the same peak count and intensity sum.

2. **Throughput** — open/index, full decode, and random access on a large *plain*
   ``.mzML`` file (supply with ``--plain``; not committed — see README).

3. **Gzip handling** — the same large file gzipped (supply with ``--gz``), comparing
   mzmlpy's ``extract`` / ``indexed`` / ``stream`` modes against the competitors.

Competitors are optional. Install them alongside mzmlpy, e.g.:

    uv run --with pyteomics --with pymzml --with psims --with lxml \\
           --with pynumpress --with rapidgzip benchmarks/benchmark.py --plain FILE --gz FILE

Any library that is not importable is reported as ``not installed`` and skipped.
"""

from __future__ import annotations

import argparse
import gc
import gzip
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "tests" / "data"


def purge_mzmlpy_caches(gz: Path) -> None:
    """Remove *all* mzmlpy on-disk caches so a 'cold start' is genuinely cold.

    ``clear_cache()`` only clears the tmp extract directory; the ``indexed`` mode also writes
    ``.gzidx`` / ``.mzidx`` seek/offset indices (and their ``.src`` signature sidecars) next to the
    ``.gz`` file, which would otherwise make a re-run's "cold" startup actually warm.
    """
    from mzmlpy import clear_cache

    clear_cache()
    p = str(gz)
    sidecars = [p + "idx", p.removesuffix(".gz") + "idx"]  # X.mzML.gzidx, X.mzMLidx
    for base in list(sidecars):
        sidecars.append(base + ".src")
    for sidecar in sidecars:
        try:
            os.remove(sidecar)
        except FileNotFoundError:
            pass

# The re-encoded corpus: same spectra, different binary encodings. Reference sum is
# the lossless zlib value; numpress-slof is lossy and only expected to match closely.
CORPUS = {
    "zlib": "zlib_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "zstd": "zstd_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "numpress-linear": "numpresslinear_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "numpress-slof": "numpressslof_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "numpress-pic": "numpresspic_20250806_ArgC_DDA_HCD-FT_01.mzML",
}


# --------------------------------------------------------------------------- timing
def best_of(fn: Callable[[], Any], repeats: int) -> tuple[float | None, Any]:
    """Return (min wall-clock seconds, last result) or (None, error-string) on failure."""
    best: float | None = None
    out: Any = None
    for _ in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 - benchmark harness reports, never crashes
            return None, f"ERR {type(exc).__name__}: {str(exc)[:60]}"
        dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
    return best, out


def available(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


# --------------------------------------------------------------- decode workloads
def _summ(pairs) -> tuple[int, float]:
    """Fold an iterator of (mz, intensity) arrays into (total peaks, total intensity)."""
    n = 0
    tot = 0.0
    for mz, it in pairs:
        if mz is not None and it is not None and len(mz):
            n += len(mz)
            tot += float(np.asarray(it).sum())
    return n, round(tot, 1)


def _random_order(n: int) -> list[int]:
    """Non-monotonic spread of indices — deliberately jumps around so a sequential-only
    reader (mzmlpy ``stream`` mode) cannot satisfy the reads by reading forward."""
    return [i for i in (n - 1, 0, n // 2, n - 3, 5, (3 * n) // 4, 1, n // 3) if 0 <= i < n]


def mzmlpy_decode(path: str, gzip_mode: str = "extract", in_memory: bool = True) -> tuple[int, float]:
    from mzmlpy import Mzml

    with Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory) as r:
        return _summ((s.mz, s.intensity) for s in r.spectra)


def mzmlpy_index(path: str, gzip_mode: str = "extract", in_memory: bool = True) -> int:
    from mzmlpy import Mzml

    with Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory) as r:
        return len(r.spectra)


def mzmlpy_random(path: str, gzip_mode: str = "extract", in_memory: bool = True) -> int:
    from mzmlpy import Mzml

    with Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory) as r:
        c = 0
        for i in _random_order(len(r.spectra)):
            mz = r.spectra[i].mz
            c += 0 if mz is None else len(mz)
        return c


def pyteomics_decode(path: str, gz: bool = False) -> tuple[int, float]:
    from pyteomics import mzml as pmz

    src = gzip.open(path, "rb") if gz else path
    with pmz.read(src) as r:
        return _summ((s.get("m/z array"), s.get("intensity array")) for s in r)


def pyteomics_index(path: str) -> int:
    from pyteomics import mzml as pmz

    with pmz.MzML(path) as r:
        return len(r.index["spectrum"])


def pyteomics_random(path: str) -> int:
    from pyteomics import mzml as pmz

    with pmz.MzML(path) as r:
        ids = list(r.index["spectrum"].keys())
        c = 0
        for i in _random_order(len(ids)):
            mz = r.get_by_id(ids[i]).get("m/z array")
            c += 0 if mz is None else len(mz)
        return c


def pymzml_decode(path: str) -> tuple[int, float]:
    import pymzml

    def pairs(run):
        for s in run:
            try:
                yield s.mz, s.i
            except Exception:  # noqa: BLE001 - pymzml raises on non-peak spectra
                yield None, None

    return _summ(pairs(pymzml.run.Reader(path)))


def pymzml_index(path: str) -> int:
    import pymzml

    run = pymzml.run.Reader(path)
    return run.get_spectrum_count()


def pymzml_random(path: str) -> int:
    # pymzml supports indexed random access via run[native_id] (native_id is the integer scan
    # number for typical vendor ids, read from the file's built-in index or rebuilt from scratch).
    import pymzml

    run = pymzml.run.Reader(path)
    ids = sorted(k for k in run.info["file_object"].offset_dict if isinstance(k, int))
    c = 0
    for i in _random_order(len(ids)):
        mz = run[ids[i]].mz
        c += 0 if mz is None else len(mz)
    return c


# --------------------------------------------------------------------- table render
def fmt_secs(dt: float | None, payload: Any) -> str:
    if dt is None:
        return str(payload)
    return f"{dt:.3f}s"


def print_table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    print(f"\n### {title}\n")
    widths = [max(len(columns[i]), *(len(r[i]) for r in rows)) for i in range(len(columns))]
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
    sep = " | ".join("-" * widths[i] for i in range(len(columns)))
    print(f"| {header} |")
    print(f"| {sep} |")
    for r in rows:
        print("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(columns))) + " |")


# ------------------------------------------------------------------------- groups
def group_format_support(corpus_dir: Path, libs: set[str], repeats: int) -> None:
    rows = []
    for label, fname in CORPUS.items():
        path = corpus_dir / fname
        if not path.exists():
            continue
        cells = [label]
        for lib, fn in (
            ("mzmlpy", lambda p=path: mzmlpy_decode(str(p))),
            ("pyteomics", lambda p=path: pyteomics_decode(str(p))),
            ("pymzml", lambda p=path: pymzml_decode(str(p))),
        ):
            if lib not in libs:
                cells.append("n/a")
                continue
            _, out = best_of(fn, repeats=1)  # correctness, not speed — one pass
            if isinstance(out, tuple):
                peaks, isum = out
                cells.append(f"OK {peaks:,}p / {isum:,.0f}")
            else:
                cells.append("FAIL" if out.startswith("ERR") else str(out))
        rows.append(cells)
    if rows:
        print_table(
            "Format support & correctness (tests/data corpus)", ["encoding", "mzmlpy", "pyteomics", "pymzml"], rows
        )


def group_throughput(plain: Path, libs: set[str], repeats: int) -> None:
    size_mb = plain.stat().st_size / 1048576
    ops = [
        (
            "index + count",
            {
                "mzmlpy": lambda: mzmlpy_index(str(plain)),
                "pyteomics": lambda: pyteomics_index(str(plain)),
                "pymzml": lambda: pymzml_index(str(plain)),
            },
        ),
        (
            "full decode",
            {
                "mzmlpy": lambda: mzmlpy_decode(str(plain)),
                "pyteomics": lambda: pyteomics_decode(str(plain)),
                "pymzml": lambda: pymzml_decode(str(plain)),
            },
        ),
        (
            f"random {len(_random_order(999))} reads",
            {
                "mzmlpy": lambda: mzmlpy_random(str(plain)),
                "pyteomics": lambda: pyteomics_random(str(plain)),
                "pymzml": lambda: pymzml_random(str(plain)),
            },
        ),
    ]
    rows = []
    for op_name, fns in ops:
        cells = [op_name]
        for lib in ("mzmlpy", "pyteomics", "pymzml"):
            fn = fns.get(lib)
            if fn is None:
                cells.append("n/a")
            elif lib not in libs:
                cells.append("not installed")
            else:
                dt, payload = best_of(fn, repeats)
                cells.append(fmt_secs(dt, payload))
        rows.append(cells)
    print_table(
        f"Throughput — {plain.name} ({size_mb:.1f} MB, plain)", ["operation", "mzmlpy", "pyteomics", "pymzml"], rows
    )


def group_gzip(gz: Path, libs: set[str], repeats: int) -> None:
    size_mb = gz.stat().st_size / 1048576

    # The three modes differ on *startup* (extract decompresses; indexed builds a seek index)
    # and *random access* (stream must rescan from the top), not on full sequential decode.
    # These differences only appear with in_memory=False: the default in_memory=True buffers the
    # whole file in RAM after open, so all three modes then behave identically. We benchmark the
    # memory-constrained case, which is the only one where the mode choice actually matters.
    mode_rows = []
    for mode in ("extract", "indexed", "stream"):
        purge_mzmlpy_caches(gz)  # genuinely cold: also removes gzidx/mzidx sidecars, not just tmp
        startup, _ = best_of(lambda m=mode: mzmlpy_index(str(gz), gzip_mode=m, in_memory=False), repeats=1)
        rnd, _ = best_of(lambda m=mode: mzmlpy_random(str(gz), gzip_mode=m, in_memory=False), repeats=1)
        dec, out = best_of(lambda m=mode: mzmlpy_decode(str(gz), gzip_mode=m, in_memory=False), repeats=1)
        mode_rows.append([mode, fmt_secs(startup, None), fmt_secs(rnd, None), fmt_secs(dec, out)])
    print_table(
        f"mzmlpy gzip modes — {gz.name} ({size_mb:.1f} MB), in_memory=False, cold start",
        ["mode", "startup (open+index)", f"random {len(_random_order(999))} reads", "full decode"],
        mode_rows,
    )

    # Competitors have no mode selection: pymzml auto-reads .gz; pyteomics cannot and needs a
    # manual gzip.open() wrapper (which also forfeits random-access indexing).
    comp_rows = []
    if "pymzml" in libs:
        dt, out = best_of(lambda: pymzml_decode(str(gz)), repeats=1)
        comp_rows.append(["pymzml (auto .gz)", fmt_secs(dt, out)])
    if "pyteomics" in libs:
        dt_auto, out_auto = best_of(lambda: pyteomics_decode(str(gz), gz=False), repeats=1)
        comp_rows.append(["pyteomics (path, auto)", fmt_secs(dt_auto, out_auto)])
        dt_man, out_man = best_of(lambda: pyteomics_decode(str(gz), gz=True), repeats=1)
        comp_rows.append(["pyteomics (manual gzip.open)", fmt_secs(dt_man, out_man)])
    if comp_rows:
        print_table(f"Competitor .gz full decode — {gz.name}", ["reader", "full decode"], comp_rows)


# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--corpus-dir", type=Path, default=DEFAULT_CORPUS, help="dir with the re-encoded corpus (default: tests/data)"
    )
    ap.add_argument("--plain", type=Path, help="large plain .mzML for the throughput group")
    ap.add_argument("--gz", type=Path, help="large .mzML.gz for the gzip group")
    ap.add_argument("--repeats", type=int, default=3, help="timing repeats (min is reported)")
    args = ap.parse_args()

    competitors = {name for name in ("pyteomics", "pymzml") if available(name)}
    libs = {"mzmlpy"} | competitors
    print("mzmlpy benchmark")
    print(f"  competitors detected: {', '.join(sorted(competitors)) or 'none'}")
    for name in ("pyteomics", "pymzml"):
        if name not in libs:
            print(f"  ({name} not installed — its columns will be skipped)")
    print(f"  repeats (min reported): {args.repeats}")

    group_format_support(args.corpus_dir, libs, args.repeats)
    if args.plain and args.plain.exists():
        group_throughput(args.plain, libs, args.repeats)
    elif args.plain:
        print(f"\n[skip] throughput: {args.plain} not found")
    if args.gz and args.gz.exists():
        group_gzip(args.gz, libs, args.repeats)
    elif args.gz:
        print(f"\n[skip] gzip: {args.gz} not found")


if __name__ == "__main__":
    main()
