import logging
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from functools import cached_property
from io import BytesIO, TextIOWrapper
from re import Pattern
from typing import BinaryIO, TextIO
from xml.etree.ElementTree import XML

from .. import regex_patterns
from .interface import MzmlInterface
from .xml_tuple import ChromatogramElement, MzmlXMLElement, SpectrumElement

logger = logging.getLogger(__name__)


class AbstractRandomAccessMzml(MzmlInterface, ABC):
    """Abstract base class for random-access mzML file readers."""

    def __init__(
        self,
        encoding: str,
        build_index_from_scratch: bool = False,
        index_regex: Pattern[bytes] | None = None,
    ) -> None:
        self.index_regex: Pattern[bytes] | None = index_regex

        self.spectrum_offsets: OrderedDict[str, int] = OrderedDict()
        self.chromatogram_offsets: OrderedDict[str, int] = OrderedDict()
        self._spectrum_keys: list[str] = []  # For fast O(1) index access
        self._chromatogram_keys: list[str] = []  # For fast O(1) index access

        self.file_handler: TextIO = self.get_file_handler(encoding)
        self._build_index(from_scratch=build_index_from_scratch)

    @abstractmethod
    def get_binary_file_handler(self) -> BinaryIO:
        """Return a binary file handler positioned at the start."""
        pass

    @abstractmethod
    def get_file_handler(self, encoding: str) -> TextIO:
        """Return a text file handler positioned at the start."""
        pass

    def get_spectrum_by_id(self, identifier: str | int) -> SpectrumElement:
        """Retrieve spectrum by native ID.

        Args:
            identifier: Spectrum ID (string) or integer.

        Raises:
            KeyError: If ID is not found.
        """
        if isinstance(identifier, int):
            identifier = str(identifier)

        if identifier not in self.spectrum_offsets:
            raise KeyError(f"Spectrum ID {identifier} not found in index")

        offset = self.spectrum_offsets[identifier]
        seeker = self.get_binary_file_handler()
        try:
            seeker.seek(offset)
            _, end_pos = self._read_to_spec_end(seeker)
        finally:
            seeker.close()

        self.file_handler.seek(offset, 0)
        data = self.file_handler.read(end_pos - offset)

        try:
            return MzmlXMLElement(XML(data), element_type="spectrum")
        except Exception as e:
            raise ValueError(f"Error parsing spectrum with ID {identifier} at offset {offset}: {e}") from e

    def get_spectrum_by_index(self, index: int) -> SpectrumElement:
        """Retrieve spectrum by 0-based index.

        Args:
            index: 0-based index in spectrum list.

        Raises:
            IndexError: If index is out of range.
        """
        if not (0 <= index < len(self._spectrum_keys)):
            raise IndexError(f"Spectrum index {index} out of range [0, {len(self._spectrum_keys)})")

        key = self._spectrum_keys[index]
        return self.get_spectrum_by_id(key)

    def get_chromatogram_by_id(self, identifier: str | int) -> ChromatogramElement:
        """Retrieve chromatogram by native ID.

        Args:
            identifier: Chromatogram ID (string) or integer.

        Raises:
            KeyError: If ID is not found.
        """
        if isinstance(identifier, int):
            identifier = str(identifier)

        if identifier not in self.chromatogram_offsets:
            raise KeyError(f"Chromatogram ID {identifier} not found in index")

        offset = self.chromatogram_offsets[identifier]
        seeker = self.get_binary_file_handler()
        try:
            seeker.seek(offset)
            _, end_pos = self._read_to_spec_end(seeker)
        finally:
            seeker.close()

        self.file_handler.seek(offset, 0)
        data = self.file_handler.read(end_pos - offset)

        print(identifier, data[:100])

        return MzmlXMLElement(XML(data), element_type="chromatogram")

    def get_chromatogram_by_index(self, index: int) -> ChromatogramElement:
        """Retrieve chromatogram by 0-based index.

        Args:
            index: 0-based index in chromatogram list.

        Raises:
            IndexError: If index is out of range.
        """
        try:
            key = self._chromatogram_keys[index]
        except IndexError as e:
            raise IndexError(f"Chromatogram index {index} out of range [0, {len(self._chromatogram_keys)})") from e
        return self.get_chromatogram_by_id(key)

    def _build_index(self, from_scratch: bool = False) -> None:
        """Build index of spectrum/chromatogram offsets from file.

        Reads index from file footer if available, otherwise parses entire file.
        """
        seeker = self.get_binary_file_handler()

        try:
            if from_scratch or not (index_offset := self._find_index_offset(seeker)):
                self._build_index_from_scratch(seeker)
                return

            try:
                self._parse_index_section(seeker, index_offset)
                self._finalize_index()
            except Exception as e:
                logger.warning(f"Error reading index: {e}. Building from scratch.")
                seeker.seek(0)
                self._build_index_from_scratch(seeker)

        finally:
            seeker.close()

    def _find_index_offset(self, seeker: BinaryIO) -> int | None:
        """Find indexListOffset in file footer, return None if not found."""
        seeker.seek(0, 2)
        file_size = seeker.tell()
        search_start = max(0, file_size - 10240)  # Last 10KB

        seeker.seek(search_start)
        footer_data = seeker.read()

        if match := regex_patterns.INDEX_LIST_OFFSET_PATTERN.search(footer_data):
            return int(match.group("indexListOffset").decode("utf-8"))

        logger.warning("No index found, building from scratch for random access support")
        return None

    def _parse_index_section(self, seeker: BinaryIO, index_offset: int) -> None:
        """Parse the index section and populate offset dictionaries."""
        seeker.seek(index_offset, 0)

        current_index_type = None
        offset_pattern = re.compile(rb'<offset idRef="([^"]*)"[^>]*>(\d+)</offset>')
        index_name_pattern = re.compile(rb'<index name="([^"]*)">')

        for line in seeker:
            if b"</indexList>" in line:
                break

            # Check for new index section
            if name_match := index_name_pattern.search(line):
                current_index_type = name_match.group(1).decode("utf-8")
                continue

            # Parse offset entry
            if (offset_match := offset_pattern.search(line)) and current_index_type:
                self._add_offset_entry(
                    current_index_type,
                    offset_match.group(1).decode("utf-8"),
                    int(offset_match.group(2).decode("utf-8")),
                )

    def _add_offset_entry(self, index_type: str, native_id: str, offset: int) -> None:
        """Add an offset entry to the appropriate dictionary with duplicate checking."""
        if index_type == "spectrum":
            if native_id in self.spectrum_offsets:
                raise ValueError(f"Duplicate spectrum ID found in index: {native_id}")
            self.spectrum_offsets[native_id] = offset

        elif index_type == "chromatogram":
            if native_id in self.chromatogram_offsets:
                raise ValueError(f"Duplicate chromatogram ID found in index: {native_id}")
            self.chromatogram_offsets[native_id] = offset

    def _finalize_index(self) -> None:
        """Build key lists for fast index access."""
        self._spectrum_keys = list(self.spectrum_offsets.keys())
        self._chromatogram_keys = list(self.chromatogram_offsets.keys())
        self._validate_unique_offsets()

    def _validate_unique_offsets(self) -> None:
        """Ensure no offsets are shared between or within spectrum/chromatogram indices."""
        # Check for duplicates within spectra
        spectrum_offset_values = list(self.spectrum_offsets.values())
        if len(spectrum_offset_values) != len(set(spectrum_offset_values)):
            raise ValueError("Duplicate offsets found within spectrum index")

        # Check for duplicates within chromatograms
        chromatogram_offset_values = list(self.chromatogram_offsets.values())
        if len(chromatogram_offset_values) != len(set(chromatogram_offset_values)):
            raise ValueError("Duplicate offsets found within chromatogram index")

        # Check for shared offsets between spectra and chromatograms
        if shared := set(spectrum_offset_values) & set(chromatogram_offset_values):
            raise ValueError(f"Offsets shared between spectra and chromatograms: {sorted(shared)}")

    def _build_index_from_scratch(self, seeker: BinaryIO) -> None:
        """Build index by parsing the file for spectrum/chromatogram elements."""

        def get_data_indices(
            fh: BinaryIO, chunksize: int = 8192, lookback_size: int = 100
        ) -> tuple[dict[str, int], dict[str, int]]:
            """Find binary offsets of all spectra and chromatograms.

            Uses regex instead of XML parser to capture exact file positions.

            Returns:
                Tuple of (chrom_positions, spec_positions) dictionaries.
            """
            chrom_positions: dict[str, int] = {}
            spec_positions: dict[str, int] = {}

            chromcnt = 0
            speccnt = 0
            chromexp: Pattern[bytes] = re.compile(b'<\\s*chromatogram[^>]*id="([^"]*)"')
            chromcntexp: Pattern[bytes] = re.compile(b'<\\s*chromatogramList\\s*count="([^"]*)"')
            specexp: Pattern[bytes] = re.compile(b'<\\s*spectrum[^>]*id="([^"]*)"')
            speccntexp: Pattern[bytes] = re.compile(b'<\\s*spectrumList\\s*count="([^"]*)"')
            fh.seek(0)
            prev_chunk = ""
            while True:
                offset: int = fh.tell()
                chunk: bytes = fh.read(chunksize)
                if not chunk:
                    break

                if len(prev_chunk) > 0:
                    chunk = prev_chunk[-lookback_size:] + chunk
                    offset -= lookback_size

                prev_chunk = chunk

                for m in chromexp.finditer(chunk):
                    key = m.group(1).decode("utf-8")
                    value = offset + m.start()
                    chrom_positions[key] = value

                for m in specexp.finditer(chunk):
                    key = m.group(1).decode("utf-8")
                    value = offset + m.start()
                    spec_positions[key] = value

                m = chromcntexp.search(chunk)
                if m is not None:
                    chromcnt = int(m.group(1))
                m = speccntexp.search(chunk)
                if m is not None:
                    speccnt = int(m.group(1))

            if chromcnt != len(chrom_positions) or speccnt != len(spec_positions):
                print(
                    f"[Warning] Found {len(spec_positions)} spectra and "
                    f"{len(chrom_positions)} chromatograms; "
                    f"index lists show {speccnt} and {chromcnt} entries."
                )
                print("[Warning] Using found offsets but some may be missing. File may be truncated.")

            return chrom_positions, spec_positions

        chrom_positions, spec_positions = get_data_indices(seeker)

        # Update separate offset dictionaries
        self.chromatogram_offsets.update(chrom_positions)
        self.spectrum_offsets.update(spec_positions)

        # Build keys lists for fast index access
        self._spectrum_keys = list(self.spectrum_offsets.keys())
        self._chromatogram_keys = list(self.chromatogram_offsets.keys())

    def _read_to_spec_end(self, seeker: BinaryIO, chunks_to_read: int = 8) -> tuple[int, int]:
        """Return start and end positions of current spectrum/chromatogram element."""
        chunk_size = 512 * chunks_to_read
        end_found = False
        start_pos = seeker.tell()
        data_chunk = seeker.read(chunk_size)
        end_pos: int | None = None
        while not end_found:
            data_chunk += seeker.read(chunk_size)
            tag_end, seeker = self._read_until_tag_end(seeker)
            data_chunk += tag_end
            match = regex_patterns.SPECTRUM_CLOSE_PATTERN.search(data_chunk)
            if match:
                end_pos = start_pos + match.end()
                end_found = True
            else:
                match = regex_patterns.CHROMATOGRAM_CLOSE_PATTERN.search(data_chunk)
                if match:
                    end_pos = start_pos + match.end()
                    end_found = True
        if end_pos is None:
            raise Exception("Could not find end of spectrum or chromatogram")
        return (start_pos, end_pos)

    def _read_until_tag_end(self, seeker: BinaryIO, max_search_len: int = 12) -> tuple[bytes, BinaryIO]:
        """Read bytes until tag boundary to avoid splitting XML tags in chunks."""
        count = 0
        string = b""
        curr_byte = ""
        while count < max_search_len and curr_byte != b">" and curr_byte != b"<" and curr_byte != b" ":
            curr_byte = seeker.read(1)
            string += curr_byte
            count += 1
        return string, seeker

    def read(self, size: int = -1) -> str:
        """Read data from file. Default (-1) reads entire file."""
        return self.file_handler.read(size)

    def close(self) -> None:
        """Close file handler."""
        self.file_handler.close()

    @property
    def TIC(self) -> ChromatogramElement:
        """Retrieve the Total Ion Chromatogram (TIC)."""
        return self.get_chromatogram_by_id("TIC")

    @cached_property
    def spectrum_count(self) -> int | None:
        """Count of spectra in the file, if determinable."""
        return len(self.spectrum_offsets) if self.spectrum_offsets else None

    @cached_property
    def chromatogram_count(self) -> int | None:
        """Count of chromatograms in the file, if determinable."""
        return len(self.chromatogram_offsets) if self.chromatogram_offsets else None


class StandardMzml(AbstractRandomAccessMzml):
    """Random-access mzML file reader using binary searching and caching."""

    def __init__(
        self,
        path: str,
        encoding: str,
        build_index_from_scratch: bool = False,
        index_regex: Pattern[bytes] | None = None,
    ) -> None:
        self.path: str = path
        super().__init__(encoding, build_index_from_scratch, index_regex)

    def get_binary_file_handler(self) -> BinaryIO:
        return open(self.path, "rb")

    def get_file_handler(self, encoding: str) -> TextIO:
        return open(self.path, encoding=encoding)


class BytesMzml(AbstractRandomAccessMzml):
    """mzML file wrapper for in-memory BytesIO objects."""

    def __init__(self, binary: BytesIO, encoding: str, build_index_from_scratch: bool = False) -> None:
        self.binary: BytesIO = binary
        # Reset position for initial reads
        self.binary.seek(0)
        super().__init__(encoding, build_index_from_scratch)

    def get_binary_file_handler(self) -> BinaryIO:
        return BytesIO(self.binary.getbuffer())

    def get_file_handler(self, encoding: str) -> TextIO:
        return TextIOWrapper(self.get_binary_file_handler(), encoding=encoding)
