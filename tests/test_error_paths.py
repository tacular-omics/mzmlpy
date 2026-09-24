"""Error paths that 0.10 moved onto the MzmlError hierarchy, plus empty-sequence defaults."""

import zlib
from pathlib import Path
from xml.etree.ElementTree import fromstring

import pytest

from mzmlpy import (
    MzmlDecodeError,
    MzmlError,
    MzmlOffsetIndexError,
    MzmlParseError,
    SpectrumFilter,
    write_indexed_gzip,
)
from mzmlpy.decoder import MSDecoder
from mzmlpy.elems.data_processing import DataProcessing
from mzmlpy.elems.file_desc import FileDescription
from mzmlpy.elems.instrument_config import InstrumentConfiguration
from mzmlpy.elems.referenceable_param_group import ReferenceableParamGroup
from mzmlpy.elems.sample import Sample
from mzmlpy.elems.scan_setting import ScanSetting
from mzmlpy.elems.software import Software
from mzmlpy.embedded_indexed_gzip import decompress_indexed_member, read_embedded_index
from mzmlpy.spectra import Chromatogram, Precursor, Spectrum

NS = "http://psi.hupo.org/ms/mzml"


# ---------------------------------------------------------------- embedded gzip index
def _gzip_header(flags: int) -> bytes:
    return b"\x1f\x8b\x08" + bytes([flags]) + b"\x00" * 6


_COMMENT = 0x10


def _index(widths: tuple[int, int], body: bytes) -> bytes:
    return _gzip_header(_COMMENT) + b"FU\x01" + bytes(widths) + body


_BAD_INDEXES = [
    (_gzip_header(0), "no embedded index comment"),
    (_gzip_header(0xE0), "reserved flags"),
    (_gzip_header(0x04) + b"\x01", "Truncated gzip extra-field length"),
    (_gzip_header(0x04) + b"\x05\x00ab", "Truncated gzip extra field"),
    (_gzip_header(0x08) + b"name-without-terminator", "Truncated gzip header"),
    (_gzip_header(0x08) + b"a" * (1024 * 1024 + 2), "exceeds the supported size"),
    (_gzip_header(_COMMENT) + b"XY\x01\x02\x03\x00", "not an FU version 1 index"),
    (_gzip_header(_COMMENT) + b"FU\x01\x05", "Truncated embedded index widths"),
    (_index((0, 5), b"\x00"), "widths must be positive"),
    (_index((2, 3), b""), "has no terminator"),
    (_index((2, 3), b"ab1"), "Truncated embedded index entry"),
    (_index((2, 3), b"\xac\xac010\x00"), "empty identifier"),
    (_index((2, 3), b"ab011ab012\x00" + b"\x00" * 40), "Duplicate embedded index identifier: ab"),
    (_index((2, 3), b"ab999\x00"), "outside the file: 999"),
    (_index((2, 3), b"ab030cd020\x00" + b"\x00" * 40), "not ordered"),
    (_index((2, 3), b"\x00"), "contains no entries"),
]


# Explicit ids: the default would embed the 1 MiB payload in the node id, which pytest exports
# as PYTEST_CURRENT_TEST and a Windows environment variable cannot hold (the CI job hung).
@pytest.mark.parametrize(("content", "message"), _BAD_INDEXES, ids=[message for _, message in _BAD_INDEXES])
def test_malformed_embedded_index_raises_offset_index_error(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "bad.mzML.gz"
    path.write_bytes(content)
    with pytest.raises(MzmlOffsetIndexError, match=message):
        read_embedded_index(path)


def _raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


@pytest.mark.parametrize(
    ("tail", "message"),
    [
        (lambda stream: stream[: len(stream) // 2], "Truncated deflate stream"),
        (lambda stream: stream + b"\x00\x00\x00", "Truncated gzip trailer"),
        (lambda stream: stream + b"\x00" * 8, "checksum failed"),
    ],
    ids=["truncated-stream", "truncated-trailer", "bad-checksum"],
)
def test_corrupt_indexed_member_raises_parse_error(tmp_path: Path, tail, message: str) -> None:
    path = tmp_path / "member.bin"
    path.write_bytes(tail(_raw_deflate(b"<spectrum id='s'/>" * 50)))
    with pytest.raises(MzmlParseError, match=message):
        decompress_indexed_member(path, 0)


def test_write_indexed_gzip_rejects_bad_arguments(tmp_path: Path) -> None:
    with pytest.raises(MzmlError, match="compression_level"):
        write_indexed_gzip("tests/data/example.mzML", tmp_path / "out.mzML.gz", compression_level=10)
    with pytest.raises(MzmlError, match=r"\.gz or \.igz"):
        write_indexed_gzip("tests/data/example.mzML", tmp_path / "out.mzML")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('<spectrum id="a"><spectrum id="b"/></spectrum>', "Nested spectrum"),
        ("<chromatogram/>", "chromatogram element has no id"),
        ('<spectrum id="a">', "Invalid or unclosed mzML input"),
    ],
)
def test_write_indexed_gzip_rejects_unsplittable_input(tmp_path: Path, body: str, message: str) -> None:
    source = tmp_path / "in.mzML"
    source.write_text(f'<mzML xmlns="{NS}"><run>{body}</run></mzML>', encoding="utf-8")
    with pytest.raises(MzmlParseError, match=message):
        write_indexed_gzip(source, tmp_path / "out.mzML.gz")
    assert not (tmp_path / "out.mzML.gz").exists()


# ---------------------------------------------------------------- argument validation
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"rt": (1.0,)}, "lower and an upper bound"),
        ({"spectrum_type": "raw"}, "centroid or profile"),
        ({"mobility_type": "k0"}, "inverse_reduced or drift_time"),
    ],
)
def test_spectrum_filter_rejects_bad_arguments(kwargs: dict, message: str) -> None:
    with pytest.raises(MzmlError, match=message):
        SpectrumFilter(**kwargs)


def test_unshuffle_rejects_non_positive_element_size() -> None:
    with pytest.raises(MzmlDecodeError, match="element_size must be positive"):
        MSDecoder.unshuffle(b"", 0)


# ---------------------------------------------------------------- missing ids
@pytest.mark.parametrize(
    ("cls", "tag"),
    [
        (Spectrum, "spectrum"),
        (Chromatogram, "chromatogram"),
        (DataProcessing, "dataProcessing"),
        (InstrumentConfiguration, "instrumentConfiguration"),
        (ReferenceableParamGroup, "referenceableParamGroup"),
        (Sample, "sample"),
        (ScanSetting, "scanSettings"),
        (Software, "software"),
    ],
)
def test_missing_id_raises_mzml_error(cls: type, tag: str) -> None:
    element = cls(fromstring(f'<{tag} xmlns="{NS}"/>'))
    with pytest.raises(MzmlError, match="(?i)id"):
        _ = element.id


# ---------------------------------------------------------------- empty sequences are ()
def test_absent_sequences_are_empty_tuples() -> None:
    assert Chromatogram(fromstring(f'<chromatogram xmlns="{NS}" id="c"/>')).binary_arrays == ()
    assert Precursor(fromstring(f'<precursor xmlns="{NS}"/>')).selected_ions == ()
    assert FileDescription(fromstring(f'<fileDescription xmlns="{NS}"/>')).source_files == ()


def test_empty_file_raises_parse_error(tmp_path: Path) -> None:
    from mzmlpy import Mzml

    path = tmp_path / "empty.mzML"
    path.write_text('<?xml version="1.0"?>\n', encoding="utf-8")
    with pytest.raises(MzmlParseError):
        Mzml(path)


def test_chromatogram_id_regex_lookup() -> None:
    from mzmlpy import Mzml

    with Mzml("tests/data/example.mzML", chromatogram_id_regex=r"^(t)ic$") as reader:
        assert reader.chromatograms["t"].id == "tic"
        assert "t" in reader.chromatograms
