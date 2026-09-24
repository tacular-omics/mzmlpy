#!/usr/bin/env python3
"""Interface for different mzML file formats."""

import atexit
import gzip
import logging
import os
import warnings
import weakref
from collections.abc import Iterator
from enum import StrEnum
from functools import cached_property
from io import BytesIO
from itertools import islice
from pathlib import Path
from re import Pattern
from typing import Any, BinaryIO, Literal, NoReturn, cast, overload
from xml.etree import ElementTree as ET

from ._xml import iter_records
from .constants import ChromatogramTypeAccession
from .embedded_indexed_gzip import is_embedded_indexed_gzip
from .errors import MzmlError, _parse_errors
from .file_classes import (
    AbstractRandomAccessMzml,
    BytesMzml,
    ChromatogramElement,
    EmbeddedIndexedGzip,
    IndexedGzip,
    MzmlInterface,
    MzmlXMLElement,
    SpectrumElement,
    StandardGzip,
    StandardMzml,
)
from .spectra import Chromatogram, Spectrum
from .util import (
    _HAS_RAPIDGZIP,
    expand_param_group_refs,
    get_tag,
    gzip_decompress,
)

logger = logging.getLogger(__name__)


class AccessStrategy(StrEnum):
    """Concrete storage strategy selected for an mzML reader."""

    MEMORY = "memory"
    PLAIN = "plain"
    EMBEDDED = "embedded"
    RAPIDGZIP = "rapidgzip"
    STREAM = "stream"


@overload
def _convert_mzml_element_to_object(
    mzml_element: SpectrumElement,
) -> Spectrum: ...


@overload
def _convert_mzml_element_to_object(
    mzml_element: ChromatogramElement,
) -> Chromatogram: ...


def _convert_mzml_element_to_object(
    mzml_element: SpectrumElement | ChromatogramElement,
) -> Spectrum | Chromatogram:
    """Convert MzmlXMLElement to Spectrum or Chromatogram object."""
    if mzml_element.element_type == "spectrum":
        return Spectrum(mzml_element.element)
    elif mzml_element.element_type == "chromatogram":
        return Chromatogram(mzml_element.element)
    else:
        raise MzmlError(f"Unknown element_type: {mzml_element.element_type}")


class _ClosedBackend:
    """Stands in for the backend after close(): every use raises instead of reopening the file."""

    def close(self) -> None:
        """Closing again is a no-op."""

    def __getattr__(self, name: str) -> NoReturn:
        raise MzmlError("This mzML reader is closed; open a new Mzml to read the file again.")


class _TrackedIterator[T]:
    """An iterator its reader can stop: after close() the next item raises MzmlError.

    Closing the wrapped generator runs its ``finally`` blocks, which close the file handle it
    holds. Without this a suspended iterator keeps a rapidgzip handle, whose worker threads
    abort the interpreter at exit (``terminate called``) when the handle is finalized too late.
    """

    __slots__ = ("__weakref__", "_closed", "_generator", "_pid")

    def __init__(self, generator: Iterator[T]) -> None:
        self._generator = generator
        self._closed = False
        self._pid = os.getpid()
        _LIVE_ITERATORS.add(self)

    def __iter__(self) -> "_TrackedIterator[T]":
        return self

    def __next__(self) -> T:
        if self._closed:
            raise MzmlError("This mzML reader is closed; open a new Mzml to read the file again.")
        return next(self._generator)

    def close(self) -> None:
        self._closed = True
        close = getattr(self._generator, "close", None)
        if close is not None:
            try:
                close()
            except ValueError:  # closed from inside its own iteration; it finishes on return
                pass


_LIVE_ITERATORS: "weakref.WeakSet[_TrackedIterator[Any]]" = weakref.WeakSet()
_LIVE_READERS: "weakref.WeakSet[FileInterface]" = weakref.WeakSet()


@atexit.register
def _close_at_exit() -> None:
    """Close handles of readers and iterators still open at exit, before interpreter teardown.

    rapidgzip aborts the process when one of its handles is finalized after its worker threads
    see the interpreter shutting down, so unclosed readers must be closed while it still runs.
    Iterators are closed before readers. Readers and iterators inherited by a forked child
    belong to the parent and are left alone: closing an inherited rapidgzip handle can hang.
    """
    pid = os.getpid()
    for iterator in list(_LIVE_ITERATORS):
        if iterator._pid == pid:
            iterator.close()
    for reader in list(_LIVE_READERS):
        if reader._pid != pid:
            continue
        try:
            reader.close()
        except Exception as error:  # never let one reader stop the others being closed
            logger.debug("Closing an mzML reader at exit failed: %s", error)


_warned_gzip_in_memory = False


def _note_gzip_read_into_memory(path: str | os.PathLike[str]) -> None:
    """Log once per process that a gzip file without an index is read into memory."""
    global _warned_gzip_in_memory
    if _warned_gzip_in_memory:
        return
    _warned_gzip_in_memory = True
    logger.warning(
        "Decompressing %s into memory: it has no embedded index and rapidgzip is not installed. "
        "For random access without holding the file in RAM, run mzmlpy.write_indexed_gzip on it once "
        "or install mzmlpy[rapidgzip]. (Logged once per process.)",
        path,
    )


class FileInterface:
    """Interface to different mzML formats."""

    def __init__(
        self,
        path: str | Path | BinaryIO,
        encoding: str,
        build_index_from_scratch: bool = False,
        index_regex: Pattern[bytes] | None = None,
        gzip_mode: Literal["auto", "indexed", "stream"] = "auto",
        in_memory: bool = False,
    ) -> None:
        """Initialize FileInterface with path and encoding options."""
        self.build_index_from_scratch: bool = build_index_from_scratch
        self.encoding: str = encoding
        self.index_regex: Pattern[bytes] | None = index_regex
        if gzip_mode not in {"auto", "indexed", "stream"}:
            removed = " gzip_mode='extract' was removed in 0.10." if gzip_mode == "extract" else ""
            raise MzmlError(
                f"Unsupported gzip_mode: {gzip_mode!r}.{removed} Use 'auto', 'indexed' or 'stream'; "
                "for fast random access to a .gz, run write_indexed_gzip() on it once."
            )
        self.gzip_mode: Literal["auto", "indexed", "stream"] = gzip_mode
        self.in_memory: bool = in_memory
        self._iterators: weakref.WeakSet[_TrackedIterator[Any]] = weakref.WeakSet()
        self._pid = os.getpid()
        self.access_strategy: AccessStrategy
        self.file_handler: MzmlInterface = self._open(path)
        _LIVE_READERS.add(self)

    def close(self) -> None:
        """Close the internal file handler and any iterators still holding a file handle."""
        try:
            for iterator in list(self._iterators):
                iterator.close()
            self.file_handler.close()
        finally:
            self.file_handler = _ClosedBackend()  # ty: ignore[invalid-assignment]

    def _track[T](self, generator: Iterator[T]) -> Iterator[T]:
        """Register an iterator that holds a file handle so close() can release it."""
        iterator = _TrackedIterator(generator)
        self._iterators.add(iterator)
        return iterator

    def _open(self, path_or_file: str | Path | BinaryIO) -> MzmlInterface:
        """Open appropriate file handler based on file type and format."""
        # Handle any binary file-like object (BytesIO or an open ``rb`` stream). Materialize its
        # bytes into an in-memory buffer; if the stream is gzip-compressed, decompress it first so
        # a handle opened on a ``.mzML.gz`` file is accepted transparently.
        if not isinstance(path_or_file, str | Path):
            if hasattr(path_or_file, "read"):
                if isinstance(path_or_file, BytesIO):
                    data = path_or_file.getvalue()
                else:
                    # Encoding sniffing (readline) may have advanced the stream, so rewind it if we
                    # can before reading the whole thing; getvalue() above sidesteps this for BytesIO.
                    if hasattr(path_or_file, "seek"):
                        path_or_file.seek(0)
                    data = path_or_file.read()
                if data[:2] == b"\x1f\x8b":  # gzip magic number
                    data = gzip.decompress(data)
                self.access_strategy = AccessStrategy.MEMORY
                return BytesMzml(BytesIO(data), self.encoding, self.build_index_from_scratch)
            raise TypeError(
                f"Unsupported input type {type(path_or_file).__name__!r}: expected a path (str/Path) "
                "or a binary file-like object with a read() method."
            )

        # Convert Path to string
        path = str(path_or_file) if isinstance(path_or_file, Path) else path_or_file

        # Handle in_memory mode - load entire file into memory
        if self.in_memory:
            if path.endswith((".gz", ".igz")):
                if self.gzip_mode != "auto":
                    # "indexed"/"stream" exist to avoid holding the whole file in memory; in_memory
                    # (the default) decompresses it all anyway, so the mode is a no-op here.
                    warnings.warn(
                        f"gzip_mode={self.gzip_mode!r} is ignored because in_memory=True decompresses the "
                        f"entire file into memory. Pass in_memory=False to use gzip_mode={self.gzip_mode!r}.",
                        stacklevel=2,
                    )
                # Decompress gzipped file into memory
                content = gzip_decompress(path)
            else:
                # Read uncompressed file into memory
                with open(path, "rb") as f:
                    content = f.read()

            self.access_strategy = AccessStrategy.MEMORY
            return BytesMzml(
                BytesIO(content),
                self.encoding,
                self.build_index_from_scratch,
            )

        # Handle gzipped files
        if path.endswith((".gz", ".igz")):
            if is_embedded_indexed_gzip(path):
                try:
                    embedded = EmbeddedIndexedGzip(path, self.encoding)
                except ValueError as error:
                    logger.warning("Ignoring invalid embedded gzip index in %s: %s", path, error)
                else:
                    self.access_strategy = AccessStrategy.EMBEDDED
                    return embedded
            if self.gzip_mode == "indexed":
                self.access_strategy = AccessStrategy.RAPIDGZIP
                return IndexedGzip(
                    path,
                    self.encoding,
                    self.build_index_from_scratch,
                    index_regex=self.index_regex,
                )
            if self.gzip_mode == "auto":
                if _HAS_RAPIDGZIP:
                    # rapidgzip reads the compressed file in place, building sidecar indexes next
                    # to it on first use (or reusing current ones).
                    try:
                        handler = IndexedGzip(
                            path,
                            self.encoding,
                            self.build_index_from_scratch,
                            index_regex=self.index_regex,
                        )
                    except OSError as error:  # e.g. no write access for the sidecars
                        logger.warning(
                            "Reading %s into memory: could not write rapidgzip sidecar indexes in %s (%s)",
                            path,
                            Path(path).resolve().parent,
                            error,
                        )
                    else:
                        self.access_strategy = AccessStrategy.RAPIDGZIP
                        return handler
                # No embedded index and no usable rapidgzip: decompress into memory.
                if not _HAS_RAPIDGZIP:
                    _note_gzip_read_into_memory(path)
                self.access_strategy = AccessStrategy.MEMORY
                return BytesMzml(BytesIO(gzip_decompress(path)), self.encoding, self.build_index_from_scratch)
            self.access_strategy = AccessStrategy.STREAM
            return StandardGzip(path, self.encoding)

        # Handle standard mzML files
        self.access_strategy = AccessStrategy.PLAIN
        return StandardMzml(
            path,
            self.encoding,
            self.build_index_from_scratch,
            index_regex=self.index_regex,
        )

    def read(self, size: int = -1) -> bytes | str:
        """Read binary data from file handler (size=-1 reads to end)."""
        return self.file_handler.read(size)

    @cached_property
    def _param_group_templates(self) -> dict[str, list[tuple[str, dict[str, str]]]]:
        """Map each referenceableParamGroup id to its cvParam/userParam terms.

        Parsed once from the file header. Each term is stored as (local tag name, attributes)
        so it can be re-created inside a spectrum/scan with that element's own namespace,
        regardless of how the target fragment was parsed.
        """
        templates: dict[str, list[tuple[str, dict[str, str]]]] = {}
        file_handle = self.file_handler.get_file_handler(self.encoding)
        try:
            if hasattr(file_handle, "seek"):
                file_handle.seek(0)
            for event, element in ET.iterparse(file_handle, events=("start", "end")):
                tag = get_tag(element)
                # Groups live in the header, before <run>; stop as soon as spectra begin.
                if event == "start" and tag in ("run", "spectrumList", "chromatogramList", "spectrum", "chromatogram"):
                    break
                if event == "end" and tag == "referenceableParamGroup":
                    gid = element.get("id")
                    if gid is not None:
                        templates[gid] = [
                            (get_tag(child), dict(child.attrib))
                            for child in element
                            if get_tag(child) in ("cvParam", "userParam")
                        ]
                    element.clear()
        finally:
            file_handle.close()
        return templates

    def _expand_param_group_refs(self, element: ET.Element) -> ET.Element:
        """Resolve ``referenceableParamGroupRef`` in place, then return the element.

        For every element in the subtree that references a param group, the group's cvParam /
        userParam terms are inserted as direct children (skipping ones already present, so a
        directly-specified term wins and nothing is duplicated). The ref node is left in place so
        provenance is preserved and the operation is idempotent.
        """
        return expand_param_group_refs(element, self._param_group_templates)

    def get_chromatogram_by_id(self, identifier: str) -> Chromatogram:
        with _parse_errors():
            mzml_element = self.file_handler.get_chromatogram_by_id(identifier)
            self._expand_param_group_refs(mzml_element.element)
        return _convert_mzml_element_to_object(mzml_element)

    def get_chromatogram_by_index(self, index: int) -> Chromatogram:
        with _parse_errors():
            mzml_element = self.file_handler.get_chromatogram_by_index(index)
            self._expand_param_group_refs(mzml_element.element)
        return _convert_mzml_element_to_object(mzml_element)

    def get_spectrum_by_id(self, identifier: str) -> Spectrum:
        with _parse_errors():
            mzml_element = self.file_handler.get_spectrum_by_id(identifier)
            self._expand_param_group_refs(mzml_element.element)
        return _convert_mzml_element_to_object(mzml_element)

    def get_spectrum_by_index(self, index: int) -> Spectrum:
        with _parse_errors():
            mzml_element = self.file_handler.get_spectrum_by_index(index)
            self._expand_param_group_refs(mzml_element.element)
        return _convert_mzml_element_to_object(mzml_element)

    @overload
    def _iter_xml_elements(self, tag_suffix: Literal["spectrum"]) -> Iterator[SpectrumElement]: ...

    @overload
    def _iter_xml_elements(self, tag_suffix: Literal["chromatogram"]) -> Iterator[ChromatogramElement]: ...

    def _iter_xml_elements(
        self, tag_suffix: Literal["spectrum", "chromatogram"]
    ) -> Iterator[SpectrumElement] | Iterator[ChromatogramElement]:
        """Iterate the records of one kind; close() stops the iterator and releases its handle."""
        iterator = self._track(self._iter_xml_elements_untracked(tag_suffix))
        return cast("Iterator[SpectrumElement] | Iterator[ChromatogramElement]", iterator)

    def _iter_xml_elements_untracked(
        self, tag_suffix: Literal["spectrum", "chromatogram"]
    ) -> Iterator[SpectrumElement] | Iterator[ChromatogramElement]:
        """Iterate with a private handle and bounded memory for either record kind.

        Indexed backends parse each record's byte span in one C-level call. At the first span
        that is not exactly the indexed record, iteration continues with the streaming parser
        from the same position, which also reports any error in context.
        """
        skip = 0
        backend = self.file_handler
        if isinstance(backend, AbstractRandomAccessMzml) and backend.can_iterate_indexed(tag_suffix):
            for indexed in backend.iter_indexed(tag_suffix):
                if indexed is None:
                    break
                skip += 1
                if tag_suffix == "spectrum":
                    yield MzmlXMLElement(element=indexed, element_type="spectrum")
                else:
                    yield MzmlXMLElement(element=indexed, element_type="chromatogram")
            else:
                return
        with _parse_errors(), self.file_handler.get_file_handler(self.encoding) as handle:
            for element in islice(iter_records(handle, tag_suffix), skip, None):
                if tag_suffix == "spectrum":
                    yield MzmlXMLElement(element=element, element_type="spectrum")
                else:
                    yield MzmlXMLElement(element=element, element_type="chromatogram")

    def iter_spectra(self) -> Iterator[Spectrum]:
        """Iterate over all spectra in the file."""
        for mzml_element in self._iter_xml_elements("spectrum"):
            yield Spectrum(self._expand_param_group_refs(mzml_element.element))

    def can_read_spectrum_heads(self) -> bool:
        """Whether :meth:`iter_spectrum_heads` is supported: an indexed, ASCII-compatible file
        whose index lists every spectrum (plain, rapidgzip and in-memory readers)."""
        backend = self.file_handler
        return isinstance(backend, AbstractRandomAccessMzml) and backend.can_iterate_indexed("spectrum")

    def iter_spectrum_heads(self) -> Iterator[bytes | None] | None:
        """Each spectrum's bytes before its binary arrays, in index order, or None if unsupported.

        Only indexed, ASCII-compatible files whose index lists every spectrum support this. An
        item is None where a record's head could not be cut out; read that record in full.
        """
        backend = self.file_handler
        if not (self.can_read_spectrum_heads() and isinstance(backend, AbstractRandomAccessMzml)):
            return None
        return self._track(backend.iter_spectrum_heads())

    def iter_chromatograms(self) -> Iterator[Chromatogram]:
        """Iterate over all chromatograms in the file."""
        for mzml_element in self._iter_xml_elements("chromatogram"):
            yield Chromatogram(self._expand_param_group_refs(mzml_element.element))

    def total_ion_chromatogram(self) -> Chromatogram | None:
        """Return the total ion chromatogram, or None if the file has none.

        The conventional id ``"TIC"`` is tried first; if that is absent, chromatograms are searched
        for the one carrying the "total ion current chromatogram" CV term (MS:1000235), since the
        id spelling varies by writer (e.g. ``"tic"``).
        """
        try:
            return self.get_chromatogram_by_id("TIC")
        except KeyError:
            for cid in self.chromatogram_ids:
                chromatogram = self.get_chromatogram_by_id(cid)
                if chromatogram.has_cv_param(ChromatogramTypeAccession.TOTAL_ION_CURRENT):
                    return chromatogram
            return None

    @property
    def spectrum_ids(self) -> list[str]:
        """All spectrum IDs from the file index."""
        with _parse_errors():
            return self.file_handler.spectrum_ids

    @property
    def chromatogram_ids(self) -> list[str]:
        """All chromatogram IDs from the file index."""
        with _parse_errors():
            return self.file_handler.chromatogram_ids

    @property
    def spectrum_count(self) -> int | None:
        """Count of spectra in the file, if determinable."""
        with _parse_errors():
            return self.file_handler.spectrum_count

    @property
    def chromatogram_count(self) -> int | None:
        """Count of chromatograms in the file, if determinable."""
        with _parse_errors():
            return self.file_handler.chromatogram_count


__all__ = ["AccessStrategy"]
