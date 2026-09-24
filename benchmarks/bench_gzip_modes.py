"""Performance benchmark for mzML gzip reading modes.

Compares startup cost, iteration time, and random access time across:
- in_memory=True
- a self-indexed copy written by write_indexed_gzip (embedded index)
- gzip_mode="indexed"
- gzip_mode="stream"
- plain .mzML (baseline)

Usage:
    uv run python benchmarks/bench_gzip_modes.py
    uv run python benchmarks/bench_gzip_modes.py --file path/to/large.mzML.gz

Each run copies the input file to a fresh temporary directory so that
benchmark file I/O is isolated and no sidecars from an earlier run are reused.
"""

import argparse
import gc
import gzip
import os
import random
import shutil
import statistics
import tempfile
import time
from contextlib import contextmanager

from mzmlpy import Mzml, write_indexed_gzip


@contextmanager
def timer():
    """Context manager that records elapsed wall-clock time in seconds."""
    gc.collect()
    start = time.perf_counter()
    result = {"elapsed": 0.0}
    yield result
    result["elapsed"] = time.perf_counter() - start


def bench_startup(
    path: str,
    *,
    gzip_mode: str = "auto",
    in_memory: bool = False,
    repeats: int = 3,
) -> list[float]:
    """Measure time to open the file and build the index."""
    times = []
    for _ in range(repeats):
        with timer() as t:
            reader = Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory)
        times.append(t["elapsed"])
        del reader
        gc.collect()
    return times


def bench_iterate(
    path: str,
    *,
    gzip_mode: str = "auto",
    in_memory: bool = False,
    repeats: int = 3,
    max_spectra: int | None = None,
) -> list[float]:
    """Measure time to iterate through spectra after startup."""
    times = []
    for _ in range(repeats):
        reader = Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory)
        with timer() as t:
            for i, s in enumerate(reader.spectra):
                _ = s.id
                if max_spectra is not None and i + 1 >= max_spectra:
                    break
        times.append(t["elapsed"])
        del reader
        gc.collect()
    return times


def bench_random_access(
    path: str,
    *,
    gzip_mode: str = "auto",
    in_memory: bool = False,
    n_accesses: int = 20,
    repeats: int = 3,
) -> list[float]:
    """Measure time for N random spectrum accesses after startup."""
    reader = Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory)
    count = len(reader.spectra)
    del reader
    gc.collect()

    if count == 0:
        return [0.0] * repeats

    indices = [random.randint(0, count - 1) for _ in range(n_accesses)]

    times = []
    for _ in range(repeats):
        reader = Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory)
        with timer() as t:
            for idx in indices:
                s = reader.spectra[idx]
                _ = s.id
        times.append(t["elapsed"])
        del reader
        gc.collect()
    return times


def format_times(times: list[float]) -> str:
    """Format a list of times as 'mean ± stdev (min - max)'."""
    mean = statistics.mean(times)
    if len(times) > 1:
        stdev = statistics.stdev(times)
        return f"{mean:.4f}s ± {stdev:.4f}s  (min={min(times):.4f}s, max={max(times):.4f}s)"
    return f"{mean:.4f}s"


def run_benchmarks(
    gz_path: str,
    mzml_path: str | None,
    repeats: int,
    n_accesses: int,
    max_spectra: int | None = None,
    embedded_path: str | None = None,
) -> None:
    modes: list[dict] = [
        {"label": "plain .mzML", "path": mzml_path, "gzip_mode": "auto", "in_memory": False},
        {"label": "in_memory=True", "path": gz_path, "gzip_mode": "auto", "in_memory": True},
        {
            "label": "embedded index",
            "path": embedded_path,
            "gzip_mode": "auto",
            "in_memory": False,
        },
        {
            "label": 'gzip_mode="indexed"',
            "path": gz_path,
            "gzip_mode": "indexed",
            "in_memory": False,
        },
        {
            "label": 'gzip_mode="stream"',
            "path": gz_path,
            "gzip_mode": "stream",
            "in_memory": False,
        },
    ]

    if mzml_path is None:
        modes = [m for m in modes if m["label"] != "plain .mzML"]
    if embedded_path is None:
        modes = [m for m in modes if m["label"] != "embedded index"]

    # Print file info
    reader = Mzml(gz_path, in_memory=True)
    n_spectra = len(reader.spectra)
    n_chrom = len(reader.chromatograms)
    del reader
    gc.collect()
    print(f"File: {gz_path}")
    print(f"Spectra: {n_spectra}, Chromatograms: {n_chrom}")
    iterate_label = f"Iterate (first {max_spectra})" if max_spectra is not None else "Iterate all"
    print(f"Repeats: {repeats}, Random accesses per repeat: {n_accesses}")
    if max_spectra is not None:
        print(f"Max spectra per iteration: {max_spectra}")
    print()

    col_w = 24
    header = f"{'Mode':<{col_w}} | {'Startup':<42} | {iterate_label:<42} | {'Random access':<42}"
    print(header)
    print("-" * len(header))

    for mode in modes:
        label = mode["label"]
        path = mode["path"]
        kwargs = {
            "gzip_mode": mode["gzip_mode"],
            "in_memory": mode["in_memory"],
        }

        startup_times = bench_startup(path, **kwargs, repeats=repeats)
        iterate_times = bench_iterate(path, **kwargs, repeats=repeats, max_spectra=max_spectra)
        access_times = bench_random_access(path, **kwargs, n_accesses=n_accesses, repeats=repeats)
        access_str = format_times(access_times)

        print(
            f"{label:<{col_w}} | {format_times(startup_times):<42} | {format_times(iterate_times):<42} | {access_str:<42}"
        )

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark mzML gzip reading modes")
    parser.add_argument("--file", default="tests/data/example.mzML.gz", help="Path to .mzML.gz file")
    parser.add_argument("--mzml", default=None, help="Path to uncompressed .mzML file (optional baseline)")
    parser.add_argument("--repeats", type=int, default=3, help="Number of repeats per benchmark")
    parser.add_argument("--accesses", type=int, default=20, help="Number of random accesses per repeat")
    parser.add_argument("--max-spectra", type=int, default=None, help="Max spectra to iterate over (default: all)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Copy the .gz file into the temp dir so benchmark file I/O is isolated.
        gz_basename = os.path.basename(args.file)
        gz_path = os.path.join(tmpdir, gz_basename)
        shutil.copy2(args.file, gz_path)
        print(f"Copied {args.file} → {gz_path}")

        # Extract the plain .mzML baseline in the same temp dir.
        mzml_basename = gz_basename.removesuffix(".gz") if gz_basename.endswith(".gz") else gz_basename
        mzml_path = os.path.join(tmpdir, mzml_basename)
        print(f"Extracting plain .mzML → {mzml_path}")
        with gzip.open(gz_path, "rb") as f_in, open(mzml_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

        # Override --mzml if the user explicitly provided one.
        if args.mzml is not None:
            mzml_path = args.mzml

        # A self-indexed copy for the embedded-index row.
        embedded_path = os.path.join(tmpdir, "embedded." + gz_basename)
        print(f"Writing self-indexed gzip → {embedded_path}")
        write_indexed_gzip(mzml_path, embedded_path)

        print()
        run_benchmarks(gz_path, mzml_path, args.repeats, args.accesses, args.max_spectra, embedded_path)


if __name__ == "__main__":
    main()
