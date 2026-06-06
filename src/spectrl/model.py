"""Data models for mzx encode input (InlineSpectrum) and decode output (DecodedSpectrum)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray


@dataclass
class SpectrlCvParam:
    """A CV parameter for use within mzx, mirroring mzML cvParam semantics.

    Accession and unit_accession use 'ONTOLOGY:NNNNNNN' format (e.g. 'MS:1000511', 'UO:0000031').
    A None value indicates a flag parameter (presence is the meaning).
    """

    accession: str
    value: float | int | str | None = None
    unit_accession: str | None = None


@dataclass
class SpectrlScanWindow:
    """A scan window with lower/upper m/z limits as CV params."""

    params: list[SpectrlCvParam] = field(default_factory=list)


@dataclass
class SpectrlScan:
    """A single scan event with timing and window metadata."""

    params: list[SpectrlCvParam] = field(default_factory=list)
    windows: list[SpectrlScanWindow] = field(default_factory=list)


@dataclass
class SpectrlIsolationWindow:
    """An isolation window with target m/z and offset params."""

    params: list[SpectrlCvParam] = field(default_factory=list)


@dataclass
class SpectrlSelectedIon:
    """A selected ion with m/z, charge, intensity params."""

    params: list[SpectrlCvParam] = field(default_factory=list)


@dataclass
class SpectrlActivation:
    """Activation method params (method as flag + energy as value)."""

    params: list[SpectrlCvParam] = field(default_factory=list)


@dataclass
class SpectrlPrecursor:
    """A precursor entry with isolation window, selected ions, and activation."""

    isolation_window: SpectrlIsolationWindow | None = None
    selected_ions: list[SpectrlSelectedIon] = field(default_factory=list)
    activation: SpectrlActivation | None = None
    spectrum_ref: str | None = None


@dataclass
class SpectrlProduct:
    """A product entry with an isolation window."""

    isolation_window: SpectrlIsolationWindow | None = None


@dataclass
class InlineSpectrum:
    """Input model for mzx encoding. Mirrors mzML spectrum structure.

    Attributes:
        default_array_length: Number of peaks (mzML @defaultArrayLength).
        mz: m/z array, must be sorted ascending.
        intensity: Intensity array.
        charge: Optional per-peak charge array.
        ion_mobility: Optional per-peak ion mobility array.
        ion_mobility_type: Accession string for the IM array type (e.g. 'MS:1003007').
        id: Spectrum identifier string (mzML @id), e.g. 'scan=12298'.
        params: Spectrum-level CV params (ms level, polarity, centroid flag, TIC, etc.).
        scans: List of scan entries.
        scan_combination: Optional scan-list combination CV param.
        precursors: List of precursor entries.
        products: List of product entries.
        interp: Optional ProForma 2.0 interpretation string (header key 8).
    """

    default_array_length: int
    mz: NDArray[np.float64] | None = None
    intensity: NDArray[np.float64] | None = None
    charge: NDArray[np.float64] | None = None
    ion_mobility: NDArray[np.float64] | None = None
    ion_mobility_type: str | None = None
    id: str | None = None
    params: list[SpectrlCvParam] = field(default_factory=list)
    scans: list[SpectrlScan] = field(default_factory=list)
    scan_combination: SpectrlCvParam | None = None
    precursors: list[SpectrlPrecursor] = field(default_factory=list)
    products: list[SpectrlProduct] = field(default_factory=list)
    interp: str | None = None


@dataclass
class DecodedSpectrum:
    """Output model from spectrl decoding.

    Mirrors InlineSpectrum but represents what was recovered from the token.
    The hash field (if present) is verified during decode.
    """

    default_array_length: int
    mz: NDArray[np.float64] | None = None
    intensity: NDArray[np.float64] | None = None
    charge: NDArray[np.float64] | None = None
    ion_mobility: NDArray[np.float64] | None = None
    ion_mobility_type: str | None = None
    id: str | None = None
    params: list[SpectrlCvParam] = field(default_factory=list)
    scans: list[SpectrlScan] = field(default_factory=list)
    scan_combination: SpectrlCvParam | None = None
    precursors: list[SpectrlPrecursor] = field(default_factory=list)
    products: list[SpectrlProduct] = field(default_factory=list)
    interp: str | None = None
    hash: str | None = None
    format_version: int = 1
