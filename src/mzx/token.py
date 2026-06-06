"""Base64url encoding/decoding (no padding) and segment framing for mzx tokens."""

import base64

MAGIC = "mzx1"
FORMAT_VERSION = 1


def b64url_encode(data: bytes) -> str:
    """Encode bytes to base64url string without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    """Decode a base64url string (with or without padding) to bytes."""
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def build_token(header_bytes: bytes, array_blobs: list[bytes]) -> str:
    """Assemble a mzx1 token from a msgpack header and per-array blobs."""
    parts = [MAGIC, b64url_encode(header_bytes)]
    parts.extend(b64url_encode(blob) for blob in array_blobs)
    return ".".join(parts)


def parse_token(token: str) -> tuple[bytes, list[bytes]]:
    """Split a mzx1 token into (header_bytes, [array_blob, ...]).

    Raises ValueError on bad magic or version.
    """
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError(f"Token has {len(parts)} segments; need at least 2 (magic + header).")
    magic = parts[0]
    if magic != MAGIC:
        raise ValueError(f"Unknown magic/version: {magic!r}; expected {MAGIC!r}.")
    header_bytes = b64url_decode(parts[1])
    array_blobs = [b64url_decode(p) for p in parts[2:]]
    return header_bytes, array_blobs
