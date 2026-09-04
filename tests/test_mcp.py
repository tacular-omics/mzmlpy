"""Exercise local MCP operations against real mzML records and file boundaries."""

import gzip
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from mzmlpy import Mzml, write_indexed_gzip
from mzmlpy.mcp import MzmlTools

DATA = Path(__file__).parent / "data"


@pytest.fixture(params=["plain", "gzip", "embedded"])
def source(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[MzmlTools, str]:
    name = "sample.mzML" if request.param == "plain" else "sample.mzML.gz"
    path = tmp_path / name
    if request.param == "plain":
        shutil.copyfile(DATA / "example.mzML", path)
    elif request.param == "gzip":
        path.write_bytes(gzip.compress((DATA / "example.mzML").read_bytes()))
    else:
        write_indexed_gzip(DATA / "example.mzML", path)
    return MzmlTools(tmp_path), name


def test_inspection_and_validation(source: tuple[MzmlTools, str]) -> None:
    tools, name = source
    before = sorted(tools.root.iterdir())
    result = tools.inspect_file(name)
    assert result.file == name
    assert result.data["spectrum_count"] == 4
    assert result.data["chromatogram_ids"] == ["tic", "sic"]
    assert result.data["instruments"]
    report = tools.validate_file(name, decode_binary=True, issue_limit=1)
    assert report.data["complete"]
    assert report.data["arrays_decoded"] > 0
    assert len(report.data["issues"]) <= 1
    assert report.data["issues_truncated"] == (report.data["issue_count"] > 1)
    assert sorted(tools.root.iterdir()) == before
    json.dumps(asdict(report), allow_nan=False)


def test_spectrum_pages_and_filtering(source: tuple[MzmlTools, str]) -> None:
    tools, name = source
    ids = []
    start = 0
    revision = None
    while start is not None:
        page = tools.find_spectra(name, limit=1, start_index=start, expected_revision=revision)
        ids.extend(s["id"] for s in page.data["spectra"])
        start, revision = page.data["next_index"], page.revision
    with Mzml(tools.root / name, in_memory=False, gzip_mode="stream") as reader:
        assert ids == [s.id for s in reader.spectra]
        matches = tools.find_spectra(name, ms_level=2, retention_time_min_seconds=0, polarity="positive")
        assert [s["id"] for s in matches.data["spectra"]] == [
            s.id for s in reader.spectra.filter(ms_level=2, retention_time=(0, None), polarity="positive")
        ]
    page = tools.find_spectra(name, ms_level=99, scan_limit=1)
    assert page.data["spectra"] == []
    assert page.data["next_index"] == 1
    assert not page.data["exhausted"]


def test_peak_pages_preserve_values_and_bounds(source: tuple[MzmlTools, str]) -> None:
    tools, name = source
    metadata = tools.get_spectrum(name, "scan=19")
    assert metadata.data["peaks"] is None
    page = tools.get_spectrum(name, "scan=19", include_peaks=True, limit=3, mz_min=2, mz_max=6)
    assert page.data["peaks"]["points"] == [[2.0, 13.0], [3.0, 12.0], [4.0, 11.0]]
    last = tools.get_spectrum(
        name,
        "scan=19",
        include_peaks=True,
        limit=3,
        mz_min=2,
        mz_max=6,
        start_index=page.data["peaks"]["next_index"],
        expected_revision=page.revision,
    )
    assert last.data["peaks"]["points"] == [[5.0, 10.0], [6.0, 9.0]]
    assert not last.data["peaks"]["truncated"]
    assert last.data["peaks"]["intensity_unit"]["name"] == "number of counts"


def test_chromatogram_pages(source: tuple[MzmlTools, str]) -> None:
    tools, name = source
    page = tools.get_chromatogram(name, "tic", limit=3, time_min_seconds=2, time_max_seconds=6)
    assert page.data["points"] == [[2.0, 13.0], [3.0, 12.0], [4.0, 11.0]]
    assert page.data["next_index"] == 5
    assert page.data["coordinate_unit"] == "second"


def test_file_boundary_and_revision(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.mzML"
    shutil.copyfile(DATA / "example.mzML", outside)
    tools = MzmlTools(root)
    for name in (str(outside), "../outside.mzML"):
        with pytest.raises(ValueError, match="inside"):
            tools.inspect_file(name)
    local = root / "inside.mzML"
    shutil.copyfile(outside, local)
    before = tools.inspect_file(local.name)
    local.write_bytes(local.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="revision changed"):
        tools.find_spectra(local.name, expected_revision=before.revision)
    with pytest.raises(ValueError, match="existing"):
        tools.inspect_file("missing.mzML")
    with pytest.raises(ValueError, match="directory"):
        MzmlTools(local)
    wrong = root / "notes.txt"
    wrong.write_text("hello")
    with pytest.raises(ValueError, match="suffixes"):
        tools.inspect_file(wrong.name)


def test_symlink_cannot_escape_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.mzML"
    outside.write_bytes((DATA / "example.mzML").read_bytes())
    link = root / "link.mzML"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links is unavailable")
    with pytest.raises(ValueError, match="inside"):
        MzmlTools(root).validate_file(link.name)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"start_index": -1},
        {"scan_limit": 100001},
        {"ms_level": 0},
        {"retention_time_min_seconds": float("nan")},
        {"precursor_mz_min": 20, "precursor_mz_max": 10},
    ],
)
def test_invalid_query_arguments(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        MzmlTools(DATA).find_spectra("missing.mzML", **kwargs)


def test_metadata_does_not_decode_binary(tmp_path: Path) -> None:
    xml = (DATA / "example.mzML").read_text()
    import re

    xml = re.sub(r"<binary>.*?</binary>", "<binary>invalid!!!</binary>", xml, flags=re.S)
    path = tmp_path / "bad.mzML"
    path.write_text(xml)
    tools = MzmlTools(tmp_path)
    assert tools.find_spectra(path.name, ms_level=1).data["spectra"]
    assert tools.get_spectrum(path.name, "scan=19").data["peaks"] is None
    with pytest.raises(ValueError, match="base64"):
        tools.get_spectrum(path.name, "scan=19", include_peaks=True)


@pytest.mark.parametrize("unit,factor", [("UO:0000031", 60), ("UO:0000028", 0.001)])
def test_time_accession_normalization(tmp_path: Path, unit: str, factor: float) -> None:
    xml = (DATA / "example.mzML").read_text().replace('unitAccession="UO:0000010"', f'unitAccession="{unit}"')
    path = tmp_path / "time.mzML"
    path.write_text(xml)
    result = MzmlTools(tmp_path).get_chromatogram(path.name, "tic", limit=2)
    assert result.data["points"][1][0] == factor


def test_unknown_time_unit_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "time.mzML"
    path.write_text((DATA / "example.mzML").read_text().replace("UO:0000010", "unknown"))
    with pytest.raises(ValueError, match="time units"):
        MzmlTools(tmp_path).get_chromatogram(path.name, "tic")


def test_invalid_array_pairs_are_not_silently_changed() -> None:
    from mzmlpy.mcp import _points

    for x, y in [(None, np.array([])), (np.array([1]), np.array([])), (np.array([float("nan")]), np.array([1]))]:
        with pytest.raises(ValueError):
            _points(x, y, 0, 10, None)


def test_response_budget(tmp_path: Path) -> None:
    path = tmp_path / "large.mzML"
    path.write_text((DATA / "example.mzML").read_text().replace('name="LCQ Deca"', 'name="' + "x" * 270000 + '"'))
    tools = MzmlTools(tmp_path)
    with pytest.raises(ValueError, match="256 KiB"):
        tools.inspect_file(path.name)
