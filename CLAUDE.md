# mzmlpy — Claude Code Guide

## Project overview

**mzmlpy** is a lightweight Python library (3.12+) for reading mzML mass spectrometry files.
It exposes a type-safe, lazy-loading API for spectra, chromatograms and file metadata, reads
`.mzML.gz` directly (extract, rapidgzip-indexed, streamed, or pyMZML-style self-indexed gzip),
validates file structure, and ships an optional local MCP server. The only runtime dependency is
`numpy`.

Place in the tacular-omics graph: tier 0, no sibling dependencies. `spxtacular` uses it through
its `mzml` and `readers` extras (`mzmlpy>=0.9.0,<0.10`), so a breaking change here must be checked
against spxtacular's readers. Spectrum processing (peak picking, deconvolution, plotting) belongs
in spxtacular, never here.

- Repo: https://github.com/tacular-omics/mzmlpy
- Docs: https://tacular-omics.github.io/mzmlpy/ (MkDocs, deployed by `.github/workflows/docs.yml`)
- Version source: `__version__` in `src/mzmlpy/__init__.py` (`[tool.hatch.version]`; pyproject
  `version` is dynamic)

## Commands

```bash
just install        # uv sync --locked
just lint           # ruff check src tests
just format         # ruff isort fix + ruff format (src, tests)
just ty             # ty check src (excludes decoder.py, file_classes/indexedGzip.py, util.py via [tool.ty.src] in pyproject)
just test [ARGS]    # pytest tests, extra args passed through (e.g. just test -q -k gzip)
just test-cov       # pytest with branch coverage (term + html + xml) and junit.xml in one run
just check          # lint + ty + test (the default recipe; does NOT format)
just docs           # mkdocs serve on localhost:8001
just docs-build     # mkdocs build --strict to site/
just upgrade        # pyupgrade --py312-plus over src and tests
just set-version X  # release helper (overseer only), see Releasing
```

Always run `just lint`, `just ty` and `just test` after a code change. The full suite runs in
about 10 seconds.

CLI (`src/mzmlpy/__main__.py`, JSON on stdout; exit 0 ok, 1 invalid data, 2 operational error):

```bash
uv run python -m mzmlpy inspect FILE                                   # id, version, access strategy, counts
uv run python -m mzmlpy validate FILE [--decode-binary] [--check-index]
uv run python -m mzmlpy index-gzip FILE OUTPUT                         # write a self-indexed .mzML.gz
uv run python -m mzmlpy mcp --root DIR [--output-dir DIR]              # stdio MCP server, needs the mcp extra
```

MCP protocol tests need the SDK: `uv sync --locked --extra mcp` then `UV_NO_SYNC=1 just check`
(the `dev` group already includes `mcp`, so a plain dev sync also works).

## Architecture

```
src/mzmlpy/
├── __init__.py             # public API re-exports + __version__
├── __main__.py             # python -m mzmlpy: inspect / validate / index-gzip / mcp
├── run.py                  # Mzml reader (context manager, eager header metadata, lazy records) + peek_spectrum_count
├── file_interface.py       # FileInterface + AccessStrategy: picks a file_classes backend, exposes ids/counts
├── lookup.py               # BaseLookup -> SpectrumLookup / ChromatogramLookup: index, id, slice, iter, filter
├── spectra.py              # Spectrum, Chromatogram, BinaryDataArray, Scan, Precursor, ... + the mixins
├── filtering.py            # SpectrumFilter: metadata-only predicates (never decodes arrays)
├── validation.py           # validate(), ValidationIssue, ValidationReport (streaming structural checks)
├── embedded_indexed_gzip.py# read/write pyMZML-compatible self-indexed gzip (write_indexed_gzip, index_gzip alias)
├── decoder.py              # MSDecoder: zlib / zstd / MS-Numpress decoding (excluded from ty)
├── constants.py            # all CV accessions as StrEnums + ION_MOBILITIES
├── content.py              # CVElement, _MzMLContentBuilder (header parsing)
├── util.py                 # gzip helpers, atomic cache writes, cache signatures, clear_cache (excluded from ty)
├── _xml.py                 # streaming record / fragment / header helpers shared by backends
├── regex_patterns.py       # byte regexes for encoding and index sniffing
├── _progress.py            # internal cooperative checkpoints (used by validation and MCP jobs)
├── mcp.py                  # MzmlTools (reader-backed tool logic) + create_server()
├── _mcp_server.py          # MCP SDK adapter, imported only by create_server
├── _mcp_metadata.py, _mcp_types.py, _mcp_runtime.py, _mcp_export.py
│                           # inventories, TypedDict schemas, jobs/result cache, JSONL exports
├── elems/                  # metadata wrappers: FileDescription, InstrumentConfiguration, Run, Sample,
│                           # Software, DataProcessing, ScanSetting, params (CvParam/UserParam), dtree_wrapper
├── file_classes/
│   ├── interface.py        # MzmlInterface protocol every backend implements
│   ├── standardMzml.py     # AbstractRandomAccessMzml, StandardMzml (plain file), BytesMzml (in memory)
│   ├── indexedGzip.py      # IndexedGzip: rapidgzip seekable access (excluded from ty)
│   ├── embeddedIndexedGzip.py # EmbeddedIndexedGzip: self-indexed gzip written by write_indexed_gzip
│   ├── standardGzip.py     # StandardGzip: sequential streaming of .gz
│   └── xml_tuple.py        # typed spectrum / chromatogram element container
└── py.typed
```

Data flow: `Mzml(path)` sniffs encoding, `FileInterface` selects a backend (reported as
`reader.access_strategy`: `memory`, `plain`, `embedded`, `extracted`, `rapidgzip`, `stream`),
header metadata is parsed eagerly, and `reader.spectra[...]` fetches one XML record through the
backend and wraps it in a `Spectrum`. Properties parse CV params on access; binary arrays decode on
every access.

### Key design patterns

- **Frozen dataclasses**: data classes use `@dataclass(frozen=True)`; computed values use `cached_property`.
- **Mixin composition**: `Spectrum` combines `_BinaryDataArrayMixin`, `_ScanListMixin`,
  `_PrecursorListMixin`, `_ProductListMixin`; never duplicate logic across them.
- **Lazy binary decoding**: `BinaryDataArray.data` (and so `spectrum.mz`) decodes on every call, not cached.
- **XML namespaced lookups**: every `element.find()` uses the `self.ns` prefix (e.g. `f"./{self.ns}scanList"`).
- **Warnings over exceptions** for ambiguous multi-scan/multi-window cases (e.g. `rt` or `mz_range` with several scans).
- **ID regex mapping**: `SpectrumLookup`/`ChromatogramLookup` take `id_regex` and lazily build a
  secondary `{extracted -> full_id}` map; passed via `Mzml(spectrum_id_regex=..., chromatogram_id_regex=...)`.
- **MzmlInterface protocol**: `file_classes/interface.py` is the contract; `FileInterface` delegates to the active backend.

## Public API

Everything below is in `mzmlpy.__all__` (checked by importing it):

- **Reader**: `Mzml`, `peek_spectrum_count`, `AccessStrategy`, `SpectrumLookup`, `ChromatogramLookup`, `clear_cache`.
- **Records**: `Spectrum`, `Chromatogram`, `BinaryDataArray`, `Scan`, `ScanWindow`, `Precursor`,
  `Product`, `IsolationWindow`, `SelectedIon`, `Activation`.
- **Header metadata**: `FileDescription`, `FileContent`, `SourceFile`, `Contact`,
  `InstrumentConfiguration`, `SourceComponent`, `AnalyzerComponent`, `DetectorComponent`,
  `Software`, `Sample`, `Run`, `DataProcessing`, `ProcessingMethod`, `ScanSetting`, `Target`,
  `SourceFileRef`, `ReferenceableParamGroup`, `ReferenceableParamGroupRef`, `CvParam`, `UserParam`, `CVElement`.
- **Selection and validation**: `SpectrumFilter`, `validate`, `ValidationReport`, `ValidationIssue`.
- **Errors** (`errors.py`): `MzmlError(ValueError)`, `MzmlParseError`, `MzmlOffsetIndexError`,
  `MzmlDecodeError`, `MzmlRecordNotFoundError(MzmlError, KeyError)`. Raise these, not bare `ValueError`/`KeyError`.
- **Accession enums used in return types**: `BinaryDataArrayAccession`, `BinaryDataTypeAccession`,
  `ChromatogramTypeAccession`, `CollisionDissociationTypeAccession`, `CompressionTypeAccession`,
  `DIAAcquisitionAccession`, `SpectrumCombinationAccession`.
- **Self-indexed gzip**: `write_indexed_gzip` (alias `index_gzip`), `is_embedded_indexed_gzip`, `IndexedGzipWriteResult`.
- **Not in `__all__`**: the rest of `mzmlpy.constants` (CV accession StrEnums), `mzmlpy.mcp.create_server` / `MzmlTools`.

Full signatures and examples: `llms-full.txt`.

## Conventions

- Line length 120. Python 3.12+ syntax (`X | None`, PEP 695 generics, `StrEnum`).
- Type annotations on all public API; `just ty` must pass clean.
- Google-style docstrings. mkdocstrings uses `filters: ["!^_"]` (hides private members),
  `inherited_members: true` (mixin members appear on class pages), `merge_init_into_class: true`.
- `StrEnum` for all CV accessions: never hardcode an accession string outside `constants.py`.
- `Literal[...]` return types for known-set values (`polarity`, `spectrum_type`, `chromatogram_type`).
- Absent CV terms return `None` (or `[]` for lists); ambiguous cases warn and return the first value.
- Runtime deps: `numpy>=1.26.0` only. Extras: `numpress` (`pynumpress>=0.1.5`), `zstd`,
  `rapidgzip` (for `gzip_mode="indexed"`), `mcp` (`mcp>=2.1.1,<3`). Extras import lazily; the
  base install must work without them.
- Tests: `tests/`, one file per feature area. No mocking: tests run against real XML in
  `tests/data/` (`example.mzML` and `example.mzML.gz`: 4 spectra, 2 chromatograms; plus Thermo,
  Bruker and re-encoded zlib/zstd/numpress files). Many tests are parametrized over both example
  files. `tests/test_docs.py` (pytest-examples) executes every Python block in
  `docs/getting-started.md`, so doc examples must run.
- `benchmarks/`: harness comparing mzmlpy with pyteomics/pymzml; results in `benchmarks/README.md`.

### Validation and selection

- `validate(path)` does structural checks by default; `decode_binary=True` and `check_index=True`
  enable the expensive checks explicitly. `reader.validate(...)` uses a fresh handle and does not
  disturb open iterators.
- `reader.spectra.filter(...)` / `SpectrumFilter` return a lazy iterator and never request binary
  arrays. Retention-time bounds are in seconds, inclusive, with `None` for an open end.

### Numeric decoding

- Preserve the declared dtype for raw numeric arrays, including empty arrays and dictionary tables.
- Numpress reconstructs float64. Do not add a narrowing cast based on the array declaration.
- Public decoded arrays stay writable. Callers convert explicitly with `.astype(np.float64)`.
- MCP preserves exact integers, sending values outside the JSON safe range as decimal strings.
- Cover numeric changes with `tests/test_native_precision.py` and the predictive-codec regressions.

### Optional MCP server

- `mcp.py` adapts the reader API for data access; `_mcp_server.py` owns SDK integration and is
  imported only by `create_server`, never by the core package.
- Scope is discovery, metadata, validation, selection and export. Do not add peak processing,
  derived traces or plotting here (that is spxtacular's job).
- `tests/test_mcp_protocol.py` checks current and legacy clients and the stdio subprocess.
- User-facing details (19 tools, resources, limits): `docs/mcp.md`.

## Gotchas

- **Decoding is not cached.** `spectrum.mz` decodes again on every access; store it in a variable.
- **Not thread-safe.** A reader shares one file handle; use one `Mzml` per thread.
- **`gzip_mode` only matters with `in_memory=False`.** The default `in_memory=True` buffers the
  whole (decompressed) file, so `reader.access_strategy` is `memory` for every mode.
- **`gzip_mode="indexed"` writes sidecars next to the source** (`X.mzML.gzidx`, `X.mzMLidx` and
  their `.src` signature files), so the source directory must be writable. Running the tests
  would create these next to `tests/data/` files, so `tests/test_docs.py` runs the doc examples
  against a copy in `tmp_path`; the sidecars and their `.src` files are gitignored.
- **`gzip_mode="stream"` random access rescans the file** from the start each time and warns. Use
  `extract`, `indexed` or a self-indexed gzip for random access.
- **Cache currency uses source signatures** (`util.source_signature`: realpath, size, mtime_ns,
  ctime_ns) and atomic writes. Do not go back to plain mtime checks: a truncated cache with a fresh
  mtime was trusted forever before this.
- **`ty` excludes three files** (`decoder.py`, `file_classes/indexedGzip.py`, `util.py`) in
  `[tool.ty.src]`; the workspace's newer `ty` may still report diagnostics the package CI does not.

## Releasing

Only the tacular-omics overseer bumps versions or publishes. See `RELEASING.md` and `just --list`
(`set-version`, `sync-version`, `check-version`, backed by `scripts/release_version.py`). The
version lives only in `src/mzmlpy/__init__.py` (`__version__`); `CITATION.cff` is synced from it.
Changelog: `CHANGELOG.md`, Keep-a-Changelog format with an `[Unreleased]` section. Publishing is a
GitHub release `vX.Y.Z`, which triggers `.github/workflows/publish.yml` (PyPI trusted publishing)
and Zenodo.

## Workspace note

This repo is also developed inside the tacular-omics uv workspace
(`~/Repos/tacular-omics/packages/mzmlpy`); there `uv run` uses the shared `.venv` and the root
`uv.lock`, not this repo's. See the workspace CLAUDE.md.
