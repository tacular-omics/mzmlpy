"""Adversarial / edge-case tests. Each encodes the *correct* expected behavior — a failure here
surfaces a real bug rather than a broken test."""

import pytest

from mzmlpy import Mzml

EXAMPLE = "tests/data/example.mzML"

_HEADER = '<?xml version="1.0" encoding="utf-8"?>\n<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n<mzML id="m" version="1.1.0">\n'
_FOOTER = "</mzML></indexedmzML>\n"


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(_HEADER + body + _FOOTER, encoding="utf-8")
    return str(p)


# --------------------------------------------------------------------- missing / bad files
def test_missing_file_raises_not_silent(tmp_path):
    with pytest.raises((FileNotFoundError, OSError)):
        Mzml(str(tmp_path / "does_not_exist.mzML"))


def test_truncated_xml_is_an_error_not_hang(tmp_path):
    # A spectrum whose closing tag never arrives before EOF.
    p = tmp_path / "trunc.mzML"
    p.write_text(_HEADER + '<run id="r"><spectrumList count="1">\n<spectrum index="0" id="scan=1" defaultArrayLength="0"><cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>', encoding="utf-8")
    with Mzml(str(p), in_memory=False) as r:
        with pytest.raises(Exception):
            _ = r.spectra["scan=1"]


# --------------------------------------------------------------------- empty / single-kind files
def test_empty_spectrum_list_reports_zero(tmp_path):
    path = _write(tmp_path, "empty.mzML", '<run id="r"><spectrumList count="0"></spectrumList></run>')
    with Mzml(path) as r:
        assert len(r.spectra) == 0
        assert list(r.spectra) == []
        assert not r.spectra  # falsy when empty


def test_chromatogram_only_file(tmp_path):
    body = (
        '<run id="r"><chromatogramList count="1">\n'
        '<chromatogram index="0" id="tic" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000235" name="total ion current chromatogram" value=""/>'
        "</chromatogram></chromatogramList></run>"
    )
    path = _write(tmp_path, "chrom_only.mzML", body)
    with Mzml(path) as r:
        assert len(r.spectra) == 0
        assert len(r.chromatograms) == 1
        assert r.TIC is not None and r.TIC.id == "tic"


# --------------------------------------------------------------------- indexing / slicing
def test_index_out_of_range_raises():
    with Mzml(EXAMPLE) as r:
        with pytest.raises(IndexError):
            _ = r.spectra[999]


def test_large_negative_index_raises():
    with Mzml(EXAMPLE) as r:
        with pytest.raises(IndexError):
            _ = r.spectra[-999]


def test_slices():
    with Mzml(EXAMPLE) as r:
        n = len(r.spectra)
        assert len(r.spectra[:]) == n
        assert len(r.spectra[1:3]) == 2
        assert r.spectra[5:5] == []
        # reverse slice
        rev = r.spectra[::-1]
        assert [s.id for s in rev] == [s.id for s in r.spectra][::-1]
        # negative-bounded slice
        assert [s.id for s in r.spectra[-2:]] == [s.id for s in r.spectra][-2:]


def test_contains_and_unknown_id():
    with Mzml(EXAMPLE) as r:
        assert "scan=19" in r.spectra
        assert "nope" not in r.spectra
        with pytest.raises(KeyError):
            _ = r.spectra["nope"]


# --------------------------------------------------------------------- lifecycle
def test_double_close_is_safe():
    r = Mzml(EXAMPLE)
    r.close()
    r.close()  # must not raise


def test_reopen_same_file_consistent():
    with Mzml(EXAMPLE) as a, Mzml(EXAMPLE) as b:
        assert [s.id for s in a.spectra] == [s.id for s in b.spectra]


# --------------------------------------------------------------------- structural oddities
def test_spectrum_without_binary_arrays(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "nobin.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        assert s.ms_level == 1
        assert s.mz is None or len(s.mz) == 0


def test_empty_scan_and_precursor_lists(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<scanList count="0"></scanList>'
        '<precursorList count="0"></precursorList>'
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "emptylists.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        assert s.scan_start_time is None
        assert s.precursors == [] or s.precursors is None


def test_duplicate_spectrum_ids(tmp_path):
    body = (
        '<run id="r"><spectrumList count="2">\n'
        '<spectrum index="0" id="dup" defaultArrayLength="0"><cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/></spectrum>\n'
        '<spectrum index="1" id="dup" defaultArrayLength="0"><cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/></spectrum>\n'
        "</spectrumList></run>"
    )
    path = _write(tmp_path, "dupids.mzML", body)
    with Mzml(path) as r:
        # Iteration should still see both; count should reflect both.
        levels = [s.ms_level for s in r.spectra]
        assert len(levels) == 2


# --------------------------------------------------------------------- id_regex edge cases
def test_id_regex_no_capture_group():
    # Pattern with no capture group -> full match is the key.
    with Mzml(EXAMPLE, spectrum_id_regex=r"scan=\d+") as r:
        assert r.spectra["scan=19"].id == "scan=19"


def test_id_regex_no_match_falls_through():
    with Mzml(EXAMPLE, spectrum_id_regex=r"cycle=(\d+)") as r:
        # Native id still works even if regex matches nothing useful for most.
        assert r.spectra["scan=19"].id == "scan=19"


# --------------------------------------------------------------------- numeric / polarity
def test_negative_polarity(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<cvParam cvRef="MS" accession="MS:1000129" name="negative scan" value=""/>'
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "neg.mzML", body)
    with Mzml(path) as r:
        assert r.spectra[0].polarity == "negative"
