"""0.10 renames, point queries, the retention-time table and indexed span parsing."""

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
    path: Path,
    spectra: list[str],
    *,
    omit: frozenset[str] = frozenset(),
    encoding: str = "utf-8",
    before_run: str = "",
) -> Path:
    """Write an indexedmzML whose index lists every spectrum id except those in ``omit``."""
    head = f'<?xml version="1.0" encoding="{encoding}"?>\n<indexedmzML xmlns="{NS}"><mzML xmlns="{NS}">'
    head += f'{before_run}<run id="r">'
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
    assert spectrum.precursor_charge == 3
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
    assert (
        spectrum.precursor_mz,
        spectrum.precursor_charge,
        spectrum.collision_energy,
        spectrum.isolation_mz_range,
    ) == (
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
        assert [s.id for s in reader.spectra.filter(precursor_mz=500.4, mz_tolerance=0.5, mz_tolerance_unit="da")] == [
            "scan=1"
        ]
    with Mzml(path) as reader, pytest.raises(MzmlError, match="rt_range"):
        reader.spectra.filter(rt=(1.0, 2.0))  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------- retention-time table
TIMES = [float(t) for t in range(0, 200, 2)]


@pytest.mark.parametrize("window", [(None, 10.0), (51.0, 60.0), (100.0, None), (500.0, 600.0), (0.0, 0.0), (7.0, 7.5)])
@pytest.mark.parametrize("in_memory", [False, True])
def test_rt_filter_matches_a_linear_scan(tmp_path: Path, window, in_memory: bool) -> None:
    path = ordered_run(tmp_path, TIMES)
    with Mzml(path, in_memory=in_memory) as reader:
        expected = [s.id for s in reader.spectra if s.rt is not None and _inside(s.rt, window)]
        assert [s.id for s in reader.spectra.filter(rt_range=window)] == expected


def _inside(value: float, window: tuple[float | None, float | None]) -> bool:
    lower, upper = window
    return (lower is None or value >= lower) and (upper is None or value <= upper)


def test_rt_filter_skips_spectra_without_times(tmp_path: Path) -> None:
    times: list[float | None] = [t if i % 3 else None for i, t in enumerate(TIMES)]
    path = ordered_run(tmp_path, times)
    with Mzml(path) as reader:
        assert [s.rt for s in reader.spectra.filter(rt_range=(40.0, 50.0))] == [40.0, 44.0, 46.0, 50.0]


def test_rt_filter_finds_a_lone_time_among_many_missing(tmp_path: Path) -> None:
    times: list[float | None] = [None] * 150
    times[140] = 5.0
    path = ordered_run(tmp_path, times)
    with Mzml(path) as reader:
        assert [s.id for s in reader.spectra.filter(rt_range=(1.0, 9.0))] == ["scan=140"]


OUT_OF_ORDER = [30.0, 2.0, 100.0, 4.0, 4.0, 60.0, 0.0, 58.0, 7.5, 190.0, 1.0, 59.0, 31.0, 3.0]


@pytest.mark.parametrize("window", [(None, 10.0), (3.0, 31.0), (58.0, 60.0), (100.0, None), (4.0, 4.0)])
@pytest.mark.parametrize("in_memory", [False, True])
def test_rt_filter_on_a_file_out_of_rt_order_matches_a_linear_scan(tmp_path: Path, window, in_memory: bool) -> None:
    """Merged or re-sorted files are not in retention-time order; the filter must not assume it."""
    path = ordered_run(tmp_path, [*OUT_OF_ORDER, *reversed(TIMES)])
    with Mzml(path, in_memory=in_memory) as reader:
        expected = [s.id for s in reader.spectra if s.rt is not None and _inside(s.rt, window)]
        assert expected  # otherwise the window tests nothing
        assert [s.id for s in reader.spectra.filter(rt_range=window)] == expected
        assert [s.id for s in reader.spectra.filter(rt_range=window, ms_level=1)] == expected


def test_rt_table_is_built_once_and_reused(tmp_path: Path) -> None:
    path = ordered_run(tmp_path, OUT_OF_ORDER)
    with Mzml(path) as reader:
        assert reader.spectra._rt_table is None
        assert [s.rt for s in reader.spectra.filter(rt_range=(0.0, 2.0))] == [2.0, 0.0, 1.0]
        table = reader.spectra._rt_table
        assert table is not None and list(table) == [(t,) for t in OUT_OF_ORDER]
        assert [s.rt for s in reader.spectra.filter(rt=60.0, rt_tolerance=1.0)] == [60.0, 59.0]
        assert reader.spectra._rt_table is table


def test_rt_filter_scans_every_spectrum_when_the_index_is_incomplete(tmp_path: Path) -> None:
    spectra = [spectrum_xml(i, t) for i, t in enumerate(OUT_OF_ORDER)]
    spectra[5] = spectra[5].replace('id="scan=5"', 'id="scan=4"')
    path = tmp_path / "dup.mzML"
    path.write_text(f'<mzML xmlns="{NS}"><run><spectrumList count="14">{"".join(spectra)}</spectrumList></run></mzML>')
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with Mzml(path) as reader:
            expected = [s.rt for s in reader.spectra if s.rt is not None and _inside(s.rt, (0.0, 5.0))]
            assert (
                [s.rt for s in reader.spectra.filter(rt_range=(0.0, 5.0))] == expected == [2.0, 4.0, 4.0, 0.0, 1.0, 3.0]
            )
            assert reader.spectra._rt_table is None


def _scan(cv: str, window: str = "") -> str:
    return f"<scan>{cv}{window}</scan>"


RT_CV = '<cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{v}" unitAccession="{u}"/>'
SECONDS = "UO:0000010"
WINDOW = '<scanWindowList count="1"><scanWindow>{}</scanWindow></scanWindowList>'
# name -> (scanList inner XML, XML after the scan list, whether the byte reader answers without a parse)
HEAD_CASES: dict[str, tuple[str, str, bool]] = {
    "seconds": (_scan(RT_CV.format(v=12.5, u=SECONDS)), "", True),
    "minutes": (_scan(RT_CV.format(v=1.5, u="UO:0000031")), "", True),
    "milliseconds": (_scan(RT_CV.format(v=1500, u="UO:0000028")), "", True),
    "hours": (_scan(RT_CV.format(v=0.01, u="UO:0000032")), "", True),
    "two scans": (_scan(RT_CV.format(v=1.0, u=SECONDS)) + _scan(RT_CV.format(v=2.0, u=SECONDS)), "", True),
    "scan without a time": (_scan("") + _scan(RT_CV.format(v=3.0, u=SECONDS)), "", True),
    "not finite": (_scan(RT_CV.format(v="nan", u=SECONDS)), "", True),
    "no scan list": ("", "", True),
    "time before its scan window": (_scan(RT_CV.format(v=1.0, u=SECONDS), WINDOW.format("")), "", True),
    "scan with attributes": (
        f'<scan instrumentConfigurationRef="IC1">{RT_CV.format(v=9.0, u=SECONDS)}</scan>',
        "",
        True,
    ),
    "unit name only": (
        _scan('<cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="2" unitName="minute"/>'),
        "",
        False,
    ),
    "no unit": (_scan('<cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="4"/>'), "", False),
    "single quotes": (
        _scan(
            "<cvParam cvRef='MS' accession='MS:1000016' name='scan start time' value='5' unitAccession='UO:0000010'/>"
        ),
        "",
        False,
    ),
    "two times in one scan": (_scan(RT_CV.format(v=1.0, u=SECONDS) + RT_CV.format(v=2.0, u=SECONDS)), "", False),
    "time in a scan window": (
        _scan(RT_CV.format(v=1.0, u=SECONDS), WINDOW.format(RT_CV.format(v=8.0, u=SECONDS))),
        "",
        False,
    ),
    "time only in a scan window": (_scan("", WINDOW.format(RT_CV.format(v=8.0, u=SECONDS))), "", False),
    "time after the scan list": (
        _scan(""),
        f'<precursorList count="1"><precursor><activation>{RT_CV.format(v=6.0, u=SECONDS)}</activation>'
        "</precursor></precursorList>",
        False,
    ),
    "name with another accession": (
        _scan(
            '<cvParam cvRef="MS" accession="MS:0000000" name="scan start time" value="7" unitAccession="UO:0000010"/>'
        ),
        "",
        False,
    ),
    "user param named like the term": (_scan('<userParam name="scan start time" value="3"/>'), "", False),
    "param group": ('<scan><referenceableParamGroupRef ref="g"/></scan>', "", False),
    "entity in the head": (_scan(RT_CV.format(v=1.0, u=SECONDS) + '<userParam name="a&amp;b"/>'), "", False),
}
PARAM_GROUPS = (
    '<referenceableParamGroupList count="1"><referenceableParamGroup id="g">'
    + RT_CV.format(v=11.0, u=SECONDS)
    + "</referenceableParamGroup></referenceableParamGroupList>"
)


@pytest.mark.parametrize("case", list(HEAD_CASES))
def test_rt_table_agrees_with_parsed_scans(tmp_path: Path, case: str) -> None:
    """The byte reader either gives exactly the parsed scan times or defers to a full parse."""
    from mzmlpy.lookup import _head_scan_rts, _scan_rts

    inner, after, fast = HEAD_CASES[case]
    scan_list = f'<scanList count="1">{inner}</scanList>' if inner else ""
    path = write_indexed(
        tmp_path / "h.mzML",
        [spectrum_xml(0, 1.0), spectrum_xml(1, None, extra=scan_list + after)],
        before_run=PARAM_GROUPS if case == "param group" else "",
    )
    with Mzml(path) as reader, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        heads = list(reader._file_object.iter_spectrum_heads() or [])
        assert len(heads) == 2 and heads[1] is not None
        assert (_head_scan_rts(heads[1]) is not None) is fast
        expected = [tuple(_scan_rts(s)) for s in reader.spectra]
        assert list(reader.spectra._scan_rt_table(2) or []) == expected


def test_rt_table_reports_a_bad_time_like_a_linear_scan(tmp_path: Path) -> None:
    bad = f'<scanList count="1">{_scan(RT_CV.format(v="soon", u=SECONDS))}</scanList>'
    path = write_indexed(tmp_path / "bad.mzML", [spectrum_xml(0, 1.0), spectrum_xml(1, None, extra=bad)])
    with Mzml(path) as reader, pytest.raises(MzmlError, match="soon"):
        list(reader.spectra.filter(rt_range=(0.0, 5.0)))


def test_spectrum_heads_are_cut_only_when_exact() -> None:
    from mzmlpy.file_classes.standardMzml import _spectrum_head

    assert _spectrum_head(b'  <spectrum id="a" index="0"><binaryDataArrayList/>', "a") == b'<spectrum id="a" index="0">'
    assert _spectrum_head(b'<ms:spectrum\nid="a&amp;b"><ms:binaryDataArrayList/>', "a&b") is not None
    assert _spectrum_head(b'<spectrum xid="a"><binaryDataArrayList/>', "a") is None  # a different attribute
    assert _spectrum_head(b'<spectrum id="b"><binaryDataArrayList/>', "a") is None  # a different record
    assert _spectrum_head(b'<chromatogram id="a"><binaryDataArrayList/>', "a") is None
    assert _spectrum_head(b'<spectrum id="a">' + b" " * 100, "a") is None  # no arrays within the read
    assert _spectrum_head(b"garbage", "a") is None


def test_rt_table_handles_namespace_prefixed_records(tmp_path: Path) -> None:
    from mzmlpy.lookup import _head_scan_rts

    head = (
        b'<ms:spectrum id="a"><ms:scanList count="1"><ms:scan>'
        b'<ms:cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="2" unitAccession="UO:0000031"/>'
        b"</ms:scan></ms:scanList>"
    )
    assert _head_scan_rts(head) == (120.0,)


def test_spectrum_charge_is_gone(tmp_path: Path) -> None:
    """0.9's per-point ``Spectrum.charge`` must fail loudly, not turn into the precursor charge."""
    path = ordered_run(tmp_path, [1.0])
    with Mzml(path) as reader:
        spectrum = reader.spectra[0]
        with pytest.raises(AttributeError):
            spectrum.charge  # noqa: B018  # ty: ignore[unresolved-attribute]
        assert spectrum.precursor_charge is None


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
        found = tools.find_spectra("im.mzML", mobility_type="ook0", mobility_min=1.0).data
        assert [s["id"] for s in found["spectra"]] == ["scan=0"]
        assert tools.find_spectra("im.mzML", mobility_type="drift_time").data["spectra"] == []
        with pytest.raises(ValueError, match="explicit mobility_type"):
            tools.find_spectra("im.mzML", mobility_min=1.0)
        with pytest.raises(ValueError, match="ook0 or drift_time"):
            tools.find_spectra("im.mzML", mobility_type="k0")  # ty: ignore[invalid-argument-type]
    finally:
        tools.close()


def test_mcp_json_keys_match_reader_attribute_names(tmp_path: Path) -> None:
    extra = (
        '<scanList count="1"><scan>'
        '<cvParam accession="MS:1000016" value="12.5" unitAccession="UO:0000010" unitName="second"/>'
        '<cvParam accession="MS:1002815" value="1.1"/></scan></scanList>'
        '<precursorList count="1"><precursor><isolationWindow>'
        '<cvParam accession="MS:1000827" value="500.0"/><cvParam accession="MS:1000828" value="1.0"/>'
        '<cvParam accession="MS:1000829" value="1.5"/></isolationWindow></precursor></precursorList>'
    )
    write_indexed(tmp_path / "keys.mzML", [spectrum_xml(0, None, ms_level=2, extra=extra)])
    tools = MzmlTools(tmp_path)
    try:
        spectrum = tools.find_spectra("keys.mzML").data["spectra"][0]
        assert "retention_times_seconds" not in spectrum
        scan = spectrum["scans"][0]
        assert (scan["rt"], scan["ook0"], scan["drift_time"]) == (12.5, 1.1, None)
        assert "inverse_reduced_ion_mobility" not in scan and "ion_mobility_drift_time" not in scan
        summary = tools.summarize_run("keys.mzML").data
        assert summary["isolation_windows"] == [{"isolation_mz": 500.0, "lower_offset": 1.0, "upper_offset": 1.5}]
    finally:
        tools.close()


# ---------------------------------------------------------------- review round 3 fixes
ARRAY_TEXT = "binaryDataArrayList"


@pytest.mark.parametrize("where", ["user param value", "spectrum id", "both"])
def test_rt_filter_ignores_the_array_list_name_outside_its_tag(tmp_path: Path, where: str) -> None:
    """The head ends at the ``<binaryDataArrayList`` element, not at that text in a value."""
    spectra = [spectrum_xml(i, t) for i, t in enumerate(OUT_OF_ORDER)]
    param = f'<userParam name="note" value="has {ARRAY_TEXT} inside"/>'
    for i in (1, 6, 10):
        if where in ("user param value", "both"):
            spectra[i] = spectra[i].replace("</scanList>", "</scanList>" + param)
        if where in ("spectrum id", "both"):
            spectra[i] = spectra[i].replace(f'id="scan={i}"', f'id="scan={i} {ARRAY_TEXT}"')
    path = write_indexed(tmp_path / "text.mzML", spectra)
    with Mzml(path) as reader:
        for window in [(None, 10.0), (0.0, 2.0), (1.0, 1.0)]:
            expected = [s.id for s in reader.spectra if s.rt is not None and _inside(s.rt, window)]
            assert expected
            assert [s.id for s in reader.spectra.filter(rt_range=window)] == expected
        assert reader.spectra._rt_table is not None  # the fast path answered


def test_spectrum_head_cuts_at_the_array_list_element() -> None:
    from mzmlpy.file_classes.standardMzml import _spectrum_head

    data = b'<spectrum id="a"><userParam value="binaryDataArrayList"/><binaryDataArrayList count="0"/>'
    assert _spectrum_head(data, "a") == b'<spectrum id="a"><userParam value="binaryDataArrayList"/>'
    assert _spectrum_head(b'<spectrum id="a"><binaryDataArrayListX/>', "a") is None  # a different element


def test_point_queries_accept_numpy_scalars(tmp_path: Path) -> None:
    extra = (
        '<precursorList count="1"><precursor><selectedIonList count="1"><selectedIon>'
        '<cvParam accession="MS:1000744" value="500.0"/></selectedIon></selectedIonList></precursor></precursorList>'
    )
    path = write_indexed(tmp_path / "p.mzML", [spectrum_xml(0, 10.0), spectrum_xml(1, 50.0, ms_level=2, extra=extra)])
    with Mzml(path) as reader:
        spectra = reader.spectra
        assert [s.id for s in spectra.filter(rt=np.float32(40.0), rt_tolerance=np.float32(15.0))] == ["scan=1"]
        assert [s.id for s in spectra.filter(rt=np.int64(10))] == ["scan=0"]
        assert [s.id for s in spectra.filter(precursor_mz=np.float64(500.009), mz_tolerance=np.int32(20))] == ["scan=1"]
        assert [s.id for s in spectra.filter(rt_range=(np.float32(40.0), np.float64(60.0)))] == ["scan=1"]
        for bad in (True, np.bool_(True), "10"):
            with pytest.raises(MzmlError):
                spectra.filter(rt=bad)  # ty: ignore[invalid-argument-type]
        with pytest.raises(MzmlError):
            spectra.filter(rt_range=(True, 5.0))  # ty: ignore[invalid-argument-type]


def test_filtering_a_stream_reader_does_not_count_spectra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gzip

    from mzmlpy.lookup import SpectrumLookup

    source = ordered_run(tmp_path, TIMES)
    gz = tmp_path / "run.mzML.gz"
    gz.write_bytes(gzip.compress(source.read_bytes()))

    def counted(self: SpectrumLookup) -> int:
        raise AssertionError("the filter counted every spectrum before its first result")

    with Mzml(gz, gzip_mode="stream") as reader:
        monkeypatch.setattr(SpectrumLookup, "count", property(counted))
        assert next(reader.spectra.filter(ms_level=1)).id == "scan=0"
        assert next(reader.spectra.filter(rt_range=(10.0, 14.0))).rt == 10.0


@pytest.mark.parametrize("gzip_mode", [None, "stream", "indexed"])
def test_reading_after_close_raises(tmp_path: Path, gzip_mode: str | None) -> None:
    import gzip

    if gzip_mode == "indexed":
        pytest.importorskip("rapidgzip")

    path = ordered_run(tmp_path, [1.0, 2.0, 3.0])
    if gzip_mode is not None:
        gz = tmp_path / "run.mzML.gz"
        gz.write_bytes(gzip.compress(path.read_bytes()))
        path = gz
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reader = Mzml(path, gzip_mode=gzip_mode or "auto")
        live = iter(reader.spectra)
        assert next(live).rt == 1.0
        assert reader.spectra[1].rt == 2.0
        reader.close()
        with pytest.raises(MzmlError, match="closed"):
            next(live)
        with pytest.raises(MzmlError, match="closed"):
            reader.spectra[0]  # noqa: B018
        with pytest.raises(MzmlError, match="closed"):
            list(reader.spectra)
        with pytest.raises(MzmlError, match="closed"):
            list(reader.spectra.filter(rt_range=(0.0, 5.0)))
        reader.close()  # closing twice is fine


def test_an_unclosed_stream_iterator_does_not_abort_the_interpreter(tmp_path: Path) -> None:
    import gzip
    import subprocess
    import sys

    source = ordered_run(tmp_path, TIMES)
    gz = tmp_path / "run.mzML.gz"
    gz.write_bytes(gzip.compress(source.read_bytes()))
    script = (
        "import warnings; warnings.simplefilter('ignore')\n"
        "from mzmlpy import Mzml\n"
        f"reader = Mzml({str(gz)!r}, gzip_mode='stream')\n"
        "live = iter(reader.spectra)\n"
        "print(next(live).id)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "scan=0"
