# mzmlpy

A lightweight Python library for parsing mzML mass spectrometry files. Initially built from pymzml, it implements a more straightforward, type-safe API and includes direct support for modern mzML structures (> 1.1.0).

[![Python package](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml/badge.svg)](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml)
[![codecov](https://codecov.io/github/tacular-omics/mzmlpy/graph/badge.svg?token=1CTVZVFXF7)](https://codecov.io/github/tacular-omics/mzmlpy)
[![PyPI version](https://badge.fury.io/py/mzmlpy.svg)](https://badge.fury.io/py/mzmlpy)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-g.svg)](https://opensource.org/licenses/MIT)

## Installation

```bash
pip install mzmlpy
```

## Quick Start

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML.gz") as reader:
    print(f"File ID: {reader.id}")
    print(f"Total Spectra: {len(reader.spectra)}")

    for spectrum in reader.spectra:
        print(f"Scan {spectrum.id} (MS{spectrum.ms_level}) - TIC: {spectrum.TIC}")
```

The `Mzml` reader lazily loads data, meaning binary arrays and metadata are only parsed when you access them. It supports `.mzML` and `.mzML.gz` files, and exposes spectra and chromatograms via lookup objects that support iteration, integer indexing, slicing, and string-based ID lookup.

## Features

- **Lazy parsing** -- binary data is decoded only when accessed.
- **Type-safe API** -- dataclass-based models with full type annotations.
- **Flexible access** -- look up spectra and chromatograms by index, slice, or string ID.
- **Ion mobility support** -- detect and retrieve IM binary arrays.
- **Comprehensive compression** -- zlib, zstd, and MS-Numpress decoders built in.
- **Context manager** -- use `with` for safe file handling.

## Next Steps

- [Getting Started](getting-started.md) -- installation details, basic usage patterns, and working with binary data.
- [API Reference](api/mzml.md) -- full auto-generated documentation for every public class and method.
