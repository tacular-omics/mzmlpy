"""CV accession ↔ integer-tail mapping using mzmlpy's StrEnum constants.

Rules (§3.1):
- Accession tails default to MS: ontology.
- Unit tails default to UO: ontology.
- Any other ontology uses an explicit [ontology_id, tail] pair.

The tail for "MS:1000511" is 1000511; for "UO:0000031" is 31.
"""

from __future__ import annotations

from mzmlpy.constants import (
    BinaryDataArrayAccession,
    BinaryDataTypeAccession,
    CollisionDissociationTypeAccession,
    CompressionTypeAccessions,
    ScanPolarity,
    SpectrumCombinationAccession,
    SpectrumMSAccession,
    SpectrumType,
)

_DEFAULT_PARAM_ONTOLOGY = "MS"
_DEFAULT_UNIT_ONTOLOGY = "UO"


def accession_tail(accession: str) -> int:
    """Extract the integer tail from an accession string like 'MS:1000511' → 1000511."""
    return int(accession.split(":")[1])


def accession_ontology(accession: str) -> str:
    """Extract the ontology prefix from 'MS:1000511' → 'MS'."""
    return accession.split(":")[0]


def encode_tail(accession: str) -> int:
    """Encode an accession to its tail integer (assumes MS: default ontology)."""
    return accession_tail(accession)


def encode_unit(unit_accession: str) -> int | list:
    """Encode a unit accession to a tail int (UO: default) or [ontology, tail] for other ontologies."""
    onto = accession_ontology(unit_accession)
    tail = accession_tail(unit_accession)
    if onto == _DEFAULT_UNIT_ONTOLOGY:
        return tail
    return [onto, tail]


def decode_tail(tail: int, ontology: str = _DEFAULT_PARAM_ONTOLOGY) -> str:
    """Reconstruct an accession string from a tail integer and ontology prefix."""
    return f"{ontology}:{tail:07d}"


def decode_unit_tail(tail: int | list) -> str:
    """Reconstruct a unit accession string from a tail (int = UO: default, list = [ontology, tail])."""
    if isinstance(tail, list):
        return f"{tail[0]}:{tail[1]:07d}"
    return f"{_DEFAULT_UNIT_ONTOLOGY}:{tail:07d}"


# ─── Codec compression tails (used by codecs module) ───────────────────────

COMP_NUMLIN_ZLIB = accession_tail(CompressionTypeAccessions.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB)
COMP_NUMSLOF_ZLIB = accession_tail(CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB)
COMP_NUMPIC_ZLIB = accession_tail(CompressionTypeAccessions.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB)
COMP_NUMLIN = accession_tail(CompressionTypeAccessions.MS_NUMPRESS_LINEAR_PREDICTION)
COMP_NUMSLOF = accession_tail(CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT)
COMP_NUMPIC = accession_tail(CompressionTypeAccessions.MS_NUMPRESS_POSITIVE_INTEGER)
COMP_ZLIB = accession_tail(CompressionTypeAccessions.ZLIB_COMPRESSION)
COMP_NONE = accession_tail(CompressionTypeAccessions.NO_COMPRESSION)

# ─── Data type tails ────────────────────────────────────────────────────────

TYPE_FLOAT64 = accession_tail(BinaryDataTypeAccession.FLOAT_64)
TYPE_FLOAT32 = accession_tail(BinaryDataTypeAccession.FLOAT_32)
TYPE_INT32 = accession_tail(BinaryDataTypeAccession.INT_32)
TYPE_INT64 = accession_tail(BinaryDataTypeAccession.INT_64)

# ─── Array type tails ───────────────────────────────────────────────────────

ARRAY_MZ = accession_tail(BinaryDataArrayAccession.MZ)
ARRAY_INTENSITY = accession_tail(BinaryDataArrayAccession.INTENSITY)
ARRAY_CHARGE = accession_tail(BinaryDataArrayAccession.CHARGE)

# Ion mobility array tails
ION_MOBILITY_ARRAY_TAILS: dict[str, int] = {
    acc: accession_tail(acc)
    for acc in (
        BinaryDataArrayAccession.RAW_ION_MOBILITY,
        BinaryDataArrayAccession.MEAN_ION_MOBILITY_DRIFT_TIME,
        BinaryDataArrayAccession.DECONVOLUTED_ION_MOBILITY_DRIFT_TIME,
        BinaryDataArrayAccession.MEAN_INVERSE_REDUCED_ION_MOBILITY,
        BinaryDataArrayAccession.MEAN_ION_MOBILITY,
        BinaryDataArrayAccession.DECONVOLUTED_INVERSE_REDUCED_ION_MOBILITY,
        BinaryDataArrayAccession.RAW_ION_MOBILITY_DRIFT_TIME,
        BinaryDataArrayAccession.RAW_INVERSE_REDUCED_ION_MOBILITY,
        BinaryDataArrayAccession.ION_MOBILITY,
    )
}

# ─── Known accession registry for validation/tests ──────────────────────────

ALL_MZX_ACCESSIONS: set[str] = set()
for _enum in (
    BinaryDataArrayAccession,
    BinaryDataTypeAccession,
    CompressionTypeAccessions,
    ScanPolarity,
    SpectrumCombinationAccession,
    SpectrumMSAccession,
    SpectrumType,
    CollisionDissociationTypeAccession,
):
    ALL_MZX_ACCESSIONS.update(str(v) for v in _enum)
