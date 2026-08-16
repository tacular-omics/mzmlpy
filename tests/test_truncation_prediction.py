"""Tests for the truncation + delta/linear prediction compression codecs (MS:1003089 / MS:1003090).

The decode algorithm is verified against two independent reference implementations that agree
exactly: ProteoWizard's mzMLb writer (`pwiz/data/msdata/IO.cpp`) and psims' `mzml.binary_encoding`
(`delta_predict` / `linear_predict`). These tests encode with the reference forward transform and
assert a clean round-trip through the real decode path, plus the byte-level worked example both
references produce.
"""

import base64
import zlib
from xml.etree import ElementTree

import numpy as np
import pytest

from mzmlpy.decoder import MSDecoder
from mzmlpy.spectra import BinaryDataArray

FLOAT_32 = "MS:1000521"
FLOAT_64 = "MS:1000523"
TRUNCATION_DELTA_ZLIB = "MS:1003089"
TRUNCATION_LINEAR_ZLIB = "MS:1003090"
MZ_ARRAY = "MS:1000514"


# --- Reference forward transforms (ported verbatim from psims.mzml.binary_encoding) ---


def delta_encode(x: np.ndarray) -> np.ndarray:
    out = x.copy()
    n = len(x)
    if n < 2:
        return out
    prev = out[0]
    offset = out[0]
    for i in range(1, n):
        tmp = out[i]
        out[i] = offset + out[i] - prev
        prev = tmp
    return out


def linear_encode(x: np.ndarray) -> np.ndarray:
    out = x.copy()
    n = len(x)
    if n < 3:
        return out
    prev2 = out[0]
    prev1 = out[1]
    offset = out[1]
    for i in range(2, n):
        out[i] = offset + out[i] - 2 * prev1 + prev2
        tmp = prev1
        prev1 = out[i] + 2 * prev1 - prev2 - offset
        prev2 = tmp
    return out


# --- Direct unit tests of the reversal against the shared worked example ---


def test_reverse_delta_worked_example():
    """Both references: stored [100.0, 100.5, 100.5] -> [100.0, 100.5, 101.0]."""
    stored = np.array([100.0, 100.5, 100.5], dtype=np.float64)
    out = MSDecoder.reverse_delta_prediction(stored)
    np.testing.assert_array_equal(out, [100.0, 100.5, 101.0])


def test_reverse_linear_worked_example():
    stored = np.array([100.0, 100.5, 100.5], dtype=np.float64)
    out = MSDecoder.reverse_linear_prediction(stored)
    np.testing.assert_array_equal(out, [100.0, 100.5, 101.0])


def test_reverse_does_not_mutate_input():
    stored = np.array([100.0, 100.5, 100.5], dtype=np.float64)
    original = stored.copy()
    MSDecoder.reverse_delta_prediction(stored)
    MSDecoder.reverse_linear_prediction(stored)
    np.testing.assert_array_equal(stored, original)


# --- Round-trip through the reversal for a range of shapes and dtypes ---

# (array, rtol). float64 prediction is an exact inverse (rtol=0); float32 accumulates rounding in
# the forward+reverse recurrence — a small tolerance is expected and inherent to the scheme.
ROUND_TRIP_CASES = [
    (np.array([], dtype=np.float64), 0.0),
    (np.array([42.0], dtype=np.float64), 0.0),
    (np.array([10.0, 12.0], dtype=np.float64), 0.0),
    (np.arange(100.0, 400.0, 0.5, dtype=np.float64), 0.0),
    (np.linspace(200.0, 2000.0, 500, dtype=np.float32), 1e-6),
]


@pytest.mark.parametrize("original,rtol", ROUND_TRIP_CASES)
def test_delta_round_trip(original, rtol):
    stored = delta_encode(original)
    decoded = MSDecoder.reverse_delta_prediction(stored)
    np.testing.assert_allclose(decoded, original, rtol=rtol, atol=0)


@pytest.mark.parametrize("original,rtol", ROUND_TRIP_CASES)
def test_linear_round_trip(original, rtol):
    stored = linear_encode(original)
    decoded = MSDecoder.reverse_linear_prediction(stored)
    np.testing.assert_allclose(decoded, original, rtol=rtol, atol=0)


# --- End-to-end through the real BinaryDataArray decode dispatch ---


def _binary_data_array_xml(values: np.ndarray, dtype_accession: str, compression_accession: str) -> BinaryDataArray:
    payload = base64.b64encode(zlib.compress(values.tobytes())).decode("ascii")
    xml = (
        "<binaryDataArray>"
        f'<cvParam accession="{dtype_accession}" name="float" value=""/>'
        f'<cvParam accession="{compression_accession}" name="compression" value=""/>'
        f'<cvParam accession="{MZ_ARRAY}" name="m/z array" value=""/>'
        f"<binary>{payload}</binary>"
        "</binaryDataArray>"
    )
    return BinaryDataArray(ElementTree.fromstring(xml))


def _binary_data_array_xml_with_generic_zlib_first(
    values: np.ndarray, dtype_accession: str, compression_accession: str
) -> BinaryDataArray:
    payload = base64.b64encode(zlib.compress(values.tobytes())).decode("ascii")
    xml = (
        "<binaryDataArray>"
        f'<cvParam accession="{dtype_accession}" name="float" value=""/>'
        '<cvParam accession="MS:1000574" name="zlib compression" value=""/>'
        f'<cvParam accession="{compression_accession}" name="prediction compression" value=""/>'
        f'<cvParam accession="{MZ_ARRAY}" name="m/z array" value=""/>'
        f"<binary>{payload}</binary>"
        "</binaryDataArray>"
    )
    return BinaryDataArray(ElementTree.fromstring(xml))


@pytest.mark.parametrize(
    "dtype_accession,np_dtype", [(FLOAT_64, np.float64), (FLOAT_32, np.float32)]
)
def test_decode_truncation_delta_end_to_end(dtype_accession, np_dtype):
    original = np.arange(300.0, 600.0, 0.25, dtype=np_dtype)
    stored = delta_encode(original).astype(np_dtype)
    bda = _binary_data_array_xml(stored, dtype_accession, TRUNCATION_DELTA_ZLIB)
    decoded = bda._decode()
    assert decoded.dtype == np.float64
    np.testing.assert_allclose(decoded, original.astype(np.float64), rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize(
    "dtype_accession,np_dtype", [(FLOAT_64, np.float64), (FLOAT_32, np.float32)]
)
def test_decode_truncation_linear_end_to_end(dtype_accession, np_dtype):
    original = np.linspace(400.0, 1600.0, 400, dtype=np_dtype)
    stored = linear_encode(original).astype(np_dtype)
    bda = _binary_data_array_xml(stored, dtype_accession, TRUNCATION_LINEAR_ZLIB)
    decoded = bda._decode()
    assert decoded.dtype == np.float64
    np.testing.assert_allclose(decoded, original.astype(np.float64), rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize(
    "compression,encoder",
    [
        (TRUNCATION_DELTA_ZLIB, delta_encode),
        (TRUNCATION_LINEAR_ZLIB, linear_encode),
    ],
)
def test_prediction_compression_wins_when_generic_zlib_term_comes_first(compression, encoder):
    original = np.arange(100.0, 110.0, 0.5, dtype=np.float64)
    bda = _binary_data_array_xml_with_generic_zlib_first(encoder(original), FLOAT_64, compression)
    assert bda.compression == compression
    np.testing.assert_array_equal(bda._decode(), original)


@pytest.mark.parametrize("compression", [TRUNCATION_DELTA_ZLIB, TRUNCATION_LINEAR_ZLIB])
def test_prediction_decode_rejects_partial_elements(compression):
    payload = base64.b64encode(zlib.compress(b"not-a-multiple-of-eight")).decode("ascii")
    xml = (
        "<binaryDataArray>"
        f'<cvParam accession="{FLOAT_64}" name="64-bit float" value=""/>'
        f'<cvParam accession="{compression}" name="prediction compression" value=""/>'
        f'<cvParam accession="{MZ_ARRAY}" name="m/z array" value=""/>'
        f"<binary>{payload}</binary>"
        "</binaryDataArray>"
    )
    with pytest.raises(ValueError, match="not a multiple of the 8-byte element size"):
        BinaryDataArray(ElementTree.fromstring(xml))._decode()
