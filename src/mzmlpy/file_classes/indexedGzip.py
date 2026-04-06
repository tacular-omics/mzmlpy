"""Random-access mzML reader for gzip-compressed files using rapidgzip."""

import io
import logging
import os
from io import TextIOWrapper
from re import Pattern
from typing import BinaryIO, TextIO

from rapidgzip import RapidgzipFile

from .standardMzml import AbstractRandomAccessMzml

logger = logging.getLogger(__name__)


class _NonClosingBinaryWrapper(io.RawIOBase):
    """Wrapper around a binary file handle that ignores close().

    Used to share a single RapidgzipFile across multiple callers that
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
    """Random-access mzML reader for gzip files using rapidgzip.

    Uses the ``rapidgzip`` library to provide seekable access to the
    decompressed content of a ``.mzML.gz`` file without extracting to disk.
    Rapidgzip supports parallel decompression for faster index building.

    On first open, the full gzip seek index is built and saved as a
    ``.gzidx`` file alongside the ``.gz`` file (e.g. ``data.mzML.gzidx``
    next to ``data.mzML.gz``). On subsequent opens the cached index is
    loaded directly, making startup nearly instant.

    A persistent binary file handle is reused for all random-access
    operations to avoid the overhead of repeatedly opening handles.

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
        self._index_path: str = path + "idx"  # e.g. data.mzML.gzidx

        self._ensure_gzip_index()

        # Persistent binary handle reused by get_binary_file_handler().
        self._binary_fh: RapidgzipFile = self._open_indexed()

        super().__init__(encoding, build_index_from_scratch, index_regex)

    def _ensure_gzip_index(self) -> None:
        """Load existing .gzidx or build and save one."""
        if self._is_index_current():
            logger.debug("Using cached gzip index: %s", self._index_path)
            return

        logger.debug("Building gzip index for: %s", self.path)
        with RapidgzipFile(self.path, parallelization=os.cpu_count() or 1) as f:
            f.build_full_index()
            f.export_index(self._index_path)
        logger.debug("Saved gzip index to: %s", self._index_path)

    def _is_index_current(self) -> bool:
        """Check whether a cached .gzidx exists and is newer than the .gz file."""
        if not os.path.exists(self._index_path):
            return False
        return os.path.getmtime(self._index_path) >= os.path.getmtime(self.path)

    def _open_indexed(self) -> RapidgzipFile:
        """Open a new RapidgzipFile with the cached seek index."""
        fh = RapidgzipFile(self.path, parallelization=os.cpu_count() or 1)
        fh.import_index(self._index_path)
        return fh

    def get_binary_file_handler(self) -> BinaryIO:
        """Return a seekable binary view over the persistent decompressed handle."""
        return _NonClosingBinaryWrapper(self._binary_fh)  # type: ignore[return-value]

    def get_file_handler(self, encoding: str) -> TextIO:
        """Return a seekable text file handler over the decompressed gzip content."""
        return TextIOWrapper(self._open_indexed(), encoding=encoding)

    def close(self) -> None:
        """Close file handlers."""
        super().close()
        self._binary_fh.close()
