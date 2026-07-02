# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.0.0] - 2026-07-02

A large correctness, robustness, and diagnostics release. Some behavior changed in ways that can
affect existing code (see **Changed**), hence the major version bump.

### Added

- **`llms.txt`** — a compact, accurate usage guide for AI coding assistants (installation, core
  API, gotchas, and the meaning of error messages), so LLMs generate correct mzmlpy code.
- **`Spectrum.id_dict` / `Chromatogram.id_dict`** — parse the native id into its `key=value`
  components (integers coerced to `int`), so `spectrum.id_dict["scan"]` gives the scan number
  directly across vendor formats (Thermo, Bruker, SCIEX).
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

- **Version 5.0.0** and `Development Status :: 5 - Production/Stable`.
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
- **Caches** are written atomically and validated against a source size+mtime signature, so an
  interrupted write or a restored (older) source no longer yields a stale/corrupt cache.
- **`FileDescription.get_source_file(id)`** now matches the source file's `id` attribute (it
  previously matched CV params, returning `None` for a valid id).
- **`MSDecoder.encode_linear` / `encode_slof`** now pass the required numpress fixed point (they
  raised `TypeError` before); encoding is functional.

[5.0.0]: https://github.com/tacular-omics/mzmlpy/releases/tag/v5.0.0
