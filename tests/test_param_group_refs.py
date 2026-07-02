"""referenceableParamGroupRef resolution (spectrum-level, scan-level/nested, and dedup)."""

import pytest

from mzmlpy import Mzml

# Minimal mzML: a spectrum inherits polarity from a group at the spectrum level and a filter
# string from a group at the (nested) scan level, and also specifies one grouped term directly
# to exercise de-duplication.
SYNTHETIC = """<?xml version="1.0" encoding="utf-8"?>
<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">
<mzML>
  <referenceableParamGroupList count="2">
    <referenceableParamGroup id="SpecGroup">
      <cvParam cvRef="MS" accession="MS:1000130" name="positive scan" value=""/>
      <cvParam cvRef="MS" accession="MS:1000579" name="MS1 spectrum" value=""/>
    </referenceableParamGroup>
    <referenceableParamGroup id="ScanGroup">
      <cvParam cvRef="MS" accession="MS:1000512" name="filter string" value="FTMS + p"/>
    </referenceableParamGroup>
  </referenceableParamGroupList>
  <run id="run1">
    <spectrumList count="1" defaultDataProcessingRef="dp">
      <spectrum index="0" id="scan=1" defaultArrayLength="0">
        <referenceableParamGroupRef ref="SpecGroup"/>
        <cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>
        <cvParam cvRef="MS" accession="MS:1000130" name="positive scan" value=""/>
        <scanList count="1">
          <scan>
            <referenceableParamGroupRef ref="ScanGroup"/>
          </scan>
        </scanList>
      </spectrum>
    </spectrumList>
  </run>
</mzML>
</indexedmzML>
"""


@pytest.fixture()
def synthetic_reader(tmp_path):
    path = tmp_path / "synthetic.mzML"
    path.write_text(SYNTHETIC)
    return Mzml(str(path))


def test_spectrum_level_ref_resolved(synthetic_reader):
    s = synthetic_reader.spectra[0]
    assert s.polarity == "positive"  # MS:1000130 comes only from SpecGroup (plus a direct copy)
    assert s.has_cvparm("MS:1000579")  # MS1 spectrum, group-only


def test_scan_level_nested_ref_resolved(synthetic_reader):
    scan = synthetic_reader.spectra[0].scans[0]
    # filter string is supplied via a scan-level referenceableParamGroupRef (nested in the subtree)
    fs = scan.get_cvparm("MS:1000512")
    assert fs is not None
    assert fs.value == "FTMS + p"


def test_no_duplicate_when_term_present_directly(synthetic_reader):
    s = synthetic_reader.spectra[0]
    # MS:1000130 appears both directly on the spectrum and in SpecGroup: it must resolve once.
    positive_scan = [p for p in s.cv_params if p.accession == "MS:1000130"]
    assert len(positive_scan) == 1


def test_provenance_ref_preserved(synthetic_reader):
    s = synthetic_reader.spectra[0]
    assert [rp.ref for rp in s.ref_params] == ["SpecGroup"]


def test_resolution_is_idempotent_across_accesses(synthetic_reader):
    # Re-materializing the spectrum must not accumulate duplicate inserted params.
    counts = {len(synthetic_reader.spectra[0].cv_params) for _ in range(3)}
    assert len(counts) == 1
