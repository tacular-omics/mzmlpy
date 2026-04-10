"""Performance benchmark: mzmlpy vs pymzml.

Compares startup, iteration (with and without binary data decoding),
metadata access, and random-access performance across both libraries.

Both libraries use their default settings for a fair comparison:
- pymzml: build_index_from_scratch=False (uses embedded index),
  skip_chromatogram=True (default, matches mzmlpy's reader.spectra).
- mzmlpy: default constructor (no in_memory, no gzip_mode override).

Usage:
    uv run python benchmarks/bench_vs_pymzml.py
    uv run python benchmarks/bench_vs_pymzml.py --file path/to/file.mzML
    uv run python benchmarks/bench_vs_pymzml.py --repeats 5 --max-spectra 500

Requires: pip install pymzml
"""

from __future__ import annotations

import argparse
import gc
import random
import statistics
import time
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from mzmlpy import Mzml

PYMZML_AVAILABLE = True
try:
    import pymzml
except ImportError:
    PYMZML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def timer():
    """Context manager that records elapsed wall-clock time in seconds."""
    gc.collect()
    start = time.perf_counter()
    result = {"elapsed": 0.0}
    yield result
    result["elapsed"] = time.perf_counter() - start


def _run(func, repeats: int) -> list[float]:
    """Run *func* ``repeats`` times, return list of elapsed times."""
    times: list[float] = []
    for _ in range(repeats):
        with timer() as t:
            func()
        times.append(t["elapsed"])
        gc.collect()
    return times


def fmt(times: list[float]) -> str:
    """Format a list of times as 'mean ± stdev'."""
    mean = statistics.mean(times)
    if len(times) > 1:
        stdev = statistics.stdev(times)
        return f"{mean:.4f}s ± {stdev:.4f}s"
    return f"{mean:.4f}s"


def ratio_str(mzmlpy_times: list[float], pymzml_times: list[float]) -> str:
    """Return a ratio string like '2.3x faster' or '1.1x slower'."""
    mzmlpy_mean = statistics.mean(mzmlpy_times)
    pymzml_mean = statistics.mean(pymzml_times)
    if mzmlpy_mean == 0 or pymzml_mean == 0:
        return "N/A"
    ratio = pymzml_mean / mzmlpy_mean
    if ratio >= 1.0:
        return f"{ratio:.1f}x faster"
    return f"{1 / ratio:.1f}x slower"


# ---------------------------------------------------------------------------
# Benchmarks — startup (file open + index build only)
# ---------------------------------------------------------------------------

def bench_startup_mzmlpy(path: str) -> None:
    reader = Mzml(path)
    del reader


def bench_startup_pymzml(path: str) -> None:
    run = pymzml.run.Reader(path)
    del run


# ---------------------------------------------------------------------------
# Benchmarks — iteration (reader is pre-opened, timing covers only the loop)
# ---------------------------------------------------------------------------

def bench_iterate_mzmlpy(reader: Mzml, *, max_spectra: int | None, decode: bool) -> None:
    """Iterate spectra from an already-opened reader."""
    for i, s in enumerate(reader.spectra):
        _ = s.id
        _ = s.ms_level
        if decode:
            _ = s.mz
            _ = s.intensity
        if max_spectra is not None and i + 1 >= max_spectra:
            break


def bench_iterate_pymzml(path: str, *, max_spectra: int | None, decode: bool) -> None:
    """pymzml re-opens the file on each iteration (no way to re-seek), so
    Reader creation is included.  This mirrors real-world usage."""
    run = pymzml.run.Reader(path)
    for i, spec in enumerate(run):
        _ = spec.ID
        _ = spec.ms_level
        if decode:
            _ = spec.mz
            _ = spec.i
        if max_spectra is not None and i + 1 >= max_spectra:
            break


# ---------------------------------------------------------------------------
# Benchmarks — metadata access
# ---------------------------------------------------------------------------

def bench_metadata_mzmlpy(reader: Mzml, max_spectra: int | None) -> None:
    """Access common metadata fields per spectrum."""
    for i, s in enumerate(reader.spectra):
        _ = s.id
        _ = s.ms_level
        _ = s.scan_start_time
        _ = s.TIC
        if s.has_precursors:
            for p in s.precursors:
                for ion in p.selected_ions:
                    _ = ion.selected_ion_mz
                    _ = ion.charge_state
        if max_spectra is not None and i + 1 >= max_spectra:
            break


def bench_metadata_pymzml(path: str, max_spectra: int | None) -> None:
    """Access the same metadata fields via pymzml.  Some properties raise on
    certain files, so we guard with try/except (this reflects real-world API
    robustness, not extra overhead — the fast path doesn't enter except)."""
    run = pymzml.run.Reader(path)
    for i, spec in enumerate(run):
        _ = spec.ID
        _ = spec.ms_level
        try:
            _ = spec.scan_time_in_minutes()
        except (AttributeError, TypeError):
            pass
        try:
            _ = spec.TIC
        except (AttributeError, TypeError):
            pass
        try:
            if spec.selected_precursors:
                for p in spec.selected_precursors:
                    _ = p.get("mz")
                    _ = p.get("charge")
        except (AttributeError, TypeError):
            pass
        if max_spectra is not None and i + 1 >= max_spectra:
            break


# ---------------------------------------------------------------------------
# Benchmarks — random access (reader is pre-opened)
# ---------------------------------------------------------------------------

def bench_random_access_mzmlpy(reader: Mzml, indices: list[int]) -> None:
    for idx in indices:
        s = reader.spectra[idx]
        _ = s.mz
        _ = s.intensity


def bench_random_access_pymzml(run: pymzml.run.Reader, ids: list[int]) -> None:
    for sid in ids:
        spec = run[sid]
        _ = spec.mz
        _ = spec.i


# ---------------------------------------------------------------------------
# Accuracy verification
# ---------------------------------------------------------------------------

def verify_accuracy(path: str, max_spectra: int | None) -> None:
    """Verify both libraries produce identical m/z and intensity arrays."""
    mzmlpy_data: list[tuple[int, np.ndarray, np.ndarray]] = []
    with Mzml(path) as reader:
        for i, s in enumerate(reader.spectra):
            mzmlpy_data.append((s.ms_level, s.mz, s.intensity))
            if max_spectra is not None and i + 1 >= max_spectra:
                break

    pymzml_data: list[tuple[int, np.ndarray, np.ndarray]] = []
    run = pymzml.run.Reader(path)
    for i, spec in enumerate(run):
        pymzml_data.append((spec.ms_level, np.array(spec.mz), np.array(spec.i)))
        if max_spectra is not None and i + 1 >= max_spectra:
            break

    assert len(mzmlpy_data) == len(pymzml_data), (
        f"Spectrum count mismatch: mzmlpy={len(mzmlpy_data)}, pymzml={len(pymzml_data)}"
    )
    mismatches = 0
    for idx, ((ml, mmz, mi), (pl, pmz, pi)) in enumerate(zip(mzmlpy_data, pymzml_data, strict=True)):
        if ml != pl:
            print(f"  WARNING: spectrum {idx} ms_level mismatch: mzmlpy={ml}, pymzml={pl}")
            mismatches += 1
            continue
        if len(mmz) != len(pmz):
            print(f"  WARNING: spectrum {idx} peak count mismatch: mzmlpy={len(mmz)}, pymzml={len(pmz)}")
            mismatches += 1
            continue
        if len(mmz) > 0 and not np.allclose(mmz, pmz, atol=1e-6):
            max_diff = np.max(np.abs(mmz - pmz))
            print(f"  WARNING: spectrum {idx} m/z arrays differ (max diff={max_diff:.2e})")
            mismatches += 1
        if len(mi) > 0 and not np.allclose(mi, pi, atol=1e-2):
            max_diff = np.max(np.abs(mi - pi))
            print(f"  WARNING: spectrum {idx} intensity arrays differ (max diff={max_diff:.2e})")
            mismatches += 1

    if mismatches == 0:
        print("  All arrays match within tolerance.")
    else:
        print(f"  {mismatches} mismatches found.")


# ---------------------------------------------------------------------------
# Warmup
# ---------------------------------------------------------------------------

def warmup(path: str) -> None:
    """Prime both libraries so one-time costs (OBO loading, JIT warmup, OS
    page-cache population) don't skew the timed benchmarks."""
    # mzmlpy
    with Mzml(path) as reader:
        for s in reader.spectra:
            _ = s.mz
            _ = s.intensity
            break

    # pymzml — triggers OBO ontology loading (cached globally after first call)
    run = pymzml.run.Reader(path)
    for spec in run:
        _ = spec.ms_level
        _ = spec.mz
        _ = spec.i
        break

    gc.collect()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_benchmarks(path: str, repeats: int, max_spectra: int | None, n_accesses: int) -> None:
    if not PYMZML_AVAILABLE:
        print("ERROR: pymzml is not installed. Install with: pip install pymzml")
        return

    # Suppress noisy warnings during benchmarks (e.g. empty binary arrays).
    warnings.filterwarnings("ignore")

    file_name = Path(path).name

    # Gather file stats via mzmlpy
    with Mzml(path) as reader:
        n_spectra = len(reader.spectra)
        n_chrom = len(reader.chromatograms)
        # Collect scan IDs for random access
        scan_ids_pymzml: list[int] = []
        scan_indices: list[int] = []
        for i, s in enumerate(reader.spectra):
            scan_indices.append(i)
            # pymzml uses numeric IDs parsed from the nativeID
            try:
                scan_ids_pymzml.append(int(s.id.split("=")[-1]))
            except (ValueError, AttributeError):
                pass

    # Pick random access targets
    random.seed(42)
    if len(scan_indices) >= n_accesses:
        access_indices = random.sample(scan_indices, n_accesses)
    else:
        access_indices = scan_indices
    if len(scan_ids_pymzml) >= n_accesses:
        access_ids = [scan_ids_pymzml[i] for i in access_indices]
    else:
        access_ids = scan_ids_pymzml

    # Verify pymzml random access actually works for this file by testing
    # every selected ID.  Keep only IDs that pymzml can resolve, and trim
    # access_indices to match so both libraries access the same spectra.
    pymzml_random_ok = False
    if access_ids:
        run = pymzml.run.Reader(path)
        valid_pairs: list[tuple[int, int]] = []
        for idx, sid in zip(access_indices, access_ids, strict=True):
            try:
                _ = run[sid]
                valid_pairs.append((idx, sid))
            except Exception:
                pass
        if valid_pairs:
            access_indices = [p[0] for p in valid_pairs]
            access_ids = [p[1] for p in valid_pairs]
            pymzml_random_ok = True
        del run

    iterate_n = min(max_spectra, n_spectra) if max_spectra else n_spectra

    print("=" * 80)
    print("mzmlpy vs pymzml — Performance Benchmark")
    print("=" * 80)
    print(f"File:            {file_name}")
    print(f"Spectra:         {n_spectra}")
    print(f"Chromatograms:   {n_chrom}")
    print(f"Iterate:         {iterate_n} spectra")
    print(f"Random accesses: {len(access_indices)}")
    print(f"Repeats:         {repeats}")
    print()

    # Verify accuracy first
    print("Verifying data accuracy between libraries...")
    verify_accuracy(path, max_spectra)
    print()

    # Warm up both libraries (OBO loading, page cache, etc.)
    print("Warming up...")
    warmup(path)
    print()

    # Results table
    col_time = 24
    col_ratio = 16

    header = f"{'Benchmark':<24} | {'mzmlpy':<{col_time}} | {'pymzml':<{col_time}} | {'mzmlpy vs pymzml':<{col_ratio}}"
    print(header)
    print("-" * len(header))

    results: list[tuple[str, list[float], list[float]]] = []

    # 1. Startup — measures file open + index build only
    t_mzmlpy = _run(lambda: bench_startup_mzmlpy(path), repeats)
    t_pymzml = _run(lambda: bench_startup_pymzml(path), repeats)
    results.append(("Startup", t_mzmlpy, t_pymzml))

    # 2. Iterate (no decode) — open file, iterate spectra, access ID + ms_level
    #    mzmlpy: reader supports re-iteration over spectra from a single open.
    #    pymzml: Reader must be re-created per iteration (no re-seek support),
    #    so Reader creation is included.  This reflects real-world usage for both.
    def _iter_no_decode_mzmlpy():
        with Mzml(path) as r:
            bench_iterate_mzmlpy(r, max_spectra=max_spectra, decode=False)

    t_mzmlpy = _run(_iter_no_decode_mzmlpy, repeats)
    t_pymzml = _run(lambda: bench_iterate_pymzml(path, max_spectra=max_spectra, decode=False), repeats)
    results.append(("Iterate (no decode)", t_mzmlpy, t_pymzml))

    # 3. Iterate (decode) — same but also decode m/z + intensity arrays
    def _iter_decode_mzmlpy():
        with Mzml(path) as r:
            bench_iterate_mzmlpy(r, max_spectra=max_spectra, decode=True)

    t_mzmlpy = _run(_iter_decode_mzmlpy, repeats)
    t_pymzml = _run(lambda: bench_iterate_pymzml(path, max_spectra=max_spectra, decode=True), repeats)
    results.append(("Iterate (decode)", t_mzmlpy, t_pymzml))

    # 4. Metadata — access all common metadata fields per spectrum
    def _meta_mzmlpy():
        with Mzml(path) as r:
            bench_metadata_mzmlpy(r, max_spectra)

    t_mzmlpy = _run(_meta_mzmlpy, repeats)
    t_pymzml = _run(lambda: bench_metadata_pymzml(path, max_spectra), repeats)
    results.append(("Metadata", t_mzmlpy, t_pymzml))

    # 5. Random access — seek to N random spectra and decode arrays.
    #    Both libraries use their indexed random-access path:
    #    mzmlpy: reader.spectra[index] (positional offset lookup)
    #    pymzml: run[scan_id] (ID-based offset lookup)
    if access_indices and access_ids and pymzml_random_ok:
        def _ra_mzmlpy():
            with Mzml(path) as r:
                bench_random_access_mzmlpy(r, access_indices)

        def _ra_pymzml():
            run = pymzml.run.Reader(path)
            bench_random_access_pymzml(run, access_ids)

        t_mzmlpy = _run(_ra_mzmlpy, repeats)
        t_pymzml = _run(_ra_pymzml, repeats)
        results.append(("Random access", t_mzmlpy, t_pymzml))
    elif access_indices:
        def _ra_mzmlpy_only():
            with Mzml(path) as r:
                bench_random_access_mzmlpy(r, access_indices)

        t_mzmlpy = _run(_ra_mzmlpy_only, repeats)
        results.append(("Random access", t_mzmlpy, []))
    else:
        results.append(("Random access", [], []))

    for label, t_mzmlpy, t_pymzml in results:
        m_str = fmt(t_mzmlpy) if t_mzmlpy else "N/A"
        p_str = fmt(t_pymzml) if t_pymzml else "N/A (unsupported)"
        r_str = ratio_str(t_mzmlpy, t_pymzml) if t_mzmlpy and t_pymzml else "—"
        print(f"{label:<24} | {m_str:<{col_time}} | {p_str:<{col_time}} | {r_str}")

    print()
    print("Note: 'N.Nx faster' means mzmlpy is N.N times faster than pymzml.")
    print("      'N.Nx slower' means mzmlpy is N.N times slower than pymzml.")
    if not pymzml_random_ok and access_ids:
        print(f"      pymzml random access failed for this file (scan IDs {access_ids[:3]}...).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark mzmlpy vs pymzml")
    parser.add_argument(
        "--file",
        default="tests/data/zlib_20250806_ArgC_DDA_HCD-FT_01.mzML",
        help="Path to .mzML file (default: tests/data/zlib_20250806_ArgC_DDA_HCD-FT_01.mzML)",
    )
    parser.add_argument("--repeats", type=int, default=5, help="Number of repeats per benchmark (default: 5)")
    parser.add_argument("--max-spectra", type=int, default=None, help="Max spectra to iterate (default: all)")
    parser.add_argument("--accesses", type=int, default=10, help="Number of random accesses (default: 10)")
    args = parser.parse_args()

    run_benchmarks(args.file, args.repeats, args.max_spectra, args.accesses)


if __name__ == "__main__":
    main()
