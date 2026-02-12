import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_scan_settings(filename):
    reader = Mzml(filename, build_index_from_scratch=False)
    scan_settings = reader._content.scan_settings

    assert len(scan_settings) == 1

    settings = scan_settings["tiny_x0020_scan_x0020_settings"]
    assert settings.id == "tiny_x0020_scan_x0020_settings"

    # Check source file refs
    assert len(settings.source_file_refs) == 1
    assert settings.source_file_refs[0].ref == "sf_parameters"

    # Check targets
    assert len(settings.targets) == 2

    t1 = settings.targets[0]
    param1 = t1.get_cvparm("MS:1000744")
    assert param1 is not None
    assert param1.value == "1000"
    assert param1.unit_name == "m/z"

    t2 = settings.targets[1]
    param2 = t2.get_cvparm("MS:1000744")
    assert param2 is not None
    assert param2.value == "1200"
