"""Regression tests for a fresh batch of behavioral fixes.

Each test here is written against the *correct* post-fix behavior; every one of them would fail
against the code as it stood before the fix it documents.
"""

import io
import shutil
import struct
import warnings
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from mzmlpy import Mzml
from mzmlpy.decoder import MSDecoder
from mzmlpy.spectra import Activation, Spectrum, _parse_native_id

EXAMPLE = "tests/data/example.mzML"
EXAMPLE_GZ = "tests/data/example.mzML.gz"


# --------------------------------------------------------------------------------------------
# 1. Stable lookup / cursor persistence
# --------------------------------------------------------------------------------------------


def test_spectra_lookup_is_cached_across_accesses() -> None:
    """`.spectra` must return the same lookup instance every time, not rebuild one per access."""
    with Mzml(EXAMPLE) as reader:
        assert reader.spectra is reader.spectra


def test_chromatograms_lookup_is_cached_across_accesses() -> None:
    """`.chromatograms` must return the same lookup instance every time."""
    with Mzml(EXAMPLE) as reader:
        assert reader.chromatograms is reader.chromatograms


def test_repeated_spectra_access_shares_one_cursor() -> None:
    """Calling `.spectra` fresh each time must not reset the `next()` cursor.

    Against the old (non-cached) property, `reader.spectra.next()` restarted at index 0 on
    every call because each `.spectra` access built a brand-new `SpectrumLookup`.
    """
    with Mzml(EXAMPLE) as reader:
        first = reader.spectra.next()
        second = reader.spectra.next()
        third = reader.spectra.next()
        assert [first.id, second.id, third.id] == ["scan=19", "scan=20", "scan=21"]


def test_next_advances_through_all_spectra_by_index() -> None:
    """`next()` called repeatedly must walk forward 0, 1, 2, ... rather than restarting at 0."""
    with Mzml(EXAMPLE) as reader:
        lookup = reader.spectra
        seen = [lookup.next() for _ in range(len(lookup))]
        assert [s.id for s in seen] == [reader.spectra[i].id for i in range(len(lookup))]


def test_next_reset_restarts_at_first_spectrum() -> None:
    """`reset()` rewinds the cursor so the following `next()` yields the first spectrum again."""
    with Mzml(EXAMPLE) as reader:
        lookup = reader.spectra
        first = lookup.next()
        lookup.next()
        lookup.next()
        lookup.reset()
        assert lookup.next().id == first.id == "scan=19"


# --------------------------------------------------------------------------------------------
# 2. File-like object input
# --------------------------------------------------------------------------------------------


def test_mzml_accepts_an_open_binary_file_handle() -> None:
    """A plain `open(path, "rb")` handle (not just BytesIO) is accepted directly."""
    with open(EXAMPLE, "rb") as fh, Mzml(fh) as reader:
        assert len(reader.spectra) == 4


def test_mzml_accepts_an_open_gzip_file_handle_and_decompresses() -> None:
    """A file handle opened on a `.mzML.gz` file is transparently decompressed."""
    with open(EXAMPLE_GZ, "rb") as fh, Mzml(fh) as reader:
        assert len(reader.spectra) == 4
        expected_ids = ["scan=19", "scan=20", "scan=21", "sample=1 period=1 cycle=22 experiment=1"]
        assert [s.id for s in reader.spectra] == expected_ids


def test_mzml_accepts_bytesio_of_raw_mzml() -> None:
    with open(EXAMPLE, "rb") as fh:
        raw = fh.read()
    with Mzml(io.BytesIO(raw)) as reader:
        assert len(reader.spectra) == 4


def test_mzml_accepts_bytesio_of_gzipped_mzml_and_decompresses() -> None:
    with open(EXAMPLE_GZ, "rb") as fh:
        gzipped = fh.read()
    with Mzml(io.BytesIO(gzipped)) as reader:
        assert len(reader.spectra) == 4


def test_mzml_rejects_unsupported_input_type_with_actionable_typeerror() -> None:
    """An object that is neither a path nor file-like raises a `TypeError` naming the problem.

    A bare ``int`` fails earlier (during encoding sniffing) with a different exception, so this
    uses a minimal object that clears the encoding-sniff step (has ``readline``) but is rejected
    by ``FileInterface`` for lacking ``read`` — the actual path that raises the documented
    `TypeError`.
    """

    class _NotFileLike:
        def readline(self) -> bytes:
            return b""

    with pytest.raises(TypeError, match="expected a path"):
        Mzml(_NotFileLike())


def test_file_interface_rejects_unsupported_type_directly() -> None:
    """Unit-level check of the `TypeError` raised by `FileInterface` for a wholly unsupported type."""
    from mzmlpy.file_interface import FileInterface

    with pytest.raises(TypeError, match="expected a path"):
        FileInterface(path=12345, encoding="utf-8")


# --------------------------------------------------------------------------------------------
# 3. gzip_mode ignored warning
# --------------------------------------------------------------------------------------------


def test_gzip_mode_indexed_warns_when_in_memory_default() -> None:
    """`in_memory=True` (the default) makes `gzip_mode='indexed'` a no-op; that must be flagged."""
    with pytest.warns(UserWarning, match="ignored because in_memory"):
        reader = Mzml(EXAMPLE_GZ, gzip_mode="indexed")
    reader.close()


def test_gzip_mode_stream_warns_when_in_memory_default() -> None:
    with pytest.warns(UserWarning, match="ignored because in_memory"):
        reader = Mzml(EXAMPLE_GZ, gzip_mode="stream")
    reader.close()


def test_gzip_mode_extract_default_does_not_warn() -> None:
    """The default `gzip_mode='extract'` is compatible with `in_memory=True` and warns about nothing."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reader = Mzml(EXAMPLE_GZ, gzip_mode="extract")
        reader.close()
    assert not any("ignored because in_memory" in str(w.message) for w in caught)


def test_gzip_mode_indexed_with_in_memory_false_does_not_warn(tmp_path: Path) -> None:
    """When `in_memory=False`, `gzip_mode='indexed'` is actually honored, so no warning fires.

    Uses a `tmp_path` copy of the fixture (rather than `tests/data/example.mzML.gz` directly)
    because ``gzip_mode='indexed'`` writes ``.gzidx``/``.mzMLidx`` cache files next to the
    source path, and this keeps that side effect out of the repo's test-data directory.
    """
    pytest.importorskip("rapidgzip")
    gz_copy = tmp_path / "example.mzML.gz"
    shutil.copy(EXAMPLE_GZ, gz_copy)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reader = Mzml(str(gz_copy), gzip_mode="indexed", in_memory=False)
        reader.close()
    assert not any("ignored because in_memory" in str(w.message) for w in caught)


# --------------------------------------------------------------------------------------------
# 4. Native-id integer coercion fidelity
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("native_id", "expected"),
    [
        ("scan=19", {"scan": 19}),
        ("scan=007", {"scan": "007"}),
        ("n=1_000", {"n": "1_000"}),
        ("x=-5", {"x": -5}),
    ],
)
def test_parse_native_id_coercion(native_id: str, expected: dict[str, int | str]) -> None:
    result = _parse_native_id(native_id)
    assert result == expected
    for key, value in expected.items():
        assert type(result[key]) is type(value)


def test_parse_native_id_leading_zeros_stay_string() -> None:
    """Leading zeros are not numerically round-trippable, so the value must stay a string."""
    result = _parse_native_id("scan=007")
    assert result["scan"] == "007"
    assert isinstance(result["scan"], str)


def test_parse_native_id_underscores_stay_string() -> None:
    """Underscore-grouped digits are valid `int()` input but not what's on disk, so keep as str."""
    result = _parse_native_id("n=1_000")
    assert result["n"] == "1_000"
    assert isinstance(result["n"], str)


def test_id_dict_round_trips_real_spectrum_id() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum: Spectrum = reader.spectra[0]
        assert spectrum.id == "scan=19"
        assert spectrum.id_dict == {"scan": 19}
        assert isinstance(spectrum.id_dict["scan"], int)


# --------------------------------------------------------------------------------------------
# 5. Dictionary-encoded zstd decode with fewer unique values than points (U < N)
# --------------------------------------------------------------------------------------------


def _shuffle(raw: bytes, element_size: int) -> bytes:
    """Group same-position bytes together, mirroring MSDecoder's byte-shuffle encoding."""
    n = len(raw) // element_size
    return bytes(raw[j * element_size + i] for i in range(element_size) for j in range(n))


def _build_dict_encoded_zstd_payload(values: NDArray[np.float64], indices: NDArray[np.unsignedinteger]) -> bytes:
    value_bytes = _shuffle(values.tobytes(), values.dtype.itemsize)
    idx_element_size = indices.dtype.itemsize
    idx_bytes = indices.tobytes() if idx_element_size == 1 else _shuffle(indices.tobytes(), idx_element_size)
    index_offset = 16 + len(value_bytes)
    decompressed = struct.pack("<QQ", index_offset, len(indices)) + value_bytes + idx_bytes
    zstd = pytest.importorskip("zstd")
    return zstd.compress(decompressed)


def test_dict_encoded_zstd_decodes_fewer_unique_values_than_points_one_byte_index() -> None:
    """The critical dictionary-encoding case: 3 unique values expand to 10 output points.

    The existing fixture happens to have unique-count == output-count, so it cannot catch a bug
    where the decoder sizes the value table off the output count instead of the header's index
    offset — this hand-built payload can.
    """
    values = np.array([10.0, 20.0, 30.0], dtype="<f8")
    indices = np.array([0, 1, 2, 0, 1, 2, 0, 1, 2, 0], dtype="<u1")
    payload = _build_dict_encoded_zstd_payload(values, indices)

    result = MSDecoder.decode_dict_encoded_zstd(payload, np.dtype("<f8"))

    assert np.allclose(result, values[indices])


def test_dict_encoded_zstd_decodes_fewer_unique_values_than_points_two_byte_index() -> None:
    """Same as above but with > 256 output points, forcing a 2-byte (uint16) index table."""
    values = np.array([1.5, 2.5, 3.5, 4.5], dtype="<f8")
    n_points = 300
    indices = np.array([i % len(values) for i in range(n_points)], dtype="<u2")
    payload = _build_dict_encoded_zstd_payload(values, indices)

    result = MSDecoder.decode_dict_encoded_zstd(payload, np.dtype("<f8"))

    assert np.allclose(result, values[indices])
    assert len(result) == n_points


# --------------------------------------------------------------------------------------------
# 6. collision_gas valueless flag
# --------------------------------------------------------------------------------------------


def test_collision_gas_returns_term_name_when_valueless() -> None:
    """MS:1000419 (collision gas) is normally a valueless flag; the name carries the identity."""
    element = ElementTree.fromstring(
        '<activation><cvParam accession="MS:1000419" name="nitrogen" value=""/></activation>'
    )
    activation = Activation(element)
    assert activation.collision_gas == "nitrogen"


def test_collision_gas_prefers_value_when_present() -> None:
    element = ElementTree.fromstring(
        '<activation><cvParam accession="MS:1000419" name="collision gas" value="argon"/></activation>'
    )
    activation = Activation(element)
    assert activation.collision_gas == "argon"


def test_collision_gas_none_when_absent() -> None:
    element = ElementTree.fromstring("<activation></activation>")
    activation = Activation(element)
    assert activation.collision_gas is None


# --------------------------------------------------------------------------------------------
# 7. Duplicate-id from-scratch warning
# --------------------------------------------------------------------------------------------

_HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n'
    '<mzML id="m" version="1.1.0">\n'
)
_FOOTER = "</mzML></indexedmzML>\n"


def test_duplicate_spectrum_id_from_scratch_warns(tmp_path: Path) -> None:
    """Building the index from scratch over duplicate spectrum ids must warn, not silently drop."""
    body = (
        '<run id="r"><spectrumList count="2">\n'
        '<spectrum index="0" id="dup" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/></spectrum>\n'
        '<spectrum index="1" id="dup" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/></spectrum>\n'
        "</spectrumList></run>"
    )
    path = tmp_path / "dupids.mzML"
    path.write_text(_HEADER + body + _FOOTER, encoding="utf-8")

    with pytest.warns(UserWarning, match="Duplicate spectrum id"):
        reader = Mzml(str(path), build_index_from_scratch=True)
    reader.close()


def test_duplicate_chromatogram_id_from_scratch_warns(tmp_path: Path) -> None:
    body = (
        '<run id="r"><chromatogramList count="2">\n'
        '<chromatogram index="0" id="dup" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000235" name="total ion current chromatogram" value=""/></chromatogram>\n'
        '<chromatogram index="1" id="dup" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000235" name="total ion current chromatogram" value=""/></chromatogram>\n'
        "</chromatogramList></run>"
    )
    path = tmp_path / "dupchromids.mzML"
    path.write_text(_HEADER + body + _FOOTER, encoding="utf-8")

    with pytest.warns(UserWarning, match="Duplicate chromatogram id"):
        reader = Mzml(str(path), build_index_from_scratch=True)
    reader.close()


# --------------------------------------------------------------------------------------------
# 8. peek_spectrum_count with no spectrumList (already covered elsewhere; sanity check here too)
# --------------------------------------------------------------------------------------------


def test_peek_spectrum_count_none_without_spectrum_list(tmp_path: Path) -> None:
    from mzmlpy import peek_spectrum_count

    body = '<run id="r"><chromatogramList count="0"></chromatogramList></run>'
    path = tmp_path / "no_spectra.mzML"
    path.write_text(_HEADER + body + _FOOTER, encoding="utf-8")
    assert peek_spectrum_count(str(path)) is None


# --------------------------------------------------------------------------------------------
# 9. Spectrum id lookup is strict and identical across reader modes
#    (stream mode previously matched a bare trailing number, which could return the wrong spectrum)
# --------------------------------------------------------------------------------------------


def test_id_lookup_consistent_across_modes() -> None:
    """A bare trailing number must NOT resolve in any mode; the full native id must resolve in all.

    example.mzML.gz has ids 'scan=19'/'scan=20'/'scan=21' and 'sample=1 period=1 cycle=22
    experiment=1'. Old stream mode returned the SCIEX spectrum for ``["1"]`` (matching the trailing
    ``experiment=1``) and returned ``scan=19`` for ``["19"]``; every other mode raised KeyError.
    """
    warnings.simplefilter("ignore")  # silence the stream re-scan UserWarning

    def probe(**kwargs: object) -> tuple[object, object]:
        with Mzml(EXAMPLE_GZ, **kwargs) as r:  # type: ignore[arg-type]
            # Bare trailing number no longer resolves in any mode.
            with pytest.raises(KeyError):
                r.spectra["19"]
            with pytest.raises(KeyError):
                r.spectra["1"]
            # Full native id resolves in every mode.
            return r.spectra["scan=19"].id, len(r.spectra)

    default = probe()
    stream = probe(gzip_mode="stream", in_memory=False)
    assert default == stream == ("scan=19", 4)


def test_id_regex_resolves_identically_in_stream_and_default() -> None:
    """The sanctioned component lookup (spectrum_id_regex) resolves the same in every mode."""
    warnings.simplefilter("ignore")

    with Mzml(EXAMPLE_GZ, spectrum_id_regex=r"scan=(\d+)") as rd:
        assert rd.spectra["19"].id == "scan=19"
    with Mzml(EXAMPLE_GZ, spectrum_id_regex=r"scan=(\d+)", gzip_mode="stream", in_memory=False) as rs:
        assert rs.spectra["19"].id == "scan=19"
