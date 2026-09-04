"""Inspect, validate, or index mzML files with python -m mzmlpy."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from . import Mzml, validate, write_indexed_gzip


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, returning 0 for success, 1 for invalid data, or 2 for an operational error."""
    parser = argparse.ArgumentParser(prog="python -m mzmlpy")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Summarize file metadata and record counts as JSON")
    inspect.add_argument("file")
    validation = commands.add_parser("validate", help="Report structural problems as JSON")
    validation.add_argument("file")
    validation.add_argument("--decode-binary", action="store_true", help="Decode arrays and verify their lengths")
    validation.add_argument("--check-index", action="store_true", help="Verify XML footer offset targets")
    index = commands.add_parser("index-gzip", help="Create a self-indexed gzip file")
    index.add_argument("file")
    index.add_argument("output")
    mcp = commands.add_parser("mcp", help="Serve local read-only MCP tools (requires the mcp extra)")
    mcp.add_argument("--root", required=True, help="Existing directory containing permitted mzML files")
    args = parser.parse_args(argv)
    try:
        if args.command == "mcp":
            from .mcp import create_server

            create_server(args.root).run(transport="stdio")
            return 0
        if args.command == "validate":
            report = validate(args.file, decode_binary=args.decode_binary, check_index=args.check_index)
            print(json.dumps(report.to_dict(), indent=2))
            return 0 if report.valid else 1
        if args.command == "inspect":
            with Mzml(args.file, in_memory=False, gzip_mode="stream") as reader:
                result = {
                    "file": reader.file_name,
                    "id": reader.id,
                    "version": reader.version,
                    "access_strategy": reader.access_strategy,
                    "spectrum_count": len(reader.spectra),
                    "chromatogram_count": len(reader.chromatograms),
                }
        else:
            result = asdict(write_indexed_gzip(args.file, args.output))
            result["output_path"] = str(result["output_path"])
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:
        print(f"{parser.prog}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
