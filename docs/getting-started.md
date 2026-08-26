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

    mz = spec.mz  # NDArray[float64] | None
    intensity = spec.intensity  # NDArray[float64] | None
    charge = spec.charge  # NDArray[float64] | None

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

    time = tic.time  # NDArray[float64] | None
    intensity = tic.intensity  # NDArray[float64] | None

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
