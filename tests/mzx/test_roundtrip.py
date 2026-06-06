"""Round-trip tests: encode → decode preserves peaks and metadata."""

import numpy as np
import pytest

from mzx import decode_token, encode_spectrum
from mzx.model import InlineSpectrum, MzxCvParam


def _assert_arrays_close(a, b, rtol=1e-4, atol=1e-4):
    assert a is not None and b is not None
    np.testing.assert_allclose(a, b, rtol=rtol, atol=atol)


def _assert_arrays_exact(a, b):
    assert a is not None and b is not None
    np.testing.assert_array_equal(a, b)


# ─── Acceptance criterion 1: Round-trip (lossy) ─────────────────────────────

def test_roundtrip_lossy_mz_intensity(simple_spectrum):
    token = encode_spectrum(simple_spectrum)
    decoded = decode_token(token)
    _assert_arrays_close(decoded.mz, simple_spectrum.mz, rtol=1e-4)
    _assert_arrays_close(decoded.intensity, simple_spectrum.intensity, rtol=1e-2)


def test_roundtrip_ms2_metadata(ms2_spectrum):
    token = encode_spectrum(ms2_spectrum)
    decoded = decode_token(token)

    assert decoded.id == ms2_spectrum.id
    assert decoded.default_array_length == ms2_spectrum.default_array_length
    assert decoded.interp == ms2_spectrum.interp

    # Spectrum-level params present
    accessions = {p.accession for p in decoded.params}
    assert "MS:1000511" in accessions  # ms level
    assert "MS:1000130" in accessions  # positive scan flag
    assert "MS:1000127" in accessions  # centroid flag

    # Precursor round-trip
    assert len(decoded.precursors) == 1
    pre = decoded.precursors[0]
    assert pre.isolation_window is not None
    assert pre.activation is not None
    act_accessions = {p.accession for p in pre.activation.params}
    assert "MS:1000422" in act_accessions  # HCD flag
    assert any(p.accession == "MS:1000045" for p in pre.activation.params)  # CE

    # Scan round-trip
    assert len(decoded.scans) == 1
    scan = decoded.scans[0]
    assert any(p.accession == "MS:1000016" for p in scan.params)  # scan start time
    assert len(scan.windows) == 1


# ─── Acceptance criterion 2: Round-trip (lossless) ──────────────────────────

def test_roundtrip_lossless_mz(simple_spectrum):
    token = encode_spectrum(simple_spectrum, lossless=True)
    decoded = decode_token(token)
    _assert_arrays_exact(decoded.mz, simple_spectrum.mz)
    _assert_arrays_exact(decoded.intensity, simple_spectrum.intensity)


def test_roundtrip_lossless_large():
    rng = np.random.default_rng(7)
    n = 200
    mz = np.sort(rng.uniform(100.0, 2000.0, n))
    intensity = rng.uniform(1e3, 1e8, n)
    spec = InlineSpectrum(default_array_length=n, mz=mz, intensity=intensity)
    token = encode_spectrum(spec, lossless=True)
    decoded = decode_token(token)
    _assert_arrays_exact(decoded.mz, mz)
    _assert_arrays_exact(decoded.intensity, intensity)


# ─── Acceptance criterion 5: Flag semantics ──────────────────────────────────

def test_flag_params_roundtrip():
    """Polarity, centroid/profile, activation flags survive as null values."""
    spec = InlineSpectrum(
        default_array_length=0,
        params=[
            MzxCvParam(accession="MS:1000130"),  # positive (flag)
            MzxCvParam(accession="MS:1000127"),  # centroid (flag)
        ],
    )
    token = encode_spectrum(spec)
    decoded = decode_token(token)
    flag_accessions = {p.accession for p in decoded.params if p.value is None}
    assert "MS:1000130" in flag_accessions
    assert "MS:1000127" in flag_accessions


# ─── Acceptance criterion 6: Oversize policy ────────────────────────────────

def test_oversize_raises():
    rng = np.random.default_rng(1)
    n = 5000
    mz = np.sort(rng.uniform(100.0, 2000.0, n))
    intensity = rng.uniform(1e3, 1e8, n)
    spec = InlineSpectrum(default_array_length=n, mz=mz, intensity=intensity)
    with pytest.raises(OverflowError, match="max_len"):
        encode_spectrum(spec, max_len=100)


def test_top_n_reduces_spectrum():
    from mzx import top_n
    rng = np.random.default_rng(2)
    n = 100
    mz = np.sort(rng.uniform(100.0, 1000.0, n))
    intensity = rng.uniform(1e3, 1e8, n)
    spec = InlineSpectrum(default_array_length=n, mz=mz, intensity=intensity)
    trimmed = top_n(spec, 10)
    assert trimmed.default_array_length == 10
    assert len(trimmed.mz) == 10
    assert len(trimmed.intensity) == 10
    # top 10 by intensity
    expected_top = np.sort(intensity)[-10:]
    np.testing.assert_array_equal(np.sort(trimmed.intensity), expected_top)


# ─── Acceptance criterion 8: Segment integrity ───────────────────────────────

def test_with_charge_array():
    rng = np.random.default_rng(3)
    n = 10
    mz = np.sort(rng.uniform(100.0, 1000.0, n))
    intensity = rng.uniform(1e3, 1e6, n)
    charge = np.ones(n, dtype=np.float64) * 2
    spec = InlineSpectrum(default_array_length=n, mz=mz, intensity=intensity, charge=charge)
    token = encode_spectrum(spec)
    decoded = decode_token(token)
    assert decoded.charge is not None
    np.testing.assert_allclose(decoded.charge, charge, atol=1.0)


def test_token_starts_with_magic(simple_spectrum):
    token = encode_spectrum(simple_spectrum)
    assert token.startswith("mzx1.")
