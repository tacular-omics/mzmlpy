"""Preserve encoded types and exact integers through the reader and MCP transport."""

import asyncio
import base64
import copy
import gzip
import json
import struct
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from mzmlpy import BinaryDataArray, Mzml
from mzmlpy.constants import BinaryDataTypeAccession as DType
from mzmlpy.constants import CompressionTypeAccessions as Compression
from mzmlpy.decoder import MSDecoder
from mzmlpy.mcp import MzmlTools, _points

TYPES = [(DType.FLOAT_32, "<f4"), (DType.FLOAT_64, "<f8"), (DType.INT_32, "<i4"), (DType.INT_64, "<i8")]
CODECS = [
    Compression.NO_COMPRESSION,
    Compression.ZLIB_COMPRESSION,
    Compression.TRUNCATION_ZLIB,
    Compression.ZSTD_COMPRESSION,
    Compression.BYTE_SHUFFLED_ZSTD,
    Compression.DICTIONARY_ENCODED_ZSTD,
]


def values_for(dtype: str) -> np.ndarray:
    if dtype == "<i8":
        return np.array([-(2**63), -(2**53 + 1), -1, 0, 2**53 - 1, 2**53 + 1, 2**63 - 1], dtype=dtype)
    if dtype == "<i4":
        return np.array([-(2**31), -1, 0, 2**31 - 1], dtype=dtype)
    return np.array([-0.0, 0.1, 1.5, np.finfo(dtype).tiny, np.finfo(dtype).max], dtype=dtype)


def shuffle(data: bytes, size: int) -> bytes:
    return b"".join(data[i::size] for i in range(size))


def array_xml(values: np.ndarray, accession: str, codec: str, semantic: str = "MS:1000515") -> ET.Element:
    payload = values.tobytes()
    if codec in {Compression.ZLIB_COMPRESSION, Compression.TRUNCATION_ZLIB}:
        payload = zlib.compress(payload)
    elif codec in {Compression.ZSTD_COMPRESSION, Compression.BYTE_SHUFFLED_ZSTD, Compression.DICTIONARY_ENCODED_ZSTD}:
        zstd = pytest.importorskip("zstd")
        if codec == Compression.BYTE_SHUFFLED_ZSTD:
            payload = shuffle(payload, values.itemsize)
        elif codec == Compression.DICTIONARY_ENCODED_ZSTD:
            # A dictionary may repeat entries. Nonmonotonic indices also exercise ordering.
            dictionary = values[::-1].copy()
            indices = np.arange(len(values) - 1, -1, -1, dtype=np.uint8)
            payload = struct.pack("<QQ", 16 + dictionary.nbytes, len(values))
            payload += shuffle(dictionary.tobytes(), values.itemsize) + indices.tobytes()
        payload = zstd.compress(payload)
    array = ET.Element("binaryDataArray")
    ET.SubElement(array, "cvParam", accession=accession)
    ET.SubElement(array, "cvParam", accession=codec)
    attrs = {"accession": semantic}
    if semantic == "MS:1000595":
        attrs.update(unitAccession="UO:0000010", unitName="second")
    ET.SubElement(array, "cvParam", **attrs)
    ET.SubElement(array, "binary").text = base64.b64encode(payload).decode()
    return array


@pytest.mark.parametrize("accession,dtype", TYPES)
@pytest.mark.parametrize("codec", CODECS)
@pytest.mark.parametrize("empty", [False, True])
def test_native_values_across_codecs(accession, dtype, codec, empty):
    expected = np.array([], dtype=dtype) if empty else values_for(dtype)
    record = BinaryDataArray(array_xml(expected, accession, codec))
    actual = record.data
    assert actual.dtype == expected.dtype
    assert actual.tobytes() == expected.tobytes()
    assert actual.nbytes == expected.nbytes
    assert actual.flags.writeable
    if not empty:
        actual[0] = 42
        assert record.data.tobytes() == expected.tobytes()


@pytest.mark.parametrize("accession,dtype", TYPES)
@pytest.mark.parametrize("text", [None, "", "  \n "])
def test_empty_binary_preserves_declared_type(accession, dtype, text):
    element = array_xml(np.array([], dtype=dtype), accession, Compression.NO_COMPRESSION)
    element.find("binary").text = text
    assert BinaryDataArray(element).data.dtype == np.dtype(dtype)
    element.remove(element.find("binary"))
    assert BinaryDataArray(element).data.dtype == np.dtype(dtype)


@pytest.mark.parametrize(
    "method,codec",
    [
        ("linear", Compression.MS_NUMPRESS_LINEAR_PREDICTION),
        ("pic", Compression.MS_NUMPRESS_POSITIVE_INTEGER),
        ("slof", Compression.MS_NUMPRESS_SHORT_LOGGED_FLOAT),
    ],
)
def test_numpress_retains_reconstructed_precision(method, codec):
    pytest.importorskip("pynumpress")
    values = np.array([100.0, 101.0, 102.0], dtype=np.float64)
    payload = bytes(getattr(MSDecoder, f"encode_{method}")(values))
    element = array_xml(values, DType.FLOAT_64, Compression.NO_COMPRESSION)
    element.findall("cvParam")[1].set("accession", codec)
    element.find("binary").text = base64.b64encode(payload).decode()
    actual = BinaryDataArray(element).data
    assert actual.dtype == np.float64
    np.testing.assert_allclose(actual, getattr(MSDecoder, f"decode_{method}")(payload), rtol=0, atol=0)
    element.find("binary").text = ""
    assert BinaryDataArray(element).data.dtype == np.float64


def write_run(path: Path, values: np.ndarray, accession: str) -> None:
    root = ET.Element("mzML", version="1.1.0")
    run = ET.SubElement(root, "run", id="run")
    for kind in ["spectrum", "chromatogram"]:
        records = ET.SubElement(run, f"{kind}List", count="1")
        record = ET.SubElement(records, kind, id="record", index="0", defaultArrayLength=str(len(values)))
        arrays = ET.SubElement(record, "binaryDataArrayList", count="2")
        semantic = "MS:1000514" if kind == "spectrum" else "MS:1000595"
        arrays.append(
            array_xml(np.arange(len(values), dtype="<f4"), DType.FLOAT_32, Compression.ZLIB_COMPRESSION, semantic)
        )
        arrays.append(array_xml(values, accession, Compression.ZLIB_COMPRESSION))
        if kind == "spectrum":
            charge = copy.deepcopy(arrays[-1])
            charge.findall("cvParam")[-1].set("accession", "MS:1000516")
            arrays.append(charge)
            arrays.set("count", "3")
    content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    path.write_bytes(gzip.compress(content) if path.suffix == ".gz" else content)


@pytest.mark.parametrize("accession,dtype", TYPES)
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("in_memory", [False, True])
def test_public_array_accessors(tmp_path, accession, dtype, compressed, in_memory):
    path = tmp_path / ("run.mzML.gz" if compressed else "run.mzML")
    values = values_for(dtype)
    write_run(path, values, accession)
    with Mzml(path, in_memory=in_memory, gzip_mode="stream") as reader:
        spectrum = next(iter(reader.spectra))
        chromatogram = next(iter(reader.chromatograms))
        assert spectrum.mz.dtype == np.dtype("<f4")
        assert chromatogram.time.dtype == np.dtype("<f4")
        for actual in [spectrum.intensity, spectrum.charge, chromatogram.intensity]:
            assert actual.dtype == values.dtype
            assert actual.tobytes() == values.tobytes()


def test_mcp_values_preserve_large_integers_and_types(tmp_path):
    values = values_for("<i8")
    write_run(tmp_path / "run.mzML", values, DType.INT_64)
    expected = [str(int(v)) if abs(int(v)) > 2**53 - 1 else int(v) for v in values]
    service = MzmlTools(tmp_path)
    try:
        data = service.get_array("run.mzML", "record", 1).data
        assert data["dtype"] == "int64"
        assert data["values"] == expected
        assert type(data["values"][2]) is int
        peaks = service.get_spectrum("run.mzML", "record", include_peaks=True).data["peaks"]
        assert [point[1] for point in peaks["points"]] == expected
        assert peaks["intensity_dtype"] == "int64"
        chromatogram = service.get_chromatogram("run.mzML", "record").data
        assert [point[1] for point in chromatogram["points"]] == expected
        assert chromatogram["coordinate_dtype"] == "float32"
    finally:
        service.close()
    # Bound comparisons must also happen before a lossy float conversion.
    points = _points(np.array([2**53, 2**53 + 1], dtype="<i8"), np.array([1, 2]), 0, 10, (None, float(2**53)))
    assert points["points"] == [[str(2**53), 1]]


def test_native_mcp_protocol(tmp_path):
    mcp = pytest.importorskip("mcp")
    from mzmlpy.mcp import create_server

    write_run(tmp_path / "run.mzML", values_for("<i8"), DType.INT_64)

    async def exercise():
        async with asyncio.timeout(25), mcp.Client(create_server(tmp_path)) as client:
            for tool, arguments in [
                ("get_array", {"record_id": "record", "array_index": 1}),
                ("get_spectrum", {"spectrum_id": "record", "include_peaks": True}),
                ("get_chromatogram", {"chromatogram_id": "record"}),
            ]:
                result = await client.call_tool(tool, {"file": "run.mzML", **arguments})
                assert not result.is_error, result
                data = json.loads(json.dumps(result.structured_content))["data"]
                if tool == "get_spectrum":
                    data = data["peaks"]
                values = data["values"] if tool == "get_array" else [point[1] for point in data["points"]]
                assert values[-1] == str(2**63 - 1)
                assert values[-2] == str(2**53 + 1)
                assert values[2] == -1 and type(values[2]) is int

    asyncio.run(exercise())
