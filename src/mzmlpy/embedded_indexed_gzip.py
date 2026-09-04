"""Read and write pyMZML-compatible self-indexed gzip files."""

from __future__ import annotations

import contextlib
import gzip
import os
import re
import shutil
import struct
import tempfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from xml.parsers import expat

from .util import atomic_write_path

_GZIP_MAGIC = b"\x1f\x8b"
_FORMAT_MARKER = b"FU\x01"
_PAD = b"\xac"
_FCOMMENT = 0x10
_FEXTRA = 0x04
_FNAME = 0x08
_FHCRC = 0x02
_RESERVED_FLAGS = 0xE0
_MEMBER_HEADER = struct.Struct("<BBBBIBB")
_TRAILER = struct.Struct("<II")
_SCAN_NUMBER = re.compile(r"(?:^|\s)scan=(\d+)(?:\s|$)")
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class EmbeddedIndexEntry:
    """One identifier and raw-deflate offset from an embedded gzip index."""

    identifier: str
    offset: int


@dataclass(frozen=True)
class IndexedGzipWriteResult:
    """Summary returned after creating a self-indexed gzip file."""

    output_path: Path
    spectrum_count: int
    chromatogram_count: int
    member_count: int
    index_entry_count: int


@dataclass(frozen=True)
class _Block:
    kind: str
    identifier: str
    position: int
    data: bytes


def _read_c_string(file_handler: BinaryIO, limit: int | None = None) -> bytes:
    value = bytearray()
    while limit is None or len(value) <= limit:
        byte = file_handler.read(1)
        if not byte:
            raise ValueError("Truncated gzip header")
        if byte == b"\x00":
            return bytes(value)
        value.extend(byte)
    raise ValueError("Gzip header field exceeds the supported size")


def _seek_comment(file_handler: BinaryIO) -> bool:
    header = file_handler.read(10)
    if len(header) != 10 or header[:2] != _GZIP_MAGIC or header[2] != 8:
        return False
    flags = header[3]
    if flags & _RESERVED_FLAGS:
        raise ValueError("Gzip header uses reserved flags")
    if flags & _FEXTRA:
        raw_length = file_handler.read(2)
        if len(raw_length) != 2:
            raise ValueError("Truncated gzip extra-field length")
        extra_length = struct.unpack("<H", raw_length)[0]
        if len(file_handler.read(extra_length)) != extra_length:
            raise ValueError("Truncated gzip extra field")
    if flags & _FNAME:
        _read_c_string(file_handler, limit=1024 * 1024)
    return bool(flags & _FCOMMENT)


def is_embedded_indexed_gzip(path: str | Path) -> bool:
    """Return whether a gzip file starts with the pyMZML ``FU`` version 1 marker."""
    try:
        with open(path, "rb") as file_handler:
            if not _seek_comment(file_handler):
                return False
            return file_handler.read(len(_FORMAT_MARKER)) == _FORMAT_MARKER
    except (OSError, ValueError):
        return False


def read_embedded_index(path: str | Path) -> list[EmbeddedIndexEntry]:
    """Read and validate a pyMZML-compatible index from the first gzip comment."""
    file_size = os.path.getsize(path)
    with open(path, "rb") as file_handler:
        if not _seek_comment(file_handler):
            raise ValueError("Gzip file has no embedded index comment")
        if file_handler.read(3) != _FORMAT_MARKER:
            raise ValueError("Gzip comment is not an FU version 1 index")
        widths = file_handler.read(2)
        if len(widths) != 2:
            raise ValueError("Truncated embedded index widths")
        identifier_width, offset_width = widths
        if identifier_width == 0 or offset_width == 0:
            raise ValueError("Embedded index widths must be positive")

        entries: list[EmbeddedIndexEntry] = []
        seen: set[str] = set()
        previous_offset = -1
        while True:
            first = file_handler.read(1)
            if not first:
                raise ValueError("Embedded index comment has no terminator")
            if first == b"\x00":
                break
            raw_identifier = first + file_handler.read(identifier_width - 1)
            raw_offset = file_handler.read(offset_width)
            if len(raw_identifier) != identifier_width or len(raw_offset) != offset_width:
                raise ValueError("Truncated embedded index entry")
            if raw_identifier == b"\x01" * identifier_width:
                break
            try:
                identifier_bytes = raw_identifier.lstrip(_PAD)
                identifier = identifier_bytes.decode("utf-8")
            except UnicodeDecodeError:
                identifier = identifier_bytes.decode("latin-1")
            try:
                offset = int(raw_offset.lstrip(_PAD).decode("ascii"))
            except ValueError as error:
                if raw_offset == b"\x01" * offset_width:
                    break
                raise ValueError("Embedded index contains an invalid offset") from error
            if not identifier:
                raise ValueError("Embedded index contains an empty identifier")
            if identifier in seen:
                raise ValueError(f"Duplicate embedded index identifier: {identifier}")
            if not 0 < offset < file_size:
                raise ValueError(f"Embedded index offset is outside the file: {offset}")
            if offset < previous_offset:
                raise ValueError("Embedded index offsets are not ordered")
            seen.add(identifier)
            entries.append(EmbeddedIndexEntry(identifier, offset))
            previous_offset = offset

    if not entries:
        raise ValueError("Embedded index contains no entries")
    return entries


def decompress_indexed_member(path: str | Path, offset: int) -> bytes:
    """Decompress and validate the gzip member whose raw deflate stream starts at ``offset``."""
    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
    output = bytearray()
    with open(path, "rb") as file_handler:
        file_handler.seek(offset)
        while not decompressor.eof:
            chunk = file_handler.read(_CHUNK_SIZE)
            if not chunk:
                raise ValueError(f"Truncated deflate stream at offset {offset}")
            try:
                output.extend(decompressor.decompress(chunk))
            except zlib.error as error:
                raise ValueError(f"Invalid deflate stream at offset {offset}") from error

        trailer_position = file_handler.tell() - len(decompressor.unused_data)
        file_handler.seek(trailer_position)
        raw_trailer = file_handler.read(_TRAILER.size)
        if len(raw_trailer) != _TRAILER.size:
            raise ValueError(f"Truncated gzip trailer at offset {offset}")
        expected_crc, expected_size = _TRAILER.unpack(raw_trailer)

    actual_crc = zlib.crc32(output) & 0xFFFFFFFF
    actual_size = len(output) & 0xFFFFFFFF
    if actual_crc != expected_crc or actual_size != expected_size:
        raise ValueError(f"Gzip member checksum failed at offset {offset}")
    return bytes(output)


def _member_header(has_comment: bool) -> bytes:
    flags = _FCOMMENT if has_comment else 0
    return _MEMBER_HEADER.pack(0x1F, 0x8B, 8, flags, 0, 0, 255)


def _write_member(
    file_handler: BinaryIO,
    data: bytes,
    compression_level: int,
    comment: bytes | None = None,
) -> int:
    file_handler.write(_member_header(comment is not None))
    if comment is not None:
        file_handler.write(comment)
        file_handler.write(b"\x00")
    payload_offset = file_handler.tell()
    compressor = zlib.compressobj(compression_level, zlib.DEFLATED, -zlib.MAX_WBITS)
    file_handler.write(compressor.compress(data))
    file_handler.write(compressor.flush())
    file_handler.write(_TRAILER.pack(zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF))
    return payload_offset


def _iter_blocks(file_handler: BinaryIO) -> Iterator[_Block]:
    """Split at XML record boundaries, preserving every source byte."""
    buffer = bytearray()
    buffer_offset = 0
    first_element = True
    junk_position = 0
    positions = {"spectrum": 0, "chromatogram": 0}
    records: list[tuple[str, str, int, int]] = []
    active: tuple[str, str, int] | None = None
    parser = expat.ParserCreate(namespace_separator="}")

    def on_start(name: str, attributes: dict[str, str]) -> None:
        nonlocal active
        kind = name.rsplit("}", 1)[-1]
        if kind in positions:
            if active is not None:
                raise ValueError("Nested spectrum or chromatogram elements are not supported")
            if "id" not in attributes:
                raise ValueError(f"{kind} element has no id attribute")
            active = kind, attributes["id"], parser.CurrentByteIndex

    def on_end(name: str) -> None:
        nonlocal active
        kind = name.rsplit("}", 1)[-1]
        if active is not None and kind == active[0]:
            end = parser.CurrentByteIndex
            local_end = end - buffer_offset
            # For an empty element Expat points just after '/>'. Otherwise it points
            # at the closing tag, which has already arrived in the input buffer.
            if buffer[local_end : local_end + 2] == b"</":
                end = buffer_offset + buffer.index(b">", local_end) + 1
            records.append((*active, end))
            active = None

    parser.StartElementHandler = on_start
    parser.EndElementHandler = on_end
    while True:
        chunk = file_handler.read(_CHUNK_SIZE)
        buffer.extend(chunk)
        try:
            parser.Parse(chunk, not chunk)
        except expat.ExpatError as error:
            raise ValueError(f"Invalid or unclosed mzML input: {error}") from error
        consumed = 0
        for kind, identifier, start, end in records:
            prefix = bytes(buffer[consumed : start - buffer_offset])
            if first_element:
                yield _Block("special", "Head", 0, prefix)
                first_element = False
                prefix = b""
            elif prefix.strip():
                yield _Block("special", f"junk:{junk_position}", junk_position, prefix)
                junk_position += 1
                prefix = b""
            data = prefix + bytes(buffer[start - buffer_offset : end - buffer_offset])
            yield _Block(kind, identifier, positions[kind], data)
            positions[kind] += 1
            consumed = end - buffer_offset
        del buffer[:consumed]
        buffer_offset += consumed
        records.clear()
        if not chunk:
            yield _Block("special", "Head" if first_element else "tail", 0, bytes(buffer))
            return


def _aliases(block: _Block) -> list[str]:
    if block.kind == "special":
        return [block.identifier]
    prefix = "s" if block.kind == "spectrum" else "c"
    aliases = [f"{prefix}:{block.identifier}"]
    if block.kind == "spectrum":
        scan_match = _SCAN_NUMBER.search(block.identifier)
        if scan_match:
            aliases.append(scan_match.group(1))
        elif block.identifier.isdecimal():
            aliases.append(block.identifier)
    else:
        aliases.append(block.identifier)
    return aliases


@contextlib.contextmanager
def _decompressed_source(path: str | Path) -> Iterator[str]:
    source_path = str(path)
    with open(source_path, "rb") as source:
        is_gzip = source.read(2) == _GZIP_MAGIC
    if not is_gzip:
        yield source_path
        return

    temporary = tempfile.NamedTemporaryFile(prefix="mzmlpy-index-", suffix=".mzML", delete=False)
    temporary_path = temporary.name
    try:
        with temporary, gzip.open(source_path, "rb") as compressed:
            shutil.copyfileobj(compressed, temporary, length=_CHUNK_SIZE)
        yield temporary_path
    finally:
        with contextlib.suppress(OSError):
            os.remove(temporary_path)


def write_indexed_gzip(
    source: str | Path,
    output: str | Path,
    *,
    compression_level: int = 6,
) -> IndexedGzipWriteResult:
    """Create a deterministic, pyMZML-compatible self-indexed ``.mzML.gz`` file.

    The input may be plain mzML or gzip-compressed mzML. Memory use depends on the largest
    XML section plus the embedded index. Gzip input is decompressed once to a temporary spool so
    the index can be sized before the output header is written.
    """
    if not -1 <= compression_level <= 9:
        raise ValueError("compression_level must be between -1 and 9")
    output_path = str(output)
    if not output_path.lower().endswith((".gz", ".igz")):
        raise ValueError("output path must end in .gz or .igz")

    with _decompressed_source(source) as plain_path:
        blocks: list[tuple[str, ...]] = []
        seen_aliases: set[str] = set()
        spectrum_count = 0
        chromatogram_count = 0
        with open(plain_path, "rb") as source_handler:
            for block in _iter_blocks(source_handler):
                aliases = []
                for alias in _aliases(block):
                    if "\x00" in alias:
                        raise ValueError("Embedded index identifiers cannot contain a null byte")
                    if alias in seen_aliases:
                        if alias.startswith(("s:", "c:", "si:", "ci:")):
                            raise ValueError(f"Duplicate mzML identifier in input: {block.identifier}")
                        continue
                    seen_aliases.add(alias)
                    aliases.append(alias)
                blocks.append(tuple(aliases))
                spectrum_count += block.kind == "spectrum"
                chromatogram_count += block.kind == "chromatogram"

        encoded_aliases = [alias.encode("utf-8") for aliases in blocks for alias in aliases]
        identifier_width = max((len(alias) for alias in encoded_aliases), default=1)
        offset_width = 20
        if identifier_width > 255:
            raise ValueError("Embedded index identifiers cannot exceed 255 UTF-8 bytes")
        if len(encoded_aliases) > 10_000_000:
            raise ValueError("Embedded index contains too many entries")

        comment_size = 5 + len(encoded_aliases) * (identifier_width + offset_width)
        comment = bytearray(_FORMAT_MARKER + bytes((identifier_width, offset_width)))
        comment.extend(b"\x01" * (comment_size - len(comment)))

        index_entries: list[EmbeddedIndexEntry] = []
        with atomic_write_path(output_path) as temporary_output, open(temporary_output, "w+b") as output_handler:
            with open(plain_path, "rb") as source_handler:
                for block_number, block in enumerate(_iter_blocks(source_handler)):
                    payload_offset = _write_member(
                        output_handler,
                        block.data,
                        compression_level,
                        bytes(comment) if block_number == 0 else None,
                    )
                    for alias in blocks[block_number]:
                        index_entries.append(EmbeddedIndexEntry(alias, payload_offset))

            output_handler.seek(10 + len(_FORMAT_MARKER) + 2)
            for entry in index_entries:
                raw_identifier = entry.identifier.encode("utf-8")
                raw_offset = str(entry.offset).encode("ascii")
                if len(raw_offset) > offset_width:
                    raise ValueError("Compressed offset exceeds embedded index width")
                output_handler.write(raw_identifier.rjust(identifier_width, _PAD))
                output_handler.write(raw_offset.rjust(offset_width, _PAD))
            output_handler.flush()
            os.fsync(output_handler.fileno())

    return IndexedGzipWriteResult(
        output_path=Path(output_path),
        spectrum_count=spectrum_count,
        chromatogram_count=chromatogram_count,
        member_count=len(blocks),
        index_entry_count=len(index_entries),
    )


index_gzip = write_indexed_gzip


__all__ = [
    "EmbeddedIndexEntry",
    "IndexedGzipWriteResult",
    "decompress_indexed_member",
    "index_gzip",
    "is_embedded_indexed_gzip",
    "read_embedded_index",
    "write_indexed_gzip",
]
