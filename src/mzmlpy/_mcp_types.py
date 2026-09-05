"""Output contracts exposed in MCP tool schemas, without an SDK runtime dependency."""

from typing import Any, Literal, NotRequired, TypedDict


class SpectrumData(TypedDict):
    id: str
    index: int | None
    ms_level: int | None
    polarity: str | None
    spectrum_type: str | None
    default_array_length: int | None
    attributes: dict[str, str]
    structure: dict[str, Any]
    terms: list[dict[str, Any]]
    user_params: list[dict[str, Any]]
    retention_times_seconds: list[float | None]
    scans: list[dict[str, Any]]
    precursors: list[dict[str, Any]]
    products: list[dict[str, Any]]
    arrays: list[dict[str, Any]]
    position: NotRequired[int]
    peaks: NotRequired[dict[str, Any] | None]


class SpectrumPage(TypedDict):
    spectra: list[SpectrumData]
    scanned: int
    next_index: int | None
    exhausted: bool


class MetadataPage(TypedDict):
    section: str
    items: list[dict[str, Any]]
    next_index: int | None


class BatchData(TypedDict):
    spectra: list[SpectrumData]
    missing_ids: list[str]


class ArrayData(TypedDict):
    record_id: str
    kind: Literal["spectrum", "chromatogram"]
    array_index: int
    metadata: dict[str, Any]
    values: list[int | float | str]
    dtype: str
    total_values: int
    next_index: int | None
    value_representation: str


class InspectData(TypedDict):
    mzml_id: str
    mzml_version: str
    access_strategy: str
    spectrum_count: int
    chromatogram_count: int
    counts_validated: bool
    chromatogram_ids: list[str]
    chromatogram_ids_truncated: bool
    instruments: list[dict[str, Any]]
    software: list[dict[str, Any]]


class ValidationData(TypedDict):
    valid: bool
    complete: bool
    spectrum_count: int
    chromatogram_count: int
    arrays_decoded: int
    index_entries_checked: int
    decode_binary: bool
    check_index: bool
    issue_count: int
    issues: list[dict[str, str]]
    issues_truncated: bool


class ChromatogramData(TypedDict):
    id: str
    type: str | None
    metadata: dict[str, Any]
    coordinate_unit: str
    source_time_unit: dict[str, str | None]
    intensity_unit: dict[str, str | None]
    points: list[list[int | float | str]]
    coordinate_dtype: str
    intensity_dtype: str
    total_points: int
    returned_points: int
    next_index: int | None
    truncated: bool
    selection: str


class ChromatogramPage(TypedDict):
    chromatograms: list[dict[str, Any]]
    next_index: int | None


class SummaryData(TypedDict):
    spectrum_count: int
    chromatogram_count: int
    ms_levels: dict[str, int]
    polarities: dict[str, int]
    spectrum_types: dict[str, int]
    array_types: dict[str, int]
    compressions: dict[str, int]
    empty_spectra_declared: int
    missing_retention_time: int
    spectra_with_multiple_scans: int
    retention_time_min_seconds: float | None
    retention_time_max_seconds: float | None
    retention_time_span_seconds: float | None
    first_scan_time_regressions: int
    largest_adjacent_first_scan_gap_seconds: float | None
    declared_array_length_min: int | None
    declared_array_length_max: int | None
    spectra_with_ion_mobility: int
    isolation_windows: list[dict[str, float | None]]
    isolation_windows_truncated: bool
    binary_arrays_decoded: bool
    scope: str


class FileEntry(TypedDict):
    file: str
    is_directory: bool
    size_bytes: int | None
    revision: str | None


class DirectoryPage(TypedDict):
    directory: str
    revision: str
    entries: list[FileEntry]
    next_index: int | None


class ComparisonData(TypedDict):
    files: list[dict[str, str]]
    differences: dict[str, list[Any]]
    scope: str


class ArtifactData(TypedDict):
    artifact_id: str
    path: str
    uri: str
    format: str
    format_version: int
    record_count: int
    byte_count: int
    sha256: str
    processing_applied: bool


class ExportPage(TypedDict):
    artifact_id: str
    lines: list[dict[str, Any]]
    next_line: int | None
