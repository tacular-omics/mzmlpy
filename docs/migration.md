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
| `Spectrum.charge` (per-point array) | `Spectrum.charge_array` | |
| `Scan.inverse_reduced_ion_mobility` | `Scan.ook0` (also `Spectrum.ook0`) | 1/K0, V·s/cm² |
| `Scan.ion_mobility_drift_time` | `Scan.drift_time` | |
| `SelectedIon.selected_ion_mz` | `SelectedIon.mz` | |
| `SelectedIon.peak_intensity` | `SelectedIon.intensity` | |
| `SelectedIon.charge_state` | `SelectedIon.charge` | |
| `SelectedIon.ir_im` | `SelectedIon.ook0` | |
| `SelectedIon.im_drift_time` | `SelectedIon.drift_time` | |
| `Activation.ce` | `Activation.collision_energy` | MS:1000045 only; no longer falls back to `activation_energy` |
| `Activation.supplemental_ce` | `Activation.supplemental_collision_energy` | |
| `get_cvparm(id)` / `has_cvparm(id)` | `get_cv_param(id)` / `has_cv_param(id)` | |
| `cv_params`, `user_params`, `ref_params` (`list`) | same names, `tuple` | |
| `accessions`, `names` (`set`) | same names, `frozenset` | |

## Reader and lookups

| 0.9 | 0.10 | notes |
|---|---|---|
| `Mzml.TIC`, `ChromatogramLookup.TIC` | `Mzml.total_ion_chromatogram`, `ChromatogramLookup.total_ion_chromatogram` | |
| `reader.spectra.next()` / `reset()` | `it = iter(reader.spectra)`; `next(it)` | the stateful cursor is removed |
| `lookup.file_object` | removed | internal |
| `Mzml.iter` | removed | internal |
| `Mzml.obo_version = ...` | read-only property | |
| `Mzml.referenceable_param_groups`, `instrument_configurations`, `data_processes`, `scan_settings` | same | now return a new dict on each call |
| `lookup.get_by_index("3")` | `lookup.get_by_index(3)` | a non-int raises `TypeError` |
| `spectra.filter(retention_time=...)`, `SpectrumFilter(retention_time=...)` | `rt=...` | seconds |
| `SpectrumFilter(2, ...)` (positional) | `SpectrumFilter(ms_level=2, ...)` | keyword-only |

## Errors

| 0.9 | 0.10 |
|---|---|
| `ValueError` for bad data or arguments | `MzmlError` or a subclass (still a `ValueError`) |
| `xml.etree.ElementTree.ParseError` leaking from malformed XML | `MzmlParseError` (original as `__cause__`) |
| `ValueError` for an inconsistent offset index | `MzmlOffsetIndexError` |
| `ValueError` for undecodable binary data | `MzmlDecodeError` |
| `KeyError` for a missing id | `MzmlRecordNotFoundError` (still a `KeyError`) |

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

The MCP server's tool names, parameters (such as `retention_time_min_seconds`) and JSON keys are
unchanged.
