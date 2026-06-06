"""Codec registry keyed by compression CV accession tail integer."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from ..cv import (
    COMP_NUMLIN_ZLIB,
    COMP_NUMPIC_ZLIB,
    COMP_NUMSLOF_ZLIB,
    COMP_ZLIB,
)
from .numpress import (
    decode_numlin_zlib,
    decode_numpic_zlib,
    decode_numslof_zlib,
    encode_numlin_zlib,
    encode_numpic_zlib,
    encode_numslof_zlib,
)
from .raw import decode_zlib_raw, encode_zlib_raw


class Codec(Protocol):
    def encode(self, data: np.ndarray, fp: float | None) -> bytes: ...
    def decode(self, blob: bytes) -> np.ndarray: ...


class _NumLinZlibCodec:
    def encode(self, data: np.ndarray, fp: float | None) -> bytes:
        return encode_numlin_zlib(data, fp)

    def decode(self, blob: bytes) -> np.ndarray:
        return decode_numlin_zlib(blob)


class _NumSlofZlibCodec:
    def encode(self, data: np.ndarray, fp: float | None) -> bytes:
        return encode_numslof_zlib(data, fp)

    def decode(self, blob: bytes) -> np.ndarray:
        return decode_numslof_zlib(blob)


class _NumPicZlibCodec:
    def encode(self, data: np.ndarray, fp: float | None) -> bytes:
        return encode_numpic_zlib(data, fp)

    def decode(self, blob: bytes) -> np.ndarray:
        return decode_numpic_zlib(blob)


class _ZlibRawCodec:
    def encode(self, data: np.ndarray, fp: float | None) -> bytes:
        return encode_zlib_raw(data)

    def decode(self, blob: bytes) -> np.ndarray:
        return decode_zlib_raw(blob)


_REGISTRY: dict[int, Codec] = {
    COMP_NUMLIN_ZLIB: _NumLinZlibCodec(),
    COMP_NUMSLOF_ZLIB: _NumSlofZlibCodec(),
    COMP_NUMPIC_ZLIB: _NumPicZlibCodec(),
    COMP_ZLIB: _ZlibRawCodec(),
}


def get_codec(comp_tail: int) -> Codec:
    """Return the codec for a given compression accession tail.

    Raises KeyError if the tail is not registered.
    """
    if comp_tail not in _REGISTRY:
        raise KeyError(f"No codec registered for compression tail {comp_tail}.")
    return _REGISTRY[comp_tail]
