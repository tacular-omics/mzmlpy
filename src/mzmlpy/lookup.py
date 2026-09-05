import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import cached_property
from typing import Literal, overload

from .file_interface import FileInterface
from .filtering import SpectrumFilter
from .spectra import Chromatogram, Spectrum


class BaseLookup[T: (Spectrum, Chromatogram)](ABC):
    """Base class for spectrum and chromatogram lookups."""

    def __init__(self, file_object: FileInterface, count: int | None = None, id_regex: str | None = None) -> None:
        self.file_object = file_object
        self._count = count
        self._id_regex = id_regex
        self._cursor: Iterator[T] | None = None

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

    def get_by_index(self, index: int | str) -> T:
        """Get item by index. Negative indices count from the end, like a list."""
        if isinstance(index, str):
            index = int(index)
        if index < 0:
            # Normalize against the count so lookup[-1] mirrors slice behavior (lookup[-1:]).
            count = self.count
            if count is not None:
                index += count
            if index < 0:
                raise IndexError("Index out of range")
        return self._get_by_index_impl(index)

    def get_by_id(self, identifier: str) -> T:
        """Get item by ID."""
        return self._get_by_id_impl(identifier)

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
        return self.get_by_id(index)

    def next(self) -> T:
        """Advance a persistent cursor and return the next item.

        The cursor is created on first call and advances on each subsequent call, raising
        ``StopIteration`` once every item has been returned. Call :meth:`reset` to start over.
        """
        if self._cursor is None:
            self._cursor = iter(self)
        return next(self._cursor)

    def reset(self) -> None:
        """Reset the cursor used by :meth:`next` so the next call starts from the first item."""
        self._cursor = None

    # Abstract methods to be implemented by subclasses
    @abstractmethod
    def _get_by_index_impl(self, index: int) -> T:
        """Get item by index implementation."""
        ...

    @abstractmethod
    def _get_by_id_impl(self, identifier: str) -> T:
        """Get item by ID implementation."""
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

    def __contains__(self, identifier: str) -> bool:
        """Check if item with given ID exists."""
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
        retention_time: tuple[float | None, float | None] | None = None,
        polarity: Literal["positive", "negative"] | None = None,
        precursor_mz: tuple[float | None, float | None] | None = None,
        spectrum_type: Literal["centroid", "profile"] | None = None,
        mobility_type: Literal["inverse_reduced", "drift_time"] | None = None,
        ion_mobility: tuple[float | None, float | None] | None = None,
        faims_voltage: tuple[float | None, float | None] | None = None,
    ) -> Iterator[Spectrum]:
        """Lazily select spectra by metadata, using inclusive time bounds in seconds.

        Criteria are combined with AND. Retention time matches any scan. Precursor m/z
        matches overlapping isolation windows, with selected ions as a fallback. Missing
        metadata does not match a requested criterion. Keep the reader open while iterating.
        """
        predicate = SpectrumFilter(
            ms_level, retention_time, polarity, precursor_mz, spectrum_type, mobility_type, ion_mobility, faims_voltage
        )
        return (spectrum for spectrum in self if predicate.matches(spectrum))

    def _get_by_index_impl(self, index: int) -> Spectrum:
        return self.file_object.get_spectrum_by_index(index)

    def _get_by_id_impl(self, identifier: str) -> Spectrum:
        try:
            return self.file_object.get_spectrum_by_id(identifier)
        except KeyError:
            if self._id_regex is not None and (mapped := self._id_map.get(identifier)):
                return self.file_object.get_spectrum_by_id(mapped)
            raise

    def _get_ids_for_map(self) -> list[str]:
        return self.file_object.spectrum_ids

    def _get_count_impl(self) -> int | None:
        if self._count is not None:
            return self._count
        return self.file_object.spectrum_count

    def _iter_impl(self) -> Iterator[Spectrum]:
        return self.file_object.iter_spectra()


class ChromatogramLookup(BaseLookup[Chromatogram]):
    """Lookup interface for chromatograms."""

    def _get_by_index_impl(self, index: int) -> Chromatogram:
        return self.file_object.get_chromatogram_by_index(index)

    def _get_by_id_impl(self, identifier: str) -> Chromatogram:
        try:
            return self.file_object.get_chromatogram_by_id(identifier)
        except KeyError:
            if self._id_regex is not None and (mapped := self._id_map.get(identifier)):
                return self.file_object.get_chromatogram_by_id(mapped)
            raise

    def _get_ids_for_map(self) -> list[str]:
        return self.file_object.chromatogram_ids

    def _get_count_impl(self) -> int | None:
        if self._count is not None:
            return self._count
        return self.file_object.chromatogram_count

    def _iter_impl(self) -> Iterator[Chromatogram]:
        return self.file_object.iter_chromatograms()

    @property
    def TIC(self) -> Chromatogram:
        """Access Total Ion Chromatogram."""
        return self.file_object.TIC
