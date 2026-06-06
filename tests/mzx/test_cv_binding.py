"""Acceptance criterion 7: No accession is hardcoded — all resolve via CV binding."""

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

from mzx.cv import (
    ARRAY_CHARGE,
    ARRAY_INTENSITY,
    ARRAY_MZ,
    COMP_NUMLIN_ZLIB,
    COMP_NUMPIC_ZLIB,
    COMP_NUMSLOF_ZLIB,
    COMP_ZLIB,
    TYPE_FLOAT64,
    accession_tail,
    decode_tail,
    encode_unit,
    decode_unit_tail,
)


def test_all_cv_constants_resolve():
    """Every mzx cv constant equals the tail of its source StrEnum value."""
    assert ARRAY_MZ == accession_tail(BinaryDataArrayAccession.MZ)
    assert ARRAY_INTENSITY == accession_tail(BinaryDataArrayAccession.INTENSITY)
    assert ARRAY_CHARGE == accession_tail(BinaryDataArrayAccession.CHARGE)
    assert TYPE_FLOAT64 == accession_tail(BinaryDataTypeAccession.FLOAT_64)
    assert COMP_NUMLIN_ZLIB == accession_tail(CompressionTypeAccessions.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB)
    assert COMP_NUMSLOF_ZLIB == accession_tail(CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB)
    assert COMP_NUMPIC_ZLIB == accession_tail(CompressionTypeAccessions.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB)
    assert COMP_ZLIB == accession_tail(CompressionTypeAccessions.ZLIB_COMPRESSION)


def test_tail_roundtrip():
    """accession_tail + decode_tail roundtrips for MS: ontology."""
    for acc in BinaryDataArrayAccession:
        tail = accession_tail(str(acc))
        reconstructed = decode_tail(tail)
        assert reconstructed == str(acc), f"{acc}: {reconstructed} != {acc}"


def test_unit_tail_roundtrip():
    """UO: unit accessions roundtrip through encode_unit/decode_unit_tail."""
    uo_accession = "UO:0000031"
    encoded = encode_unit(uo_accession)
    assert isinstance(encoded, int)
    decoded = decode_unit_tail(encoded)
    assert decoded == uo_accession


def test_non_uo_unit_tail_uses_list():
    """Non-UO unit accessions use the [ontology, tail] list form."""
    ms_accession = "MS:1000045"
    encoded = encode_unit(ms_accession)
    assert isinstance(encoded, list)
    assert encoded[0] == "MS"
    decoded = decode_unit_tail(encoded)
    assert decoded == ms_accession


def test_no_hardcoded_integers_in_codecs():
    """Codec registry keys match mzmlpy enum tails — not bare integer literals."""
    from mzx.codecs import _REGISTRY
    expected_keys = {
        accession_tail(CompressionTypeAccessions.MS_NUMPRESS_LINEAR_PREDICTION_ZLIB),
        accession_tail(CompressionTypeAccessions.MS_NUMPRESS_SHORT_LOGGED_FLOAT_ZLIB),
        accession_tail(CompressionTypeAccessions.MS_NUMPRESS_POSITIVE_INTEGER_ZLIB),
        accession_tail(CompressionTypeAccessions.ZLIB_COMPRESSION),
    }
    assert set(_REGISTRY.keys()) == expected_keys


def test_polarity_flags_are_accessions():
    """Polarity constants are proper StrEnum accessions."""
    assert ScanPolarity.POSITIVE.startswith("MS:")
    assert ScanPolarity.NEGATIVE.startswith("MS:")
    assert accession_tail(ScanPolarity.POSITIVE) > 0
    assert accession_tail(ScanPolarity.NEGATIVE) > 0
