import gzip
from pathlib import Path

import pytest

from mzmlpy import AccessStrategy, Mzml, write_indexed_gzip
from mzmlpy.embedded_indexed_gzip import (
    decompress_indexed_member,
    is_embedded_indexed_gzip,
    read_embedded_index,
)
from mzmlpy.file_classes import EmbeddedIndexedGzip

MZML_FILE = Path("tests/data/example.mzML")
GZ_FILE = Path("tests/data/example.mzML.gz")


@pytest.fixture()
def embedded_file(tmp_path: Path) -> Path:
    output = tmp_path / "example.indexed.mzML.gz"
    write_indexed_gzip(MZML_FILE, output)
    return output


def test_writer_preserves_decompressed_bytes(embedded_file: Path) -> None:
    with gzip.open(embedded_file, "rb") as file_handler:
        assert file_handler.read() == MZML_FILE.read_bytes()


def test_writer_accepts_gzip_input(tmp_path: Path) -> None:
    output = tmp_path / "from-gzip.mzML.gz"
    result = write_indexed_gzip(GZ_FILE, output)

    assert result.spectrum_count == 4
    assert result.chromatogram_count == 2
    with gzip.open(output, "rb") as file_handler:
        assert file_handler.read() == MZML_FILE.read_bytes()


def test_writer_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.mzML.gz"
    second = tmp_path / "second.mzML.gz"
    write_indexed_gzip(MZML_FILE, first)
    write_indexed_gzip(MZML_FILE, second)

    assert first.read_bytes() == second.read_bytes()


def test_embedded_index_has_native_and_pymzml_aliases(embedded_file: Path) -> None:
    entries = {entry.identifier: entry.offset for entry in read_embedded_index(embedded_file)}

    assert entries["s:scan=19"] == entries["19"]
    assert entries["c:tic"] == entries["tic"]
    assert entries["Head"] < entries["s:scan=19"] < entries["tail"]


@pytest.mark.parametrize("gzip_mode", ["extract", "indexed", "stream"])
def test_reader_auto_detects_embedded_index(embedded_file: Path, gzip_mode: str) -> None:
    with Mzml(embedded_file, gzip_mode=gzip_mode, in_memory=False) as reader:
        assert isinstance(reader._file_object.file_handler, EmbeddedIndexedGzip)
        assert reader.access_strategy is AccessStrategy.EMBEDDED
        assert [spectrum.id for spectrum in reader.spectra] == [
            "scan=19",
            "scan=20",
            "scan=21",
            "sample=1 period=1 cycle=22 experiment=1",
        ]
        assert reader.spectra["scan=20"].id == "scan=20"
        assert reader.spectra[-1].id == "sample=1 period=1 cycle=22 experiment=1"
        assert [chromatogram.id for chromatogram in reader.chromatograms] == ["tic", "sic"]


def test_reader_matches_plain_mzml(embedded_file: Path) -> None:
    with Mzml(embedded_file, in_memory=False) as indexed, Mzml(MZML_FILE) as reference:
        assert len(indexed.spectra) == len(reference.spectra)
        for position in range(len(reference.spectra)):
            actual = indexed.spectra[position]
            expected = reference.spectra[position]
            assert actual.id == expected.id
            assert actual.ms_level == expected.ms_level
            assert actual.TIC == expected.TIC


def test_fast_sequential_stream_reconstructs_mzml(embedded_file: Path) -> None:
    reader = EmbeddedIndexedGzip(embedded_file, "utf-8")
    try:
        with reader.get_file_handler("utf-8") as file_handler:
            assert file_handler.read().encode() == MZML_FILE.read_bytes()
    finally:
        reader.close()


def test_detection_rejects_regular_gzip() -> None:
    assert not is_embedded_indexed_gzip(GZ_FILE)


def test_corrupt_member_is_rejected(embedded_file: Path) -> None:
    entries = {entry.identifier: entry.offset for entry in read_embedded_index(embedded_file)}
    offset = entries["s:scan=19"]
    data = bytearray(embedded_file.read_bytes())
    data[offset + 4] ^= 0xFF
    embedded_file.write_bytes(data)

    with pytest.raises(ValueError, match="deflate stream|checksum"):
        decompress_indexed_member(embedded_file, offset)


def test_invalid_embedded_offset_is_rejected(embedded_file: Path) -> None:
    data = bytearray(embedded_file.read_bytes())
    identifier_width = data[13]
    offset_width = data[14]
    first_offset_position = 15 + identifier_width
    data[first_offset_position : first_offset_position + offset_width] = b"x" * offset_width
    embedded_file.write_bytes(data)

    with pytest.raises(ValueError, match="invalid offset"):
        read_embedded_index(embedded_file)

    with Mzml(
        embedded_file,
        gzip_mode="extract",
        in_memory=False,
        extract_dir=embedded_file.parent / "extract",
    ) as reader:
        assert reader.access_strategy is AccessStrategy.EXTRACTED
        assert reader.spectra[0].id == "scan=19"


def test_failed_write_keeps_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.mzML"
    source.write_bytes(
        b'<mzML><run><spectrumList count="2">'
        b'<spectrum id="same"></spectrum>'
        b'<spectrum id="same"></spectrum>'
        b"</spectrumList></run></mzML>"
    )
    output = tmp_path / "existing.mzML.gz"
    output.write_bytes(b"existing")

    with pytest.raises(ValueError, match="Duplicate mzML identifier"):
        write_indexed_gzip(source, output)

    assert output.read_bytes() == b"existing"
