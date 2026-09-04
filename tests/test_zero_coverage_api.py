"""Tests for public API surfaces flagged with zero coverage in a prior audit.

Covers: `_ParamGroup.has_ref_param`/`get_ref_param`/`has_user_param`, `Contact` fields beyond
`.name`, `SourceFile.checksum`/`.checksum_type`, `Mzml(extract_dir=...)`, `clear_cache()`, and
`cv_int`'s non-integer error path.
"""

from pathlib import Path

import pytest

from mzmlpy import Mzml, clear_cache

EXAMPLE = "tests/data/example.mzML"


# --------------------------------------------------------------------------------------------
# _ParamGroup.has_ref_param / get_ref_param / has_user_param
# --------------------------------------------------------------------------------------------


def test_has_ref_param_true_for_present_ref() -> None:
    """example.mzML's third spectrum (index 2, scan=21) pulls its MS1 terms via a
    referenceableParamGroupRef to 'CommonMS1SpectrumParams'."""
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[2]
        assert spectrum.has_ref_param("CommonMS1SpectrumParams") is True


def test_has_ref_param_false_for_absent_ref() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[2]
        assert spectrum.has_ref_param("NotARealGroup") is False


def test_get_ref_param_returns_matching_ref() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[2]
        ref = spectrum.get_ref_param("CommonMS1SpectrumParams")
        assert ref is not None
        assert ref.ref == "CommonMS1SpectrumParams"


def test_get_ref_param_returns_none_when_absent() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[2]
        assert spectrum.get_ref_param("NotARealGroup") is None


def test_has_user_param_true_for_present_param() -> None:
    """Spectrum index 2 carries `<userParam name="example" .../>`."""
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[2]
        assert spectrum.has_user_param("example") is True


def test_has_user_param_false_for_absent_param() -> None:
    with Mzml(EXAMPLE) as reader:
        spectrum = reader.spectra[2]
        assert spectrum.has_user_param("not-a-real-param") is False


# --------------------------------------------------------------------------------------------
# Contact fields beyond .name
# --------------------------------------------------------------------------------------------


def test_contact_fields_present_in_fixture() -> None:
    with Mzml(EXAMPLE) as reader:
        fd = reader.file_description
        assert fd is not None
        contact = fd.contact[0]
        assert contact.name == "William Pennington"
        assert contact.organization == "Higglesworth University"
        assert contact.address == "12 Higglesworth Avenue, 12045, HI, USA"
        assert contact.url == "http://www.higglesworth.edu/"
        assert contact.email == "wpennington@higglesworth.edu"


def test_contact_fields_absent_from_fixture_return_none() -> None:
    """The example fixture's contact has no phone/fax/role terms; those accessors must return
    None rather than raising when the underlying cvParam is simply absent."""
    with Mzml(EXAMPLE) as reader:
        fd = reader.file_description
        assert fd is not None
        contact = fd.contact[0]
        assert contact.phone_number is None
        assert contact.toll_free_phone_number is None
        assert contact.fax_number is None
        assert contact.role is None


# --------------------------------------------------------------------------------------------
# SourceFile.checksum / .checksum_type
# --------------------------------------------------------------------------------------------


def test_source_file_checksum_and_type() -> None:
    """example.mzML's first source file carries an MS:1000569 (SHA-1) checksum."""
    with Mzml(EXAMPLE) as reader:
        fd = reader.file_description
        assert fd is not None
        source_file = fd.source_files[0]
        assert source_file.checksum_type == "SHA1"
        assert source_file.checksum == "1234567890123456789012345678901234567890"


def test_source_file_checksums_differ_across_files() -> None:
    with Mzml(EXAMPLE) as reader:
        fd = reader.file_description
        assert fd is not None
        checksums = [sf.checksum for sf in fd.source_files if sf.checksum is not None]
        assert len(checksums) >= 2
        assert len(set(checksums)) == len(checksums)  # each source file's checksum is distinct


# --------------------------------------------------------------------------------------------
# Mzml(extract_dir=...)
# --------------------------------------------------------------------------------------------


def test_extract_dir_places_extracted_file_and_reads_correctly(tmp_path: Path) -> None:
    with Mzml("tests/data/example.mzML.gz", gzip_mode="extract", in_memory=False, extract_dir=tmp_path) as reader:
        extracted = Path(reader._file_object.file_handler.path)
        assert extracted.parent == tmp_path
        assert extracted.exists()
        assert len(reader.spectra) == 4
        assert reader.spectra[0].id == "scan=19"


# --------------------------------------------------------------------------------------------
# clear_cache()
# --------------------------------------------------------------------------------------------


def test_clear_cache_runs_without_error() -> None:
    clear_cache()  # must not raise even if nothing has been cached yet


def test_clear_cache_removes_default_gz_extraction() -> None:
    """Extracting with the default (no extract_dir) cache location, then clearing it, must
    remove the extracted file from the default temp cache directory."""
    import tempfile

    reader = Mzml("tests/data/example.mzML.gz", gzip_mode="extract", in_memory=False)
    cached_path = Path(reader._file_object.file_handler.path)
    reader.close()

    assert str(cached_path).startswith(str(Path(tempfile.gettempdir()) / "mzmlpy"))
    assert cached_path.exists()

    clear_cache()

    assert not cached_path.exists()


# --------------------------------------------------------------------------------------------
# cv_int non-integer actionable error path (mirrors the cv_float case in test_diagnostics.py)
# --------------------------------------------------------------------------------------------


def test_non_integer_cv_value_error_names_the_term(tmp_path: Path) -> None:
    """A non-integer value on an integer-typed CV term (ms level) raises an error naming the
    term and the bad value, not a bare 'invalid literal for int()'."""
    header = (
        '<?xml version="1.0" encoding="utf-8"?>\n<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n'
        '<mzML id="m" version="1.1.0">\n'
    )
    footer = "</mzML></indexedmzML>\n"
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="not_an_int"/>'
        "</spectrum></spectrumList></run>"
    )
    path = tmp_path / "badint.mzML"
    path.write_text(header + body + footer, encoding="utf-8")

    with Mzml(str(path)) as reader:
        with pytest.raises(ValueError) as exc:
            _ = reader.spectra[0].ms_level
        msg = str(exc.value)
        assert "MS:1000511" in msg
        assert "not_an_int" in msg
