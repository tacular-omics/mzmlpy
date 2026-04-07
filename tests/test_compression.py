import numpy as np
import pytest

from mzmlpy import Mzml

LOSSLESS_FILES = [
    "tests/data/zlib_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "tests/data/zstd_20250806_ArgC_DDA_HCD-FT_01.mzML",
]

NUMPRESS_FILES = [
    "tests/data/numpresslinear_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "tests/data/numpresspic_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "tests/data/numpressslof_20250806_ArgC_DDA_HCD-FT_01.mzML",
]

NOT_IMPLEMENTED_FILES = [
    "tests/data/mzshufflezstd_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "tests/data/dictzstd_20250806_ArgC_DDA_HCD-FT_01.mzML",
]

EXPECTED_ID = "controllerType=0 controllerNumber=1 scan=339"
EXPECTED_MZ = np.array([114.95743560791016, 129.10096740722656, 131.0811767578125])
EXPECTED_INT = np.array([2163.010498046875, 22231.859375, 2310.19091796875])


# --- Lossless compression (zlib, zstd) ---


@pytest.mark.parametrize("filename", LOSSLESS_FILES)
def test_lossless_structural(filename):
    reader = Mzml(filename)
    assert len(reader.spectra) == 10
    assert len(reader.chromatograms) == 1

    s = reader.spectra[0]
    assert s.id == EXPECTED_ID
    assert s.ms_level == 2
    assert len(s.mz) == 112
    assert len(s.intensity) == 112


@pytest.mark.parametrize("filename", LOSSLESS_FILES)
def test_lossless_values(filename):
    reader = Mzml(filename)
    s = reader.spectra[0]
    np.testing.assert_array_equal(s.mz[:3], EXPECTED_MZ)
    np.testing.assert_array_equal(s.intensity[:3], EXPECTED_INT)


def test_lossless_cross_compression():
    """Verify zlib and zstd produce identical binary data (both are lossless)."""
    zlib_reader = Mzml(LOSSLESS_FILES[0])
    zstd_reader = Mzml(LOSSLESS_FILES[1])

    zlib_s = zlib_reader.spectra[0]
    zstd_s = zstd_reader.spectra[0]

    np.testing.assert_array_equal(zlib_s.mz, zstd_s.mz)
    np.testing.assert_array_equal(zlib_s.intensity, zstd_s.intensity)


# --- Numpress lossy compression ---


@pytest.mark.parametrize("filename", NUMPRESS_FILES)
def test_numpress_structural(filename):
    pytest.importorskip("pynumpress")
    reader = Mzml(filename)
    assert len(reader.spectra) == 10
    assert len(reader.chromatograms) == 1

    s = reader.spectra[0]
    assert s.id == EXPECTED_ID
    assert s.ms_level == 2
    assert len(s.mz) == 112
    assert len(s.intensity) == 112


@pytest.mark.parametrize("filename", NUMPRESS_FILES)
def test_numpress_values(filename):
    pytest.importorskip("pynumpress")
    reader = Mzml(filename)
    s = reader.spectra[0]

    # Numpress is lossy -- values should be close but not necessarily exact
    np.testing.assert_allclose(s.mz[:3], EXPECTED_MZ, rtol=1e-4)
    np.testing.assert_allclose(s.intensity[:3], EXPECTED_INT, rtol=1e-2)


# --- Not-yet-implemented compression ---


@pytest.mark.parametrize("filename", NOT_IMPLEMENTED_FILES)
def test_not_implemented_raises(filename):
    reader = Mzml(filename)
    s = reader.spectra[0]
    with pytest.raises(NotImplementedError):
        _ = s.mz
