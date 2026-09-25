"""Property-based tests (Hypothesis) for binary array decoding and index offsets.

Arrays are encoded here with the reference codecs (numpy bytes, zlib, zstd, pynumpress) and the
spec'd byte layouts, then decoded through the real ``BinaryDataArray`` path. Whole indexedmzML
documents are generated with correct ``<offset>`` values and read back through every access
strategy, and through a self-indexed gzip written by ``write_indexed_gzip``.

Profiles: ``default`` is fast enough for every CI run; ``HYPOTHESIS_PROFILE=thorough`` runs many
more examples.
"""

import base64
import tempfile
import zlib
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import quoteattr

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from mzmlpy import Mzml, validate, write_indexed_gzip
from mzmlpy.constants import CompressionTypeAccession as C
from mzmlpy.decoder import MSDecoder
from mzmlpy.spectra import BinaryDataArray

DTYPES = {
    "MS:1000521": np.dtype("<f4"),
    "MS:1000523": np.dtype("<f8"),
    "MS:1000519": np.dtype("<i4"),
    "MS:1000522": np.dtype("<i8"),
}


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


@st.composite
def typed_arrays(draw, max_size=64):
    accession = draw(st.sampled_from(sorted(DTYPES)))
    dtype = DTYPES[accession]
    elements = (
        st.floats(width=dtype.itemsize * 8, allow_nan=True, allow_infinity=True)
        if dtype.kind == "f"
        else st.integers(np.iinfo(dtype).min, np.iinfo(dtype).max)
    )
    return accession, draw(hnp.arrays(dtype, st.integers(0, max_size), elements=elements))


def _shuffle(raw: bytes, size: int) -> bytes:
    """Byte-shuffle as specified for MS:1003781: all byte 0s, then all byte 1s, ..."""
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, size).T.tobytes()


def _lossless_payload(values: np.ndarray, compression: str) -> bytes:
    raw = values.tobytes()
    if compression == C.NO_COMPRESSION:
        return raw
    if compression == C.ZLIB_COMPRESSION:
        return zlib.compress(raw)
    zstd = pytest.importorskip("zstd")
    if compression == C.ZSTD_COMPRESSION:
        return zstd.compress(raw)
    return zstd.compress(_shuffle(raw, values.dtype.itemsize))


@given(
    typed_arrays(), st.sampled_from([C.NO_COMPRESSION, C.ZLIB_COMPRESSION, C.ZSTD_COMPRESSION, C.BYTE_SHUFFLED_ZSTD])
)
def test_lossless_codecs_round_trip_bit_exact(typed, compression):
    accession, values = typed
    payload = _lossless_payload(values, compression)
    decoded = _bda(payload, accession, compression).data
    assert decoded.dtype == values.dtype
    assert decoded.tobytes() == values.tobytes()  # bit-exact, NaN payloads included
    assert decoded.flags.writeable


@given(typed_arrays(), st.integers(1, 12))
def test_dictionary_encoded_zstd_round_trip(typed, n_unique):
    zstd = pytest.importorskip("zstd")
    accession, values = typed
    if values.size:
        # Draw values from a small table so the dictionary really is smaller than the output.
        values = values[np.arange(values.size) % min(n_unique, values.size)]
    table, indices = np.unique(values.view(f"u{values.dtype.itemsize}"), return_inverse=True)
    table = table.view(values.dtype)
    idx_size = 1 if len(table) <= 0xFF else 2
    idx = indices.astype(f"<u{idx_size}").tobytes()
    value_bytes = _shuffle(table.tobytes(), values.dtype.itemsize)
    header = np.array([16 + len(value_bytes), values.size], dtype="<u8").tobytes()
    body = header + value_bytes + (idx if idx_size == 1 else _shuffle(idx, idx_size))
    decoded = _bda(zstd.compress(body), accession, C.DICTIONARY_ENCODED_ZSTD).data
    assert decoded.tobytes() == values.tobytes()


@given(st.binary(max_size=256), st.integers(1, 8))
def test_unshuffle_inverts_shuffle(raw, size):
    raw = raw[: len(raw) - len(raw) % size]
    assert MSDecoder.unshuffle(_shuffle(raw, size), size) == raw


finite_mz = hnp.arrays(np.float64, st.integers(0, 64), elements=st.floats(0.0, 5000.0))
finite_intensity = hnp.arrays(np.float64, st.integers(0, 64), elements=st.floats(0.0, 1e9))


def _numpress_encode(kind: str, values: np.ndarray) -> bytes:
    pynumpress = pytest.importorskip("pynumpress")
    if kind == "linear":
        return bytes(pynumpress.encode_linear(values, pynumpress.optimal_linear_fixed_point(values)))
    if kind == "pic":
        return bytes(pynumpress.encode_pic(values))
    return bytes(pynumpress.encode_slof(values, pynumpress.optimal_slof_fixed_point(values)))


NUMPRESS = {
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


@given(st.sampled_from(sorted(NUMPRESS)), st.sampled_from(["none", "zlib", "zstd"]), finite_mz, finite_intensity)
def test_numpress_decodes_within_codec_error(kind, outer, mz, intensity):
    values = mz if kind == "linear" else intensity
    raw = _numpress_encode(kind, values)
    bare, with_zlib, with_zstd = NUMPRESS[kind]
    if outer == "zlib":
        payload, term = zlib.compress(raw), with_zlib
    elif outer == "zstd":
        payload, term = pytest.importorskip("zstd").compress(raw), with_zstd
    else:
        payload, term = raw, bare
    decoded = _bda(payload, "MS:1000521", term).data  # declared float32: numpress still yields float64
    assert decoded.dtype == np.float64
    assert decoded.shape == values.shape
    if kind == "linear":
        np.testing.assert_allclose(decoded, values, rtol=0, atol=1e-4)
    elif kind == "pic":
        # MSNumpress encodePic rounds half up: (size_t)(x + 0.5).
        np.testing.assert_array_equal(decoded, np.floor(values + 0.5))
    else:
        # Short logged float keeps ~4-5 significant digits of log(x + 1).
        np.testing.assert_allclose(decoded, values, rtol=5e-4, atol=1e-3)


# --- Whole documents: index offsets ---

_id_chars = st.characters(min_codepoint=0x20, max_codepoint=0x7E, exclude_characters='"<>&')
spectrum_ids = st.lists(
    st.text(_id_chars, min_size=1, max_size=20).map(str.strip).filter(bool), max_size=8, unique=True
)


def _array_xml(values: np.ndarray, accession: str, name: str, compress: bool) -> str:
    payload = zlib.compress(values.tobytes()) if compress else values.tobytes()
    encoded = base64.b64encode(payload).decode("ascii")
    compression = C.ZLIB_COMPRESSION if compress else C.NO_COMPRESSION
    return (
        f'<binaryDataArray encodedLength="{len(encoded)}">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>'
        f'<cvParam cvRef="MS" accession="{compression}" name="compression" value=""/>'
        f'<cvParam cvRef="MS" accession="{accession}" name="{name}" value=""/>'
        f"<binary>{encoded}</binary></binaryDataArray>"
    )


def build_indexed_mzml(spectra: list[tuple[str, np.ndarray, np.ndarray, bool]]) -> bytes:
    """Serialise spectra into an indexedmzML document whose offsets point at each <spectrum."""
    head = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n'
        '<mzML xmlns="http://psi.hupo.org/ms/mzml" version="1.1.0" id="prop">\n'
        '<cvList count="1"><cv id="MS" fullName="PSI-MS" URI="https://purl.obolibrary.org/obo/ms.obo"/></cvList>\n'
        "<fileDescription><fileContent/></fileDescription>\n"
        '<softwareList count="1"><software id="sw" version="1"/></softwareList>\n'
        '<instrumentConfigurationList count="1"><instrumentConfiguration id="IC"/></instrumentConfigurationList>\n'
        '<dataProcessingList count="1"><dataProcessing id="DP"/></dataProcessingList>\n'
        '<run id="r" defaultInstrumentConfigurationRef="IC">\n'
        f'<spectrumList count="{len(spectra)}" defaultDataProcessingRef="DP">\n'
    ).encode()
    body = bytearray(head)
    offsets = []
    for index, (spec_id, mz, intensity, compress) in enumerate(spectra):
        offsets.append((spec_id, len(body)))
        record = (
            f'<spectrum index="{index}" id={quoteattr(spec_id)} defaultArrayLength="{mz.size}">'
            '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
            f'<binaryDataArrayList count="2">{_array_xml(mz, "MS:1000514", "m/z array", compress)}'
            f"{_array_xml(intensity, 'MS:1000515', 'intensity array', compress)}</binaryDataArrayList>"
            "</spectrum>\n"
        )
        body += record.encode()
    body += b"</spectrumList>\n</run>\n</mzML>\n"
    index_offset = len(body)
    body += b'<indexList count="1"><index name="spectrum">'
    for spec_id, offset in offsets:
        body += f"<offset idRef={quoteattr(spec_id)}>{offset}</offset>".encode()
    body += f"</index></indexList>\n<indexListOffset>{index_offset}</indexListOffset>\n</indexedmzML>\n".encode()
    return bytes(body)


@st.composite
def documents(draw):
    ids = draw(spectrum_ids)
    spectra = []
    for spec_id in ids:
        n = draw(st.integers(0, 16))
        mz = draw(hnp.arrays(np.float64, n, elements=st.floats(0, 5000)))
        intensity = draw(hnp.arrays(np.float64, n, elements=st.floats(0, 1e9)))
        spectra.append((spec_id, mz, intensity, draw(st.booleans())))
    return spectra


def _check_reader(reader: Mzml, spectra) -> None:
    assert len(reader.spectra) == len(spectra)
    for index, (spec_id, mz, intensity, _) in enumerate(spectra):
        for spec in (reader.spectra[spec_id], reader.spectra[index]):
            assert spec.id == spec_id
            assert spec.index == index
            np.testing.assert_array_equal(spec.mz, mz)
            np.testing.assert_array_equal(spec.intensity, intensity)
    assert [s.id for s in reader.spectra] == [s[0] for s in spectra]


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(documents())
def test_index_offsets_round_trip_through_every_access_path(spectra):
    document = build_indexed_mzml(spectra)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "doc.mzML"
        path.write_bytes(document)
        # The offsets written above must be exactly what an index check expects.
        report = validate(path, decode_binary=True, check_index=True)
        assert report.valid, report.issues
        for kwargs in ({}, {"in_memory": False}, {"in_memory": False, "build_index_from_scratch": True}):
            with Mzml(path, **kwargs) as reader:
                _check_reader(reader, spectra)
        gz = Path(tmp) / "doc.mzML.gz"
        write_indexed_gzip(path, gz)
        with Mzml(gz, in_memory=False) as reader:
            assert reader.access_strategy == "embedded"
            _check_reader(reader, spectra)
