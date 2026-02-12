import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_file_description(filename):
    reader = Mzml(filename, build_index_from_scratch=False)
    fd = reader._content.file_description

    # Test FileContent
    assert fd.file_content is not None
    # Access by Accession
    msn_spectrum = fd.file_content.get_cvparm("MS:1000580")
    assert msn_spectrum is not None
    assert msn_spectrum.name == "MSn spectrum"

    # Access by Name
    centroid_spectrum = fd.file_content.get_cvparm("centroid spectrum")
    assert centroid_spectrum is not None
    assert centroid_spectrum.accession == "MS:1000127"

    # Test SourceFiles
    assert len(fd.source_files) == 3
    sf1 = fd.source_files[0]
    assert sf1.id == "tiny1.yep"
    assert sf1.name == "tiny1.yep"
    assert sf1.location == "file://F:/data/Exp01"

    # Check cv params in source file
    yep_file_param = sf1.get_cvparm("MS:1000567")
    assert yep_file_param is not None
    assert yep_file_param.name == "Bruker/Agilent YEP file"

    sha1_param = sf1.get_cvparm("MS:1000569")
    assert sha1_param is not None
    assert sha1_param.value == "1234567890123456789012345678901234567890"

    sf3 = fd.source_files[2]
    assert sf3.id == "sf_parameters"
    assert sf3.name == "parameters.par"

    # Test Contact
    assert fd.contact is not None
    assert len(fd.contact) == 1
    assert fd.contact[0].get_cvparm("MS:1000586").value == "William Pennington"
    assert fd.contact[0].get_cvparm("contact organization").value == "Higglesworth University"
    assert fd.contact[0].get_cvparm("MS:1000589").value == "wpennington@higglesworth.edu"

    c = fd.contact[0]
    assert c.name == "William Pennington"
    assert c.organization == "Higglesworth University"
    assert c.email == "wpennington@higglesworth.edu"
    assert c.address == "12 Higglesworth Avenue, 12045, HI, USA"
