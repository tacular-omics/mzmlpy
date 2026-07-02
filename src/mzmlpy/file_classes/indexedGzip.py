"""Random-access mzML reader for gzip-compressed files using rapidgzip."""

import io
import json
import logging
import os
from collections import OrderedDict
from io import TextIOWrapper
from re import Pattern
from typing import BinaryIO, TextIO

try:
    from rapidgzip import RapidgzipFile
except ImportError:
    RapidgzipFile = None  # type: ignore[assignment, misc]

from ..util import atomic_write_path, cache_is_current, write_cache_signature
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

    Two index files are cached alongside the ``.gz`` file:

    - ``.gzidx`` — the gzip seek-point index (for seeking in compressed data)
    - ``.mzidx`` — the mzML spectrum/chromatogram byte-offset index

    On first open both indices are built and saved. On subsequent opens they
    are loaded directly, making startup nearly instant with no file parsing.

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
        if RapidgzipFile is None:
            raise ImportError(
                "rapidgzip is required for gzip_mode='indexed'. "
                "Install it with: pip install mzmlpy[rapidgzip]"
            )
        self.path: str = path
        self._gzip_index_path: str = path + "idx"  # e.g. data.mzML.gzidx
        self._mzml_index_path: str = path.removesuffix(".gz") + "idx"  # e.g. data.mzMLidx

        self._ensure_gzip_index()

        # Persistent binary handle reused by get_binary_file_handler().
        self._binary_fh: RapidgzipFile = self._open_indexed()

        # If base construction (opening the text handle / building the index) fails, close the
        # persistent binary handle so its rapidgzip worker threads do not linger until shutdown.
        try:
            super().__init__(encoding, build_index_from_scratch, index_regex)
        except BaseException:
            self._binary_fh.close()
            raise

    # -- gzip seek index ---------------------------------------------------

    def _ensure_gzip_index(self) -> None:
        """Load existing .gzidx or build and save one."""
        if cache_is_current(self._gzip_index_path, self.path):
            logger.debug("Using cached gzip index: %s", self._gzip_index_path)
            return

        logger.debug("Building gzip index for: %s", self.path)
        # Atomic write so an interrupted build never leaves a truncated index that the currency
        # check would later trust.
        with atomic_write_path(self._gzip_index_path) as tmp_path:
            with RapidgzipFile(self.path, parallelization=os.cpu_count() or 1) as f:
                # Seek to end to force full decompression and index building
                f.seek(0, 2)
                f.export_index(tmp_path)
        write_cache_signature(self._gzip_index_path, self.path)
        logger.debug("Saved gzip index to: %s", self._gzip_index_path)

    def _open_indexed(self) -> RapidgzipFile:
        """Open a new RapidgzipFile with the cached seek index."""
        fh = RapidgzipFile(self.path, parallelization=os.cpu_count() or 1)
        fh.import_index(self._gzip_index_path)
        return fh

    # -- mzML spectrum/chromatogram index ----------------------------------

    def _build_index(self, from_scratch: bool = False) -> None:
        """Build or load the mzML spectrum/chromatogram offset index.

        Overrides the base class to check for a cached ``.mzidx`` JSON file
        first. If present and current, loads offsets directly. Otherwise
        delegates to the base class to parse the file, then caches the result.
        """
        if not from_scratch and cache_is_current(self._mzml_index_path, self.path):
            self._load_mzml_index()
            return

        # Delegate to base class to parse offsets from the file
        super()._build_index(from_scratch=from_scratch)
        self._save_mzml_index()

    def _load_mzml_index(self) -> None:
        """Load cached mzML offsets from the .mzidx JSON file."""
        logger.debug("Using cached mzML index: %s", self._mzml_index_path)
        with open(self._mzml_index_path) as f:
            data = json.load(f)

        self.spectrum_offsets = OrderedDict(data["spectrum_offsets"])
        self.chromatogram_offsets = OrderedDict(data["chromatogram_offsets"])
        self._spectrum_keys = list(self.spectrum_offsets.keys())
        self._chromatogram_keys = list(self.chromatogram_offsets.keys())

    def _save_mzml_index(self) -> None:
        """Save mzML offsets to the .mzidx JSON file."""
        data = {
            "spectrum_offsets": list(self.spectrum_offsets.items()),
            "chromatogram_offsets": list(self.chromatogram_offsets.items()),
        }
        with atomic_write_path(self._mzml_index_path) as tmp_path, open(tmp_path, "w") as f:
            json.dump(data, f)
        write_cache_signature(self._mzml_index_path, self.path)
        logger.debug("Saved mzML index to: %s", self._mzml_index_path)

    # -- file handlers -----------------------------------------------------

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
