"""Acceptance criterion 3: Determinism and hash verification."""

import numpy as np
import pytest

from mzx import decode_token, encode_spectrum
from mzx.model import InlineSpectrum


def _make_spec(seed=42, n=20):
    rng = np.random.default_rng(seed)
    mz = np.sort(rng.uniform(100.0, 1000.0, n))
    intensity = rng.uniform(1e3, 1e6, n)
    return InlineSpectrum(default_array_length=n, mz=mz, intensity=intensity, id="scan=1")


def test_deterministic_token():
    """Same input produces byte-identical token across calls."""
    spec = _make_spec()
    t1 = encode_spectrum(spec)
    t2 = encode_spectrum(spec)
    assert t1 == t2


def test_deterministic_unordered_input():
    """Input with peaks out of order produces same token as pre-sorted input."""
    spec = _make_spec(n=10)
    # Shuffle
    idx = np.array([5, 3, 9, 0, 7, 1, 8, 2, 6, 4])
    shuffled = InlineSpectrum(
        default_array_length=10,
        mz=spec.mz[idx],
        intensity=spec.intensity[idx],
        id=spec.id,
    )
    t_sorted = encode_spectrum(spec)
    t_shuffled = encode_spectrum(shuffled)
    assert t_sorted == t_shuffled


def test_hash_stored_in_token():
    token = encode_spectrum(_make_spec())
    decoded = decode_token(token)
    assert decoded.hash is not None
    assert len(decoded.hash) == 16  # 12 bytes → 16 base64url chars


def test_hash_verified_on_decode():
    """Tampered hash causes ValueError on decode."""
    import base64
    token = encode_spectrum(_make_spec())
    parts = token.split(".")
    # Tamper: flip last char of the header segment
    hdr = parts[1]
    tampered_hdr = hdr[:-1] + ("A" if hdr[-1] != "A" else "B")
    # We need to actually tamper the stored hash inside the msgpack, not the header encoding
    # Easier: modify an array byte so hash won't match
    arr0 = parts[2]
    # Flip one character in the first array segment
    arr0_bytes = bytearray(base64.urlsafe_b64decode(arr0 + "=="))
    arr0_bytes[-1] ^= 0xFF
    import base64 as b64
    new_arr0 = b64.urlsafe_b64encode(bytes(arr0_bytes)).rstrip(b"=").decode()
    tampered = ".".join(parts[:2] + [new_arr0] + parts[3:])
    with pytest.raises(ValueError, match="hash mismatch"):
        decode_token(tampered)


def test_hash_matches_re_encode():
    """Decoded hash equals hash from a fresh encode of same data."""
    spec = _make_spec()
    t1 = encode_spectrum(spec)
    decoded = decode_token(t1)
    t2 = encode_spectrum(spec)
    decoded2 = decode_token(t2)
    assert decoded.hash == decoded2.hash
