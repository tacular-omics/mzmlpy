#!/usr/bin/env python3
"""Interface for different mzML file formats."""

import gzip
import tempfile
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from re import Pattern
from typing import Literal, overload
from xml.etree import ElementTree as ET

from .file_classes import (
    BytesMzml,
    ChromatogramElement,
    MzmlInterface,
    MzmlXMLElement,
    SpectrumElement,
    StandardGzip,
    StandardMzml,
)
from .spectra import Chromatogram, Spectrum


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
        extract_gzip: bool = True,
        in_memory: bool = False,
    ) -> None:
        """Initialize FileInterface with path and encoding options."""
        self.build_index_from_scratch: bool = build_index_from_scratch
        self.encoding: str = encoding
        self.index_regex: Pattern[bytes] | None = index_regex
        self.extract_gzip: bool = extract_gzip
        self.in_memory: bool = in_memory
        self.temp_file = None
        self.file_handler: MzmlInterface = self._open(path)

    def close(self) -> None:
        """Close the internal file handler."""
        self.file_handler.close()
        if self.temp_file is not None:
            self.temp_file.close()

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
                with gzip.open(path, "rb") as f:
                    content = f.read()
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
            # Extract gzip to temporary file if requested
            if self.extract_gzip:
                self.temp_file = tempfile.NamedTemporaryFile(mode="w+b", suffix=".mzML", delete=False)
                with gzip.open(path, "rb") as f_in:
                    self.temp_file.write(f_in.read())
                self.temp_file.flush()

                return StandardMzml(
                    self.temp_file.name,
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

    def read(self, size: int = -1) -> bytes | str:
        """Read binary data from file handler (size=-1 reads to end)."""
        return self.file_handler.read(size)

    def get_chromatogram_by_id(self, identifier: str) -> Chromatogram:
        chromatogram = convert_mzml_element_to_object(
            self.file_handler.get_chromatogram_by_id(identifier),
        )
        return chromatogram

    def get_chromatogram_by_index(self, index: int) -> Chromatogram:
        chromatogram = convert_mzml_element_to_object(
            self.file_handler.get_chromatogram_by_index(index),
        )
        return chromatogram

    def get_spectrum_by_id(self, identifier: str) -> Spectrum:
        spectrum = convert_mzml_element_to_object(
            self.file_handler.get_spectrum_by_id(identifier),
        )
        return spectrum

    def get_spectrum_by_index(self, index: int) -> Spectrum:
        spectrum = convert_mzml_element_to_object(
            self.file_handler.get_spectrum_by_index(index),
        )
        return spectrum

    @overload
    def _iter_xml_elements(self, tag_suffix: Literal["spectrum"]) -> Iterator[SpectrumElement]: ...

    @overload
    def _iter_xml_elements(self, tag_suffix: Literal["chromatogram"]) -> Iterator[ChromatogramElement]: ...

    def _iter_xml_elements(
        self, tag_suffix: Literal["spectrum", "chromatogram"]
    ) -> Iterator[SpectrumElement] | Iterator[ChromatogramElement]:
        """Iterate over XML elements with specific tag suffix."""
        # Get a fresh file handle for iteration
        file_handle = self.file_handler.get_file_handler(self.encoding)
        try:
            # We must seek to 0 for a fresh iterator
            # Note: get_file_handler usually returns a new handle at pos 0,
            # but seeking ensures it for implementations that might recycle handles.
            if hasattr(file_handle, "seek"):
                file_handle.seek(0)

            # Type hint needed for iterparse iterator
            mzml_iter: Iterator[tuple[str, ET.Element]] = iter(ET.iterparse(file_handle, events=("end",)))

            for event, element in mzml_iter:
                if event == "end":
                    # Extract tag suffix for matching
                    tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
                    if tag == tag_suffix:
                        # Create properly typed MzmlXMLElement
                        if tag_suffix == "spectrum":
                            yield MzmlXMLElement(element=element, element_type="spectrum")
                        else:
                            yield MzmlXMLElement(element=element, element_type="chromatogram")
        finally:
            file_handle.close()

    def iter_spectra(self) -> Iterator[Spectrum]:
        """Iterate over all spectra in the file."""
        for mzml_element in self._iter_xml_elements("spectrum"):
            yield Spectrum(mzml_element.element)

    def iter_chromatograms(self) -> Iterator[Chromatogram]:
        """Iterate over all chromatograms in the file."""
        for mzml_element in self._iter_xml_elements("chromatogram"):
            yield Chromatogram(mzml_element.element)

    @property
    def TIC(self) -> Chromatogram:
        """Retrieve the Total Ion Chromatogram (TIC)."""
        return self.get_chromatogram_by_id("TIC")

    @property
    def spectrum_count(self) -> int | None:
        """Count of spectra in the file, if determinable."""
        return self.file_handler.spectrum_count

    @property
    def chromatogram_count(self) -> int | None:
        """Count of chromatograms in the file, if determinable."""
        return self.file_handler.chromatogram_count
