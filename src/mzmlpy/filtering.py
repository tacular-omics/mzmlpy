"""Metadata predicates for lazy spectrum selection."""

import math
from dataclasses import dataclass
from typing import Literal

from .spectra import Spectrum


def _check_range(name: str, bounds: tuple[float | None, float | None] | None) -> None:
    if bounds is None:
        return
    if len(bounds) != 2:
        raise ValueError(f"{name} must contain a lower and an upper bound")
    lower, upper = bounds
    if any(value is not None and (not math.isfinite(value) or value < 0) for value in bounds):
        raise ValueError(f"{name} bounds must be finite and nonnegative, or None")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError(f"{name} lower bound must not exceed the upper bound")


def _within(value: float | None, bounds: tuple[float | None, float | None]) -> bool:
    lower, upper = bounds
    return (
        value is not None
        and math.isfinite(value)
        and (lower is None or lower <= value)
        and (upper is None or value <= upper)
    )


@dataclass(frozen=True)
class SpectrumFilter:
    """Combine metadata criteria with AND, without decoding binary arrays.

    Retention times are inclusive bounds in seconds, matched against any scan. Precursor
    m/z bounds overlap any reported isolation window, or match a selected ion when that
    precursor has no usable isolation window. Missing metadata does not match a requested
    criterion. Either range endpoint may be None for an open bound.
    """

    ms_level: int | None = None
    retention_time: tuple[float | None, float | None] | None = None
    polarity: Literal["positive", "negative"] | None = None
    precursor_mz: tuple[float | None, float | None] | None = None

    def __post_init__(self) -> None:
        if self.ms_level is not None and (type(self.ms_level) is not int or self.ms_level < 1):
            raise ValueError("ms_level must be a positive integer")
        if self.polarity not in {None, "positive", "negative"}:
            raise ValueError("polarity must be 'positive' or 'negative'")
        _check_range("retention_time", self.retention_time)
        _check_range("precursor_mz", self.precursor_mz)

    def matches(self, spectrum: Spectrum) -> bool:
        """Return whether a spectrum satisfies every supplied criterion."""
        if self.ms_level is not None and spectrum.ms_level != self.ms_level:
            return False
        if self.polarity is not None and spectrum.polarity != self.polarity:
            return False
        if self.retention_time is not None:
            if not any(
                (time := scan.scan_start_time) is not None and _within(time.total_seconds(), self.retention_time)
                for scan in spectrum.scans
            ):
                return False
        if self.precursor_mz is not None and not self._matches_precursor(spectrum):
            return False
        return True

    def _matches_precursor(self, spectrum: Spectrum) -> bool:
        assert self.precursor_mz is not None
        lower, upper = self.precursor_mz
        for precursor in spectrum.precursors:
            window = precursor.isolation_window
            if window is not None and not window.no_isolation and window.target_mz is not None:
                target = window.target_mz
                left, right = window.lower_offset, window.upper_offset
                if (
                    left is not None
                    and right is not None
                    and all(math.isfinite(v) and v >= 0 for v in (target, left, right))
                ):
                    if (lower is None or target + right >= lower) and (upper is None or target - left <= upper):
                        return True
                    continue
            if any(_within(ion.selected_ion_mz, self.precursor_mz) for ion in precursor.selected_ions):
                return True
        return False
