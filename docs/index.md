# mzmlpy

[![CI](https://github.com/tacular-omics/mzmlpy/actions/workflows/ci.yml/badge.svg)](https://github.com/tacular-omics/mzmlpy/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/tacular-omics/mzmlpy/graph/badge.svg?token=1CTVZVFXF7)](https://codecov.io/github/tacular-omics/mzmlpy)
[![PyPI version](https://badge.fury.io/py/mzmlpy.svg)](https://badge.fury.io/py/mzmlpy)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21960079.svg)](https://doi.org/10.5281/zenodo.21960079)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-g.svg)](https://opensource.org/licenses/MIT)

mzmlpy is a lightweight, type-safe Python library for reading mzML mass spectrometry files,
including gzipped `.mzML.gz`. Metadata is parsed into typed models, while m/z, intensity, ion
mobility and other binary arrays are decoded only when you ask for them.

Spectra and chromatograms can be iterated, indexed, sliced, looked up by native ID, or filtered
on metadata without decoding peaks. zlib, MS-Numpress and Zstandard arrays are supported, and
mzmlpy opens and indexes files [about 20x faster than pyteomics](benchmarks.md), with full
decoding on par with pyteomics and pymzml. An optional
[MCP server](mcp.md) lets AI clients inspect local mzML files.

```bash
pip install mzmlpy
```

## Where next

- [Getting started](getting-started.md): install options, reading spectra, gzip modes, validation.
- [MCP server](mcp.md): connect an AI client to local mzML files.
- [API reference](api/mzml.md): every public class and function.
- Using an AI coding assistant? Point it at
  [`llms.txt`](https://github.com/tacular-omics/mzmlpy/blob/main/llms.txt) for a short index, or
  [`llms-full.txt`](https://github.com/tacular-omics/mzmlpy/blob/main/llms-full.txt) for the full API guide.

## Related packages

The tacular-omics mass spectrometry stack:

- [tdfpy](https://tacular-omics.github.io/tdfpy/) reads Bruker timsTOF `.d` data.
- **[mzmlpy](https://tacular-omics.github.io/mzmlpy/) reads mzML files.** (this package)
- [spxtacular](https://tacular-omics.github.io/spxtacular/) processes the spectra from both: centroiding, deconvolution, matching, scoring and plotting.
