# Getting Started

## Installation

mzmlpy needs Python 3.12 or later. Install it from PyPI:

```bash
pip install mzmlpy
# or, in a uv project
uv add mzmlpy
```

The base install depends only on NumPy. Optional extras add codecs and features:

| Extra | Adds |
|---|---|
| `numpress` | MS-Numpress array decoding |
| `zstd` | Zstandard-compressed arrays |
| `rapidgzip` | `gzip_mode="indexed"` seekable gzip access |
| `mcp` | the [MCP server](mcp.md) |

```bash
pip install "mzmlpy[numpress,zstd]"
```

## Basic Usage

Open an mzML file with the context manager to ensure proper cleanup:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    print(f"File ID: {reader.id}")
    print(f"mzML version: {reader.version}")
```

Both `.mzML` and `.mzML.gz` files are supported. The reader lazily parses the file, so metadata is available immediately while binary data is decoded only on access.

## Reading Gzipped Files

When working with `.mzML.gz` files, the `gzip_mode` parameter controls how the compressed file is accessed:

`gzip_mode="auto"` is the default. Reading from disk (the default), it uses, in order:

1. The embedded index, if the file has one (written by `write_indexed_gzip`, below).
2. `rapidgzip`, if it is installed (`pip install mzmlpy[rapidgzip]`). It reads the compressed
   file in place and keeps two small sidecar indexes next to it, so later opens start fast. If
   the sidecars cannot be written (for example, a read-only directory), it falls back to step 3.
3. Otherwise it decompresses the whole file into memory, as 0.9 did.

Inspect `reader.access_strategy` to see the route taken (`"embedded"`, `"rapidgzip"` or
`"memory"`). For a large `.mzML.gz`, step 3 needs memory about the size of the decompressed
file, so run `write_indexed_gzip` on it once or install the rapidgzip extra.

For fast random access with no extra files, create a self-indexed gzip file once:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from mzmlpy import Mzml, write_indexed_gzip

with TemporaryDirectory() as directory:
    output = Path(directory) / "input.indexed.mzML.gz"
    write_indexed_gzip("tests/data/example.mzML", output)

    with Mzml(output) as reader:
        spectrum = reader.spectra[0]
```

mzmlpy detects this pyMZML-compatible embedded format automatically. The file remains a standard
concatenated gzip stream, and decompressing it reconstructs the original mzML bytes exactly.

- **`"auto"`** (default) takes the first of the routes above that is available.
- **`"indexed"`** — Use the `rapidgzip` library for seekable access to the compressed file without decompressing it all. Requires `pip install mzmlpy[rapidgzip]`. Builds a gzip seek index (`.gzidx`) and mzML offset index (`.mzMLidx`) on first open, cached alongside the file for instant startup on subsequent opens.
- **`"stream"`** — Stream the file sequentially with no index. Lowest startup cost, but random access (e.g. `reader.spectra[0]`) scans from the beginning each time — a warning is emitted.

`gzip_mode="extract"` and `extract_dir` were removed in 0.10; see the [migration notes](migration.md).

An embedded index gives fast random access with no extra files. `"indexed"` pays a one-time
index-build cost, then fast random access on later opens (the index is cached alongside the
file). `"stream"` has the lowest startup cost, but random access re-scans from the start each
time. For a reproducible benchmark with real numbers — including a comparison against pyteomics
and pymzml — see [`benchmarks/`](https://github.com/tacular-omics/mzmlpy/tree/main/benchmarks)
in the repository.

```python
from mzmlpy import Mzml

# Indexed mode — seekable, no full decompression (requires rapidgzip)
with Mzml("tests/data/example.mzML.gz", gzip_mode="indexed") as reader:
    print(f"Spectra: {len(reader.spectra)}")
    spec = reader.spectra[0]
    print(spec.id)
```

### Readers and multiprocessing

Open readers inside each worker process rather than passing an open reader to it. A child
process forked (`os.fork`, or the `fork` start method) while it holds a rapidgzip-backed reader
can abort when it exits (`terminate called`, exit status 134). This is a limitation of rapidgzip,
which cannot be forked safely once its worker threads are running; the parent is not affected.
If workers must inherit readers, use the `spawn` start method:
`multiprocessing.get_context("spawn")`.

## Iterating Spectra

The `reader.spectra` property returns a lookup object that supports iteration, integer indexing, slicing, and string ID lookup:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    # Iterate all spectra
    for spectrum in reader.spectra:
        print(f"Scan {spectrum.id} (MS{spectrum.ms_level}) - TIC: {spectrum.total_ion_current}")

    # Access by index
    first = reader.spectra[0]

    # Access by slice
    batch = reader.spectra[0:2]

    # Access by string ID
    scan = reader.spectra["scan=19"]

    # Filter with a list comprehension
    ms2_spectra = [s for s in reader.spectra if s.ms_level == 2]
```

## Native IDs and Summary Values

The native `id` string encodes vendor-specific components (e.g. Thermo's `controllerType=0 controllerNumber=1 scan=19`); `id_dict` parses it into a dict with numeric components coerced to `int`. Common summary values and the instrument scan filter are also exposed directly, instead of requiring a manual `get_cv_param` lookup:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    spec = reader.spectra[0]

    print(spec.id_dict)  # e.g. {"scan": 19}

    print(spec.base_peak_mz, spec.base_peak_intensity)
    print(spec.lowest_observed_mz, spec.highest_observed_mz)
    print(spec.filter_string)  # e.g. Thermo scan filter string
```

To cheaply check how many spectra a file contains without opening it fully -- no reader is constructed and no random-access index is built, so this is much cheaper than `len(Mzml(path).spectra)` when you only need the count -- use the standalone `peek_spectrum_count` function:

```python
from mzmlpy import peek_spectrum_count

count = peek_spectrum_count("tests/data/example.mzML")  # int | None
```

## Accessing Binary Data

Spectra expose `mz` and `intensity` as convenience properties. Access is lazy -- the binary data is decoded on every call, so save the result to a local variable when you need it more than once:

```python
from mzmlpy import Mzml
from mzmlpy import constants as c

with Mzml("tests/data/example.mzML") as reader:
    spec = reader.spectra[0]

    mz = spec.mz  # np.ndarray | None
    intensity = spec.intensity  # np.ndarray | None
    charge = spec.charge_array  # np.ndarray | None

    # For less common array types, use get_binary_array with a CV accession
    barr = spec.get_binary_array(c.BinaryDataArrayAccession.RAW_ION_MOBILITY)
    if barr is not None:
        values = barr.data

    # Iterate all binary arrays on a spectrum
    for ba in spec.binary_arrays:
        print(ba.binary_array_type, ba.compression, ba.encoding)
```

## Working with Scan Timing

Retention time is a float in seconds (`rt`), ion injection time is a float in milliseconds (`ion_injection_time`), and `mz_range` is the scan window envelope. The spectrum delegates each to its first scan:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    spec = reader.spectra[0]

    if spec.rt is not None:
        rt_minutes = spec.rt / 60
        print(f"RT: {rt_minutes:.4f} min")

    if spec.ion_injection_time is not None:
        print(f"Ion injection time: {spec.ion_injection_time:.2f} ms")

    if spec.mz_range is not None:
        lower, upper = spec.mz_range
        print(f"Scan window: {lower}-{upper} m/z")
```

## Working with Ion Mobility

Check whether a spectrum carries ion mobility data and retrieve the relevant arrays:

```python
from mzmlpy import Mzml
from mzmlpy.constants import BinaryDataArrayAccession

with Mzml("tests/data/example.mzML") as reader:
    spec = reader.spectra[0]

    if spec.has_im:
        print(f"IM types: {spec.im_types}")

        im_array = spec.get_binary_array(
            BinaryDataArrayAccession.MEAN_INVERSE_REDUCED_ION_MOBILITY
        )
        if im_array is not None:
            values = im_array.data
```

## Working with Chromatograms

Chromatograms work similarly to spectra -- access by index, ID, or iteration:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    tic = reader.chromatograms["tic"]

    rt = tic.rt  # np.ndarray | None, float64 seconds whatever unit the file records
    intensity = tic.intensity  # np.ndarray | None

    # Precursor and product info (SRM chromatograms)
    print(tic.precursor)
    print(tic.product)
    print(tic.chromatogram_type)  # "tic", "basepeak", "srm", etc.
```

## Accessing File Metadata

The reader exposes instrument configuration, software, and other file-level metadata:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    # Instrument configurations
    for config_id, config in reader.instrument_configurations.items():
        print(f"Instrument: {config_id}")
        print(f"  Sources: {len(config.source_components)}")
        print(f"  Analyzers: {len(config.analyzer_components)}")
        print(f"  Detectors: {len(config.detector_components)}")

    # Software
    for sw in reader.softwares.values():
        print(f"{sw.id} v{sw.version}")

    # Other metadata
    _ = reader.cvs
    _ = reader.file_description
    _ = reader.referenceable_param_groups
    _ = reader.data_processes
    _ = reader.samples
    _ = reader.scan_settings
    _ = reader.run
```

## Validation

Use `validate` to check a file directly without creating or repairing caches. The default
scans XML, checks list counts, duplicate IDs, references, index ID agreement, and supported
array metadata. It does not decode binary arrays.

```python
from mzmlpy import validate

report = validate("tests/data/example.mzML")
print(report.valid, report.spectrum_count, report.chromatogram_count)
for issue in report.issues:
    print(issue.code, issue.location, issue.message)
```

Set `decode_binary=True` to decode arrays and compare their lengths. Set `check_index=True`
to seek to XML footer offsets and verify their targets. These checks may be expensive,
especially offset verification on ordinary gzip files. The report states which checks ran,
how many arrays and index entries were checked, and whether XML parsing completed.
`report.to_dict()` returns JSON-serializable results. File-open errors raise `OSError`.
Malformed content is reported through `report.issues`.

An open reader also has `reader.validate(...)`. It uses a fresh handle to the selected
representation and leaves open iterators untouched. Use standalone `validate(path)` when the
original source file, rather than a cached representation, is what you want to inspect.
These checks do not constitute full XSD or controlled-vocabulary validation, and they do
not verify the embedded gzip index itself.

## Numeric types

Decoded arrays preserve the numeric type declared in the file: `float32`, `float64`,
`int32`, or `int64`. This applies to spectrum, chromatogram, charge, and mobility arrays,
including empty arrays. Arrays remain writable and each access decodes a fresh array.

Releases before 0.9 converted ordinary arrays to float64. Preserving
the stored type avoids rounding large integers and uses half the array memory for float32
and int32 data. Code that needs float64 for calculations can convert explicitly:

```python
import numpy as np
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    spectrum = reader.spectra[0]
    intensity = spectrum.intensity.astype(np.float64)
```

Choose calculation types deliberately. Arithmetic on integer arrays can overflow, and
float32 arithmetic can round differently from float64. Existing consumers that require
double precision should use the explicit conversion above.

Numpress is a compressed numerical representation with its own reconstruction rules.
Its decoded output remains float64, including empty arrays, without an extra narrowing cast.
Decoding cannot recover precision discarded during lossy encoding. See the
[Numpress format description](https://github.com/ms-numpress/ms-numpress).
For arrays without a declared numeric type, the existing warning and float64 fallback remain.

## Lazy filtering

`reader.spectra.filter(...)` selects spectra from metadata without decoding their binary
arrays. All supplied criteria must match. `*_range` bounds are inclusive, and `None` leaves
an endpoint open. Retention times are expressed in seconds, with source units normalized.

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    selected = reader.spectra.filter(ms_level=2, rt_range=(0, None))
    for spectrum in selected:
        print(spectrum.id, spectrum.ms_level)
    # Point queries, as in tdfpy: within 30 s, and within 20 ppm.
    near = list(reader.spectra.filter(rt=5.0, rt_tolerance=30.0))
    same_precursor = list(reader.spectra.filter(precursor_mz=445.34, mz_tolerance=20, mz_tolerance_type="ppm"))
```

Available criteria are `ms_level`, `rt_range=(lower_seconds, upper_seconds)` or `rt=` with
`rt_tolerance`, `polarity="positive"` or `"negative"`,
`precursor_mz_range=(lower_mz, upper_mz)` or `precursor_mz=` with `mz_tolerance` and
`mz_tolerance_type` (`"ppm"` or `"da"`), `spectrum_type="centroid"` or `"profile"`, and
scan-level mobility or FAIMS selection. Pass a point or its range, not both.
Retention time matches any scan. Precursor m/z matches overlap with any reported isolation
window. Selected-ion m/z values are used when a precursor has no usable isolation window.
Missing metadata does not match a requested criterion. Invalid numeric metadata raises its
normal contextual error. `SpectrumFilter` provides the same reusable predicate through
its `matches(spectrum)` method.

For mobility selection, use `ook0_range=(lower, upper)` (1/K0, V·s/cm²) or
`drift_time_range=(lower, upper)`; `(None, None)` selects spectra that record the quantity at
all. `faims_voltage_range=(lower, upper)` accepts signed volts. These criteria inspect scan
metadata and do not process per-peak mobility arrays.

With an indexed reader (access strategy `plain`, `rapidgzip` or `memory`; not
`stream` or `embedded`, which scan every spectrum), the first retention-time criterion reads the scan times of every spectrum once, from the bytes before
each record's binary arrays, and caches them on `reader.spectra`. That query and every later
one then read in full only the spectra inside the window. Record order does not matter, so
merged or re-sorted files give the same result as a full scan. Other criteria are a
sequential scan. Keep the reader
open while consuming the returned iterator; each call returns a new, independent iterator.

## Command-line inspection

The CLI emits JSON and needs no additional installation:

```bash
python -m mzmlpy inspect data.mzML
python -m mzmlpy validate data.mzML --decode-binary --check-index
python -m mzmlpy index-gzip data.mzML data.indexed.mzML.gz
```

Exit codes are `0` for success, `1` for validation findings with errors, and `2` for an
operational error. Inspection reads metadata and counts without decoding arrays.

## Memory

Since 0.10 the reader reads records from disk on demand by default. Pass `in_memory=True` to
load the whole (decompressed) file once, which suits many random reads of a small file.
`gzip_mode` only applies when reading from disk.
Sequential iteration detaches completed spectra and chromatograms, including records that
are skipped while finding the requested kind. Keeping returned spectra in a list still
retains their XML in your own code.
