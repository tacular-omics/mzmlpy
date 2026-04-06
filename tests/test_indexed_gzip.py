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


def test_cached_index_reuse(reference_reader):
    """Opening the same file twice should use cached .gzidx and .mzidx on the second open."""
    import os

    gzidx_path = GZ_FILE + "idx"
    mzidx_path = GZ_FILE.removesuffix(".gz") + "idx"

    # Clean up any leftover index files
    for p in (gzidx_path, mzidx_path):
        if os.path.exists(p):
            os.unlink(p)

    # First open — builds and saves both indices
    r1 = Mzml(GZ_FILE, gzip_mode="indexed", in_memory=False)
    assert os.path.exists(gzidx_path)
    assert os.path.exists(mzidx_path)
    gzidx_mtime = os.path.getmtime(gzidx_path)
    mzidx_mtime = os.path.getmtime(mzidx_path)

    # Second open — should load from cache (no rebuild)
    r2 = Mzml(GZ_FILE, gzip_mode="indexed", in_memory=False)
    assert os.path.getmtime(gzidx_path) == gzidx_mtime
    assert os.path.getmtime(mzidx_path) == mzidx_mtime

    # Verify correctness from cached index
    for i in range(len(reference_reader.spectra)):
        assert r2.spectra[i].id == reference_reader.spectra[i].id

    # Clean up
    for p in (gzidx_path, mzidx_path):
        os.unlink(p)
