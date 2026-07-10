"""Spectrum, Chromatogram, and related mixin/helper classes for parsing mzML binary and metadata structures.

This module provides `Spectrum` and `Chromatogram` as the primary data-access types, backed by
a set of internal mixin classes (`_BinaryDataArrayMixin`, `_ScanListMixin`, `_PrecursorListMixin`,
`_ProductListMixin`) that compose binary data, scan, precursor, and product functionality.
`BinaryDataArray` handles base64 decoding and decompression for a single `binaryDataArray` XML element.
"""

import base64
import contextlib
import warnings
from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from .constants import (
    BINARY_DECODE_DTYPES,
    ION_MOBILITIES,
    ActivationAccession,
    BinaryDataArrayAccession,
    BinaryDataTypeAccession,
    ChromatogramTypeAccession,
    CollisionDissociationTypeAccession,
    CompressionTypeAccessions,
    IsolationWindowAccession,
    MzMLElement,
    ScanPolarity,
    SelectedIonAccession,
    SpectrumCombinationAccession,
    SpectrumMSAccession,
    XMLElement,
)
from .constants import SpectrumType as SpectrumTypeAccessions
from .decoder import MSDecoder
from .elems.dtree_wrapper import _DataTreeWrapper, _DataTreeWrapperProtocol, _ParamGroup


def decode_to_numpy(data: bytes, data_type: str) -> NDArray[np.float64]:
    dtype = _resolve_dtype(data_type)
    if len(data) % dtype.itemsize != 0:
        raise ValueError(
            f"Cannot decode binary array: {len(data)} bytes is not a multiple of the "
            f"{dtype.itemsize}-byte element size for data type {data_type!r}. The data may be "
            f"corrupt, truncated, or use a truncation encoding that mzmlpy does not support."
        )
    return np.frombuffer(data, dtype=dtype).astype(np.float64)


def _resolve_dtype(data_type: str) -> np.dtype:
    """Resolve a binary data type accession to a NumPy dtype."""
    try:
        accession = BinaryDataTypeAccession(data_type)
    except ValueError:
        accession = None
    dtype_str = BINARY_DECODE_DTYPES.get(accession) if accession is not None else None
    if dtype_str is None:
        raise ValueError(
            f"Unsupported or unknown binary data type accession {data_type!r}; mzmlpy can decode "
            f"32-/64-bit float and 32-/64-bit integer arrays."
        )
    return np.dtype(dtype_str)


def _parse_native_id(identifier: str) -> dict[str, int | str]:
    """Parse a native spectrum/chromatogram id into its space-separated ``key=value`` components.

    Integer values are coerced to ``int``; everything else stays a ``str``. Tokens without an
    ``=`` are skipped. Example::

        _parse_native_id("controllerType=0 controllerNumber=1 scan=19")
        # {"controllerType": 0, "controllerNumber": 1, "scan": 19}
    """
    result: dict[str, int | str] = {}
    for token in identifier.split():
        key, sep, value = token.partition("=")
        if not sep:
            continue
        try:
            # Only coerce when the int round-trips exactly back to the original token, so values
            # like "007" (leading zeros) or "1_000" (underscores) stay strings and keep matching
            # the on-disk id instead of silently becoming 7 / 1000.
            coerced = int(value)
            result[key] = coerced if str(coerced) == value else value
        except ValueError:
            result[key] = value
    return result


@dataclass(frozen=True)
class BinaryDataArray(_ParamGroup):
    """Wraps a single `binaryDataArray` XML element, handling base64 decoding and decompression.

    Exposes compression type, numeric encoding, semantic array type, and a `data` property
    that decodes the raw bytes into a NumPy array on each access.
    """

    @cached_property
    def compression(self) -> CompressionTypeAccessions | None:
        """Return the compression accession for this array, or None if no compression CV term is present."""
        for param in self.cv_params:
            with contextlib.suppress(ValueError):
                return CompressionTypeAccessions(param.accession)
        return None

    @cached_property
    def encoding(self) -> BinaryDataTypeAccession | None:
        """Return the binary data type accession (e.g. 32-bit or 64-bit float/int), or None if absent."""
        for bdaa in BinaryDataTypeAccession:
            if bdaa in self.accessions:
                return bdaa
        return None

    @cached_property
    def binary_array_type(self) -> BinaryDataArrayAccession | None:
        """Return the semantic array type accession (e.g. m/z, intensity, ion mobility), or None if absent."""
        for bdaa in BinaryDataArrayAccession:
            if bdaa in self.accessions:
                return bdaa

    def _decode(self) -> np.ndarray:

        # Get compression and encoding from cached properties
        compression_type = self.compression
        binary_data_type = self.encoding

        if compression_type is None:
            compression_type = CompressionTypeAccessions.NO_COMPRESSION
            warnings.warn(f"Compression type not specified. Assuming {compression_type}.", UserWarning, stacklevel=2)

        if binary_data_type is None:
            binary_data_type = BinaryDataTypeAccession.FLOAT_64
            warnings.warn(f"Binary data type not specified. Assuming {binary_data_type}.", UserWarning, stacklevel=2)
        # Get binary data from element
        binary_element = self.element.find(f"./{self.ns}binary")
        if binary_element is None or binary_element.text is None:
            return np.array([], dtype=np.float64)

        # Decode base64
        try:
            out_data = base64.b64decode(binary_element.text)
        except ValueError as e:  # binascii.Error subclasses ValueError
            raise ValueError(
                f"Failed to base64-decode binary data array (data type {binary_data_type}): {e}"
            ) from e

        if len(out_data) == 0:
            return np.array([], dtype=np.float64)

        # Decompress based on compression type
        match compression_type:
            case CompressionTypeAccessions.BYTE_SHUFFLED_ZSTD:
                unshuffled = MSDecoder.decode_byte_shuffled_zstd(out_data, _resolve_dtype(binary_data_type).itemsize)
                return decode_to_numpy(unshuffled, binary_data_type)
            case CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT:
                return MSDecoder.decode_slof(out_data)
            case CompressionTypeAccessions.TRUNCATION_LINEAR_PREDICTION_ZLIB:
                # Reverse the linear predictor in native precision, then widen to float64.
                native = np.frombuffer(MSDecoder.decode_zlib(out_data), dtype=_resolve_dtype(binary_data_type))
                return MSDecoder.reverse_linear_prediction(native).astype(np.float64)
            case CompressionTypeAccessions.ZLIB_COMPRESSION:
                return decode_to_numpy(MSDecoder.decode_zlib(out_data), binary_data_type)
            case CompressionTypeAccessions.NO_COMPRESSION:
                return decode_to_numpy(out_data, binary_data_type)
            case CompressionTypeAccessions.DICTIONARY_ENCODED_ZSTD:
                return MSDecoder.decode_dict_encoded_zstd(out_data, _resolve_dtype(binary_data_type))
            case CompressionTypeAccessions.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB:
                return MSDecoder.decode_linear(MSDecoder.decode_zlib(out_data))
            case CompressionTypeAccessions.TRUNCATION_ZLIB:
                return decode_to_numpy(MSDecoder.decode_zlib(out_data), binary_data_type)
            case CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB:
                return MSDecoder.decode_slof(MSDecoder.decode_zlib(out_data))
            case CompressionTypeAccessions.MS_NUMPRESS_LINEAR_PREDICTION_ZSTD:
                return MSDecoder.decode_linear(MSDecoder.decode_ztsd(out_data))
            case CompressionTypeAccessions.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB:
                return MSDecoder.decode_pic(MSDecoder.decode_zlib(out_data))
            case CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZSTD:
                return MSDecoder.decode_slof(MSDecoder.decode_ztsd(out_data))
            case CompressionTypeAccessions.MS_NUMPRESS_LINEAR_PREDICTION:
                return MSDecoder.decode_linear(out_data)
            case CompressionTypeAccessions.MS_NUMPRESS_POSITIVE_INTEGER:
                return MSDecoder.decode_pic(out_data)
            case CompressionTypeAccessions.TRUNCATION_DELTA_PREDICTION_ZLIB:
                # Reverse the delta predictor in native precision, then widen to float64.
                native = np.frombuffer(MSDecoder.decode_zlib(out_data), dtype=_resolve_dtype(binary_data_type))
                return MSDecoder.reverse_delta_prediction(native).astype(np.float64)
            case CompressionTypeAccessions.ZSTD_COMPRESSION:
                return decode_to_numpy(MSDecoder.decode_ztsd(out_data), binary_data_type)
            case CompressionTypeAccessions.MS_NUMPRESS_POSITIVE_INTEGER_ZSTD:
                return MSDecoder.decode_pic(MSDecoder.decode_ztsd(out_data))
            case _:
                try:
                    return decode_to_numpy(out_data, binary_data_type)
                except Exception as e:
                    raise ValueError(f"Unsupported compression type: {compression_type}") from e

    @property
    def data(self) -> np.ndarray:
        """Decode and return the binary data as a NumPy array.

        Decoding runs on every access — store the result in a local variable if you need it more than once.
        """
        return self._decode()


@dataclass(frozen=True)
class _BinaryDataArrayList(_ParamGroup):
    """Internal wrapper for a `binaryDataArrayList` XML element.

    Provides iteration and lookup over the child `BinaryDataArray` objects.
    """

    @property
    def binary_arrays(self) -> list[BinaryDataArray]:
        """Get a list of BinaryDataConverter objects for each binary data array."""
        return [BinaryDataArray(elem) for elem in self.element.findall(f"./{self.ns}{XMLElement.BINARY_DATA_ARRAY}")]

    def get_binary_array(self, id: str) -> BinaryDataArray | None:
        """Get a BinaryDataConverter object for the binary data array with the specified id."""
        for binary_array in self.binary_arrays:
            if id in binary_array.accessions or id in binary_array.names:
                return binary_array
        return None

    def has_binary_array(self, id: str) -> bool:
        """Check if a binary data array with the specified id exists."""
        return self.get_binary_array(id) is not None


@dataclass(frozen=True)
class _BinaryDataArrayMixin(_DataTreeWrapperProtocol):
    """Mixin that adds binary array access to classes wrapping an XML element with a `binaryDataArrayList` child.

    Used by both `Spectrum` and `Chromatogram` to expose `binary_arrays`, `get_binary_array`, and
    `has_binary_array` without duplicating logic.
    """

    @property
    def _binary_array_list(self) -> _BinaryDataArrayList | None:
        """Get a BinaryDataArrayList object for the binary data array list of this spectrum, if present."""
        binary_array_list_element = self.element.find(f"./{self.ns}{XMLElement.BINARY_DATA_ARRAY_LIST}")
        if binary_array_list_element is not None:
            return _BinaryDataArrayList(binary_array_list_element)
        return None

    @property
    def binary_arrays(self) -> list[BinaryDataArray]:
        """Get a list of BinaryDataConverter objects for each binary data array."""
        if self._binary_array_list is not None:
            return self._binary_array_list.binary_arrays
        return []

    def get_binary_array(self, id: str) -> BinaryDataArray | None:
        """Get a BinaryDataConverter object for the binary data array with the specified id."""
        if self._binary_array_list is not None:
            return self._binary_array_list.get_binary_array(id)
        return None

    def has_binary_array(self, id: str) -> bool:
        """Check if a binary data array with the specified id exists."""
        if self._binary_array_list is not None:
            return self._binary_array_list.has_binary_array(id)
        return False


@dataclass(frozen=True)
class ScanWindow(_ParamGroup):
    """A scan window defining the m/z range acquired in a single scan."""

    @property
    def lower_mz(self) -> float | None:
        """Get scan window lower limit for this spectrum."""
        # The accession (MS:1000501) already identifies this as an m/z limit, so the value is
        # taken regardless of how the unit is expressed (unitName, unitAccession only, or absent).
        return self.cv_float(SpectrumMSAccession.SCAN_WINDOW_LOWER_LIMIT)

    @property
    def upper_mz(self) -> float | None:
        """Get scan window upper limit for this spectrum."""
        return self.cv_float(SpectrumMSAccession.SCAN_WINDOW_UPPER_LIMIT)


@dataclass(frozen=True)
class _ScanWindowList(_ParamGroup):
    """A list of scan windows for a single scan event."""

    @property
    def scan_windows(self) -> list[ScanWindow]:
        """Get a list of ScanWindow objects for each scan window in the scan window list."""
        return [ScanWindow(elem) for elem in self.element.findall(f"./{self.ns}{XMLElement.SCAN_WINDOW}")]

    @property
    def has_scan_windows(self) -> bool:
        """Check if this scan has a scan window list."""
        return self.element.find(f"./{self.ns}{XMLElement.SCAN_WINDOW}") is not None


@dataclass(frozen=True)
class Scan(_ParamGroup):
    """A single scan event with timing, window, and CV parameter metadata."""

    @property
    def _has_scan_windows_list(self) -> bool:
        """Check if this scan has a scan window list."""
        return self.element.find(f"./{self.ns}{XMLElement.SCAN_WINDOW_LIST}") is not None

    @property
    def _scan_window_list(self) -> _ScanWindowList | None:
        """Get a ScanWindowList object for the scan window list of this scan, or None."""
        scan_window_list_element = self.element.find(f"./{self.ns}{XMLElement.SCAN_WINDOW_LIST}")
        if scan_window_list_element is not None:
            return _ScanWindowList(scan_window_list_element)
        return None

    @property
    def scan_windows(self) -> list[ScanWindow]:
        """Get a list of ScanWindow objects for the scan window list of this scan."""
        return (
            self._scan_window_list.scan_windows
            if self._has_scan_windows_list and self._scan_window_list is not None
            else []
        )

    @property
    def is_single_windowed_scan(self) -> bool:
        """Check if this scan has a single scan window."""
        return (
            self._has_scan_windows_list
            and self._scan_window_list is not None
            and len(self._scan_window_list.scan_windows) == 1
        )

    @property
    def lower_mz(self) -> float | None:
        """Get scan window lower limit for this scan, if it has a single scan window."""
        if self._scan_window_list is not None:
            if not self.is_single_windowed_scan:
                warnings.warn(
                    "This scan has multiple scan windows. Cannot determine a single lower limit.",
                    UserWarning,
                    stacklevel=2,
                )
                return None
            return self.scan_windows[0].lower_mz
        return None

    @property
    def upper_mz(self) -> float | None:
        """Get scan window upper limit for this scan, if it has a single scan window."""
        if self._scan_window_list is not None:
            if not self.is_single_windowed_scan:
                warnings.warn(
                    "This scan has multiple scan windows. Cannot determine a single upper limit.",
                    UserWarning,
                    stacklevel=2,
                )
                return None
            return self.scan_windows[0].upper_mz
        return None

    @property
    def scan_start_time(self) -> timedelta | None:
        """Get scan start time for this scan."""
        cv = self.get_cvparm(SpectrumMSAccession.SCAN_START_TIME)
        return cv.to_timedelta if cv is not None else None

    @property
    def ion_injection_time(self) -> timedelta | None:
        """Get ion injection time for this scan."""
        cv = self.get_cvparm(SpectrumMSAccession.ION_INJECTION_TIME)
        return cv.to_timedelta if cv is not None else None

    @property
    def inverse_reduced_ion_mobility(self) -> float | None:
        """Inverse reduced ion mobility (1/K0) for this scan (MS:1002815), e.g. Bruker timsTOF."""
        return self.cv_float(SpectrumMSAccession.INVERSE_REDUCED_ION_MOBILITY)

    @property
    def ion_mobility_drift_time(self) -> float | None:
        """Ion mobility drift time for this scan (MS:1002476)."""
        return self.cv_float(SpectrumMSAccession.ION_MOBILITY_DRIFT_TIME)

    @property
    def filter_string(self) -> str | None:
        """Instrument filter string for this scan (MS:1000512), e.g. a Thermo scan filter."""
        cv = self.get_cvparm(SpectrumMSAccession.FILTER_STRING)
        return cv.value if cv is not None else None

    @property
    def faims_compensation_voltage(self) -> float | None:
        """FAIMS compensation voltage for this scan (MS:1001581).

        Front-end high-field asymmetric waveform ion mobility (FAIMS) filtering: each scan may
        carry a single compensation voltage. See the PSI IM-MS/DIA recommendation v1.0, §3.6.
        """
        return self.cv_float(SpectrumMSAccession.FAIMS_COMPENSATION_VOLTAGE)

    @property
    def selexion_separation_voltage(self) -> float | None:
        """SCIEX SelexION differential-mobility separation voltage for this scan (MS:1003394)."""
        return self.cv_float(SpectrumMSAccession.SELEXION_SEPARATION_VOLTAGE)

    @property
    def selexion_compensation_voltage(self) -> float | None:
        """SCIEX SelexION differential-mobility compensation voltage for this scan (MS:1003371)."""
        return self.cv_float(SpectrumMSAccession.SELEXION_COMPENSATION_VOLTAGE)


@dataclass(frozen=True)
class _ScanList(_ParamGroup):
    """Internal wrapper for a `scanList` XML element.

    Parses the list of `Scan` objects and the optional spectrum-combination CV term.
    """

    @property
    def scans(self) -> list[Scan]:
        """Get a list of Scan objects for each scan in the scan list."""
        return [Scan(elem) for elem in self.element.findall(f"./{self.ns}{XMLElement.SCAN}")]

    @property
    def spectra_combination(self) -> SpectrumCombinationAccession | None:
        """Get spectrum combination type (if any) for this spectrum."""
        for cvparam in self.cv_params:
            with contextlib.suppress(ValueError):
                return SpectrumCombinationAccession(cvparam.accession)
        return None


@dataclass(frozen=True)
class _ScanListMixin(_DataTreeWrapperProtocol):
    """Mixin that exposes scan-level convenience properties on `Spectrum`.

    Delegates to the first scan for single-valued properties such as `scan_start_time`,
    `ion_injection_time`, `lower_mz`, and `upper_mz`, emitting a warning when multiple
    scans are present.
    """

    @property
    def _has_scan_list(self) -> bool:
        """Check if this spectrum has a scan list."""
        return self.element.find(f"./{self.ns}{XMLElement.SCAN_LIST}") is not None

    @property
    def _scan_list(self) -> _ScanList | None:
        """Get a ScanList object for the scan list of this spectrum, or None if no scan list is present."""
        scan_list_element = self.element.find(f"./{self.ns}{XMLElement.SCAN_LIST}")
        if scan_list_element is not None:
            return _ScanList(scan_list_element)
        return None

    @property
    def spectra_combination(self) -> Literal["no_combination", "median", "sum", "mean"] | None:
        """Get spectrum combination type (if any) for this spectrum."""
        if self._has_scan_list and self._scan_list is not None:
            comb = self._scan_list.spectra_combination
            match comb:
                case SpectrumCombinationAccession.NO_COMBINATION:
                    return "no_combination"
                case SpectrumCombinationAccession.MEDIAN:
                    return "median"
                case SpectrumCombinationAccession.SUM:
                    return "sum"
                case SpectrumCombinationAccession.MEAN:
                    return "mean"
        return None

    @property
    def scans(self) -> list[Scan]:
        """Get a list of Scan objects for the scan list of this spectrum, or None if no scan list is present."""
        if self._has_scan_list and self._scan_list is not None:
            return self._scan_list.scans
        return []

    @property
    def is_single_scan(self) -> bool:
        """Check if this spectrum has a single scan."""
        return self._has_scan_list and self._scan_list is not None and len(self._scan_list.scans) == 1

    """
    Properties to grab from scan list
    """

    def _first_scan(self, quantity: str) -> "Scan | None":
        """Return the first scan for delegating a single-scan property.

        Returns None when there is no scan list or it is empty (a valid case, e.g. an empty
        ``<scanList count="0">``). Warns only when there is genuinely more than one scan — not
        for zero scans.
        """
        if self._scan_list is None:
            return None
        scans = self.scans
        if not scans:
            return None
        if len(scans) > 1:
            warnings.warn(
                f"This spectrum has multiple scans. Returning {quantity} of the first scan.",
                UserWarning,
                stacklevel=3,
            )
        return scans[0]

    @property
    def lower_mz(self) -> float | None:
        """Get scan window lower limit for this spectrum, if it has a single scan with a single scan window."""
        scan = self._first_scan("lower limit")
        return scan.lower_mz if scan is not None else None

    @property
    def upper_mz(self) -> float | None:
        """Get scan window upper limit for this spectrum, if it has a single scan with a single scan window."""
        scan = self._first_scan("upper limit")
        return scan.upper_mz if scan is not None else None

    @property
    def scan_start_time(self) -> timedelta | None:
        """Get scan start time for this spectrum, if it has a single scan."""
        scan = self._first_scan("scan start time")
        return scan.scan_start_time if scan is not None else None

    @property
    def ion_injection_time(self) -> timedelta | None:
        """Get ion injection time for this spectrum, if it has a single scan."""
        scan = self._first_scan("ion injection time")
        return scan.ion_injection_time if scan is not None else None

    @property
    def ion_mobility(self) -> float | None:
        """Scan-level ion mobility for this spectrum: inverse reduced ion mobility (preferred) or
        drift time. Common for Bruker timsTOF PASEF MS2, where mobility is a scan cvParam rather
        than a binary array. Returns None if the spectrum has no single scan or no mobility term.
        """
        scan = self._first_scan("ion mobility")
        if scan is None:
            return None
        irim = scan.inverse_reduced_ion_mobility
        return irim if irim is not None else scan.ion_mobility_drift_time

    @property
    def filter_string(self) -> str | None:
        """Scan filter string for this spectrum (from its single scan), if present."""
        scan = self._first_scan("filter string")
        return scan.filter_string if scan is not None else None


@dataclass(frozen=True, repr=False)
class IsolationWindow(_ParamGroup):
    """Represents an isolation window element from a precursor or product.

    Provides access to the target m/z, lower offset, and upper offset values.
    """

    @property
    def target_mz(self) -> float | None:
        """Get isolation window target m/z for this precursor."""
        return self.cv_float(IsolationWindowAccession.TARGET_MZ)

    @property
    def lower_offset(self) -> float | None:
        """Get isolation window lower offset for this precursor."""
        return self.cv_float(IsolationWindowAccession.LOWER_OFFSET)

    @property
    def upper_offset(self) -> float | None:
        """Get isolation window upper offset for this precursor."""
        return self.cv_float(IsolationWindowAccession.UPPER_OFFSET)

    @property
    def no_isolation(self) -> bool:
        """Whether this window carries the "no isolation" marker (MS:1003159).

        Full-mass-range DIA (e.g. MSE/HDMSE) sets this on an otherwise-empty isolationWindow to
        signal that no precursor was isolated (PSI IM-MS/DIA recommendation v1.0, §3.5).
        """
        return IsolationWindowAccession.NO_ISOLATION in self.accessions


@dataclass(frozen=True, repr=False)
class SelectedIon(_ParamGroup):
    """Represents a selected ion element within a precursor.

    Provides access to the selected ion m/z, peak intensity, charge state,
    ion mobility values, FAIMS voltages, and collisional cross section.
    """

    @property
    def selected_ion_mz(self) -> float | None:
        """Get selected ion m/z for this precursor."""
        return self.cv_float(SelectedIonAccession.SELECTED_ION_MZ)

    @property
    def peak_intensity(self) -> float | None:
        """Get peak intensity for this precursor."""
        return self.cv_float(SelectedIonAccession.PEAK_INTENSITY)

    @property
    def charge_state(self) -> int | None:
        """Get charge state for this precursor."""
        return self.cv_int(SelectedIonAccession.CHARGE_STATE)

    @property
    def ir_im(self) -> float | None:
        """Get inversion reduced ion mobility for this precursor."""
        return self.cv_float(SelectedIonAccession.INVERSE_REDUCED_ION_MOBILITY)

    @property
    def im_drift_time(self) -> float | None:
        """Get ion mobility drift time for this precursor."""
        return self.cv_float(SelectedIonAccession.ION_MOBILITY_DRIFT_TIME)

    @property
    def faims_voltage_start(self) -> float | None:
        """Get FAIMS voltage start for this precursor."""
        return self.cv_float(SelectedIonAccession.FAIMS_VOLTAGE_START)

    @property
    def faims_voltage_end(self) -> float | None:
        """Get FAIMS voltage end for this precursor."""
        return self.cv_float(SelectedIonAccession.FAIMS_VOLTAGE_END)

    @property
    def ccs(self) -> float | None:
        """Get collisional cross section for this precursor."""
        return self.cv_float(SelectedIonAccession.COLLISIONAL_CROSS_SECTION)


@dataclass(frozen=True, repr=False)
class Activation(_ParamGroup):
    """Represents an activation element within a precursor.

    Provides access to the activation type, collision energy, supplemental collision energy,
    collision gas, and collision gas pressure.
    """

    @property
    def activation_type(self) -> CollisionDissociationTypeAccession | None:
        """Get activation type for this precursor."""
        for cd in CollisionDissociationTypeAccession:
            if cd in self.accessions:
                return cd
        return None

    @property
    def activation_energy(self) -> float | None:
        """Get activation energy for this precursor."""
        return self.cv_float(ActivationAccession.ACTIVATION_ENERGY)

    @property
    def ce(self) -> float | None:
        """Get collision energy for this precursor."""
        return self.cv_float(ActivationAccession.COLLISION_ENERGY)

    @property
    def supplemental_ce(self) -> float | None:
        """Get supplemental collision energy for this precursor."""
        return self.cv_float(ActivationAccession.SUPPLEMENTAL_COLLISION_ENERGY)

    @property
    def collision_gas(self) -> str | None:
        """Get collision gas for this precursor.

        ``collision gas`` (MS:1000419) is normally a valueless flag whose identity is carried by
        the term name, so this returns the parameter's value when one is present and otherwise the
        term name — instead of returning ``None`` for the (common) valueless case.
        """
        cv = self.get_cvparm(ActivationAccession.COLLISION_GAS)
        if cv is None:
            return None
        return cv.value if cv.value else cv.name

    @property
    def collision_gas_pressure(self) -> float | None:
        """Get collision gas pressure for this precursor."""
        return self.cv_float(ActivationAccession.COLLISION_GAS_PRESSURE)


@dataclass(frozen=True, repr=False)
class Precursor(_DataTreeWrapper):
    """Represents a precursor element in an mzML spectrum.

    Provides access to the isolation window, selected ions, activation parameters,
    and reference attributes such as spectrum ref and source file ref.
    """

    @property
    def isolation_window(self) -> IsolationWindow | None:
        iso_window = self.element.find(f"./{self.ns}{MzMLElement.ISOLATION_WINDOW}")
        if iso_window is not None:
            return IsolationWindow(iso_window)
        return None

    @property
    def selected_ions(self) -> list[SelectedIon]:
        sel_ion_list = self.element.find(f"./{self.ns}{MzMLElement.SELECTED_ION_LIST}")
        if sel_ion_list is not None:
            return [SelectedIon(elem) for elem in sel_ion_list.findall(f"./{self.ns}{MzMLElement.SELECTED_ION}")]
        return []

    @property
    def activation(self) -> Activation | None:
        activation_element = self.element.find(f"./{self.ns}{MzMLElement.ACTIVATION}")
        if activation_element is not None:
            return Activation(activation_element)

    @property
    def spectrum_ref(self) -> str | None:
        return self.get_attribute("spectrumRef")

    @property
    def source_file_ref(self) -> str | None:
        return self.get_attribute("sourceFileRef")

    @property
    def external_spectrum_id(self) -> str | None:
        return self.get_attribute("externalSpectrumID")

    def __repr__(self) -> str:
        s = "Precursor("
        if self.spectrum_ref is not None:
            s += f"spectrum_ref='{self.spectrum_ref}', "
        if self.source_file_ref is not None:
            s += f"source_file_ref='{self.source_file_ref}', "
        if self.external_spectrum_id is not None:
            s += f"external_spectrum_id='{self.external_spectrum_id}', "

        if self.isolation_window is not None:
            s += f"isolation_window={self.isolation_window}, "
        if self.selected_ions:
            s += f"selected_ions=[{', '.join(str(si) for si in self.selected_ions)}], "
        if self.activation is not None:
            s += f"activation={self.activation}, "

        s += ")"
        return s

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class _PrecursorListMixin(_DataTreeWrapperProtocol):
    """Mixin that exposes precursor access on classes wrapping an XML element with a `precursorList` child."""

    @property
    def has_precursors(self) -> bool:
        """Check if this spectrum has a precursor list."""
        return self.element.find(f"./{self.ns}{MzMLElement.PRECURSOR_LIST}") is not None

    @property
    def precursors(self) -> list[Precursor]:
        """Get a list of Precursor objects for the precursor list of this spectrum, or None ."""
        precursor_list_element = self.element.find(f"./{self.ns}{MzMLElement.PRECURSOR_LIST}")
        if precursor_list_element is not None:
            return [Precursor(elem) for elem in precursor_list_element.findall(f"./{self.ns}{MzMLElement.PRECURSOR}")]
        return []


@dataclass(frozen=True, repr=False)
class Product(_ParamGroup):
    """A product ion selection element containing an isolation window and CV parameters."""

    @property
    def isolation_window(self) -> IsolationWindow | None:
        """Get the isolation window for this product, if present."""
        iso_window = self.element.find(f"./{self.ns}{MzMLElement.ISOLATION_WINDOW}")
        if iso_window is not None:
            return IsolationWindow(iso_window)
        return None


@dataclass(frozen=True, repr=False)
class _ProductListMixin(_DataTreeWrapperProtocol):
    """Mixin that exposes product access on classes wrapping an XML element with a `productList` child."""

    @property
    def has_products(self) -> bool:
        """Check if this spectrum has a product list."""
        return self.element.find(f"./{self.ns}productList") is not None

    @property
    def products(self) -> list[Product]:
        """Get a list of Product objects for the product list of this spectrum, or None"""
        product_list_element = self.element.find(f"./{self.ns}{MzMLElement.PRODUCT_LIST}")
        if product_list_element is not None:
            return [Product(elem) for elem in product_list_element.findall(f"./{self.ns}{MzMLElement.PRODUCT}")]
        return []


@dataclass(frozen=True)
class Spectrum(_ParamGroup, _BinaryDataArrayMixin, _ScanListMixin, _PrecursorListMixin, _ProductListMixin):
    """An mzML `spectrum` element.

    Exposes binary data arrays (`mz`, `intensity`, `charge`, ion mobility via `has_im`/`im_types`),
    scan metadata (`scan_start_time`, `ion_injection_time`, `lower_mz`, `upper_mz`, `spectrum_type`,
    `polarity`, `ms_level`, `TIC`), and structured precursor/product lists.
    """

    @property
    def id(self) -> str:
        """Get spectrum id."""
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Spectrum ID is missing")
        return id

    @property
    def id_dict(self) -> dict[str, int | str]:
        """Parse the native id into its ``key=value`` components (e.g. ``{"scan": 19}``).

        Vendor native ids are space-separated ``key=value`` tokens, e.g. Thermo
        ``"controllerType=0 controllerNumber=1 scan=19"`` or Bruker ``"frame=1016 scan=1"``.
        Integer components are returned as ints, so ``spectrum.id_dict["scan"]`` gives the scan
        number without manual parsing.
        """
        return _parse_native_id(self.id)

    @property
    def spot_id(self) -> str | None:
        """Get spectrum spot id, or None if not present."""
        return self.get_attribute("spotID")

    @property
    def index(self) -> int | None:
        """Get spectrum index, or None if not present."""
        index_str = self.get_attribute("index")
        if index_str is not None:
            try:
                return int(index_str)
            except ValueError:
                warnings.warn(f"Invalid index value: {index_str}. Returning None.", UserWarning, stacklevel=2)
        return None

    @property
    def default_array_length(self) -> int | None:
        """Get spectrum default array length, or None if not present."""
        default_array_length_str = self.get_attribute("defaultArrayLength")
        if default_array_length_str is not None:
            try:
                return int(default_array_length_str)
            except ValueError:
                warnings.warn(
                    f"Invalid default array length value: {default_array_length_str}. Returning None.",
                    UserWarning,
                    stacklevel=2,
                )
        return None

    @property
    def data_processing_ref(self) -> str | None:
        """Get spectrum data processing reference, or None if not present."""
        return self.get_attribute("dataProcessingRef")

    @property
    def source_file_ref(self) -> str | None:
        """Get spectrum source file reference, or None if not present."""
        return self.get_attribute("sourceFileRef")

    @property
    def mz(self) -> NDArray[np.float64] | None:
        """Get m/z array as a numpy array, or None if not present."""
        binary_array = self.get_binary_array(BinaryDataArrayAccession.MZ)
        if binary_array is not None:
            return binary_array._decode()
        return None

    @property
    def intensity(self) -> NDArray[np.float64] | None:
        """Get intensity array as a numpy array, or None if not present."""
        binary_array = self.get_binary_array(BinaryDataArrayAccession.INTENSITY)
        if binary_array is not None:
            return binary_array._decode()
        return None

    @property
    def charge(self) -> NDArray[np.float64] | None:
        """Return the per-point charge array, or None if no charge binary array is present."""
        binary_array = self.get_binary_array(BinaryDataArrayAccession.CHARGE)
        if binary_array is not None:
            return binary_array._decode()
        return None

    @property
    def has_im(self) -> bool:
        """Return True if this spectrum carries ion mobility data — either as a binary array
        (e.g. combined-IM frames) or as a scan-level cvParam (e.g. Bruker timsTOF PASEF MS2)."""
        for barray in self.binary_arrays:
            if barray.binary_array_type in ION_MOBILITIES:
                return True
        for scan in self.scans:
            if scan.inverse_reduced_ion_mobility is not None or scan.ion_mobility_drift_time is not None:
                return True
        return False

    @property
    def im_types(self) -> set[BinaryDataArrayAccession]:
        """Return the set of ion mobility array accessions present in this spectrum; empty set if none."""
        im_arrays = set()
        for barray in self.binary_arrays:
            if barray.binary_array_type in ION_MOBILITIES:
                im_arrays.add(barray.binary_array_type)
        return im_arrays

    @cached_property
    def spectrum_type(self) -> Literal["centroid", "profile"] | None:
        """Get spectrum type (centroid / profile / unknown)."""
        if SpectrumTypeAccessions.CENTROID in self.accessions:
            return "centroid"
        elif SpectrumTypeAccessions.PROFILE in self.accessions:
            return "profile"
        return None

    @cached_property
    def polarity(self) -> Literal["positive", "negative"] | None:
        """Get polarity (positive / negative / or unknown scan)."""

        if ScanPolarity.POSITIVE in self.accessions:
            return "positive"
        elif ScanPolarity.NEGATIVE in self.accessions:
            return "negative"
        return None

    @cached_property
    def TIC(self) -> float | None:
        """Get total ion current (TIC) for this spectrum."""

        return self.cv_float(SpectrumMSAccession.TOTAL_ION_CURRENT)

    @cached_property
    def ms_level(self) -> int | None:
        """Get MS level for this spectrum."""
        return self.cv_int(SpectrumMSAccession.MS_LEVEL)

    @property
    def base_peak_mz(self) -> float | None:
        """Base peak m/z for this spectrum (MS:1000504)."""
        return self.cv_float(SpectrumMSAccession.BASE_PEAK_MZ)

    @property
    def base_peak_intensity(self) -> float | None:
        """Base peak intensity for this spectrum (MS:1000505)."""
        return self.cv_float(SpectrumMSAccession.BASE_PEAK_INTENSITY)

    @property
    def lowest_observed_mz(self) -> float | None:
        """Lowest observed m/z for this spectrum (MS:1000528)."""
        return self.cv_float(SpectrumMSAccession.LOWEST_OBSERVED_MZ)

    @property
    def highest_observed_mz(self) -> float | None:
        """Highest observed m/z for this spectrum (MS:1000527)."""
        return self.cv_float(SpectrumMSAccession.HIGHEST_OBSERVED_MZ)


@dataclass(frozen=True)
class Chromatogram(_ParamGroup, _BinaryDataArrayMixin):
    """An mzML `chromatogram` element.

    Exposes `time` and `intensity` binary arrays, optional `precursor` and `product` structures,
    and a `chromatogram_type` property (e.g. `"tic"`, `"basepeak"`, `"srm"`).
    """

    @property
    def id(self) -> str:
        """Get chromatogram id."""
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Chromatogram ID is missing")
        return id

    @property
    def id_dict(self) -> dict[str, int | str]:
        """Parse the native id into its ``key=value`` components (integer values coerced to int)."""
        return _parse_native_id(self.id)

    @property
    def default_array_length(self) -> int | None:
        """Get chromatogram default array length, or None if not present."""
        r = self.get_attribute("defaultArrayLength")
        if r is not None:
            try:
                return int(r)
            except ValueError:
                warnings.warn(
                    f"Invalid default array length value: {r}. Returning None.",
                    UserWarning,
                    stacklevel=2,
                )
        return None

    @property
    def source_file_ref(self) -> str | None:
        """Get chromatogram source file reference, or None if not present."""
        return self.get_attribute("sourceFileRef")

    @property
    def time(self) -> NDArray[np.float64] | None:
        """Get time array as a numpy array, or None if not present."""
        binary_array = self.get_binary_array(BinaryDataArrayAccession.TIME)
        if binary_array is not None:
            return binary_array._decode()
        return None

    @property
    def intensity(self) -> NDArray[np.float64] | None:
        """Get intensity array as a numpy array, or None if not present."""
        binary_array = self.get_binary_array(BinaryDataArrayAccession.INTENSITY)
        if binary_array is not None:
            return binary_array._decode()
        return None

    @property
    def has_precursor(self) -> bool:
        """Check if this chromatogram has a precursor."""
        return self.element.find(f"./{self.ns}precursor") is not None

    @property
    def precursor(self) -> Precursor | None:
        """Get a Precursor object for the precursor of this chromatogram, or None if no precursor is present."""
        precursor_element = self.element.find(f"./{self.ns}{MzMLElement.PRECURSOR}")
        if precursor_element is not None:
            return Precursor(precursor_element)
        return None

    @property
    def has_product(self) -> bool:
        """Check if this chromatogram has a product."""
        return self.element.find(f"./{self.ns}product") is not None

    @property
    def product(self) -> Product | None:
        """Get a Product object for the product of this chromatogram, or None if no product is present."""
        product_element = self.element.find(f"./{self.ns}{MzMLElement.PRODUCT}")
        if product_element is not None:
            return Product(product_element)
        return None

    @property
    def data_processing_ref(self) -> str | None:
        """Get chromatogram data processing reference, or None if not present."""
        return self.get_attribute("dataProcessingRef")

    @property
    def chromatogram_type(
        self,
    ) -> Literal["emission", "sim", "basepeak", "pic", "tic", "absorption", "srm", "sic"] | None:
        """Get chromatogram type (e.g. TIC, BPC, etc.) for this chromatogram."""
        for acc in ChromatogramTypeAccession:
            if acc in self.accessions:
                match acc:
                    case ChromatogramTypeAccession.EMMISION:
                        return "emission"
                    case ChromatogramTypeAccession.SELECTED_ION_MONITORING:
                        return "sim"
                    case ChromatogramTypeAccession.BASEPEAK:
                        return "basepeak"
                    case ChromatogramTypeAccession.PRECURSOR_ION_CURRENT:
                        return "pic"
                    case ChromatogramTypeAccession.TOTAL_ION_CURRENT:
                        return "tic"
                    case ChromatogramTypeAccession.ABSORPTION:
                        return "absorption"
                    case ChromatogramTypeAccession.SELECTED_REACTION_MONITORING:
                        return "srm"
                    case ChromatogramTypeAccession.SELECTED_ION_CURRENT:
                        return "sic"
        return None
