"""The offset index is a cache of the document, so every accessor must report the same records.

Each document here is written with an index that names fewer records than the document holds,
which is what a writer that stops early leaves behind. A reader may not answer such a file two
ways: ``len``, ``ids``, ``in``, ``__getitem__`` and iteration all read the same records, and the
disagreement that caused the rebuild is reported rather than absorbed.
"""

import warnings
from pathlib import Path

import pytest

from mzmlpy import Mzml

HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n'
    '<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0" id="agreement">\n'
    '<cvList count="1"><cv id="MS" fullName="PSI-MS" URI="https://purl.obolibrary.org/obo/ms.obo"/></cvList>\n'
    "<fileDescription><fileContent/></fileDescription>\n"
    '<softwareList count="1"><software id="sw" version="1"/></softwareList>\n'
    '<instrumentConfigurationList count="1"><instrumentConfiguration id="IC"/></instrumentConfigurationList>\n'
    '<dataProcessingList count="1"><dataProcessing id="DP"/></dataProcessingList>\n'
    '<run id="r" defaultInstrumentConfigurationRef="IC">\n'
)


def _record(kind: str, index: int, identifier: str) -> str:
    term = "MS:1000511" if kind == "spectrum" else "MS:1000235"
    array = "MS:1000514" if kind == "spectrum" else "MS:1000595"
    return (
        f'<{kind} index="{index}" id="{identifier}" defaultArrayLength="0">'
        f'<cvParam cvRef="MS" accession="{term}" name="term" value="1"/>'
        '<binaryDataArrayList count="1"><binaryDataArray encodedLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>'
        '<cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>'
        f'<cvParam cvRef="MS" accession="{array}" name="array" value=""/>'
        f"<binary></binary></binaryDataArray></binaryDataArrayList></{kind}>\n"
    )


def build(
    *,
    spectra: int,
    chromatograms: int = 0,
    declared_spectra: int | None = None,
    declared_chromatograms: int | None = None,
    indexed_spectra: list[int] | None = None,
    indexed_chromatograms: list[int] | None = None,
) -> bytes:
    """An indexedmzML document whose index may name fewer records than the document holds.

    ``declared_*`` set the list ``count`` attributes (by default the honest counts) and
    ``indexed_*`` choose which record positions get an ``<offset>`` entry (by default all).
    """
    body = bytearray(HEADER.encode())
    offsets: dict[str, list[tuple[str, int]]] = {"spectrum": [], "chromatogram": []}
    for kind, total, declared in (
        ("spectrum", spectra, declared_spectra),
        ("chromatogram", chromatograms, declared_chromatograms),
    ):
        if kind == "chromatogram" and not total:
            continue
        count = total if declared is None else declared
        body += f'<{kind}List count="{count}" defaultDataProcessingRef="DP">\n'.encode()
        for position in range(total):
            identifier = f"scan={position}" if kind == "spectrum" else f"chrom={position}"
            offsets[kind].append((identifier, len(body)))
            body += _record(kind, position, identifier).encode()
        body += f"</{kind}List>\n".encode()
    body += b"</run>\n</mzML>\n"

    def pick(kind: str, positions: list[int] | None) -> list[tuple[str, int]]:
        return offsets[kind] if positions is None else [offsets[kind][position] for position in positions]

    chosen = {
        "spectrum": pick("spectrum", indexed_spectra),
        "chromatogram": pick("chromatogram", indexed_chromatograms),
    }
    sections = [kind for kind in ("spectrum", "chromatogram") if chosen[kind]]
    index_offset = len(body)
    body += f'<indexList count="{len(sections)}">'.encode()
    for kind in sections:
        body += f'<index name="{kind}">'.encode()
        for identifier, offset in chosen[kind]:
            body += f'<offset idRef="{identifier}">{offset}</offset>'.encode()
        body += b"</index>"
    body += b"</indexList>\n"
    body += f"<indexListOffset>{index_offset}</indexListOffset>\n</indexedmzML>\n".encode()
    return bytes(body)


def _written(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / f"{name}.mzML"
    path.write_bytes(data)
    return str(path)


def assert_accessors_agree(reader: Mzml, kind: str, identifiers: list[str]) -> None:
    """Every way of reaching the records of one kind reports exactly ``identifiers``."""
    lookup = reader.spectra if kind == "spectrum" else reader.chromatograms
    assert [record.id for record in lookup] == identifiers
    assert lookup.ids == identifiers
    assert len(lookup) == len(identifiers)
    for position, identifier in enumerate(identifiers):
        assert identifier in lookup
        assert lookup[position].id == identifier
        assert lookup[identifier].id == identifier
    with pytest.raises(IndexError):
        lookup[len(identifiers)]


@pytest.mark.parametrize(
    ("document", "kind", "identifiers", "message"),
    [
        pytest.param(
            # The count agrees with the short index: a writer that stops early gets both wrong.
            build(spectra=2, declared_spectra=1, indexed_spectra=[0]),
            "spectrum",
            ["scan=0", "scan=1"],
            "Index does not list every spectrum",
            id="spectrum_trailing_count_agrees",
        ),
        pytest.param(
            build(spectra=2, indexed_spectra=[0]),
            "spectrum",
            ["scan=0", "scan=1"],
            "Spectrum index count does not match spectrumList",
            id="spectrum_trailing_count_honest",
        ),
        pytest.param(
            build(spectra=1, chromatograms=2, indexed_chromatograms=[0]),
            "chromatogram",
            ["chrom=0", "chrom=1"],
            "Chromatogram index count does not match chromatogramList",
            id="chromatogram_trailing",
        ),
        pytest.param(
            # The whole chromatogram section missing from the index used to drop every one.
            build(spectra=1, chromatograms=2, indexed_chromatograms=[]),
            "chromatogram",
            ["chrom=0", "chrom=1"],
            "Chromatogram index count does not match chromatogramList",
            id="chromatogram_section_absent",
        ),
        pytest.param(
            # Too many chromatograms for the list's start tag to be in the window read before
            # the first one, so only its end tag proves the index left the whole list out.
            build(spectra=1, chromatograms=24, indexed_chromatograms=[]),
            "chromatogram",
            [f"chrom={position}" for position in range(24)],
            "Index lists no chromatogram",
            id="chromatogram_section_absent_long_list",
        ),
    ],
)
def test_short_index_is_rebuilt_before_any_accessor_answers(
    tmp_path: Path, document: bytes, kind: str, identifiers: list[str], message: str
) -> None:
    with pytest.warns(UserWarning, match=message):
        reader = Mzml(_written(tmp_path, "short_index", document))
    with reader:
        assert_accessors_agree(reader, kind, identifiers)


def test_record_missing_from_the_middle_is_proved_by_reading_it(tmp_path: Path) -> None:
    """A gap the counts hide is proved by the span that holds it, and the index is rebuilt then.

    The declared count matches the two entries the index does name, and the last of them ends
    the list, so nothing bounded can tell at open that a third record sits between them. The
    span of the first entry runs to the second and holds both, which proves it on first read.
    """
    path = _written(tmp_path, "middle", build(spectra=3, declared_spectra=2, indexed_spectra=[0, 2]))
    with Mzml(path) as reader:
        assert reader.spectra.ids == ["scan=0", "scan=2"]  # the file's own index and count, so far
        with pytest.warns(UserWarning, match="does not list every spectrum"):
            assert [spectrum.id for spectrum in reader.spectra] == ["scan=0", "scan=1", "scan=2"]
        assert_accessors_agree(reader, "spectrum", ["scan=0", "scan=1", "scan=2"])


def test_agreement_does_not_depend_on_the_access_strategy(tmp_path: Path) -> None:
    """The checks live in the shared random-access base, so a buffered reader agrees too."""
    path = _written(tmp_path, "in_memory", build(spectra=2, declared_spectra=1, indexed_spectra=[0]))
    with pytest.warns(UserWarning, match="Index does not list every spectrum"):
        reader = Mzml(path, in_memory=True)
    with reader:
        assert reader.access_strategy == "memory"
        assert_accessors_agree(reader, "spectrum", ["scan=0", "scan=1"])


def test_complete_index_is_trusted_and_never_rebuilt(tmp_path: Path) -> None:
    """The checks must not fire on a sound file: no warning, and the indexed fast path survives."""
    path = _written(tmp_path, "complete", build(spectra=3, chromatograms=2))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with Mzml(path) as reader:
            backend = reader._file_object.file_handler  # noqa: SLF001
            assert backend.can_iterate_indexed("spectrum")
            assert backend.can_iterate_indexed("chromatogram")
            assert_accessors_agree(reader, "spectrum", ["scan=0", "scan=1", "scan=2"])
            assert_accessors_agree(reader, "chromatogram", ["chrom=0", "chrom=1"])


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_example_files_keep_their_index(filename: str) -> None:
    """The shipped examples are sound, so neither check rejects their index."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with Mzml(filename) as reader:
            assert reader.spectra.ids == [spectrum.id for spectrum in reader.spectra]
            assert reader.chromatograms.ids == [chromatogram.id for chromatogram in reader.chromatograms]
