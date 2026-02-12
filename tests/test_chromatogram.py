import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_chromatogram_reading(filename):
    reader = Mzml(filename, build_index_from_scratch=False)

    assert len(reader.chromatograms) == 2

    # Test TIC
    tic = reader.chromatograms["tic"]
    assert tic.id == "tic"
    assert tic.chromatogram_type == "tic"

    # Check binary data
    assert tic.time is not None
    assert tic.intensity is not None
    assert len(tic.time) == 15
    assert len(tic.intensity) == 15

    # Test SIC
    sic = reader.chromatograms[1]
    assert sic.id == "sic"
    assert sic.chromatogram_type == "sic"

    # Check Precursor in Chromatogram
    assert sic.has_precursor
    precursor = sic.precursor
    assert precursor is not None
    assert precursor.isolation_window is not None
    assert precursor.activation is not None

    # Check Product in Chromatogram
    assert sic.has_product
    product = sic.product
    assert product is not None
