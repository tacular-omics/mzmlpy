import pytest

from mzmlpy import Mzml

GZ_FILE = "tests/data/example.mzML.gz"
MZML_FILE = "tests/data/example.mzML"


@pytest.fixture()
def indexed_reader():
    return Mzml(GZ_FILE, gzip_mode="indexed", in_memory=False)


@pytest.fixture()
def reference_reader():
    return Mzml(MZML_FILE)


def test_spectrum_ids(indexed_reader, reference_reader):
    assert indexed_reader._file_object.spectrum_ids == reference_reader._file_object.spectrum_ids


def test_chromatogram_ids(indexed_reader, reference_reader):
    assert indexed_reader._file_object.chromatogram_ids == reference_reader._file_object.chromatogram_ids


def test_spectrum_count(indexed_reader, reference_reader):
    assert len(indexed_reader.spectra) == len(reference_reader.spectra)


def test_chromatogram_count(indexed_reader, reference_reader):
    assert len(indexed_reader.chromatograms) == len(reference_reader.chromatograms)


def test_get_spectrum_by_index(indexed_reader, reference_reader):
    for i in range(len(reference_reader.spectra)):
        s_idx = indexed_reader.spectra[i]
        s_ref = reference_reader.spectra[i]
        assert s_idx.id == s_ref.id
        assert s_idx.ms_level == s_ref.ms_level
        assert s_idx.TIC == s_ref.TIC


def test_get_spectrum_by_id(indexed_reader, reference_reader):
    for sid in reference_reader._file_object.spectrum_ids:
        s_idx = indexed_reader.spectra[sid]
        s_ref = reference_reader.spectra[sid]
        assert s_idx.id == s_ref.id
        assert s_idx.ms_level == s_ref.ms_level


def test_get_chromatogram_by_id(indexed_reader):
    tic = indexed_reader.chromatograms["tic"]
    assert tic.id == "tic"


def test_spectrum_slicing(indexed_reader, reference_reader):
    sliced = indexed_reader.spectra[0:2]
    ref_sliced = reference_reader.spectra[0:2]
    assert len(sliced) == len(ref_sliced)
    for s_idx, s_ref in zip(sliced, ref_sliced, strict=True):
        assert s_idx.id == s_ref.id


def test_iteration(indexed_reader, reference_reader):
    idx_ids = [s.id for s in indexed_reader.spectra]
    ref_ids = [s.id for s in reference_reader.spectra]
    assert idx_ids == ref_ids
