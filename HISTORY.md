# History

## 0.4.0 (2026-04-07)

**New features:**

* Added `gzip_mode` parameter to `Mzml` for controlling how `.mzML.gz` files are read:
  * `"extract"` (default) — decompress to a cached file under `<tmpdir>/mzmlpy/` for full random access; cache persists across sessions.
  * `"indexed"` — seekable access to the compressed file via `rapidgzip`, with no extraction. Requires `pip install mzmlpy[rapidgzip]`.
  * `"stream"` — sequential streaming with no index; lowest startup cost, but random access scans from the beginning and emits a warning.
* Added `rapidgzip` integration for parallel gzip decompression. New optional extra: `pip install mzmlpy[rapidgzip]`.
* Cached gzip seek index (`.gzidx`) and mzML offset index (`.mzidx`) as sidecar files alongside `.gz` files for instant startup on subsequent opens.
* Added `extract_dir` parameter to `Mzml` for choosing a custom extraction directory.
* Added `clear_cache()` to the public API for reclaiming extracted-cache disk space before the OS clears the temp directory.
* Added byte-shuffled zstd and dictionary-encoded zstd decompression support.
* Verified compatibility with Bruker timsTOF mzML files; added a dedicated test suite covering them.

**Bug fixes:**

* Raise a clear `ImportError` when `rapidgzip` is missing for `gzip_mode="indexed"`.
* Dictionary-encoded zstd now uses the actual dtype instead of guessing it from the buffer size.
* Fixed several `pynumpress` API compatibility issues.

## 0.2.0 (2026-03-16)

**Breaking changes:**

* Renamed `lower_limit` / `upper_limit` → `lower_mz` / `upper_mz` on `ScanWindow`, `Scan`, and `Spectrum`.
* Renamed `lower_scan_window_limit` / `upper_scan_window_limit` → `lower_mz` / `upper_mz` on `Scan`.

**Bug fixes:**

* Fixed polarity accessions — `ScanPolarity.POSITIVE` and `ScanPolarity.NEGATIVE` were swapped, causing incorrect polarity identification for all spectra.

**New features:**

* Added `ION_MOBILITIES` constant set grouping all ion mobility `BinaryDataArrayAccession` values.
* Added `Spectrum.charge` — charge array as a numpy array (or `None`).
* Added `Spectrum.has_im` — `True` if the spectrum contains any ion mobility binary array.
* Added `Spectrum.im_types` — set of `BinaryDataArrayAccession` values present for ion mobility.
* Added `Spectrum.scan_start_time` — delegates to the first scan's `scan_start_time`.
* Added `Spectrum.ion_injection_time` — delegates to the first scan's `ion_injection_time`.

## 0.1.0 (2026-02-10)

* First release on PyPI.
