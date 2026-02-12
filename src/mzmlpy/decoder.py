#!/usr/bin/env python3
"""MS-Numpress decoder for compressed m/z and intensity values."""

import zlib

import numpy as np
from numpy.typing import NDArray


def fix_input(data: NDArray[np.uint8] | bytes) -> NDArray[np.uint8]:
    if isinstance(data, bytes):
        return np.frombuffer(data, dtype=np.uint8)
    return data


class MSDecoder:
    """Lazy-loading decoder for MS-Numpress compressed data via pynumpress."""

    @classmethod
    def decode_linear(cls, data: NDArray[np.uint8] | bytes) -> NDArray[np.float64]:
        """Decode MS-Numpress linear prediction compressed data."""
        import pynumpress

        result = pynumpress.decodeLinear(fix_input(data))
        return np.asarray(result, dtype=np.float64)

    @classmethod
    def decode_pic(cls, data: NDArray[np.uint8] | bytes) -> NDArray[np.float64]:
        """Decode MS-Numpress positive integer compressed data."""
        import pynumpress

        result = pynumpress.decodePic(fix_input(data))
        return np.asarray(result, dtype=np.float64)

    @classmethod
    def decode_slof(cls, data: NDArray[np.uint8] | bytes) -> NDArray[np.float64]:
        """Decode MS-Numpress short logged float compressed data."""
        import pynumpress

        result = pynumpress.decodeSlof(fix_input(data))
        return np.asarray(result, dtype=np.float64)

    @classmethod
    def encode_linear(cls, data: NDArray[np.float64] | list[float]) -> bytearray:
        """Encode data using MS-Numpress linear prediction compression."""
        import pynumpress

        if isinstance(data, list):
            data = np.array(data, dtype=np.float64)
        return pynumpress.encodeLinear(data)

    @classmethod
    def encode_pic(cls, data: NDArray[np.float64] | list[float]) -> bytearray:
        """Encode data using MS-Numpress positive integer compression."""
        import pynumpress

        if isinstance(data, list):
            data = np.array(data, dtype=np.float64)
        return pynumpress.encodePic(data)

    @classmethod
    def encode_slof(cls, data: NDArray[np.float64] | list[float]) -> bytearray:
        """Encode data using MS-Numpress short logged float compression."""
        import pynumpress

        if isinstance(data, list):
            data = np.array(data, dtype=np.float64)
        return pynumpress.encodeSlof(data)

    @classmethod
    def decode_zlib(cls, data: bytes) -> bytes:
        """Decompress zlib-compressed data."""
        return zlib.decompress(data)

    @classmethod
    def encode_zlib(cls, data: bytes) -> bytes:
        """Compress data using zlib."""
        return zlib.compress(data)

    @classmethod
    def decode_ztsd(cls, data: bytes) -> bytes:
        """Decompress ztsd-compressed data."""
        import zstd

        return zstd.decompress(data)

    @classmethod
    def encode_ztsd(cls, data: bytes) -> bytes:
        """Compress data using ztsd."""
        import zstd

        return zstd.compress(data)
