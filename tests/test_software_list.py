import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_software_list(filename):
    reader = Mzml(filename, build_index_from_scratch=False)
    software_list = reader._content.softwares

    assert len(software_list) == 3

    # Check Bioworks
    bioworks = software_list[0]
    assert bioworks is not None
    assert bioworks.version == "3.3.1 sp1"
    # Access by Acession
    item = bioworks.get_cvparm("MS:1000533")
    assert item is not None
    assert item.name == "Bioworks"

    # Check pwiz
    pwiz = software_list[1]
    assert pwiz is not None
    assert pwiz.version == "1.0"
    item = pwiz.get_cvparm("MS:1000615")
    assert item is not None
    assert item.name == "ProteoWizard"

    # Check CompassXtract
    compass = software_list[2]
    assert compass is not None
    assert compass.version == "2.0.5"
    item = compass.get_cvparm("MS:1000718")
    assert item is not None
    assert item.name == "CompassXtract"
