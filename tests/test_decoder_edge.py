"""Decoder edge cases surfaced by adversarial probing."""

import struct

import numpy as np
import pytest

from mzmlpy.decoder import MSDecoder

zstd = pytest.importorskip("zstd")


def test_unshuffle_rejects_non_multiple_length():
    """A byte-shuffled buffer whose length isn't a multiple of the element size must raise,
    not silently produce scrambled output via numpy broadcasting."""
    with pytest.raises(ValueError, match="not a multiple"):
        MSDecoder.unshuffle(b"\x00" * 12, 8)


def test_unshuffle_roundtrip():
    values = list(range(16))
    raw = bytes(values)
    element_size = 4
    # shuffle: group by byte position
    n = len(raw) // element_size
    shuffled = bytes(raw[j * element_size + i] for i in range(element_size) for j in range(n))
    assert MSDecoder.unshuffle(shuffled, element_size) == raw


def test_dict_encoded_zstd_empty_array():
    """An empty dict-encoded array (num_elements == 0) must return an empty array, not divide by zero."""
    header = struct.pack("<QQ", 0, 0)  # byte offset, element count
    payload = zstd.compress(header)
    out = MSDecoder.decode_dict_encoded_zstd(payload, np.dtype("<f8"))
    assert isinstance(out, np.ndarray)
    assert len(out) == 0
