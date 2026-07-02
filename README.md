<div align="center">
  <img src="logo.png" alt="MZMLpy Logo" width="400" style="margin: 20px;"/>

  A lightweight Python library for parsing mzML mass spectrometry files. Implements a type-safe, lazy-loading API with direct support for modern mzML structures (>= 1.1.0).

  [![Python package](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml/badge.svg)](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml)
  [![codecov](https://codecov.io/github/tacular-omics/mzmlpy/graph/badge.svg?token=1CTVZVFXF7)](https://codecov.io/github/tacular-omics/mzmlpy)
  [![PyPI version](https://badge.fury.io/py/mzmlpy.svg)](https://badge.fury.io/py/mzmlpy)
  [![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-g.svg)](https://opensource.org/licenses/MIT)

</div>

## Installation

```bash
pip install mzmlpy
```

Optional extras:

```bash
pip install mzmlpy[numpress]   # MS-Numpress decoding
pip install mzmlpy[zstd]       # Zstandard compression
pip install mzmlpy[rapidgzip]  # Parallel gzip decompression (recommended for .gz files)
```

## Quick Start

```python
from mzmlpy import Mzml

with Mzml("path/to/file.mzML") as reader:
    print(f"File: {reader.file_name}  |  Spectra: {len(reader.spectra)}")

    for spectrum in reader.spectra:
        mz = spectrum.mz
        intensity = spectrum.intensity
        print(f"  {spectrum.id} MS{spectrum.ms_level} — {len(mz)} peaks")
```

Both `.mzML` and `.mzML.gz` files are supported. Metadata is parsed eagerly; binary data is decoded on demand.

## Reading Gzipped Files

When opening `.mzML.gz` files, the `gzip_mode` parameter controls how the file is accessed:

| Mode | Description |
|---|---|
| `"extract"` (default) | Decompress to `<tmpdir>/mzmlpy/` and cache across sessions. First open pays decompression cost; subsequent opens reuse the cache instantly. The OS clears tmp on reboot. |
| `"indexed"` | Seekable access to the compressed file using `rapidgzip`. No decompression to disk. Requires `pip install mzmlpy[rapidgzip]`. |
| `"stream"` | Stream sequentially. Lowest startup cost but no efficient random access. |

For most use cases, `"extract"` or `"indexed"` is recommended:

```python
# Default — extracts to tmp, cached across sessions
with Mzml("data.mzML.gz") as reader:
    spec = reader.spectra[0]

# Indexed — no extraction, seekable access (requires rapidgzip)
with Mzml("data.mzML.gz", gzip_mode="indexed") as reader:
    spec = reader.spectra[0]
```

To reclaim disk space before the OS clears tmp on reboot:

```python
from mzmlpy import clear_cache
clear_cache()
```

### Performance

`"extract"` pays a one-time decompression cost then matches plain `.mzML` speed on later opens
(the extracted copy is cached). `"indexed"` pays a one-time index-build cost for seekable access
with no disk copy. `"stream"` has the lowest startup cost but random access re-scans from the
start, so it's sequential-only in practice. See **[`benchmarks/`](benchmarks/)** for a
reproducible harness with real numbers on real files, including a head-to-head against
pyteomics and pymzml.

For full usage examples see the **[Getting Started guide](https://tacular-omics.github.io/mzmlpy/getting-started/)** and **[API Reference](https://tacular-omics.github.io/mzmlpy/api/mzml/)**.

Using an AI coding assistant? Point it at **[`llms.txt`](llms.txt)** — a compact, accurate API guide for generating correct mzmlpy code.


## Benchmarks

`benchmarks/` contains a reproducible harness comparing mzmlpy against
[pyteomics](https://github.com/levitsky/pyteomics) and [pymzml](https://github.com/pymzml/pymzML)
on compression-format support, throughput, and gzip handling. See
[`benchmarks/README.md`](benchmarks/README.md) for how to run it and current results.


## Development

```bash
just lint     # ruff check
just format   # ruff isort + format
just ty       # ty type checker
just test     # pytest

# or all at once:
just check
```
