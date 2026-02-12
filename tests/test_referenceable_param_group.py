import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_referenceable_param_groups(filename):
    reader = Mzml(filename, build_index_from_scratch=False)
    rpgs = reader._content.referenceable_param_groups

    assert len(rpgs) == 2

    # Test CommonMS1SpectrumParams
    ms1_group = rpgs["CommonMS1SpectrumParams"]
    assert ms1_group is not None

    ms1_spectrum_param = ms1_group.get_cvparm("MS:1000579")
    assert ms1_spectrum_param is not None
    assert ms1_spectrum_param.name == "MS1 spectrum"

    positive_scan_param = ms1_group.get_cvparm("MS:1000130")
    assert positive_scan_param is not None
    assert positive_scan_param.name == "positive scan"

    # Test CommonMS2SpectrumParams
    ms2_group = rpgs["CommonMS2SpectrumParams"]
    assert ms2_group is not None

    msn_spectrum_param = ms2_group.get_cvparm("MS:1000580")
    assert msn_spectrum_param is not None
    assert msn_spectrum_param.name == "MSn spectrum"

    positive_scan_param = ms2_group.get_cvparm("MS:1000130")
    assert positive_scan_param is not None
