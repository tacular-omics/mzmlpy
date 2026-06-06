"""Lossless IEEE-754 little-endian + zlib codec."""

import zlib

import numpy as np


def encode_zlib_raw(data: np.ndarray) -> bytes:
    """Encode array as little-endian float64 + zlib."""
    raw = data.astype("<f8").tobytes()
    return zlib.compress(raw)


def decode_zlib_raw(blob: bytes) -> np.ndarray:
    """Decode zlib-compressed little-endian float64 bytes back to array."""
    raw = zlib.decompress(blob)
    return np.frombuffer(raw, dtype="<f8").astype(np.float64)
