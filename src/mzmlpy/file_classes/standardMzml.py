import io
import logging
import warnings
from abc import ABC, abstractmethod
from collections import OrderedDict
from functools import cached_property
from io import BytesIO, TextIOWrapper
from re import Pattern
from typing import BinaryIO, TextIO, cast
from xml.etree.ElementTree import Element, ParseError
from xml.parsers import expat

from .. import regex_patterns
from .._xml import read_fragment, read_header
from ..util import get_tag
from .interface import MzmlInterface
from .xml_tuple import ChromatogramElement, MzmlXMLElement, SpectrumElement

logger = logging.getLogger(__name__)


class _MemoryViewReader(io.RawIOBase):
    def __init__(self, mv: memoryview) -> None:
        super().__init__()
        self._mv = mv
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            size = len(self._mv) - self._pos
        n = min(size, len(self._mv) - self._pos)
        data = bytes(self._mv[self._pos : self._pos + n])
        self._pos += n
        return data

    def readinto(self, b: bytearray) -> int:  # type: ignore[override]
        n = min(len(b), len(self._mv) - self._pos)
        b[:n] = self._mv[self._pos : self._pos + n]
        self._pos += n
        return n

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, pos: int, whence: int = 0) -> int:
        size = len(self._mv)
        if whence == 0:
            self._pos = pos
        elif whence == 1:
            self._pos += pos
        elif whence == 2:
            self._pos = size + pos
        self._pos = max(0, min(self._pos, size))
        return self._pos

    def tell(self) -> int:
        return self._pos

    def close(self) -> None:
        self._mv.release()
        super().close()


class AbstractRandomAccessMzml(MzmlInterface, ABC):
    """Abstract base class for random-access mzML file readers."""

    def __init__(
        self,
        encoding: str,
        build_index_from_scratch: bool = False,
        index_regex: Pattern[bytes] | None = None,
    ) -> None:
        self.index_regex: Pattern[bytes] | None = index_regex
        self.encoding: str = encoding

        self.spectrum_offsets: OrderedDict[str, int] = OrderedDict()
        self.chromatogram_offsets: OrderedDict[str, int] = OrderedDict()
        self._spectrum_keys: list[str] = []  # For fast O(1) index access
        self._chromatogram_keys: list[str] = []  # For fast O(1) index access

        self.file_handler: TextIO = self.get_file_handler(encoding)
        # Close the handle if index building fails, so a failed construction does not leak it
        # (for IndexedGzip this handle is a RapidgzipFile with worker threads).
        try:
            self._build_index(from_scratch=build_index_from_scratch)
        except BaseException:
            self.file_handler.close()
            raise

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

        return MzmlXMLElement(
            self._read_record(self.spectrum_offsets[identifier], "spectrum", identifier), element_type="spectrum"
        )

    @cached_property
    def _header(self) -> tuple[dict[str, str], int | None]:
        with self.get_binary_file_handler() as handle:
            handle.seek(0)
            return read_header(handle)

    def _read_record(self, offset: int, kind: str, identifier: str) -> Element:
        namespaces, _ = self._header
        with self.get_binary_file_handler() as handle:
            handle.seek(offset)
            try:
                try:
                    element = read_fragment(handle, self.encoding, namespaces)
                except ParseError as error:
                    if error.code != expat.errors.codes[expat.errors.XML_ERROR_UNBOUND_PREFIX]:
                        raise
                    with self.get_file_handler(self.encoding) as source:
                        context, _ = read_header(source, (kind, identifier))
                    namespaces.update(context)
                    handle.seek(offset)
                    element = read_fragment(handle, self.encoding, context)
            except Exception as error:
                raise ValueError(
                    f"Could not find end or parse {kind} {identifier!r} at offset {offset}: {error}"
                ) from error
        if get_tag(element) != kind or element.get("id") != identifier:
            raise ValueError(f"Index entry for {kind} {identifier!r} points to a different element at offset {offset}")
        return element

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

        return MzmlXMLElement(
            self._read_record(self.chromatogram_offsets[identifier], "chromatogram", identifier),
            element_type="chromatogram",
        )

    def get_chromatogram_by_index(self, index: int) -> ChromatogramElement:
        """Retrieve chromatogram by 0-based index.

        Args:
            index: 0-based index in chromatogram list.

        Raises:
            IndexError: If index is out of range.
        """
        if not 0 <= index < len(self._chromatogram_keys):
            raise IndexError(f"Chromatogram index {index} out of range")
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
        """Parse XML offsets independently of whitespace, quoting, and namespaces."""
        namespaces, expected_spectra = self._header
        seeker.seek(index_offset)
        root = read_fragment(seeker, self.encoding, namespaces)
        if get_tag(root) != "indexList":
            raise ValueError("indexListOffset does not point to an indexList")
        indices = list(root)
        if int(root.get("count", str(len(indices)))) != len(indices):
            raise ValueError("Index list count does not match its entries")
        for index in indices:
            kind = index.get("name")
            if get_tag(index) != "index" or kind not in {"spectrum", "chromatogram"}:
                raise ValueError("Unknown index kind")
            for entry in index:
                if get_tag(entry) != "offset":
                    raise ValueError("Unexpected element in index")
                offset = int(entry.text or "")
                if not 0 <= offset < index_offset:
                    raise ValueError("Record offset is outside the data section")
                self._add_offset_entry(kind, entry.attrib["idRef"], offset)
        if expected_spectra is not None and len(self.spectrum_offsets) != expected_spectra:
            raise ValueError("Spectrum index count does not match spectrumList")

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
        for offsets in (self.spectrum_offsets, self.chromatogram_offsets):
            if any(
                not isinstance(identifier, str) or type(offset) is not int or offset < 0
                for identifier, offset in offsets.items()
            ):
                raise ValueError("Invalid record ID or byte offset in index")
        self._validate_unique_offsets()
        self.spectrum_offsets = OrderedDict(sorted(self.spectrum_offsets.items(), key=lambda item: item[1]))
        self.chromatogram_offsets = OrderedDict(sorted(self.chromatogram_offsets.items(), key=lambda item: item[1]))
        self._spectrum_keys = list(self.spectrum_offsets)
        self._chromatogram_keys = list(self.chromatogram_offsets)

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
        """Build byte offsets with an XML parser, without retaining the document tree."""
        self.spectrum_offsets.clear()
        self.chromatogram_offsets.clear()
        expected: dict[str, int] = {}
        parser = expat.ParserCreate(encoding=self.encoding, namespace_separator="}")

        def on_start(name: str, attributes: dict[str, str]) -> None:
            tag = name.rsplit("}", 1)[-1]
            if tag in {"spectrumList", "chromatogramList"} and "count" in attributes:
                expected[tag.removesuffix("List")] = int(attributes["count"])
            elif tag in {"spectrum", "chromatogram"}:
                identifier = attributes.get("id")
                if identifier is None:
                    return
                offsets = self.spectrum_offsets if tag == "spectrum" else self.chromatogram_offsets
                if identifier in offsets:
                    warnings.warn(
                        f"Duplicate {tag} id {identifier!r} while building index from scratch. "
                        "Keeping the last occurrence.",
                        stacklevel=2,
                    )
                offsets[identifier] = parser.CurrentByteIndex

        parser.StartElementHandler = on_start
        seeker.seek(0)
        try:
            while chunk := seeker.read(1024 * 1024):
                parser.Parse(chunk, False)
            parser.Parse(b"", True)
        except expat.ExpatError as error:
            # Retain complete records from interrupted acquisitions. Iteration and access to
            # the unfinished record still raise a contextual parse error.
            warnings.warn(f"Incomplete or invalid XML while indexing: {error}", stacklevel=2)
        finally:
            parser.StartElementHandler = None
        found = {"spectrum": len(self.spectrum_offsets), "chromatogram": len(self.chromatogram_offsets)}
        if any(found[kind] != count for kind, count in expected.items()):
            warnings.warn(
                f"Found {found['spectrum']} spectra and {found['chromatogram']} chromatograms. "
                "Declared counts differ. The file may be truncated.",
                stacklevel=2,
            )
        self._finalize_index()

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
        """Count of spectra in the file (0 for a file with none; the index is always built)."""
        return len(self.spectrum_offsets)

    @cached_property
    def chromatogram_count(self) -> int | None:
        """Count of chromatograms in the file (0 for a file with none; the index is always built)."""
        return len(self.chromatogram_offsets)

    @property
    def spectrum_ids(self) -> list[str]:
        """All spectrum IDs from the file index."""
        return list(self.spectrum_offsets.keys())

    @property
    def chromatogram_ids(self) -> list[str]:
        """All chromatogram IDs from the file index."""
        return list(self.chromatogram_offsets.keys())


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
        self._data = binary.getvalue()
        # Reset position for initial reads
        self.binary.seek(0)
        super().__init__(encoding, build_index_from_scratch)

    def get_binary_file_handler(self) -> BinaryIO:
        return io.BufferedReader(cast(io.RawIOBase, _MemoryViewReader(memoryview(self._data))))

    def get_file_handler(self, encoding: str) -> TextIO:
        return TextIOWrapper(self.get_binary_file_handler(), encoding=encoding)
