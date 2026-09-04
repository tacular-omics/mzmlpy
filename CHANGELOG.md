# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Optional `mcp` extra and local stdio server via `python -m mzmlpy mcp --root DIR`.
- Read-only tools for file inspection, validation, spectrum filtering, peak retrieval, and
  chromatograms, with explicit units, paging, file revisions, and restricted data paths.
- Full local MCP data-access integration with discovery, paged header metadata, acquisition
  inventories and comparisons, batched spectrum access, and arbitrary numeric arrays.
- Background jobs with progress, cancellation and bounded retention, revision-aware summary
  caching, typed output schemas, reference resources, and workflow prompts.
- Optional JSONL record exports preserve original encoded binary data and provenance. Exports
  require an explicit output directory. Spectrum processing remains in Spectacular.
- Spectrum representation, scan mobility, and signed FAIMS voltage metadata filters.
- MCP client integration tests, stdio smoke tests, and optional-install CI coverage.

## [0.8.0] - 2026-09-04

### Added

- Streaming validation reports for XML structure, counts, IDs, references, and array metadata.
  Optional binary decoding verifies array lengths, and optional index checks verify XML offsets.
- Lazy spectrum filtering by MS level, retention time in seconds, polarity, and precursor m/z.
- `python -m mzmlpy inspect`, `validate`, and `index-gzip` commands with JSON output.
- Cross-mode regression tests, base-install CI on Linux, Windows, and macOS, strict docs checks,
  and clean-wheel smoke tests. Coverage and JUnit reports now come from one test run.

### Fixed

- Extracted-cache collisions between files sharing a basename, size, and timestamp.
  Cache paths now include source identity and revision, including in custom directories.
- Index parsing for compact XML, single quotes, namespace prefixes, comments, and long tags.
  Invalid footer fallback discards partial entries. Lookup verifies record identity.
- Whole-file buffering during extraction and encoding sniffing, and retention of preceding
  spectra during chromatogram iteration. In-memory text readers share immutable source bytes.
- Invented chromatograms in spectra-only embedded gzip files, missing root metadata in unindexed
  mzML, and out-of-range negative indexes returning the last record.
- Temporary-file collisions during overlapping writes and recovery from malformed rapidgzip sidecars.
- Binary decoding now rejects invalid base64 characters while accepting XML whitespace.
- Scan times now recognize supported time-unit accessions even when unitName is absent.

### Changed

- Embedded gzip writing identifies XML boundaries with a streaming parser and rejects malformed input.
- Cache signatures include source identity and cached-file metadata. Old caches are rebuilt.
- `in_memory=True` remains the default. Large-file examples explicitly select disk-backed access.

## [0.7.0] - 2026-08-28

### Added

- `write_indexed_gzip` and its `index_gzip` alias create deterministic, pyMZML-compatible
  self-indexed gzip files from plain or compressed mzML input. Output is atomic and preserves the
  decompressed mzML bytes exactly.
- Self-indexed gzip files are detected automatically with `in_memory=False`. Spectrum and
  chromatogram access uses embedded member offsets without extracted files, sidecars, rapidgzip,
  or a writable source directory.
- `gzip_mode="auto"` is the new default and reuses embedded indexes, current extracted caches, or
  complete rapidgzip sidecars before falling back to extraction. `Mzml.access_strategy` reports
  the concrete route selected for every input.
- Embedded index and gzip member validation rejects duplicate identifiers, invalid offsets,
  malformed deflate streams, and checksum failures.

## [0.6.0] - 2026-08-15

Ion-mobility / DIA release, tracking the PSI "Encoding data independent acquisition, ion mobility
data, subsampled data arrays, and additional compression types in mzML 1.1" recommendation v1.0
(2026-06-30).

### Added

- **Citation metadata** — `CITATION.cff` provides validated author, ORCID, project, license, and
  keyword metadata for GitHub and Zenodo software archiving.
- **Front-end ion mobility filtering accessors** on `Scan` (recommendation §3.6): `faims_compensation_voltage`
  (`MS:1001581`), `selexion_separation_voltage` (`MS:1003394`), and `selexion_compensation_voltage`
  (`MS:1003371`).
- **DIA acquisition detection** on `FileContent`: `dia_acquisition` returns the declared
  merged-concept DIA method term (`MS:1003224`–`MS:1003228`, covering SWATH/HRM, diaPASEF,
  HDMSE/IMS-AIF, MSE/AIF/bbCID, SONAR), and `is_dia` is a convenience boolean
  (recommendation §3.3).
- **`IsolationWindow.no_isolation`** — detects the `MS:1003159` "no isolation" marker used on
  full-mass-range DIA (MSE/HDMSE) windows (recommendation §3.5).

### Fixed

- **Truncation + prediction compression** — the `truncation, linear prediction and zlib` (`MS:1003090`)
  and `truncation, delta prediction and zlib` (`MS:1003089`) codecs now decode instead of raising
  `NotImplementedError`. Composite prediction terms take precedence when a producer also emits a
  generic zlib term, and malformed partial elements now raise the same actionable error as other
  binary encodings.
- **Referenced DIA metadata** — DIA acquisition terms inherited by `fileContent` through a valid
  `referenceableParamGroupRef` are now resolved instead of incorrectly reporting `is_dia=False`.

## [0.5.0] - 2026-07-09

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
- **Empty binary data arrays** no longer emit a `UserWarning` on decode; an empty/absent `<binary>`
  simply returns an empty array (the warnings were noisy for files with legitimately empty arrays).
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

[0.7.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.7.0
[0.6.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.6.0
[0.5.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.5.0
[0.4.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.4.0
[0.2.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.2.0
[0.1.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v0.1.0
