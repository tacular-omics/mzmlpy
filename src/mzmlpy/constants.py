from enum import StrEnum


class PeakType(StrEnum):
    """Enumeration of peak types."""

    PROFILE = "profile"
    CENTROIDED = "centroided"
    DECONVOLUTED = "deconvoluted"


class NoiseMode(StrEnum):
    """Enumeration of noise estimation modes."""

    MEDIAN = "median"
    MEAN = "mean"
    MAD = "mad"


class DataType(StrEnum):
    """Enumeration of data array types."""

    MZ = "mz"
    INTENSITY = "i"
    TIME = "time"


class TimeUnit(StrEnum):
    """Enumeration of time units."""

    MILLISECOND = "millisecond"
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"


class BinaryDataTypeAccession(StrEnum):
    """Enumeration of binary data type accessions."""

    FLOAT_32 = "MS:1000521"
    FLOAT_64 = "MS:1000523"
    INT_32 = "MS:1000519"
    INT_64 = "MS:1000522"
    ASCII_STRING = "MS:1001479"


class CompressionTypeAccessions(StrEnum):
    BYTE_SHUFFLED_ZSTD = "MS:1003781"
    MS_NUMPRESS_SHORT_LOGGED_FLOAT = "MS:1002314"
    TRUNCATION_LINEAR_PREDICTION_ZLIB = "MS:1003090"
    ZLIB_COMPRESSION = "MS:1000574"
    NO_COMPRESSION = "MS:1000576"
    DICTIONARY_ENCODED_ZSTD = "MS:1003782"

    # MS-Numpress linear prediction compression followed by zlib compression
    MS_NUMPRESS_LINEAR_PREDICTION_ZLIB = "MS:1002746"
    TRUNCATION_ZLIB = "MS:1003088"
    MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB = "MS:1002748"
    MS_NUMPRESS_LINEAR_PREDICTION_ZSTD = "MS:1003783"
    MS_NUMPRESS_POSITIVE_INTEGER_ZLIB = "MS:1002747"
    MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZSTD = "MS:1003785"
    MS_NUMPRESS_LINEAR_PREDICTION = "MS:1002312"
    MS_NUMPRESS_POSITIVE_INTEGER = "MS:1002313"
    TRUNCATION_DELTA_PREDICTION_ZLIB = "MS:1003089"
    ZSTD_COMPRESSION = "MS:1003780"
    MS_NUMPRESS_POSITIVE_INTEGER_ZSTD = "MS:1003784"


class XMLAttribute(StrEnum):
    """Enumeration of common XML attribute names."""

    ACCESSION = "accession"
    NAME = "name"
    DEFAULT_ARRAY_LENGTH = "defaultArrayLength"


class XMLElement(StrEnum):
    """Enumeration of common XML element names."""

    BINARY_DATA_ARRAY_LIST = "binaryDataArrayList"
    BINARY_DATA_ARRAY = "binaryDataArray"
    CV_PARAM = "cvParam"
    BINARY = "binary"
    SCAN_LIST = "scanList"
    SCAN = "scan"
    SCAN_WINDOW_LIST = "scanWindowList"
    SCAN_WINDOW = "scanWindow"


class EncodingFormat(StrEnum):
    """Enumeration of encoding formats."""

    LATIN1 = "latin-1"
    UTF8 = "utf-8"
    XML = "xml"


class SpectrumType(StrEnum):
    """Enumeration of spectrum types."""

    PROFILE = "MS:1000128"
    CENTROID = "MS:1000127"


class SpectrumCombinationAccession(StrEnum):
    NO_COMBINATION = "MS:1000795"
    MEDIAN = "MS:1000573"
    SUM = "MS:1000571"
    MEAN = "MS:1000575"


class ScanPolarity(StrEnum):
    """Enumeration of MS accessions for chromatogram properties."""

    POSITIVE = "MS:1000129"
    NEGATIVE = "MS:1000130"


# TODO: These are a mix of spectrum params and scan/window params
class SpectrumMSAccession(StrEnum):
    """Enumeration of MS accessions for spectrum properties."""

    MS_LEVEL = "MS:1000511"
    PEAK_INTENSITY = "MS:1000042"

    # scan/precursor properties?
    SCAN_START_TIME = "MS:1000016"
    SELECTED_ION_MZ = "MS:1000744"
    CHARGE_STATE = "MS:1000041"
    TOTAL_ION_CURRENT = "MS:1000285"
    ION_INJECTION_TIME = "MS:1000927"
    SCAN_WINDOW_LOWER_LIMIT = "MS:1000501"
    SCAN_WINDOW_UPPER_LIMIT = "MS:1000500"


class BinaryDataArrayAccession(StrEnum):
    """Enumeration of binary data array accessions."""

    RAW_ION_MOBILITY = "MS:1003007"
    MEAN_ION_MOBILITY_DRIFT_TIME = "MS:1002477"
    DECONVOLUTED_ION_MOBILITY_DRIFT_TIME = "MS:1003156"
    MEAN_INVERSE_REDUCED_ION_MOBILITY = "MS:1003006"
    MEAN_ION_MOBILITY = "MS:1002816"
    DECONVOLUTED_INVERSE_REDUCED_ION_MOBILITY = "MS:1003155"
    RAW_ION_MOBILITY_DRIFT_TIME = "MS:1003153"
    VACUUM_PUMP_PRESSURE = "MS:4000210"
    RAW_INVERSE_REDUCED_ION_MOBILITY = "MS:1003008"
    DECONVOLUTED_ION_MOBILITY = "MS:1003154"
    TIME = "MS:1000595"
    MEAN_CHARGE = "MS:1002478"
    MZ = "MS:1000514"
    SAMPLED_NOISE_INTENSITY = "MS:1002744"
    FLOW_RATE = "MS:1000820"
    CHARGE = "MS:1000516"
    SAMPLED_NOISE_BASELINE = "MS:1002745"
    ION_MOBILITY = "MS:1002893"
    BASELINE = "MS:1002530"
    RESOLUTION = "MS:1002529"
    PRESSURE = "MS:1000821"
    INTENSITY = "MS:1000515"
    MEASURED_ELEMENT = "MS:1002716"
    SCANNING_QUADRUPOLE_POSITION_UPPER_BOUND_MZ = "MS:1003158"
    NON_STANDARD_DATA = "MS:1000786"
    SCANNING_QUADRUPOLE_POSITION_LOWER_BOUND_MZ = "MS:1003157"
    NOISE = "MS:1002742"
    WAVELENGTH = "MS:1000617"
    SIGNAL_TO_NOISE = "MS:1000517"
    MASS = "MS:1003143"
    TEMPERATURE = "MS:1000822"
    SAMPLED_NOISE_MZ = "MS:1002743"


class XMLNamespace(StrEnum):
    """Enumeration of XML namespace identifiers."""

    SCHEMA_LOCATION = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"


class MzMLElement(StrEnum):
    """Enumeration of mzML element tag names (without namespace)."""

    MZML = "mzML"
    CV = "cv"
    FILE_DESCRIPTION = "fileDescription"
    SAMPLE_LIST = "sampleList"
    REFERENCEABLE_PARAM_GROUP_LIST = "referenceableParamGroupList"
    SOFTWARE_LIST = "softwareList"
    SOFTWARE = "software"
    INSTRUMENT_CONFIG_LIST = "instrumentConfigurationList"
    DATA_PROCESSING_LIST = "dataProcessingList"
    CV_PARAM = "cvParam"
    USER_PARAM = "userParam"
    SPECTRUM_LIST = "spectrumList"
    CHROMATOGRAM_LIST = "chromatogramList"
    RUN = "run"
    SPECTRUM = "spectrum"
    CHROMATOGRAM = "chromatogram"
    SCAN_SETTINGS_LIST = "scanSettingsList"
    PROCESSING_METHOD = "processingMethod"
    REFERENCEABLE_PARAM_GROUP = "referenceableParamGroup"
    REFERENCEABLE_PARAM_GROUP_REF = "referenceableParamGroupRef"
    FILE_CONTENT = "fileContent"
    SOURCE_FILE_LIST = "sourceFileList"
    SOURCE_FILE = "sourceFile"
    CONTACT = "contact"
    SOFTWARE_REF = "softwareRef"
    COMPONENT_LIST = "componentList"
    SOURCE = "source"
    ANALYZER = "analyzer"
    DETECTOR = "detector"
    SOURCE_FILE_REF_LIST = "sourceFileRefList"
    SOURCE_FILE_REF = "sourceFileRef"
    TARGET_LIST = "targetList"
    TARGET = "target"
    ISOLATION_WINDOW = "isolationWindow"
    SELECTED_ION_LIST = "selectedIonList"
    SELECTED_ION = "selectedIon"
    ACTIVATION = "activation"
    PRECURSOR_LIST = "precursorList"
    PRECURSOR = "precursor"
    PRODUCT_LIST = "productList"
    PRODUCT = "product"
    SAMPLE = "sample"
    INSTRUMENT_CONFIGURATION = "instrumentConfiguration"
    SCAN_SETTINGS = "scanSettings"
    DATA_PROCESSING = "dataProcessing"


PROTON_MASS = 1.00727646677
ISOTOPE_AVERAGE_DIFFERENCE = 1.002

# Data type to numpy dtype mapping
BINARY_DECODE_DTYPES: dict[BinaryDataTypeAccession, str] = {
    BinaryDataTypeAccession.FLOAT_32: "float32",
    BinaryDataTypeAccession.FLOAT_64: "float64",
    BinaryDataTypeAccession.INT_32: "int32",
    BinaryDataTypeAccession.INT_64: "int64",
}


class ChromatogramTypeAccession(StrEnum):
    EMMISION = "MS:1000813"
    SELECTED_ION_MONITORING = "MS:1001472"
    BASEPEAK = "MS:1000628"
    PRECURSOR_ION_CURRENT = "MS:4000025"
    TOTAL_ION_CURRENT = "MS:1000235"
    ABSORPTION = "MS:1000812"
    SELECTED_REACTION_MONITORING = "MS:1001473"
    SELECTED_ION_CURRENT = "MS:1000627"


ISOLATION_WINDOW_TARGET_MZ = "MS:1000827"


class ChecksumTypeAccession(StrEnum):
    """Enumeration of checksum type accessions."""

    MD5 = "MS:1000568"
    SHA1 = "MS:1000569"
    SHA256 = "MS:1003151"


class ContactAccession(StrEnum):
    """Enumeration of contact information accessions."""

    EMAIL = "MS:1000589"
    URL = "MS:1000588"
    NAME = "MS:1000586"
    FAX_NUMBER = "MS:1001756"
    ADDRESS = "MS:1000587"
    TOLL_FREE_PHONE_NUMBER = "MS:1001757"
    PHONE_NUMBER = "MS:1001755"
    ROLE = "MS:1002033"
    ORGANIZATION = "MS:1000590"


class CollisionDissociationTypeAccession(StrEnum):
    """Enumeration of collision dissociation type accessions."""

    SUPPLEMENTAL_BEAM_TYPE_COLLISION_INDUCED_DISSOCIATION = "MS:1002678"
    HIGHER_ENERGY_BEAM_TYPE_COLLISION_INDUCED_DISSOCIATION = "MS:1002481"
    BEAM_TYPE_COLLISION_INDUCED_DISSOCIATION = "MS:1000422"
    ULTRAVIOLET_PHOTODISSOCIATION = "MS:1003246"
    TRAP_TYPE_COLLISION_INDUCED_DISSOCIATION = "MS:1002472"
    INFRARED_MULTIPHOTON_DISSOCIATION = "MS:1000262"
    ELECTRON_ACTIVATED_DISSOCIATION = "MS:1003294"
    SUPPLEMENTAL_COLLISION_INDUCED_DISSOCIATION = "MS:1002679"
    IN_SOURCE_COLLISION_INDUCED_DISSOCIATION = "MS:1001880"
    LOW_ENERGY_COLLISION_INDUCED_DISSOCIATION = "MS:1000433"
    PULSED_Q_DISSOCIATION = "MS:1000599"
    COLLISION_INDUCED_DISSOCIATION = "MS:1000133"
    SUSTAINED_OFF_RESONANCE_IRRADIATION = "MS:1000282"
    BLACKBODY_INFRARED_RADIATIVE_DISSOCIATION = "MS:1000242"
    PHOTODISSOCIATION = "MS:1000435"
    SURFACE_INDUCED_DISSOCIATION = "MS:1000136"
    POST_SOURCE_DECAY = "MS:1000135"
    ELECTRON_CAPTURE_DISSOCIATION = "MS:1000250"
    PLASMA_DESORPTION = "MS:1000134"
    LIFT = "MS:1002000"
    ELECTRON_TRANSFER_DISSOCIATION = "MS:1000598"
    NEGATIVE_ELECTRON_TRANSFER_DISSOCIATION = "MS:1003247"
