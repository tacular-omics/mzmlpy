"""Tests targeting previously low-coverage areas: stream gzip mode, metadata elements,
ion-mobility/FAIMS/product accessors, and decoder encode round-trips."""

import warnings

import numpy as np
import pytest

from mzmlpy import Mzml

EXAMPLE = "tests/data/example.mzML"
EXAMPLE_GZ = "tests/data/example.mzML.gz"
_HEADER = '<?xml version="1.0" encoding="utf-8"?>\n<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">\n<mzML id="m" version="1.1.0">\n'
_FOOTER = "</mzML></indexedmzML>\n"


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(_HEADER + body + _FOOTER, encoding="utf-8")
    return str(p)


# ------------------------------------------------------------------ stream gzip mode
def test_stream_mode_full_api():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # stream warns on random access
        with Mzml(EXAMPLE_GZ, gzip_mode="stream", in_memory=False) as r, Mzml(EXAMPLE) as ref:
            ref_ids = [s.id for s in ref.spectra]
            assert [s.id for s in r.spectra] == ref_ids  # iteration
            assert r.spectra["scan=19"].id == "scan=19"  # by id
            assert r.spectra[1].id == ref_ids[1]  # by index
            assert len(r.spectra) == len(ref_ids)  # count via full scan
            assert "scan=19" in r.spectra
            assert "missing" not in r.spectra
            assert [s.id for s in r.spectra[0:2]] == ref_ids[0:2]  # slice
            assert r.chromatograms["tic"].id == "tic"  # chromatogram by id
            assert r.chromatograms[0].id == r.chromatograms.__iter__().__next__().id
            assert r.TIC is not None


def test_stream_mode_unknown_id_raises():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with Mzml(EXAMPLE_GZ, gzip_mode="stream", in_memory=False) as r:
            with pytest.raises(KeyError):
                _ = r.spectra["does-not-exist"]
            with pytest.raises(IndexError):
                _ = r.spectra[999]


# ------------------------------------------------------------------ FileDescription / Run
def test_file_description_metadata():
    with Mzml(EXAMPLE) as r:
        fd = r.file_description
        assert fd is not None
        assert len(fd.source_files) == 3
        names = [sf.name for sf in fd.source_files]
        assert "tiny1.yep" in names
        sf0 = fd.source_files[0]
        assert sf0.location == "file://F:/data/Exp01"
        _ = sf0.checksum, sf0.checksum_type  # exercise (may be None)
        assert fd.get_source_file(sf0.id) is not None
        assert fd.get_source_file("nope") is None
        assert fd.file_content is not None
        assert [c.name for c in fd.contact] == ["William Pennington"]


def test_run_metadata():
    with Mzml(EXAMPLE) as r:
        run = r.run
        assert run is not None
        assert run.default_instrument_configuration_ref is not None
        assert run.default_source_file_ref == "tiny1.yep"
        assert run.sample_ref is not None
        ts = run.start_time_stamp
        assert ts is not None and ts.year == 2007


def test_instrument_configuration_and_scan_settings():
    with Mzml(EXAMPLE) as r:
        assert isinstance(r.instrument_configurations, dict)
        assert isinstance(r.scan_settings, dict)
        assert isinstance(r.data_processes, dict)


# ------------------------------------------------------------------ ion mobility / FAIMS / ccs / products
def test_ion_mobility_faims_ccs_and_products(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">\n'
        '<spectrum index="0" id="scan=2" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<precursorList count="1"><precursor><selectedIonList count="1"><selectedIon>'
        '<cvParam cvRef="MS" accession="MS:1000744" name="selected ion m/z" value="500.5"/>'
        '<cvParam cvRef="MS" accession="MS:1000042" name="peak intensity" value="1234.0"/>'
        '<cvParam cvRef="MS" accession="MS:1002815" name="inverse reduced ion mobility" value="0.85"/>'
        '<cvParam cvRef="MS" accession="MS:1002476" name="ion mobility drift time" value="12.3"/>'
        '<cvParam cvRef="MS" accession="MS:1003450" name="FAIMS compensation voltage" value="-45.0"/>'
        '<cvParam cvRef="MS" accession="MS:1003451" name="FAIMS voltage" value="-50.0"/>'
        '<cvParam cvRef="MS" accession="MS:1002954" name="collisional cross sectional area" value="350.0"/>'
        "</selectedIon></selectedIonList></precursor></precursorList>"
        '<productList count="1"><product><isolationWindow>'
        '<cvParam cvRef="MS" accession="MS:1000827" name="isolation window target m/z" value="250.0"/>'
        "</isolationWindow></product></productList>"
        "</spectrum></spectrumList></run>"
    )
    path = _write(tmp_path, "im.mzML", body)
    with Mzml(path) as r:
        ion = r.spectra[0].precursors[0].selected_ions[0]
        assert ion.peak_intensity == 1234.0
        assert ion.ir_im == 0.85
        assert ion.im_drift_time == 12.3
        assert ion.faims_voltage_start == -45.0
        assert ion.faims_voltage_end == -50.0
        assert ion.ccs == 350.0
        products = r.spectra[0].products
        assert len(products) == 1
        assert products[0].isolation_window.target_mz == 250.0


# ------------------------------------------------------------------ decoder encode round-trips
def test_scan_level_ion_mobility_bruker():
    """timsTOF PASEF MS2 stores ion mobility as a scan cvParam (MS:1002815), not a binary array.
    has_im and ion_mobility must reflect it (has_im previously returned False for such spectra)."""
    with Mzml("tests/data/bruker_ms2_im.mzML") as r:
        s = r.spectra[0]
        assert s.has_im is True
        assert s.ion_mobility == 1.595546371847
        assert s.scans[0].inverse_reduced_ion_mobility == 1.595546371847
        assert s.scans[0].ion_mobility_drift_time is None


def test_numpress_encode_decode_roundtrip():
    """encode_* previously crashed (missing fixed-point arg); verify each round-trips within the
    precision its encoding provides (linear ~exact, pic integer-only, slof low-precision)."""
    pytest.importorskip("pynumpress")
    from mzmlpy.decoder import MSDecoder

    mz = [100.0, 200.5, 300.25, 400.125]
    counts = [1.0, 500.0, 12345.0, 42.0]

    lin = MSDecoder.decode_linear(bytes(MSDecoder.encode_linear(mz)))
    assert np.allclose(lin, mz, rtol=1e-4)

    pic = MSDecoder.decode_pic(bytes(MSDecoder.encode_pic(counts)))
    assert np.allclose(pic, counts, atol=1.0)  # positive-integer encoding

    slof = MSDecoder.decode_slof(bytes(MSDecoder.encode_slof(mz)))
    assert np.allclose(slof, mz, rtol=1e-2)  # short-logged-float, ~3 sig figs


def test_zlib_encode_decode_roundtrip():
    from mzmlpy.decoder import MSDecoder

    raw = b"hello mzml" * 100
    assert MSDecoder.decode_zlib(MSDecoder.encode_zlib(raw)) == raw
