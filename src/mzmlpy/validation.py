"""Streaming structural checks and optional binary and index verification."""

import gzip
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Literal, cast
from xml.etree import ElementTree as ET

from ._xml import read_fragment
from .regex_patterns import FILE_ENCODING_PATTERN
from .spectra import BinaryDataArray
from .util import expand_param_group_refs, get_tag

_REFERENCE_TARGETS = {
    "instrumentConfigurationRef": "instrumentConfiguration",
    "defaultInstrumentConfigurationRef": "instrumentConfiguration",
    "softwareRef": "software",
    "dataProcessingRef": "dataProcessing",
    "defaultDataProcessingRef": "dataProcessing",
    "sourceFileRef": "sourceFile",
    "defaultSourceFileRef": "sourceFile",
    "sampleRef": "sample",
    "scanSettingsRef": "scanSettings",
    "spectrumRef": "spectrum",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One machine-readable finding with a stable code and an XML location."""

    code: str
    message: str
    location: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class ValidationReport:
    """Results of the requested checks, without claiming full schema or ontology validation.

    Structural validation scans XML and records IDs and references without decoding arrays.
    Binary decoding and byte-offset verification are explicit, potentially expensive options.
    """

    issues: tuple[ValidationIssue, ...]
    spectrum_count: int
    chromatogram_count: int
    arrays_decoded: int
    index_entries_checked: int
    complete: bool
    decode_binary: bool
    check_index: bool

    @property
    def valid(self) -> bool:
        """Whether parsing completed and the requested checks found no errors."""
        return self.complete and not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict:
        """Return JSON-serializable results, including the computed valid flag."""
        return {"valid": self.valid, **asdict(self)}


class _Validator:
    def __init__(self, decode_binary: bool, check_index: bool) -> None:
        self.decode_binary = decode_binary
        self.check_index = check_index
        self.issues: list[ValidationIssue] = []
        self.ids: dict[str, set[str]] = {}
        self.references: list[tuple[str, str, str]] = []
        self.templates: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.records: dict[str, list[str]] = {"spectrum": [], "chromatogram": []}
        self.index_entries: dict[str, list[tuple[str, int]]] = {}
        self.index_list_offset: int | None = None
        self.has_index = False
        self.namespaces: dict[str, str] = {}
        self.arrays_decoded = 0
        self.index_entries_checked = 0

    def issue(self, code: str, message: str, location: str) -> None:
        self.issues.append(ValidationIssue(code, message, location))

    def integer(self, text: str | None, location: str, attribute: str) -> int | None:
        if text is None:
            return None
        try:
            value = int(text)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            self.issue("invalid_integer", f"{attribute} must be a nonnegative integer, got {text!r}", location)
            return None

    def start(self, element: ET.Element) -> None:
        tag = get_tag(element)
        identifier = element.get("id")
        location = f"{tag}[{identifier}]" if identifier is not None else tag
        if identifier is not None:
            known = self.ids.setdefault(tag, set())
            if identifier in known:
                self.issue("duplicate_id", f"Duplicate {tag} identifier {identifier!r}", location)
            known.add(identifier)
        if tag == "indexList":
            self.has_index = True
        if tag in self.records:
            if not identifier:
                self.issue("missing_id", f"{tag} has no nonempty id", location)
            self.records[tag].append(identifier or "")
        for attribute, target in _REFERENCE_TARGETS.items():
            if value := element.get(attribute):
                self.references.append((target, value, location))
        if tag == "referenceableParamGroupRef":
            self.references.append(("referenceableParamGroup", element.get("ref", ""), location))
        elif tag == "sourceFileRef":
            self.references.append(("sourceFile", element.get("ref", ""), location))

    def record(self, element: ET.Element) -> None:
        location = f"{get_tag(element)}[{element.get('id', '')}]"
        expand_param_group_refs(element, self.templates)
        default_length = self.integer(element.get("defaultArrayLength"), location, "defaultArrayLength")
        for position, node in enumerate(child for child in element.iter() if get_tag(child) == "binaryDataArray"):
            array_location = f"{location}/binaryDataArray[{position}]"
            array = BinaryDataArray(node)
            known_encoding = array.encoding is not None and array.compression is not None
            if array.encoding is None:
                self.issue("unsupported_or_missing_encoding", "No supported numeric encoding term", array_location)
            if array.compression is None:
                self.issue("unsupported_or_missing_compression", "No supported compression term", array_location)
            length = self.integer(node.get("arrayLength"), array_location, "arrayLength")
            if "arrayLength" not in node.attrib:
                length = default_length
            binary = next((child for child in node if get_tag(child) == "binary"), None)
            if binary is None:
                self.issue("missing_binary", "Array has no binary element", array_location)
                continue
            text = "".join((binary.text or "").split())
            encoded_length = self.integer(node.get("encodedLength"), array_location, "encodedLength")
            if encoded_length is not None and len(text) != encoded_length:
                self.issue(
                    "encoded_length_mismatch",
                    f"Declared {encoded_length} base64 characters, found {len(text)}",
                    array_location,
                )
            if self.decode_binary and known_encoding:
                try:
                    values = array.data
                    self.arrays_decoded += 1
                    if length is not None and len(values) != length:
                        self.issue(
                            "array_length_mismatch", f"Expected {length} values, decoded {len(values)}", array_location
                        )
                except ImportError as error:
                    self.issue("missing_dependency", str(error), array_location)
                except Exception as error:
                    self.issue("decode_error", str(error), array_location)

    def finish(self, handle: BinaryIO, encoding: str, complete: bool) -> ValidationReport:
        if complete:
            for kind, identifier, location in self.references:
                if identifier not in self.ids.get(kind, set()):
                    self.issue("missing_reference", f"Unknown {kind} reference {identifier!r}", location)
            if self.has_index:
                for kind, identifiers in self.records.items():
                    indexed = [
                        identifier
                        for identifier, _ in sorted(self.index_entries.get(kind, []), key=lambda entry: entry[1])
                    ]
                    if indexed != identifiers:
                        self.issue("index_ids_mismatch", "Index IDs or order differ from the XML records", kind)
            if self.check_index and self.index_list_offset is not None:
                try:
                    handle.seek(self.index_list_offset)
                    if get_tag(read_fragment(handle, encoding, self.namespaces)) != "indexList":
                        raise ValueError("indexListOffset does not point to an indexList")
                except Exception as error:
                    self.issue("invalid_index_list_offset", str(error), "indexListOffset")
            if self.check_index:
                for kind, entries in self.index_entries.items():
                    for identifier, offset in entries:
                        try:
                            handle.seek(offset)
                            element = read_fragment(handle, encoding, self.namespaces)
                            if get_tag(element) != kind or element.get("id") != identifier:
                                raise ValueError("Offset points to a different record")
                            self.index_entries_checked += 1
                        except Exception as error:
                            self.issue("invalid_index_offset", str(error), f"{kind}[{identifier}]")
        return ValidationReport(
            tuple(self.issues),
            len(self.records["spectrum"]),
            len(self.records["chromatogram"]),
            self.arrays_decoded,
            self.index_entries_checked,
            complete,
            self.decode_binary,
            self.check_index,
        )


def _validate_stream(handle: BinaryIO, *, decode_binary: bool, check_index: bool) -> ValidationReport:
    validator = _Validator(decode_binary, check_index)
    complete = False
    encoding = "utf-8"
    try:
        prefix = handle.read(1024)
        match = FILE_ENCODING_PATTERN.search(prefix)
        if match:
            encoding = match.group("encoding").decode("ascii")
        handle.seek(0)
        parents: list[ET.Element] = []
        child_counts: list[int] = []
        saw_mzml = False
        events = cast(
            Iterator[tuple[str, ET.Element | tuple[str, str]]],
            ET.iterparse(handle, events=("start", "end", "start-ns")),
        )
        for event, item in events:
            if isinstance(item, tuple):
                validator.namespaces[item[0]] = item[1]
                continue
            element = item
            tag = get_tag(element)
            if event == "start":
                if child_counts:
                    child_counts[-1] += 1
                parents.append(element)
                child_counts.append(0)
                saw_mzml |= tag == "mzML"
                validator.start(element)
                continue
            count = child_counts.pop()
            parents.pop()
            location = f"{tag}[{element.get('id', '')}]"
            declared = validator.integer(element.get("count"), location, "count")
            if declared is not None and count != declared:
                validator.issue("count_mismatch", f"Declared {declared} children, found {count}", location)
            if tag == "referenceableParamGroup":
                validator.templates[element.get("id", "")] = [
                    (get_tag(child), dict(child.attrib))
                    for child in element
                    if get_tag(child) in {"cvParam", "userParam"}
                ]
            elif tag == "indexListOffset":
                validator.index_list_offset = validator.integer(element.text, location, "indexListOffset")
            elif tag == "index":
                kind = element.get("name", "")
                if kind not in validator.records:
                    validator.issue("unknown_index_kind", f"Unknown index kind {kind!r}", location)
                else:
                    entries = validator.index_entries.setdefault(kind, [])
                    for entry in element:
                        offset = validator.integer(entry.text, location, "offset")
                        if offset is not None:
                            entries.append((entry.get("idRef", ""), offset))
            elif tag in validator.records:
                validator.record(element)
            # Keep descendants intact until their containing record or metadata section ends.
            if parents and (tag in validator.records or get_tag(parents[-1]) == "mzML"):
                parents[-1].remove(element)
        if not saw_mzml:
            validator.issue("not_mzml", "Document contains no mzML element", "document")
        complete = True
    except (ET.ParseError, OSError, ValueError, EOFError) as error:
        validator.issue("parse_error", str(error), "document")
    return validator.finish(handle, encoding, complete)


def validate(file: str | Path, *, decode_binary: bool = False, check_index: bool = False) -> ValidationReport:
    """Validate plain or gzip mzML without creating or repairing caches.

    The default checks XML structure, list counts, IDs, references, index ID agreement,
    and supported array metadata. Set decode_binary to decode every array and compare
    lengths. Set check_index to seek to XML footer offsets and verify their targets.
    This does not perform full XSD, controlled-vocabulary, or embedded gzip index validation.
    Memory grows with IDs, references, and findings, plus the largest record.

    File-open errors raise OSError. Malformed content is returned as report issues.
    """
    with open(file, "rb") as raw:
        compressed = raw.read(2) == b"\x1f\x8b"
        raw.seek(0)
        if compressed:
            with gzip.GzipFile(fileobj=raw) as handle:
                return _validate_stream(cast(BinaryIO, handle), decode_binary=decode_binary, check_index=check_index)
        return _validate_stream(raw, decode_binary=decode_binary, check_index=check_index)
