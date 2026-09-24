import logging
import os
import shutil
from pathlib import Path

import pytest

from mzmlpy import AccessStrategy, Mzml, MzmlError, file_interface, write_indexed_gzip

MZML_FILE = Path("tests/data/example.mzML")
GZ_FILE = Path("tests/data/example.mzML.gz")


def _gzip_copy(tmp_path: Path) -> Path:
    path = tmp_path / "example.mzML.gz"
    shutil.copyfile(GZ_FILE, path)
    return path


def test_access_strategy_reports_memory_and_plain() -> None:
    with Mzml(MZML_FILE, in_memory=True) as memory_reader:
        assert memory_reader.access_strategy is AccessStrategy.MEMORY
        assert memory_reader.access_strategy == "memory"
    with Mzml(MZML_FILE, in_memory=False) as plain_reader:
        assert plain_reader.access_strategy is AccessStrategy.PLAIN
    with Mzml(MZML_FILE) as default_reader:  # in_memory=False is the default since 0.10
        assert default_reader.access_strategy is AccessStrategy.PLAIN


def test_explicit_gzip_strategies_are_observable(tmp_path: Path) -> None:
    path = _gzip_copy(tmp_path)
    with Mzml(path, gzip_mode="stream", in_memory=False) as stream_reader:
        assert stream_reader.access_strategy is AccessStrategy.STREAM


def test_auto_prefers_the_embedded_index(tmp_path: Path) -> None:
    source = _gzip_copy(tmp_path)
    embedded = tmp_path / "embedded.mzML.gz"
    write_indexed_gzip(source, embedded)
    with Mzml(embedded, in_memory=False) as reader:
        assert reader.access_strategy is AccessStrategy.EMBEDDED
        assert reader.spectra[1].id == "scan=20"
    assert not Path(f"{embedded}idx").exists()


def test_auto_uses_rapidgzip_with_sidecars_when_installed(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    path = _gzip_copy(tmp_path)
    with Mzml(path, in_memory=False) as reader:
        assert reader.access_strategy is AccessStrategy.RAPIDGZIP
        assert reader.spectra[1].id == "scan=20"
    assert Path(f"{path}idx").exists()  # the gzip seek index sidecar is kept for next time
    with Mzml(path, in_memory=False) as reader:
        assert reader.access_strategy is AccessStrategy.RAPIDGZIP


def test_auto_reads_into_memory_without_rapidgzip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(file_interface, "_HAS_RAPIDGZIP", False)
    monkeypatch.setattr(file_interface, "_warned_gzip_in_memory", False)
    path = _gzip_copy(tmp_path)
    with caplog.at_level(logging.WARNING, logger="mzmlpy.file_interface"):
        with Mzml(path, in_memory=False) as reader:
            assert reader.access_strategy is AccessStrategy.MEMORY
            assert reader.spectra[1].id == "scan=20"
        with Mzml(path, in_memory=False):
            pass
    notes = [r.getMessage() for r in caplog.records if "write_indexed_gzip" in r.getMessage()]
    assert len(notes) == 1  # logged once per process, not per reader
    assert sorted(p.name for p in tmp_path.iterdir()) == ["example.mzML.gz"]  # nothing written


def test_auto_falls_back_to_memory_when_sidecars_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("rapidgzip")

    def unwritable(*args: object, **kwargs: object) -> None:
        raise PermissionError("read-only directory")

    monkeypatch.setattr(file_interface, "IndexedGzip", unwritable)
    path = _gzip_copy(tmp_path)
    with Mzml(path, in_memory=False) as reader:
        assert reader.access_strategy is AccessStrategy.MEMORY
        assert len(reader.spectra) == 4


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root ignores directory permissions")
def test_auto_falls_back_to_memory_in_a_read_only_directory(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    pytest.importorskip("rapidgzip")
    folder = tmp_path / "ro"
    folder.mkdir()
    path = _gzip_copy(folder)
    folder.chmod(0o555)
    try:
        with caplog.at_level(logging.WARNING, logger="mzmlpy.file_interface"):
            with Mzml(path, in_memory=False) as reader:
                assert reader.access_strategy is AccessStrategy.MEMORY
                assert len(reader.spectra) == 4
        assert any(str(folder.resolve()) in r.getMessage() for r in caplog.records)  # names the directory
        assert sorted(p.name for p in folder.iterdir()) == ["example.mzML.gz"]
    finally:
        folder.chmod(0o755)


def test_invalid_gzip_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported gzip_mode"):
        Mzml(MZML_FILE, gzip_mode="invalid")  # type: ignore[arg-type]


def test_extract_mode_was_removed() -> None:
    with pytest.raises(MzmlError, match="'extract' was removed"):
        Mzml(GZ_FILE, gzip_mode="extract", in_memory=False)  # type: ignore[arg-type]


def test_extract_dir_was_removed(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="extract_dir"):
        Mzml(GZ_FILE, extract_dir=tmp_path)  # type: ignore[call-arg]
