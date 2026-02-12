import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_instrument_configuration(filename):
    reader = Mzml(filename, build_index_from_scratch=False)
    configs = reader._content.instrument_configurations

    assert len(configs) == 1
    config = configs["LCQ_x0020_Deca"]

    # Check ID and Params
    assert config.id == "LCQ_x0020_Deca"
    assert config.get_cvparm("MS:1000554").name == "LCQ Deca"
    assert config.get_cvparm("MS:1000529").value == "23433"

    # Check Software Ref
    assert config.software_ref == "CompassXtract"

    # Check Components
    assert len(config.source_components) == 1
    source = config.source_components[0]
    assert source.order == 1
    assert source.get_cvparm("MS:1000398").name == "nanoelectrospray"

    assert len(config.analyzer_components) == 1
    analyzer = config.analyzer_components[0]
    assert analyzer.order == 2
    assert analyzer.get_cvparm("MS:1000082").name == "quadrupole ion trap"

    assert len(config.detector_components) == 1
    detector = config.detector_components[0]
    assert detector.order == 3
    assert detector.get_cvparm("MS:1000253").name == "electron multiplier"
