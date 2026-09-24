import math
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import cached_property
from typing import Literal, overload

from .errors import MzmlError
from .file_interface import AccessStrategy, FileInterface
from .filtering import SpectrumFilter, check_point, mz_tolerance_range, tolerance_range
from .spectra import Chromatogram, Spectrum

# How far a retention-time probe walks past spectra without a scan time before giving up.
_RT_SEARCH_WALK = 64
_NO_RT_NEARBY = object()


def _scan_rts(spectrum: Spectrum) -> list[float]:
    """Finite scan start times of every scan in ``spectrum``, in seconds."""
    return [value for scan in spectrum.scans if (value := scan.rt) is not None and math.isfinite(value)]


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

        With a random-access reader (every access strategy except ``stream``), a retention-time
        criterion binary-searches the file and stops after the window, so it reads only the
        spectra near it. This assumes spectra are stored in retention-time order, as instrument
        files are. For a file that is not (e.g. merged runs), iterate ``reader.spectra`` and test
        each spectrum with :meth:`SpectrumFilter.matches`.

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
        count = self.count
        if (
            predicate.rt_range is not None
            and count is not None
            and getattr(self._file_object, "access_strategy", AccessStrategy.STREAM) != AccessStrategy.STREAM
        ):
            return self._filter_rt_window(predicate, predicate.rt_range, count)
        return (spectrum for spectrum in self if predicate.matches(spectrum))

    def _filter_rt_window(
        self, predicate: SpectrumFilter, bounds: tuple[float | None, float | None], count: int
    ) -> Iterator[Spectrum]:
        """Binary-search the first spectrum that can reach ``bounds``, then scan until past it."""
        lower, upper = bounds
        start = 0
        if lower is not None:
            left, right = 0, count
            while left < right:
                middle = (left + right) // 2
                latest = self._latest_rt_from(middle, count)
                if latest is _NO_RT_NEARBY:
                    # Retention times are too sparse to search; select with a full scan instead.
                    yield from (spectrum for spectrum in self if predicate.matches(spectrum))
                    return
                if not isinstance(latest, float) or latest >= lower:
                    right = middle
                else:
                    left = middle + 1
            start = left
        for index in range(start, count):
            spectrum = self.get_by_index(index)
            times = _scan_rts(spectrum)
            if upper is not None and times and min(times) > upper:
                return
            if predicate.matches(spectrum):
                yield spectrum

    def _latest_rt_from(self, index: int, count: int) -> float | None | object:
        """Latest scan time of the first spectrum at or after ``index`` that has one.

        None means no later spectrum has a time. ``_NO_RT_NEARBY`` means none was found within
        a short walk.
        """
        for position in range(index, min(count, index + _RT_SEARCH_WALK)):
            if times := _scan_rts(self.get_by_index(position)):
                return max(times)
        return None if index + _RT_SEARCH_WALK >= count else _NO_RT_NEARBY

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
