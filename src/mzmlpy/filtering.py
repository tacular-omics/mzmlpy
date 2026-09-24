"""Metadata predicates for lazy spectrum selection."""

import math
from dataclasses import dataclass
from numbers import Real
from typing import Literal, TypeGuard

import numpy as np

from .constants import Polarity, ToleranceUnit
from .errors import MzmlError
from .spectra import Spectrum


def _check_range(name: str, bounds: tuple[float | None, float | None] | None, *, signed: bool = False) -> None:
    if bounds is None:
        return
    if len(bounds) != 2:
        raise MzmlError(f"{name} must contain a lower and an upper bound")
    lower, upper = bounds
    if any(value is not None and not _is_number(value) for value in bounds):
        raise MzmlError(f"{name} bounds must be numbers or None")
    if any(value is not None and (not math.isfinite(value) or (not signed and value < 0)) for value in bounds):
        raise MzmlError(f"{name} bounds must be finite, nonnegative unless signed, or None")
    if lower is not None and upper is not None and lower > upper:
        raise MzmlError(f"{name} lower bound must not exceed the upper bound")


def _within(value: float | None, bounds: tuple[float | None, float | None]) -> bool:
    lower, upper = bounds
    return (
        value is not None
        and math.isfinite(value)
        and (lower is None or lower <= value)
        and (upper is None or value <= upper)
    )


def _is_number(value: object) -> TypeGuard[float]:
    """A real number other than a bool, including numpy scalars (``numbers.Real``)."""
    return isinstance(value, Real) and not isinstance(value, bool | np.bool_)


def _nonnegative(name: str, value: float) -> None:
    if not _is_number(value) or not math.isfinite(value) or value < 0:
        raise MzmlError(f"{name} must be a finite nonnegative number")


def check_point(name: str, value: object) -> None:
    """Reject a point query that is not one finite number, pointing tuples at ``{name}_range``."""
    if value is None:
        return
    if isinstance(value, tuple | list):
        raise MzmlError(f"{name} is a single value; pass bounds as {name}_range=(lower, upper)")
    if not _is_number(value) or not math.isfinite(value) or value < 0:
        raise MzmlError(f"{name} must be a finite nonnegative number")


def tolerance_range(value: float | None, tolerance: float, name: str) -> tuple[float, float] | None:
    """``(value - tolerance, value + tolerance)`` for a point query, clamped at 0, or None when ``value`` is None."""
    _nonnegative(name, tolerance)
    if value is None:
        return None
    value, tolerance = float(value), float(tolerance)
    return (max(0.0, value - tolerance), value + tolerance)


def mz_tolerance_range(mz: float | None, tolerance: float, tolerance_unit: ToleranceUnit) -> tuple[float, float] | None:
    """m/z bounds around ``mz`` for a tolerance in ppm or Da, matching tdfpy's ``query``."""
    if tolerance_unit not in {"da", "ppm"}:
        raise MzmlError("mz_tolerance_unit must be 'da' or 'ppm'")
    _nonnegative("mz_tolerance", tolerance)
    if mz is None:
        return None
    mz, tolerance = float(mz), float(tolerance)
    width = mz * tolerance / 1e6 if tolerance_unit == "ppm" else tolerance
    return (max(0.0, mz - width), mz + width)


@dataclass(frozen=True, kw_only=True)
class SpectrumFilter:
    """Combine metadata criteria with AND, without decoding binary arrays.

    Every range is an inclusive ``(lower, upper)`` tuple; either end may be None for an open
    bound. ``rt_range`` is in seconds and matches any scan. ``precursor_mz_range`` overlaps any
    reported isolation window, or matches a selected ion when that precursor has no usable
    isolation window. ``ook0_range`` (1/K0, Vs/cm²), ``drift_time_range`` and
    ``faims_voltage_range`` (signed volts) match any scan. Missing metadata does not match a
    requested criterion.
    """

    ms_level: int | None = None
    rt_range: tuple[float | None, float | None] | None = None
    polarity: Polarity | None = None
    precursor_mz_range: tuple[float | None, float | None] | None = None
    spectrum_type: Literal["centroid", "profile"] | None = None
    ook0_range: tuple[float | None, float | None] | None = None
    drift_time_range: tuple[float | None, float | None] | None = None
    faims_voltage_range: tuple[float | None, float | None] | None = None

    def __post_init__(self) -> None:
        if self.ms_level is not None and (type(self.ms_level) is not int or self.ms_level < 1):
            raise MzmlError("ms_level must be a positive integer")
        if self.polarity not in {None, "positive", "negative"}:
            raise MzmlError("polarity must be 'positive' or 'negative'")
        if self.spectrum_type not in {None, "centroid", "profile"}:
            raise MzmlError("spectrum_type must be centroid or profile")
        _check_range("ook0_range", self.ook0_range)
        _check_range("drift_time_range", self.drift_time_range)
        _check_range("faims_voltage_range", self.faims_voltage_range, signed=True)
        _check_range("rt_range", self.rt_range)
        _check_range("precursor_mz_range", self.precursor_mz_range)

    def matches(self, spectrum: Spectrum) -> bool:
        """Return whether a spectrum satisfies every supplied criterion."""
        if self.ms_level is not None and spectrum.ms_level != self.ms_level:
            return False
        if self.spectrum_type is not None and spectrum.spectrum_type != self.spectrum_type:
            return False
        if self.polarity is not None and spectrum.polarity != self.polarity:
            return False
        if self.rt_range is not None and not any(_within(scan.rt, self.rt_range) for scan in spectrum.scans):
            return False
        if self.ook0_range is not None and not any(_within(scan.ook0, self.ook0_range) for scan in spectrum.scans):
            return False
        if self.drift_time_range is not None and not any(
            _within(scan.drift_time, self.drift_time_range) for scan in spectrum.scans
        ):
            return False
        if self.faims_voltage_range is not None and not any(
            _within(scan.faims_compensation_voltage, self.faims_voltage_range) for scan in spectrum.scans
        ):
            return False
        if self.precursor_mz_range is not None and not self._matches_precursor(spectrum, self.precursor_mz_range):
            return False
        return True

    @staticmethod
    def _matches_precursor(spectrum: Spectrum, bounds: tuple[float | None, float | None]) -> bool:
        lower, upper = bounds
        for precursor in spectrum.precursors:
            window = precursor.isolation_window
            if window is not None and not window.no_isolation and window.isolation_mz is not None:
                target = window.isolation_mz
                left, right = window.lower_offset, window.upper_offset
                if (
                    left is not None
                    and right is not None
                    and all(math.isfinite(v) and v >= 0 for v in (target, left, right))
                ):
                    if (lower is None or target + right >= lower) and (upper is None or target - left <= upper):
                        return True
                    continue
            if any(_within(ion.mz, bounds) for ion in precursor.selected_ions):
                return True
        return False


__all__ = ["SpectrumFilter"]
