"""0.10 renames, point queries, retention-time bisection and indexed span parsing."""

import warnings
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from mzmlpy import Chromatogram, Mzml, MzmlError, Spectrum
from mzmlpy.file_classes.standardMzml import StandardMzml
from mzmlpy.mcp import MzmlTools

NS = "http://psi.hupo.org/ms/mzml"
EMPTY_ARRAYS = '<binaryDataArrayList count="0"/>'


def spectrum_xml(index: int, rt: float | None, *, ms_level: int = 1, extra: str = "") -> str:
    scan = (
        f'<scanList count="1"><scan><cvParam cvRef="MS" accession="MS:1000016" name="scan start time" '
        f'value="{rt}" unitAccession="UO:0000010" unitName="second"/></scan></scanList>'
        if rt is not None
        else ""
    )
    return (
        f'<spectrum index="{index}" id="scan={index}" defaultArrayLength="0">'
        f'<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="{ms_level}"/>'
        f"{scan}{extra}{EMPTY_ARRAYS}</spectrum>"
    )


def write_indexed(
    path: Path, spectra: list[str], *, omit: frozenset[str] = frozenset(), encoding: str = "utf-8"
) -> Path:
    """Write an indexedmzML whose index lists every spectrum id except those in ``omit``."""
    head = f'<?xml version="1.0" encoding="{encoding}"?>\n<indexedmzML xmlns="{NS}"><mzML xmlns="{NS}"><run id="r">'
    head += f'<spectrumList count="{len(spectra)}">'
    body = head.encode(encoding)
    offsets: list[tuple[str, int]] = []
    for xml in spectra:
        identifier = ET.fromstring(xml).get("id") or ""
        offsets.append((identifier, len(body)))
        body += xml.encode(encoding)
    body += "</spectrumList></run></mzML>".encode(encoding)
    index_offset = len(body)
    entries = "".join(f'<offset idRef="{i}">{o}</offset>' for i, o in offsets if i not in omit)
    body += (
        f'<indexList count="1"><index name="spectrum">{entries}</index></indexList>'
        f"<indexListOffset>{index_offset}</indexListOffset></indexedmzML>"
    ).encode(encoding)
    path.write_bytes(body)
    return path


def ordered_run(tmp_path: Path, times: list[float | None]) -> Path:
    return write_indexed(tmp_path / "run.mzML", [spectrum_xml(i, t) for i, t in enumerate(times)])


# ---------------------------------------------------------------- precursor shortcuts
PRECURSOR = """<spectrum id="s"><precursorList count="1"><precursor>
<isolationWindow><cvParam accession="MS:1000827" value="500"/><cvParam accession="MS:1000828" value="1.5"/>
<cvParam accession="MS:1000829" value="0.5"/></isolationWindow>
<selectedIonList count="1"><selectedIon><cvParam accession="MS:1000744" value="500.25"/>
<cvParam accession="MS:1000041" value="3"/></selectedIon></selectedIonList>
<activation><cvParam accession="MS:1000133"/><cvParam accession="MS:1000045" value="27"/></activation>
</precursor></precursorList></spectrum>"""


def test_spectrum_precursor_shortcuts() -> None:
    spectrum = Spectrum(ET.fromstring(PRECURSOR))
    window = spectrum.precursors[0].isolation_window
    assert window is not None
    assert window.isolation_mz == 500.0
    assert window.isolation_width == 2.0
    assert window.isolation_mz_range == (498.5, 500.5)
    assert spectrum.precursor_mz == 500.25
    assert spectrum.charge == 3
    assert spectrum.collision_energy == 27.0
    assert spectrum.isolation_mz_range == (498.5, 500.5)
    assert spectrum.precursors is spectrum.precursors  # cached


@pytest.mark.parametrize(
    "xml",
    [
        "<spectrum/>",
        "<spectrum><precursorList><precursor/></precursorList></spectrum>",
        "<spectrum><precursorList><precursor><selectedIonList/><isolationWindow/></precursor></precursorList></spectrum>",
    ],
)
def test_spectrum_precursor_shortcuts_are_none_when_absent(xml: str) -> None:
    spectrum = Spectrum(ET.fromstring(xml))
    assert (spectrum.precursor_mz, spectrum.charge, spectrum.collision_energy, spectrum.isolation_mz_range) == (
        None,
        None,
        None,
        None,
    )
    for precursor in spectrum.precursors:
        if precursor.isolation_window is not None:
            assert precursor.isolation_window.isolation_width is None


# ---------------------------------------------------------------- Chromatogram.rt
def chromatogram(unit: str, values: np.ndarray) -> Chromatogram:
    import base64

    encoded = base64.b64encode(values.astype("<f8").tobytes()).decode()
    return Chromatogram(
        ET.fromstring(
            f'<chromatogram id="tic" defaultArrayLength="{len(values)}"><binaryDataArrayList count="1">'
            f'<binaryDataArray><cvParam accession="MS:1000523"/><cvParam accession="MS:1000576"/>'
            f'<cvParam accession="MS:1000595" {unit}/><binary>{encoded}</binary></binaryDataArray>'
            "</binaryDataArrayList></chromatogram>"
        )
    )


def test_chromatogram_rt_converts_minutes_to_seconds() -> None:
    rt = chromatogram('unitAccession="UO:0000031" unitName="minute"', np.array([1.0, 2.5])).rt
    assert rt is not None and rt.dtype == np.float64
    np.testing.assert_array_equal(rt, [60.0, 150.0])


def test_chromatogram_rt_without_unit_warns_and_assumes_seconds() -> None:
    with pytest.warns(UserWarning, match="chromatogram time array"):
        rt = chromatogram('unitAccession="UO:0000999"', np.array([3.0])).rt
    np.testing.assert_array_equal(rt, [3.0])


def test_chromatogram_without_time_array_has_no_rt() -> None:
    assert Chromatogram(ET.fromstring('<chromatogram id="x"/>')).rt is None


# ---------------------------------------------------------------- point queries
def test_point_queries_follow_tdfpy(tmp_path: Path) -> None:
    extra = (
        '<precursorList count="1"><precursor><selectedIonList count="1"><selectedIon>'
        '<cvParam accession="MS:1000744" value="500.0"/></selectedIon></selectedIonList></precursor></precursorList>'
    )
    path = write_indexed(tmp_path / "p.mzML", [spectrum_xml(0, 10.0), spectrum_xml(1, 50.0, ms_level=2, extra=extra)])
    with Mzml(path) as reader:
        assert [s.id for s in reader.spectra.filter(rt=40.0, rt_tolerance=15.0)] == ["scan=1"]
        assert [s.id for s in reader.spectra.filter(rt=5.0)] == ["scan=0"]  # lower bound clamps at 0
        assert [s.id for s in reader.spectra.filter(precursor_mz=500.009, mz_tolerance=20)] == ["scan=1"]
        assert list(reader.spectra.filter(precursor_mz=500.02, mz_tolerance=20)) == []
        assert [s.id for s in reader.spectra.filter(precursor_mz=500.4, mz_tolerance=0.5, mz_tolerance_type="da")] == [
            "scan=1"
        ]
    with Mzml(path) as reader, pytest.raises(MzmlError, match="rt_range"):
        reader.spectra.filter(rt=(1.0, 2.0))  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------- retention-time bisection
TIMES = [float(t) for t in range(0, 200, 2)]


@pytest.mark.parametrize("window", [(None, 10.0), (51.0, 60.0), (100.0, None), (500.0, 600.0), (0.0, 0.0), (7.0, 7.5)])
@pytest.mark.parametrize("in_memory", [False, True])
def test_rt_bisect_matches_a_linear_scan(tmp_path: Path, window, in_memory: bool) -> None:
    path = ordered_run(tmp_path, TIMES)
    with Mzml(path, in_memory=in_memory) as reader:
        expected = [s.id for s in reader.spectra if s.rt is not None and _inside(s.rt, window)]
        assert [s.id for s in reader.spectra.filter(rt_range=window)] == expected


def _inside(value: float, window: tuple[float | None, float | None]) -> bool:
    lower, upper = window
    return (lower is None or value >= lower) and (upper is None or value <= upper)


def test_rt_bisect_skips_spectra_without_times(tmp_path: Path) -> None:
    times: list[float | None] = [t if i % 3 else None for i, t in enumerate(TIMES)]
    path = ordered_run(tmp_path, times)
    with Mzml(path) as reader:
        assert [s.rt for s in reader.spectra.filter(rt_range=(40.0, 50.0))] == [40.0, 44.0, 46.0, 50.0]


def test_rt_bisect_falls_back_to_a_scan_when_times_are_sparse(tmp_path: Path) -> None:
    times: list[float | None] = [None] * 150
    times[140] = 5.0
    path = ordered_run(tmp_path, times)
    with Mzml(path) as reader:
        assert [s.id for s in reader.spectra.filter(rt_range=(1.0, 9.0))] == ["scan=140"]


def test_stream_reader_filters_by_rt_without_random_access(tmp_path: Path) -> None:
    import gzip

    source = ordered_run(tmp_path, TIMES)
    gz = tmp_path / "run.mzML.gz"
    gz.write_bytes(gzip.compress(source.read_bytes()))
    with Mzml(gz, gzip_mode="stream") as reader:
        assert [s.rt for s in reader.spectra.filter(rt_range=(10.0, 14.0))] == [10.0, 12.0, 14.0]


# ---------------------------------------------------------------- indexed span parsing
def test_iteration_recovers_a_record_missing_from_the_index(tmp_path: Path) -> None:
    spectra = [spectrum_xml(i, float(i)) for i in range(6)]
    path = write_indexed(tmp_path / "gap.mzML", spectra, omit=frozenset({"scan=3"}))
    with Mzml(path) as reader:
        backend = reader._file_object.file_handler  # noqa: SLF001
        assert isinstance(backend, StandardMzml)
        assert [s.id for s in reader.spectra] == [f"scan={i}" for i in range(6)]
        assert reader.spectra["scan=2"].rt == 2.0  # its span also holds scan=3, so it is parsed by streaming


def test_span_parsing_rejects_anything_but_the_indexed_record(tmp_path: Path) -> None:
    path = ordered_run(tmp_path, [1.0, 2.0])
    with Mzml(path) as reader:
        backend = reader._file_object.file_handler  # noqa: SLF001
        assert isinstance(backend, StandardMzml)
        good = spectrum_xml(0, 1.0).encode()
        assert backend.parse_span(good, "spectrum", "scan=0") is not None
        assert backend.parse_span(good, "spectrum", "scan=9") is None  # wrong id
        assert backend.parse_span(good, "chromatogram") is None  # wrong kind
        assert backend.parse_span(b'<spectrum id="scan=0"/>', "spectrum") is None  # self-closing
        assert backend.parse_span(good[:-20], "spectrum") is None  # truncated
        assert backend.parse_span(good + good, "spectrum") is None  # two records
        assert backend.parse_span(good.replace(b"<cvParam", b"<cvParam <", 1), "spectrum") is None  # malformed


@pytest.mark.parametrize("encoding", ["utf-16", "no-such-codec"])
def test_non_ascii_compatible_encoding_uses_the_streaming_parser(tmp_path: Path, encoding: str) -> None:
    path = ordered_run(tmp_path, [0.0, 1.0, 2.0])
    with Mzml(path) as reader:
        backend = reader._file_object.file_handler  # noqa: SLF001
        assert isinstance(backend, StandardMzml)
        backend.encoding = encoding  # as if declared by the file; checked before any span is parsed
        assert not backend.can_iterate_indexed("spectrum")
        assert backend.parse_span(spectrum_xml(0, 0.0).encode(), "spectrum") is None


def test_duplicate_ids_disable_indexed_iteration(tmp_path: Path) -> None:
    spectra = [spectrum_xml(0, 1.0), spectrum_xml(1, 2.0).replace("scan=1", "scan=0")]
    path = tmp_path / "dup.mzML"
    path.write_text(f'<mzML xmlns="{NS}"><run><spectrumList count="2">{"".join(spectra)}</spectrumList></run></mzML>')
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with Mzml(path) as reader:
            backend = reader._file_object.file_handler  # noqa: SLF001
            assert isinstance(backend, StandardMzml)
            assert not backend.can_iterate_indexed("spectrum")
            assert [s.rt for s in reader.spectra] == [1.0, 2.0]


def test_random_access_handle_is_closed_with_the_reader(tmp_path: Path) -> None:
    path = ordered_run(tmp_path, [1.0, 2.0])
    reader = Mzml(path)
    backend = reader._file_object.file_handler  # noqa: SLF001
    assert reader.spectra[1].rt == 2.0
    handle = backend._record_handle  # noqa: SLF001
    assert handle is not None and not handle.closed
    reader.close()
    assert handle.closed


# ---------------------------------------------------------------- MCP mobility mapping
def test_mcp_mobility_bounds_map_to_the_named_quantity(tmp_path: Path) -> None:
    extra = '<scanList count="1"><scan><cvParam accession="MS:1002815" value="1.1"/></scan></scanList>'
    write_indexed(tmp_path / "im.mzML", [spectrum_xml(0, None, extra=extra), spectrum_xml(1, 3.0)])
    tools = MzmlTools(tmp_path)
    try:
        found = tools.find_spectra("im.mzML", mobility_type="inverse_reduced", ion_mobility_min=1.0).data
        assert [s["id"] for s in found["spectra"]] == ["scan=0"]
        assert tools.find_spectra("im.mzML", mobility_type="drift_time").data["spectra"] == []
        with pytest.raises(ValueError, match="explicit mobility_type"):
            tools.find_spectra("im.mzML", ion_mobility_min=1.0)
        with pytest.raises(ValueError, match="inverse_reduced or drift_time"):
            tools.find_spectra("im.mzML", mobility_type="k0")  # ty: ignore[invalid-argument-type]
    finally:
        tools.close()
