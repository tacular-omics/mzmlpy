"""Third adversarial round: precursors/activation, chromatogram data, mismatched arrays, re-iteration."""

import base64
import zlib

from mzmlpy import Mzml

EXAMPLE = "tests/data/example.mzML"
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


def _b64_zlib_f64(values):
    import struct

    raw = b"".join(struct.pack("<d", v) for v in values)
    return base64.b64encode(zlib.compress(raw)).decode()


def _binary_array(values, accession, name):
    encoded = _b64_zlib_f64(values)
    return (
        f'<binaryDataArray encodedLength="{len(encoded)}">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>'
        '<cvParam cvRef="MS" accession="MS:1000574" name="zlib compression" value=""/>'
        f'<cvParam cvRef="MS" accession="{accession}" name="{name}" value=""/>'
        f"<binary>{encoded}</binary></binaryDataArray>"
    )


# ---------------------------------------------------------------- precursor / activation
def test_precursor_full_chain(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=2" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<precursorList count="1"><precursor>'
        '<isolationWindow><cvParam cvRef="MS" accession="MS:1000827" '
        'name="isolation window target m/z" value="500.0"/></isolationWindow>'
        '<selectedIonList count="1"><selectedIon>'
        '<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="500.5"/>'
        '<cvParam cvRef="MS" accession="MS:1000041" name="charge state" value="2"/>'
        "</selectedIon></selectedIonList>"
        '<activation><cvParam cvRef="MS" accession="MS:1000133" '
        'name="collision-induced dissociation" value=""/></activation>'
        "</precursor></precursorList>"
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "prec.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        assert len(s.precursors) == 1
        p = s.precursors[0]
        assert p.isolation_window is not None and p.isolation_window.target_mz == 500.0
        assert len(p.selected_ions) == 1
        assert p.selected_ions[0].selected_ion_mz == 500.5
        assert p.selected_ions[0].charge_state == 2
        assert p.activation is not None


def test_ms1_has_no_precursors(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "ms1.mzML", body)
    with Mzml(path) as r:
        assert s_precursors_empty(r.spectra[0])


def s_precursors_empty(spectrum):
    p = spectrum.precursors
    return p == [] or p is None


def test_precursor_missing_charge_is_none(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=2" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<precursorList count="1"><precursor><selectedIonList count="1"><selectedIon>'
        '<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="500.5"/>'
        "</selectedIon></selectedIonList></precursor></precursorList>"
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "nocharge.mzML", body)
    with Mzml(path) as r:
        si = r.spectra[0].precursors[0].selected_ions[0]
        assert si.selected_ion_mz == 500.5
        assert si.charge_state is None


# ---------------------------------------------------------------- binary arrays
def test_mz_and_intensity_roundtrip(tmp_path):
    mzs = [100.0, 200.5, 300.25]
    intens = [10.0, 20.0, 30.0]
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="3">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<binaryDataArrayList count="2">'
        + _binary_array(mzs, "MS:1000514", "m/z array")
        + _binary_array(intens, "MS:1000515", "intensity array")
        + "</binaryDataArrayList></spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "bin.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        assert list(s.mz) == mzs
        assert list(s.intensity) == intens


def test_mz_without_intensity_array(tmp_path):
    """m/z array present but no intensity array — mz should decode, intensity should be None/empty."""
    mzs = [100.0, 200.0]
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="2">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<binaryDataArrayList count="1">'
        + _binary_array(mzs, "MS:1000514", "m/z array")
        + "</binaryDataArrayList></spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "mzonly.mzML", body)
    with Mzml(path) as r:
        s = r.spectra[0]
        assert list(s.mz) == mzs
        assert s.intensity is None or len(s.intensity) == 0


# ---------------------------------------------------------------- chromatogram binary data
def test_chromatogram_time_intensity(tmp_path):
    times = [0.0, 1.0, 2.0]
    intens = [5.0, 6.0, 7.0]
    body = (
        '<run id="r"><chromatogramList count="1">'
        '<chromatogram index="0" id="tic" defaultArrayLength="3">'
        '<cvParam cvRef="MS" accession="MS:1000235" name="total ion current chromatogram" value=""/>'
        '<binaryDataArrayList count="2">'
        + _binary_array(times, "MS:1000595", "time array")
        + _binary_array(intens, "MS:1000515", "intensity array")
        + "</binaryDataArrayList></chromatogram></chromatogramList></run>"
    )
    path = _write(tmp_path, "chrom.mzML", body)
    with Mzml(path) as r:
        c = r.chromatograms["tic"]
        assert list(c.time) == times
        assert list(c.intensity) == intens


# ---------------------------------------------------------------- iteration robustness
def test_reiteration_is_repeatable():
    with Mzml(EXAMPLE) as r:
        first = [s.id for s in r.spectra]
        second = [s.id for s in r.spectra]
        assert first == second == list(x.id for x in r.spectra)


def test_len_then_iterate_consistent():
    with Mzml(EXAMPLE) as r:
        n = len(r.spectra)
        assert n == sum(1 for _ in r.spectra)
