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
| `"extract"` (default) | Decompress to a cached temp file, then use random access. Fast on repeated opens. |
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

Extracted files are cached in a temporary directory. To clear the cache:

```python
from mzmlpy import clear_cache
clear_cache()
```

For full usage examples see the **[Getting Started guide](https://tacular-omics.github.io/mzmlpy/getting-started/)** and **[API Reference](https://tacular-omics.github.io/mzmlpy/api/mzml/)**.

## Development

```bash
just lint     # ruff check
just format   # ruff isort + format
just ty       # ty type checker
just test     # pytest

# or all at once:
just check
```
