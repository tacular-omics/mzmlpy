#!/usr/bin/env python3
"""Interface for different mzML file formats."""

import gzip
import hashlib
import logging
import os
import shutil
import tempfile
import warnings
from collections.abc import Iterator
from enum import StrEnum
from functools import cached_property
from io import BytesIO
from pathlib import Path
from re import Pattern
from typing import BinaryIO, Literal, overload
from xml.etree import ElementTree as ET

from ._xml import iter_records
from .constants import ChromatogramTypeAccession
from .embedded_indexed_gzip import is_embedded_indexed_gzip
from .file_classes import (
    BytesMzml,
    ChromatogramElement,
    EmbeddedIndexedGzip,
    IndexedGzip,
    MzmlInterface,
    MzmlXMLElement,
    SpectrumElement,
    StandardGzip,
    StandardMzml,
    has_cached_indexes,
)
from .spectra import Chromatogram, Spectrum
from .util import (
    atomic_write_path,
    cache_is_current,
    expand_param_group_refs,
    get_tag,
    gzip_decompress,
    gzip_open_binary,
    source_signature,
    write_cache_signature,
)

logger = logging.getLogger(__name__)


class AccessStrategy(StrEnum):
    """Concrete storage strategy selected for an mzML reader."""

    MEMORY = "memory"
    PLAIN = "plain"
    EMBEDDED = "embedded"
    EXTRACTED = "extracted"
    RAPIDGZIP = "rapidgzip"
    STREAM = "stream"


@overload
def convert_mzml_element_to_object(
    mzml_element: SpectrumElement,
) -> Spectrum: ...


@overload
def convert_mzml_element_to_object(
    mzml_element: ChromatogramElement,
) -> Chromatogram: ...


def convert_mzml_element_to_object(
    mzml_element: SpectrumElement | ChromatogramElement,
) -> Spectrum | Chromatogram:
    """Convert MzmlXMLElement to Spectrum or Chromatogram object."""
    if mzml_element.element_type == "spectrum":
        return Spectrum(mzml_element.element)
    elif mzml_element.element_type == "chromatogram":
        return Chromatogram(mzml_element.element)
    else:
        raise ValueError(f"Unknown element_type: {mzml_element.element_type}")


class FileInterface:
    """Interface to different mzML formats."""

    def __init__(
        self,
        path: str | Path | BinaryIO,
        encoding: str,
        build_index_from_scratch: bool = False,
        index_regex: Pattern[bytes] | None = None,
        gzip_mode: Literal["auto", "extract", "indexed", "stream"] = "auto",
        in_memory: bool = False,
        extract_dir: str | None = None,
    ) -> None:
        """Initialize FileInterface with path and encoding options."""
        self.build_index_from_scratch: bool = build_index_from_scratch
        self.encoding: str = encoding
        self.index_regex: Pattern[bytes] | None = index_regex
        if gzip_mode not in {"auto", "extract", "indexed", "stream"}:
            raise ValueError(f"Unsupported gzip_mode: {gzip_mode}")
        self.gzip_mode: Literal["auto", "extract", "indexed", "stream"] = gzip_mode
        self.in_memory: bool = in_memory
        self._extract_dir: str | None = extract_dir
        self.access_strategy: AccessStrategy
        self.file_handler: MzmlInterface = self._open(path)

    def close(self) -> None:
        """Close the internal file handler."""
        self.file_handler.close()

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
                if self.gzip_mode not in {"auto", "extract"}:
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
            if self.gzip_mode == "auto":
                extracted_path = self._get_extract_path(path)
                if cache_is_current(extracted_path, path):
                    self.access_strategy = AccessStrategy.EXTRACTED
                    return self._open_extracted(path, extracted_path)
                if has_cached_indexes(path):
                    self.access_strategy = AccessStrategy.RAPIDGZIP
                    return IndexedGzip(
                        path,
                        self.encoding,
                        self.build_index_from_scratch,
                        index_regex=self.index_regex,
                    )
                self.access_strategy = AccessStrategy.EXTRACTED
                return self._open_extracted(path, extracted_path)
            if self.gzip_mode == "extract":
                self.access_strategy = AccessStrategy.EXTRACTED
                return self._open_extracted(path)
            if self.gzip_mode == "indexed":
                self.access_strategy = AccessStrategy.RAPIDGZIP
                return IndexedGzip(
                    path,
                    self.encoding,
                    self.build_index_from_scratch,
                    index_regex=self.index_regex,
                )
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

    def _open_extracted(self, gz_path: str, extracted_path: str | None = None) -> StandardMzml:
        """Open a current extracted cache, creating it atomically when needed."""
        target = extracted_path or self._get_extract_path(gz_path)
        if cache_is_current(target, gz_path):
            logger.debug("Using cached extraction: %s", target)
        else:
            logger.debug("Extracting %s to %s", gz_path, target)
            signature = source_signature(gz_path)
            with atomic_write_path(target) as temporary_path:
                with open(temporary_path, "wb") as output, gzip_open_binary(gz_path) as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                if source_signature(gz_path) != signature:
                    raise OSError("Source changed during extraction. Reopen the reader to retry.")
            write_cache_signature(target, gz_path, signature)
        return StandardMzml(
            target,
            self.encoding,
            self.build_index_from_scratch,
            index_regex=self.index_regex,
        )

    def _get_extract_path(self, gz_path: str) -> str:
        """Use a source-specific, revision-specific filename in either cache directory."""
        cache_dir = self._extract_dir or os.path.join(tempfile.gettempdir(), "mzmlpy")
        os.makedirs(cache_dir, exist_ok=True)
        path_hash = hashlib.sha256(source_signature(gz_path).encode()).hexdigest()[:24]
        filename = Path(gz_path).stem + f"_{path_hash}.mzML"
        return os.path.join(cache_dir, filename)

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
        mzml_element = self.file_handler.get_chromatogram_by_id(identifier)
        self._expand_param_group_refs(mzml_element.element)
        return convert_mzml_element_to_object(mzml_element)

    def get_chromatogram_by_index(self, index: int) -> Chromatogram:
        mzml_element = self.file_handler.get_chromatogram_by_index(index)
        self._expand_param_group_refs(mzml_element.element)
        return convert_mzml_element_to_object(mzml_element)

    def get_spectrum_by_id(self, identifier: str) -> Spectrum:
        mzml_element = self.file_handler.get_spectrum_by_id(identifier)
        self._expand_param_group_refs(mzml_element.element)
        return convert_mzml_element_to_object(mzml_element)

    def get_spectrum_by_index(self, index: int) -> Spectrum:
        mzml_element = self.file_handler.get_spectrum_by_index(index)
        self._expand_param_group_refs(mzml_element.element)
        return convert_mzml_element_to_object(mzml_element)

    @overload
    def _iter_xml_elements(self, tag_suffix: Literal["spectrum"]) -> Iterator[SpectrumElement]: ...

    @overload
    def _iter_xml_elements(self, tag_suffix: Literal["chromatogram"]) -> Iterator[ChromatogramElement]: ...

    def _iter_xml_elements(
        self, tag_suffix: Literal["spectrum", "chromatogram"]
    ) -> Iterator[SpectrumElement] | Iterator[ChromatogramElement]:
        """Iterate with a private handle and bounded memory for either record kind."""
        with self.file_handler.get_file_handler(self.encoding) as handle:
            for element in iter_records(handle, tag_suffix):
                if tag_suffix == "spectrum":
                    yield MzmlXMLElement(element=element, element_type="spectrum")
                else:
                    yield MzmlXMLElement(element=element, element_type="chromatogram")

    def iter_spectra(self) -> Iterator[Spectrum]:
        """Iterate over all spectra in the file."""
        for mzml_element in self._iter_xml_elements("spectrum"):
            yield Spectrum(self._expand_param_group_refs(mzml_element.element))

    def iter_chromatograms(self) -> Iterator[Chromatogram]:
        """Iterate over all chromatograms in the file."""
        for mzml_element in self._iter_xml_elements("chromatogram"):
            yield Chromatogram(self._expand_param_group_refs(mzml_element.element))

    @property
    def TIC(self) -> Chromatogram:
        """Retrieve the Total Ion Chromatogram (TIC).

        The conventional id ``"TIC"`` is tried first; if that is absent, chromatograms are searched
        for the one carrying the "total ion current chromatogram" CV term (MS:1000235), since the
        id spelling varies by writer (e.g. ``"tic"``). Raises ``KeyError`` if no TIC is present.
        """
        try:
            return self.get_chromatogram_by_id("TIC")
        except KeyError:
            for cid in self.chromatogram_ids:
                chromatogram = self.get_chromatogram_by_id(cid)
                if chromatogram.has_cvparm(ChromatogramTypeAccession.TOTAL_ION_CURRENT):
                    return chromatogram
            raise

    @property
    def spectrum_ids(self) -> list[str]:
        """All spectrum IDs from the file index."""
        return self.file_handler.spectrum_ids

    @property
    def chromatogram_ids(self) -> list[str]:
        """All chromatogram IDs from the file index."""
        return self.file_handler.chromatogram_ids

    @property
    def spectrum_count(self) -> int | None:
        """Count of spectra in the file, if determinable."""
        return self.file_handler.spectrum_count

    @property
    def chromatogram_count(self) -> int | None:
        """Count of chromatograms in the file, if determinable."""
        return self.file_handler.chromatogram_count
