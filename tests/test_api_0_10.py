"""The 0.10 public API: error hierarchy, vocabulary renames, immutability, removed names."""

import importlib
import os
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import mzmlpy
from mzmlpy import (
    Mzml,
    MzmlDecodeError,
    MzmlError,
    MzmlOffsetIndexError,
    MzmlParseError,
    MzmlRecordNotFoundError,
    SpectrumFilter,
)
from mzmlpy.elems.dtree_wrapper import _DataTreeWrapper, _ParamGroup

settings.register_profile("default", max_examples=40, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))

EXAMPLE = "tests/data/example.mzML"
BRUKER = "tests/data/bruker_ms2_im.mzML"

_HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<mzML xmlns="http://psi.hupo.org/ms/mzml" id="m" version="1.1.0">\n'
    '<run id="r"><spectrumList count="1">\n'
)
_FOOTER = "</spectrumList></run></mzML>\n"

_UNITS = {
    "second": ("UO:0000010", 1.0),
    "minute": ("UO:0000031", 60.0),
    "millisecond": ("UO:0000028", 0.001),
}


def _one_spectrum(scan_params: str) -> str:
    return (
        _HEADER + '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        f'<scanList count="1"><scan>{scan_params}</scan></scanList>'
        "</spectrum>" + _FOOTER
    )


# ---------------------------------------------------------------- errors
@pytest.mark.parametrize("error", [MzmlParseError, MzmlOffsetIndexError, MzmlDecodeError, MzmlRecordNotFoundError])
def test_every_error_is_an_mzml_error_and_a_value_error(error: type[Exception]) -> None:
    assert issubclass(error, MzmlError)
    assert issubclass(error, ValueError)


def test_record_not_found_is_also_a_key_error_with_a_readable_message() -> None:
    assert issubclass(MzmlRecordNotFoundError, KeyError)
    with Mzml(EXAMPLE) as reader:
        with pytest.raises(KeyError) as caught:
            reader.spectra["no-such-id"]
    assert isinstance(caught.value, MzmlRecordNotFoundError)
    assert "no-such-id" in str(caught.value)
    assert not str(caught.value).startswith("'")


def test_malformed_xml_raises_parse_error_with_cause(tmp_path: Path) -> None:
    path = tmp_path / "broken.mzML"
    path.write_text('<?xml version="1.0"?>\n<mzML><run id="r"><spectrumList count="1"><spectrum <<', encoding="utf-8")
    with pytest.raises(MzmlParseError):
        with Mzml(path) as reader:
            list(reader.spectra)


def test_get_by_index_rejects_non_int() -> None:
    with Mzml(EXAMPLE) as reader:
        with pytest.raises(TypeError):
            reader.spectra.get_by_index("1")  # ty: ignore[invalid-argument-type]
        with pytest.raises(TypeError):
            reader.spectra.get_by_index(True)


# ---------------------------------------------------------------- immutability
def test_reader_dict_properties_return_copies() -> None:
    with Mzml(EXAMPLE) as reader:
        for name in ("referenceable_param_groups", "instrument_configurations", "data_processes", "scan_settings"):
            first = getattr(reader, name)
            assert isinstance(first, dict)
            first["injected"] = None  # ty: ignore[invalid-assignment]
            assert "injected" not in getattr(reader, name), name


def test_obo_version_is_read_only() -> None:
    with Mzml(EXAMPLE) as reader:
        version = reader.obo_version
        with pytest.raises(AttributeError):
            reader.obo_version = "x"  # ty: ignore[invalid-assignment]
        assert reader.obo_version == version


def test_param_collections_are_immutable() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[0]
        assert isinstance(spectrum.cv_params, tuple)
        assert isinstance(spectrum.user_params, tuple)
        assert isinstance(spectrum.accessions, frozenset)
        assert isinstance(spectrum.names, frozenset)
        assert "MS:1000511" in spectrum.accessions
        assert "ms level" in spectrum.names


def test_serialize_returns_a_copy() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[0]
        data = spectrum.serialize()
        assert str(data["tag"]).endswith("spectrum")
        attributes = data["attributes"]
        assert isinstance(attributes, dict)
        attributes["id"] = "changed"
        assert spectrum.id != "changed"
        assert spectrum.serialize()["attributes"]["id"] == spectrum.id  # ty: ignore[not-subscriptable]


def test_wrapper_tolerates_params_without_name() -> None:
    from xml.etree.ElementTree import fromstring

    element = fromstring('<scan><cvParam accession="MS:1000016" value="1"/><userParam value="x"/></scan>')
    wrapper = _ParamGroup(element)
    assert wrapper.cv_params[0].name == ""
    assert wrapper.user_params[0].name == ""


# ---------------------------------------------------------------- TIC and vocabulary
def test_total_ion_chromatogram_on_reader() -> None:
    with Mzml(EXAMPLE) as reader:
        tic = reader.total_ion_chromatogram
        assert tic is not None
        assert tic.id == "tic"


def test_selected_ion_and_activation_vocabulary() -> None:
    with Mzml(EXAMPLE) as reader:
        ms2 = next(s for s in reader.spectra if s.ms_level == 2)
        (precursor,) = ms2.precursors
        ion = precursor.selected_ions[0]
        assert ms2.id == "scan=20"
        assert ion.mz == 445.34
        assert ion.charge == 2
        assert precursor.activation is not None
        assert precursor.activation.collision_energy == 35.0
        assert precursor.activation.activation_energy is None
        assert precursor.isolation_window is not None
        assert precursor.isolation_window.mz_range == pytest.approx((444.8, 445.8))


def test_mobility_vocabulary_on_bruker() -> None:
    with Mzml(BRUKER) as reader:
        spectrum = reader.spectra[0]
        assert spectrum.ook0 is not None
        assert spectrum.scans[0].ook0 == spectrum.ook0
        assert spectrum.scans[0].drift_time is None


def test_spectrum_charge_array_and_mz_range() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[0]
        assert spectrum.charge_array is None
        assert spectrum.mz_range == spectrum.scans[0].mz_range


def test_rt_is_none_without_a_value_or_unit(tmp_path: Path) -> None:
    path = tmp_path / "no_rt_value.mzML"
    path.write_text(
        _one_spectrum('<cvParam cvRef="MS" accession="MS:1000016" name="scan start time"/>'), encoding="utf-8"
    )
    with Mzml(path) as reader:
        assert reader.spectra[0].rt is None


def test_spectrum_filter_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        SpectrumFilter(1)  # ty: ignore[too-many-positional-arguments]
    assert SpectrumFilter(rt=(0.0, 1.0)).rt == (0.0, 1.0)


@given(
    value=st.floats(min_value=0, max_value=1e5, allow_nan=False, allow_infinity=False),
    unit=st.sampled_from(sorted(_UNITS)),
    window=st.tuples(
        st.floats(min_value=0, max_value=1e7, allow_nan=False),
        st.floats(min_value=0, max_value=1e7, allow_nan=False),
    ).map(sorted),
)
def test_rt_is_seconds_for_any_unit_and_drives_the_filter(value: float, unit: str, window: list[float]) -> None:
    accession, factor = _UNITS[unit]
    xml = _one_spectrum(
        f'<cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="{value!r}" '
        f'unitCvRef="UO" unitAccession="{accession}" unitName="{unit}"/>'
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rt.mzML"
        path.write_text(xml, encoding="utf-8")
        with Mzml(path) as reader:
            spectrum = reader.spectra[0]
            rt = spectrum.rt
            assert rt == pytest.approx(value * factor, rel=1e-9, abs=1e-6)
            assert spectrum.scans[0].rt == rt
            lower, upper = window
            selected = [s.id for s in reader.spectra.filter(rt=(lower, upper))]
            assert selected == (["scan=1"] if lower <= rt <= upper else [])


# ---------------------------------------------------------------- removed names
REMOVED_ATTRIBUTES = {
    "Spectrum": ["TIC", "scan_start_time", "lower_mz", "upper_mz", "charge"],
    "Scan": ["scan_start_time", "lower_mz", "upper_mz", "inverse_reduced_ion_mobility", "ion_mobility_drift_time"],
    "SelectedIon": ["selected_ion_mz", "peak_intensity", "charge_state", "ir_im", "im_drift_time"],
    "Activation": ["ce", "supplemental_ce"],
    "SpectrumLookup": ["next", "reset", "file_object"],
    "ChromatogramLookup": ["TIC", "total_ion_chromatogram", "next", "reset", "file_object"],
    "Mzml": ["TIC", "iter"],
}


@pytest.mark.parametrize(("cls", "attribute"), [(c, a) for c, attrs in REMOVED_ATTRIBUTES.items() for a in attrs])
def test_removed_attributes_are_gone(cls: str, attribute: str) -> None:
    assert not hasattr(getattr(mzmlpy, cls), attribute)


def test_removed_wrapper_methods_are_gone() -> None:
    assert not hasattr(_DataTreeWrapper, "get_cvparm")
    assert not hasattr(_DataTreeWrapper, "has_cvparm")


@pytest.mark.parametrize(
    "name",
    [
        "PeakType",
        "NoiseMode",
        "DataType",
        "TimeUnit",
        "XMLAttribute",
        "XMLElement",
        "EncodingFormat",
        "XMLNamespace",
        "PROTON_MASS",
        "ISOTOPE_AVERAGE_DIFFERENCE",
        "ISOLATION_WINDOW_TARGET_MZ",
        "SpectrumType",
        "CompressionTypeAccessions",
        "BINARY_DECODE_DTYPES",
    ],
)
def test_removed_constants_are_gone(name: str) -> None:
    assert not hasattr(mzmlpy.constants, name)


def test_emission_spelling() -> None:
    from mzmlpy.constants import ChromatogramTypeAccession

    assert ChromatogramTypeAccession.EMISSION == "MS:1000813"
    assert not hasattr(ChromatogramTypeAccession, "EMMISION")


@pytest.mark.parametrize(
    "module",
    [
        "mzmlpy",
        "mzmlpy.constants",
        "mzmlpy.content",
        "mzmlpy.decoder",
        "mzmlpy.errors",
        "mzmlpy.file_interface",
        "mzmlpy.filtering",
        "mzmlpy.lookup",
        "mzmlpy.regex_patterns",
        "mzmlpy.run",
        "mzmlpy.spectra",
        "mzmlpy.util",
        "mzmlpy.validation",
    ],
)
def test_all_names_resolve(module: str) -> None:
    mod = importlib.import_module(module)
    assert isinstance(mod.__all__, list)
    for name in mod.__all__:
        assert hasattr(mod, name), f"{module}.{name}"


# ---------------------------------------------------------------- 0.10 review follow-ups
def _spectrum_file(tmp_path: Path, body: str, name: str = "s.mzML") -> Path:
    path = tmp_path / name
    path.write_text(
        _HEADER + '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>' + body + "</spectrum>" + _FOOTER,
        encoding="utf-8",
    )
    return path


def _window(lower: float | None, upper: float | None) -> str:
    params = ""
    if lower is not None:
        params += f'<cvParam cvRef="MS" accession="MS:1000501" name="scan window lower limit" value="{lower}"/>'
    if upper is not None:
        params += f'<cvParam cvRef="MS" accession="MS:1000500" name="scan window upper limit" value="{upper}"/>'
    return f"<scanWindow>{params}</scanWindow>"


def _scan_with_windows(*windows: str) -> str:
    inner = f'<scanWindowList count="{len(windows)}">{"".join(windows)}</scanWindowList>' if windows else ""
    return f'<scanList count="1"><scan>{inner}</scan></scanList>'


def test_scan_window_mz_range_and_multi_window_envelope(tmp_path: Path) -> None:
    body = _scan_with_windows(_window(400.0, 600.0), _window(350.0, 500.0), _window(None, 2000.0))
    with Mzml(_spectrum_file(tmp_path, body)) as reader:
        scan = reader.spectra[0].scans[0]
        assert [w.mz_range for w in scan.scan_windows] == [(400.0, 600.0), (350.0, 500.0), None]
        # The incomplete third window is ignored; the envelope spans the two complete ones.
        assert scan.mz_range == (350.0, 600.0)
        assert reader.spectra[0].mz_range == (350.0, 600.0)


@pytest.mark.parametrize(
    "body",
    [
        _scan_with_windows(),  # no scanWindowList
        _scan_with_windows(_window(100.0, None)),  # only a lower limit
        _scan_with_windows(_window(None, 900.0), _window(None, None)),  # no complete window
    ],
)
def test_scan_mz_range_is_none_without_a_complete_window(tmp_path: Path, body: str) -> None:
    with Mzml(_spectrum_file(tmp_path, body)) as reader:
        assert reader.spectra[0].scans[0].mz_range is None
        assert reader.spectra[0].mz_range is None


def _precursor(isolation: str = "", activation: str = "") -> str:
    return (
        '<precursorList count="1"><precursor>'
        f"<isolationWindow>{isolation}</isolationWindow>"
        '<selectedIonList count="1"><selectedIon>'
        '<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="500.0"/>'
        "</selectedIon></selectedIonList>"
        f"<activation>{activation}</activation>"
        "</precursor></precursorList>"
    )


_TARGET = '<cvParam cvRef="MS" accession="MS:1000827" name="isolation window target m/z" value="500.0"/>'
_LOWER = '<cvParam cvRef="MS" accession="MS:1000828" name="isolation window lower offset" value="1.5"/>'
_UPPER = '<cvParam cvRef="MS" accession="MS:1000829" name="isolation window upper offset" value="0.5"/>'


@pytest.mark.parametrize(
    ("isolation", "expected"),
    [
        (_TARGET + _LOWER + _UPPER, (498.5, 500.5)),
        (_LOWER + _UPPER, None),
        (_TARGET + _UPPER, None),
        (_TARGET + _LOWER, None),
    ],
)
def test_isolation_window_mz_range(tmp_path: Path, isolation: str, expected: tuple[float, float] | None) -> None:
    with Mzml(_spectrum_file(tmp_path, _precursor(isolation=isolation))) as reader:
        window = reader.spectra[0].precursors[0].isolation_window
        assert window is not None
        assert window.mz_range == expected


def _cv(accession: str, name: str, value: str, unit: str = "") -> str:
    return f'<cvParam cvRef="MS" accession="{accession}" name="{name}" value="{value}"{unit}/>'


def test_activation_energy_alone_is_not_a_collision_energy(tmp_path: Path) -> None:
    activation = _cv("MS:1000509", "activation energy", "12.5")
    with Mzml(_spectrum_file(tmp_path, _precursor(activation=activation))) as reader:
        act = reader.spectra[0].precursors[0].activation
        assert act is not None
        assert act.collision_energy is None
        assert act.activation_energy == 12.5
        assert act.supplemental_collision_energy is None


def test_supplemental_collision_energy(tmp_path: Path) -> None:
    activation = _cv("MS:1000045", "collision energy", "28") + _cv("MS:1002680", "supplemental collision energy", "25")
    with Mzml(_spectrum_file(tmp_path, _precursor(activation=activation))) as reader:
        act = reader.spectra[0].precursors[0].activation
        assert act is not None
        assert act.collision_energy == 28.0
        assert act.supplemental_collision_energy == 25.0
        assert act.activation_energy is None


def _rt_param(value: str, unit: str = "") -> str:
    return _cv("MS:1000016", "scan start time", value, unit)


@pytest.fixture
def fresh_time_warnings() -> None:
    import mzmlpy.spectra

    mzmlpy.spectra._warned_time_units.clear()


@pytest.mark.usefixtures("fresh_time_warnings")
def test_rt_without_a_unit_warns_once_and_is_taken_as_seconds(tmp_path: Path) -> None:
    with Mzml(_spectrum_file(tmp_path, _one_scan(_rt_param("12.5")))) as reader:
        with pytest.warns(UserWarning, match=r"retention time .*no unit.*assuming seconds"):
            assert reader.spectra[0].rt == 12.5
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert reader.spectra[0].rt == 12.5  # second read does not warn again


@pytest.mark.usefixtures("fresh_time_warnings")
def test_rt_with_a_non_time_unit_warns_and_is_taken_as_seconds(tmp_path: Path) -> None:
    unit = ' unitCvRef="UO" unitAccession="UO:0000187" unitName="percent"'
    with Mzml(_spectrum_file(tmp_path, _one_scan(_rt_param("3", unit)))) as reader:
        with pytest.warns(UserWarning, match=r"percent.*assuming seconds"):
            assert reader.spectra[0].rt == 3.0


def test_rt_unit_name_without_accession_is_honoured(tmp_path: Path) -> None:
    unit = ' unitName="minute"'
    with Mzml(_spectrum_file(tmp_path, _one_scan(_rt_param("2", unit)))) as reader:
        assert reader.spectra[0].rt == 120.0


def test_non_numeric_rt_raises_mzml_error(tmp_path: Path) -> None:
    unit = ' unitCvRef="UO" unitAccession="UO:0000010" unitName="second"'
    with Mzml(_spectrum_file(tmp_path, _one_scan(_rt_param("soon", unit)))) as reader:
        with pytest.raises(MzmlError):
            _ = reader.spectra[0].rt


@pytest.mark.parametrize(
    ("value", "unit", "expected_ms"),
    [
        ("25", ' unitCvRef="UO" unitAccession="UO:0000028" unitName="millisecond"', 25.0),
        ("0.025", ' unitCvRef="UO" unitAccession="UO:0000010" unitName="second"', 25.0),
    ],
)
def test_ion_injection_time_is_float_milliseconds(tmp_path: Path, value: str, unit: str, expected_ms: float) -> None:
    param = _cv("MS:1000927", "ion injection time", value, unit)
    with Mzml(_spectrum_file(tmp_path, _one_scan(param))) as reader:
        spectrum = reader.spectra[0]
        assert spectrum.ion_injection_time == pytest.approx(expected_ms)
        assert isinstance(spectrum.ion_injection_time, float)
        assert spectrum.scans[0].ion_injection_time == spectrum.ion_injection_time


def _one_scan(params: str) -> str:
    return f'<scanList count="1"><scan>{params}</scan></scanList>'


def test_non_mzml_root_raises_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "foo.mzML"
    path.write_text('<?xml version="1.0"?>\n<foo/>\n', encoding="utf-8")
    with pytest.raises(MzmlParseError, match="foo"):
        Mzml(path)


@pytest.mark.parametrize("key", [1.0, None, b"scan=19", ("scan=19",)])
def test_lookup_rejects_unsupported_key_types(key: object) -> None:
    with Mzml(EXAMPLE) as reader:
        with pytest.raises(TypeError):
            _ = reader.spectra[key]  # ty: ignore[invalid-argument-type]
        assert key not in reader.spectra


def test_get_by_id_rejects_non_strings() -> None:
    with Mzml(EXAMPLE) as reader, pytest.raises(TypeError):
        reader.spectra.get_by_id(1)  # ty: ignore[invalid-argument-type]


def test_negative_index_error_names_the_valid_range() -> None:
    with Mzml(EXAMPLE) as reader:
        assert reader.spectra[-4].id == reader.spectra[0].id
        with pytest.raises(IndexError, match=r"index -5 out of range: valid indices are -4 to 3"):
            _ = reader.spectra[-5]


def test_sequence_properties_are_tuples() -> None:
    with Mzml(EXAMPLE) as reader:
        ms2 = next(s for s in reader.spectra if s.ms_level == 2)
        (precursor,) = ms2.precursors
        description = reader.file_description
        assert description is not None
        values = [
            ms2.scans,
            ms2.precursors,
            ms2.products,
            ms2.binary_arrays,
            ms2.scans[0].scan_windows,
            precursor.selected_ions,
            description.source_files,
            description.contact,
        ]
        assert all(isinstance(v, tuple) for v in values)
        chromatogram = reader.chromatograms[0]
        assert isinstance(chromatogram.binary_arrays, tuple)
