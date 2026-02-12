import gzip
from functools import cached_property
from typing import TextIO
from xml.etree.ElementTree import iterparse

from .. import regex_patterns
from .interface import MzmlInterface
from .xml_tuple import ChromatogramElement, MzmlXMLElement, SpectrumElement


class StandardGzip(MzmlInterface):
    def __init__(self, path: str, encoding: str) -> None:
        self.path: str = path
        self.file_handler: TextIO = gzip.open(path, "rt", encoding=encoding)

    def close(self) -> None:
        self.file_handler.close()

    def get_file_handler(self, encoding: str) -> TextIO:
        """Return a fresh decompressed text file handler."""
        return gzip.open(self.path, "rt", encoding=encoding)

    def read(self, size: int = -1) -> str:
        """Read data from file. Default (-1) reads entire file."""
        return self.file_handler.read(size)

    def get_spectrum_by_id(self, identifier: str | int) -> SpectrumElement:
        """Retrieve spectrum by native ID.

        Args:
            identifier: Spectrum ID (string) or integer.

        Raises:
            KeyError: If ID is not found.
        """
        if isinstance(identifier, int):
            identifier = str(identifier)

        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler("utf-8")
        mzml_iter = iterparse(fh, events=["end"])

        for event, element in mzml_iter:
            if event == "end" and element.tag.endswith("}spectrum"):
                elem_id = element.get("id")
                if elem_id:
                    # Direct string match
                    if elem_id == identifier:
                        fh.close()
                        return MzmlXMLElement(element=element, element_type="spectrum")
                    # Try numeric ID extraction (pattern works on strings)
                    match = regex_patterns.SPECTRUM_ID_PATTERN.search(elem_id)
                    if match and match.group(1) == identifier:
                        fh.close()
                        return MzmlXMLElement(element=element, element_type="spectrum")

        fh.close()
        raise KeyError(f"Spectrum ID {identifier} not found in file")

    def get_spectrum_by_index(self, index: int) -> SpectrumElement:
        """Retrieve spectrum by 0-based index.

        Args:
            index: 0-based index in spectrum list.

        Raises:
            IndexError: If index is out of range.
        """
        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler("utf-8")
        mzml_iter = iterparse(fh, events=["end"])

        current_index = 0

        for event, element in mzml_iter:
            if event == "end" and element.tag.endswith("}spectrum"):
                if current_index == index:
                    fh.close()
                    return MzmlXMLElement(element=element, element_type="spectrum")
                current_index += 1

        fh.close()
        raise IndexError(f"Spectrum index {index} out of range [0, {current_index})")

    def get_chromatogram_by_id(self, identifier: str | int) -> ChromatogramElement:
        """Retrieve chromatogram by native ID.

        Args:
            identifier: Chromatogram ID (string) or integer.

        Raises:
            KeyError: If ID is not found.
        """
        if isinstance(identifier, int):
            identifier = str(identifier)

        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler("utf-8")
        mzml_iter = iterparse(fh, events=["end"])

        for event, element in mzml_iter:
            if event == "end" and element.tag.endswith("}chromatogram"):
                elem_id = element.get("id")
                if elem_id and elem_id == identifier:
                    fh.close()
                    return MzmlXMLElement(element=element, element_type="chromatogram")

        fh.close()
        raise KeyError(f"Chromatogram ID {identifier} not found in file")

    def get_chromatogram_by_index(self, index: int) -> ChromatogramElement:
        """Retrieve chromatogram by 0-based index.

        Args:
            index: 0-based index in chromatogram list.

        Raises:
            IndexError: If index is out of range.
        """
        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler("utf-8")
        mzml_iter = iterparse(fh, events=["end"])

        current_index = 0

        for event, element in mzml_iter:
            if event == "end" and element.tag.endswith("}chromatogram"):
                if current_index == index:
                    fh.close()
                    return MzmlXMLElement(element=element, element_type="chromatogram")
                current_index += 1

        fh.close()
        raise IndexError(f"Chromatogram index {index} out of range [0, {current_index})")

    @property
    def TIC(self) -> ChromatogramElement:
        """Retrieve the Total Ion Chromatogram (TIC)."""
        return self.get_chromatogram_by_id("TIC")

    @cached_property
    def spectrum_count(self) -> int | None:
        """Count of spectra in the file, if determinable."""
        count = 0
        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler("utf-8")
        mzml_iter = iterparse(fh, events=["end"])

        for event, element in mzml_iter:
            if event == "end" and element.tag.endswith("}spectrum"):
                count += 1

        fh.close()
        return count

    @cached_property
    def chromatogram_count(self) -> int | None:
        """Count of chromatograms in the file, if determinable."""
        count = 0
        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler("utf-8")
        mzml_iter = iterparse(fh, events=["end"])

        for event, element in mzml_iter:
            if event == "end" and element.tag.endswith("}chromatogram"):
                count += 1

        fh.close()
        return count
