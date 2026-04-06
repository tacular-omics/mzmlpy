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

Benchmarked on a real-world DDA file (33,535 spectra, first-open cold start, with rapidgzip):

| Mode | Startup | Iterate (500 spectra) | Random access (5 reads) |
|---|---|---|---|
| plain `.mzML` | 0.042s | 0.087s | 0.001s |
| `in_memory=True` | 1.499s | 0.362s | 0.002s |
| `gzip_mode="extract"` | 0.957s | 0.083s | 0.001s |
| `gzip_mode="indexed"` ¹ | 6.850s | 0.135s | 0.074s |
| `gzip_mode="stream"` | 0.089s | 0.155s | 22.8s |

¹ `"indexed"` startup includes building the gzip seek index and mzML offset index on first open — both are cached alongside the file, so subsequent opens are fast.

`"extract"` pays a one-time decompression cost (~1s for a large file) then matches plain `.mzML` speed. `"stream"` is sequential-only — random access requires re-scanning from the start.

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
