"""
The class :py:class:`Reader` parses mzML files.
"""

import gzip
import os
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from pathlib import Path
from re import Match
from typing import Any, Self

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


# Keep encoding detection methods
def _guess_encoding(mzml_file: Any) -> str:
    """Determine the encoding used for the file."""
    match: Match[bytes] | None = FILE_ENCODING_PATTERN.search(mzml_file.readline())
    return bytes.decode(match.group("encoding")) if match else "utf-8"


def _determine_file_encoding(path: str) -> str:
    """Determine the encoding used for the file in path."""
    if not os.path.exists(path):
        return "utf-8"

    if path.endswith(".gz") or path.endswith(".igz"):
        with gzip.open(path, "rb") as sniffer:
            return _guess_encoding(sniffer)
    else:
        with open(path, "rb") as sniffer:
            return _guess_encoding(sniffer)


class Mzml:
    """
    Reader for mzML files.

    Data is lazily loaded, so only the specific sections of the xml file are parsed. The actual data/properties
    of objects are only parsed when accessed. It's suggested to use the context manager to ensure proper file handling.
    Spectra and Chromatogram properties will return a lookup object for each respectively.

    Parameters
    ----------
    file : Path to the mzML file or a file-like object.
    build_index_from_scratch : Build the index from scratch instead of using existing index.
    extract_gzip : Extract gzip-compressed files before reading.
    in_memory : Load the entire file into memory for faster access.
    """

    def __init__(
        self,
        file: str | Path | Any,
        build_index_from_scratch: bool = False,
        extract_gzip: bool = True,
        in_memory: bool = True,
    ) -> None:
        """Initialize Mzml and parse metadata."""
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
            extract_gzip=extract_gzip,
            in_memory=in_memory,
        )

        # Parse metadata
        self._root, self.iter, builder = self._parse_metadata()
        # Extract parsed content
        self._content: _MzMLContent = builder.build()
        self.obo_version = builder.obo_version

    def _parse_metadata(
        self,
    ) -> tuple[ElementTree.Element, Iterator[tuple[str, ElementTree.Element]], MzMLContentBuilder]:
        """Parse metadata and return root, iterator, and builder."""
        file_handle = self._file_object.file_handler.get_file_handler(self._encoding)

        mzml_iter: Iterator[tuple[str, ElementTree.Element]] = iter(
            ElementTree.iterparse(file_handle, events=("end", "start"))
        )

        _, root = next(mzml_iter)

        # Build metadata
        builder = MzMLContentBuilder()
        builder.parse_from_iterator(mzml_iter)

        root.clear()
        return root, mzml_iter, builder

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
        return SpectrumLookup(file_object=self._file_object)

    @property
    def chromatograms(self) -> ChromatogramLookup:
        """Access chromatograms lookup."""
        return ChromatogramLookup(file_object=self._file_object)

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
        return {cv.id: cv for cv in self._content.cv_list}

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
        return {s.id: s for s in self._content.softwares}

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
        return {s.id: s for s in self._content.samples}

    @property
    def scan_settings(self) -> dict[str, ScanSetting]:
        """Access scan settings."""
        return self._content.scan_settings

    @property
    def run(self) -> Run | None:
        """Access run information."""
        return self._content.run
