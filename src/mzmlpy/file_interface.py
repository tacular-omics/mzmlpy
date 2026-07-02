#!/usr/bin/env python3
"""Interface for different mzML file formats."""

import hashlib
import logging
import os
import tempfile
from collections.abc import Iterator
from functools import cached_property
from io import BytesIO
from pathlib import Path
from re import Pattern
from typing import Literal, overload
from xml.etree import ElementTree as ET

from .constants import ChromatogramTypeAccession
from .file_classes import (
    BytesMzml,
    ChromatogramElement,
    IndexedGzip,
    MzmlInterface,
    MzmlXMLElement,
    SpectrumElement,
    StandardGzip,
    StandardMzml,
)
from .spectra import Chromatogram, Spectrum
from .util import atomic_write_path, cache_is_current, get_tag, gzip_decompress, write_cache_signature

logger = logging.getLogger(__name__)


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
        path: str | Path | BytesIO,
        encoding: str,
        build_index_from_scratch: bool = False,
        index_regex: Pattern[bytes] | None = None,
        gzip_mode: Literal["extract", "indexed", "stream"] = "extract",
        in_memory: bool = False,
        extract_dir: str | None = None,
    ) -> None:
        """Initialize FileInterface with path and encoding options."""
        self.build_index_from_scratch: bool = build_index_from_scratch
        self.encoding: str = encoding
        self.index_regex: Pattern[bytes] | None = index_regex
        self.gzip_mode: Literal["extract", "indexed", "stream"] = gzip_mode
        self.in_memory: bool = in_memory
        self._extract_dir: str | None = extract_dir
        self.file_handler: MzmlInterface = self._open(path)

    def close(self) -> None:
        """Close the internal file handler."""
        self.file_handler.close()

    def _open(self, path_or_file: str | Path | BytesIO) -> MzmlInterface:
        """Open appropriate file handler based on file type and format."""
        # Handle BytesIO objects
        if isinstance(path_or_file, BytesIO):
            return BytesMzml(
                path_or_file,
                self.encoding,
                self.build_index_from_scratch,
            )

        # Convert Path to string
        path = str(path_or_file) if isinstance(path_or_file, Path) else path_or_file

        # Handle in_memory mode - load entire file into memory
        if self.in_memory:
            if path.endswith(".gz"):
                # Decompress gzipped file into memory
                content = gzip_decompress(path)
            else:
                # Read uncompressed file into memory
                with open(path, "rb") as f:
                    content = f.read()

            return BytesMzml(
                BytesIO(content),
                self.encoding,
                self.build_index_from_scratch,
            )

        # Handle gzipped files
        if path.endswith(".gz"):
            if self.gzip_mode == "extract":
                extracted_path = self._get_extract_path(path)
                if cache_is_current(extracted_path, path):
                    logger.debug("Using cached extraction: %s", extracted_path)
                else:
                    logger.debug("Extracting %s to %s", path, extracted_path)
                    # Atomic write so an interrupted extraction never leaves a truncated .mzML that
                    # the currency check would then treat as a valid cache.
                    with atomic_write_path(extracted_path) as tmp_path, open(tmp_path, "wb") as f_out:
                        f_out.write(gzip_decompress(path))
                    write_cache_signature(extracted_path, path)

                return StandardMzml(
                    extracted_path,
                    self.encoding,
                    self.build_index_from_scratch,
                    index_regex=self.index_regex,
                )
            elif self.gzip_mode == "indexed":
                return IndexedGzip(
                    path,
                    self.encoding,
                    self.build_index_from_scratch,
                    index_regex=self.index_regex,
                )
            else:
                return StandardGzip(path, self.encoding)

        # Handle standard mzML files
        return StandardMzml(
            path,
            self.encoding,
            self.build_index_from_scratch,
            index_regex=self.index_regex,
        )

    def _get_extract_path(self, gz_path: str) -> str:
        """Return the path for the extracted mzML file.

        If ``extract_dir`` was provided, uses that directory with the original
        filename (minus ``.gz``). Otherwise, uses ``<tmpdir>/mzmlpy/`` with a
        hash-based filename to avoid collisions.
        """
        if self._extract_dir is not None:
            os.makedirs(self._extract_dir, exist_ok=True)
            filename = Path(gz_path).name.removesuffix(".gz")
            return os.path.join(self._extract_dir, filename)

        cache_dir = os.path.join(tempfile.gettempdir(), "mzmlpy")
        os.makedirs(cache_dir, exist_ok=True)
        path_hash = hashlib.sha256(os.path.abspath(gz_path).encode()).hexdigest()[:16]
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
        templates = self._param_group_templates
        if not templates:
            return element

        targets = [
            (el, [ref.get("ref") for ref in el if get_tag(ref) == "referenceableParamGroupRef"])
            for el in element.iter()
        ]
        for el, group_ids in targets:
            if not group_ids:
                continue
            ns = el.tag[: el.tag.index("}") + 1] if "}" in el.tag else ""
            seen_cv = {c.get("accession") for c in el if get_tag(c) == "cvParam"}
            seen_user = {c.get("name") for c in el if get_tag(c) == "userParam"}
            for gid in group_ids:
                if gid is None:
                    continue
                for local_name, attrib in templates.get(gid, []):
                    if local_name == "cvParam":
                        if attrib.get("accession") in seen_cv:
                            continue
                        seen_cv.add(attrib.get("accession"))
                    else:
                        if attrib.get("name") in seen_user:
                            continue
                        seen_user.add(attrib.get("name"))
                    ET.SubElement(el, f"{ns}{local_name}", dict(attrib))
        return element

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
        """Iterate over XML elements with a specific tag suffix.

        Uses ``start``/``end`` events to track each element's parent so that, after an element is
        yielded, it can be detached from the tree with ``parent.remove(...)``. This keeps peak
        memory bounded — the container element does not accumulate every parsed spectrum as
        iteration proceeds — while the yielded element stays fully intact and usable even after
        iteration advances (e.g. ``list(reader.spectra)`` or a deferred ``spectrum.mz``).
        ``element.clear()`` would instead empty a spectrum the caller is still holding.
        """
        # Get a fresh file handle for iteration
        file_handle = self.file_handler.get_file_handler(self.encoding)
        try:
            # We must seek to 0 for a fresh iterator
            # Note: get_file_handler usually returns a new handle at pos 0,
            # but seeking ensures it for implementations that might recycle handles.
            if hasattr(file_handle, "seek"):
                file_handle.seek(0)

            # Stack of currently-open elements: pushed on "start", popped on "end". After popping a
            # matched element, the new top of the stack is its parent.
            open_elements: list[ET.Element] = []
            for event, element in ET.iterparse(file_handle, events=("start", "end")):
                if event == "start":
                    open_elements.append(element)
                    continue

                # end event
                open_elements.pop()
                if get_tag(element) != tag_suffix:
                    continue

                if tag_suffix == "spectrum":
                    yield MzmlXMLElement(element=element, element_type="spectrum")
                else:
                    yield MzmlXMLElement(element=element, element_type="chromatogram")

                # Detach the just-yielded (and now consumed) element from its parent so the
                # container does not keep growing. The element itself is unaffected and remains
                # fully usable through the reference the caller now holds.
                if open_elements:
                    open_elements[-1].remove(element)
        finally:
            file_handle.close()

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
