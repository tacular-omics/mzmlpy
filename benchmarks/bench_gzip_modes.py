"""Performance benchmark for mzML gzip reading modes.

Compares startup cost, iteration time, and random access time across:
- in_memory=True (default)
- gzip_mode="extract"
- gzip_mode="indexed"
- gzip_mode="stream"
- plain .mzML (baseline)

Usage:
    uv run python benchmarks/bench_gzip_modes.py
    uv run python benchmarks/bench_gzip_modes.py --file path/to/large.mzML.gz
"""

import argparse
import gc
import random
import statistics
import time
from contextlib import contextmanager

from mzmlpy import Mzml


@contextmanager
def timer():
    """Context manager that records elapsed wall-clock time in seconds."""
    gc.collect()
    start = time.perf_counter()
    result = {"elapsed": 0.0}
    yield result
    result["elapsed"] = time.perf_counter() - start


def bench_startup(path: str, *, gzip_mode: str = "extract", in_memory: bool = False, repeats: int = 3) -> list[float]:
    """Measure time to open the file and build the index."""
    times = []
    for _ in range(repeats):
        with timer() as t:
            reader = Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory)
        times.append(t["elapsed"])
        del reader
        gc.collect()
    return times


def bench_iterate(path: str, *, gzip_mode: str = "extract", in_memory: bool = False, repeats: int = 3) -> list[float]:
    """Measure time to iterate through all spectra after startup."""
    times = []
    for _ in range(repeats):
        reader = Mzml(path, gzip_mode=gzip_mode, in_memory=in_memory)
        with timer() as t:
            for s in reader.spectra:
                _ = s.id
        times.append(t["elapsed"])
        del reader
        gc.collect()
    return times


def bench_random_access(
    path: str, *, gzip_mode: str = "extract", in_memory: bool = False, n_accesses: int = 20, repeats: int = 3
) -> list[float]:
    """Measure time for N random spectrum accesses after startup."""
    # First, get the spectrum count
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


def run_benchmarks(gz_path: str, mzml_path: str | None, repeats: int, n_accesses: int) -> None:
    modes: list[dict] = [
        {"label": "plain .mzML", "path": mzml_path, "gzip_mode": "extract", "in_memory": False},
        {"label": "in_memory=True", "path": gz_path, "gzip_mode": "extract", "in_memory": True},
        {"label": 'gzip_mode="extract"', "path": gz_path, "gzip_mode": "extract", "in_memory": False},
        {"label": 'gzip_mode="indexed"', "path": gz_path, "gzip_mode": "indexed", "in_memory": False},
        {"label": 'gzip_mode="stream"', "path": gz_path, "gzip_mode": "stream", "in_memory": False},
    ]

    if mzml_path is None:
        modes = [m for m in modes if m["label"] != "plain .mzML"]

    # Print file info
    reader = Mzml(gz_path, in_memory=True)
    n_spectra = len(reader.spectra)
    n_chrom = len(reader.chromatograms)
    del reader
    gc.collect()
    print(f"File: {gz_path}")
    print(f"Spectra: {n_spectra}, Chromatograms: {n_chrom}")
    print(f"Repeats: {repeats}, Random accesses per repeat: {n_accesses}")
    print()

    col_w = 24
    header = f"{'Mode':<{col_w}} | {'Startup':<42} | {'Iterate all':<42} | {'Random access':<42}"
    print(header)
    print("-" * len(header))

    for mode in modes:
        label = mode["label"]
        path = mode["path"]
        kwargs = {"gzip_mode": mode["gzip_mode"], "in_memory": mode["in_memory"]}

        # Startup
        startup_times = bench_startup(path, **kwargs, repeats=repeats)

        # Iteration
        iterate_times = bench_iterate(path, **kwargs, repeats=repeats)

        # Random access (skip for stream mode — it doesn't support indexing)
        if mode["gzip_mode"] == "stream" and not mode["in_memory"]:
            access_str = "N/A (no index)"
        else:
            access_times = bench_random_access(path, **kwargs, n_accesses=n_accesses, repeats=repeats)
            access_str = format_times(access_times)

        print(f"{label:<{col_w}} | {format_times(startup_times):<42} | {format_times(iterate_times):<42} | {access_str:<42}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark mzML gzip reading modes")
    parser.add_argument("--file", default="tests/data/example.mzML.gz", help="Path to .mzML.gz file")
    parser.add_argument("--mzml", default=None, help="Path to uncompressed .mzML file (optional baseline)")
    parser.add_argument("--repeats", type=int, default=3, help="Number of repeats per benchmark")
    parser.add_argument("--accesses", type=int, default=20, help="Number of random accesses per repeat")
    args = parser.parse_args()

    # Auto-detect .mzML path
    mzml_path = args.mzml
    if mzml_path is None and args.file.endswith(".gz"):
        candidate = args.file.removesuffix(".gz")
        import os

        if os.path.exists(candidate):
            mzml_path = candidate

    run_benchmarks(args.file, mzml_path, args.repeats, args.accesses)


if __name__ == "__main__":
    main()
