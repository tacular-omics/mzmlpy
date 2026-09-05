"""Metadata-only serialization and acquisition inventories for MCP clients."""

import math
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from . import Chromatogram, Mzml, Spectrum
from ._progress import checkpoint
from .elems.dtree_wrapper import _DataTreeWrapper, _ParamGroup
from .util import get_tag, gzip_open_binary


def record_list_attributes(path: Path, kind: str) -> dict[str, Any] | None:
    """Read inherited list defaults without retaining or decoding preceding records."""
    target = f"{kind}List"
    with gzip_open_binary(str(path)) if path.suffix in {".gz", ".igz"} else path.open("rb") as handle:
        parents = []
        for event, element in ET.iterparse(handle, events=("start", "end")):
            checkpoint("reading record list metadata")
            if event == "start":
                if get_tag(element) == target:
                    return {"tag": target, "attributes": dict(element.attrib)}
                parents.append(element)
            else:
                parents.pop()
                element.clear()
                if parents:
                    parents[-1].remove(element)
    return None


def metadata_tree(group: _DataTreeWrapper, *, omit_arrays: bool = False) -> dict[str, Any]:
    """Preserve header attributes, CV terms, user parameters, and nested metadata."""

    def visit(element: Any) -> dict[str, Any]:
        if get_tag(element) in {"binary", "spectrumList", "chromatogramList"}:
            raise ValueError("Record arrays and lists are not header metadata")
        return {
            "tag": get_tag(element),
            "attributes": dict(element.attrib),
            "text": element.text.strip() if element.text and element.text.strip() else None,
            "children": [
                visit(child) for child in element if not (omit_arrays and get_tag(child) == "binaryDataArrayList")
            ],
        }

    return visit(group.element)


def params(group: _ParamGroup) -> list[dict[str, Any]]:
    return [asdict(param) for param in group.cv_params]


def array_metadata(array: Any) -> dict[str, Any]:
    return {
        "type": array.binary_array_type,
        "encoding": array.encoding,
        "compression": array.compression,
        "attributes": dict(array.element.attrib),
        "terms": params(array),
        "user_params": [asdict(param) for param in array.user_params],
    }


def spectrum_metadata(spectrum: Spectrum) -> dict[str, Any]:
    return {
        "id": spectrum.id,
        "index": spectrum.index,
        "ms_level": spectrum.ms_level,
        "polarity": spectrum.polarity,
        "spectrum_type": spectrum.spectrum_type,
        "default_array_length": spectrum.default_array_length,
        "attributes": dict(spectrum.element.attrib),
        "structure": metadata_tree(spectrum, omit_arrays=True),
        "terms": params(spectrum),
        "user_params": [asdict(param) for param in spectrum.user_params],
        "retention_times_seconds": [
            time.total_seconds() if (time := scan.scan_start_time) is not None else None for scan in spectrum.scans
        ],
        "scans": [
            {
                "attributes": dict(scan.element.attrib),
                "terms": params(scan),
                "user_params": [asdict(param) for param in scan.user_params],
                "inverse_reduced_ion_mobility": scan.inverse_reduced_ion_mobility,
                "ion_mobility_drift_time": scan.ion_mobility_drift_time,
                "faims_compensation_voltage": scan.faims_compensation_voltage,
                "windows": [metadata_tree(window) for window in scan.scan_windows],
            }
            for scan in spectrum.scans
        ],
        "precursors": [
            {
                "spectrum_ref": precursor.spectrum_ref,
                "source_file_ref": precursor.source_file_ref,
                "external_spectrum_id": precursor.external_spectrum_id,
                "isolation_window": params(precursor.isolation_window) if precursor.isolation_window else None,
                "selected_ions": [params(ion) for ion in precursor.selected_ions],
                "activation": metadata_tree(precursor.activation) if precursor.activation else None,
            }
            for precursor in spectrum.precursors
        ],
        "products": [metadata_tree(product) for product in spectrum.products],
        "arrays": [array_metadata(array) for array in spectrum.binary_arrays],
    }


def chromatogram_metadata(chromatogram: Chromatogram) -> dict[str, Any]:
    return {
        "id": chromatogram.id,
        "type": chromatogram.chromatogram_type,
        "attributes": dict(chromatogram.element.attrib),
        "structure": metadata_tree(chromatogram, omit_arrays=True),
        "terms": params(chromatogram),
        "user_params": [asdict(param) for param in chromatogram.user_params],
        "arrays": [array_metadata(array) for array in chromatogram.binary_arrays],
    }


def inventory(reader: Mzml) -> dict[str, Any]:
    """Scan recorded metadata without requesting any decoded binary arrays."""
    counts: dict[str, Counter[str]] = {
        key: Counter() for key in ("ms_levels", "polarities", "spectrum_types", "array_types", "compressions")
    }
    total = empty = missing_time = regressions = multiple_scans = 0
    earliest = latest = previous = largest_gap = None
    min_length = max_length = None
    windows: set[tuple[float | None, ...]] = set()
    windows_truncated = False
    mobility_spectra = 0
    for spectrum in reader.spectra:
        checkpoint("summarizing spectra", total)
        total += 1
        counts["ms_levels"][str(spectrum.ms_level) if spectrum.ms_level is not None else "missing"] += 1
        counts["polarities"][spectrum.polarity or "missing"] += 1
        counts["spectrum_types"][spectrum.spectrum_type or "missing"] += 1
        length = spectrum.default_array_length
        if length is not None:
            empty += length == 0
            min_length = length if min_length is None else min(min_length, length)
            max_length = length if max_length is None else max(max_length, length)
        scans = spectrum.scans
        multiple_scans += len(scans) > 1
        times = [t.total_seconds() for scan in scans if (t := scan.scan_start_time) is not None]
        missing_time += not times
        for time in times:
            earliest = time if earliest is None else min(earliest, time)
            latest = time if latest is None else max(latest, time)
        # Consecutive timing statistics use only the first recorded scan time.
        if scans and (first := scans[0].scan_start_time) is not None:
            time = first.total_seconds()
            if previous is not None:
                delta = time - previous
                regressions += delta < 0
                if delta >= 0:
                    largest_gap = delta if largest_gap is None else max(largest_gap, delta)
            previous = time
        else:
            previous = None
        mobility_spectra += spectrum.has_im
        for array in spectrum.binary_arrays:
            counts["array_types"][array.binary_array_type or "unknown"] += 1
            counts["compressions"][array.compression or "unspecified"] += 1
        for precursor in spectrum.precursors:
            window = precursor.isolation_window
            if window is not None:
                item = (window.target_mz, window.lower_offset, window.upper_offset)
                if any(value is not None and not math.isfinite(value) for value in item):
                    raise ValueError("Nonfinite isolation window metadata")
                if item not in windows:
                    if len(windows) < 100:
                        windows.add(item)
                    else:
                        windows_truncated = True
    chromatogram_count = 0
    for _ in reader.chromatograms:
        chromatogram_count += 1
        checkpoint("summarizing chromatograms", chromatogram_count)
    return {
        "spectrum_count": total,
        "chromatogram_count": chromatogram_count,
        **{name: dict(value) for name, value in counts.items()},
        "empty_spectra_declared": empty,
        "missing_retention_time": missing_time,
        "spectra_with_multiple_scans": multiple_scans,
        "retention_time_min_seconds": earliest,
        "retention_time_max_seconds": latest,
        "retention_time_span_seconds": latest - earliest if latest is not None and earliest is not None else None,
        "first_scan_time_regressions": regressions,
        "largest_adjacent_first_scan_gap_seconds": largest_gap,
        "declared_array_length_min": min_length,
        "declared_array_length_max": max_length,
        "spectra_with_ion_mobility": mobility_spectra,
        "isolation_windows": [
            {"target_mz": t, "lower_offset_mz": low, "upper_offset_mz": high}
            for t, low, high in sorted(windows, key=lambda item: tuple(-math.inf if v is None else v for v in item))
        ],
        "isolation_windows_truncated": windows_truncated,
        "binary_arrays_decoded": False,
        "scope": "Recorded acquisition metadata only. Counts and timing metrics do not establish scientific quality.",
    }
