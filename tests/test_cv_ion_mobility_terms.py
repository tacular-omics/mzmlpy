"""``ION_MOBILITIES`` against the PSI-MS controlled vocabulary itself.

Every expected value in this module is **sourced outside mzmlpy**: it is parsed from
``tests/data/psi-ms-ion-mobility-array-terms.obo``, a verbatim excerpt of ``psi-ms.obo``
downloaded from HUPO-PSI (its URL, the CV's ``data-version`` and the download date are in the
file's own header). Nothing is compared against a list written by hand here or taken from
``mzmlpy.constants``, so this test fails when the CV and the constant disagree, whichever of
the two moved. Refresh the fixture from the URL in its header when the CV gains a term.

The governing sentence, from the ``MS:1002893`` stanza in that file:

    def: "Abstract array of ion mobility data values. A more specific child term concept
    should be specified in data files to make precise the nature of the data being provided."

So the terms a reader must recognise as an ion mobility array are ``MS:1002893`` and every
term whose ``is_a`` is ``MS:1002893``.
"""

import base64
import warnings
from pathlib import Path

import numpy as np
import pytest

from mzmlpy import Mzml
from mzmlpy.constants import ION_MOBILITIES, BinaryDataArrayAccession

OBO = Path(__file__).parent / "data" / "psi-ms-ion-mobility-array-terms.obo"
ION_MOBILITY_ARRAY = "MS:1002893"


def _cv_terms(path: Path) -> dict[str, dict[str, list[str] | str | bool]]:
    """Parse the ``[Term]`` stanzas of an OBO file into ``{id: {name, is_a, obsolete}}``."""
    terms: dict[str, dict[str, list[str] | str | bool]] = {}
    current: dict[str, list[str] | str | bool] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line == "[Term]":
            current = {"name": "", "is_a": [], "obsolete": False}
        elif line.startswith("[") and line.endswith("]"):
            current = None
        elif current is not None and ": " in line and not line.startswith("!"):
            key, _, value = line.partition(": ")
            if key == "id":
                terms[value] = current
            elif key == "name":
                current["name"] = value
            elif key == "is_a":
                parents = current["is_a"]
                assert isinstance(parents, list)
                parents.append(value.split(" ! ")[0].strip())
            elif key == "is_obsolete" and value == "true":
                current["obsolete"] = True
    return terms


CV = _cv_terms(OBO)
CV_ION_MOBILITY_ARRAYS = {ION_MOBILITY_ARRAY} | {
    accession for accession, term in CV.items() if ION_MOBILITY_ARRAY in term["is_a"]
}


def test_the_fixture_really_is_the_cv_excerpt_it_claims_to_be() -> None:
    """Guard the apparatus: an empty or mis-parsed fixture would make every test below vacuous."""
    assert len(CV) == 10, f"expected the parent and its nine children, parsed {len(CV)}"
    assert CV[ION_MOBILITY_ARRAY]["name"] == "ion mobility array"
    assert CV[ION_MOBILITY_ARRAY]["is_a"] == ["MS:1000513"]  # binary data array
    assert len(CV_ION_MOBILITY_ARRAYS) == 10
    assert not [accession for accession, term in CV.items() if term["obsolete"]]
    # Names vary ("mean ion mobility array", "raw ion mobility drift time array"), so check the shape.
    assert all("ion mobility" in str(term["name"]) and str(term["name"]).endswith("array") for term in CV.values())


def test_ion_mobilities_is_exactly_the_cv_ion_mobility_array_subtree() -> None:
    """The expected set is parsed from the CV excerpt, not written here and not read from mzmlpy."""
    assert {str(accession) for accession in ION_MOBILITIES} == CV_ION_MOBILITY_ARRAYS


def test_every_cv_ion_mobility_array_term_is_a_declared_array_accession() -> None:
    declared = {str(accession) for accession in BinaryDataArrayAccession}
    assert CV_ION_MOBILITY_ARRAYS <= declared


def _array(accession: str, name: str, values: list[float]) -> str:
    encoded = base64.b64encode(np.asarray(values, dtype="<f8").tobytes()).decode()
    return (
        f'<binaryDataArray encodedLength="{len(encoded)}">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/>'
        '<cvParam cvRef="MS" accession="MS:1000576" name="no compression"/>'
        f'<cvParam cvRef="MS" accession="{accession}" name="{name}"/>'
        f"<binary>{encoded}</binary></binaryDataArray>"
    )


def _write(tmp_path: Path, accession: str, name: str) -> Path:
    """One two-point spectrum whose only ion mobility array carries ``accession``."""
    path = tmp_path / "im.mzML"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML><run id="run1">'
        '<spectrumList count="1"><spectrum index="0" id="scan=1" defaultArrayLength="2">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<binaryDataArrayList count="2">'
        f"{_array('MS:1000514', 'm/z array', [100.0, 200.0])}{_array(accession, name, [0.9, 0.8])}"
        "</binaryDataArrayList></spectrum></spectrumList></run></mzML></indexedmzML>"
    )
    return path


@pytest.mark.parametrize("accession", sorted(CV_ION_MOBILITY_ARRAYS))
def test_a_spectrum_carrying_each_cv_term_reports_its_ion_mobility_array(accession: str, tmp_path: Path) -> None:
    """Both the accessions and their names come from the CV excerpt, so the inputs are the CV's."""
    name = str(CV[accession]["name"])
    with Mzml(str(_write(tmp_path, accession, name))) as reader:
        spec = reader.spectra[0]
        assert spec.has_im is True, f"{accession} ({name}) is not recognised"
        assert spec.im_types == {BinaryDataArrayAccession(accession)}
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            im = spec.ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8])
