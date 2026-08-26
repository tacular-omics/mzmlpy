import shutil
from pathlib import Path

import pytest

from mzmlpy import AccessStrategy, Mzml

MZML_FILE = Path("tests/data/example.mzML")
GZ_FILE = Path("tests/data/example.mzML.gz")


def _gzip_copy(tmp_path: Path) -> Path:
    path = tmp_path / "example.mzML.gz"
    shutil.copyfile(GZ_FILE, path)
    return path


def test_access_strategy_reports_memory_and_plain() -> None:
    with Mzml(MZML_FILE) as memory_reader:
        assert memory_reader.access_strategy is AccessStrategy.MEMORY
        assert memory_reader.access_strategy == "memory"
    with Mzml(MZML_FILE, in_memory=False) as plain_reader:
        assert plain_reader.access_strategy is AccessStrategy.PLAIN


def test_explicit_gzip_strategies_are_observable(tmp_path: Path) -> None:
    path = _gzip_copy(tmp_path)
    with Mzml(path, gzip_mode="stream", in_memory=False) as stream_reader:
        assert stream_reader.access_strategy is AccessStrategy.STREAM
    with Mzml(path, gzip_mode="extract", in_memory=False, extract_dir=tmp_path / "extract") as extracted_reader:
        assert extracted_reader.access_strategy is AccessStrategy.EXTRACTED


def test_auto_extracts_without_creating_adjacent_sidecars(tmp_path: Path) -> None:
    path = _gzip_copy(tmp_path)
    with Mzml(path, gzip_mode="auto", in_memory=False, extract_dir=tmp_path / "extract") as reader:
        assert reader.access_strategy is AccessStrategy.EXTRACTED
        assert reader.spectra[0].id == "scan=19"

    assert not Path(f"{path}idx").exists()
    assert not path.with_suffix("").with_suffix(".mzMLidx").exists()


def test_auto_reuses_complete_rapidgzip_sidecars(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    path = _gzip_copy(tmp_path)
    with Mzml(path, gzip_mode="indexed", in_memory=False):
        pass

    with Mzml(path, gzip_mode="auto", in_memory=False, extract_dir=tmp_path / "unused") as reader:
        assert reader.access_strategy is AccessStrategy.RAPIDGZIP
        assert reader.spectra[1].id == "scan=20"


def test_auto_prefers_a_current_extraction_over_sidecars(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    path = _gzip_copy(tmp_path)
    extract_dir = tmp_path / "extract"
    with Mzml(path, gzip_mode="auto", in_memory=False, extract_dir=extract_dir):
        pass
    with Mzml(path, gzip_mode="indexed", in_memory=False):
        pass

    with Mzml(path, gzip_mode="auto", in_memory=False, extract_dir=extract_dir) as reader:
        assert reader.access_strategy is AccessStrategy.EXTRACTED


def test_invalid_gzip_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported gzip_mode"):
        Mzml(MZML_FILE, gzip_mode="invalid")  # type: ignore[arg-type]
