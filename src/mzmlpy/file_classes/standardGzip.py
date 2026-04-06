import warnings
from functools import cached_property
from typing import TextIO
from xml.etree.ElementTree import iterparse

from .. import regex_patterns
from ..util import gzip_open_text
from .interface import MzmlInterface
from .xml_tuple import ChromatogramElement, MzmlXMLElement, SpectrumElement

_STREAM_WARNING = (
    "Random access on gzip_mode='stream' requires scanning the file from the beginning "
    "for every access. Use gzip_mode='extract' or gzip_mode='indexed' for efficient random access."
)


class StandardGzip(MzmlInterface):
    def __init__(self, path: str, encoding: str) -> None:
        self.path: str = path
        self._encoding: str = encoding
        self.file_handler: TextIO = gzip_open_text(path, encoding=encoding)

    def close(self) -> None:
        self.file_handler.close()

    def get_file_handler(self, encoding: str) -> TextIO:
        """Return a fresh decompressed text file handler."""
        return gzip_open_text(self.path, encoding=encoding)

    def read(self, size: int = -1) -> str:
        """Read data from file. Default (-1) reads entire file."""
        return self.file_handler.read(size)

    def get_spectrum_by_id(self, identifier: str | int) -> SpectrumElement:
        """Retrieve spectrum by native ID.

        Warning:
            This scans the file from the beginning on every call.
            Use ``gzip_mode='extract'`` or ``gzip_mode='indexed'`` for
            efficient random access.

        Args:
            identifier: Spectrum ID (string) or integer.

        Raises:
            KeyError: If ID is not found.
        """
        warnings.warn(_STREAM_WARNING, stacklevel=2)
        if isinstance(identifier, int):
            identifier = str(identifier)

        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler(self._encoding)
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

        Warning:
            This scans the file from the beginning on every call.

        Args:
            index: 0-based index in spectrum list.

        Raises:
            IndexError: If index is out of range.
        """
        warnings.warn(_STREAM_WARNING, stacklevel=2)
        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler(self._encoding)
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

        Warning:
            This scans the file from the beginning on every call.

        Args:
            identifier: Chromatogram ID (string) or integer.

        Raises:
            KeyError: If ID is not found.
        """
        warnings.warn(_STREAM_WARNING, stacklevel=2)
        if isinstance(identifier, int):
            identifier = str(identifier)

        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler(self._encoding)
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

        Warning:
            This scans the file from the beginning on every call.

        Args:
            index: 0-based index in chromatogram list.

        Raises:
            IndexError: If index is out of range.
        """
        warnings.warn(_STREAM_WARNING, stacklevel=2)
        # Can't seek in gzip, so need fresh handle
        fh = self.get_file_handler(self._encoding)
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
    def _ids(self) -> tuple[list[str], list[str]]:
        """Scan the file once to build spectrum and chromatogram ID lists."""
        spec_ids: list[str] = []
        chrom_ids: list[str] = []
        fh = self.get_file_handler(self._encoding)
        for _, element in iterparse(fh, events=["end"]):
            if element.tag.endswith("}spectrum"):
                elem_id = element.get("id")
                if elem_id:
                    spec_ids.append(elem_id)
                element.clear()
            elif element.tag.endswith("}chromatogram"):
                elem_id = element.get("id")
                if elem_id:
                    chrom_ids.append(elem_id)
                element.clear()
        fh.close()
        return spec_ids, chrom_ids

    @property
    def spectrum_ids(self) -> list[str]:
        """All spectrum IDs (requires one full file scan, then cached)."""
        return self._ids[0]

    @property
    def chromatogram_ids(self) -> list[str]:
        """All chromatogram IDs (requires one full file scan, then cached)."""
        return self._ids[1]

    @cached_property
    def spectrum_count(self) -> int | None:
        """Count of spectra in the file."""
        return len(self.spectrum_ids)

    @cached_property
    def chromatogram_count(self) -> int | None:
        """Count of chromatograms in the file."""
        return len(self.chromatogram_ids)
