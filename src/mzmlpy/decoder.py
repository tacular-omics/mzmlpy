#!/usr/bin/env python3
"""MS-Numpress decoder for compressed m/z and intensity values."""

import importlib
import zlib

import numpy as np
from numpy.typing import NDArray


def _require(module: str, extra: str):
    """Import an optional decoding dependency, raising an actionable error if it is missing."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(
            f"Decoding this array requires the optional '{module}' package, which is not installed. "
            f"Install it with:  pip install mzmlpy[{extra}]"
        ) from exc


def fix_input(data: NDArray[np.uint8] | bytes) -> NDArray[np.uint8]:
    if isinstance(data, bytes):
        return np.frombuffer(data, dtype=np.uint8)
    return data


class MSDecoder:
    """Lazy-loading decoder for MS-Numpress compressed data via pynumpress."""

    @classmethod
    def decode_linear(cls, data: NDArray[np.uint8] | bytes) -> NDArray[np.float64]:
        """Decode MS-Numpress linear prediction compressed data."""
        pynumpress = _require("pynumpress", "numpress")

        result = pynumpress.decode_linear(fix_input(data))
        return np.asarray(result, dtype=np.float64)

    @classmethod
    def decode_pic(cls, data: NDArray[np.uint8] | bytes) -> NDArray[np.float64]:
        """Decode MS-Numpress positive integer compressed data."""
        pynumpress = _require("pynumpress", "numpress")

        result = pynumpress.decode_pic(fix_input(data))
        return np.asarray(result, dtype=np.float64)

    @classmethod
    def decode_slof(cls, data: NDArray[np.uint8] | bytes) -> NDArray[np.float64]:
        """Decode MS-Numpress short logged float compressed data."""
        pynumpress = _require("pynumpress", "numpress")

        result = pynumpress.decode_slof(fix_input(data))
        return np.asarray(result, dtype=np.float64)

    @classmethod
    def encode_linear(cls, data: NDArray[np.float64] | list[float]) -> bytearray:
        """Encode data using MS-Numpress linear prediction compression."""
        pynumpress = _require("pynumpress", "numpress")

        if isinstance(data, list):
            data = np.array(data, dtype=np.float64)
        return pynumpress.encode_linear(data, pynumpress.optimal_linear_fixed_point(data))

    @classmethod
    def encode_pic(cls, data: NDArray[np.float64] | list[float]) -> bytearray:
        """Encode data using MS-Numpress positive integer compression."""
        pynumpress = _require("pynumpress", "numpress")

        if isinstance(data, list):
            data = np.array(data, dtype=np.float64)
        return pynumpress.encode_pic(data)

    @classmethod
    def encode_slof(cls, data: NDArray[np.float64] | list[float]) -> bytearray:
        """Encode data using MS-Numpress short logged float compression."""
        pynumpress = _require("pynumpress", "numpress")

        if isinstance(data, list):
            data = np.array(data, dtype=np.float64)
        return pynumpress.encode_slof(data, pynumpress.optimal_slof_fixed_point(data))

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
        zstd = _require("zstd", "zstd")

        return zstd.decompress(data)

    @classmethod
    def encode_ztsd(cls, data: bytes) -> bytes:
        """Compress data using ztsd."""
        zstd = _require("zstd", "zstd")

        return zstd.compress(data)

    @staticmethod
    def unshuffle(data: bytes, element_size: int) -> bytes:
        """Reverse a byte-shuffle transform.

        Byte shuffling groups bytes by their position within each element
        (all byte-0s, then all byte-1s, etc.) to improve compression of
        numeric arrays. This reverses that transform.
        """
        if element_size <= 0:
            raise ValueError(f"element_size must be positive, got {element_size}")
        if len(data) % element_size != 0:
            # Otherwise numpy silently broadcasts mismatched slices into scrambled output.
            raise ValueError(f"byte-shuffled data length {len(data)} is not a multiple of element size {element_size}")
        n_elements = len(data) // element_size
        src = np.frombuffer(data, dtype=np.uint8)
        dst = np.empty_like(src)
        for i in range(element_size):
            dst[i::element_size] = src[i * n_elements : (i + 1) * n_elements]
        return dst.tobytes()

    @classmethod
    def decode_byte_shuffled_zstd(cls, data: bytes, element_size: int) -> bytes:
        """Decompress byte-shuffled zstd data (MS:1003781)."""
        return cls.unshuffle(cls.decode_ztsd(data), element_size)

    @staticmethod
    def reverse_delta_prediction(values: NDArray) -> NDArray:
        """Reverse the delta-prediction transform (used by MS:1003089).

        The encoder stores ``values[0]`` and ``values[1]`` verbatim and, for ``i >= 2``,
        ``x[0] + x[i] - x[i-1]`` (a first difference offset by the base value). Walking that back:
        ``out[i] = values[i] + out[i-1] - out[0]``.

        The recurrence runs in the array's *native* float precision and the operation order is
        kept identical to the reference implementations so results are bit-reproducible against
        other tools (ProteoWizard mzMLb ``IO.cpp``; psims ``mzml.binary_encoding.delta_predict``).
        """
        out = values.copy()
        for i in range(2, len(out)):
            out[i] = out[i] + out[i - 1] - out[0]
        return out

    @staticmethod
    def reverse_linear_prediction(values: NDArray) -> NDArray:
        """Reverse the linear- (second-order) prediction transform (used by MS:1003090).

        The encoder stores ``values[0]`` and ``values[1]`` verbatim and, for ``i >= 2``,
        ``x[1] + x[i] - 2*x[i-1] + x[i-2]`` (a linear extrapolation residual offset by ``x[1]``).
        Walking that back: ``out[i] = values[i] + 2*out[i-1] - out[i-2] - out[1]``.

        As with :meth:`reverse_delta_prediction`, the recurrence runs in native precision with the
        reference operation order (ProteoWizard mzMLb ``IO.cpp``; psims ``linear_predict``).
        """
        out = values.copy()
        for i in range(2, len(out)):
            out[i] = out[i] + 2 * out[i - 1] - out[i - 2] - out[1]
        return out

    @classmethod
    def decode_dict_encoded_zstd(cls, data: bytes, dtype: np.dtype) -> np.ndarray:
        """Decode dictionary-encoded zstd data (MS:1003782).

        The decompressed layout is:
        [16-byte header] [byte-shuffled value table] [byte-shuffled index table]

        The header contains two uint64 values: ``header[0]`` is the absolute byte offset
        (from the start of the decompressed buffer) at which the index table begins — i.e. the
        end of the value table — and ``header[1]`` is the number of output elements. The value
        table holds the *unique* values, of which there can be fewer than the output count
        (that is the whole point of dictionary encoding), so its size must come from the header
        offset, not from the output count.
        """
        decompressed = cls.decode_ztsd(data)
        header = np.frombuffer(decompressed[:16], dtype=np.uint64)
        index_offset = int(header[0])
        num_elements = int(header[1])
        if num_elements == 0:
            # Empty array: nothing to index (avoids a divide-by-zero on the index-size calc below).
            return np.array([], dtype=dtype)
        element_size = dtype.itemsize

        # Value table: unique values, from the end of the 16-byte header up to the index offset.
        value_data = cls.unshuffle(decompressed[16:index_offset], element_size)
        values = np.frombuffer(value_data, dtype=dtype)

        # Index table: remaining bytes, byte-shuffled by index element size.
        idx_data = decompressed[index_offset:]
        idx_size = len(idx_data) // num_elements
        if idx_size == 1:
            indices = np.frombuffer(idx_data, dtype=np.uint8)
        else:
            indices = np.frombuffer(cls.unshuffle(idx_data, idx_size), dtype=np.dtype(f"<u{idx_size}"))

        return values[indices]
