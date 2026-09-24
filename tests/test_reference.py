"""mzmlpy against independent readers and writers, using values frozen by tests/reference/generate_reference.py.

* ``pyteomics_reference.json``: what pyteomics.mzml reads from each bundled file it can decode.
* ``psims_written.mzML`` + ``psims_reference.json``: a file written by psims from known arrays.
* zstd, byte-shuffled zstd and dictionary zstd files (which pyteomics cannot decode) must match the
  zlib file they were re-encoded from, spectrum by spectrum.

Known, intended difference: pyteomics casts MS-Numpress output to the declared array type
(32-bit float here); mzmlpy returns the reconstructed float64 values unchanged. Casting mzmlpy's
values to the declared type reproduces pyteomics exactly.
"""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from mzmlpy import Mzml

REF = Path(__file__).parent / "reference"
DATA = Path(__file__).parent / "data"
PYTEOMICS = json.loads((REF / "pyteomics_reference.json").read_text())
PSIMS = json.loads((REF / "psims_reference.json").read_text())


def _digest(values: np.ndarray | None, ref: dict, numpress: bool) -> None:
    assert values is not None
    assert values.size == ref["length"]
    if numpress:
        values = values.astype(ref["dtype"])
    else:
        assert values.dtype.str == ref["dtype"]
    assert hashlib.sha256(values.astype("<f8").tobytes()).hexdigest() == ref["sha256"]


def _needs(name: str) -> None:
    if "numpress" in name:
        pytest.importorskip("pynumpress")


@pytest.mark.filterwarnings("ignore:This spectrum has multiple scans")
@pytest.mark.parametrize("name", sorted(PYTEOMICS))
def test_spectra_match_pyteomics(name):
    _needs(name)
    expected = PYTEOMICS[name]["spectra"]
    numpress = "numpress" in name
    with Mzml(DATA / name) as reader:
        spectra = list(reader.spectra)
        assert len(spectra) == len(expected)
        for spec, ref in zip(spectra, expected, strict=True):
            assert spec.id == ref["id"]
            assert spec.index == ref["index"]
            assert spec.ms_level == ref["ms_level"]
            _digest(spec.mz, ref["m/z array"], numpress)
            _digest(spec.intensity, ref["intensity array"], numpress)
            rt = ref.get("scan_start_time_s")
            assert spec.scan_start_time == (None if rt is None else timedelta(seconds=rt))
            assert spec.spectrum_type == ("centroid" if ref["centroid"] else "profile" if ref["profile"] else None)
            for cv_name, value in ref["cv"].items():
                assert spec.cv_float(cv_name) == value, cv_name
            assert len(spec.precursors) == len(ref["precursors"])
            for prec, pref in zip(spec.precursors, ref["precursors"], strict=True):
                assert prec.spectrum_ref == pref["spectrum_ref"]
                iw = prec.isolation_window
                got_iw = [None, None, None] if iw is None else [iw.target_mz, iw.lower_offset, iw.upper_offset]
                assert got_iw == pref["isolation_window"]
                assert (prec.activation.ce if prec.activation else None) == pref["collision_energy"]
                got_ions = [
                    {"mz": si.selected_ion_mz, "charge": si.charge_state, "intensity": si.peak_intensity}
                    for si in prec.selected_ions
                ]
                assert got_ions == pref["selected_ions"]


@pytest.mark.parametrize("name", sorted(PYTEOMICS))
def test_chromatograms_match_pyteomics(name):
    _needs(name)
    expected = PYTEOMICS[name]["chromatograms"]
    numpress = "numpress" in name
    with Mzml(DATA / name) as reader:
        chroms = list(reader.chromatograms)
        assert [c.id for c in chroms] == [c["id"] for c in expected]
        for chrom, ref in zip(chroms, expected, strict=True):
            _digest(chrom.time, ref["time array"], numpress)
            _digest(chrom.intensity, ref["intensity array"], numpress)


@pytest.mark.parametrize(
    "name",
    [
        "zstd_20250806_ArgC_DDA_HCD-FT_01.mzML",
        "mzshufflezstd_20250806_ArgC_DDA_HCD-FT_01.mzML",
        "dictzstd_20250806_ArgC_DDA_HCD-FT_01.mzML",
    ],
)
def test_zstd_family_matches_zlib_source(name):
    pytest.importorskip("zstd")
    with Mzml(DATA / "zlib_20250806_ArgC_DDA_HCD-FT_01.mzML") as zlib_reader, Mzml(DATA / name) as reader:
        pairs = list(zip(zlib_reader.spectra, reader.spectra, strict=True))
        assert len(pairs) == 10
        for ref, spec in pairs:
            assert spec.id == ref.id
            np.testing.assert_array_equal(spec.mz, ref.mz)
            np.testing.assert_array_equal(spec.intensity, ref.intensity)
        for ref, chrom in zip(zlib_reader.chromatograms, reader.chromatograms, strict=True):
            np.testing.assert_array_equal(chrom.time, ref.time)
            np.testing.assert_array_equal(chrom.intensity, ref.intensity)


def test_psims_written_file():
    pytest.importorskip("pynumpress")
    with Mzml(REF / "psims_written.mzML") as reader:
        spectra = list(reader.spectra)
        assert [s.id for s in spectra] == [s["id"] for s in PSIMS]
        for spec, ref in zip(spectra, PSIMS, strict=True):
            assert spec.ms_level == ref["ms_level"]
            assert spec.scan_start_time == timedelta(minutes=ref["rt_min"])
            numpress = ref["compression"].startswith("MS-Numpress")
            for values, key, dtype in (
                (spec.mz, "mz", ref["mz_dtype"]),
                (spec.intensity, "intensity", ref["int_dtype"]),
            ):
                assert values is not None
                expected = np.array(ref[key], dtype=dtype)
                if numpress:
                    # Lossy fixed-point encoding: psims chose the optimal fixed point for these values.
                    np.testing.assert_allclose(values, expected, rtol=0, atol=1e-6)
                else:
                    assert values.dtype == expected.dtype
                    np.testing.assert_array_equal(values, expected)
            if "precursor" in ref:
                pref = ref["precursor"]
                (prec,) = spec.precursors
                (ion,) = prec.selected_ions
                assert (ion.selected_ion_mz, ion.charge_state, ion.peak_intensity) == (
                    pref["mz"],
                    pref["charge"],
                    pref["intensity"],
                )
                assert prec.spectrum_ref == pref["scan_id"]
                assert prec.activation is not None and prec.activation.ce == pref["activation"][1]["collision energy"]
                lower, target, upper = pref["isolation_window"]
                iw = prec.isolation_window
                assert iw is not None and (iw.target_mz, iw.lower_offset, iw.upper_offset) == (target, lower, upper)
            else:
                assert spec.precursors == []
