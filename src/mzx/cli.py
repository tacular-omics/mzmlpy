"""CLI for mzx: encode, decode, and inspect tokens."""

from __future__ import annotations

import argparse
import json
import sys


def _encode_cmd(args: argparse.Namespace) -> None:
    import numpy as np

    from . import encode_spectrum
    from .model import InlineSpectrum, MzxCvParam

    data = json.load(sys.stdin if args.input == "-" else open(args.input))
    mz = np.array(data["mz"], dtype=np.float64)
    intensity = np.array(data["intensity"], dtype=np.float64)

    params = [MzxCvParam(**p) for p in data.get("params", [])]
    spec = InlineSpectrum(
        default_array_length=len(mz),
        mz=mz,
        intensity=intensity,
        id=data.get("id"),
        params=params,
    )
    token = encode_spectrum(spec, lossless=args.lossless, max_len=args.max_len)
    print(token)


def _decode_cmd(args: argparse.Namespace) -> None:
    from . import decode_token

    token = (sys.stdin.read() if args.input == "-" else open(args.input).read()).strip()
    decoded = decode_token(token)
    out: dict = {
        "id": decoded.id,
        "default_array_length": decoded.default_array_length,
        "mz": decoded.mz.tolist() if decoded.mz is not None else None,
        "intensity": decoded.intensity.tolist() if decoded.intensity is not None else None,
        "charge": decoded.charge.tolist() if decoded.charge is not None else None,
        "hash": decoded.hash,
        "interp": decoded.interp,
    }
    print(json.dumps(out, indent=2))


def _inspect_cmd(args: argparse.Namespace) -> None:
    import msgpack

    from .token import parse_token

    token = (sys.stdin.read() if args.input == "-" else open(args.input).read()).strip()
    header_bytes, blobs = parse_token(token)
    h = msgpack.unpackb(header_bytes, raw=False)
    print(f"Segments: 1 header + {len(blobs)} array(s)")
    print(f"Header size: {len(header_bytes)} bytes")
    for i, blob in enumerate(blobs):
        print(f"Array {i} size: {len(blob)} bytes")
    print("Header (decoded):")
    print(json.dumps(h, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(prog="mzx", description="mzx inline spectrum encoder/decoder")
    sub = parser.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encode", help="Encode a spectrum JSON to a mzx1 token")
    enc.add_argument("input", nargs="?", default="-", help="Input JSON file or '-' for stdin")
    enc.add_argument("--lossless", action="store_true", help="Use lossless IEEE-754 + zlib encoding")
    enc.add_argument("--max-len", type=int, default=None, help="Maximum token length in bytes")
    enc.set_defaults(func=_encode_cmd)

    dec = sub.add_parser("decode", help="Decode a mzx1 token to JSON")
    dec.add_argument("input", nargs="?", default="-", help="Token file or '-' for stdin")
    dec.set_defaults(func=_decode_cmd)

    ins = sub.add_parser("inspect", help="Inspect a mzx1 token header as readable JSON")
    ins.add_argument("input", nargs="?", default="-", help="Token file or '-' for stdin")
    ins.set_defaults(func=_inspect_cmd)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
