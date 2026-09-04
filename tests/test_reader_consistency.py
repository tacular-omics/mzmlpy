"""Regression coverage for equivalent documents and independent storage backends."""

import gzip
import os
import re
import tracemalloc
from contextlib import ExitStack
from pathlib import Path

import pytest

from mzmlpy import Mzml, write_indexed_gzip
from mzmlpy.util import atomic_write_path

MODES = ["memory", "plain", "extract", "stream", "embedded", "indexed"]


def document(identifier: str = "scan=1", count: int = 1, payload: str = "", chromatograms: bool = True) -> bytes:
    spectra = "".join(
        f'<spectrum id="{identifier if count == 1 else f"scan={i}"}" index="{i}" defaultArrayLength="0">'
        '<cvParam accession="MS:1000511" name="ms level" value="1"/>'
        f'<binaryDataArrayList count="1"><binaryDataArray><binary>{payload}</binary>'
        "</binaryDataArray></binaryDataArrayList></spectrum>"
        for i in range(count)
    )
    chrom = (
        '<chromatogramList count="1"><chromatogram id="tic" defaultArrayLength="0">'
        '<cvParam accession="MS:1000235" name="total ion current chromatogram"/>'
        "</chromatogram></chromatogramList>"
        if chromatograms
        else ""
    )
    return (
        '<mzML xmlns="http://psi.hupo.org/ms/mzml" id="audit-run" version="1.1.0">'
        f'<run id="run"><spectrumList count="{count}">{spectra}</spectrumList>{chrom}</run></mzML>'
    ).encode()


def open_mode(path: Path, mode: str) -> Mzml:
    if mode in {"memory", "plain"}:
        return Mzml(path, in_memory=mode == "memory")
    output = path.with_suffix(".mzML.gz")
    if mode == "embedded":
        write_indexed_gzip(path, output)
        return Mzml(output, in_memory=False)
    if mode == "indexed":
        pytest.importorskip("rapidgzip")
    output.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    return Mzml(output, in_memory=False, gzip_mode=mode, extract_dir=path.parent / "cache")


@pytest.mark.filterwarnings("ignore:Random access on gzip_mode='stream'")
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "variant", ["plain", "single_quotes", "prefix", "scoped_prefix", "long_tag", "comment", "cdata", "empty_tag"]
)
def test_xml_variants_agree_on_counts_and_lookup(tmp_path: Path, mode: str, variant: str) -> None:
    data = document()
    if variant == "single_quotes":
        data = data.replace(b'"', b"'")
    elif variant == "prefix":
        data = re.sub(rb"<(/?)([A-Za-z][A-Za-z0-9]*)", rb"<\1m:\2", data).replace(b"xmlns=", b"xmlns:m=")
    elif variant == "scoped_prefix":
        data = data.replace(
            b"<chromatogramList count=", b'<chromatogramList xmlns:c="http://psi.hupo.org/ms/mzml" count='
        )
        data = data.replace(b"<chromatogram id=", b"<c:chromatogram id=").replace(
            b"</chromatogram>", b"</c:chromatogram>"
        )
    elif variant == "long_tag":
        data = data.replace(b"<spectrum id=", b"<spectrum " + b" " * 20000 + b"id=")
    elif variant == "comment":
        data = data.replace(b"<run id=", b'<!-- <spectrum id="fake"></spectrum> --><run id=')
    elif variant == "cdata":
        data = data.replace(b"<binary></binary>", b"<binary><![CDATA[</spectrum>]]></binary>")
    elif variant == "empty_tag":
        data = re.sub(rb"<spectrum id=.*?</spectrum>", b'<spectrum id="scan=1" defaultArrayLength="0"/>', data)
    path = tmp_path / "variant.mzML"
    path.write_bytes(data)
    with open_mode(path, mode) as reader:
        assert (reader.id, reader.version) == ("audit-run", "1.1.0")
        spectra = list(reader.spectra)
        assert len(spectra) == len(reader.spectra) == 1
        assert reader.spectra[0].id == reader.spectra["scan=1"].id == spectra[0].id
        assert reader.spectra[-1].id == "scan=1"
        assert len(reader.chromatograms) == 1
        assert reader.chromatograms[0].id == reader.TIC.id == "tic"
        for lookup in (reader.spectra, reader.chromatograms):
            for index in (-2, 1):
                with pytest.raises(IndexError):
                    _ = lookup[index]


@pytest.mark.parametrize("from_scratch", [False, True])
def test_compact_footer_and_fallback_agree(tmp_path: Path, from_scratch: bool) -> None:
    data = Path("tests/data/example.mzML").read_bytes()
    start = data.index(b"<indexList count=")
    path = tmp_path / "compact.mzML"
    path.write_bytes(data[:start] + re.sub(rb">\s+<", b"><", data[start:]))
    with Mzml(path, in_memory=False, build_index_from_scratch=from_scratch) as reader:
        assert len(reader.spectra) == 4
        assert [reader.spectra[i].id for i in range(4)] == [s.id for s in reader.spectra]
        assert len(reader.chromatograms) == 2


def test_bad_footer_fallback_discards_partial_entries(tmp_path: Path) -> None:
    data = Path("tests/data/example.mzML").read_bytes()
    start = data.index(b"<indexList count=")
    footer = data[start:].replace(b'idRef="scan=19"', b'idRef="ghost"').replace(b'idRef="scan=20"', b'idRef="ghost"')
    path = tmp_path / "invalid-index.mzML"
    path.write_bytes(data[:start] + footer)
    with Mzml(path, in_memory=False) as reader:
        assert len(reader.spectra) == 4
        assert "ghost" not in reader._file_object.spectrum_ids
        assert reader.spectra[0].id == "scan=19"


@pytest.mark.parametrize("count, chromatograms", [(1, False), (0, True), (0, False)])
def test_embedded_absent_record_kinds(tmp_path: Path, count: int, chromatograms: bool) -> None:
    path = tmp_path / "missing.mzML"
    path.write_bytes(document(count=count, chromatograms=chromatograms))
    with open_mode(path, "embedded") as reader:
        assert len(reader.spectra) == len(list(reader.spectra)) == count
        assert len(reader.chromatograms) == len(list(reader.chromatograms)) == int(chromatograms)
        assert (reader.TIC is not None) == chromatograms


def test_shared_extraction_cache_preserves_both_sources(tmp_path: Path) -> None:
    paths = []
    for name, identifier in [("a", "scan=1"), ("b", "scan=2")]:
        directory = tmp_path / name
        directory.mkdir()
        path = directory / "sample.mzML.gz"
        path.write_bytes(gzip.compress(document(identifier), compresslevel=0, mtime=0))
        os.utime(path, ns=(1700000000000000000, 1700000000000000000))
        paths.append(path)
    assert paths[0].stat().st_size == paths[1].stat().st_size
    with ExitStack() as stack:
        readers = [stack.enter_context(Mzml(p, in_memory=False, extract_dir=tmp_path / "cache")) for p in paths]
        assert [r.spectra[0].id for r in readers] == ["scan=1", "scan=2"]
        paths[0].write_bytes(gzip.compress(document("scan=3"), compresslevel=0, mtime=0))
        with Mzml(paths[0], in_memory=False, extract_dir=tmp_path / "cache") as updated:
            assert updated.spectra[0].id == "scan=3"
            assert readers[0].spectra[0].id == "scan=1"


def test_overlapping_atomic_writes_have_independent_temporaries(tmp_path: Path) -> None:
    destination = tmp_path / "output"
    with atomic_write_path(str(destination)) as first:
        Path(first).write_text("first")
        with atomic_write_path(str(destination)) as second:
            assert second != first
            Path(second).write_text("second")
        assert destination.read_text() == "second"
    assert destination.read_text() == "first"
    assert sorted(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("mode", ["plain", "memory", "stream", "extract"])
def test_reading_chromatograms_does_not_retain_spectra(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "large.mzML"
    path.write_bytes(document(count=1000, payload="A" * 20000))
    with open_mode(path, mode) as reader:
        tracemalloc.start()
        try:
            chromatograms = list(reader.chromatograms)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert len(chromatograms) == 1
        assert peak < 4 * 1024 * 1024


@pytest.mark.parametrize("compressed", [False, True])
def test_cold_open_has_bounded_python_memory(tmp_path: Path, compressed: bool) -> None:
    path = tmp_path / "cold.mzML"
    data = document(count=1000, payload="A" * 20000)
    if compressed:
        path = path.with_suffix(".mzML.gz")
        data = gzip.compress(data)
    path.write_bytes(data)
    del data
    tracemalloc.start()
    try:
        with Mzml(path, in_memory=False, extract_dir=tmp_path / "cache") as reader:
            assert len(reader.spectra) == 1000
            _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024


def test_invalid_rapidgzip_sidecars_are_rebuilt(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    from mzmlpy.util import write_cache_signature

    source = tmp_path / "cached.mzML.gz"
    source.write_bytes(gzip.compress(document()))
    with Mzml(source, in_memory=False, gzip_mode="indexed"):
        pass
    mzml_index = str(source.with_suffix("")) + "idx"
    Path(mzml_index).write_text('{"spectrum_offsets": [["scan=1", "invalid"]], "chromatogram_offsets": []}')
    write_cache_signature(mzml_index, str(source))
    gzip_index = str(source) + "idx"
    Path(gzip_index).write_bytes(b"corrupt seek index")
    write_cache_signature(gzip_index, str(source))
    with Mzml(source, in_memory=False, gzip_mode="indexed") as reader:
        assert reader.spectra[0].id == "scan=1"
        assert reader.chromatograms[0].id == "tic"
