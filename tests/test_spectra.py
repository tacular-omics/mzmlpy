import pytest

from mzmlpy import Mzml


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_spectra(filename):
    reader = Mzml(filename, build_index_from_scratch=False)

    assert len(reader.spectra) == 4

    # Spectrum 0 (index 0, scan=19)
    s1 = reader.spectra[0]
    assert s1.id == "scan=19"
    assert s1.ms_level == 1
    assert s1.polarity is None
    assert s1.spectrum_type == "centroid"
    assert s1.TIC == 16675500.0

    # Check Scan List
    assert len(s1.scans) == 1
    scan = s1.scans[0]
    assert scan.scan_start_time.total_seconds() == 5.8905 * 60  # minutes to seconds
    assert len(scan.scan_windows) == 1
    assert scan.scan_windows[0].lower_limit == 400.0
    assert scan.scan_windows[0].upper_limit == 1800.0

    # Check Binary Data
    assert s1.mz is not None
    assert s1.intensity is not None
    assert len(s1.mz) == 15
    assert len(s1.intensity) == 15

    # Spectrum 1 (index 1, scan=20)
    s2 = reader.spectra[1]
    assert s2.id == "scan=20"
    assert s2.ms_level == 2
    assert s2.spectrum_type == "profile"

    # Check Precursor
    assert len(s2.precursors) == 1
    precursor = s2.precursors[0]
    assert precursor.spectrum_ref == "scan=19"

    # Isolation Window
    assert precursor.isolation_window.target_mz == 445.3
    assert precursor.isolation_window.lower_offset == 0.5
    assert precursor.isolation_window.upper_offset == 0.5

    # Selected Ion
    assert len(precursor.selected_ions) == 1
    sel_ion = precursor.selected_ions[0]
    assert sel_ion.selected_ion_mz == 445.34
    assert sel_ion.peak_intensity == 120053.0
    assert sel_ion.charge_state == 2

    # Activation
    assert precursor.activation.ce == 35.0
    assert precursor.activation.get_cvparm("MS:1000133") is not None  # CID

    # Spectrum 2 - No binary data
    s3 = reader.spectra[2]
    assert s3.default_array_length == 0
    with pytest.warns(UserWarning):
        assert len(s3.mz) == 0

    # Spectrum 3 - Different SpotID
    s4 = reader.spectra[3]
    assert s4.spot_id == "A1,42x42,4242x4242"
    assert s4.source_file_ref == "tiny.wiff"
