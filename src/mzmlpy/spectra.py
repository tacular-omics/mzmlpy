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
from functools import cached_property
from typing import Literal

import numpy as np

from .constants import (
    _BINARY_DECODE_DTYPES,
    ION_MOBILITIES,
    ActivationAccession,
    BinaryDataArrayAccession,
    BinaryDataTypeAccession,
    ChromatogramTypeAccession,
    CollisionDissociationTypeAccession,
    CompressionTypeAccession,
    IsolationWindowAccession,
    MzMLElement,
    Polarity,
    ScanPolarity,
    SelectedIonAccession,
    SpectrumCombinationAccession,
    SpectrumMSAccession,
    SpectrumTypeAccession,
    TimeUnitAccession,
)
from .decoder import MSDecoder
from .elems.dtree_wrapper import _DataTreeWrapper, _DataTreeWrapperProtocol, _ParamGroup
from .elems.params import CvParam
from .errors import MzmlDecodeError, MzmlError


def _decode_to_native(data: bytes, data_type: str) -> np.ndarray:
    dtype = _resolve_dtype(data_type)
    if len(data) % dtype.itemsize != 0:
        raise MzmlDecodeError(
            f"Cannot decode binary array: {len(data)} bytes is not a multiple of the "
            f"{dtype.itemsize}-byte element size for data type {data_type!r}. The data may be "
            f"corrupt, truncated, or use a truncation encoding that mzmlpy does not support."
        )
    return np.frombuffer(data, dtype=dtype)


def _decode_to_numpy(data: bytes, data_type: str) -> np.ndarray:
    """Decode a writable array in its declared numeric type."""
    return _decode_to_native(data, data_type).copy()


def _resolve_dtype(data_type: str) -> np.dtype:
    """Resolve a binary data type accession to a NumPy dtype."""
    try:
        accession = BinaryDataTypeAccession(data_type)
    except ValueError:
        accession = None
    dtype_str = _BINARY_DECODE_DTYPES.get(accession) if accession is not None else None
    if dtype_str is None:
        raise MzmlDecodeError(
            f"Unsupported or unknown binary data type accession {data_type!r}; mzmlpy can decode "
            f"32-/64-bit float and 32-/64-bit integer arrays."
        )
    return np.dtype(dtype_str)


_C = CompressionTypeAccession

# Generic codec term -> combined terms that already include that codec.
_COMBINED_WITH_GENERIC: dict[CompressionTypeAccession, frozenset[CompressionTypeAccession]] = {
    _C.ZLIB_COMPRESSION: frozenset(
        {
            _C.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB,
            _C.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB,
            _C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB,
            _C.TRUNCATION_ZLIB,
            _C.TRUNCATION_DELTA_PREDICTION_ZLIB,
            _C.TRUNCATION_LINEAR_PREDICTION_ZLIB,
        }
    ),
    _C.ZSTD_COMPRESSION: frozenset(
        {
            _C.MS_NUMPRESS_LINEAR_PREDICTION_ZSTD,
            _C.MS_NUMPRESS_POSITIVE_INTEGER_ZSTD,
            _C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZSTD,
            _C.BYTE_SHUFFLED_ZSTD,
            _C.DICTIONARY_ENCODED_ZSTD,
        }
    ),
}

# (bare numpress term, generic codec term) -> the combined "numpress followed by codec" term.
_NUMPRESS_COMBINATIONS: dict[tuple[CompressionTypeAccession, CompressionTypeAccession], CompressionTypeAccession] = {
    (_C.MS_NUMPRESS_LINEAR_PREDICTION, _C.ZLIB_COMPRESSION): _C.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB,
    (_C.MS_NUMPRESS_POSITIVE_INTEGER, _C.ZLIB_COMPRESSION): _C.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB,
    (_C.MS_NUMPRESS_SHORT_LOGGED_FLOAT, _C.ZLIB_COMPRESSION): _C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB,
    (_C.MS_NUMPRESS_LINEAR_PREDICTION, _C.ZSTD_COMPRESSION): _C.MS_NUMPRESS_LINEAR_PREDICTION_ZSTD,
    (_C.MS_NUMPRESS_POSITIVE_INTEGER, _C.ZSTD_COMPRESSION): _C.MS_NUMPRESS_POSITIVE_INTEGER_ZSTD,
    (_C.MS_NUMPRESS_SHORT_LOGGED_FLOAT, _C.ZSTD_COMPRESSION): _C.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZSTD,
}


# Accession string -> enum member, so hot paths use one dict lookup instead of an enum call in a try.
_COMPRESSION_BY_ACCESSION: dict[str, CompressionTypeAccession] = {term.value: term for term in CompressionTypeAccession}
_DATA_TYPE_BY_ACCESSION: dict[str, BinaryDataTypeAccession] = {term.value: term for term in BinaryDataTypeAccession}
_ARRAY_TYPE_BY_ACCESSION: dict[str, BinaryDataArrayAccession] = {term.value: term for term in BinaryDataArrayAccession}


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
    def compression(self) -> CompressionTypeAccession | None:
        """Return the compression accession for this array, or None if no compression CV term is present.

        cvParam order has no meaning in mzML, so when several compression terms are present they are
        resolved independently of order: a combined term wins over the generic codec it already
        includes, a bare MS-Numpress term plus the generic zlib or zstd term (the form written before
        the combined "followed by zlib" terms existed) resolves to the combined term, and "no
        compression" never masks a real codec. Any other conflict warns and returns the first term.
        """
        found: list[CompressionTypeAccession] = []
        for param in self.cv_params:
            term = _COMPRESSION_BY_ACCESSION.get(param.accession)
            if term is not None and term not in found:
                found.append(term)
        if len(found) <= 1:
            return found[0] if found else None

        terms = [t for t in found if t != CompressionTypeAccession.NO_COMPRESSION]
        # Drop a generic codec term that a combined term in the same array already includes.
        for generic, combined_terms in _COMBINED_WITH_GENERIC.items():
            if generic in terms and any(t in combined_terms for t in terms):
                terms.remove(generic)
        # Legacy two-term form: bare numpress + generic zlib/zstd -> the combined term.
        for (numpress, generic), combined in _NUMPRESS_COMBINATIONS.items():
            if numpress in terms and generic in terms:
                terms = [combined if t == numpress else t for t in terms if t != generic]
        if len(terms) > 1:
            warnings.warn(
                f"binaryDataArray has conflicting compression terms {[str(t) for t in terms]}; using {terms[0]}.",
                UserWarning,
                stacklevel=2,
            )
        return terms[0]

    @cached_property
    def encoding(self) -> BinaryDataTypeAccession | None:
        """Return the binary data type accession (e.g. 32-bit or 64-bit float/int), or None if absent."""
        # Enum declaration order decides between conflicting terms, as before.
        found = {term for param in self.cv_params if (term := _DATA_TYPE_BY_ACCESSION.get(param.accession))}
        return next((term for term in BinaryDataTypeAccession if term in found), None) if found else None

    @cached_property
    def binary_array_type(self) -> BinaryDataArrayAccession | None:
        """Return the semantic array type accession (e.g. m/z, intensity, ion mobility), or None if absent."""
        found = {term for param in self.cv_params if (term := _ARRAY_TYPE_BY_ACCESSION.get(param.accession))}
        return next((term for term in BinaryDataArrayAccession if term in found), None) if found else None

    def _decode(self) -> np.ndarray:

        # Get compression and encoding from cached properties
        compression_type = self.compression
        binary_data_type = self.encoding

        if compression_type is None:
            compression_type = CompressionTypeAccession.NO_COMPRESSION
            warnings.warn(f"Compression type not specified. Assuming {compression_type}.", UserWarning, stacklevel=2)

        if binary_data_type is None:
            binary_data_type = BinaryDataTypeAccession.FLOAT_64
            warnings.warn(f"Binary data type not specified. Assuming {binary_data_type}.", UserWarning, stacklevel=2)
        # Numpress reconstructs float64 values rather than storing a raw typed array.
        result_dtype = (
            np.dtype("<f8") if compression_type.name.startswith("MS_NUMPRESS") else _resolve_dtype(binary_data_type)
        )
        # Get binary data from element
        binary_element = self.element.find(f"./{self.ns}binary")
        if binary_element is None or binary_element.text is None:
            return np.array([], dtype=result_dtype)

        # Decode base64
        try:
            out_data = base64.b64decode("".join(binary_element.text.split()), validate=True)
        except ValueError as e:  # binascii.Error subclasses ValueError
            raise MzmlDecodeError(
                f"Failed to base64-decode binary data array (data type {binary_data_type}): {e}"
            ) from e

        if len(out_data) == 0:
            return np.array([], dtype=result_dtype)

        # Decompress based on compression type
        match compression_type:
            case CompressionTypeAccession.BYTE_SHUFFLED_ZSTD:
                unshuffled = MSDecoder.decode_byte_shuffled_zstd(out_data, _resolve_dtype(binary_data_type).itemsize)
                return _decode_to_numpy(unshuffled, binary_data_type)
            case CompressionTypeAccession.MS_NUMPRESS_SHORT_LOGGED_FLOAT:
                return MSDecoder.decode_slof(out_data)
            case CompressionTypeAccession.TRUNCATION_LINEAR_PREDICTION_ZLIB:
                # Reverse the linear predictor in the stored precision.
                native = _decode_to_native(MSDecoder.decode_zlib(out_data), binary_data_type)
                return MSDecoder.reverse_linear_prediction(native)
            case CompressionTypeAccession.ZLIB_COMPRESSION:
                return _decode_to_numpy(MSDecoder.decode_zlib(out_data), binary_data_type)
            case CompressionTypeAccession.NO_COMPRESSION:
                return _decode_to_numpy(out_data, binary_data_type)
            case CompressionTypeAccession.DICTIONARY_ENCODED_ZSTD:
                return MSDecoder.decode_dict_encoded_zstd(out_data, _resolve_dtype(binary_data_type))
            case CompressionTypeAccession.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB:
                return MSDecoder.decode_linear(MSDecoder.decode_zlib(out_data))
            case CompressionTypeAccession.TRUNCATION_ZLIB:
                return _decode_to_numpy(MSDecoder.decode_zlib(out_data), binary_data_type)
            case CompressionTypeAccession.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB:
                return MSDecoder.decode_slof(MSDecoder.decode_zlib(out_data))
            case CompressionTypeAccession.MS_NUMPRESS_LINEAR_PREDICTION_ZSTD:
                return MSDecoder.decode_linear(MSDecoder.decode_ztsd(out_data))
            case CompressionTypeAccession.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB:
                return MSDecoder.decode_pic(MSDecoder.decode_zlib(out_data))
            case CompressionTypeAccession.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZSTD:
                return MSDecoder.decode_slof(MSDecoder.decode_ztsd(out_data))
            case CompressionTypeAccession.MS_NUMPRESS_LINEAR_PREDICTION:
                return MSDecoder.decode_linear(out_data)
            case CompressionTypeAccession.MS_NUMPRESS_POSITIVE_INTEGER:
                return MSDecoder.decode_pic(out_data)
            case CompressionTypeAccession.TRUNCATION_DELTA_PREDICTION_ZLIB:
                # Reverse the delta predictor in the stored precision.
                native = _decode_to_native(MSDecoder.decode_zlib(out_data), binary_data_type)
                return MSDecoder.reverse_delta_prediction(native)
            case CompressionTypeAccession.ZSTD_COMPRESSION:
                return _decode_to_numpy(MSDecoder.decode_ztsd(out_data), binary_data_type)
            case CompressionTypeAccession.MS_NUMPRESS_POSITIVE_INTEGER_ZSTD:
                return MSDecoder.decode_pic(MSDecoder.decode_ztsd(out_data))
            case _:
                try:
                    return _decode_to_numpy(out_data, binary_data_type)
                except Exception as e:
                    raise MzmlDecodeError(f"Unsupported compression type: {compression_type}") from e

    @property
    def data(self) -> np.ndarray:
        """Decode and return the binary data as a NumPy array.

        Raw numeric encodings retain their declared dtype, including empty arrays.
        Numpress returns reconstructed float64 values. Arrays are writable.
        Decoding runs on every access. Store the result locally when using it repeatedly.
        """
        return self._decode()


_SECONDS_PER_UNIT: dict[str, float] = {
    TimeUnitAccession.MILLISECOND: 0.001,
    TimeUnitAccession.SECOND: 1.0,
    TimeUnitAccession.MINUTE: 60.0,
    TimeUnitAccession.HOUR: 3600.0,
    "millisecond": 0.001,
    "second": 1.0,
    "minute": 60.0,
    "hour": 3600.0,
}
_warned_time_units: set[tuple[str, str | None]] = set()


def _unit_factor(cv: CvParam, quantity: str, unit: Literal["second", "millisecond"], stacklevel: int = 4) -> float:
    """Return the factor converting ``cv``'s time unit to ``unit``.

    A missing or non-time unit is taken to be ``unit`` and warns once per (quantity, unit) pair.
    """
    factor = _SECONDS_PER_UNIT.get(cv.unit_accession or "") or _SECONDS_PER_UNIT.get((cv.unit_name or "").lower())
    if factor is None:
        recorded = " ".join(part for part in (cv.unit_accession, cv.unit_name) if part) or None
        key = (quantity, recorded)
        if key not in _warned_time_units:
            _warned_time_units.add(key)
            what = "has no unit" if recorded is None else f"has non-time unit {recorded!r}"
            warnings.warn(
                f"The {quantity} ({cv.accession}) {what}; assuming {unit}s.", UserWarning, stacklevel=stacklevel
            )
        return 1.0
    return factor / _SECONDS_PER_UNIT[unit]


def _time(group: _ParamGroup, accession: str, quantity: str, unit: Literal["second", "millisecond"]) -> float | None:
    """Read a time-valued cvParam and return it in ``unit`` (see :func:`_unit_factor`)."""
    cv = group.get_cv_param(accession)
    value = group.cv_float(accession)
    if cv is None or value is None:
        return None
    factor = _unit_factor(cv, quantity, unit)
    return value if factor == 1.0 else value * factor


@dataclass(frozen=True)
class _BinaryDataArrayList(_ParamGroup):
    """Internal wrapper for a `binaryDataArrayList` XML element.

    Provides iteration and lookup over the child `BinaryDataArray` objects.
    """

    @property
    def binary_arrays(self) -> tuple[BinaryDataArray, ...]:
        """The binary data arrays, in document order."""
        return tuple(
            BinaryDataArray(elem) for elem in self.element.findall(f"./{self.ns}{MzMLElement.BINARY_DATA_ARRAY}")
        )

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
        binary_array_list_element = self.element.find(f"./{self.ns}{MzMLElement.BINARY_DATA_ARRAY_LIST}")
        if binary_array_list_element is not None:
            return _BinaryDataArrayList(binary_array_list_element)
        return None

    @cached_property
    def binary_arrays(self) -> tuple[BinaryDataArray, ...]:
        """The binary data arrays, in document order."""
        if (array_list := self._binary_array_list) is not None:
            return array_list.binary_arrays
        return ()

    @cached_property
    def _binary_array_map(self) -> dict[str, BinaryDataArray]:
        """Accession or name -> the first array carrying it, built once per record."""
        mapping: dict[str, BinaryDataArray] = {}
        for binary_array in self.binary_arrays:
            for param in binary_array.cv_params:
                mapping.setdefault(param.accession, binary_array)
                mapping.setdefault(param.name, binary_array)
        return mapping

    def get_binary_array(self, id: str) -> BinaryDataArray | None:
        """Get a BinaryDataConverter object for the binary data array with the specified id."""
        return self._binary_array_map.get(id)

    def has_binary_array(self, id: str) -> bool:
        """Check if a binary data array with the specified id exists."""
        return id in self._binary_array_map


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

    @property
    def mz_range(self) -> tuple[float, float] | None:
        """``(lower_mz, upper_mz)`` of this scan window, or None if either limit is missing."""
        lower, upper = self.lower_mz, self.upper_mz
        if lower is None or upper is None:
            return None
        return (lower, upper)


@dataclass(frozen=True)
class _ScanWindowList(_ParamGroup):
    """A list of scan windows for a single scan event."""

    @property
    def scan_windows(self) -> tuple[ScanWindow, ...]:
        """Get a list of ScanWindow objects for each scan window in the scan window list."""
        return tuple(ScanWindow(elem) for elem in self.element.findall(f"./{self.ns}{MzMLElement.SCAN_WINDOW}"))

    @property
    def has_scan_windows(self) -> bool:
        """Check if this scan has a scan window list."""
        return self.element.find(f"./{self.ns}{MzMLElement.SCAN_WINDOW}") is not None


@dataclass(frozen=True)
class Scan(_ParamGroup):
    """A single scan event with timing, window, and CV parameter metadata."""

    @property
    def _has_scan_windows_list(self) -> bool:
        """Check if this scan has a scan window list."""
        return self.element.find(f"./{self.ns}{MzMLElement.SCAN_WINDOW_LIST}") is not None

    @property
    def _scan_window_list(self) -> _ScanWindowList | None:
        """Get a ScanWindowList object for the scan window list of this scan, or None."""
        scan_window_list_element = self.element.find(f"./{self.ns}{MzMLElement.SCAN_WINDOW_LIST}")
        if scan_window_list_element is not None:
            return _ScanWindowList(scan_window_list_element)
        return None

    @property
    def scan_windows(self) -> tuple[ScanWindow, ...]:
        """Get a list of ScanWindow objects for the scan window list of this scan."""
        return (
            self._scan_window_list.scan_windows
            if self._has_scan_windows_list and self._scan_window_list is not None
            else ()
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
    def mz_range(self) -> tuple[float, float] | None:
        """m/z range acquired by this scan: ``(lowest lower limit, highest upper limit)`` over its
        scan windows, or None if no window has both limits.

        A scan with several windows returns the envelope of all complete windows; use
        :attr:`scan_windows` for the individual windows.
        """
        ranges = [r for w in self.scan_windows if (r := w.mz_range) is not None]
        if not ranges:
            return None
        return (min(r[0] for r in ranges), max(r[1] for r in ranges))

    @property
    def rt(self) -> float | None:
        """Retention time (scan start time, MS:1000016) of this scan in seconds, or None if absent.

        Values recorded in milliseconds, minutes or hours are converted to seconds. A value with no
        unit, or a unit that is not a time unit, is taken as seconds and warns once per unit. A
        non-numeric value raises :class:`MzmlError`.
        """
        return _time(self, SpectrumMSAccession.SCAN_START_TIME, "retention time", "second")

    @property
    def ion_injection_time(self) -> float | None:
        """Ion injection time (MS:1000927) of this scan in milliseconds, or None if absent.

        Milliseconds is the unit instruments and search engines report. Values recorded in other
        time units are converted. A value with no unit, or a unit that is not a time unit, is taken
        as milliseconds and warns once per unit. A non-numeric value raises :class:`MzmlError`.
        """
        return _time(self, SpectrumMSAccession.ION_INJECTION_TIME, "ion injection time", "millisecond")

    @property
    def ook0(self) -> float | None:
        """Inverse reduced ion mobility 1/K0 (Vs/cm², MS:1002815) of this scan, e.g. Bruker timsTOF, or None."""
        return self.cv_float(SpectrumMSAccession.INVERSE_REDUCED_ION_MOBILITY)

    @property
    def drift_time(self) -> float | None:
        """Ion mobility drift time (MS:1002476) of this scan, or None."""
        return self.cv_float(SpectrumMSAccession.ION_MOBILITY_DRIFT_TIME)

    @property
    def filter_string(self) -> str | None:
        """Instrument filter string for this scan (MS:1000512), e.g. a Thermo scan filter."""
        cv = self.get_cv_param(SpectrumMSAccession.FILTER_STRING)
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
    def scans(self) -> tuple[Scan, ...]:
        """Get a list of Scan objects for each scan in the scan list."""
        return tuple(Scan(elem) for elem in self.element.findall(f"./{self.ns}{MzMLElement.SCAN}"))

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

    Delegates to the first scan for single-valued properties such as `rt`,
    `ion_injection_time` and `mz_range`, emitting a warning when multiple scans are present.
    """

    @property
    def _has_scan_list(self) -> bool:
        """Check if this spectrum has a scan list."""
        return self.element.find(f"./{self.ns}{MzMLElement.SCAN_LIST}") is not None

    @property
    def _scan_list(self) -> _ScanList | None:
        """Get a ScanList object for the scan list of this spectrum, or None if no scan list is present."""
        scan_list_element = self.element.find(f"./{self.ns}{MzMLElement.SCAN_LIST}")
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

    @cached_property
    def scans(self) -> tuple[Scan, ...]:
        """The Scan objects of this spectrum's scan list, or an empty tuple if it has none."""
        if (scan_list := self._scan_list) is not None:
            return scan_list.scans
        return ()

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
    def mz_range(self) -> tuple[float, float] | None:
        """m/z range acquired for this spectrum (see :attr:`Scan.mz_range`), from its first scan."""
        scan = self._first_scan("m/z range")
        return scan.mz_range if scan is not None else None

    @property
    def rt(self) -> float | None:
        """Retention time (scan start time) of this spectrum in seconds, from its first scan."""
        scan = self._first_scan("retention time")
        return scan.rt if scan is not None else None

    @property
    def ion_injection_time(self) -> float | None:
        """Ion injection time in milliseconds (see :attr:`Scan.ion_injection_time`), from the first scan."""
        scan = self._first_scan("ion injection time")
        return scan.ion_injection_time if scan is not None else None

    @property
    def ook0(self) -> float | None:
        """Inverse reduced ion mobility 1/K0 (Vs/cm²) from this spectrum's first scan, or None.

        This never falls back to drift time. Use ``spectrum.scans[0].drift_time`` for drift-tube data.
        """
        scan = self._first_scan("1/K0")
        return scan.ook0 if scan is not None else None

    @property
    def filter_string(self) -> str | None:
        """Scan filter string for this spectrum (from its single scan), if present."""
        scan = self._first_scan("filter string")
        return scan.filter_string if scan is not None else None


@dataclass(frozen=True, repr=False)
class IsolationWindow(_ParamGroup):
    """Represents an isolation window element from a precursor or product.

    Provides the isolation target m/z, the lower and upper offsets, the window width and the
    isolated m/z range. The names match tdfpy's ``DiaWindow`` and ``Precursor``.
    """

    @property
    def isolation_mz(self) -> float | None:
        """Isolation window target m/z (MS:1000827), or None."""
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
    def isolation_width(self) -> float | None:
        """Full window width, ``lower_offset + upper_offset``, or None if either offset is missing."""
        lower, upper = self.lower_offset, self.upper_offset
        if lower is None or upper is None:
            return None
        return lower + upper

    @property
    def isolation_mz_range(self) -> tuple[float, float] | None:
        """``(isolation_mz - lower_offset, isolation_mz + upper_offset)``, or None if any of the three is missing."""
        target, lower, upper = self.isolation_mz, self.lower_offset, self.upper_offset
        if target is None or lower is None or upper is None:
            return None
        return (target - lower, target + upper)

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

    Provides access to the selected ion m/z, peak intensity, charge, ion mobility values,
    FAIMS voltages, and collisional cross section.
    """

    @property
    def mz(self) -> float | None:
        """Selected ion m/z (MS:1000744), or None."""
        return self.cv_float(SelectedIonAccession.SELECTED_ION_MZ)

    @property
    def intensity(self) -> float | None:
        """Peak intensity of the selected ion (MS:1000042), or None."""
        return self.cv_float(SelectedIonAccession.PEAK_INTENSITY)

    @property
    def charge(self) -> int | None:
        """Charge state of the selected ion (MS:1000041), or None."""
        return self.cv_int(SelectedIonAccession.CHARGE_STATE)

    @property
    def ook0(self) -> float | None:
        """Inverse reduced ion mobility 1/K0 (Vs/cm², MS:1002815) of the selected ion, or None."""
        return self.cv_float(SelectedIonAccession.INVERSE_REDUCED_ION_MOBILITY)

    @property
    def drift_time(self) -> float | None:
        """Ion mobility drift time of the selected ion, or None."""
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
    def collision_energy(self) -> float | None:
        """Collision energy (MS:1000045) as recorded, or None.

        The term's unit is electronvolt, but some writers (notably Thermo converters) record the
        normalized collision energy (NCE, percent) under this term, so the number is returned as
        written without conversion. :attr:`activation_energy` (MS:1000509) is a separate term.
        """
        return self.cv_float(ActivationAccession.COLLISION_ENERGY)

    @property
    def supplemental_collision_energy(self) -> float | None:
        """Supplemental collision energy (MS:1002680) as recorded, or None (e.g. EThcD supplemental activation)."""
        return self.cv_float(ActivationAccession.SUPPLEMENTAL_COLLISION_ENERGY)

    @property
    def collision_gas(self) -> str | None:
        """Get collision gas for this precursor.

        ``collision gas`` (MS:1000419) is normally a valueless flag whose identity is carried by
        the term name, so this returns the parameter's value when one is present and otherwise the
        term name — instead of returning ``None`` for the (common) valueless case.
        """
        cv = self.get_cv_param(ActivationAccession.COLLISION_GAS)
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
    def selected_ions(self) -> tuple[SelectedIon, ...]:
        sel_ion_list = self.element.find(f"./{self.ns}{MzMLElement.SELECTED_ION_LIST}")
        if sel_ion_list is not None:
            return tuple(SelectedIon(elem) for elem in sel_ion_list.findall(f"./{self.ns}{MzMLElement.SELECTED_ION}"))
        return ()

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

    @cached_property
    def precursors(self) -> tuple[Precursor, ...]:
        """Get a list of Precursor objects for the precursor list of this spectrum, or None ."""
        precursor_list_element = self.element.find(f"./{self.ns}{MzMLElement.PRECURSOR_LIST}")
        if precursor_list_element is not None:
            return tuple(
                Precursor(elem) for elem in precursor_list_element.findall(f"./{self.ns}{MzMLElement.PRECURSOR}")
            )
        return ()

    def _first_precursor(self) -> Precursor | None:
        precursors = self.precursors
        return precursors[0] if precursors else None

    def _first_selected_ion(self) -> "SelectedIon | None":
        precursor = self._first_precursor()
        if precursor is None:
            return None
        ions = precursor.selected_ions
        return ions[0] if ions else None

    @property
    def precursor_mz(self) -> float | None:
        """m/z of the first selected ion of the first precursor, or None.

        Matches tdfpy's ``Precursor.precursor_mz``. For DIA spectra, which usually report only an
        isolation window, use :attr:`isolation_mz_range`.
        """
        ion = self._first_selected_ion()
        return ion.mz if ion is not None else None

    @property
    def precursor_charge(self) -> int | None:
        """Charge state of the first selected ion of the first precursor, or None.

        Named ``precursor_charge`` (not ``charge``) so 0.9 code that read ``Spectrum.charge`` as the
        per-point array fails loudly; that array is now :attr:`charge_array`.
        """
        ion = self._first_selected_ion()
        return ion.charge if ion is not None else None

    @property
    def collision_energy(self) -> float | None:
        """Collision energy of the first precursor's activation, as recorded (see
        :attr:`Activation.collision_energy`), or None."""
        precursor = self._first_precursor()
        activation = precursor.activation if precursor is not None else None
        return activation.collision_energy if activation is not None else None

    @property
    def isolation_mz_range(self) -> tuple[float, float] | None:
        """Isolated m/z range of the first precursor's isolation window (see
        :attr:`IsolationWindow.isolation_mz_range`), or None."""
        precursor = self._first_precursor()
        window = precursor.isolation_window if precursor is not None else None
        return window.isolation_mz_range if window is not None else None


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
    def products(self) -> tuple[Product, ...]:
        """Get a list of Product objects for the product list of this spectrum, or None"""
        product_list_element = self.element.find(f"./{self.ns}{MzMLElement.PRODUCT_LIST}")
        if product_list_element is not None:
            return tuple(Product(elem) for elem in product_list_element.findall(f"./{self.ns}{MzMLElement.PRODUCT}"))
        return ()


@dataclass(frozen=True)
class Spectrum(_ParamGroup, _BinaryDataArrayMixin, _ScanListMixin, _PrecursorListMixin, _ProductListMixin):
    """An mzML `spectrum` element.

    Exposes binary data arrays (`mz`, `intensity`, `charge_array`, ion mobility via `has_im`/`im_types`),
    scan metadata (`rt`, `ion_injection_time`, `mz_range`, `ook0`, `spectrum_type`, `polarity`,
    `ms_level`, `total_ion_current`), and structured precursor/product lists.
    """

    @property
    def id(self) -> str:
        """Get spectrum id."""
        id = self.get_attribute("id")
        if id is None:
            raise MzmlError("Spectrum ID is missing")
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
    def mz(self) -> np.ndarray | None:
        """Get m/z array as a numpy array, or None if not present."""
        binary_array = self.get_binary_array(BinaryDataArrayAccession.MZ)
        if binary_array is not None:
            return binary_array._decode()
        return None

    @property
    def intensity(self) -> np.ndarray | None:
        """Get intensity array as a numpy array, or None if not present."""
        binary_array = self.get_binary_array(BinaryDataArrayAccession.INTENSITY)
        if binary_array is not None:
            return binary_array._decode()
        return None

    @property
    def charge_array(self) -> np.ndarray | None:
        """Return the per-point charge array (MS:1000516), or None if no charge binary array is present.

        Named ``charge_array`` because ``charge`` means a single precursor charge state elsewhere
        (:attr:`SelectedIon.charge`, :attr:`precursor_charge`).
        """
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
            if scan.ook0 is not None or scan.drift_time is not None:
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
        if SpectrumTypeAccession.CENTROID in self.accessions:
            return "centroid"
        elif SpectrumTypeAccession.PROFILE in self.accessions:
            return "profile"
        return None

    @cached_property
    def polarity(self) -> Polarity | None:
        """Get polarity (positive / negative / or unknown scan)."""

        if ScanPolarity.POSITIVE in self.accessions:
            return "positive"
        elif ScanPolarity.NEGATIVE in self.accessions:
            return "negative"
        return None

    @cached_property
    def total_ion_current(self) -> float | None:
        """Total ion current of this spectrum (MS:1000285), or None if absent."""
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

    Exposes `rt` (seconds) and `intensity` binary arrays, optional `precursor` and `product` structures,
    and a `chromatogram_type` property (e.g. `"tic"`, `"basepeak"`, `"srm"`).
    """

    @property
    def id(self) -> str:
        """Get chromatogram id."""
        id = self.get_attribute("id")
        if id is None:
            raise MzmlError("Chromatogram ID is missing")
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
    def rt(self) -> np.ndarray | None:
        """Time array (MS:1000595) in seconds as a new float64 array, or None if not present.

        Values recorded in milliseconds, minutes or hours are converted to seconds. A time array
        with no unit, or a unit that is not a time unit, is taken as seconds and warns once per unit.
        """
        binary_array = self.get_binary_array(BinaryDataArrayAccession.TIME)
        if binary_array is None:
            return None
        values = binary_array._decode().astype(np.float64)
        cv = binary_array.get_cv_param(BinaryDataArrayAccession.TIME)
        factor = 1.0 if cv is None else _unit_factor(cv, "chromatogram time array", "second", stacklevel=3)
        if factor != 1.0:
            values *= factor
        return values

    @property
    def intensity(self) -> np.ndarray | None:
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
                    case ChromatogramTypeAccession.EMISSION:
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


__all__ = [
    "Activation",
    "BinaryDataArray",
    "Chromatogram",
    "IsolationWindow",
    "Precursor",
    "Product",
    "Scan",
    "ScanWindow",
    "SelectedIon",
    "Spectrum",
]
