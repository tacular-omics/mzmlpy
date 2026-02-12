from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import overload

from .file_interface import FileInterface
from .spectra import Chromatogram, Spectrum


class BaseLookup[T: (Spectrum, Chromatogram)](ABC):
    """Base class for spectrum and chromatogram lookups."""

    def __init__(self, file_object: FileInterface, count: int | None = None) -> None:
        self.file_object = file_object
        self._count = count

    def get_by_index(self, index: int | str) -> T:
        """Get item by index."""
        if isinstance(index, str):
            index = int(index)
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
        """Get next item using iterator."""
        return next(iter(self))

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

    def _get_by_index_impl(self, index: int) -> Spectrum:
        return self.file_object.get_spectrum_by_index(index)

    def _get_by_id_impl(self, identifier: str) -> Spectrum:
        return self.file_object.get_spectrum_by_id(identifier)

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
        return self.file_object.get_chromatogram_by_id(identifier)

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
