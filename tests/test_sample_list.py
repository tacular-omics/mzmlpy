import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_sample_list(filename):
    reader = Mzml(filename, build_index_from_scratch=False)
    samples = reader._content.samples

    assert len(samples) == 1
    sample = samples[0]
    assert sample.id == "_x0032_0090101_x0020_-_x0020_Sample_x0020_1"
    assert sample.name == "Sample 1"
