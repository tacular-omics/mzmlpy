<div align="center">
  <img src="https://raw.githubusercontent.com/tacular-omics/mzmlpy/main/logo.png" alt="MZMLpy Logo" width="400" style="margin: 20px;"/>

  A lightweight Python library for parsing mzML mass spectrometry files. Implements a type-safe, lazy-loading API with direct support for modern mzML structures (>= 1.1.0).

  [![Python package](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml/badge.svg)](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml)
  [![codecov](https://codecov.io/github/tacular-omics/mzmlpy/graph/badge.svg?token=1CTVZVFXF7)](https://codecov.io/github/tacular-omics/mzmlpy)
  [![PyPI version](https://badge.fury.io/py/mzmlpy.svg)](https://badge.fury.io/py/mzmlpy)
  [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21960079.svg)](https://doi.org/10.5281/zenodo.21960079)
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

`"auto"` is the default. It selects an embedded index first, then a current extracted cache,
then complete rapidgzip sidecars, and finally creates an extracted cache. The selected route is
available through `reader.access_strategy`.

Self-indexed gzip files created by `write_indexed_gzip` are detected automatically when
`in_memory=False`. Their index lives inside the gzip header, so random access needs no extracted
copy, sidecar index, or optional dependency.

```python
from mzmlpy import Mzml, write_indexed_gzip

write_indexed_gzip("data.mzML", "data.indexed.mzML.gz")

with Mzml("data.indexed.mzML.gz", in_memory=False) as reader:
    spec = reader.spectra["controllerType=0 controllerNumber=1 scan=1234"]
```

The writer also accepts an ordinary `.mzML.gz` input. It preserves the decompressed mzML bytes
exactly and writes the destination atomically. The embedded layout is compatible with pyMZML's
`FU` version 1 indexed gzip reader.

| Mode | Description |
|---|---|
| `"auto"` (default) | Reuse the fastest valid representation already available, otherwise extract into the central cache. |
| `"extract"` | Decompress to `<tmpdir>/mzmlpy/` and cache across sessions. First open pays decompression cost. Subsequent opens reuse the cache instantly. The OS clears tmp on reboot. |
| `"indexed"` | Seekable access to the compressed file using `rapidgzip`. No decompression to disk. Requires `pip install mzmlpy[rapidgzip]`. |
| `"stream"` | Stream sequentially. Lowest startup cost but no efficient random access. |

For most use cases, `"extract"` or `"indexed"` is recommended:

```python
# Automatic selection with observable behavior
with Mzml("data.mzML.gz", in_memory=False) as reader:
    print(reader.access_strategy)
    spec = reader.spectra[0]

# Indexed — no extraction, seekable access (requires rapidgzip)
with Mzml("data.mzML.gz", gzip_mode="indexed", in_memory=False) as reader:
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

### mzmlpy vs pymzml

Compared against pymzml 2.6.0 on a Bruker timsTOF file with ion mobility (10 spectra, 6.7 MB):

| Benchmark | mzmlpy | pymzml | Ratio |
|---|---|---|---|
| Startup | 0.012s | 0.092s | **8.0x faster** |
| Iterate (decode) | 0.039s | 0.228s | **5.8x faster** |
| Random access | 0.012s | 0.110s | **9.2x faster** |

Both libraries produce identical m/z and intensity arrays. The gap narrows on smaller files (~1.1--1.3x) and widens on larger, more complex files. See the full results in the **[Benchmarks](https://tacular-omics.github.io/mzmlpy/benchmarks/)** page or run `benchmarks/bench_vs_pymzml.py` yourself.

For full usage examples see the **[Getting Started guide](https://tacular-omics.github.io/mzmlpy/getting-started/)** and **[API Reference](https://tacular-omics.github.io/mzmlpy/api/mzml/)**.

Using an AI coding assistant? Point it at **[`llms.txt`](llms.txt)** — a compact, accurate API guide for generating correct mzmlpy code.

## Validation and filtering

```python
from mzmlpy import Mzml, validate

report = validate("data.mzML", decode_binary=True)
print(report.valid, report.issues)

with Mzml("data.mzML", in_memory=False) as reader:
    for spectrum in reader.spectra.filter(ms_level=2, retention_time=(60, 180)):
        print(spectrum.id)
```

Validation reports structural and decoding problems without repairing the input. Filtering
uses metadata and inclusive retention-time bounds in seconds, without decoding arrays.
See the [guide](https://tacular-omics.github.io/mzmlpy/getting-started/) for check scope,
precursor filters, cache behavior, and `python -m mzmlpy` CLI commands.

## Citation

Citation metadata are provided in [`CITATION.cff`](CITATION.cff). The archived v0.6.0 release is
available from Zenodo at [doi:10.5281/zenodo.21960080](https://doi.org/10.5281/zenodo.21960080).


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
