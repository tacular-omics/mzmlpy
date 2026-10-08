"""Round-trip property tests for the encode half of the codecs and for 32-bit arrays read from a file.

``test_properties.py`` already covers decoding of lossless codecs (bit-exact, every dtype, NaN/inf)
and numpress payloads made by pynumpress directly. The tests here cover what it does not:

* numpress payloads made by mzmlpy's own encoders (``MSDecoder.encode_*``), checked against the
  error bound the MS-Numpress format itself allows, read from the payload's fixed-point header;
* special and out-of-float32-range values in 32-bit arrays, written to a spectrum with an
  independent base64/zlib encoder (line-wrapped, as many writers emit) and read back through
  ``Mzml``.
"""

import base64
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from mzmlpy import Mzml
from mzmlpy.constants import CompressionTypeAccession as C
from mzmlpy.decoder import MSDecoder
from mzmlpy.spectra import BinaryDataArray

FLOAT_32 = "MS:1000521"
FLOAT_64 = "MS:1000523"

# kind -> (bare term, "followed by zlib" term, "followed by zstd" term)
NUMPRESS_TERMS = {
    "linear": (
        C.MS_NUMPRESS_LINEAR_PREDICTION,
        C.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB,
        C.MS_NUMPRESS_LINEAR_PREDICTION_ZSTD,
    ),
    "pic": (C.MS_NUMPRESS_POSITIVE_INTEGER, C.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB, C.MS_NUMPRESS_POSITIVE_INTEGER_ZSTD),
    "slof": (
        C.MS_NUMPRESS_SHORT_LOGGED_FLOAT,
        C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB,
        C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZSTD,
    ),
}

# Domain each MS-Numpress codec is specified for. Linear stores round(x * fp) in 32-bit ints with
# fp >= 1, so the linear extrapolation 2*x1 - x0 must stay below 2**31: values up to 1e9 are safe.
# Pic stores round(x) as a non-negative int (INT_MAX limit). Slof stores log(x + 1), x >= 0.
NUMPRESS_MAX = {"linear": 1e9, "pic": 2.0**31 - 2, "slof": 1e12}


@st.composite
def numpress_inputs(draw):
    """Non-negative arrays spanning tiny to large magnitudes, including empty and length 1."""
    kind = draw(st.sampled_from(sorted(NUMPRESS_TERMS)))
    scale = draw(st.sampled_from([1e-6, 1e-2, 1.0, 1e3, NUMPRESS_MAX[kind]]))
    unit = st.floats(0.0, 1.0, allow_subnormal=False)
    size = st.sampled_from([0, 1, 2]) | st.integers(3, 200)  # 1 value: linear's 12-byte payload
    values = draw(hnp.arrays(np.float64, size, elements=unit)) * scale
    return kind, values


def _bda(payload: bytes, dtype_accession: str, compression: str) -> BinaryDataArray:
    xml = (
        "<binaryDataArray>"
        f'<cvParam accession="{dtype_accession}" name="type" value=""/>'
        f'<cvParam accession="{compression}" name="compression" value=""/>'
        '<cvParam accession="MS:1000514" name="m/z array" value=""/>'
        f"<binary>{base64.b64encode(payload).decode('ascii')}</binary>"
        "</binaryDataArray>"
    )
    return BinaryDataArray(ElementTree.fromstring(xml))


def _header_fixed_point(payload: bytes) -> float:
    """MS-Numpress linear and slof payloads start with the fixed point as an 8-byte big-endian double."""
    return float(np.frombuffer(payload[:8], dtype=">f8")[0])


@given(numpress_inputs(), st.sampled_from(["none", "zlib", "zstd"]))
@example(("linear", np.array([123.4])), "none")
def test_mzmlpy_numpress_encoders_stay_within_the_format_error_bound(kind_values, outer):
    """Catches an MSDecoder.encode_* that passes a fixed point too large for the format's integer
    width (e.g. linear's optimum to slof, overflowing the 16-bit slof ints), a combined
    numpress+codec term dispatched to the wrong numpress decoder, and a wrong one-value linear
    decode (mzmlpy's own 12-byte special case: header endianness, first-value width).

    Oracles come from the MS-Numpress format, not from the code: linear stores round(x * fp) as
    exact integers, so |decoded - x| <= 0.5 / fp; pic stores round-half-up(x), so decoded equals
    floor(x + 0.5) exactly; slof stores round(log(x + 1) * fp), so |log1p(decoded) - log1p(x)| <=
    0.5 / fp. ``fp`` is read from the payload header. Tiny magnitudes make these bounds far tighter
    than the fixed tolerances of the decode-only test.
    """
    kind, values = kind_values
    pytest.importorskip("pynumpress")
    raw = bytes(getattr(MSDecoder, f"encode_{kind}")(values))
    bare, with_zlib, with_zstd = NUMPRESS_TERMS[kind]
    if outer == "zstd":
        payload, term = pytest.importorskip("zstd").compress(raw), with_zstd
    elif outer == "zlib":
        payload, term = zlib.compress(raw), with_zlib
    else:
        payload, term = raw, bare

    decoded = _bda(payload, FLOAT_64, term).data
    assert decoded.dtype == np.float64
    assert decoded.shape == values.shape
    if values.size == 0:
        return
    if kind == "pic":
        np.testing.assert_array_equal(decoded, np.floor(values + 0.5))
        return
    fixed_point = _header_fixed_point(raw)
    # x * fp and int / fp are each rounded once in double precision: allow a few ulps on top.
    if kind == "linear":
        error, reference = np.abs(decoded - values), values
    else:
        error, reference = np.abs(np.log1p(decoded) - np.log1p(values)), np.log1p(values)
    bound = 0.5 / fixed_point + 4 * np.spacing(np.maximum(reference, 1.0))
    assert np.all(error <= bound), (fixed_point, values[error > bound], decoded[error > bound])


any_float64 = st.floats(allow_nan=True, allow_infinity=True, allow_subnormal=True)


def _wrapped_base64(payload: bytes) -> str:
    """MIME-style base64: 76-character lines, as several mzML writers emit, plus XML indentation."""
    return "\n" + base64.encodebytes(payload).decode("ascii").replace("\n", "\n        ")


def _array_xml(values: np.ndarray, dtype_accession: str, compress: bool, array_accession: str) -> str:
    raw = values.tobytes()
    compression = C.ZLIB_COMPRESSION if compress else C.NO_COMPRESSION
    return (
        "<binaryDataArray>"
        f'<cvParam cvRef="MS" accession="{dtype_accession}" name="type" value=""/>'
        f'<cvParam cvRef="MS" accession="{compression}" name="compression" value=""/>'
        f'<cvParam cvRef="MS" accession="{array_accession}" name="array" value=""/>'
        f"<binary>{_wrapped_base64(zlib.compress(raw) if compress else raw)}</binary>"
        "</binaryDataArray>"
    )


@given(
    hnp.arrays(np.float64, st.integers(0, 300), elements=any_float64),
    st.booleans(),
    st.booleans(),
)
def test_spectrum_float32_mz_reads_back_as_float32_of_the_source(source, mz_zlib, intensity_zlib):
    """Catches a reader that drops or mangles line-wrapped base64 in <binary>, applies one array's
    data type or compression to its sibling (here a 32-bit m/z array next to a 64-bit intensity
    array, each with its own codec), or converts 32-bit values on the way out (upcasting, flushing
    -0.0 or subnormals, normalising NaN payloads, saturating instead of keeping inf).

    The spectrum is written by an independent encoder in this test (numpy cast + zlib + base64), so
    a bug shared by an mzmlpy encoder and decoder cannot cancel out. Oracle: the m/z array equals
    np.float32(source) bit for bit (values beyond float32 range become +-inf, tiny ones +-0.0); the
    intensity array equals the float64 source bit for bit.
    """
    with np.errstate(over="ignore"):  # values beyond float32 range are meant to become +-inf
        mz = source.astype("<f4")
        expected_mz = np.float32(source)
    intensity = source[::-1].copy()
    document = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0">\n'
        '<run id="r"><spectrumList count="1">\n'
        f'<spectrum index="0" id="scan=1" defaultArrayLength="{source.size}">\n'
        '<binaryDataArrayList count="2">\n'
        f"{_array_xml(mz, FLOAT_32, mz_zlib, 'MS:1000514')}\n"
        f"{_array_xml(intensity, FLOAT_64, intensity_zlib, 'MS:1000515')}\n"
        "</binaryDataArrayList></spectrum></spectrumList></run></mzML>\n"
    )
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.mzML"
        path.write_text(document, encoding="utf-8")
        with Mzml(path) as reader:
            spectrum = reader.spectra[0]
            read_mz, read_intensity = spectrum.mz, spectrum.intensity
    assert read_mz.dtype == np.dtype("<f4")
    assert read_mz.tobytes() == expected_mz.tobytes()  # NaN-aware: compares bit patterns
    assert read_intensity.dtype == np.dtype("<f8")
    assert read_intensity.tobytes() == intensity.tobytes()
