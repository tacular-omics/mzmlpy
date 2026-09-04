"""Streaming XML helpers shared by the storage backends."""

import codecs
import contextlib
from collections.abc import Iterator
from typing import BinaryIO, TextIO, cast
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

from .util import get_tag


def iter_records(handle: TextIO, kind: str | None = None) -> Iterator[ET.Element]:
    """Yield intact records and detach both record kinds to bound parser memory."""
    parents: list[ET.Element] = []
    for event, element in ET.iterparse(handle, events=("start", "end")):
        if event == "start":
            parents.append(element)
            continue
        parents.pop()
        tag = get_tag(element)
        if tag not in {"spectrum", "chromatogram"}:
            continue
        if kind is None or tag == kind:
            yield element
        if parents:
            parents[-1].remove(element)


def read_fragment(handle: BinaryIO, encoding: str, namespaces: dict[str, str]) -> ET.Element:
    """Read one element at the current byte offset, restoring inherited namespaces."""
    declarations = " ".join(
        f"xmlns{':' + prefix if prefix else ''}={quoteattr(uri)}" for prefix, uri in namespaces.items()
    )
    parser = ET.XMLPullParser(events=("start", "end"))
    parser.feed(f"<wrapper {declarations}>")
    decoder = codecs.getincrementaldecoder(encoding)()
    depth = 0
    while True:
        chunk = handle.read(16384)
        if chunk:
            parser.feed(decoder.decode(chunk))
        else:
            # Finalization also flushes Expat's large-token reparse deferral. Trailing
            # parent closing tags may be invalid in this wrapper after our record ends.
            with contextlib.suppress(ET.ParseError):
                parser.close()
        for event, element in cast(Iterator[tuple[str, ET.Element]], parser.read_events()):
            depth += 1 if event == "start" else -1
            if event == "end" and depth == 1:
                return element
        if not chunk:
            break
    raise ValueError("Could not find end of XML element (file may be truncated)")


def read_header(
    handle: BinaryIO | TextIO, target: tuple[str, str | None] | None = None
) -> tuple[dict[str, str], int | None]:
    """Read namespaces in scope at the first record, or at a requested record."""
    namespaces: dict[str, str] = {}
    bindings: list[tuple[str, str | None]] = []
    parents: list[ET.Element] = []
    count = None
    events = cast(
        Iterator[tuple[str, ET.Element | tuple[str, str] | None]],
        ET.iterparse(handle, events=("start", "end", "start-ns", "end-ns")),
    )
    for event, item in events:
        if isinstance(item, tuple):
            prefix, uri = item
            bindings.append((prefix, namespaces.get(prefix)))
            namespaces[prefix] = uri
        elif item is None:
            prefix, previous = bindings.pop()
            if previous is None:
                namespaces.pop(prefix, None)
            else:
                namespaces[prefix] = previous
        elif event == "start":
            parents.append(item)
            tag = get_tag(item)
            if tag in {"spectrum", "chromatogram"}:
                if target is None or (tag == target[0] and (target[1] is None or item.get("id") == target[1])):
                    return namespaces, count
            elif tag == "spectrumList":
                value = item.get("count")
                count = int(value) if value is not None else None
        else:
            parents.pop()
            if parents and get_tag(item) in {"spectrum", "chromatogram"}:
                parents[-1].remove(item)
    if target is not None:
        raise ValueError(f"Record {target!r} was not found while resolving namespaces")
    return namespaces, count
