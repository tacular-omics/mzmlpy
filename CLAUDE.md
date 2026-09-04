# CLAUDE.md

## Project

**mzmlpy** — lightweight Python library for parsing mzML mass spectrometry files. Exposes a type-safe, lazy-loading API for spectra, chromatograms, and file metadata. Python 3.12+ only.

Current version: **0.8.0** (Beta).

## Commands

```bash
just lint        # ruff check src + tests
just format      # ruff isort + format src + tests
just ty          # ty type checker (excludes src/mzmlpy/decoder.py, src/mzmlpy/file_classes/indexedGzip.py, src/mzmlpy/util.py)
just check       # lint + ty + test
just test        # pytest tests/
just test-cov    # pytest with coverage report
just docs        # mkdocs serve on localhost:8001
just docs-build  # mkdocs build to site/
just install     # uv sync
```

Always run `just lint`, `just ty`, and `just test` after any code change.

## Architecture

```
src/mzmlpy/
├── run.py              # Mzml — main reader class, context manager, lazy XML parsing
├── spectra.py          # Spectrum, Chromatogram, and all mixin/helper classes
├── constants.py        # All StrEnum accessions + ION_MOBILITIES constant set
├── decoder.py          # MSDecoder — zlib/zstd/numpress decompression (excluded from ty)
├── lookup.py           # SpectrumLookup, ChromatogramLookup — index/id/slice access
├── file_interface.py   # FileInterface — routes to file_classes, exposes spectrum_ids etc.
├── content.py          # CVElement, MzMLContentBuilder
├── elems/              # Metadata dataclasses (FileDescription, InstrumentConfiguration, etc.)
├── file_classes/
│   ├── standardMzml.py # AbstractRandomAccessMzml, StandardMzml, BytesMzml
│   ├── standardGzip.py # StandardGzip — streaming reader for non-extracted .gz files
│   ├── interface.py    # MzmlInterface protocol
│   └── xml_tuple.py    # SpectrumElement, ChromatogramElement typed wrappers
└── py.typed            # PEP 561 marker
```

### Key design patterns

- **Frozen dataclasses** — all data classes use `@dataclass(frozen=True)`; use `cached_property` for computed values
- **Mixin composition** — `Spectrum` inherits from `_BinaryDataArrayMixin`, `_ScanListMixin`, `_PrecursorListMixin`, `_ProductListMixin`; never duplicate logic across these
- **Lazy binary decoding** — `BinaryDataArray.data` decodes on every call (not cached); callers should store result if reusing
- **XML namespaced lookups** — all `element.find()` calls use `self.ns` prefix (e.g. `f"./{self.ns}scanList"`)
- **Warnings over exceptions** for ambiguous multi-scan/multi-window cases (e.g. `lower_mz` on a spectrum with multiple scans)
- **ID regex mapping** — `SpectrumLookup`/`ChromatogramLookup` accept `id_regex` to build a secondary `{extracted → full_id}` map lazily from the already-parsed file index; passed via `Mzml(spectrum_id_regex=..., chromatogram_id_regex=...)`
- **MzmlInterface protocol** — `file_classes/interface.py` defines the contract; `StandardMzml`, `BytesMzml`, and `StandardGzip` all implement it; `FileInterface` delegates to whichever is active

## Dependencies

- **Runtime:** `numpy>=1.26.0` only
- **Optional:** `pynumpress>=0.0.4` (`pip install mzmlpy[numpress]`), `zstd>=1.5.5` (`pip install mzmlpy[zstd]`),
  `rapidgzip>=0.14.0` (`pip install mzmlpy[rapidgzip]`, used by `gzip_mode="indexed"`)
- **Dev:** pytest, pytest-cov, pytest-examples, ruff, ty, pyupgrade, zstd, mkdocs, mkdocs-material, mkdocstrings[python]
- **Build:** uv + hatchling

## Code style

- Line length: 120
- Type annotations required on all public API; `just ty` must pass clean
- Google-style docstrings; `filters: ["!^_"]` in mkdocs hides private members automatically
- `StrEnum` for all CV accession constants — never hardcode accession strings outside `constants.py`
- `Literal[...]` return types preferred over plain `str` for known-set values (e.g. `polarity`, `spectrum_type`)

## Docs

MkDocs + Material theme + mkdocstrings. Deployed to GitHub Pages via `mkdocs gh-deploy` on push to `main`. Config in `mkdocs.yml`:
- `inherited_members: true` — flattens mixin members onto class pages
- `merge_init_into_class: true` — merges `__init__` args into class docstring
- `filters: ["!^_"]` — hides private/dunder members
- `signature_crossrefs: true` — type annotations link to their doc pages

## Tests

Test data: `tests/data/example.mzML` and `tests/data/example.mzML.gz` (4 spectra, 2 chromatograms),
plus real Thermo/Bruker/re-encoded files under `tests/data/` for format and edge-case coverage.
Tests are parametrized over both example files. No mocking — tests run against real XML.
`tests/test_docs.py` uses `pytest-examples` to execute every Python code block in `docs/getting-started.md`.

## Other resources

- `benchmarks/` — reproducible harness comparing mzmlpy against pyteomics/pymzml (format support,
  throughput, gzip handling); see `benchmarks/README.md` for current results.
- `llms.txt` — compact, verified API guide for AI coding assistants.
- `CHANGELOG.md` — Keep-a-Changelog format, updated per release.

## Validation and selection

- `validation.py` provides `validate(path)` and typed reports. Structural checks are the default.
- `decode_binary=True` and `check_index=True` enable expensive checks explicitly.
- `filtering.py` provides `SpectrumFilter`. `reader.spectra.filter(...)` returns a lazy iterator.
- Retention-time bounds use seconds. Filtering never requests binary arrays.
- `_xml.py` contains streaming record and fragment helpers shared across backends.
- `just test` accepts extra pytest arguments. `just test-cov` emits coverage and JUnit in one run.
- `just docs-build` builds documentation in strict mode.

## Optional MCP server

- `mcp.py` adapts the public reader API into five local read-only tools.
- The SDK is imported only by `create_server`, not by the core package.
- Run `uv sync --locked --extra mcp` and `UV_NO_SYNC=1 just check` for protocol tests.
- `tests/test_mcp_protocol.py` checks current and legacy clients and the stdio subprocess.
- Base installations must still work without the MCP SDK.
