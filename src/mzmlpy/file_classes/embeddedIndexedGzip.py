"""Random access for pyMZML-compatible self-indexed gzip files."""

from __future__ import annotations

import gzip
import io
import re
from collections import OrderedDict
from collections.abc import Buffer
from functools import cached_property
from pathlib import Path
from typing import Literal, TextIO, overload
from xml.etree.ElementTree import ParseError
from xml.parsers import expat

from .._xml import read_fragment, read_header
from ..embedded_indexed_gzip import decompress_indexed_member, read_embedded_index
from .interface import MzmlInterface
from .xml_tuple import ChromatogramElement, MzmlXMLElement, SpectrumElement

_SPECIAL_KEYS = {"Head", "tail", "junk"}
_ELEMENT_PATTERNS = {
    "spectrum": re.compile(rb"<(?:[\w.-]+:)?spectrum(?=\s|>)", re.DOTALL),
    "chromatogram": re.compile(rb"<(?:[\w.-]+:)?chromatogram(?=\s|>)", re.DOTALL),
}


_SYNTHETIC_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"


class _HeaderSkippingStream(io.RawIOBase):
    """Replace the indexed first header with a small ordinary gzip header."""

    def __init__(self, path: str, first_payload_offset: int) -> None:
        super().__init__()
        self._file_handler = open(path, "rb")
        self._first_payload_offset = first_payload_offset
        self._position = 0
        self._file_handler.seek(first_payload_offset)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = 0) -> int:
        if offset == 0 and whence == 0:
            self._position = 0
            self._file_handler.seek(self._first_payload_offset)
            return 0
        raise io.UnsupportedOperation("header-skipping stream only supports seek(0)")

    def readinto(self, target: Buffer) -> int:
        view = memoryview(target).cast("B")
        written = 0
        if self._position < len(_SYNTHETIC_GZIP_HEADER):
            count = min(len(view), len(_SYNTHETIC_GZIP_HEADER) - self._position)
            view[:count] = _SYNTHETIC_GZIP_HEADER[self._position : self._position + count]
            written += count
            self._position += count
        if written < len(view):
            count = self._file_handler.readinto(view[written:])
            if count:
                written += count
                self._position += count
        return written

    def close(self) -> None:
        self._file_handler.close()
        super().close()


class _EmbeddedGzipFile(gzip.GzipFile):
    def __init__(self, source: _HeaderSkippingStream) -> None:
        self._embedded_source = source
        super().__init__(fileobj=source, mode="rb")

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._embedded_source.close()


class EmbeddedIndexedGzip(MzmlInterface):
    """Read spectrum members directly through offsets stored in the gzip header."""

    def __init__(self, path: str | Path, encoding: str) -> None:
        self.path = str(path)
        self.encoding = encoding
        try:
            self._entries = read_embedded_index(self.path)
            self._offsets = OrderedDict((entry.identifier, entry.offset) for entry in self._entries)
            self._member_offsets = list(dict.fromkeys(self._offsets.values()))
            self.spectrum_offsets: OrderedDict[str, int] = OrderedDict()
            self.chromatogram_offsets: OrderedDict[str, int] = OrderedDict()
            self._spectrum_keys: list[str] = []
            self._chromatogram_keys: list[str] = []
            self._legacy_discovered = False
            self._build_alias_maps()
            self.file_handler: TextIO = self.get_file_handler(encoding)
        except BaseException:
            if hasattr(self, "file_handler"):
                self.file_handler.close()
            raise

    def _build_alias_maps(self) -> None:
        spectrum_positions: list[tuple[int, str]] = []
        chromatogram_positions: list[tuple[int, str]] = []
        for identifier, offset in self._offsets.items():
            if identifier.startswith("s:"):
                self.spectrum_offsets[identifier[2:]] = offset
            elif identifier.startswith("c:"):
                self.chromatogram_offsets[identifier[2:]] = offset
            elif identifier.startswith("si:"):
                spectrum_positions.append((int(identifier[3:]), identifier))
            elif identifier.startswith("ci:"):
                chromatogram_positions.append((int(identifier[3:]), identifier))

        if spectrum_positions:
            by_offset = {offset: identifier for identifier, offset in self.spectrum_offsets.items()}
            self._spectrum_keys = [
                by_offset[self._offsets[alias]]
                for _, alias in sorted(spectrum_positions)
                if self._offsets[alias] in by_offset
            ]
        elif self.spectrum_offsets:
            self._spectrum_keys = list(self.spectrum_offsets)
        if chromatogram_positions:
            by_offset = {offset: identifier for identifier, offset in self.chromatogram_offsets.items()}
            self._chromatogram_keys = [
                by_offset[self._offsets[alias]]
                for _, alias in sorted(chromatogram_positions)
                if self._offsets[alias] in by_offset
            ]
        elif self.chromatogram_offsets:
            self._chromatogram_keys = list(self.chromatogram_offsets)

        self._modern_index = any(identifier.startswith(("s:", "c:")) for identifier in self._offsets)
        if not self.spectrum_offsets and not self._modern_index:
            for identifier, offset in self._offsets.items():
                if identifier.isdecimal():
                    self.spectrum_offsets[identifier] = offset
            self._spectrum_keys = list(self.spectrum_offsets)
        if not self.chromatogram_offsets and not self._modern_index:
            for identifier, offset in self._offsets.items():
                if (
                    not identifier.isdecimal()
                    and identifier not in _SPECIAL_KEYS
                    and not identifier.startswith("junk:")
                ):
                    self.chromatogram_offsets[identifier] = offset
            self._chromatogram_keys = list(self.chromatogram_offsets)

    @overload
    def _element_at(self, offset: int, kind: Literal["spectrum"]) -> SpectrumElement: ...

    @overload
    def _element_at(self, offset: int, kind: Literal["chromatogram"]) -> ChromatogramElement: ...

    def _element_at(
        self, offset: int, kind: Literal["spectrum", "chromatogram"]
    ) -> SpectrumElement | ChromatogramElement:
        member = decompress_indexed_member(self.path, offset)
        match = re.search(rb"<(?:[\w.-]+:)?" + kind.encode() + rb"(?=\s|>)", member)
        if match is None:
            raise ValueError(f"Indexed member at offset {offset} contains no {kind}")
        try:
            element = read_fragment(io.BytesIO(member[match.start() :]), self.encoding, self._namespaces)
        except ParseError as error:
            if error.code != expat.errors.codes[expat.errors.XML_ERROR_UNBOUND_PREFIX]:
                raise
            offsets = self.spectrum_offsets if kind == "spectrum" else self.chromatogram_offsets
            identifier = next((key for key, value in offsets.items() if value == offset), None)
            with self.get_file_handler(self.encoding) as source:
                context, _ = read_header(source, (kind, identifier if self._modern_index else None))
            self._namespaces.update(context)
            element = read_fragment(io.BytesIO(member[match.start() :]), self.encoding, context)
        if kind == "spectrum":
            return MzmlXMLElement(element, element_type="spectrum")
        return MzmlXMLElement(element, element_type="chromatogram")

    @cached_property
    def _namespaces(self) -> dict[str, str]:
        with self.get_file_handler(self.encoding) as handle:
            return read_header(handle)[0]

    def _discover_legacy_ids(self) -> None:
        if self._legacy_discovered or self._modern_index:
            return
        spectrum_offsets: OrderedDict[str, int] = OrderedDict()
        chromatogram_offsets: OrderedDict[str, int] = OrderedDict()
        for offset in dict.fromkeys(self._offsets.values()):
            member = decompress_indexed_member(self.path, offset)
            for kind, target in (
                ("spectrum", spectrum_offsets),
                ("chromatogram", chromatogram_offsets),
            ):
                match = _ELEMENT_PATTERNS[kind].search(member)
                if match is None:
                    continue
                element = self._element_at(offset, "spectrum" if kind == "spectrum" else "chromatogram").element
                identifier = element.get("id")
                if identifier is not None:
                    target[identifier] = offset
        self.spectrum_offsets = spectrum_offsets
        self._spectrum_keys = list(spectrum_offsets)
        self.chromatogram_offsets = chromatogram_offsets
        self._chromatogram_keys = list(chromatogram_offsets)
        self._legacy_discovered = True

    def close(self) -> None:
        self.file_handler.close()

    def get_file_handler(self, encoding: str) -> TextIO:
        raw = _HeaderSkippingStream(self.path, self._member_offsets[0])
        return io.TextIOWrapper(_EmbeddedGzipFile(raw), encoding=encoding)

    def read(self, size: int = -1) -> str:
        return self.file_handler.read(size)

    def get_spectrum_by_id(self, identifier: str | int) -> SpectrumElement:
        key = str(identifier)
        if key not in self.spectrum_offsets:
            self._discover_legacy_ids()
        try:
            offset = self.spectrum_offsets[key]
        except KeyError as error:
            raise KeyError(f"Spectrum ID {key} not found in embedded index") from error
        result = self._element_at(offset, "spectrum")
        if self._modern_index and result.element.get("id") != key:
            raise ValueError(f"Embedded index entry {key!r} points to a different spectrum")
        return result

    def get_spectrum_by_index(self, index: int) -> SpectrumElement:
        self._discover_legacy_ids()
        if not 0 <= index < len(self._spectrum_keys):
            raise IndexError(f"Spectrum index {index} out of range")
        try:
            key = self._spectrum_keys[index]
        except IndexError as error:
            raise IndexError(f"Spectrum index {index} out of range [0, {len(self._spectrum_keys)})") from error
        return self.get_spectrum_by_id(key)

    def get_chromatogram_by_id(self, identifier: str | int) -> ChromatogramElement:
        key = str(identifier)
        if key not in self.chromatogram_offsets:
            self._discover_legacy_ids()
        try:
            offset = self.chromatogram_offsets[key]
        except KeyError as error:
            raise KeyError(f"Chromatogram ID {key} not found in embedded index") from error
        result = self._element_at(offset, "chromatogram")
        if self._modern_index and result.element.get("id") != key:
            raise ValueError(f"Embedded index entry {key!r} points to a different chromatogram")
        return result

    def get_chromatogram_by_index(self, index: int) -> ChromatogramElement:
        self._discover_legacy_ids()
        if not 0 <= index < len(self._chromatogram_keys):
            raise IndexError(f"Chromatogram index {index} out of range")
        try:
            key = self._chromatogram_keys[index]
        except IndexError as error:
            raise IndexError(f"Chromatogram index {index} out of range [0, {len(self._chromatogram_keys)})") from error
        return self.get_chromatogram_by_id(key)

    @property
    def TIC(self) -> ChromatogramElement:
        try:
            return self.get_chromatogram_by_id("TIC")
        except KeyError:
            return self.get_chromatogram_by_id("tic")

    @cached_property
    def spectrum_count(self) -> int | None:
        self._discover_legacy_ids()
        return len(self._spectrum_keys)

    @cached_property
    def chromatogram_count(self) -> int | None:
        self._discover_legacy_ids()
        return len(self._chromatogram_keys)

    @property
    def spectrum_ids(self) -> list[str]:
        if not any(identifier.startswith("s:") for identifier in self._offsets):
            self._discover_legacy_ids()
        return list(self.spectrum_offsets)

    @property
    def chromatogram_ids(self) -> list[str]:
        if not any(identifier.startswith("c:") for identifier in self._offsets):
            self._discover_legacy_ids()
        return list(self.chromatogram_offsets)


__all__ = ["EmbeddedIndexedGzip"]
