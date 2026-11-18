"""Spectrum.ion_mobility_array: the per-point ion mobility binary array."""

import base64
import warnings
from pathlib import Path

import numpy as np
import pytest

from mzmlpy import Mzml, validate
from mzmlpy.constants import BinaryDataArrayAccession

DATA = Path(__file__).parent / "data"
COMBINED_ID = "merged=1015 frame=1016 scanStart=655 scanEnd=679"


def _array(accession: str, name: str, values: list[float], array_length: int | None = None) -> str:
    """One binaryDataArray. ``array_length`` writes the optional per-array ``arrayLength`` attribute."""
    encoded = base64.b64encode(np.asarray(values, dtype="<f8").tobytes()).decode()
    declared = "" if array_length is None else f' arrayLength="{array_length}"'
    return (
        f'<binaryDataArray encodedLength="{len(encoded)}"{declared}>'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float"/>'
        '<cvParam cvRef="MS" accession="MS:1000576" name="no compression"/>'
        f'<cvParam cvRef="MS" accession="{accession}" name="{name}"/>'
        f"<binary>{encoded}</binary></binaryDataArray>"
    )


def _write(tmp_path: Path, arrays: list[str], points: int | None = 2) -> Path:
    """One spectrum holding ``arrays``. ``points`` is its defaultArrayLength, omitted when None."""
    path = tmp_path / "im.mzML"
    declared = "" if points is None else f' defaultArrayLength="{points}"'
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML><run id="run1">'
        '<spectrumList count="1">'
        f'<spectrum index="0" id="scan=1"{declared}>'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        f'<binaryDataArrayList count="{len(arrays)}">{"".join(arrays)}</binaryDataArrayList>'
        "</spectrum></spectrumList></run></mzML></indexedmzML>"
    )
    return path


MZ = _array("MS:1000514", "m/z array", [100.0, 200.0])
IM_MEAN = _array("MS:1003006", "mean inverse reduced ion mobility array", [0.9, 0.8])
IM_RAW = _array("MS:1002816", "mean ion mobility array", [1.5, 1.6])
# Not per-point for a two-point spectrum: mzML lets a binaryDataArray carry its own arrayLength.
IM_MEAN_LONG = _array("MS:1003006", "mean inverse reduced ion mobility array", [0.9, 0.8, 0.7])
IM_RAW_LONG = _array("MS:1002816", "mean ion mobility array", [1.5, 1.6, 1.7])


def test_combined_im_array_matches_mz() -> None:
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


def test_scan_level_only_spectrum_returns_none() -> None:
    with Mzml(str(DATA / "bruker_ms2_im.mzML")) as reader:
        spec = reader.spectra[0]
        assert spec.has_im is True
        assert spec.im_types == set()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert spec.ion_mobility_array is None


def test_spectrum_without_im_returns_none() -> None:
    with Mzml(str(DATA / "example.mzML")) as reader:
        spec = reader.spectra[0]
        assert spec.has_im is False
        assert spec.ion_mobility_array is None


def test_single_array_does_not_warn(tmp_path: Path) -> None:
    with Mzml(str(_write(tmp_path, [MZ, IM_MEAN]))) as reader:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            im = reader.spectra[0].ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8])


def test_multiple_per_point_arrays_warn_and_return_the_first(tmp_path: Path) -> None:
    """Both hold one value per point, so document order decides and the warning names the winner."""
    with Mzml(str(_write(tmp_path, [MZ, IM_MEAN, IM_RAW]))) as reader:
        spec = reader.spectra[0]
        with pytest.warns(UserWarning, match=r"2 ion mobility arrays holding one value per point \(2\).*MS:1003006"):
            im = spec.ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8])  # first in document order


def test_an_array_of_another_length_is_not_per_point(tmp_path: Path) -> None:
    """A lone ion mobility array that is not one value per point is reported, not handed back.

    Returning it would let `im[i]` and `mz[i]` describe different points.
    """
    path = _write(tmp_path, [MZ, IM_MEAN_LONG])
    with Mzml(str(path)) as reader:
        spec = reader.spectra[0]
        assert spec.has_im is True  # the array is still there, and im_types still names it
        assert spec.im_types == {BinaryDataArrayAccession.MEAN_INVERSE_REDUCED_ION_MOBILITY}
        with pytest.warns(UserWarning, match=r"length \[3\].*2 points, so none of them is per-point"):
            assert spec.ion_mobility_array is None
        raw = spec.get_binary_array(BinaryDataArrayAccession.MEAN_INVERSE_REDUCED_ION_MOBILITY)
        assert raw is not None
        np.testing.assert_array_equal(raw.data, [0.9, 0.8, 0.7])  # reachable, just not as the per-point array


def test_an_array_of_another_length_beside_a_per_point_one_is_not_an_ambiguity(tmp_path: Path) -> None:
    """The per-point array wins over an earlier array of another length, and nothing warns.

    Document order alone would return the 3-value array for a 2-point spectrum. Only one of the two
    holds one value per point, so the length makes the choice and there is nothing to warn about.
    """
    with Mzml(str(_write(tmp_path, [MZ, IM_RAW_LONG, IM_MEAN]))) as reader:
        spec = reader.spectra[0]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            im = spec.ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8])


def test_the_mz_length_is_tried_when_default_array_length_names_no_array(tmp_path: Path) -> None:
    """``defaultArrayLength`` is only the default: a ``binaryDataArray`` may declare its own ``arrayLength``.

    ``validate(decode_binary=True)`` calls this file valid, because it checks such an array against its own
    ``arrayLength``, so the property must not drop an ion mobility array that pairs with ``mz`` one value
    per point just because the element's declared default disagrees.
    """
    mz = _array("MS:1000514", "m/z array", [100.0, 200.0, 300.0], array_length=3)
    im_long = _array("MS:1003006", "mean inverse reduced ion mobility array", [0.9, 0.8, 0.7], array_length=3)
    path = _write(tmp_path, [mz, im_long], points=2)
    assert validate(str(path), decode_binary=True).valid
    with Mzml(str(path)) as reader:
        spec = reader.spectra[0]
        assert spec.default_array_length == 2
        assert spec.mz is not None and len(spec.mz) == 3
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            im = spec.ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8, 0.7])


def test_the_point_count_falls_back_to_the_mz_length(tmp_path: Path) -> None:
    """With no defaultArrayLength attribute, the m/z array's length is the point count."""
    with Mzml(str(_write(tmp_path, [MZ, IM_MEAN_LONG], points=None))) as reader:
        spec = reader.spectra[0]
        assert spec.default_array_length is None
        assert spec.mz is not None and len(spec.mz) == 2
        with pytest.warns(UserWarning, match="none of them is per-point"):
            assert spec.ion_mobility_array is None


def test_without_a_point_count_the_file_is_taken_at_its_word(tmp_path: Path) -> None:
    """No defaultArrayLength and no m/z array: nothing to check against, so the first is returned."""
    with Mzml(str(_write(tmp_path, [IM_MEAN_LONG], points=None))) as reader:
        spec = reader.spectra[0]
        assert spec.default_array_length is None
        assert spec.mz is None
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            im = spec.ion_mobility_array
    assert im is not None
    np.testing.assert_array_equal(im, [0.9, 0.8, 0.7])
