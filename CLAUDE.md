# CLAUDE.md

## Project

**mzmlpy** — lightweight Python library for parsing mzML mass spectrometry files. Exposes a type-safe, lazy-loading API for spectra, chromatograms, and file metadata. Python 3.12+ only.

Current version: **0.2.0** (Beta). Published on PyPI.

## Commands

```bash
just lint        # ruff check src
just format      # ruff isort + format src + tests
just ty          # ty type checker (excludes src/mzmlpy/decoder.py)
just check       # lint + ty + test
just test        # pytest tests/
just test-cov    # pytest with coverage report
just docs        # mkdocs serve on localhost:8001
just docs-build  # mkdocs build to site/
just install     # uv sync
```

Always run `just lint` and `just test` after any code change.

## Architecture

```
src/mzmlpy/
├── run.py              # Mzml — main reader class, context manager, lazy XML parsing
├── spectra.py          # Spectrum, Chromatogram, and all mixin/helper classes
├── constants.py        # All StrEnum accessions + ION_MOBILITIES constant set
├── decoder.py          # MSDecoder — zlib/zstd/numpress decompression (excluded from ty)
├── lookup.py           # SpectrumLookup, ChromatogramLookup — index/id/slice access
├── file_interface.py   # File format routing (.mzML, .mzML.gz)
├── content.py          # CVElement
├── elems/              # Metadata dataclasses (FileDescription, InstrumentConfiguration, etc.)
└── py.typed            # PEP 561 marker
```

### Key design patterns

- **Frozen dataclasses** — all data classes use `@dataclass(frozen=True)`; use `cached_property` for computed values
- **Mixin composition** — `Spectrum` inherits from `_BinaryDataArrayMixin`, `_ScanListMixin`, `_PrecursorListMixin`, `_ProductListMixin`; never duplicate logic across these
- **Lazy binary decoding** — `BinaryDataArray.data` decodes on every call (not cached); callers should store result if reusing
- **XML namespaced lookups** — all `element.find()` calls use `self.ns` prefix (e.g. `f"./{self.ns}scanList"`)
- **Warnings over exceptions** for ambiguous multi-scan/multi-window cases (e.g. `lower_mz` on a spectrum with multiple scans)

## Dependencies

- **Runtime:** `numpy>=1.26.0` only
- **Optional:** `pynumpress>=0.0.4` (install via `pip install mzmlpy[numpress]`)
- **Dev:** pytest, ruff, ty, pyupgrade, zstd, pytest-cov, mkdocs, mkdocs-material, mkdocstrings[python]
- **Build:** uv + hatchling

## Code style

- Line length: 120
- Type annotations required on all public API
- Google-style docstrings
- `StrEnum` for all CV accession constants — never hardcode accession strings outside `constants.py` (there are some legacy exceptions in `spectra.py` that should be migrated)
- `Literal[...]` return types preferred over plain `str` for known-set values (e.g. `polarity`, `spectrum_type`)

## Docs

MkDocs + Material theme + mkdocstrings. All 34 exported public classes have API reference pages under `docs/api/`. Config in `mkdocs.yml` — `inherited_members: true` flattens mixin members, `signature_crossrefs: true` makes type annotations into links.

## Tests

Test data: `tests/data/example.mzML` and `tests/data/example.mzML.gz` (4 spectra, 1 chromatogram).
Tests are parametrized over both files. No mocking — tests run against real XML.
