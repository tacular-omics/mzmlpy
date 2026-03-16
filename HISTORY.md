# History

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
