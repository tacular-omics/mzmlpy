import math
import re
from abc import ABC, abstractmethod
from array import array
from bisect import bisect_right
from collections.abc import Iterator
from functools import cached_property
from typing import Literal, overload

from .constants import SpectrumMSAccession, TimeUnitAccession
from .errors import MzmlError
from .file_interface import FileInterface
from .filtering import SpectrumFilter, _within, check_point, mz_tolerance_range, tolerance_range
from .spectra import _SECONDS_PER_UNIT, Chromatogram, Spectrum

_SCAN_START = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?scan[\s>/]")
_CV_PARAM = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?cvParam\s[^>]*>")
_SCAN_NAME_END = frozenset((b" ", b"\t", b"\r", b"\n", b">", b"/"))
_ATTRIBUTE = re.compile(rb'([\w:.-]+)\s*=\s*"([^"]*)"')
_RT_TERMS = (SpectrumMSAccession.SCAN_START_TIME.encode(), b"scan start time")
_RT_FACTORS = {unit.value.encode(): _SECONDS_PER_UNIT[unit] for unit in TimeUnitAccession}


def _head_scan_rts(head: bytes) -> tuple[float, ...] | None:
    """Scan times in seconds from a spectrum's bytes before its binary arrays, like
    :func:`_scan_rts`, or None when only a full parse can answer exactly.

    Only the plain case is read here: each ``scan`` holds at most one scan start time cvParam,
    as a direct child, written with double-quoted attributes, a numeric value and a time unit
    accession, and no referenceable param group is referenced. Anything else (and every warning
    or error case of :attr:`Scan.rt`) returns None so the caller parses the record.
    """
    if b"referenceableParamGroupRef" in head:
        return None
    mentions = [*_find_all(head, _RT_TERMS[0]), *_find_all(head, _RT_TERMS[1])]
    if not mentions:
        return ()
    if b"&" in head:
        return None
    mentions.sort()
    if b":scan" in head:
        scan_starts = [match.start() for match in _SCAN_START.finditer(head)]
    else:
        scan_starts = [i for i in _find_all(head, b"<scan") if head[i + 5 : i + 6] in _SCAN_NAME_END]
    times: list[float] = []
    owners: set[int] = set()
    tag_end = -1
    for position in mentions:
        if position < tag_end:
            continue  # accession and name of the tag just read
        tag_start = head.rfind(b"<", 0, position)
        tag_end = head.find(b">", position)
        owner = bisect_right(scan_starts, position) - 1
        if tag_start < 0 or tag_end < 0 or owner < 0 or owner in owners:
            return None
        owners.add(owner)
        tag = head[tag_start : tag_end + 1]
        scan_start = scan_starts[owner]
        if (
            _CV_PARAM.fullmatch(tag) is None
            # A direct child of the scan: not past its end tag, not inside its scan windows.
            or head.find(b"scan>", head.find(b">", scan_start) + 1, tag_start) >= 0
            or head.find(b"scanWindowList", scan_start, tag_start) >= 0
        ):
            return None
        attributes = dict(_ATTRIBUTE.findall(tag))
        factor = _RT_FACTORS.get(attributes.get(b"unitAccession", b""))
        if attributes.get(b"accession") != _RT_TERMS[0] or factor is None:
            return None
        try:
            value = float(attributes[b"value"])
        except (KeyError, ValueError):
            return None
        value = value if factor == 1.0 else value * factor
        if math.isfinite(value):
            times.append(value)
    return tuple(times)


def _find_all(data: bytes, term: bytes) -> Iterator[int]:
    position = data.find(term)
    while position >= 0:
        yield position
        position = data.find(term, position + len(term))


def _scan_rts(spectrum: Spectrum) -> list[float]:
    """Finite scan start times of every scan in ``spectrum``, in seconds."""
    return [value for scan in spectrum.scans if (value := scan.rt) is not None and math.isfinite(value)]


class _RtTable:
    """Scan times of every spectrum by index, in about 8 bytes per spectrum.

    Almost every spectrum has exactly one scan time, kept in a float array. A spectrum with none
    or several is marked NaN there (stored times are always finite) and its times kept in a dict.
    """

    __slots__ = ("_first", "_other")

    def __init__(self) -> None:
        self._first: array[float] = array("d")
        self._other: dict[int, tuple[float, ...]] = {}

    def append(self, times: tuple[float, ...]) -> None:
        if len(times) == 1:
            self._first.append(times[0])
        else:
            self._other[len(self._first)] = times
            self._first.append(math.nan)

    def __len__(self) -> int:
        return len(self._first)

    def __iter__(self) -> Iterator[tuple[float, ...]]:
        for index, value in enumerate(self._first):
            yield (value,) if value == value else self._other[index]

    def indices_within(self, bounds: tuple[float | None, float | None]) -> Iterator[int]:
        """Indices of spectra with at least one scan time inside ``bounds``."""
        lower, upper = bounds
        other = self._other
        for index, value in enumerate(self._first):
            if value != value:  # NaN: none or several times
                if any(_within(time, bounds) for time in other[index]):
                    yield index
            elif (lower is None or value >= lower) and (upper is None or value <= upper):
                yield index


class BaseLookup[T: (Spectrum, Chromatogram)](ABC):
    """Base class for spectrum and chromatogram lookups."""

    def __init__(self, file_object: FileInterface, *, count: int | None = None, id_regex: str | None = None) -> None:
        self._file_object = file_object
        self._count = count
        self._id_regex = id_regex

    @cached_property
    def _id_map(self) -> dict[str, str]:
        """Map regex-extracted keys to their full IDs, built lazily on first use."""
        if self._id_regex is None:
            return {}
        pattern = re.compile(self._id_regex)
        result: dict[str, str] = {}
        for full_id in self._get_ids_for_map():
            if m := pattern.search(full_id):
                key = m.group(1) if m.lastindex else m.group(0)
                if key not in result:
                    result[key] = full_id
        return result

    @abstractmethod
    def _get_ids_for_map(self) -> list[str]:
        """Return the list of all IDs used to build the regex ID map."""
        ...

    def get_by_index(self, index: int) -> T:
        """Get item by index. Negative indices count from the end, like a list."""
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError(f"index must be an int, got {type(index).__name__}")
        if index < 0:
            # Normalize against the count so lookup[-1] mirrors slice behavior (lookup[-1:]).
            count = self.count
            if count is None:
                raise IndexError(f"index {index} out of range: negative indices need a known count")
            if index + count < 0:
                valid = f"valid indices are -{count} to {count - 1}" if count else "the lookup is empty"
                raise IndexError(f"index {index} out of range: {valid}")
            index += count
        return self._get_by_index_impl(index)

    def get_by_id(self, identifier: str) -> T:
        """Get item by native id, or by the ``id_regex`` key when the reader was given one.

        Raises:
            MzmlRecordNotFoundError: No record has this id (also a ``KeyError``).
            TypeError: ``identifier`` is not a string.
        """
        if not isinstance(identifier, str):
            raise TypeError(f"id must be a str, got {type(identifier).__name__}")
        try:
            return self._get_by_exact_id(identifier)
        except KeyError:
            if self._id_regex is not None and (mapped := self._id_map.get(identifier)):
                return self._get_by_exact_id(mapped)
            raise

    def get_by_slice(self, slice_obj: slice) -> list[T]:
        """Get items by slice notation."""
        if self.count is None:
            # Don't know count - must iterate all and slice
            items: list[T] = list(self)
            return items[slice_obj]
        # Know count - use slice.indices() to handle all cases
        start, stop, step = slice_obj.indices(self.count)
        return [self.get_by_index(i) for i in range(start, stop, step)]

    @property
    def count(self) -> int | None:
        """Get count of items."""
        if self._count is not None:
            return self._count
        return self._get_count_impl()

    @property
    def ids(self) -> list[str]:
        """Native ids of all items, in file order, without parsing the items."""
        return list(self._get_ids_for_map())

    def __iter__(self) -> Iterator[T]:
        """Iterate over all items in the file."""
        return self._iter_impl()

    @overload
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: str) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> list[T]: ...
    def __getitem__(self, index: int | str | slice) -> T | list[T]:
        """Access item by index or ID."""
        if isinstance(index, slice):
            return self.get_by_slice(index)
        if isinstance(index, int):
            return self.get_by_index(index)
        if isinstance(index, str):
            return self.get_by_id(index)
        raise TypeError(f"lookup key must be an int, str or slice, got {type(index).__name__}")

    # Abstract methods to be implemented by subclasses
    @abstractmethod
    def _get_by_index_impl(self, index: int) -> T:
        """Get item by index implementation."""
        ...

    @abstractmethod
    def _get_by_exact_id(self, identifier: str) -> T:
        """Get item by its full native id; raises MzmlRecordNotFoundError if absent."""
        ...

    @abstractmethod
    def _get_count_impl(self) -> int | None:
        """Get count implementation."""
        ...

    @abstractmethod
    def _iter_impl(self) -> Iterator[T]:
        """Iterator implementation."""
        ...

    def __len__(self) -> int:
        """Get count of items."""
        count = self.count
        if count is None:
            raise TypeError("Count is not available")
        return count

    def __repr__(self) -> str:
        """String representation."""
        count = self.count
        count_str = str(count) if count is not None else "unknown"
        return f"<{self.__class__.__name__} count={count_str}>"

    def __str__(self) -> str:
        """String representation."""
        return self.__repr__()

    def __contains__(self, identifier: object) -> bool:
        """Check if item with given ID exists."""
        if not isinstance(identifier, str):
            return False
        try:
            self.get_by_id(identifier)
            return True
        except KeyError:
            return False


class SpectrumLookup(BaseLookup[Spectrum]):
    """Lookup interface for spectra."""

    # Scan times per spectrum index, built by the first retention-time filter.
    _rt_table: _RtTable | None = None

    def filter(
        self,
        *,
        ms_level: int | None = None,
        rt: float | None = None,
        rt_range: tuple[float | None, float | None] | None = None,
        rt_tolerance: float = 30.0,
        polarity: Literal["positive", "negative"] | None = None,
        precursor_mz: float | None = None,
        precursor_mz_range: tuple[float | None, float | None] | None = None,
        mz_tolerance: float = 20.0,
        mz_tolerance_type: Literal["ppm", "da"] = "ppm",
        spectrum_type: Literal["centroid", "profile"] | None = None,
        ook0_range: tuple[float | None, float | None] | None = None,
        drift_time_range: tuple[float | None, float | None] | None = None,
        faims_voltage_range: tuple[float | None, float | None] | None = None,
    ) -> Iterator[Spectrum]:
        """Lazily select spectra by metadata, without decoding binary arrays.

        Criteria are combined with AND. Tuples are inclusive ``*_range`` bounds, either end None
        for open. Point queries follow tdfpy's ``query``: ``rt`` matches within ``rt_tolerance``
        seconds and ``precursor_mz`` within ``mz_tolerance`` ppm (or Da with
        ``mz_tolerance_type="da"``). Pass a point or its range, not both. See
        :class:`SpectrumFilter` for how each criterion matches. Keep the reader open while
        iterating.

        With an indexed reader (access strategy ``plain``, ``rapidgzip`` or
        ``memory``; ``stream`` and ``embedded`` scan every spectrum), the first retention-time
        query reads the scan times of every spectrum once, from the metadata before each
        record's binary arrays, and caches them. It and later queries then read in full only the
        spectra inside the window. Record order does not matter.

        Raises:
            MzmlError: A criterion is invalid, or both a point and its range were given.
        """
        check_point("rt", rt)
        check_point("precursor_mz", precursor_mz)
        tolerance_range(None, rt_tolerance, "rt_tolerance")
        mz_tolerance_range(None, mz_tolerance, mz_tolerance_type)
        if rt is not None:
            if rt_range is not None:
                raise MzmlError("pass rt or rt_range, not both")
            rt_range = tolerance_range(rt, rt_tolerance, "rt_tolerance")
        if precursor_mz is not None:
            if precursor_mz_range is not None:
                raise MzmlError("pass precursor_mz or precursor_mz_range, not both")
            precursor_mz_range = mz_tolerance_range(precursor_mz, mz_tolerance, mz_tolerance_type)
        predicate = SpectrumFilter(
            ms_level=ms_level,
            rt_range=rt_range,
            polarity=polarity,
            precursor_mz_range=precursor_mz_range,
            spectrum_type=spectrum_type,
            ook0_range=ook0_range,
            drift_time_range=drift_time_range,
            faims_voltage_range=faims_voltage_range,
        )
        # Only a retention-time query on a reader that can read spectrum heads needs the count;
        # on a stream reader counting would read the whole file before the first result.
        if predicate.rt_range is not None and self._file_object.can_read_spectrum_heads():
            count = self.count
            if count is not None:
                return self._filter_rt_window(predicate, predicate.rt_range, count)
        return (spectrum for spectrum in self if predicate.matches(spectrum))

    def _filter_rt_window(
        self, predicate: SpectrumFilter, bounds: tuple[float | None, float | None], count: int
    ) -> Iterator[Spectrum]:
        """Read only spectra with a scan time inside ``bounds``, using the cached scan-time table.

        Correct for any record order: the table holds every spectrum's scan times.
        """
        table = self._scan_rt_table(count)
        if table is None:
            yield from (spectrum for spectrum in self if predicate.matches(spectrum))
            return
        for index in table.indices_within(bounds):
            spectrum = self.get_by_index(index)
            if predicate.matches(spectrum):
                yield spectrum

    def _scan_rt_table(self, count: int) -> _RtTable | None:
        """Scan times of every spectrum by index, read once and cached.

        Each spectrum's scan times come from the bytes before its binary arrays
        (:func:`_head_scan_rts`); a record those bytes cannot answer for exactly is parsed in
        full. None when the file cannot supply records by index (filters then scan every one).
        """
        if self._rt_table is None:
            heads = self._file_object.iter_spectrum_heads()
            if heads is None:
                return None
            table = _RtTable()
            for index, head in enumerate(heads):
                times = _head_scan_rts(head) if head is not None else None
                if times is None:
                    times = tuple(_scan_rts(self.get_by_index(index)))
                table.append(times)
            if len(table) != count:
                return None
            self._rt_table = table
        return self._rt_table

    def _get_by_index_impl(self, index: int) -> Spectrum:
        return self._file_object.get_spectrum_by_index(index)

    def _get_by_exact_id(self, identifier: str) -> Spectrum:
        return self._file_object.get_spectrum_by_id(identifier)

    def _get_ids_for_map(self) -> list[str]:
        return self._file_object.spectrum_ids

    def _get_count_impl(self) -> int | None:
        if self._count is not None:
            return self._count
        return self._file_object.spectrum_count

    def _iter_impl(self) -> Iterator[Spectrum]:
        return self._file_object.iter_spectra()


class ChromatogramLookup(BaseLookup[Chromatogram]):
    """Lookup interface for chromatograms."""

    def _get_by_index_impl(self, index: int) -> Chromatogram:
        return self._file_object.get_chromatogram_by_index(index)

    def _get_by_exact_id(self, identifier: str) -> Chromatogram:
        return self._file_object.get_chromatogram_by_id(identifier)

    def _get_ids_for_map(self) -> list[str]:
        return self._file_object.chromatogram_ids

    def _get_count_impl(self) -> int | None:
        if self._count is not None:
            return self._count
        return self._file_object.chromatogram_count

    def _iter_impl(self) -> Iterator[Chromatogram]:
        return self._file_object.iter_chromatograms()


__all__ = ["BaseLookup", "SpectrumLookup", "ChromatogramLookup"]
