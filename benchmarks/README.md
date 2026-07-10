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
| peek count only (no index) | **0.000 s**¹ | n/a² | 0.007 s |
| index + count (random-access ready) | 0.076 s | 0.78 s | n/a² |
| full decode (all spectra) | 0.86 s | 1.74 s | **0.74 s** |
| random 8 reads | **0.092 s** | 0.74 s | ❌ crash³ |

¹ pymzml's `get_spectrum_count()` reads the `spectrumList count="N"` attribute directly — no
byte-offset index, no reader construction — and is genuinely the cheapest way to *just* get a
count. mzmlpy replicates the same trick via the standalone `peek_spectrum_count(path)` function
(not the `Mzml` class): stream to the same opening tag and stop. It comes out at least as fast
here. This is a different operation from the row below — it does not leave you with any way to
access a spectrum afterward.

² pyteomics has no cheap count-only path (opening a reader is essentially as expensive as
building the index below); pymzml has no cheap way to also get random-access-ready indexing
without hitting the bug in note 3.

³ pymzml **does** support indexed random access (`run[native_id]`) and worked correctly on the
small canonical `tests/data/example.mzML` file. On this real 48 MB file (produced by
ThermoRawFileParser) every indexed lookup raised
`AttributeError: 'NoneType' object has no attribute 'obo_translator'` — its internal index/offset
lookup returned `None` for a native id it had itself just listed as present, reproducibly, even
after forcing `build_index_from_scratch=True`. This looks like a pymzml bug parsing its offset
index for this file's id/index format, not a missing feature — flagging it rather than hiding it
as "n/a" is the honest result.

All three agree to the last digit on peak count and intensity sum where pymzml could decode at
all. Full-decode throughput is close across all three (mzmlpy competitive with pymzml's
sequential-streaming path, both faster than pyteomics); mzmlpy's random access is fast and
reliable, pyteomics's is slower but reliable, and pymzml's crashed on this real-world file.
(Absolute numbers vary run to run with system load; ordering is stable. The decisive
differentiators remain format coverage and gzip handling below, not raw speed.)

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
startup and random access. Before each mode the harness purges **all** mzmlpy caches — the tmp
`extract` directory *and* the `.gzidx`/`.mzidx` (+`.src`) index sidecars written next to the
`.gz` file — so every startup figure is a genuine cold build, not a re-used index.

## Notes on fairness

- Times are the **minimum of `--repeats` runs** (default 3) to reduce noise; wall-clock,
  warm OS cache.
- "Correctness" columns run a single pass and compare total peak count + summed intensity
  against mzmlpy.
- pyteomics/pymzml have no on-disk cache, so their cold and warm gzip numbers are identical.
- pyteomics requires `psims` for controlled-vocabulary parsing (fetched/cached on first use);
  mzmlpy depends only on `numpy` at runtime.
