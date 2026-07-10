# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-07-02

A large correctness, robustness, and diagnostics release. Some behavior changed in ways that can
affect existing code (see **Changed**).

### Added

- **`peek_spectrum_count(file)`** — a standalone function that returns a file's spectrum count
  without constructing a reader or building a random-access index: it streams to the
  `<spectrumList count="N">` opening tag and stops. Useful for cheaply checking many files.
  Works for `.mzML` and `.mzML.gz`. Returns `None` if there is no `spectrumList`.
- **`llms.txt`** — a compact, accurate usage guide for AI coding assistants (installation, core
  API, gotchas, and the meaning of error messages), so LLMs generate correct mzmlpy code.
- **`Spectrum.id_dict` / `Chromatogram.id_dict`** — parse the native id into its `key=value`
  components (integers coerced to `int`), so `spectrum.id_dict["scan"]` gives the scan number
  directly across vendor formats (Thermo, Bruker, SCIEX).
- **Spectrum/scan summary accessors** — `Spectrum.base_peak_mz`, `base_peak_intensity`,
  `lowest_observed_mz`, `highest_observed_mz`, and `filter_string` (also `Scan.filter_string`),
  exposing common cvParams that previously required manual `get_cvparm` lookups.
- **Scan-level ion mobility** — `Scan.inverse_reduced_ion_mobility` / `Scan.ion_mobility_drift_time`
  and a spectrum-level `Spectrum.ion_mobility`. `has_im` now also detects scan-level mobility
  (Bruker timsTOF PASEF MS2), which previously reported `has_im=False` despite mobility being present.
- **`Product.isolation_window`** — products now expose their isolation window (like precursors).
- **`referenceableParamGroupRef` resolution.** CV terms a spectrum or scan inherits from a
  referenced parameter group (e.g. polarity via `MS:1000130`) are now resolved onto the element,
  so `spectrum.polarity`, `ms_level`, etc. reflect grouped terms. Previously these returned `None`.
- **`benchmarks/`** — a reproducible harness comparing mzmlpy against pyteomics and pymzml
  (format support, throughput, gzip handling), with a README of results.
- **Actionable error messages.** Decode failures now explain themselves: missing optional
  dependencies name the `pip install mzmlpy[...]` extra to install; buffer-size mismatches,
  malformed base64, unknown data types, and non-numeric CV values report the offending value and
  context instead of raw `numpy`/`binascii`/`ValueError` output.
- **Negative indexing** on spectrum/chromatogram lookups (`reader.spectra[-1]`), consistent with
  slicing.
- **`BaseLookup.next()`** is now a real stateful cursor with a companion **`reset()`**.
- **`util.atomic_write_path`** and cache-signature helpers for crash-safe, correctly-invalidated
  caches.

### Changed

- **Version 0.5.0.**
- **`TIC`** is now located by its CV accession (`MS:1000235`) when the id is not literally `"TIC"`
  (e.g. `"tic"`); previously `reader.TIC` returned `None` for such files.
- **Empty files** report a spectrum/chromatogram count of `0`; `len(reader.spectra)` no longer
  raises `TypeError` on a file with no spectra.
- **Binary array dtypes** are pinned little-endian per the mzML spec (correct on big-endian hosts).
- **Iteration** detaches each element from the tree after yielding, bounding peak memory on large
  files while keeping yielded spectra fully usable (verified ~37× lower peak on a 232 MB file).
- **Duplicate ids** in `cvs` / `softwares` / `samples` now emit a warning instead of silently
  dropping the earlier entry.
- **`_Param.to_timedelta`** returns `None` for non-time / non-numeric parameters instead of raising.
- Scan-list accessors (`scan_start_time`, `lower_mz`, `upper_mz`, `ion_injection_time`) warn only
  for genuinely multiple scans, and return `None` (not raise) for an empty scan list.
- **`reader.spectra` / `reader.chromatograms`** now return the same lookup instance across accesses,
  so `reader.spectra.next()` in a loop advances the cursor (instead of restarting at the first
  spectrum) and a regex `id_map` is built once instead of on every access.
- **File-like input** is now fully supported: `Mzml(...)` accepts any binary file-like object
  (not only `BytesIO`), and a gzip-compressed stream is decompressed transparently. An unsupported
  input type raises a clear `TypeError`.
- **`gzip_mode`** now warns when it is silently overridden by the default `in_memory=True` (which
  decompresses the whole file into memory); pass `in_memory=False` to use `"indexed"`/`"stream"`.
- **Spectrum id lookup is now consistent across every reader mode.** `gzip_mode="stream"` previously
  matched a bare trailing number against the native id (so `reader.spectra["19"]` could resolve
  `scan=19` — or silently return the *wrong* spectrum when the trailing number was ambiguous, e.g.
  `experiment=1` or a per-frame `scan=1`), while all other modes required the full native id. Stream
  mode now matches on the full native id like every other mode. To look up by a component such as the
  scan number, use `Mzml(spectrum_id_regex=r"scan=(\d+)")` and index with the extracted key — this
  resolves identically in all modes.

### Fixed

- **Resource leaks:** a `RapidgzipFile` (with worker threads) was leaked when a reader was closed,
  when construction failed, and when a `StandardGzip` scan hit malformed XML — all now cleaned up.
- **Infinite loop** in random access on a truncated final element; now raises a clear error.
- **Byte-vs-character offset** bug that over-read past an element containing multi-byte UTF-8.
- **Empty `<scanList count="0">`** raised `RuntimeError` and a spurious "multiple scans" warning.
- **Scan-window limits** returned `None` unless `unitName` was exactly `"m/z"` (now resolved by
  accession, tolerating `unitAccession`-only or absent units).
- **A single malformed `cvParam`** (missing a schema-required attribute) crashed access to *all*
  parameters on the element.
- **Decoder:** `unshuffle` silently produced scrambled output on a length not a multiple of the
  element size (now raises); dictionary-encoded zstd raised `ZeroDivisionError` on an empty array
  (now returns an empty array).
- **Dictionary-encoded zstd** (`MS:1003782`) sized the value table from the output count instead of
  the header's index offset, silently returning garbage whenever there were fewer unique values
  than output points; it now uses the header offset and decodes correctly.
- **Native-id parsing** (`id_dict`) coerced values like `"007"` and `"1_000"` to `7` / `1000`,
  losing information that no longer matched the on-disk id; such values now stay strings (only
  round-trip-safe integers are coerced).
- **`Activation.collision_gas`** returned `None` for the usual valueless `MS:1000419` flag; it now
  returns the term name (or value when present).
- **Duplicate native ids** encountered while building an index from scratch now emit a warning
  (matching the footer-index path) instead of being silently dropped.
- **`peek_spectrum_count`** no longer accumulates the whole element tree in memory for a file that
  has no `spectrumList`.
- **Caches** are written atomically and validated against a source size+mtime signature, so an
  interrupted write or a restored (older) source no longer yields a stale/corrupt cache.
- **`FileDescription.get_source_file(id)`** now matches the source file's `id` attribute (it
  previously matched CV params, returning `None` for a valid id).
- **`MSDecoder.encode_linear` / `encode_slof`** now pass the required numpress fixed point (they
  raised `TypeError` before); encoding is functional.

## [0.4.0] - 2026-04-07

### Added

- **`gzip_mode` parameter** on `Mzml` for controlling how `.mzML.gz` files are read:
  - `"extract"` (default) — decompress to a cached file under `<tmpdir>/mzmlpy/` for full random
    access; cache persists across sessions.
  - `"indexed"` — seekable access to the compressed file via `rapidgzip`, with no extraction.
    Requires `pip install mzmlpy[rapidgzip]`.
  - `"stream"` — sequential streaming with no index; lowest startup cost, but random access scans
    from the beginning and emits a warning.
- **`rapidgzip` integration** for parallel gzip decompression. New optional extra:
  `pip install mzmlpy[rapidgzip]`.
- Cached gzip seek index (`.gzidx`) and mzML offset index (`.mzidx`) as sidecar files alongside
  `.gz` files for instant startup on subsequent opens.
- **`extract_dir` parameter** on `Mzml` for choosing a custom extraction directory.
- **`clear_cache()`** added to the public API for reclaiming extracted-cache disk space before the
  OS clears the temp directory.
- Byte-shuffled zstd and dictionary-encoded zstd decompression support.
- Verified compatibility with Bruker timsTOF mzML files; added a dedicated test suite covering
  them.

### Fixed

- Raise a clear `ImportError` when `rapidgzip` is missing for `gzip_mode="indexed"`.
- Dictionary-encoded zstd now uses the actual dtype instead of guessing it from the buffer size.
- Fixed several `pynumpress` API compatibility issues.

## [0.2.0] - 2026-03-16

### Changed

- **Breaking:** renamed `lower_limit` / `upper_limit` → `lower_mz` / `upper_mz` on `ScanWindow`,
  `Scan`, and `Spectrum`.
- **Breaking:** renamed `lower_scan_window_limit` / `upper_scan_window_limit` → `lower_mz` /
  `upper_mz` on `Scan`.

### Added

- **`ION_MOBILITIES`** constant set grouping all ion mobility `BinaryDataArrayAccession` values.
- **`Spectrum.charge`** — charge array as a numpy array (or `None`).
- **`Spectrum.has_im`** — `True` if the spectrum contains any ion mobility binary array.
- **`Spectrum.im_types`** — set of `BinaryDataArrayAccession` values present for ion mobility.
- **`Spectrum.scan_start_time`** — delegates to the first scan's `scan_start_time`.
- **`Spectrum.ion_injection_time`** — delegates to the first scan's `ion_injection_time`.

### Fixed

- Polarity accessions — `ScanPolarity.POSITIVE` and `ScanPolarity.NEGATIVE` were swapped, causing
  incorrect polarity identification for all spectra.

## [0.1.0] - 2026-02-10

### Added

- First release on PyPI.

[0.5.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.5.0
[0.4.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.4.0
[0.2.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.2.0
[0.1.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.1.0
