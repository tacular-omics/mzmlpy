<div align="center">
  <img src="https://raw.githubusercontent.com/tacular-omics/mzmlpy/main/logo.png" alt="MZMLpy Logo" width="400" style="margin: 20px;"/>

  [![Python package](https://github.com/tacular-omics/mzmlpy/actions/workflows/ci.yml/badge.svg)](https://github.com/tacular-omics/mzmlpy/actions/workflows/ci.yml)
  [![codecov](https://codecov.io/github/tacular-omics/mzmlpy/graph/badge.svg?token=1CTVZVFXF7)](https://codecov.io/github/tacular-omics/mzmlpy)
  [![PyPI version](https://badge.fury.io/py/mzmlpy.svg)](https://badge.fury.io/py/mzmlpy)
  [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21960079.svg)](https://doi.org/10.5281/zenodo.21960079)
  [![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-g.svg)](https://opensource.org/licenses/MIT)

</div>

**mzmlpy** is a Python library for reading mzML mass spectrometry files. It's built for
people writing proteomics or metabolomics pipelines who need a reader that's fast on
large files, tells them exactly what's wrong with a malformed file, and doesn't force a
full decode just to look at a spectrum's metadata.

## Why mzmlpy?

- **Lazy by design** — metadata is parsed up front; binary m/z and intensity arrays are
  only decoded when you actually touch them.
- **Fast** — 5–9x faster than pymzml on complex files in our benchmarks (see below).
- **Type-safe** — dataclass-based models with full type annotations, not loosely-typed
  XML trees.
- **Handles gzip well** — reads `.mzML.gz` directly, with a self-indexed gzip format for
  random access without decompressing the whole file.
- **Common compressions** — zlib out of the box; zstd and MS-Numpress through optional
  extras.
- **Validates, not just parses** — a `validate()` function reports structural and
  decoding problems instead of silently producing bad data.

## Install

```bash
pip install mzmlpy
```

Optional extras:

```bash
pip install mzmlpy[numpress]   # MS-Numpress decoding
pip install mzmlpy[zstd]       # Zstandard compression
pip install mzmlpy[rapidgzip]  # Parallel gzip decompression (recommended for .gz files)
pip install mzmlpy[mcp]        # MCP server for AI coding assistants
```

## Quick example

```python
from mzmlpy import Mzml

with Mzml("path/to/file.mzML") as reader:
    print(f"File: {reader.file_name}  |  Spectra: {len(reader.spectra)}")

    for spectrum in reader.spectra:
        mz = spectrum.mz
        intensity = spectrum.intensity
        print(f"  {spectrum.id} MS{spectrum.ms_level} — {len(mz)} peaks")
```

Both `.mzML` and `.mzML.gz` files are supported. Metadata is parsed eagerly; binary data
is decoded on demand.

## What else it can do

```python
from mzmlpy import Mzml, validate

# Structural/decoding validation, no repair attempted
report = validate("data.mzML", decode_binary=True)
print(report.valid, report.issues)

# Filter by metadata without decoding any arrays
with Mzml("data.mzML") as reader:
    for spectrum in reader.spectra.filter(ms_level=2, rt_range=(60, 180)):
        print(spectrum.id)
```

Gzipped files get the same lazy, indexable access as plain mzML — `gzip_mode="auto"` uses an
embedded index, then rapidgzip if installed, then decompression into memory, and never writes
files next to yours. For fast re-opens, convert once with `write_indexed_gzip` (random access with
no extra files) or open once with `gzip_mode="indexed"` to save reusable sidecar indexes. Ion
mobility data (e.g. Bruker timsTOF PASEF) is exposed on the spectrum whether it's stored
as a binary array or a scan-level parameter.

| Feature | Notes |
|---|---|
| `.mzML` / `.mzML.gz` | Transparent gzip handling, including self-indexed files |
| Validation | `validate()` reports issues without altering the file |
| Filtering | By MS level, retention time, and precursor, without decoding arrays |
| Ion mobility | Detects both array-based and scan-level IM data |
| MCP server | `pip install mzmlpy[mcp]` — file discovery, metadata, and bounded array access for AI clients |
| CLI | `python -m mzmlpy` for validation and inspection from the shell |

See the **[Getting Started guide](https://tacular-omics.github.io/mzmlpy/getting-started/)**
and **[API Reference](https://tacular-omics.github.io/mzmlpy/api/mzml/)** for the full
picture, including gzip mode details, the CLI, and the MCP server.

Using an AI coding assistant? Point it at
**[`llms.txt`](https://github.com/tacular-omics/mzmlpy/blob/main/llms.txt)**, a short index of the
package and its docs, or at
**[`llms-full.txt`](https://github.com/tacular-omics/mzmlpy/blob/main/llms-full.txt)** for the full API
guide with signatures and examples.

## In the tacular-omics family

mzmlpy reads mzML; [tdfpy](https://github.com/tacular-omics/tdfpy) reads the Bruker
timsTOF `.d` format the same way. Both feed spectra into
[spxtacular](https://github.com/tacular-omics/spxtacular), the shared spectrum-processing
layer for deisotoping, deconvolution, and downstream analysis.

## Links

- **Docs**: https://tacular-omics.github.io/mzmlpy/
- **Changelog**: [`CHANGELOG.md`](https://github.com/tacular-omics/mzmlpy/blob/main/CHANGELOG.md)

## Citation

Citation metadata are provided in [`CITATION.cff`](CITATION.cff). All archived releases are
available from Zenodo at [doi:10.5281/zenodo.21960079](https://doi.org/10.5281/zenodo.21960079).

## Benchmarks

`benchmarks/` contains a reproducible harness comparing mzmlpy against
[pyteomics](https://github.com/levitsky/pyteomics) and [pymzml](https://github.com/pymzml/pymzML)
on compression-format support, throughput, and gzip handling.

Compared against pymzml 2.6.0 on a Bruker timsTOF file with ion mobility (10 spectra, 6.7 MB):

| Benchmark | mzmlpy | pymzml | Ratio |
|---|---|---|---|
| Startup | 0.012s | 0.092s | **8.0x faster** |
| Iterate (decode) | 0.039s | 0.228s | **5.8x faster** |
| Random access | 0.012s | 0.110s | **9.2x faster** |

Both libraries produce identical m/z and intensity arrays. The gap narrows on smaller
files (~1.1–1.3x) and widens on larger, more complex files. See
[`benchmarks/README.md`](https://github.com/tacular-omics/mzmlpy/blob/main/benchmarks/README.md)
for how to run it yourself, and the full results on the
**[Benchmarks page](https://tacular-omics.github.io/mzmlpy/benchmarks/)**.

## License

MIT — see [`LICENSE`](https://github.com/tacular-omics/mzmlpy/blob/main/LICENSE).
