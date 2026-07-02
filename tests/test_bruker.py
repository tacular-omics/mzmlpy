from datetime import timedelta

import numpy as np
import pytest

from mzmlpy import Mzml
from mzmlpy.constants import BinaryDataArrayAccession, CollisionDissociationTypeAccession

BRUKER_IM = "tests/data/bruker_ms2_im.mzML"
BRUKER_COMBINED_IM = "tests/data/bruker_ms2_im_combined_im.mzML"
BRUKER_FILES = [BRUKER_IM, BRUKER_COMBINED_IM]


@pytest.mark.parametrize("filename", BRUKER_FILES)
def test_bruker_im_spectra(filename):
    reader = Mzml(filename)
    assert len(reader.spectra) == 10
    assert len(reader.chromatograms) == 5

    s = reader.spectra[0]
    assert s.ms_level == 2
    assert s.polarity == "positive"
    assert s.spectrum_type == "centroid"
    assert s.TIC == 3186.0


def test_bruker_im_empty_spectra():
    reader = Mzml(BRUKER_IM)
    s = reader.spectra[0]

    assert s.default_array_length == 0
    assert s.mz is not None
    assert len(s.mz) == 0
    assert s.intensity is not None
    assert len(s.intensity) == 0
    # This timsTOF PASEF MS2 spectrum has ion mobility as a scan-level cvParam (MS:1002815),
    # so has_im is True even though there is no ion-mobility binary array.
    assert s.has_im is True
    assert s.ion_mobility == 1.595546371847


def test_bruker_im_scan_metadata():
    reader = Mzml(BRUKER_IM)
    s = reader.spectra[0]

    assert s.is_single_scan is True
    assert s.spectra_combination == "no_combination"
    assert s.scan_start_time == timedelta(seconds=124.958506)
    assert s.lower_mz == 100.0
    assert s.upper_mz == 1700.0

    # Ion mobility stored as cvParam in the scan element
    scan = s.scans[0]
    im_cv = scan.get_cvparm("MS:1002815")
    assert im_cv is not None
    assert im_cv.name == "inverse reduced ion mobility"
    assert im_cv.value is not None
    assert float(im_cv.value) == pytest.approx(1.595546371847)


def test_bruker_combined_im_binary_data():
    reader = Mzml(BRUKER_COMBINED_IM)
    s = reader.spectra[0]

    assert s.default_array_length == 113
    assert s.mz is not None
    assert len(s.mz) == 113
    assert s.intensity is not None
    assert len(s.intensity) == 113

    np.testing.assert_allclose(s.mz[:3], [544.25124415, 286.9327726, 393.20848807], rtol=1e-6)
    np.testing.assert_allclose(s.intensity[:3], [49.0, 22.0, 67.0], rtol=1e-6)

    # Ion mobility binary array
    assert s.has_im is True
    assert BinaryDataArrayAccession.MEAN_INVERSE_REDUCED_ION_MOBILITY in s.im_types

    im_array = s.get_binary_array(BinaryDataArrayAccession.MEAN_INVERSE_REDUCED_ION_MOBILITY)
    assert im_array is not None
    im_data = im_array.data
    assert len(im_data) == 113
    np.testing.assert_allclose(im_data[:3], [0.89429618, 0.8920917, 0.8920917], rtol=1e-5)


def test_bruker_combined_im_multi_scan():
    reader = Mzml(BRUKER_COMBINED_IM)
    s = reader.spectra[0]

    assert s.is_single_scan is False
    assert s.spectra_combination == "sum"
    assert len(s.scans) == 25

    # scan_start_time warns about multiple scans but still returns first scan's value
    with pytest.warns(UserWarning, match="multiple scans"):
        scan_time = s.scan_start_time
    assert scan_time == timedelta(seconds=124.958506)

    # User params for ion mobility range
    user_param_names = [up.name for up in s.user_params]
    assert "ion mobility lower limit" in user_param_names
    assert "ion mobility upper limit" in user_param_names


def test_bruker_combined_im_precursors():
    reader = Mzml(BRUKER_COMBINED_IM)
    s = reader.spectra[0]

    assert s.has_precursors is True
    precursor = s.precursors[0]

    # Isolation window
    iso = precursor.isolation_window
    assert iso is not None
    assert iso.target_mz == pytest.approx(577.050745983777, rel=1e-6)
    assert iso.lower_offset == 1.0
    assert iso.upper_offset == 1.0

    # Selected ion
    si = precursor.selected_ions[0]
    assert si.selected_ion_mz == pytest.approx(576.762738803541, rel=1e-6)
    assert si.charge_state == 2
    assert si.peak_intensity == 2614.0
    assert si.ccs == pytest.approx(356.922244927527, rel=1e-6)

    # Activation
    act = precursor.activation
    assert act is not None
    assert act.activation_type == CollisionDissociationTypeAccession.COLLISION_INDUCED_DISSOCIATION
    assert act.ce == pytest.approx(30.617136659436, rel=1e-4)


@pytest.mark.parametrize("filename", BRUKER_FILES)
def test_bruker_chromatograms(filename):
    reader = Mzml(filename)

    expected_ids = ["TIC", "BPC", "BPC,±MS", "TIC,±AllMS/MS", "TIC,±MS"]
    for cid in expected_ids:
        chrom = reader.chromatograms[cid]
        assert chrom.id == cid

    tic = reader.chromatograms["TIC"]
    assert tic.default_array_length == 143403


@pytest.mark.parametrize("filename", BRUKER_FILES)
def test_bruker_metadata(filename):
    reader = Mzml(filename)

    # Source files
    assert reader.file_description is not None
    src_files = reader.file_description.source_files
    assert len(src_files) == 2
    src_names = {sf.name for sf in src_files}
    assert "Analysis.tdf" in src_names
    assert "Analysis.tdf_bin" in src_names
    for sf in src_files:
        assert sf.has_cvparm("MS:1002817")  # Bruker TDF format

    # Software
    assert len(reader.softwares) == 3

    # Instrument configuration
    ic_list = list(reader.instrument_configurations.values())
    assert len(ic_list) == 1
    ic = ic_list[0]
    assert len(ic.source_components) == 1
    assert len(ic.analyzer_components) == 2
    assert len(ic.detector_components) == 2

    # Referenceable param group for timsTOF
    ref_groups = reader.referenceable_param_groups
    assert len(ref_groups) == 1
    assert "CommonInstrumentParams" in ref_groups
    assert ref_groups["CommonInstrumentParams"].has_cvparm("MS:1003123")


def test_bruker_id_regex():
    # Per-scan ID format: frame=1016 scan=N
    reader = Mzml(BRUKER_IM, spectrum_id_regex=r"scan=(\d+)")
    s = reader.spectra["1"]
    assert s.id == "frame=1016 scan=1"
    assert "1" in reader.spectra

    # Combined IM ID format: merged=N frame=... scanStart=... scanEnd=...
    reader2 = Mzml(BRUKER_COMBINED_IM, spectrum_id_regex=r"merged=(\d+)")
    s2 = reader2.spectra["1015"]
    assert "merged=1015" in s2.id
