"""Spectrum.ion_mobility_array: the per-point ion mobility binary array."""

import base64
import warnings
from pathlib import Path

import numpy as np
import pytest

from mzmlpy import Mzml

DATA = Path(__file__).parent / "data"
COMBINED_ID = "merged=1015 frame=1016 scanStart=655 scanEnd=679"


def _array(accession: str, name: str, values: list[float]) -> str:
    encoded = base64.b64encode(np.asarray(values, dtype="<f8").tobytes()).decode()
    return (
        '<binaryDataArray encodedLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/>'
        '<cvParam cvRef="MS" accession="MS:1000576" name="no compression"/>'
        f'<cvParam cvRef="MS" accession="{accession}" name="{name}"/>'
        f"<binary>{encoded}</binary></binaryDataArray>"
    )


def _write(tmp_path: Path, arrays: list[str]) -> Path:
    path = tmp_path / "im.mzML"
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML><run id="run1">'
        '<spectrumList count="1"><spectrum index="0" id="scan=1" defaultArrayLength="2">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        f'<binaryDataArrayList count="{len(arrays)}">{"".join(arrays)}</binaryDataArrayList>'
        "</spectrum></spectrumList></run></mzML></indexedmzML>"
    )
    return path


MZ = _array("MS:1000514", "m/z array", [100.0, 200.0])
IM_MEAN = _array("MS:1003006", "mean inverse reduced ion mobility array", [0.9, 0.8])
IM_RAW = _array("MS:1002816", "mean ion mobility array", [1.5, 1.6])


def test_combined_im_array_matches_mz():
    with Mzml(str(DATA / "bruker_ms2_im_combined_im.mzML")) as reader:
        spec = reader.spectra[COMBINED_ID]
        im = spec.ion_mobility_array
        mz = spec.mz
        assert im is not None
        assert mz is not None
        assert len(im) == len(mz) == 113
        assert im.dtype == np.float64
        np.testing.assert_allclose(im[:3], [0.894, 0.892, 0.892], atol=1e-3)
        assert im.flags.writeable
        im[0] = 0.0  # a caller may edit the result
        assert im[0] == 0.0


def test_scan_level_only_spectrum_returns_none():
    with Mzml(str(DATA / "bruker_ms2_im.mzML")) as reader:
        spec = reader.spectra[0]
        assert spec.has_im is True
        assert spec.im_types == set()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert spec.ion_mobility_array is None


def test_spectrum_without_im_returns_none():
    with Mzml(str(DATA / "example.mzML")) as reader:
        spec = reader.spectra[0]
        assert spec.has_im is False
        assert spec.ion_mobility_array is None


def test_single_array_does_not_warn(tmp_path):
    with Mzml(str(_write(tmp_path, [MZ, IM_MEAN]))) as reader:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            im = reader.spectra[0].ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8])


def test_multiple_arrays_warn_and_return_first(tmp_path):
    with Mzml(str(_write(tmp_path, [MZ, IM_MEAN, IM_RAW]))) as reader:
        spec = reader.spectra[0]
        with pytest.warns(UserWarning, match="2 ion mobility arrays"):
            im = spec.ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8])  # first in document order
