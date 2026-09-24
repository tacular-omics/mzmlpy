"""
The class :py:class:`Mzml` reads mzML files; :func:`peek_spectrum_count` reads only the spectrum count.
"""

import os
import warnings
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from io import BytesIO
from itertools import chain
from pathlib import Path
from re import Match
from typing import Any, BinaryIO, Literal, Self, cast

from .constants import MzMLElement
from .content import CVElement, _MzMLContent, _MzMLContentBuilder
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
from .embedded_indexed_gzip import decompress_indexed_member, is_embedded_indexed_gzip, read_embedded_index
from .errors import MzmlParseError, _parse_errors
from .file_interface import AccessStrategy, FileInterface
from .lookup import ChromatogramLookup, SpectrumLookup
from .regex_patterns import FILE_ENCODING_PATTERN
from .spectra import Chromatogram
from .util import get_tag, gzip_open_binary
from .validation import ValidationReport, _validate_stream


# Keep encoding detection methods
def _guess_encoding(mzml_file: Any) -> str:
    """Determine the encoding used for the file."""
    match: Match[bytes] | None = FILE_ENCODING_PATTERN.search(mzml_file.read(1024))
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

    if path.endswith((".gz", ".igz")) and is_embedded_indexed_gzip(path):
        try:
            first_offset = read_embedded_index(path)[0].offset
        except ValueError:
            pass
        else:
            return _guess_encoding(BytesIO(decompress_indexed_member(path, first_offset)))
    if path.endswith(".gz") or path.endswith(".igz"):
        with gzip_open_binary(path) as sniffer:
            return _guess_encoding(sniffer)
    else:
        with open(path, "rb") as sniffer:
            return _guess_encoding(sniffer)


def peek_spectrum_count(file: str | Path) -> int | None:
    """Return a file's spectrum count without building a random-access index.

    Unlike ``len(Mzml(file).spectra)``, this does not construct a reader or index every
    spectrum's byte offset — it streams forward just far enough to read the
    ``<spectrumList count="N">`` opening tag's ``count`` attribute (just after the header
    metadata, before the first spectrum) and stops. Files ending in ``.gz`` or ``.igz`` are
    decompressed on the fly. Useful for cheaply checking many
    files (e.g. before deciding which to open fully). Returns ``None`` if the file has no
    ``spectrumList`` or the tag has no ``count`` attribute.

    Note:
        There is no equally cheap ``peek_chromatogram_count``: per the mzML schema,
        ``chromatogramList`` follows ``spectrumList``, so reaching its opening tag requires
        streaming past the entire spectrum list first — at that point building the full index
        via :class:`Mzml` is a better fit than a "peek."
    """
    path_str = str(file)
    is_gz = path_str.endswith(".gz") or path_str.endswith(".igz")
    file_handle = gzip_open_binary(path_str) if is_gz else open(path_str, "rb")
    try:
        with _parse_errors(path_str):
            # Read the count off the spectrumList *start* tag, but clear completed elements on their
            # *end* events so that a file with no spectrumList doesn't accumulate the whole tree in
            # memory before returning None.
            for event, element in ElementTree.iterparse(file_handle, events=("start", "end")):
                if event == "start":
                    if get_tag(element) == MzMLElement.SPECTRUM_LIST:
                        count = element.attrib.get("count")
                        return int(count) if count is not None else None
                else:
                    element.clear()
            return None
    finally:
        file_handle.close()


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
        gzip_mode: Strategy for reading gzip-compressed (``.mzML.gz``) files. Only used with
            ``in_memory=False``; with ``in_memory=True`` the whole file is decompressed into memory
            and ``"indexed"`` or ``"stream"`` warn that they are ignored.

            Self-indexed files created by :func:`mzmlpy.write_indexed_gzip` are detected
            automatically when ``in_memory=False``. They use their embedded index regardless of
            this setting.

            - ``"auto"`` (default): Use the embedded index if the file has one. Otherwise use
              ``rapidgzip`` if it is installed, building sidecar indexes next to the file on
              first use. Otherwise decompress the whole file into memory. For large files,
              run :func:`mzmlpy.write_indexed_gzip` once or ``pip install mzmlpy[rapidgzip]``.
            - ``"indexed"``: Use the ``rapidgzip`` library for seekable access to the
              compressed file without decompressing it all. Requires
              ``pip install mzmlpy[rapidgzip]``.
            - ``"stream"``: Stream the file sequentially without building an index.
              Individual spectrum access re-scans the file from the beginning each time.

            ``"extract"`` and ``extract_dir`` were removed in 0.10.
        in_memory: Load the entire (decompressed) file into memory. Defaults to ``False``: plain
            files are read from disk through their index and gzip files follow ``gzip_mode``.
            Pass ``True`` to buffer a small file, or a gzip file you will read many times.
        spectrum_id_regex: Optional regex applied to spectrum IDs to create a secondary lookup
            key. The first capture group (or full match if no groups) becomes the simplified key.
            For example, ``r"scan=(\\d+)"`` lets you look up spectra by scan number
            (``reader.spectra["19"]``) instead of the full native ID (``"scan=19"``).
        chromatogram_id_regex: Optional regex applied to chromatogram IDs to create a secondary
            lookup key. Works identically to ``spectrum_id_regex`` but for chromatograms.
    """

    def __init__(
        self,
        file: str | Path | BinaryIO,
        *,
        build_index_from_scratch: bool = False,
        gzip_mode: Literal["auto", "indexed", "stream"] = "auto",
        in_memory: bool = False,
        spectrum_id_regex: str | None = None,
        chromatogram_id_regex: str | None = None,
    ) -> None:
        """Initialize Mzml and parse metadata."""
        self._spectrum_id_regex = spectrum_id_regex
        self._chromatogram_id_regex = chromatogram_id_regex
        self._spectra_lookup: SpectrumLookup | None = None
        self._chromatograms_lookup: ChromatogramLookup | None = None
        self._path: Path | None = None
        file_interface_arg: Any

        if isinstance(file, str | Path):
            self._path = Path(file)
            # Use string representation for internal helpers that expect paths
            path_str = str(self._path)
            self._encoding = _determine_file_encoding(path_str)
            file_interface_arg = path_str
        else:
            # File-like object — must be a readable binary stream. Validate up front so an
            # unsupported input (e.g. an int) raises a clear TypeError instead of an opaque
            # AttributeError from encoding sniffing below.
            if not (hasattr(file, "read") and hasattr(file, "readline")):
                raise TypeError(
                    f"Unsupported input type {type(file).__name__!r}: expected a path (str/Path) "
                    "or a readable binary file-like object."
                )
            if hasattr(file, "name") and isinstance(file.name, str):
                self._path = Path(file.name)
            self._encoding = _guess_encoding(file)
            file_interface_arg = file

        source = str(self._path) if self._path is not None else "in-memory-stream"
        # Open file
        with _parse_errors(source):
            self._file_object: FileInterface = FileInterface(
                path=file_interface_arg,
                encoding=self._encoding,
                build_index_from_scratch=build_index_from_scratch,
                gzip_mode=gzip_mode,
                in_memory=in_memory,
            )

        # Parse metadata. If parsing fails, close the file object so a half-constructed
        # reader does not leak file handles or rapidgzip worker threads — the caller
        # never receives the object, so it can never call close() itself.
        try:
            with _parse_errors(source):
                builder = self._parse_metadata()
            # Extract parsed content
            self._content: _MzMLContent = builder.build()
            self._obo_version: str | None = builder.obo_version
        except BaseException:
            self._file_object.close()
            raise

    def _parse_metadata(self) -> _MzMLContentBuilder:
        """Parse the metadata sections into a content builder."""
        file_handle = self._file_object.file_handler.get_file_handler(self._encoding)
        try:
            mzml_iter: Iterator[tuple[str, ElementTree.Element]] = iter(
                ElementTree.iterparse(file_handle, events=("end", "start"))
            )

            # iterparse raises ParseError ("no element found") on input without a root element,
            # which _parse_errors turns into MzmlParseError, so next() cannot hit StopIteration.
            _, root = next(mzml_iter)
            if get_tag(root) not in ("mzML", "indexedmzML"):
                raise MzmlParseError(f"Root element is <{get_tag(root)}>, not <mzML> or <indexedmzML>")

            # Build metadata
            builder = _MzMLContentBuilder()
            builder.parse_from_iterator(chain((("start", root),), mzml_iter))

            root.clear()
            return builder
        finally:
            # Metadata is fully extracted into the builder above, so this transient handle is
            # no longer needed. Closing it matters for gzip_mode="indexed", where the handle is a
            # RapidgzipFile with worker threads that otherwise linger until interpreter shutdown
            # (triggering rapidgzip's "close all RapidgzipFile objects" warning / abort).
            file_handle.close()

    def validate(self, *, decode_binary: bool = False, check_index: bool = False) -> ValidationReport:
        """Validate this reader's XML through a fresh handle.

        See :func:`mzmlpy.validate` for check scope. This checks the representation selected
        by the reader. Use the standalone function to validate the original file directly.
        """
        with self._file_object.file_handler.get_file_handler(self._encoding) as handle:
            binary = cast(BinaryIO, getattr(handle, "buffer", handle))
            return _validate_stream(binary, decode_binary=decode_binary, check_index=check_index)

    @property
    def access_strategy(self) -> AccessStrategy:
        """Concrete storage strategy selected when the file was opened."""
        return self._file_object.access_strategy

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
        """Access spectra lookup.

        Returns the same lookup instance across calls, so the regex id map built for
        ``spectrum_id_regex`` persists and id lookups don't re-scan the file on every access.
        """
        if self._spectra_lookup is None:
            self._spectra_lookup = SpectrumLookup(file_object=self._file_object, id_regex=self._spectrum_id_regex)
        return self._spectra_lookup

    @property
    def chromatograms(self) -> ChromatogramLookup:
        """Access chromatograms lookup.

        Returns the same lookup instance across calls (see :meth:`spectra`).
        """
        if self._chromatograms_lookup is None:
            self._chromatograms_lookup = ChromatogramLookup(
                file_object=self._file_object, id_regex=self._chromatogram_id_regex
            )
        return self._chromatograms_lookup

    @property
    def total_ion_chromatogram(self) -> Chromatogram | None:
        """The total ion chromatogram, or None if the file has none.

        Found by the id ``"TIC"`` or, failing that, by the MS:1000235 CV term.
        """
        return self._file_object.total_ion_chromatogram()

    @property
    def obo_version(self) -> str | None:
        """Version of the PSI-MS controlled vocabulary declared in the ``cvList``."""
        return self._obo_version

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
        """Access referenceable parameter groups (a new dict on every call)."""
        return dict(self._content.referenceable_param_groups)

    @property
    def softwares(self) -> dict[str, Software]:
        """Access software list."""
        return _index_by_id(self._content.softwares, "software")

    @property
    def instrument_configurations(self) -> dict[str, InstrumentConfiguration]:
        """Access instrument configurations (a new dict on every call)."""
        return dict(self._content.instrument_configurations)

    @property
    def data_processes(self) -> dict[str, DataProcessing]:
        """Access data processing steps (a new dict on every call)."""
        return dict(self._content.data_processes)

    @property
    def samples(self) -> dict[str, Sample]:
        """Access sample list."""
        return _index_by_id(self._content.samples, "sample")

    @property
    def scan_settings(self) -> dict[str, ScanSetting]:
        """Access scan settings (a new dict on every call)."""
        return dict(self._content.scan_settings)

    @property
    def run(self) -> Run | None:
        """Access run information."""
        return self._content.run


__all__ = ["Mzml", "peek_spectrum_count"]
