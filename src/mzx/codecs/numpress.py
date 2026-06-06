"""MS-Numpress + zlib codec wrappers over pynumpress."""

import zlib

import numpy as np
import pynumpress

DEFAULT_NUMLIN_FP = 100000.0  # ~0.1 mDa precision for m/z
# SLOF fp must satisfy: log(max_intensity + 1) * fp <= 65535 (uint16 max)
# Use 3600.0 which handles intensities up to ~8e7; clip to safe value if data is larger.
_SLOF_UINT16_MAX = 65535.0


def _safe_slof_fp(data: np.ndarray, desired_fp: float) -> float:
    """Return a slof fp that won't overflow uint16 given the array's max value."""
    max_val = float(np.max(data)) if len(data) > 0 else 1.0
    max_val = max(max_val, 1.0)
    import math
    max_fp = _SLOF_UINT16_MAX / (math.log(max_val + 1) + 1e-9)
    return min(desired_fp, max_fp)


DEFAULT_NUMSLOF_FP = 3600.0  # handles intensities up to ~8e7; adjusted dynamically if needed


def encode_numlin_zlib(data: np.ndarray, fp: float | None = None) -> bytes:
    """Encode array with MS-Numpress linear prediction then zlib."""
    fp = fp if fp is not None else DEFAULT_NUMLIN_FP
    encoded = pynumpress.encode_linear(data.astype(np.float64), fp)
    return zlib.compress(encoded.tobytes())


def decode_numlin_zlib(blob: bytes) -> np.ndarray:
    """Decode MS-Numpress linear + zlib blob back to float64 array."""
    decompressed = zlib.decompress(blob)
    return np.array(pynumpress.decode_linear(np.frombuffer(decompressed, dtype=np.uint8)), dtype=np.float64)


def encode_numslof_zlib(data: np.ndarray, fp: float | None = None) -> bytes:
    """Encode array with MS-Numpress short logged float then zlib."""
    desired = fp if fp is not None else DEFAULT_NUMSLOF_FP
    safe_fp = _safe_slof_fp(data, desired)
    encoded = pynumpress.encode_slof(data.astype(np.float64), safe_fp)
    return zlib.compress(encoded.tobytes())


def decode_numslof_zlib(blob: bytes) -> np.ndarray:
    """Decode MS-Numpress slof + zlib blob back to float64 array."""
    decompressed = zlib.decompress(blob)
    return np.array(pynumpress.decode_slof(np.frombuffer(decompressed, dtype=np.uint8)), dtype=np.float64)


def encode_numpic_zlib(data: np.ndarray, fp: float | None = None) -> bytes:
    """Encode array with MS-Numpress positive integer then zlib."""
    encoded = pynumpress.encode_pic(data.astype(np.float64))
    return zlib.compress(encoded.tobytes())


def decode_numpic_zlib(blob: bytes) -> np.ndarray:
    """Decode MS-Numpress pic + zlib blob back to float64 array."""
    decompressed = zlib.decompress(blob)
    return np.array(pynumpress.decode_pic(np.frombuffer(decompressed, dtype=np.uint8)), dtype=np.float64)
