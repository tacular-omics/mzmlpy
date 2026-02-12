import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_data_processing(filename):
    reader = Mzml(filename, build_index_from_scratch=False)
    procs = reader._content.data_processes

    assert len(procs) == 2

    # Check CompassXtract processing
    compass_proc = procs["CompassXtract_x0020_processing"]
    assert len(compass_proc.processing_methods) == 1

    method = compass_proc.processing_methods[0]
    assert method.order == 1
    assert method.software_ref == "CompassXtract"

    assert method.get_cvparm("MS:1000033").name == "deisotoping"
    assert method.get_cvparm("MS:1000034").name == "charge deconvolution"
    assert method.get_cvparm("MS:1000035").name == "peak picking"

    # Check pwiz processing
    pwiz_proc = procs["pwiz_processing"]
    assert len(pwiz_proc.processing_methods) == 1

    method = pwiz_proc.processing_methods[0]
    assert method.order == 2
    assert method.software_ref == "pwiz"

    assert method.get_cvparm("MS:1000544").name == "Conversion to mzML"
