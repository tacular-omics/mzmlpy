"""Diagnostic-quality tests: errors should be actionable, not cryptic."""

import pytest

from mzmlpy import Mzml

_HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n'
    '<mzML id="m" version="1.1.0">\n'
)
_FOOTER = "</mzML></indexedmzML>\n"


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(_HEADER + body + _FOOTER, encoding="utf-8")
    return str(p)


def test_missing_optional_dependency_error_is_actionable():
    """A missing decode dependency names the package and the pip extra to install."""
    from mzmlpy.decoder import _require

    with pytest.raises(ImportError) as exc:
        _require("definitely_not_a_real_module_xyz", "numpress")
    msg = str(exc.value)
    assert "definitely_not_a_real_module_xyz" in msg
    assert "pip install mzmlpy[numpress]" in msg


def test_unsupported_dtype_error_names_the_accession():
    """The 'unsupported data type' error must show the actual accession, not None."""
    from mzmlpy.spectra import decode_to_numpy

    with pytest.raises(ValueError) as exc:
        decode_to_numpy(b"\x00" * 8, "MS:9999999")
    assert "MS:9999999" in str(exc.value)


def test_buffer_size_mismatch_error_is_contextual():
    """A byte count that isn't a multiple of the element size explains why, not a raw numpy error."""
    from mzmlpy.spectra import decode_to_numpy

    with pytest.raises(ValueError) as exc:
        decode_to_numpy(b"\x00" * 7, "MS:1000523")  # 7 bytes, 64-bit float = 8-byte elements
    msg = str(exc.value)
    assert "7 bytes" in msg
    assert "8-byte" in msg
    assert "corrupt" in msg or "truncat" in msg


def test_non_numeric_cv_value_error_names_the_term(tmp_path):
    """A non-numeric value on a numeric CV term raises an error naming the term and value,
    not a bare 'could not convert string to float'."""
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=2" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<precursorList count="1"><precursor><selectedIonList count="1"><selectedIon>'
        '<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="not_a_number"/>'
        "</selectedIon></selectedIonList></precursor></precursorList>"
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "badnum.mzML", body)
    with Mzml(path) as r:
        si = r.spectra[0].precursors[0].selected_ions[0]
        with pytest.raises(ValueError) as exc:
            _ = si.selected_ion_mz
        msg = str(exc.value)
        assert "MS:1000744" in msg
        assert "not_a_number" in msg


def test_malformed_base64_error_has_context(tmp_path):
    """Invalid base64 in a <binary> element yields a contextual error, not a raw binascii.Error."""
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="1">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<binaryDataArrayList count="1"><binaryDataArray encodedLength="4">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>'
        '<cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>'
        '<cvParam cvRef="MS" accession="MS:1000514" name="m/z array" value=""/>'
        "<binary>!!!not-base64!!!</binary>"
        "</binaryDataArray></binaryDataArrayList></spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "badb64.mzML", body)
    with Mzml(path) as r:
        with pytest.raises(ValueError, match="base64-decode"):
            _ = r.spectra[0].mz
