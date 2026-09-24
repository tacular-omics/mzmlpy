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


def test_auto_uses_rapidgzip_in_memory_and_writes_nothing(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    path = _gzip_copy(tmp_path)
    with Mzml(path, in_memory=False) as reader:
        assert reader.access_strategy is AccessStrategy.RAPIDGZIP
        assert reader.spectra[1].id == "scan=20"
        assert len(reader.spectra) == 4
        with reader._file_object.file_handler.get_file_handler("utf-8") as fh:  # noqa: SLF001
            assert fh.read(5) == "<?xml"  # extra handles reuse the in-memory seek index
    assert sorted(p.name for p in tmp_path.iterdir()) == ["example.mzML.gz"]  # nothing written


def test_auto_writes_nothing_next_to_test_data() -> None:
    before = sorted(p.name for p in GZ_FILE.parent.iterdir())
    with Mzml(GZ_FILE, in_memory=False) as reader:
        assert len(reader.spectra) == 4
    assert sorted(p.name for p in GZ_FILE.parent.iterdir()) == before


def test_auto_reuses_sidecars_from_indexed_mode_read_only(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    path = _gzip_copy(tmp_path)
    with Mzml(path, gzip_mode="indexed", in_memory=False) as reader:
        assert reader.access_strategy is AccessStrategy.RAPIDGZIP
    written = {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()}
    assert "example.mzML.gzidx" in written and "example.mzMLidx" in written
    with Mzml(path, in_memory=False) as reader:
        assert reader.access_strategy is AccessStrategy.RAPIDGZIP
        assert reader.spectra[1].id == "scan=20"
    assert {p.name: p.stat().st_mtime_ns for p in tmp_path.iterdir()} == written  # read, not rewritten


def test_auto_ignores_stale_sidecars_without_rewriting_them(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    path = _gzip_copy(tmp_path)
    with Mzml(path, gzip_mode="indexed", in_memory=False):
        pass
    stale = tmp_path / "example.mzMLidx"
    stale.write_text("not json")  # size/mtime change makes it stale
    written = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with Mzml(path, in_memory=False) as reader:
        assert reader.spectra[1].id == "scan=20"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == written


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root ignores directory permissions")
def test_auto_reads_from_a_read_only_directory(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    folder = tmp_path / "ro"
    folder.mkdir()
    path = _gzip_copy(folder)
    folder.chmod(0o555)
    try:
        with Mzml(path, in_memory=False) as reader:
            assert reader.access_strategy is AccessStrategy.RAPIDGZIP
            assert len(reader.spectra) == 4
        with pytest.raises(OSError):  # indexed mode is asked to write sidecars, so it fails loudly
            Mzml(path, gzip_mode="indexed", in_memory=False)
        assert sorted(p.name for p in folder.iterdir()) == ["example.mzML.gz"]
    finally:
        folder.chmod(0o755)


def test_indexed_sidecars_get_normal_file_permissions(tmp_path: Path) -> None:
    pytest.importorskip("rapidgzip")
    path = _gzip_copy(tmp_path)
    old = os.umask(0o022)
    try:
        with Mzml(path, gzip_mode="indexed", in_memory=False):
            pass
    finally:
        os.umask(old)
    for name in ("example.mzML.gzidx", "example.mzML.gzidx.src", "example.mzMLidx", "example.mzMLidx.src"):
        assert (tmp_path / name).stat().st_mode & 0o777 == 0o644, name


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


def test_invalid_gzip_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported gzip_mode"):
        Mzml(MZML_FILE, gzip_mode="invalid")  # type: ignore[arg-type]


def test_extract_mode_was_removed() -> None:
    with pytest.raises(MzmlError, match="'extract' was removed"):
        Mzml(GZ_FILE, gzip_mode="extract", in_memory=False)  # type: ignore[arg-type]


def test_extract_dir_was_removed(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="extract_dir"):
        Mzml(GZ_FILE, extract_dir=tmp_path)  # type: ignore[call-arg]
