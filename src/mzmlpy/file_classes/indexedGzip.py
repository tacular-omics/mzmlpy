"""Random-access mzML reader for gzip-compressed files using indexed_gzip."""

import io
import tempfile
from io import TextIOWrapper
from pathlib import Path
from re import Pattern
from typing import BinaryIO, TextIO

import indexed_gzip

from .standardMzml import AbstractRandomAccessMzml


class _NonClosingBinaryWrapper(io.RawIOBase):
    """Wrapper around a binary file handle that ignores close().

    Used to share a single IndexedGzipFile across multiple callers that
    each expect to close their own handle.
    """

    def __init__(self, fh: BinaryIO) -> None:
        self._fh = fh

    def read(self, size: int = -1) -> bytes:
        return self._fh.read(size)

    def readinto(self, b: bytearray) -> int:  # type: ignore[override]
        data = self._fh.read(len(b))
        n = len(data)
        b[:n] = data
        return n

    def readline(self, size: int | None = -1, /) -> bytes:
        return self._fh.readline(-1 if size is None else size)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, pos: int, whence: int = 0) -> int:
        return self._fh.seek(pos, whence)

    def tell(self) -> int:
        return self._fh.tell()

    def close(self) -> None:
        pass  # Don't close the shared handle


class IndexedGzip(AbstractRandomAccessMzml):
    """Random-access mzML reader for gzip files using indexed_gzip.

    Uses the ``indexed_gzip`` library to provide seekable access to the
    decompressed content of a ``.mzML.gz`` file without extracting to disk.
    On initialization, the full gzip seek index is built once. A persistent
    binary file handle is reused for all random-access operations to avoid
    the overhead of repeatedly opening and importing the index.

    Args:
        path: Path to the gzip-compressed mzML file.
        encoding: Character encoding of the XML content.
        build_index_from_scratch: Build the mzML index by scanning the file
            instead of reading the footer index section.
        index_regex: Optional regex for custom index building.
    """

    def __init__(
        self,
        path: str,
        encoding: str,
        build_index_from_scratch: bool = False,
        index_regex: Pattern[bytes] | None = None,
    ) -> None:
        self.path: str = path
        # Build the gzip seek index once and export to a temp file.
        self._index_temp = tempfile.NamedTemporaryFile(suffix=".gzidx", delete=False)
        self._index_path: str = self._index_temp.name
        self._index_temp.close()
        with indexed_gzip.IndexedGzipFile(self.path) as f:
            f.build_full_index()
            f.export_index(self._index_path)

        # Persistent binary handle reused by get_binary_file_handler().
        self._binary_fh: indexed_gzip.IndexedGzipFile = self._open_indexed()

        super().__init__(encoding, build_index_from_scratch, index_regex)

    def _open_indexed(self) -> indexed_gzip.IndexedGzipFile:
        """Open a new IndexedGzipFile with the pre-built seek index."""
        fh = indexed_gzip.IndexedGzipFile(self.path)
        fh.import_index(self._index_path)
        return fh

    def get_binary_file_handler(self) -> BinaryIO:
        """Return a seekable binary view over the persistent decompressed handle."""
        return _NonClosingBinaryWrapper(self._binary_fh)  # type: ignore[return-value]

    def get_file_handler(self, encoding: str) -> TextIO:
        """Return a seekable text file handler over the decompressed gzip content."""
        return TextIOWrapper(self._open_indexed(), encoding=encoding)

    def close(self) -> None:
        """Close file handlers and clean up the temporary index file."""
        super().close()
        self._binary_fh.close()
        Path(self._index_path).unlink(missing_ok=True)
