"""Compression-term resolution when a binaryDataArray carries more than one compression cvParam.

The mzML 1.1 CV mapping allows exactly one child of MS:1000572 (binary data compression type), but
files written before the combined "MS-Numpress ... followed by zlib compression" terms
(MS:1002746-MS:1002748) existed carry the numpress term and the generic zlib term as two separate
cvParams. ProteoWizard's reader combines them (numpress after zlib). cvParam order has no meaning in
mzML, so the resolved codec must not depend on which term comes first.
"""

import base64
import zlib
from xml.etree import ElementTree

import numpy as np
import pytest

from mzmlpy.constants import CompressionTypeAccession as C
from mzmlpy.spectra import BinaryDataArray

FLOAT_64 = "MS:1000523"
MZ_ARRAY = "MS:1000514"


def _bda(payload: bytes, *compression_terms: str) -> BinaryDataArray:
    params = "".join(f'<cvParam accession="{acc}" name="compression" value=""/>' for acc in compression_terms)
    xml = (
        "<binaryDataArray>"
        f'<cvParam cvRef="MS" accession="{FLOAT_64}" name="64-bit float" value=""/>'
        f"{params}"
        f'<cvParam cvRef="MS" accession="{MZ_ARRAY}" name="m/z array" value=""/>'
        f"<binary>{base64.b64encode(payload).decode('ascii')}</binary>"
        "</binaryDataArray>"
    )
    return BinaryDataArray(ElementTree.fromstring(xml))


VALUES = np.array([100.0, 250.5, 250.75, 1000.125, 1500.0625], dtype=np.float64)


def _numpress(kind: str) -> tuple[bytes, str, str]:
    pynumpress = pytest.importorskip("pynumpress")
    if kind == "linear":
        raw = pynumpress.encode_linear(VALUES, pynumpress.optimal_linear_fixed_point(VALUES))
        return bytes(raw), C.MS_NUMPRESS_LINEAR_PREDICTION, C.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB
    if kind == "pic":
        raw = pynumpress.encode_pic(VALUES)
        return bytes(raw), C.MS_NUMPRESS_POSITIVE_INTEGER, C.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB
    raw = pynumpress.encode_slof(VALUES, pynumpress.optimal_slof_fixed_point(VALUES))
    return bytes(raw), C.MS_NUMPRESS_SHORT_LOGGED_FLOAT, C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB


@pytest.mark.parametrize("kind", ["linear", "pic", "slof"])
@pytest.mark.parametrize("zlib_first", [True, False])
def test_legacy_numpress_plus_zlib_terms_decode_as_combined(kind, zlib_first):
    raw, numpress_term, combined_term = _numpress(kind)
    compressed = zlib.compress(raw)
    terms = (C.ZLIB_COMPRESSION, numpress_term) if zlib_first else (numpress_term, C.ZLIB_COMPRESSION)
    legacy = _bda(compressed, *terms)
    combined = _bda(compressed, combined_term)
    assert legacy.compression == combined_term
    np.testing.assert_array_equal(legacy.data, combined.data)


@pytest.mark.parametrize(
    "numpress_term,combined_term",
    [
        (C.MS_NUMPRESS_LINEAR_PREDICTION, C.MS_NUMPRESS_LINEAR_PREDICTION_ZSTD),
        (C.MS_NUMPRESS_POSITIVE_INTEGER, C.MS_NUMPRESS_POSITIVE_INTEGER_ZSTD),
        (C.MS_NUMPRESS_SHORT_LOGGED_FLOAT, C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZSTD),
    ],
)
@pytest.mark.parametrize("zstd_first", [True, False])
def test_numpress_plus_zstd_terms_resolve_to_combined(numpress_term, combined_term, zstd_first):
    terms = (C.ZSTD_COMPRESSION, numpress_term) if zstd_first else (numpress_term, C.ZSTD_COMPRESSION)
    assert _bda(b"", *terms).compression == combined_term


@pytest.mark.parametrize("none_first", [True, False])
def test_no_compression_term_does_not_mask_a_real_codec(none_first):
    terms = (C.NO_COMPRESSION, C.ZLIB_COMPRESSION) if none_first else (C.ZLIB_COMPRESSION, C.NO_COMPRESSION)
    bda = _bda(zlib.compress(VALUES.tobytes()), *terms)
    assert bda.compression == C.ZLIB_COMPRESSION
    np.testing.assert_array_equal(bda.data, VALUES)


def test_conflicting_codecs_warn():
    with pytest.warns(UserWarning, match="compression"):
        result = _bda(b"", C.ZLIB_COMPRESSION, C.ZSTD_COMPRESSION).compression
    assert result == C.ZLIB_COMPRESSION


def test_single_term_unchanged():
    assert _bda(b"", C.ZLIB_COMPRESSION).compression == C.ZLIB_COMPRESSION
    assert _bda(b"", C.MS_NUMPRESS_LINEAR_PREDICTION).compression == C.MS_NUMPRESS_LINEAR_PREDICTION
    assert _bda(b"").compression is None


@pytest.mark.parametrize("value", [0.0, 5.0, 445.1234567, 4999.99])
def test_numpress_linear_single_value(value):
    """A one-peak array encodes to 12 bytes (fixed point + first value); pynumpress 0.1.5 rejects it.

    MSNumpress' reference decodeLinear returns one value for a 12-byte buffer. Found by Hypothesis.
    """
    pynumpress = pytest.importorskip("pynumpress")
    values = np.array([value])
    raw = bytes(pynumpress.encode_linear(values, pynumpress.optimal_linear_fixed_point(values)))
    assert len(raw) == 12
    for payload, term in (
        (raw, C.MS_NUMPRESS_LINEAR_PREDICTION),
        (zlib.compress(raw), C.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB),
    ):
        decoded = _bda(payload, term).data
        assert decoded.dtype == np.float64
        np.testing.assert_allclose(decoded, values, rtol=0, atol=1e-6)
