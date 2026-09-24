# Migrating to 0.10

mzmlpy 0.10 renames reader attributes to the vocabulary shared by the tacular-omics readers
(`rt`, `ook0`, `mz_range`, `collision_energy`, ...), removes deprecated names, and adds an
exception hierarchy. Renamed names have no aliases: the old name raises `AttributeError` or
`ImportError`.

## Records

| 0.9 | 0.10 | notes |
|---|---|---|
| `Spectrum.scan_start_time`, `Scan.scan_start_time` (`timedelta`) | `Spectrum.rt`, `Scan.rt` | float, seconds; was `.total_seconds()` |
| `Spectrum.lower_mz` / `upper_mz`, `Scan.lower_mz` / `upper_mz` | `Spectrum.mz_range`, `Scan.mz_range` | `(lower, upper)` envelope of the scan windows; `ScanWindow.lower_mz` / `upper_mz` are kept |
| `Spectrum.TIC` | `Spectrum.total_ion_current` | |
| `Spectrum.charge` (per-point array) | `Spectrum.charge_array` | `Spectrum.charge` now means the precursor charge (`int \| None`) |
| `Spectrum.ion_mobility` (1/K0, else drift time) | `Spectrum.ook0` or `Spectrum.scans[0].drift_time` | no fallback between the two quantities |
| `IsolationWindow.target_mz` | `IsolationWindow.isolation_mz` | |
| `(w.target_mz - w.lower_offset, w.target_mz + w.upper_offset)` | `IsolationWindow.isolation_mz_range` | also `isolation_width` |
| `spectrum.precursors[0].selected_ions[0].mz`, `...selected_ions[0].charge`, `precursors[0].activation.collision_energy`, `precursors[0].isolation_window` bounds | `Spectrum.precursor_mz`, `Spectrum.charge`, `Spectrum.collision_energy`, `Spectrum.isolation_mz_range` | new shortcuts; first precursor, first selected ion; None when absent |
| `Chromatogram.time` (array in its recorded unit and dtype) | `Chromatogram.rt` | float64 seconds, converted from the recorded unit; the raw array is `get_binary_array(BinaryDataArrayAccession.TIME).data` |
| `Scan.inverse_reduced_ion_mobility` | `Scan.ook0` (also `Spectrum.ook0`) | 1/K0, V·s/cm² |
| `Scan.ion_mobility_drift_time` | `Scan.drift_time` | |
| `SelectedIon.selected_ion_mz` | `SelectedIon.mz` | |
| `SelectedIon.peak_intensity` | `SelectedIon.intensity` | |
| `SelectedIon.charge_state` | `SelectedIon.charge` | |
| `SelectedIon.ir_im` | `SelectedIon.ook0` | |
| `SelectedIon.im_drift_time` | `SelectedIon.drift_time` | |
| `Activation.ce` | `Activation.collision_energy` | value as recorded; Thermo files store NCE here |
| `Activation.supplemental_ce` | `Activation.supplemental_collision_energy` | |
| `get_cvparm(id)` / `has_cvparm(id)` | `get_cv_param(id)` / `has_cv_param(id)` | |
| `cv_params`, `user_params`, `ref_params` (`list`) | same names, `tuple` | |
| `accessions`, `names` (`set`) | same names, `frozenset` | |
| `Spectrum.scans`, `precursors`, `products`, `binary_arrays`, `Scan.scan_windows`, `Precursor.selected_ions`, `FileDescription.source_files`, `contact` (`list`) | same names, `tuple` | empty tuple when absent; `== []` checks become `== ()` or `not x` |
| `Spectrum.ion_injection_time`, `Scan.ion_injection_time` (`timedelta`) | same names, float milliseconds | was `.total_seconds() * 1000` |
| `Spectrum.total_ion_current` raising `KeyError` when absent | returns `None` | |
| `UserParam.name`, `ReferenceableParamGroupRef.ref` `None` when the attribute is missing | `""` | |

## Reader and lookups

| 0.9 | 0.10 | notes |
|---|---|---|
| `Mzml.TIC`, `ChromatogramLookup.TIC` | `Mzml.total_ion_chromatogram` | the lookup has no TIC property |
| `reader.spectra.next()` / `reset()` | `it = iter(reader.spectra)`; `next(it)` | the stateful cursor is removed |
| `lookup.file_object` | removed | internal |
| `Mzml.iter` | removed | internal |
| `Mzml.obo_version = ...` | read-only property | |
| `Mzml.referenceable_param_groups`, `instrument_configurations`, `data_processes`, `scan_settings` | same | now return a new dict on each call |
| `lookup.get_by_index("3")` | `lookup.get_by_index(3)` | a non-int raises `TypeError` |
| `spectra[1.0]`, `spectra.get_by_id(1)` | `spectra[1]`, `spectra.get_by_id("scan=1")` | other key types raise `TypeError` |
| `Mzml(path)` loads the whole file (`in_memory=True` default) | `Mzml(path)` reads from disk (`in_memory=False` default) | pass `in_memory=True` for the old behaviour |
| `spectra.filter(retention_time=(lo, hi))`, `SpectrumFilter(retention_time=...)` | `rt_range=(lo, hi)` | seconds |
| (no point query) | `spectra.filter(rt=600.0, rt_tolerance=30.0)` | tdfpy convention; `rt=(lo, hi)` raises `MzmlError` pointing at `rt_range` |
| `filter(precursor_mz=(lo, hi))`, `SpectrumFilter(precursor_mz=...)` | `precursor_mz_range=(lo, hi)` | |
| (no point query) | `spectra.filter(precursor_mz=500.25, mz_tolerance=20, mz_tolerance_type="ppm")` | `"da"` for Dalton tolerance |
| `mobility_type="inverse_reduced", ion_mobility=(lo, hi)` | `ook0_range=(lo, hi)` | `(None, None)` selects spectra that record 1/K0 |
| `mobility_type="drift_time", ion_mobility=(lo, hi)` | `drift_time_range=(lo, hi)` | |
| `faims_voltage=(lo, hi)` | `faims_voltage_range=(lo, hi)` | signed volts |
| `SpectrumFilter(2, ...)` (positional) | `SpectrumFilter(ms_level=2, ...)` | keyword-only |

`spectra.filter` with a retention-time criterion now binary-searches the file and stops after
the window when the reader has random access (every access strategy except `stream`). It
assumes spectra are stored in retention-time order, as instrument files are. For a file that
is not (for example merged runs), use `(s for s in reader.spectra if SpectrumFilter(...).matches(s))`.

A scan start time or ion injection time with no unit, or a non-time unit, is read as seconds
(milliseconds for injection time) and warns once per unit. Set the unit in the file, or silence
the warning with `warnings.filterwarnings`, if the default is right for your data.

## Errors

| 0.9 | 0.10 |
|---|---|
| `ValueError` for bad data or arguments | `MzmlError` or a subclass (still a `ValueError`) |
| `xml.etree.ElementTree.ParseError` leaking from malformed XML | `MzmlParseError` (original as `__cause__`) |
| `ValueError` for an inconsistent offset index | `MzmlOffsetIndexError` |
| `ValueError` for undecodable binary data | `MzmlDecodeError` |
| `KeyError` for a missing id | `MzmlRecordNotFoundError` (still a `KeyError`) |
| a non-numeric `rt` value | `MzmlError` |
| a well-formed file whose root is not `<mzML>` / `<indexedmzML>` | `MzmlParseError` on open |

## Constants (`mzmlpy.constants`)

| 0.9 | 0.10 |
|---|---|
| `SpectrumType` | `SpectrumTypeAccession` |
| `CompressionTypeAccessions` | `CompressionTypeAccession` |
| `ChromatogramTypeAccession.EMMISION` | `ChromatogramTypeAccession.EMISSION` |
| `XMLElement` | merged into `MzMLElement` |
| `PeakType`, `NoiseMode`, `DataType`, `TimeUnit`, `XMLAttribute`, `EncodingFormat`, `XMLNamespace` | removed (unused); use `TimeUnitAccession` for time units |
| `PROTON_MASS`, `ISOTOPE_AVERAGE_DIFFERENCE`, `ISOLATION_WINDOW_TARGET_MZ` | removed (unused) |
| `BINARY_DECODE_DTYPES` | private |

The accession enums used in return types (`BinaryDataArrayAccession`, `BinaryDataTypeAccession`,
`ChromatogramTypeAccession`, `CollisionDissociationTypeAccession`, `CompressionTypeAccession`,
`DIAAcquisitionAccession`, `SpectrumCombinationAccession`) are now also importable from `mzmlpy`.

## Internal names made private

`MzMLContentBuilder`, `convert_mzml_element_to_object`, `fix_input` and `decode_to_numpy`
gained a leading underscore. Every public module now declares `__all__`.

The MCP server's tool names, parameters (such as `retention_time_min_seconds`, `mobility_type`,
`ion_mobility_min`) and JSON keys (such as `target_mz`) are unchanged. `get_chromatogram` reports
`coordinate_dtype` `float64`, since times are now always converted to seconds.
