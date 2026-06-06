"""Peak array assembly, canonical form, hashing, and top_n helper."""

from __future__ import annotations

import hashlib

import numpy as np
from numpy.typing import NDArray

from .codecs import get_codec
from .codecs.numpress import DEFAULT_NUMLIN_FP, DEFAULT_NUMSLOF_FP
from .cv import (
    ARRAY_CHARGE,
    ARRAY_INTENSITY,
    ARRAY_MZ,
    COMP_NUMLIN_ZLIB,
    COMP_NUMPIC_ZLIB,
    COMP_NUMSLOF_ZLIB,
    COMP_ZLIB,
    TYPE_FLOAT64,
)
from .model import InlineSpectrum

HASH_BYTES = 12  # 12 bytes → 16 base64url chars
SIZE_WARN_THRESHOLD = 8192  # 8 KB
SIZE_HARD_DEFAULT = None  # no default hard limit (caller passes max_len)


def canonical_sort(spec: InlineSpectrum) -> InlineSpectrum:
    """Return a copy of spec with peaks sorted m/z-ascending.

    If mz is None, returns spec unchanged.
    """
    if spec.mz is None or len(spec.mz) == 0:
        return spec
    order = np.argsort(spec.mz, kind="stable")
    mz = spec.mz[order]
    intensity = spec.intensity[order] if spec.intensity is not None else None
    charge = spec.charge[order] if spec.charge is not None else None
    im = spec.ion_mobility[order] if spec.ion_mobility is not None else None
    return InlineSpectrum(
        default_array_length=spec.default_array_length,
        mz=mz,
        intensity=intensity,
        charge=charge,
        ion_mobility=im,
        ion_mobility_type=spec.ion_mobility_type,
        id=spec.id,
        params=spec.params,
        scans=spec.scans,
        scan_combination=spec.scan_combination,
        precursors=spec.precursors,
        products=spec.products,
        interp=spec.interp,
    )


def _validate_arrays(spec: InlineSpectrum) -> None:
    """Raise ValueError if any array contains NaN or Inf."""
    for name, arr in [("mz", spec.mz), ("intensity", spec.intensity), ("charge", spec.charge), ("ion_mobility", spec.ion_mobility)]:  # noqa: E501
        if arr is not None and (np.any(np.isnan(arr)) or np.any(np.isinf(arr))):
            raise ValueError(f"Array '{name}' contains NaN or Inf values, which are not allowed in canonical form.")


def build_array_blobs(
    spec: InlineSpectrum,
    lossless: bool,
    mz_fp: float = DEFAULT_NUMLIN_FP,
    int_fp: float = DEFAULT_NUMSLOF_FP,
) -> tuple[list[bytes], list[dict]]:
    """Encode all peak arrays and return (blobs, descriptors).

    Returns a list of raw byte blobs and matching array descriptor dicts (without 'seg').
    The caller assigns seg indices.
    """
    blobs: list[bytes] = []
    descriptors: list[dict] = []

    def add_array(array: NDArray, array_tail: int, comp_tail: int, fp: float | None) -> None:
        codec = get_codec(comp_tail)
        blob = codec.encode(array, fp)
        blobs.append(blob)
        desc: dict = {
            "type": TYPE_FLOAT64,
            "array": array_tail,
            "comp": comp_tail,
        }
        if fp is not None and not lossless:
            desc["fp"] = fp
        descriptors.append(desc)

    if spec.mz is not None:
        comp = COMP_ZLIB if lossless else COMP_NUMLIN_ZLIB
        fp = None if lossless else mz_fp
        add_array(spec.mz, ARRAY_MZ, comp, fp)

    if spec.intensity is not None:
        comp = COMP_ZLIB if lossless else COMP_NUMSLOF_ZLIB
        fp = None if lossless else int_fp
        add_array(spec.intensity, ARRAY_INTENSITY, comp, fp)

    if spec.charge is not None:
        comp = COMP_ZLIB if lossless else COMP_NUMPIC_ZLIB
        add_array(spec.charge, ARRAY_CHARGE, comp, None)

    if spec.ion_mobility is not None and spec.ion_mobility_type is not None:
        from .cv import accession_tail
        im_array_tail = accession_tail(spec.ion_mobility_type)
        comp = COMP_ZLIB if lossless else COMP_NUMLIN_ZLIB
        fp = None if lossless else mz_fp
        add_array(spec.ion_mobility, im_array_tail, comp, fp)

    return blobs, descriptors


def decode_array_blobs(descriptors: list[dict], blobs: list[bytes]) -> dict[int, NDArray[np.float64]]:
    """Decode array blobs by seg index, returning a dict of array_tail → ndarray."""
    result: dict[int, NDArray[np.float64]] = {}
    for desc in descriptors:
        seg = desc["seg"]
        comp_tail = desc["comp"]
        array_tail = desc["array"]
        codec = get_codec(comp_tail)
        result[array_tail] = codec.decode(blobs[seg])
    return result


def compute_hash(header_bytes: bytes, blobs: list[bytes]) -> str:
    """Compute truncated SHA-256 over header + all array blobs, return base64url string."""
    from .token import b64url_encode
    h = hashlib.sha256()
    h.update(header_bytes)
    for blob in blobs:
        h.update(blob)
    return b64url_encode(h.digest()[:HASH_BYTES])


def top_n(spec: InlineSpectrum, n: int) -> InlineSpectrum:
    """Return a new InlineSpectrum keeping only the n most intense peaks.

    Peaks are re-sorted m/z-ascending after selection.
    This is explicit caller-driven trimming; encoding never trims silently.
    """
    if spec.intensity is None or n >= len(spec.intensity):
        return spec
    top_idx = np.argpartition(spec.intensity, -n)[-n:]
    top_idx = top_idx[np.argsort(spec.mz[top_idx] if spec.mz is not None else top_idx)]

    mz = spec.mz[top_idx] if spec.mz is not None else None
    intensity = spec.intensity[top_idx]
    charge = spec.charge[top_idx] if spec.charge is not None else None
    im = spec.ion_mobility[top_idx] if spec.ion_mobility is not None else None

    return InlineSpectrum(
        default_array_length=n,
        mz=mz,
        intensity=intensity,
        charge=charge,
        ion_mobility=im,
        ion_mobility_type=spec.ion_mobility_type,
        id=spec.id,
        params=spec.params,
        scans=spec.scans,
        scan_combination=spec.scan_combination,
        precursors=spec.precursors,
        products=spec.products,
        interp=spec.interp,
    )
