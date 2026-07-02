"""
The class :py:class:`Reader` parses mzML files.
"""

import os
import warnings
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from pathlib import Path
from re import Match
from typing import Any, Literal, Self

from .content import CVElement, MzMLContentBuilder, _MzMLContent
from .elems import (
    DataProcessing,
    FileDescription,
    InstrumentConfiguration,
    ReferenceableParamGroup,
    Run,
    Sample,
    ScanSetting,
    Software,
)
from .file_interface import FileInterface
from .lookup import ChromatogramLookup, SpectrumLookup
from .regex_patterns import FILE_ENCODING_PATTERN
from .spectra import Chromatogram
from .util import gzip_open_binary


# Keep encoding detection methods
def _guess_encoding(mzml_file: Any) -> str:
    """Determine the encoding used for the file."""
    match: Match[bytes] | None = FILE_ENCODING_PATTERN.search(mzml_file.readline())
    return bytes.decode(match.group("encoding")) if match else "utf-8"


def _index_by_id(items: Any, kind: str) -> dict[str, Any]:
    """Build an ``{id: item}`` dict, warning if two items share an id instead of silently
    dropping the earlier one."""
    result: dict[str, Any] = {}
    for item in items:
        if item.id in result:
            warnings.warn(
                f"Duplicate {kind} id {item.id!r}; keeping the last occurrence.",
                stacklevel=3,
            )
        result[item.id] = item
    return result


def _determine_file_encoding(path: str) -> str:
    """Determine the encoding used for the file in path."""
    if not os.path.exists(path):
        return "utf-8"

    if path.endswith(".gz") or path.endswith(".igz"):
        with gzip_open_binary(path) as sniffer:
            return _guess_encoding(sniffer)
    else:
        with open(path, "rb") as sniffer:
            return _guess_encoding(sniffer)


class Mzml:
    """Reader for mzML files.

    Data is lazily loaded, so only the specific sections of the XML file are parsed.
    The actual data and properties of objects are only parsed when accessed. Use the
    context manager to ensure proper file handling. The ``spectra`` and ``chromatograms``
    properties return lookup objects that support iteration, indexing, and ID-based access.

    Note:
        A reader is **not thread-safe**: random access shares a single underlying file handle,
        so concurrent access from multiple threads on the same ``Mzml`` instance will interleave
        seeks and reads and return corrupt or wrong data. Use one reader per thread.

    Args:
        file: Path to the mzML file (str or Path) or a file-like object.
        build_index_from_scratch: Build the index from scratch instead of using an existing index.
        gzip_mode: Strategy for reading gzip-compressed (``.mzML.gz``) files:

            - ``"extract"`` (default): Decompress to a temporary file on disk, then use
              standard random-access reading.
            - ``"indexed"``: Use the ``rapidgzip`` library for seekable access to the
              compressed file without extracting to disk. Requires
              ``pip install mzmlpy[rapidgzip]``.
            - ``"stream"``: Stream the file sequentially without building an index.
              Individual spectrum access re-scans the file from the beginning each time.
        in_memory: Load the entire file into memory for faster access.
        extract_dir: Directory to store extracted ``.mzML`` files when using
            ``gzip_mode='extract'``. If ``None`` (default), a system temp directory
            is used (``<tmpdir>/mzmlpy/``). Set this to a custom path to manage
            extracted files yourself — useful for batch processing where you want
            to extract all files to one directory and clean up afterward.
        spectrum_id_regex: Optional regex applied to spectrum IDs to create a secondary lookup
            key. The first capture group (or full match if no groups) becomes the simplified key.
            For example, ``r"scan=(\\d+)"`` lets you look up spectra by scan number
            (``reader.spectra["19"]``) instead of the full native ID (``"scan=19"``).
        chromatogram_id_regex: Optional regex applied to chromatogram IDs to create a secondary
            lookup key. Works identically to ``spectrum_id_regex`` but for chromatograms.
    """

    def __init__(
        self,
        file: str | Path | Any,
        build_index_from_scratch: bool = False,
        gzip_mode: Literal["extract", "indexed", "stream"] = "extract",
        in_memory: bool = True,
        extract_dir: str | Path | None = None,
        spectrum_id_regex: str | None = None,
        chromatogram_id_regex: str | None = None,
    ) -> None:
        """Initialize Mzml and parse metadata."""
        self._spectrum_id_regex = spectrum_id_regex
        self._chromatogram_id_regex = chromatogram_id_regex
        self._path: Path | None = None
        file_interface_arg: Any

        if isinstance(file, str | Path):
            self._path = Path(file)
            # Use string representation for internal helpers that expect paths
            path_str = str(self._path)
            self._encoding = _determine_file_encoding(path_str)
            file_interface_arg = path_str
        else:
            # File-like object
            if hasattr(file, "name"):
                self._path = Path(file.name)
            self._encoding = _guess_encoding(file)
            file_interface_arg = file

        # Open file
        self._file_object: FileInterface = FileInterface(
            path=file_interface_arg,
            encoding=self._encoding,
            build_index_from_scratch=build_index_from_scratch,
            gzip_mode=gzip_mode,
            in_memory=in_memory,
            extract_dir=str(extract_dir) if extract_dir is not None else None,
        )

        # Parse metadata. If parsing fails, close the file object so a half-constructed
        # reader does not leak extracted temp files or rapidgzip worker threads — the caller
        # never receives the object, so it can never call close() itself.
        try:
            self._root, self.iter, builder = self._parse_metadata()
            # Extract parsed content
            self._content: _MzMLContent = builder.build()
            self.obo_version = builder.obo_version
        except BaseException:
            self._file_object.close()
            raise

    def _parse_metadata(
        self,
    ) -> tuple[ElementTree.Element, Iterator[tuple[str, ElementTree.Element]], MzMLContentBuilder]:
        """Parse metadata and return root, iterator, and builder."""
        file_handle = self._file_object.file_handler.get_file_handler(self._encoding)
        try:
            mzml_iter: Iterator[tuple[str, ElementTree.Element]] = iter(
                ElementTree.iterparse(file_handle, events=("end", "start"))
            )

            _, root = next(mzml_iter)

            # Build metadata
            builder = MzMLContentBuilder()
            builder.parse_from_iterator(mzml_iter)

            root.clear()
            return root, mzml_iter, builder
        finally:
            # Metadata is fully extracted into the builder above, so this transient handle is
            # no longer needed. Closing it matters for gzip_mode="indexed", where the handle is a
            # RapidgzipFile with worker threads that otherwise linger until interpreter shutdown
            # (triggering rapidgzip's "close all RapidgzipFile objects" warning / abort).
            file_handle.close()

    @property
    def file_path(self) -> Path | None:
        """Access the file path as a Path object if available."""
        return self._path

    @property
    def file_name(self) -> str:
        """Access the file name as a string."""
        if self._path:
            return self._path.name
        return "in-memory-stream"

    @property
    def spectra(self) -> SpectrumLookup:
        """Access spectra lookup."""
        return SpectrumLookup(file_object=self._file_object, id_regex=self._spectrum_id_regex)

    @property
    def chromatograms(self) -> ChromatogramLookup:
        """Access chromatograms lookup."""
        return ChromatogramLookup(file_object=self._file_object, id_regex=self._chromatogram_id_regex)

    @property
    def TIC(self) -> Chromatogram | None:
        """Access the Total Ion Chromatogram (TIC)."""
        try:
            return self._file_object.TIC
        except KeyError:
            return None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, type: Any, value: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        self._file_object.close()

    @property
    def id(self) -> str:
        """Access mzML id."""
        return self._content.id

    @property
    def version(self) -> str:
        """Access mzML version."""
        return self._content.version

    @property
    def cvs(self) -> dict[str, CVElement]:
        """Access controlled vocabularies."""
        return _index_by_id(self._content.cv_list, "controlled vocabulary")

    @property
    def file_description(self) -> FileDescription | None:
        """Access file description."""
        return self._content.file_description

    @property
    def referenceable_param_groups(self) -> dict[str, ReferenceableParamGroup]:
        """Access referenceable parameter groups."""
        return self._content.referenceable_param_groups

    @property
    def softwares(self) -> dict[str, Software]:
        """Access software list."""
        return _index_by_id(self._content.softwares, "software")

    @property
    def instrument_configurations(self) -> dict[str, InstrumentConfiguration]:
        """Access instrument configurations."""
        return self._content.instrument_configurations

    @property
    def data_processes(self) -> dict[str, DataProcessing]:
        """Access data processing steps."""
        return self._content.data_processes

    @property
    def samples(self) -> dict[str, Sample]:
        """Access sample list."""
        return _index_by_id(self._content.samples, "sample")

    @property
    def scan_settings(self) -> dict[str, ScanSetting]:
        """Access scan settings."""
        return self._content.scan_settings

    @property
    def run(self) -> Run | None:
        """Access run information."""
        return self._content.run
