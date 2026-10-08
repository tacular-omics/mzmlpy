"""Chromatogram types for every MS:1000626 child, and SelectedIon.possible_charges (MS:1000633)."""

from xml.etree import ElementTree as ET

import pytest

from mzmlpy import Mzml
from mzmlpy.errors import MzmlError
from mzmlpy.spectra import Chromatogram, SelectedIon

NS = "http://psi.hupo.org/ms/mzml"


def _chromatogram(*accessions: str) -> Chromatogram:
    params = "".join(f'<cvParam cvRef="MS" accession="{a}" name="x"/>' for a in accessions)
    return Chromatogram(ET.fromstring(f'<chromatogram xmlns="{NS}" id="c" index="0">{params}</chromatogram>'))


@pytest.mark.parametrize(
    ("accession", "expected"),
    [
        ("MS:1000810", "ion_current"),
        ("MS:1000811", "electromagnetic_radiation"),
        ("MS:1002715", "temperature"),
        ("MS:1003019", "pressure"),
        ("MS:1003020", "flow_rate"),
        ("MS:1001474", "crm"),
        ("MS:1000235", "tic"),
        ("MS:1000627", "sic"),
        ("MS:1000628", "basepeak"),
        ("MS:1001472", "sim"),
        ("MS:1001473", "srm"),
        ("MS:4000025", "pic"),
        ("MS:1000812", "absorption"),
        ("MS:1000813", "emission"),
    ],
)
def test_every_chromatogram_type_child_is_recognised(accession, expected):
    assert _chromatogram(accession).chromatogram_type == expected


def test_specific_chromatogram_type_beats_parent():
    assert _chromatogram("MS:1000810", "MS:1000235").chromatogram_type == "tic"
    assert _chromatogram("MS:1000811", "MS:1000812").chromatogram_type == "absorption"


def test_unknown_chromatogram_type_is_none():
    assert _chromatogram("MS:1000595").chromatogram_type is None


def _selected_ion(params: str) -> SelectedIon:
    return SelectedIon(ET.fromstring(f'<selectedIon xmlns="{NS}">{params}</selectedIon>'))


def test_possible_charges_keeps_all_in_order():
    ion = _selected_ion(
        '<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="500.25"/>'
        '<cvParam cvRef="MS" accession="MS:1000633" name="possible charge state" value="3"/>'
        '<cvParam cvRef="MS" accession="MS:1000633" name="possible charge state" value="2"/>'
        '<cvParam cvRef="MS" accession="MS:1000633" name="possible charge state" value="4"/>'
    )
    assert ion.possible_charges == (3, 2, 4)
    assert ion.charge is None


def test_possible_charges_empty_when_absent():
    ion = _selected_ion('<cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="2"/>')
    assert ion.possible_charges == ()
    assert ion.charge == 2


def test_possible_charges_non_integer_raises():
    ion = _selected_ion('<cvParam cvRef="MS" accession="MS:1000633" name="possible charge state" value="two"/>')
    with pytest.raises(MzmlError, match="possible charge state"):
        _ = ion.possible_charges


MZML = f"""<?xml version="1.0" encoding="utf-8"?>
<mzML xmlns="{NS}" version="1.1.0">
  <cvList count="1"><cv id="MS" fullName="PSI-MS" version="4.1.0" URI="x"/></cvList>
  <run id="r">
    <spectrumList count="1">
      <spectrum id="scan=1" index="0" defaultArrayLength="0">
        <cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>
        <precursorList count="1">
          <precursor>
            <selectedIonList count="1">
              <selectedIon>
                <cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="445.3"/>
                <cvParam cvRef="MS" accession="MS:1000633" name="possible charge state" value="2"/>
                <cvParam cvRef="MS" accession="MS:1000633" name="possible charge state" value="3"/>
              </selectedIon>
            </selectedIonList>
          </precursor>
        </precursorList>
      </spectrum>
    </spectrumList>
    <chromatogramList count="1">
      <chromatogram id="pump" index="0" defaultArrayLength="0">
        <cvParam cvRef="MS" accession="MS:1003019" name="pressure chromatogram"/>
      </chromatogram>
    </chromatogramList>
  </run>
</mzML>
"""


def test_from_document(tmp_path):
    path = tmp_path / "small.mzML"
    path.write_text(MZML)
    with Mzml(str(path)) as reader:
        assert reader.chromatograms["pump"].chromatogram_type == "pressure"
        ion = reader.spectra[0].precursors[0].selected_ions[0]
        assert ion.possible_charges == (2, 3)
