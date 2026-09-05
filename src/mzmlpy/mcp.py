"""Optional local MCP tools for inspecting mzML data through the public reader API."""

import json
from dataclasses import asdict, dataclass
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from . import Mzml, SpectrumFilter, __version__, validate
from ._mcp_metadata import (
    array_metadata,
    chromatogram_metadata,
    inventory,
    metadata_tree,
    record_list_attributes,
    spectrum_metadata,
)
from ._mcp_runtime import JobManager, JobStatus, ResultCache
from ._mcp_types import (
    ArrayData,
    ArtifactData,
    BatchData,
    ChromatogramData,
    ChromatogramPage,
    ComparisonData,
    DirectoryPage,
    ExportPage,
    InspectData,
    MetadataPage,
    SpectrumData,
    SpectrumPage,
    SummaryData,
    ValidationData,
)
from ._progress import checkpoint
from .constants import BinaryDataArrayAccession, TimeUnitAccession
from .elems.dtree_wrapper import _ParamGroup

if TYPE_CHECKING:
    from mcp.server import MCPServer


@dataclass(frozen=True)
class FileResult[T]:
    """A bounded result attributed to a specific local file revision."""

    file: str
    revision: str
    data: T


def _bounded(value: Any) -> None:
    if len(json.dumps(value, allow_nan=False).encode()) > 262_144:
        raise ValueError("Result exceeds 256 KiB. Request a smaller page or use an export")


def _integer(name: str, value: int, minimum: int, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum or 'unbounded'}")


def _range(lower: float | None, upper: float | None) -> tuple[float | None, float | None] | None:
    bounds = (lower, upper) if lower is not None or upper is not None else None
    SpectrumFilter(retention_time=bounds)
    return bounds


def _params(group: _ParamGroup) -> list[dict[str, Any]]:
    return [asdict(param) for param in group.cv_params]


_spectrum = spectrum_metadata


def _json_number(value: Any) -> int | float | str:
    """Keep integer values exact even in clients that parse JSON numbers as doubles."""
    if isinstance(value, int | np.integer):
        integer = int(value)
        return integer if abs(integer) <= 2**53 - 1 else str(integer)
    number = float(value)
    if np.isfinite(number):
        return number
    return "NaN" if np.isnan(number) else "Infinity" if number > 0 else "-Infinity"


def _points(
    x: np.ndarray | None,
    y: np.ndarray | None,
    start: int,
    limit: int,
    bounds: tuple[float | None, float | None] | None,
) -> dict[str, Any]:
    if x is None or y is None:
        raise ValueError("The requested coordinate or intensity array is missing")
    if len(x) != len(y):
        raise ValueError("Coordinate and intensity arrays have different lengths")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("The requested arrays contain nonfinite values")
    if start > len(x):
        raise ValueError("start_index exceeds the array length")
    points = []
    lower, upper = bounds or (None, None)
    next_index = None
    for index in range(start, len(x)):
        if index % 4096 == 0:
            checkpoint("reading array", index)
        value = x[index].item()
        if (lower is not None and value < lower) or (upper is not None and value > upper):
            continue
        if len(points) == limit:
            next_index = index
            break
        points.append([_json_number(value), _json_number(y[index])])
    return {
        "points": points,
        "total_points": len(x),
        "returned_points": len(points),
        "next_index": next_index,
        "truncated": next_index is not None,
        "selection": "original array order, inclusive coordinate bounds, no downsampling",
        "coordinate_dtype": x.dtype.name,
        "intensity_dtype": y.dtype.name,
    }


class MzmlTools:
    """Read-only operations restricted to one configured data directory.

    Each call opens and closes its own reader. Gzip input uses streaming access or an
    existing embedded index, with no extracted cache or sidecar creation.
    """

    def __init__(self, root: str | Path, output_dir: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("The MCP root must be an existing directory")
        self.output_dir = Path(output_dir).expanduser().resolve(strict=True) if output_dir is not None else None
        if self.output_dir is not None and not self.output_dir.is_dir():
            raise ValueError("The output directory must be an existing directory")
        self._cache = ResultCache()
        self.jobs = JobManager()

    def _source(self, file: str, expected_revision: str | None = None) -> tuple[Path, str]:
        checkpoint("opening file")
        candidate = Path(file)
        path = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("File must be inside the configured data directory")
        if not path.is_file():
            raise ValueError("File must be an existing regular mzML file")
        if not path.name.endswith((".mzML", ".mzml", ".mzML.gz", ".mzml.gz", ".igz")):
            raise ValueError("Supported file suffixes are .mzML, .mzML.gz, and .igz")
        stat = path.stat()
        revision = f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("File revision changed. Restart the query against the current file")
        return path, revision

    def _result(self, path: Path, revision: str, data: dict[str, Any]) -> FileResult:
        self._source(str(path), revision)
        result = FileResult(path.relative_to(self.root).as_posix(), revision, data)
        encoded = json.dumps(asdict(result), allow_nan=False).encode()
        if len(encoded) > 262_144:
            raise ValueError("Result exceeds 256 KiB. Request a smaller page or a narrower selection")
        return result

    def inspect_file(self, file: str) -> FileResult[InspectData]:
        """Read file metadata, declared record counts, instrument terms, and software.

        Counts are reported by the reader and have not been validated. No binary decoding.
        Chromatogram IDs are limited to the first 100, in file order.
        """
        path, revision = self._source(file)
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            chromatograms = [c.id for c in islice(reader.chromatograms, 101)]
            data = {
                "mzml_id": reader.id,
                "mzml_version": reader.version,
                "access_strategy": reader.access_strategy,
                "spectrum_count": len(reader.spectra),
                "chromatogram_count": len(reader.chromatograms),
                "counts_validated": False,
                "chromatogram_ids": chromatograms[:100],
                "chromatogram_ids_truncated": len(chromatograms) > 100,
                "instruments": [
                    {
                        "id": instrument.id,
                        "terms": _params(instrument),
                        "sources": [_params(component) for component in instrument.source_components],
                        "analyzers": [_params(component) for component in instrument.analyzer_components],
                        "detectors": [_params(component) for component in instrument.detector_components],
                    }
                    for instrument in reader.instrument_configurations.values()
                ],
                "software": [
                    {"id": software.id, "version": software.version, "terms": _params(software)}
                    for software in reader.softwares.values()
                ],
            }
        return self._result(path, revision, data)

    def validate_file(
        self, file: str, decode_binary: bool = False, check_index: bool = False, issue_limit: int = 100
    ) -> FileResult[ValidationData]:
        """Scan the entire file for structural issues, optionally decoding arrays or checking XML offsets.

        This is not full XSD, ontology, or embedded gzip index validation. issue_limit bounds
        returned findings, not the full-file work or the validator's internal memory use.
        """
        _integer("issue_limit", issue_limit, 1, 1000)
        path, revision = self._source(file)
        report = validate(path, decode_binary=decode_binary, check_index=check_index)
        data = {
            "valid": report.valid,
            "complete": report.complete,
            "spectrum_count": report.spectrum_count,
            "chromatogram_count": report.chromatogram_count,
            "arrays_decoded": report.arrays_decoded,
            "index_entries_checked": report.index_entries_checked,
            "decode_binary": report.decode_binary,
            "check_index": report.check_index,
            "issue_count": len(report.issues),
            "issues": [asdict(issue) for issue in report.issues[:issue_limit]],
            "issues_truncated": len(report.issues) > issue_limit,
        }
        return self._result(path, revision, data)

    def find_spectra(
        self,
        file: str,
        ms_level: int | None = None,
        retention_time_min_seconds: float | None = None,
        retention_time_max_seconds: float | None = None,
        polarity: Literal["positive", "negative"] | None = None,
        precursor_mz_min: float | None = None,
        precursor_mz_max: float | None = None,
        start_index: int = 0,
        limit: int = 20,
        scan_limit: int = 10_000,
        expected_revision: str | None = None,
        spectrum_type: Literal["centroid", "profile"] | None = None,
        mobility_type: Literal["inverse_reduced", "drift_time"] | None = None,
        ion_mobility_min: float | None = None,
        ion_mobility_max: float | None = None,
        faims_voltage_min: float | None = None,
        faims_voltage_max: float | None = None,
    ) -> FileResult[SpectrumPage]:
        """Find spectra by metadata, with AND criteria and inclusive bounds, without decoding arrays.

        Precursor m/z overlaps isolation windows, with selected-ion fallback. Retention time
        matches any scan. start_index is a zero-based file position. Continue with next_index
        and the returned revision as expected_revision, keeping the same filters. An empty
        page can have a next_index. Pages may rescan earlier XML to reach start_index.
        Mobility bounds use the recorded scan quantity and require its explicit mobility_type.
        FAIMS bounds are signed volts. These filters use scan metadata, not per-peak mobility arrays.
        """
        _integer("start_index", start_index, 0)
        _integer("limit", limit, 1, 100)
        _integer("scan_limit", scan_limit, 1, 100_000)
        predicate = SpectrumFilter(
            ms_level=ms_level,
            retention_time=_range(retention_time_min_seconds, retention_time_max_seconds),
            polarity=polarity,
            precursor_mz=_range(precursor_mz_min, precursor_mz_max),
            spectrum_type=spectrum_type,
            mobility_type=mobility_type,
            ion_mobility=_range(ion_mobility_min, ion_mobility_max),
            faims_voltage=(faims_voltage_min, faims_voltage_max)
            if faims_voltage_min is not None or faims_voltage_max is not None
            else None,
        )
        path, revision = self._source(file, expected_revision)
        matches = []
        scanned = 0
        next_index = None
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            records = islice(reader.spectra, start_index, None)
            for position, spectrum in enumerate(records, start_index):
                if scanned == scan_limit or len(matches) == limit:
                    next_index = position
                    break
                checkpoint("finding spectra", position)
                scanned += 1
                if predicate.matches(spectrum):
                    matches.append({"position": position, **_spectrum(spectrum)})
        return self._result(
            path,
            revision,
            {"spectra": matches, "scanned": scanned, "next_index": next_index, "exhausted": next_index is None},
        )

    def get_spectrum(
        self,
        file: str,
        spectrum_id: str,
        include_peaks: bool = False,
        start_index: int = 0,
        limit: int = 100,
        mz_min: float | None = None,
        mz_max: float | None = None,
        expected_revision: str | None = None,
    ) -> FileResult[SpectrumData]:
        """Read an exact native spectrum ID, optionally returning up to 1000 [m/z, intensity] pairs.

        Metadata alone is the default. Peak retrieval decodes the full pair of arrays before
        paging. start_index and next_index address original array positions. Include the
        returned revision as expected_revision when continuing. Intensity units are preserved.
        """
        _integer("start_index", start_index, 0)
        _integer("limit", limit, 1, 1000)
        bounds = _range(mz_min, mz_max)
        if not include_peaks and (start_index != 0 or bounds is not None):
            raise ValueError("Peak selection requires include_peaks=True")
        path, revision = self._source(file, expected_revision)
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            spectrum = reader.spectra.get_by_id(spectrum_id)
            if spectrum.id != spectrum_id:
                raise KeyError(f"No spectrum with exact native ID {spectrum_id!r}")
            data = _spectrum(spectrum)
            data["peaks"] = None
            if include_peaks:
                data["peaks"] = _points(spectrum.mz, spectrum.intensity, start_index, limit, bounds)
                data["peaks"]["coordinate_unit"] = "m/z"
                data["peaks"]["intensity_unit"] = _array_unit(spectrum, BinaryDataArrayAccession.INTENSITY)
        return self._result(path, revision, data)

    def get_chromatogram(
        self,
        file: str,
        chromatogram_id: str,
        start_index: int = 0,
        limit: int = 100,
        time_min_seconds: float | None = None,
        time_max_seconds: float | None = None,
        expected_revision: str | None = None,
    ) -> FileResult[ChromatogramData]:
        """Read an exact chromatogram ID and up to 1000 [time in seconds, intensity] pairs.

        Decodes the full time and intensity arrays before paging in original array order.
        Unknown time units are an error. Continue with next_index and expected_revision.
        """
        _integer("start_index", start_index, 0)
        _integer("limit", limit, 1, 1000)
        bounds = _range(time_min_seconds, time_max_seconds)
        path, revision = self._source(file, expected_revision)
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            chromatogram = reader.chromatograms.get_by_id(chromatogram_id)
            if chromatogram.id != chromatogram_id:
                raise KeyError(f"No chromatogram with exact native ID {chromatogram_id!r}")
            unit = _array_unit(chromatogram, BinaryDataArrayAccession.TIME)
            factors = {
                TimeUnitAccession.MILLISECOND: 0.001,
                TimeUnitAccession.SECOND: 1.0,
                TimeUnitAccession.MINUTE: 60.0,
                TimeUnitAccession.HOUR: 3600.0,
            }
            factor = factors.get(unit["accession"])
            if factor is None and unit["accession"] is None:
                factor = {"millisecond": 0.001, "second": 1.0, "minute": 60.0, "hour": 3600.0}.get(
                    (unit["name"] or "").lower()
                )
            if factor is None:
                raise ValueError("Chromatogram time array has missing or unsupported time units")
            time = chromatogram.time
            points = _points(
                time.astype(np.float64) * factor if time is not None and factor != 1 else time,
                chromatogram.intensity,
                start_index,
                limit,
                bounds,
            )
            data = {
                "id": chromatogram.id,
                "type": chromatogram.chromatogram_type,
                "metadata": chromatogram_metadata(chromatogram),
                "coordinate_unit": "second",
                "source_time_unit": unit,
                "intensity_unit": _array_unit(chromatogram, BinaryDataArrayAccession.INTENSITY),
                **points,
            }
        return self._result(path, revision, data)

    def close(self) -> None:
        """Cancel outstanding jobs and close worker threads."""
        self.jobs.close()

    def server_info(self) -> dict[str, Any]:
        """Report supported operations, installed codecs, limits, and the Spectacular boundary."""
        import importlib.util

        return {
            "package_version": __version__,
            "transport": "stdio",
            "exports_enabled": self.output_dir is not None,
            "optional_codecs": {name: importlib.util.find_spec(name) is not None for name in ("zstd", "pynumpress")},
            "scope": "File discovery, recorded metadata, validation, unchanged data access and export.",
            "companion": "Use Spectacular for spectrum processing. Plotting belongs to a visualization client.",
            "excluded": ["peak picking", "smoothing", "normalization", "alignment", "identification", "XIC extraction"],
            "limits": {
                "response_bytes": 262144,
                "array_page": 1000,
                "record_page": 100,
                "batch_records": 20,
                "jobs": 8,
                "workers": 2,
                "job_retention_seconds": 900,
                "cache_bytes": 2097152,
                "export_bytes": 104857600,
            },
            "resources": ["mzmlpy://capabilities", "mzmlpy://guide", "mzmlpy://units", "mzmlpy://schemas"],
        }

    def list_files(
        self,
        directory: str = ".",
        pattern: str = "*",
        start_index: int = 0,
        limit: int = 100,
        expected_revision: str | None = None,
    ) -> DirectoryPage:
        """List mzML files and subdirectories in one directory, sorted by name, without opening files.

        pattern is a filename glob. Visit returned directories explicitly to explore nested data.
        Directory revision protects name pagination only. File revisions are returned separately.
        """
        import fnmatch
        import hashlib

        _integer("start_index", start_index, 0)
        _integer("limit", limit, 1, 100)
        path = (self.root / directory).resolve(strict=True)
        if not path.is_relative_to(self.root) or not path.is_dir():
            raise ValueError("Directory must be inside the configured data directory")
        if len(pattern) > 256 or "/" in pattern or "\\" in pattern:
            raise ValueError("pattern must be a filename glob with at most 256 characters")
        entries = []
        for index, entry in enumerate(path.iterdir()):
            checkpoint("listing directory", index)
            if index >= 20000:
                raise ValueError("Directory exceeds 20000 entries. Organize files into smaller directories")
            resolved = entry.resolve()
            if not resolved.is_relative_to(self.root):
                continue
            is_directory = entry.is_dir()
            if not is_directory and not (entry.is_file() and entry.name.endswith((".mzML", ".mzml", ".gz", ".igz"))):
                continue
            if not fnmatch.fnmatchcase(entry.name, pattern):
                continue
            if not is_directory:
                try:
                    _, revision = self._source(str(entry))
                except ValueError:
                    continue
            else:
                revision = None
            entries.append(
                {
                    "file": entry.relative_to(self.root).as_posix(),
                    "is_directory": is_directory,
                    "size_bytes": None if is_directory else entry.stat().st_size,
                    "revision": revision,
                }
            )
        entries.sort(key=lambda entry: entry["file"])
        revision = hashlib.sha256(json.dumps([entry["file"] for entry in entries]).encode()).hexdigest()
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("Directory contents changed. Restart listing")
        end = start_index + limit
        result: DirectoryPage = {
            "directory": path.relative_to(self.root).as_posix(),
            "revision": revision,
            "entries": entries[start_index:end],
            "next_index": end if end < len(entries) else None,
        }
        _bounded(result)
        return result

    def get_metadata(
        self,
        file: str,
        section: Literal[
            "run",
            "file_description",
            "instruments",
            "software",
            "samples",
            "processing",
            "scan_settings",
            "parameter_groups",
            "vocabularies",
            "record_lists",
        ] = "run",
        start_index: int = 0,
        limit: int = 20,
        expected_revision: str | None = None,
    ) -> FileResult[MetadataPage]:
        """Page complete header metadata, preserving CV accessions, units, user parameters and references.

        Run timestamps are returned as recorded, including timezone. Source-file locations are
        metadata only and are never opened. Binary arrays are not included.
        record_lists includes inherited processing defaults and may scan the full file.
        """
        _integer("start_index", start_index, 0)
        _integer("limit", limit, 1, 100)
        path, revision = self._source(file, expected_revision)
        if section == "record_lists":
            items = [
                item
                for kind in ("spectrum", "chromatogram")
                if (item := record_list_attributes(path, kind)) is not None
            ]
            return self._result(
                path,
                revision,
                {
                    "section": section,
                    "items": items[start_index : start_index + limit],
                    "next_index": start_index + limit if start_index + limit < len(items) else None,
                },
            )
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            sections: dict[str, list[Any]] = {
                "run": [reader.run] if reader.run else [],
                "file_description": [reader.file_description] if reader.file_description else [],
                "instruments": list(reader.instrument_configurations.values()),
                "software": list(reader.softwares.values()),
                "samples": list(reader.samples.values()),
                "processing": list(reader.data_processes.values()),
                "scan_settings": list(reader.scan_settings.values()),
                "parameter_groups": list(reader.referenceable_param_groups.values()),
                "vocabularies": list(reader.cvs.values()),
            }
            if section not in sections:
                raise ValueError("Unknown metadata section")
            items = sections[section]
            selected = items[start_index : start_index + limit]
            if section == "vocabularies":
                records = [item._asdict() for item in selected]
            elif section == "run":
                records = [
                    {
                        "attributes": dict(item.element.attrib),
                        "terms": _params(item),
                        "user_params": [asdict(param) for param in item.user_params],
                    }
                    for item in selected
                ]
            else:
                records = [metadata_tree(item) for item in selected]
        return self._result(
            path,
            revision,
            {
                "section": section,
                "items": records,
                "next_index": start_index + limit if start_index + limit < len(items) else None,
            },
        )

    def summarize_run(self, file: str, expected_revision: str | None = None) -> FileResult[SummaryData]:
        """Inventory all recorded spectrum and chromatogram metadata without decoding peaks.

        Counts, missing metadata, acquisition distributions and timing metrics are descriptive.
        This is not scientific quality scoring. Use start_job for a large file. Results are
        cached by filesystem revision in a bounded memory cache.
        """
        path, revision = self._source(file, expected_revision)
        key = json.dumps([str(path), revision, "summary"])
        data = self._cache.get(key)
        if data is None:
            with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
                data = inventory(reader)
            self._source(str(path), revision)
            self._cache.put(key, data)
        return self._result(path, revision, data)

    def compare_runs(self, files: list[str]) -> ComparisonData:
        """Compare 2 through 8 run metadata inventories and instrument settings.

        Return exact descriptive differences. No peak matching, normalization, alignment,
        signal processing, or claims about sample equivalence are performed.
        """
        if not 2 <= len(files) <= 8:
            raise ValueError("Supply 2 through 8 files")
        sources = [self._source(file) for file in files]
        if len({str(path) for path, _ in sources}) != len(sources):
            raise ValueError("Supply distinct files")
        summaries = []
        for index, (path, revision) in enumerate(sources):
            checkpoint("comparing files", index)
            summary = self.summarize_run(str(path), revision)
            instruments = self.get_metadata(str(path), section="instruments", limit=100, expected_revision=revision)
            if instruments.data["next_index"] is not None:
                raise ValueError("More than 100 instruments. Compare paged instrument metadata explicitly")
            summaries.append(
                {
                    "file": summary.file,
                    "revision": revision,
                    "summary": summary.data,
                    "instruments": instruments.data["items"],
                }
            )
        differences = {}
        for key in summaries[0]["summary"]:
            values = [item["summary"][key] for item in summaries]
            if any(value != values[0] for value in values[1:]):
                differences[key] = values
        instruments = [item["instruments"] for item in summaries]
        if any(value != instruments[0] for value in instruments[1:]):
            differences["instruments"] = instruments
        for path, revision in sources:
            self._source(str(path), revision)
        result: ComparisonData = {
            "files": [{"file": item["file"], "revision": item["revision"]} for item in summaries],
            "differences": differences,
            "scope": "Recorded metadata only. No spectra were processed.",
        }
        _bounded(result)
        return result

    def list_chromatograms(
        self, file: str, start_index: int = 0, limit: int = 100, expected_revision: str | None = None
    ) -> FileResult[ChromatogramPage]:
        """Page all stored chromatogram IDs and metadata without decoding their arrays."""
        _integer("start_index", start_index, 0)
        _integer("limit", limit, 1, 100)
        path, revision = self._source(file, expected_revision)
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            items = []
            for position, record in enumerate(
                islice(reader.chromatograms, start_index, start_index + limit + 1), start_index
            ):
                checkpoint("listing chromatograms", position)
                items.append(
                    {
                        "position": position,
                        **chromatogram_metadata(record),
                    }
                )
        return self._result(
            path,
            revision,
            {"chromatograms": items[:limit], "next_index": start_index + limit if len(items) > limit else None},
        )

    def get_spectra(
        self, file: str, spectrum_ids: list[str], expected_revision: str | None = None
    ) -> FileResult[BatchData]:
        """Read metadata for up to 20 exact native IDs in one scan, preserving request order.

        Missing IDs are reported explicitly. Duplicate requested IDs are rejected. No binary decoding.
        """
        if not 1 <= len(spectrum_ids) <= 20 or len(set(spectrum_ids)) != len(spectrum_ids):
            raise ValueError("Supply 1 through 20 distinct spectrum IDs")
        path, revision = self._source(file, expected_revision)
        wanted = set(spectrum_ids)
        records = {}
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            for position, spectrum in enumerate(reader.spectra):
                checkpoint("reading spectrum batch", position)
                if spectrum.id in wanted:
                    records[spectrum.id] = _spectrum(spectrum)
                    if len(records) == len(wanted):
                        break
        return self._result(
            path,
            revision,
            {
                "spectra": [records[id] for id in spectrum_ids if id in records],
                "missing_ids": [id for id in spectrum_ids if id not in records],
            },
        )

    def get_array(
        self,
        file: str,
        record_id: str,
        array_index: int,
        kind: Literal["spectrum", "chromatogram"] = "spectrum",
        start_index: int = 0,
        limit: int = 1000,
        expected_revision: str | None = None,
    ) -> FileResult[ArrayData]:
        """Read a slice of any reader-decoded numeric array, including mobility and charge arrays.

        array_index is its zero-based position in the record's arrays metadata. Values retain
        original units and ordering. Full-array decoding precedes paging. Nonfinite values are
        represented as the strings NaN, Infinity, or -Infinity, with no replacement or filtering.
        dtype identifies the decoded numeric type. Integers outside the interoperable JSON
        range of -(2**53-1) through 2**53-1 use exact decimal strings. Numpress reconstructs float64.
        """
        _integer("array_index", array_index, 0)
        _integer("start_index", start_index, 0)
        _integer("limit", limit, 1, 1000)
        if kind not in {"spectrum", "chromatogram"}:
            raise ValueError("kind must be spectrum or chromatogram")
        path, revision = self._source(file, expected_revision)
        with Mzml(path, in_memory=False, gzip_mode="stream") as reader:
            lookup = reader.spectra if kind == "spectrum" else reader.chromatograms
            record = lookup.get_by_id(record_id)
            if record.id != record_id:
                raise KeyError(f"No record with exact native ID {record_id!r}")
            arrays = record.binary_arrays
            if array_index >= len(arrays):
                raise ValueError("array_index exceeds the record's array count")
            array = arrays[array_index]
            checkpoint("decoding array")
            values = array.data
            if start_index > len(values):
                raise ValueError("start_index exceeds the array length")
            result = [_json_number(value) for value in values[start_index : start_index + limit]]
        return self._result(
            path,
            revision,
            {
                "record_id": record_id,
                "kind": kind,
                "array_index": array_index,
                "metadata": array_metadata(array),
                "values": result,
                "dtype": values.dtype.name,
                "total_values": len(values),
                "next_index": start_index + limit if start_index + limit < len(values) else None,
                "value_representation": (
                    "Native decoded values in recorded units. Large integers use decimal strings, "
                    "nonfinite floats use NaN/Infinity/-Infinity. Numpress reconstructs float64."
                ),
            },
        )

    def start_job(
        self,
        operation: Literal["summarize_run", "validate_file", "compare_runs", "export_records"],
        arguments: dict[str, Any],
    ) -> JobStatus:
        """Start a long operation and return immediately. Poll get_job, or request cancel_job.

        arguments must match the named tool's parameters. At most eight jobs are retained.
        Jobs and results expire after 15 minutes and do not survive server restart.
        """
        import inspect

        operations = {
            "summarize_run": self.summarize_run,
            "validate_file": self.validate_file,
            "compare_runs": self.compare_runs,
        }
        if self.output_dir is not None:
            operations["export_records"] = self.export_records
        if operation not in operations:
            raise ValueError("Unsupported operation, or exports are not enabled")
        function = operations[operation]
        try:
            inspect.signature(function).bind(**arguments)
        except TypeError as error:
            raise ValueError(str(error)) from error
        # Snapshot arguments so direct Python callers cannot mutate a queued request.
        copied = json.loads(json.dumps(arguments, allow_nan=False))
        return self.jobs.submit(operation, lambda: function(**copied))

    def get_job(self, job_id: str) -> JobStatus:
        """Get job state, progress stage, completed units, result, or error."""
        return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> JobStatus:
        """Request cooperative cancellation. Poll until cancelled or already completed.

        Cancellation is checked between records, XML events, and export writes. It can wait
        for reader initialization, decompression, or a single array decode to finish.
        """
        return self.jobs.cancel(job_id)

    def release_job(self, job_id: str) -> dict[str, bool]:
        """Discard a finished job result to free a slot. Exported files remain available."""
        return self.jobs.release(job_id)

    def export_records(
        self,
        file: str,
        record_ids: list[str],
        kind: Literal["spectrum", "chromatogram"] = "spectrum",
        expected_revision: str | None = None,
    ) -> FileResult[ArtifactData]:
        """Export 1 through 100 exact records to JSONL with recorded binary encodings and provenance.

        Requires --output-dir. Generated artifact names never overwrite inputs. Each line
        includes record metadata and original encoded binary text, for downstream readers such
        as Spectacular. No arrays are decoded, processed, or plotted. Maximum output is 100 MiB.
        """
        from ._mcp_export import export_records

        if self.output_dir is None:
            raise ValueError("Exports require a configured output directory")
        if kind not in {"spectrum", "chromatogram"}:
            raise ValueError("kind must be spectrum or chromatogram")
        if not 1 <= len(record_ids) <= 100 or len(set(record_ids)) != len(record_ids):
            raise ValueError("Supply 1 through 100 distinct record IDs")
        path, revision = self._source(file, expected_revision)
        result = export_records(self, path, revision, record_ids, kind)
        # The export function verifies the source immediately before publishing the artifact.
        return FileResult(path.relative_to(self.root).as_posix(), revision, result)

    def read_export(self, artifact_id: str, start_line: int = 0, limit: int = 1) -> ExportPage:
        """Read a bounded page of an exported JSONL artifact from this output directory."""
        from ._mcp_export import read_export

        if self.output_dir is None:
            raise ValueError("Exports require a configured output directory")
        _integer("start_line", start_line, 0)
        _integer("limit", limit, 1, 20)
        result = read_export(self.output_dir, artifact_id, start_line, limit)
        _bounded(result)
        return result


def _array_unit(record: Any, accession: BinaryDataArrayAccession) -> dict[str, str | None]:
    array = record.get_binary_array(accession)
    param = array.get_cvparm(accession) if array is not None else None
    return {"accession": param.unit_accession if param else None, "name": param.unit_name if param else None}


def create_server(root: str | Path, output_dir: str | Path | None = None) -> "MCPServer":
    """Create a local server with optional exports restricted to a separate output directory."""
    try:
        from ._mcp_server import build_server
    except ImportError as error:
        raise ImportError('MCP support requires pip install "mzmlpy[mcp]"') from error
    return build_server(root, output_dir)
