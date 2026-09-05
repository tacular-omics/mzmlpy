# Getting Started

## Installation

Install from PyPI:

```bash
pip install mzmlpy
```

If you need MS-Numpress decoding support, install the optional extra:

```bash
pip install mzmlpy[numpress]
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

`gzip_mode="auto"` is the default. With `in_memory=False`, it selects an embedded index, a current
extracted cache, or complete rapidgzip sidecars in that order. If none exists, it creates an
extracted cache. Inspect `reader.access_strategy` to see the concrete route.

For fast random access without cache files, create a self-indexed gzip file once:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from mzmlpy import Mzml, write_indexed_gzip

with TemporaryDirectory() as directory:
    output = Path(directory) / "input.indexed.mzML.gz"
    write_indexed_gzip("tests/data/example.mzML", output)

    with Mzml(output, in_memory=False) as reader:
        spectrum = reader.spectra[0]
```

mzMLPy detects this pyMZML-compatible embedded format automatically. The file remains a standard
concatenated gzip stream, and decompressing it reconstructs the original mzML bytes exactly.

- **`"auto"`** (default) selects the best valid representation already available and otherwise extracts into the central cache.
- **`"extract"`** decompresses to a cached file under the OS temp directory (`<tmpdir>/mzmlpy/`), then reads with full random access. The cache persists across Python sessions so subsequent opens of the same file skip decompression entirely. The OS clears the temp directory on reboot. Call `clear_cache()` to reclaim space sooner.
- **`"indexed"`** — Use the `rapidgzip` library for seekable access to the compressed file without extracting to disk. Requires `pip install mzmlpy[rapidgzip]`. Builds a gzip seek index (`.gzidx`) and mzML offset index (`.mzMLidx`) on first open, cached alongside the file for instant startup on subsequent opens.
- **`"stream"`** — Stream the file sequentially with no index. Lowest startup cost, but random access (e.g. `reader.spectra[0]`) scans from the beginning each time — a warning is emitted.

`"extract"` pays a one-time decompression cost then matches plain `.mzML` speed on later opens of
the same file (the extracted copy is cached). `"indexed"` pays a one-time index-build cost for
seekable access with no disk copy, then fast random access on later opens (the index is cached
alongside the file). `"stream"` has the lowest startup cost, but random access re-scans from the
start each time. For a reproducible benchmark with real numbers — including a comparison against
pyteomics and pymzml — see [`benchmarks/`](https://github.com/tacular-omics/mzmlpy/tree/main/benchmarks)
in the repository.

For best performance with `.mzML.gz` files, use `"extract"` or `"indexed"`:

```python
from mzmlpy import Mzml

# Indexed mode — no extraction, seekable (requires rapidgzip)
with Mzml("tests/data/example.mzML.gz", gzip_mode="indexed", in_memory=False) as reader:
    print(f"Spectra: {len(reader.spectra)}")
    spec = reader.spectra[0]
    print(spec.id)
```

To reclaim disk space before the OS clears the temp directory on reboot:

```python
from mzmlpy import clear_cache
clear_cache()
```

## Iterating Spectra

The `reader.spectra` property returns a lookup object that supports iteration, integer indexing, slicing, and string ID lookup:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    # Iterate all spectra
    for spectrum in reader.spectra:
        print(f"Scan {spectrum.id} (MS{spectrum.ms_level}) - TIC: {spectrum.TIC}")

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

The native `id` string encodes vendor-specific components (e.g. Thermo's `controllerType=0 controllerNumber=1 scan=19`); `id_dict` parses it into a dict with numeric components coerced to `int`. Common summary values and the instrument scan filter are also exposed directly, instead of requiring a manual `get_cvparm` lookup:

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
    charge = spec.charge  # np.ndarray | None

    # For less common array types, use get_binary_array with a CV accession
    barr = spec.get_binary_array(c.BinaryDataArrayAccession.RAW_ION_MOBILITY)
    if barr is not None:
        values = barr.data

    # Iterate all binary arrays on a spectrum
    for ba in spec.binary_arrays:
        print(ba.binary_array_type, ba.compression, ba.encoding)
```

## Working with Scan Timing

Retention time and ion injection time are accessible as `timedelta` objects through the spectrum, which delegates to the first scan:

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML") as reader:
    spec = reader.spectra[0]

    if spec.scan_start_time is not None:
        rt_seconds = spec.scan_start_time.total_seconds()
        rt_minutes = rt_seconds / 60
        print(f"RT: {rt_minutes:.4f} min")

    if spec.ion_injection_time is not None:
        iit_ms = spec.ion_injection_time.total_seconds() * 1000
        print(f"Ion injection time: {iit_ms:.2f} ms")

    print(f"Lower m/z: {spec.lower_mz}")
    print(f"Upper m/z: {spec.upper_mz}")
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

    time = tic.time  # np.ndarray | None
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
representation and preserves the lookup cursor. Use standalone `validate(path)` when the
original source file, rather than a cached representation, is what you want to inspect.
These checks do not constitute full XSD or controlled-vocabulary validation, and they do
not verify the embedded gzip index itself.

## Numeric types

Decoded arrays now preserve the numeric type declared in the file: `float32`, `float64`,
`int32`, or `int64`. This applies to spectrum, chromatogram, charge, and mobility arrays,
including empty arrays. Arrays remain writable and each access decodes a fresh array.

This changes the previous behavior, which converted ordinary arrays to float64. Preserving
the stored type avoids rounding large integers and uses half the array memory for float32
and int32 data. Code that needs float64 for calculations can convert explicitly:

```python
import numpy as np
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML", in_memory=False) as reader:
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
arrays. All supplied criteria must match. Bounds are inclusive, and `None` leaves an
endpoint open. Retention times are expressed in seconds, with source units normalized.

```python
from mzmlpy import Mzml

with Mzml("tests/data/example.mzML", in_memory=False) as reader:
    selected = reader.spectra.filter(ms_level=2, retention_time=(0, None))
    for spectrum in selected:
        print(spectrum.id, spectrum.ms_level)
```

Available criteria are `ms_level`, `retention_time=(lower_seconds, upper_seconds)`,
`polarity="positive"` or `"negative"`, `precursor_mz=(lower_mz, upper_mz)`,
`spectrum_type="centroid"` or `"profile"`, and scan-level mobility or FAIMS selection.
Retention time matches any scan. Precursor m/z matches overlap with any reported isolation
window. Selected-ion m/z values are used when a precursor has no usable isolation window.
Missing metadata does not match a requested criterion. Invalid numeric metadata raises its
normal contextual error. `SpectrumFilter` provides the same reusable predicate through
its `matches(spectrum)` method.

For mobility selection, use `mobility_type="inverse_reduced"` or `"drift_time"` and
optionally `ion_mobility=(lower, upper)`. Bounds use the recorded scan quantity and require
an explicit mobility type. `faims_voltage=(lower, upper)` accepts signed volts. These
criteria inspect scan metadata and do not process per-peak mobility arrays.

Filtering is a sequential scan. Keep the reader open while consuming the returned iterator.
It neither builds a retention-time index nor changes the cursor used by `reader.spectra.next()`.

## Command-line inspection

The CLI emits JSON and needs no additional installation:

```bash
python -m mzmlpy inspect data.mzML
python -m mzmlpy validate data.mzML --decode-binary --check-index
python -m mzmlpy index-gzip data.mzML data.indexed.mzML.gz
```

Exit codes are `0` for success, `1` for validation findings with errors, and `2` for an
operational error. Inspection reads metadata and counts without decoding arrays.

## Memory and extracted caches

`in_memory=True` remains the reader default. Use `in_memory=False` for large files and to
activate gzip access strategies. Extraction copies decompressed chunks directly to disk.
Sequential iteration detaches completed spectra and chromatograms, including records that
are skipped while finding the requested kind. Keeping returned spectra in a list still
retains their XML in your own code.

Both the default cache and a custom `extract_dir` use filenames based on source identity
and filesystem revision. Files with matching basenames in different directories do not
share an extracted file. Replacing a source creates a new cache path, so existing readers
can continue using their previous extracted copy. Older cache files can remain until you
clean the directory. `clear_cache()` removes the default cache only.
