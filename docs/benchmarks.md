# Benchmarks

## mzmlpy vs pymzml

Comparison of **mzmlpy** and **pymzml 2.6.0** across common mzML parsing operations.
Both libraries use default settings: pymzml with `build_index_from_scratch=False` and `skip_chromatogram=True`; mzmlpy with default constructor arguments.
A warmup phase primes both libraries before timing so that one-time costs (OBO ontology loading, OS page cache) don't skew results.

### Methodology

Each benchmark is run 10 times. The table shows **mean ± standard deviation**.
Both libraries are verified to produce identical m/z and intensity arrays before timing begins.

- **Startup** — open the file and build the spectrum index.
- **Iterate (no decode)** — iterate all spectra, accessing only `id` and `ms_level`.
- **Iterate (decode)** — iterate all spectra, decoding m/z and intensity arrays.
- **Metadata** — iterate all spectra, accessing scan time, TIC, and precursor info.
- **Random access** — seek to 10 random spectra by index/ID and decode arrays.

### zlib-compressed DDA file (10 spectra, 527 KB)

| Benchmark | mzmlpy | pymzml | Ratio |
|---|---|---|---|
| Startup | 0.0017s | 0.0021s | **1.2x faster** |
| Iterate (no decode) | 0.0059s | 0.0074s | **1.3x faster** |
| Iterate (decode) | 0.0071s | 0.0087s | **1.2x faster** |
| Metadata | 0.0069s | 0.0077s | **1.1x faster** |
| Random access | 0.0047s | 0.0053s | **1.1x faster** |

### Bruker timsTOF file with ion mobility (10 spectra, 6.7 MB)

| Benchmark | mzmlpy | pymzml | Ratio |
|---|---|---|---|
| Startup | 0.012s | 0.092s | **8.0x faster** |
| Iterate (no decode) | 0.040s | 0.221s | **5.5x faster** |
| Iterate (decode) | 0.039s | 0.228s | **5.8x faster** |
| Metadata | 0.042s | 0.226s | **5.4x faster** |
| Random access | 0.012s | 0.110s | **9.2x faster** |

The gap widens on larger, more complex files. The Bruker file contains ion mobility data and richer XML metadata, where mzmlpy's parser is 5--9x faster.

### Running the benchmark

```bash
pip install pymzml  # required dependency for comparison

# Default file
uv run python benchmarks/bench_vs_pymzml.py

# Custom file with more repeats
uv run python benchmarks/bench_vs_pymzml.py --file path/to/file.mzML --repeats 10
```

See `benchmarks/bench_vs_pymzml.py` for the full source.

## Gzip mode comparison

For `.mzML.gz` files, the `gzip_mode` parameter controls how the compressed file is accessed.
Benchmarked on a 33,535-spectrum DDA file (cold start, with rapidgzip):

| Mode | Startup | Iterate (500 spectra) | Random access (5 reads) |
|---|---|---|---|
| plain `.mzML` | 0.042s | 0.087s | 0.001s |
| `in_memory=True` | 1.499s | 0.362s | 0.002s |
| `gzip_mode="extract"` | 0.957s | 0.083s | 0.001s |
| `gzip_mode="indexed"` | 6.850s | 0.135s | 0.074s |
| `gzip_mode="stream"` | 0.089s | 0.155s | 22.8s |

`"extract"` pays a one-time decompression cost then matches plain `.mzML` speed.
`"indexed"` startup includes building the gzip seek index and mzML offset index on first open — both are cached alongside the file, so subsequent opens are fast.
`"stream"` is sequential-only — random access requires re-scanning from the start.

See `benchmarks/bench_gzip_modes.py` for the full source.
