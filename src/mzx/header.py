"""msgpack header build/parse for the mzx integer-key registry.

Top-level key registry (mirrors mzML <spectrum>):
  0  format version (int)
  1  defaultArrayLength (int)
  2  @id (str, optional)
  3  spectrum param map
  4  scanList: {c?: combination-flag-tail, s: [scan, ...]}
  5  precursorList: [precursor, ...]
  6  productList: [product, ...]
  7  binaryDataArrayList: [descriptor, ...]
  8  interp: ProForma string (optional)
  9  hash: truncated SHA-256 base64url (optional)
"""

from __future__ import annotations

import msgpack

from .cv import (
    _DEFAULT_PARAM_ONTOLOGY,
    accession_ontology,
    accession_tail,
    decode_tail,
    decode_unit_tail,
    encode_unit,
)
from .model import (
    DecodedSpectrum,
    InlineSpectrum,
    MzxActivation,
    MzxCvParam,
    MzxIsolationWindow,
    MzxPrecursor,
    MzxProduct,
    MzxScan,
    MzxScanWindow,
    MzxSelectedIon,
)
from .token import FORMAT_VERSION

# ─── CvParam encoding ───────────────────────────────────────────────────────

def _encode_cvparam(p: MzxCvParam) -> tuple[int, object]:
    """Encode a MzxCvParam into (tail_key, value) suitable for a msgpack map."""
    onto = accession_ontology(p.accession)
    tail = accession_tail(p.accession)

    if onto != _DEFAULT_PARAM_ONTOLOGY:
        tail_key: int | list = [onto, tail]
    else:
        tail_key = tail

    if p.value is None:
        val = None
    elif p.unit_accession is not None:
        val = [p.value, encode_unit(p.unit_accession)]
    else:
        val = p.value

    return tail_key, val


def _encode_param_map(params: list[MzxCvParam]) -> dict:
    """Encode a list of CvParams into an integer-keyed map."""
    m: dict = {}
    for p in params:
        key, val = _encode_cvparam(p)
        m[key] = val
    return m


def _decode_param_map(m: dict) -> list[MzxCvParam]:
    """Decode an integer-keyed param map into a list of MzxCvParam."""
    params = []
    for raw_key, raw_val in m.items():
        if isinstance(raw_key, list):
            accession = f"{raw_key[0]}:{raw_key[1]:07d}"
        else:
            accession = decode_tail(raw_key)

        if raw_val is None:
            params.append(MzxCvParam(accession=accession))
        elif isinstance(raw_val, list):
            value = raw_val[0]
            unit_accession = decode_unit_tail(raw_val[1])
            params.append(MzxCvParam(accession=accession, value=value, unit_accession=unit_accession))
        else:
            params.append(MzxCvParam(accession=accession, value=raw_val))
    return params


# ─── Scan/ScanWindow encoding ────────────────────────────────────────────────

def _encode_scan_window(w: MzxScanWindow) -> dict:
    return _encode_param_map(w.params)


def _decode_scan_window(d: dict) -> MzxScanWindow:
    return MzxScanWindow(params=_decode_param_map(d))


def _encode_scan(s: MzxScan) -> dict:
    d: dict = {0: _encode_param_map(s.params)}
    if s.windows:
        d[1] = [_encode_scan_window(w) for w in s.windows]
    return d


def _decode_scan(d: dict) -> MzxScan:
    params = _decode_param_map(d.get(0, {}))
    windows = [_decode_scan_window(w) for w in d.get(1, [])]
    return MzxScan(params=params, windows=windows)


# ─── Precursor/Product encoding ──────────────────────────────────────────────

def _encode_isolation_window(iw: MzxIsolationWindow) -> dict:
    return _encode_param_map(iw.params)


def _decode_isolation_window(d: dict) -> MzxIsolationWindow:
    return MzxIsolationWindow(params=_decode_param_map(d))


def _encode_precursor(p: MzxPrecursor) -> dict:
    d: dict = {}
    if p.isolation_window is not None:
        d[0] = _encode_isolation_window(p.isolation_window)
    if p.selected_ions:
        d[1] = [_encode_param_map(si.params) for si in p.selected_ions]
    if p.activation is not None:
        d[2] = _encode_param_map(p.activation.params)
    if p.spectrum_ref is not None:
        d["us"] = p.spectrum_ref
    return d


def _decode_precursor(d: dict) -> MzxPrecursor:
    iw = _decode_isolation_window(d[0]) if 0 in d else None
    selected_ions = [MzxSelectedIon(params=_decode_param_map(si)) for si in d.get(1, [])]
    activation = MzxActivation(params=_decode_param_map(d[2])) if 2 in d else None
    spectrum_ref = d.get("us")
    return MzxPrecursor(
        isolation_window=iw, selected_ions=selected_ions, activation=activation, spectrum_ref=spectrum_ref
    )


def _encode_product(p: MzxProduct) -> dict:
    d: dict = {}
    if p.isolation_window is not None:
        d[0] = _encode_isolation_window(p.isolation_window)
    return d


def _decode_product(d: dict) -> MzxProduct:
    iw = _decode_isolation_window(d[0]) if 0 in d else None
    return MzxProduct(isolation_window=iw)


# ─── Full header build/parse ─────────────────────────────────────────────────

def build_header(
    spec: InlineSpectrum,
    descriptors: list[dict],
    hash_str: str | None = None,
) -> bytes:
    """Serialise InlineSpectrum metadata + array descriptors to msgpack bytes."""
    h: dict = {
        0: FORMAT_VERSION,
        1: spec.default_array_length,
    }
    if spec.id is not None:
        h[2] = spec.id
    if spec.params:
        h[3] = _encode_param_map(spec.params)
    if spec.scans or spec.scan_combination is not None:
        scan_entry: dict = {"s": [_encode_scan(s) for s in spec.scans]}
        if spec.scan_combination is not None:
            _, cval = _encode_cvparam(spec.scan_combination)
            scan_entry["c"] = accession_tail(spec.scan_combination.accession)
        h[4] = scan_entry
    if spec.precursors:
        h[5] = [_encode_precursor(p) for p in spec.precursors]
    if spec.products:
        h[6] = [_encode_product(p) for p in spec.products]
    h[7] = descriptors
    if spec.interp is not None:
        h[8] = spec.interp
    if hash_str is not None:
        h[9] = hash_str
    return msgpack.packb(h, use_bin_type=True)


def parse_header(header_bytes: bytes) -> DecodedSpectrum:
    """Deserialise a msgpack header into a DecodedSpectrum (arrays NOT decoded yet)."""
    h = msgpack.unpackb(header_bytes, raw=False, strict_map_key=False)

    fmt_version = h.get(0, FORMAT_VERSION)
    default_array_length = h[1]
    id_ = h.get(2)
    params = _decode_param_map(h.get(3, {}))

    scans: list[MzxScan] = []
    scan_combination: MzxCvParam | None = None
    scan_entry = h.get(4, {})
    if scan_entry:
        scans = [_decode_scan(s) for s in scan_entry.get("s", [])]
        if "c" in scan_entry:
            combo_tail = scan_entry["c"]
            scan_combination = MzxCvParam(accession=decode_tail(combo_tail))

    precursors = [_decode_precursor(p) for p in h.get(5, [])]
    products = [_decode_product(p) for p in h.get(6, [])]
    interp = h.get(8)
    hash_str = h.get(9)

    return DecodedSpectrum(
        default_array_length=default_array_length,
        id=id_,
        params=params,
        scans=scans,
        scan_combination=scan_combination,
        precursors=precursors,
        products=products,
        interp=interp,
        hash=hash_str,
        format_version=fmt_version,
    )


def extract_descriptors(header_bytes: bytes) -> list[dict]:
    """Extract only the array descriptors (key 7) from a msgpack header."""
    h = msgpack.unpackb(header_bytes, raw=False, strict_map_key=False)
    return h.get(7, [])
