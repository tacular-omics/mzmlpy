# Benchmarks

Reproducible comparison of **mzmlpy** against the two established Python mzML readers,
[**pyteomics**](https://github.com/levitsky/pyteomics) and [**pymzml**](https://github.com/pymzml/pymzML),
across three axes: compression-format support, throughput on a large plain file, and gzip handling.

## Running

The competitors are optional dependencies, kept out of mzmlpy's runtime deps. Install them
just for the benchmark. With `uv`:

```bash
uv run --with pyteomics --with pymzml --with psims --with lxml \
       --with pynumpress --with rapidgzip \
       python benchmarks/benchmark.py --plain path/to/large.mzML --gz path/to/large.mzML.gz
```

or in a plain venv:

```bash
pip install pyteomics pymzml psims lxml pynumpress rapidgzip
python benchmarks/benchmark.py --plain path/to/large.mzML --gz path/to/large.mzML.gz
```

Any competitor that is not importable is reported as *not installed* and skipped, so the
harness still runs with whatever you have.

### Arguments

| flag | default | purpose |
|---|---|---|
| `--corpus-dir` | `tests/data` | directory holding the re-encoded corpus (committed) |
| `--plain FILE` | — | large plain `.mzML` for the throughput group |
| `--gz FILE` | — | large `.mzML.gz` for the gzip group |
| `--repeats N` | `3` | timing repeats; the **minimum** is reported |

The **format-support group runs anywhere** — it uses the small re-encoded files committed
in `tests/data/`. The throughput and gzip groups need a large file, which is not committed
(too big for git). Any real DDA/DIA run works; the numbers below use
[PXD015669](https://www.ebi.ac.uk/pride/archive/projects/PXD015669) `QEHF1_09771_JB` (48 MB,
3,392 spectra). Make a matched gzip with `gzip -k file.mzML`.

## Results

Measured on Python 3.12 / Linux with:
`mzmlpy==0.5.0`, `pyteomics==5.0`, `pymzml==2.6.1`, `psims==1.3.6`, `lxml==6.1.1`,
`numpy==2.4.2`, `pynumpress==0.0.9`, `rapidgzip==0.16.0`.

### Format support & correctness (`tests/data` corpus)

Same 1,618 peaks re-encoded five ways. Reference intensity sum = `31,417,890` (lossless);
numpress-slof/pic are lossy by design and only expected to match closely.

| encoding | mzmlpy | pyteomics | pymzml |
|---|---|---|---|
| zlib | ✅ 31,417,890 | ✅ 31,417,890 | ✅ 31,417,890 |
| **zstd** | ✅ 31,417,890 | ❌ crash (`ValueError`) | ⚠️ **0 peaks, no error** |
| numpress-linear | ✅ 31,417,890 | ✅ 31,417,890 | ⚠️ **0 peaks, no error** |
| numpress-slof | ✅ 31,417,922 | ✅ 31,417,923 | ⚠️ **0 peaks, no error** |
| numpress-pic | ✅ 31,417,897 | ✅ 31,417,897 | ⚠️ **0 peaks, no error** |

mzmlpy is the only reader that decodes all four modern encodings out of the box. pyteomics
handles numpress (via `pynumpress`) but raises on zstd; pymzml **silently returns empty
spectra** for both zstd and numpress — the dangerous failure mode, since a pipeline sees zero
peaks with no error.

### Throughput — 48 MB plain file, 3,392 spectra

| operation | mzmlpy | pyteomics | pymzml |
|---|---|---|---|
| index + count | **0.077 s** | 0.54 s | n/a¹ |
| full decode (all spectra) | 0.96 s | 1.88 s | **0.85 s** |
| random 5 reads | **0.098 s** | 0.14 s | n/a¹ |

¹ pymzml decodes binary during iteration and exposes no cheap index-only / by-index path.

All three agree to the last digit on peak count and intensity sum. mzmlpy indexes **~7×** faster
than pyteomics (its lazy design counts/indexes without decoding), full decode is competitive
(~2× faster than pyteomics, ~15% behind pymzml's sequential-streaming path), and random access is
modestly faster than pyteomics once both readers' indices are warm. (Ratios vary run to run with
system load and cache warmth — an early cold run showed pyteomics random access ~1 s; the fair
min-of-3 figure above is ~0.14 s. Ordering is stable; the decisive differences are format
coverage and gzip handling below, not raw speed.)

### Gzip handling

**Transparency.** mzmlpy and pymzml both read `.mzML.gz` directly. **pyteomics does not detect
gzip** — passing a `.mzML.gz` path makes it parse the compressed bytes as XML and raise
`XMLSyntaxError`. You must wrap it in `gzip.open()` yourself, which is ~2.5× slower on a 28 MB
file (2.46 s vs 1.0 s) *and* forfeits random-access indexing.

**mzmlpy's three modes only matter with `in_memory=False`.** The default `in_memory=True`
buffers the whole decompressed file in RAM after open, so all three modes then perform
identically (and random access is instant). The mode choice becomes decisive only in the
memory-constrained case — measured here on a 232 MB `.mzML.gz` (76,501 spectra, `in_memory=False`):

| mode | startup, first open | startup, cached | random 8 reads (non-monotonic) | full decode |
|---|---|---|---|---|
| `extract` | **1.2 s** | 1.2 s | **0.16 s** | ~20 s |
| `indexed` | 17.2 s | **0.12 s** | 0.28 s | ~20 s |
| `stream` | 6.4 s | 6.4 s | ⚠️ **49 s** | ~20 s |

- **`extract`** — decompress once to disk (cached across sessions), then random-access the plain
  file. Best all-rounder; costs disk space for the decompressed copy.
- **`indexed`** — seekable access to the compressed file via `rapidgzip`, no disk copy. Pays a
  large one-time seek-index build (17 s), but the index is cached next to the file, so later
  opens are the fastest of any mode (0.12 s) with fast random access.
- **`stream`** — lowest memory, caches nothing, sequential only. Random access is pathological:
  each read rescans from the top (49 s for 8 reads), and mzmlpy emits a warning telling you so.

Full *sequential* decode is ~20 s regardless of mode — the mode differences live entirely in
startup and random access. (Note: the harness's `clear_cache()` clears only the `extract` temp
dir, not rapidgzip's on-disk seek index, so re-running shows `indexed`'s *cached* startup;
delete the `*.index`/rapidgzip cache next to the file to re-measure its cold build.)

## Notes on fairness

- Times are the **minimum of `--repeats` runs** (default 3) to reduce noise; wall-clock,
  warm OS cache.
- "Correctness" columns run a single pass and compare total peak count + summed intensity
  against mzmlpy.
- pyteomics/pymzml have no on-disk cache, so their cold and warm gzip numbers are identical.
- pyteomics requires `psims` for controlled-vocabulary parsing (fetched/cached on first use);
  mzmlpy depends only on `numpy` at runtime.
