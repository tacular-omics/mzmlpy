"""Exercise installed artifacts independently of pytest and optional codecs."""

import argparse
import gzip
import importlib.util
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

import mzmlpy
from mzmlpy import Mzml, validate, write_indexed_gzip


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-only", action="store_true")
    parser.add_argument("--require-wheel", action="store_true")
    args = parser.parse_args()
    if args.base_only:
        assert all(importlib.util.find_spec(name) is None for name in ("rapidgzip", "zstd", "pynumpress", "mcp"))
    if args.require_wheel:
        assert "site-packages" in Path(mzmlpy.__file__).parts
        assert Path(mzmlpy.__file__).with_name("py.typed").exists()
    assert "mcp" not in sys.modules
    source = Path(__file__).parent / "data" / "example.mzML"
    if args.base_only:
        result = subprocess.run(
            [sys.executable, "-m", "mzmlpy", "mcp", "--root", str(source.parent)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 2
        assert 'pip install "mzmlpy[mcp]"' in result.stderr
    with TemporaryDirectory() as directory:
        output = Path(directory) / "indexed.mzML.gz"
        result = write_indexed_gzip(source, output)
        assert result.spectrum_count == 4
        with gzip.open(output, "rb") as handle:
            assert handle.read() == source.read_bytes()
        with Mzml(output, in_memory=False) as indexed, Mzml(source, in_memory=False) as plain:
            assert len(indexed.spectra) == len(plain.spectra) == 4
            for position in range(4):
                np.testing.assert_array_equal(indexed.spectra[position].mz, plain.spectra[position].mz)
            assert [s.id for s in indexed.spectra.filter(ms_level=1)] == [
                s.id for s in plain.spectra if s.ms_level == 1
            ]
        assert validate(output).complete


if __name__ == "__main__":
    main()
