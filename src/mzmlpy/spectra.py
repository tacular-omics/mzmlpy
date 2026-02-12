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
    BinaryDataArrayAccession,
    BinaryDataTypeAccession,
    ChromatogramTypeAccession,
    CollisionDissociationTypeAccession,
    CompressionTypeAccessions,
    MzMLElement,
    ScanPolarity,
    SpectrumCombinationAccession,
    SpectrumMSAccession,
    XMLElement,
)
from .constants import SpectrumType as SpectrumTypeAccessions
from .decoder import MSDecoder
from .elems.dtree_wrapper import _DataTreeWrapper, _DataTreeWrapperProtocol, _ParamGroup


def decode_to_numpy(data: bytes, data_type: str) -> NDArray[np.float64]:
    _data_type = BINARY_DECODE_DTYPES.get(BinaryDataTypeAccession(data_type), None)
    if _data_type is None:
        raise ValueError(f"Unsupported binary data type accession: {_data_type}")
    return np.frombuffer(data, dtype=_data_type).astype(np.float64)


@dataclass(frozen=True)
class BinaryDataArray(_ParamGroup):
    # class to handle a binary data array.
    # (element tree should point to a single binary data array element)

    @cached_property
    def compression(self) -> CompressionTypeAccessions | None:
        for param in self.cv_params:
            with contextlib.suppress(ValueError):
                return CompressionTypeAccessions(param.accession)
        return None

    @cached_property
    def encoding(self) -> BinaryDataTypeAccession | None:
        for bdaa in BinaryDataTypeAccession:
            if bdaa in self.accessions:
                return bdaa
        return None

    @cached_property
    def binary_array_type(self) -> BinaryDataArrayAccession | None:
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
            warnings.warn("Binary data array does not contain binary data.", UserWarning, stacklevel=2)
            return np.array([], dtype=np.float64)

        # Decode base64
        out_data = base64.b64decode(binary_element.text)

        if len(out_data) == 0:
            warnings.warn("Decoded binary data is empty.", UserWarning, stacklevel=2)
            return np.array([], dtype=np.float64)

        # Decompress based on compression type
        match compression_type:
            case CompressionTypeAccessions.BYTE_SHUFFLED_ZSTD:
                raise NotImplementedError("BYTE_SHUFFLED_ZSTD compression is not yet implemented.")
            case CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT:
                return MSDecoder.decode_slof(out_data)
            case CompressionTypeAccessions.TRUNCATION_LINEAR_PREDICTION_ZLIB:
                raise NotImplementedError("TRUNCATION_LINEAR_PREDICTION_ZLIB compression is not yet implemented.")
            case CompressionTypeAccessions.ZLIB_COMPRESSION:
                return decode_to_numpy(MSDecoder.decode_zlib(out_data), binary_data_type)
            case CompressionTypeAccessions.NO_COMPRESSION:
                return decode_to_numpy(out_data, binary_data_type)
            case CompressionTypeAccessions.DICTIONARY_ENCODED_ZSTD:
                raise NotImplementedError("DICTIONARY_ENCODED_ZSTD compression is not yet implemented.")
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
                raise NotImplementedError("TRUNCATION_DELTA_PREDICTION_ZLIB compression is not yet implemented.")
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
        """Get the decoded binary data array as a numpy array."""
        return self._decode()


@dataclass(frozen=True)
class _BinaryDataArrayList(_ParamGroup):
    # class to handle a list of binary data arrays (element tree should point to a binary data array list element)

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
    """
    A class representing a binary data array, with various attributes and metadata.
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
    """
    A class representing a scan window, with various attributes and metadata.
    """

    @property
    def lower_limit(self) -> float | None:
        """Get scan window lower limit for this spectrum."""
        cv = self.get_cvparm(SpectrumMSAccession.SCAN_WINDOW_LOWER_LIMIT)
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def upper_limit(self) -> float | None:
        """Get scan window upper limit for this spectrum."""
        cv = self.get_cvparm(SpectrumMSAccession.SCAN_WINDOW_UPPER_LIMIT)
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None


@dataclass(frozen=True)
class _ScanWindowList(_ParamGroup):
    """
    A class representing a scan window list, which may contain multiple scan windows.
    Should be hidden
    """

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
    """
    A class representing a scan, with various attributes and metadata.
    """

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
    def lower_scan_window_limit(self) -> float | None:
        """Get scan window lower limit for this scan, if it has a single scan window."""
        if self._scan_window_list is not None:
            if not self.is_single_windowed_scan:
                raise ValueError("This scan has multiple scan windows. Cannot determine a single lower limit.")
            return self.scan_windows[0].lower_limit
        return None

    @property
    def upper_scan_window_limit(self) -> float | None:
        """Get scan window upper limit for this scan, if it has a single scan window."""
        if self._scan_window_list is not None:
            if not self.is_single_windowed_scan:
                raise ValueError("This scan has multiple scan windows. Cannot determine a single upper limit.")
            return self.scan_windows[0].upper_limit
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


@dataclass(frozen=True)
class _ScanList(_ParamGroup):
    """
    A class representing a scan list, which may contain multiple scans.
    Should be hidden, from users
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

    @property
    def lower_scan_window_limit(self) -> float | None:
        """Get scan window lower limit for this spectrum, if it has a single scan with a single scan window."""
        if self._scan_list is not None:
            if not self.is_single_scan:
                raise ValueError("This spectrum has multiple scans. Returning lower limit of the first scan.")

            if self.scans is None or len(self.scans) == 0:
                raise RuntimeError("Scan list is present but contains no scans.")
            return self.scans[0].lower_scan_window_limit
        return None

    @property
    def upper_scan_window_limit(self) -> float | None:
        """Get scan window upper limit for this spectrum, if it has a single scan with a single scan window."""
        if self._scan_list is not None:
            if not self.is_single_scan:
                raise ValueError("This spectrum has multiple scans. Returning upper limit of the first scan.")

            if self.scans is None or len(self.scans) == 0:
                raise RuntimeError("Scan list is present but contains no scans.")

            return self.scans[0].upper_scan_window_limit
        return None


@dataclass(frozen=True, repr=False)
class IsolationWindow(_ParamGroup):
    @property
    def target_mz(self) -> float | None:
        """Get isolation window target m/z for this precursor."""
        cv = self.get_cvparm("MS:1000827")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def lower_offset(self) -> float | None:
        """Get isolation window lower offset for this precursor."""
        cv = self.get_cvparm("MS:1000828")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def upper_offset(self) -> float | None:
        """Get isolation window upper offset for this precursor."""
        cv = self.get_cvparm("MS:1000829")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None


@dataclass(frozen=True, repr=False)
class SelectedIon(_ParamGroup):
    @property
    def selected_ion_mz(self) -> float | None:
        """Get selected ion m/z for this precursor."""
        cv = self.get_cvparm("MS:1000744")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def peak_intensity(self) -> float | None:
        """Get peak intensity for this precursor."""
        cv = self.get_cvparm("MS:1000042")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def charge_state(self) -> int | None:
        """Get charge state for this precursor."""
        cv = self.get_cvparm("MS:1000041")
        if cv is not None and cv.value is not None:
            return int(cv.value)
        return None

    @property
    def ir_im(self) -> float | None:
        """Get inversion reduced ion mobility for this precursor."""
        cv = self.get_cvparm("MS:1002815")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def im_drift_time(self) -> float | None:
        """Get ion mobility drift time for this precursor."""
        cv = self.get_cvparm("MS:1002476")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def faims_voltage_start(self) -> float | None:
        """Get FAIMS voltage start for this precursor."""
        cv = self.get_cvparm("MS:1003450")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def faims_voltage_end(self) -> float | None:
        """Get FAIMS voltage end for this precursor."""
        cv = self.get_cvparm("MS:1003451")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def ccs(self) -> float | None:
        """Get collisional cross section for this precursor."""
        cv = self.get_cvparm("MS:1002954")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None


@dataclass(frozen=True, repr=False)
class Activation(_ParamGroup):
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
        cv = self.get_cvparm("MS:1000509")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def ce(self) -> float | None:
        """Get collision energy for this precursor."""
        cv = self.get_cvparm("MS:1000045")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def supplemental_ce(self) -> float | None:
        """Get supplemental collision energy for this precursor."""
        cv = self.get_cvparm("MS:1002680")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None

    @property
    def collision_gas(self) -> str | None:
        """Get collision gas for this precursor."""
        cv = self.get_cvparm("MS:1000419")
        if cv is not None and cv.value is not None:
            return cv.name
        return None

    @property
    def collision_gas_pressure(self) -> float | None:
        """Get collision gas pressure for this precursor."""
        cv = self.get_cvparm("MS:1000869")
        if cv is not None and cv.value is not None:
            return float(cv.value)
        return None


@dataclass(frozen=True, repr=False)
class Precursor(_DataTreeWrapper):
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
    pass


@dataclass(frozen=True, repr=False)
class _ProductListMixin(_DataTreeWrapperProtocol):
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
    @property
    def id(self) -> str:
        """Get spectrum id."""
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Spectrum ID is missing")
        return id

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

        cv = self.get_cvparm(SpectrumMSAccession.TOTAL_ION_CURRENT)
        if cv is None or cv.value is None:
            return None

        return float(cv.value)

    @cached_property
    def ms_level(self) -> int | None:
        """Get MS level for this spectrum."""
        cv = self.get_cvparm(SpectrumMSAccession.MS_LEVEL)
        if cv is not None and cv.value is not None:
            return int(cv.value)


@dataclass(frozen=True)
class Chromatogram(_ParamGroup, _BinaryDataArrayMixin):
    @property
    def id(self) -> str:
        """Get chromatogram id."""
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Chromatogram ID is missing")
        return id

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
