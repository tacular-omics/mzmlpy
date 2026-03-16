<div align="center">
  <img src="logo.png" alt="MZMLpy Logo" width="400" style="margin: 20px;"/>
  
    
    A lightweight Python library for parsing mzML mass spectrometry files. Initially built from pymzml, it implements a more straightforward (type-safe API), and includes direct support for modern mzML structures (> 1.1.0).

  
  [![Python package](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml/badge.svg)](https://github.com/tacular-omics/mzmlpy/actions/workflows/python-package.yml)
  [![codecov](https://codecov.io/github/tacular-omics/mzmlpy/graph/badge.svg?token=1CTVZVFXF7)](https://codecov.io/github/tacular-omics/mzmlpy)
  [![PyPI version](https://badge.fury.io/py/mzmlpy.svg)](https://badge.fury.io/py/mzmlpy)
  [![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-g.svg)](https://opensource.org/licenses/MIT)
  
</div>



## Installation

```bash
pip install mzmlpy
```

## Usage

```python
from mzmlpy import Mzml

# Initialize reader with an mzML file (supports .mzML and .mzML.gz)
with Mzml("tests/data/example.mzML.gz") as reader:
    
    # Print basic file info
    print(f"File ID: {reader.id}")
    print(f"Total Spectra: {len(reader.spectra)}")
```

The `reader` object above contains all the contents of the mzML file. Data is lazily loaded, meaning it is only accessed when requested. In addition to metadata, `reader` exposes `spectra` and `chromatograms` via the `reader.spectra` and `reader.chromatograms` properties, respectively. Both return lookup classes that support iteration and lookup by index or ID (see examples below).


## Examples

### 1. Iterating Spectra

You can iterate directly over the `spectra` object. 

```python
for spectrum in reader.spectra:
    print(f"Scan {spectrum.id} (MS{spectrum.ms_level}) - TIC: {spectrum.TIC}")
```

### 2. Accessing Spectral Data

Internally, spectra and chromatograms are stored as 2 dictionary lookups, one by index and one by ID.
The index is parsed from the spectrum/chromatogram index attribute, so it's technically possible that it won't start at 0 or be congruent. In most cases it should start at 0 and end at (num spectra - 1).

```python
# Get by index
spectrum = reader.spectra[0]
chrom = reader.chromatograms[1]

# Get by slice (must be ints)
_ = reader.spectra[1:5:1]
_ = reader.chromatograms[:2]

# get by id
_ = reader.spectra['scan=19']
_ = reader.chromatograms['sic']

try:
    _ = reader.spectra[-1]
    _ = reader.spectra[10**10]
    _ = reader.spectra['INVALID ID']
except KeyError:
    pass
```

### 3. Iterating over Spectra/Chromatograms

Use standard Python list comprehensions or loops to filter. This crawls the mzml file rather than relying on lookups, so it should always be safe.

```python
# Get all MS2 spectra
ms2_spectra = [s for s in reader.spectra if s.ms_level == 2]
print(f"Found {len(ms2_spectra)} MS2 spectra")
```

### 4. Accessing Binary Data

Spectra and Chromatograms have easy access to mz, time, and intensity arrays as these are the most common types.
There are a number of other binary data arrays supported by PSI CV terms, as well as custom-defined arrays.

Access to the data property (decoded array) is lazily loaded each time, so for repeated use, 
it is best to save the array to a local variable to avoid having to decode the data multiple times.

```python
from mzmlpy import constants as c

spectra = reader.spectra[0]

# looks for a matching cv term
_ = spectra.has_binary_array('MS:1003007')
barr = spectra.get_binary_array(c.BinaryDataArrayAccession.RAW_ION_MOBILITY) # can also access via included Enums
np_arr = barr.data # decodes the binary data

# for user defined binary array (uncommon) you will have to iterate over the binary arrays to identify
for ba in spectra.binary_arrays:
    if ba.has_user_param('custom array name'):
        arr = ba.data
```

### 5. Working with Chromatograms

Access chromatograms by ID or iterate through them.

```python
# Access Total Ion Chromatogram (TIC) if available
tic = reader.chromatograms['tic']

_ = tic.time 
_ = tic.intensity 
_ = tic.precursor # Precursor | None
_ = tic.product # Product | None

# get CvParams
_ = tic.cv_params
```

### 6. Working with Spectra

Access spectra metadata and arrays.

```python
spec = reader.spectra[0]

_ = spec.mz
_ = spec.intensity
_ = spec.charge               # NDArray | None — per-point charge array
_ = spec.precursors           # list[Precursor]
_ = spec.products             # list[Product]
_ = spec.scans
_ = spec.spectrum_type
_ = spec.polarity

# Ion mobility
_ = spec.has_im               # bool — True if any IM binary array is present
_ = spec.im_types             # set[BinaryDataArrayAccession]

# Scan timing and window (delegate to first scan)
_ = spec.scan_start_time      # timedelta | None
_ = spec.ion_injection_time   # timedelta | None
_ = spec.lower_mz             # float | None
_ = spec.upper_mz             # float | None

# get CvParams
_ = spec.cv_params
```

### 7. Accessing Metadata

Explore file metadata such as instrument configuration and software.

```python
# Instrument Configuration
for config_id, config in reader.instrument_configurations.items():
    print(f"Instrument: {config_id}")
    for component in config.components:
        print(f"  - Component: {component.type} ({component.accession})")

# Software
for software in reader.softwares.values():
    print(f"Software: {software.id} (Version: {software.version})")

_ = reader.cvs
_ = reader.file_description
_ = reader.referenceable_param_groups
_ = reader.data_processes
_ = reader.samples
_ = reader.scan_settings
_ = reader.run # does not contain chromatogram or spectra lists (only metadata)
```

### 8. Ion Mobility

Check whether a spectrum carries ion mobility data and retrieve a specific IM array.

```python
spec = reader.spectra[0]
if spec.has_im:
    print(f"IM types: {spec.im_types}")
    # Access a specific IM array
    from mzmlpy.constants import BinaryDataArrayAccession
    im_array = spec.get_binary_array(BinaryDataArrayAccession.MEAN_INVERSE_REDUCED_ION_MOBILITY)
    if im_array is not None:
        values = im_array.data
```

### 9. Scan Timing

Access retention time and ion injection time from the first scan of a spectrum.

```python
spec = reader.spectra[0]
if spec.scan_start_time is not None:
    rt_seconds = spec.scan_start_time.total_seconds()
    rt_minutes = rt_seconds / 60
    print(f"RT: {rt_minutes:.4f} min")
if spec.ion_injection_time is not None:
    print(f"Ion injection time: {spec.ion_injection_time.total_seconds() * 1000:.2f} ms")
```

## Development

```bash
just lint
just format
just ty
just test

# or run all the above:
just check
```
