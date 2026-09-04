"""Second adversarial round: cross-mode consistency, namespace/CV robustness, scan-window units."""

import warnings
from importlib.util import find_spec

import pytest

from mzmlpy import Mzml

EXAMPLE = "tests/data/example.mzML"
EXAMPLE_GZ = "tests/data/example.mzML.gz"

_HEADER = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n'
    '<mzML id="m" version="1.1.0">\n'
)
_FOOTER = "</mzML></indexedmzML>\n"


def _write(tmp_path, name, body, header=_HEADER):
    p = tmp_path / name
    p.write_text(header + body + _FOOTER, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- cross-mode consistency
def _spectra_fingerprint(reader):
    out = []
    for s in reader.spectra:
        mz = s.mz
        out.append((s.id, s.ms_level, s.polarity, None if mz is None else round(float(mz.sum()), 3)))
    return out


def test_all_access_modes_agree():
    """The same data must read identically across in_memory and every gzip_mode."""
    with Mzml(EXAMPLE) as r:
        baseline = _spectra_fingerprint(r)

    variants = [
        Mzml(EXAMPLE, in_memory=False),
        Mzml(EXAMPLE_GZ, gzip_mode="extract"),
        Mzml(EXAMPLE_GZ, gzip_mode="extract", in_memory=False),
        Mzml(EXAMPLE_GZ, gzip_mode="stream", in_memory=False),
    ]
    if find_spec("rapidgzip") is not None:
        variants.append(Mzml(EXAMPLE_GZ, gzip_mode="indexed", in_memory=False))
    for r in variants:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # stream mode warns on random access
            with r:
                assert _spectra_fingerprint(r) == baseline


# ---------------------------------------------------------------- namespace robustness
def test_mzml_without_namespace(tmp_path):
    """A file with no default xmlns should still parse (ns == '')."""
    header = '<?xml version="1.0" encoding="utf-8"?>\n<indexedmzML><mzML id="m" version="1.1.0">\n'
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<cvParam cvRef="MS" accession="MS:1000129" name="negative scan" value=""/>'
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "nons.mzML", body, header=header)
    with Mzml(path) as r:
        s = r.spectra[0]
        assert s.ms_level == 2
        assert s.polarity == "negative"


# ---------------------------------------------------------------- malformed CV params
def test_cvparam_missing_name_does_not_crash_unrelated_access(tmp_path):
    """A cvParam missing its (schema-required) name should not blow up unrelated properties."""
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<cvParam cvRef="MS" accession="MS:9999999" value="orphan"/>'  # no name attr
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "badcv.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        # Accessing ms_level touches cv_params, which parses every cvParam including the bad one.
        assert s.ms_level == 1


# ---------------------------------------------------------------- scan window units
def test_scan_window_with_unit_accession_only(tmp_path):
    """Scan window limits should resolve when only unitAccession (MS:1000040) is given, not unitName."""
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<scanList count="1"><scan><scanWindowList count="1"><scanWindow>'
        '<cvParam cvRef="MS" accession="MS:1000501" name="scan window lower limit" value="100.0" '
        'unitCvRef="MS" unitAccession="MS:1000040"/>'
        '<cvParam cvRef="MS" accession="MS:1000500" name="scan window upper limit" value="1500.0" '
        'unitCvRef="MS" unitAccession="MS:1000040"/>'
        "</scanWindow></scanWindowList></scan></scanList>"
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "unitacc.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        assert s.lower_mz == 100.0
        assert s.upper_mz == 1500.0


# ---------------------------------------------------------------- multiple scans
def test_multiple_scans_warns_and_returns_first(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<scanList count="2">'
        '<scan><cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="1.0" '
        'unitCvRef="UO" unitAccession="UO:0000010" unitName="second"/></scan>'
        '<scan><cvParam cvRef="MS" accession="MS:1000016" name="scan start time" value="2.0" '
        'unitCvRef="UO" unitAccession="UO:0000010" unitName="second"/></scan>'
        "</scanList></spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "multiscan.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        with pytest.warns(UserWarning, match="multiple scans"):
            t = s.scan_start_time
        assert t.total_seconds() == 1.0  # first scan


# ---------------------------------------------------------------- mz without intensity
def test_build_index_from_scratch_matches_default():
    with Mzml(EXAMPLE) as a, Mzml(EXAMPLE, build_index_from_scratch=True) as b:
        assert [s.id for s in a.spectra] == [s.id for s in b.spectra]
        assert [s.ms_level for s in a.spectra] == [s.ms_level for s in b.spectra]
