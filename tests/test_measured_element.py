"""``binary_array_type`` and ``MS:1002716`` (measured element), checked against the PSI-MS CV.

Which term is an array type is read from ``tests/data/psi-ms-measured-element-terms.obo``, a
verbatim excerpt of ``psi-ms.obo`` (URL, ``data-version`` and download date in its header), not
from ``mzmlpy.constants``: ``MS:1000822`` "temperature array" is ``is_a: MS:1000513`` (binary data
array), while ``MS:1002716`` "measured element" is only ``relationship: part_of MS:1000513``.
"""

import base64
from pathlib import Path

import numpy as np
import pytest

from mzmlpy import Mzml
from mzmlpy.constants import BinaryDataArrayAccession

OBO = Path(__file__).parent / "data" / "psi-ms-measured-element-terms.obo"
BINARY_DATA_ARRAY = "MS:1000513"


def _stanzas(path: Path) -> dict[str, list[str]]:
    """``{id: [lines]}`` for every ``[Term]`` stanza in an OBO file."""
    terms: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "[Term]":
            current = []
        elif line.startswith("["):
            current = None
        elif current is not None:
            if line.startswith("id: "):
                terms[line[4:]] = current
            current.append(line)
    return terms


CV = _stanzas(OBO)


def _is_array_type(accession: str) -> bool:
    return f"is_a: {BINARY_DATA_ARRAY} ! binary data array" in CV[accession]


def test_the_cv_excerpt_says_which_term_is_an_array_type() -> None:
    assert "name: temperature array" in CV["MS:1000822"]
    assert "name: measured element" in CV["MS:1002716"]
    assert _is_array_type("MS:1000822")
    assert not _is_array_type("MS:1002716")
    assert "relationship: part_of MS:1000513 ! binary data array" in CV["MS:1002716"]


def _array(cv_params: str, values: list[float]) -> str:
    encoded = base64.b64encode(np.asarray(values, dtype="<f8").tobytes()).decode()
    return (
        f'<binaryDataArray encodedLength="{len(encoded)}">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/>'
        '<cvParam cvRef="MS" accession="MS:1000576" name="no compression"/>'
        f"{cv_params}<binary>{encoded}</binary></binaryDataArray>"
    )


TEMPERATURE = (
    '<cvParam cvRef="MS" accession="MS:1000822" name="temperature array"'
    ' unitCvRef="UO" unitAccession="UO:0000027" unitName="degree Celsius"/>'
)
TIME = (
    '<cvParam cvRef="MS" accession="MS:1000595" name="time array"'
    ' unitCvRef="UO" unitAccession="UO:0000010" unitName="second"/>'
)
MEASURED = '<cvParam cvRef="MS" accession="MS:1002716" name="measured element" value="source"/>'


def _write(tmp_path: Path, cv_params: str) -> Path:
    """One chromatogram with a time array and a second array carrying ``cv_params``."""
    path = tmp_path / "measured.mzML"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML><run id="run1">'
        '<chromatogramList count="1"><chromatogram index="0" id="source temperature" defaultArrayLength="2">'
        '<binaryDataArrayList count="2">'
        f"{_array(TIME, [0.0, 1.0])}{_array(cv_params, [35.5, 36.0])}"
        "</binaryDataArrayList></chromatogram></chromatogramList></run></mzML></indexedmzML>"
    )
    return path


@pytest.mark.parametrize(
    "cv_params", [TEMPERATURE + MEASURED, MEASURED + TEMPERATURE], ids=["type-first", "element-first"]
)
def test_measured_element_does_not_hide_the_array_type(cv_params: str, tmp_path: Path) -> None:
    with Mzml(str(_write(tmp_path, cv_params))) as reader:
        array = reader.chromatograms[0].binary_arrays[1]
        assert array.binary_array_type == BinaryDataArrayAccession.TEMPERATURE
        assert array.binary_array_type == "MS:1000822"
        measured = [p for p in array.cv_params if p.accession == "MS:1002716"]
        assert [p.value for p in measured] == ["source"]
        np.testing.assert_array_equal(array.data, [35.5, 36.0])


def test_measured_element_alone_is_still_reported(tmp_path: Path) -> None:
    """With no real array type there is nothing better to report, so the old answer stands."""
    with Mzml(str(_write(tmp_path, MEASURED))) as reader:
        array = reader.chromatograms[0].binary_arrays[1]
        assert array.binary_array_type == BinaryDataArrayAccession.MEASURED_ELEMENT


def test_the_enum_member_is_kept() -> None:
    assert BinaryDataArrayAccession.MEASURED_ELEMENT == "MS:1002716"
