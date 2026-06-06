"""mzx — Inline Spectrum URL Encoder.

Encodes a single mass spectrum into a compact, URL-safe token (mzx1.…) so it can be
shared with no backend. The entire spectrum lives in the token.

Public API::

    encode_spectrum(spec, *, lossless=False, max_len=None) -> str
    decode_token(token) -> DecodedSpectrum
    from_mzmlpy(spec, ref_groups=None) -> InlineSpectrum
    top_n(spec, n) -> InlineSpectrum
    to_fragment(token, base) -> str
    to_query(token, base, param="d") -> str
    to_data_uri(token) -> str
    extract_token(url_or_uri) -> str
"""

from __future__ import annotations

import warnings
from urllib.parse import parse_qs, urlparse, urlunparse

from .cv import ARRAY_CHARGE, ARRAY_INTENSITY, ARRAY_MZ, ION_MOBILITY_ARRAY_TAILS
from .header import build_header, extract_descriptors, parse_header
from .model import DecodedSpectrum, InlineSpectrum, MzxCvParam
from .peaks import _validate_arrays, build_array_blobs, canonical_sort, compute_hash, decode_array_blobs, top_n
from .proforma import validate_interp
from .token import build_token, parse_token

__all__ = [
    "encode_spectrum",
    "decode_token",
    "from_mzmlpy",
    "top_n",
    "to_fragment",
    "to_query",
    "to_data_uri",
    "extract_token",
    "InlineSpectrum",
    "DecodedSpectrum",
    "MzxCvParam",
]

_SIZE_WARN = 8192   # bytes — warn past this
_MAGIC_PREFIX = "mzx1."
_DATA_URI_PREFIX = "data:application/vnd.mzx;v=1,"


def encode_spectrum(
    spec: InlineSpectrum,
    *,
    lossless: bool = False,
    max_len: int | None = None,
) -> str:
    """Encode an InlineSpectrum to a mzx1 token string.

    Args:
        spec: The spectrum to encode.
        lossless: If True, use raw IEEE-754 + zlib (bit-exact). Default is lossy
            MS-Numpress (recommended for URL sharing).
        max_len: Raise OverflowError if the encoded token exceeds this byte length.
            Use top_n() to reduce peak count, or fall back to a USI reference for
            repository-resident spectra.

    Returns:
        A ``mzx1.`` token string.

    Raises:
        OverflowError: If max_len is set and the encoded length exceeds it.
        ValueError: If arrays contain NaN/Inf, or peaks are not finite.
    """
    spec = canonical_sort(spec)
    _validate_arrays(spec)

    if spec.interp is not None:
        validate_interp(spec.interp)

    blobs, descriptors = build_array_blobs(spec, lossless=lossless)

    # Assign segment indices
    for i, desc in enumerate(descriptors):
        desc["seg"] = i

    # Compute hash over header (without hash field) + blobs
    header_no_hash = build_header(spec, descriptors, hash_str=None)
    hash_str = compute_hash(header_no_hash, blobs)

    # Build final header with hash
    header_bytes = build_header(spec, descriptors, hash_str=hash_str)
    token = build_token(header_bytes, blobs)

    if len(token) > _SIZE_WARN:
        warnings.warn(
            f"mzx token length {len(token)} bytes exceeds recommended maximum of {_SIZE_WARN} bytes. "
            "Consider using top_n() to reduce peak count, or fall back to a USI reference.",
            UserWarning,
            stacklevel=2,
        )

    if max_len is not None and len(token) > max_len:
        raise OverflowError(
            f"Encoded mzx token is {len(token)} bytes, which exceeds max_len={max_len}. "
            "Use top_n(spec, n) to reduce peak count before encoding, "
            "or use a USI reference for repository-resident spectra."
        )

    return token


def decode_token(token: str) -> DecodedSpectrum:
    """Decode a mzx1 token string into a DecodedSpectrum.

    Verifies the stored hash if present, raising ValueError on mismatch.

    Args:
        token: A ``mzx1.`` token string.

    Returns:
        DecodedSpectrum with all metadata and peak arrays populated.

    Raises:
        ValueError: On bad magic/version or hash mismatch.
    """
    header_bytes, blobs = parse_token(token)
    decoded = parse_header(header_bytes)

    # Verify hash BEFORE decoding arrays (catches corruption early)
    if decoded.hash is not None:
        import hashlib

        from .token import b64url_encode
        header_no_hash = _strip_hash(header_bytes)
        h = hashlib.sha256()
        h.update(header_no_hash)
        for blob in blobs:
            h.update(blob)
        from .peaks import HASH_BYTES
        expected = b64url_encode(h.digest()[:HASH_BYTES])
        if expected != decoded.hash:
            raise ValueError(
                f"mzx token hash mismatch: stored={decoded.hash!r}, computed={expected!r}. "
                "Token may be corrupted."
            )

    descriptors = extract_descriptors(header_bytes)

    # Decode peak arrays
    arrays = decode_array_blobs(descriptors, blobs)

    decoded.mz = arrays.get(ARRAY_MZ)
    decoded.intensity = arrays.get(ARRAY_INTENSITY)
    decoded.charge = arrays.get(ARRAY_CHARGE)

    # Ion mobility: any remaining array tail in ION_MOBILITY_ARRAY_TAILS
    for tail, arr in arrays.items():
        if tail in ION_MOBILITY_ARRAY_TAILS.values():
            decoded.ion_mobility = arr
            from .cv import decode_tail
            decoded.ion_mobility_type = decode_tail(tail)
            break

    return decoded


def _strip_hash(header_bytes: bytes) -> bytes:
    """Return header bytes with key 9 (hash) removed, for hash verification."""
    import msgpack
    h = msgpack.unpackb(header_bytes, raw=False, strict_map_key=False)
    h.pop(9, None)
    return msgpack.packb(h, use_bin_type=True)


def from_mzmlpy(spec, ref_groups: dict | None = None) -> InlineSpectrum:
    """Convert a mzmlpy Spectrum to InlineSpectrum.

    Args:
        spec: A mzmlpy.spectra.Spectrum.
        ref_groups: Optional dict mapping group id → mzmlpy _ParamGroup, for
            expanding referenceableParamGroupRef elements. Build it as
            ``{g.id: g for g in mzml.referenceable_param_groups}``.

    Returns:
        InlineSpectrum ready for encoding.
    """
    from .mzml import from_mzmlpy as _bridge
    return _bridge(spec, ref_groups=ref_groups)


# ─── URL binding helpers ─────────────────────────────────────────────────────

def to_fragment(token: str, base: str) -> str:
    """Wrap a token as a URL fragment: ``base#token``.

    The fragment is never sent to the server, avoiding length limits and access logs.
    """
    return f"{base.rstrip('#')}#{token}"


def to_query(token: str, base: str, param: str = "d") -> str:
    """Wrap a token as a URL query parameter: ``base?param=token``."""
    parsed = urlparse(base)
    query = f"{param}={token}"
    return urlunparse(parsed._replace(query=query))


def to_data_uri(token: str) -> str:
    """Wrap a token in a ``data:application/vnd.mzx;v=1,`` URI."""
    return f"{_DATA_URI_PREFIX}{token}"


def extract_token(url_or_uri: str) -> str:
    """Extract a mzx1 token from a URL fragment, query string, or data: URI.

    Raises ValueError if no token is found.
    """
    if url_or_uri.startswith(_DATA_URI_PREFIX):
        return url_or_uri[len(_DATA_URI_PREFIX):]

    parsed = urlparse(url_or_uri)

    if parsed.fragment.startswith(_MAGIC_PREFIX):
        return parsed.fragment

    # Check query params for any value starting with mzx1.
    qs = parse_qs(parsed.query)
    for vals in qs.values():
        for v in vals:
            if v.startswith(_MAGIC_PREFIX):
                return v

    raise ValueError(f"No mzx1 token found in: {url_or_uri!r}")
