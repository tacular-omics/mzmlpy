"""Random-access mzML reader for gzip-compressed files using indexed_gzip."""

import tempfile
from io import TextIOWrapper
from pathlib import Path
from re import Pattern
from typing import BinaryIO, TextIO

import indexed_gzip

from .standardMzml import AbstractRandomAccessMzml


class IndexedGzip(AbstractRandomAccessMzml):
    """Random-access mzML reader for gzip files using indexed_gzip.

    Uses the ``indexed_gzip`` library to provide seekable access to the
    decompressed content of a ``.mzML.gz`` file without extracting to disk.
    On initialization, the full gzip seek index is built once and exported
    to a small temporary file so that new file handles can import it cheaply.

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
        # Each subsequent IndexedGzipFile handle imports this index
        # so it can seek immediately (including SEEK_END).
        self._index_temp = tempfile.NamedTemporaryFile(suffix=".gzidx", delete=False)
        self._index_path: str = self._index_temp.name
        self._index_temp.close()
        with indexed_gzip.IndexedGzipFile(self.path) as f:
            f.build_full_index()
            f.export_index(self._index_path)
        super().__init__(encoding, build_index_from_scratch, index_regex)

    def _open_indexed(self) -> indexed_gzip.IndexedGzipFile:
        """Open a new IndexedGzipFile with the pre-built seek index."""
        fh = indexed_gzip.IndexedGzipFile(self.path)
        fh.import_index(self._index_path)
        return fh

    def get_binary_file_handler(self) -> BinaryIO:
        """Return a seekable binary file handler over the decompressed gzip content."""
        return self._open_indexed()

    def get_file_handler(self, encoding: str) -> TextIO:
        """Return a seekable text file handler over the decompressed gzip content."""
        return TextIOWrapper(self._open_indexed(), encoding=encoding)

    def close(self) -> None:
        """Close file handler and clean up the temporary index file."""
        super().close()
        Path(self._index_path).unlink(missing_ok=True)
