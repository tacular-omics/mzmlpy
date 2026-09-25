---
title: 'mzmlpy: Typed, lazy reading of mzML mass spectrometry files in Python'
tags:
  - Python
  - Proteomics
  - Metabolomics
  - Mass Spectrometry
  - mzML
authors:
  - name: Patrick T. Garrett
    orcid: 0000-0002-8434-9693
    affiliation: 1
  - given-names: John R.
    surname: Yates
    suffix: III
    orcid: 0000-0001-5267-1672
    corresponding: true
    affiliation: 1
affiliations:
  - name: The Scripps Research Institute, United States
    index: 1
date: 24 September 2026
bibliography: paper.bib
---

# Summary

mzML is the Proteomics Standards Initiative's open XML format for mass spectrometry data
[@martens2011mzml]. A file holds run-level metadata (instruments, software, samples,
processing history) and a list of spectra and chromatograms. Each record carries controlled
vocabulary (CV) terms and base64-encoded, optionally compressed numeric arrays such as m/z and
intensity. **mzmlpy** [@mzmlpy_zenodo] is a Python library that reads these files. It parses
metadata into typed, immutable objects and decodes a binary array only when the caller asks
for it. It reads plain and gzip-compressed mzML, decodes zlib, Zstandard and MS-Numpress
arrays, selects spectra by metadata without decoding peaks, and reports structural problems
through a validation function. It also writes and reads pymzML's self-indexed gzip format
[@kosters2018pymzml] and ships an optional Model Context Protocol (MCP) server
[@mcp2025spec] for AI clients. Its only runtime dependency is NumPy.

# Statement of need

Most Python code that touches mzML needs a small part of each file: a few metadata fields to
choose spectra, then peaks for the chosen ones. A reader that decodes every array, or that
returns loosely typed XML trees, makes that pattern slow or error-prone. Two further problems
come from the format itself. First, newer encodings such as Zstandard compression
[@rfc8878zstd] and the combined "MS-Numpress followed by zlib" terms [@teleman2014numpress]
are not handled by every reader, and a reader that does not recognise an encoding may return
empty arrays instead of failing. Second, `.mzML.gz` files are common in public repositories,
but plain gzip is not seekable, so random access usually means decompressing the whole file.

mzmlpy is aimed at developers of proteomics and metabolomics pipelines, format converters and
quality-control tools who need to control when arrays are decoded, who want an error rather
than silent data loss on an unsupported encoding, and who work directly with compressed files.

# State of the field

Several open-source tools read mzML from Python. **Pyteomics** [@goloborodko2013pyteomics;
@levitsky2019pyteomics] is a broad proteomics framework whose `mzml` module offers iterative
and indexed reading, with MS-Numpress support through the optional `pynumpress` package and
CV handling through **psims** [@klein2019psims]. psims itself is mainly a writer for mzML and
mzIdentML. **pymzML** [@bald2012pymzml; @kosters2018pymzml] is a dedicated mzML reader; its
version 2.0 introduced a seekable gzip layout that stores a spectrum offset index inside the
gzip stream. **pyOpenMS** [@rost2014pyopenms] exposes the C++ OpenMS library
[@pfeuffer2024openms], including in-memory and on-disc mzML access and a large set of
processing algorithms. ProteoWizard [@chambers2012proteowizard] is a widely used C++ toolkit for converting
vendor files to mzML.

mzmlpy does not replace these tools. It does not write mzML (beyond re-packaging a file as
self-indexed gzip), and it contains no spectrum processing. It also reuses an existing
container format, pymzML's, rather than inventing one. What it adds is a reader that
combines typed models, lazy decoding, current encodings, metadata-only selection, validation
and gzip random access in one small package.

Table 1 shows the format-support group of the repository's benchmark (`benchmarks/benchmark.py`),
which we re-ran for this paper with pyteomics 5.0.1 and pymzML 2.7.0. The corpus in
`tests/data` holds one set of 1,618 peaks encoded five ways; the table gives the summed
intensity each reader returned. The Numpress files use the combined "followed by zlib" CV
terms.

| encoding | mzmlpy | pyteomics | pymzML |
|---|---|---|---|
| zlib | 31,417,890 | 31,417,890 | 31,417,890 |
| Zstandard | 31,417,890 | error | 0 peaks, no error |
| Numpress linear | 31,417,890 | 31,417,890 | 0 peaks, no error |
| Numpress slof | 31,417,922 | 31,417,923 | 0 peaks, no error |
| Numpress pic | 31,417,897 | 31,417,897 | 0 peaks, no error |

: Summed intensity of the re-encoded test corpus. Numpress slof and pic are lossy by design.

On a larger file, the 47.9 MB, 3,392-spectrum Q Exactive HF run `QEHF1_09771_JB` from
PRIDE project PXD015669 [@ivanov2020directms1], we ran the harness's throughput group twice
(minimum of five repeats each; the harness opens mzmlpy with `in_memory=True`). The
workstation was shared and under load, so absolute times are indicative only. Opening a file and building a random-access index took 0.047--0.056 s
with mzmlpy and 0.94--1.08 s with pyteomics. Decoding every spectrum took 2.2--2.7 s with
mzmlpy, 3.4--4.8 s with pyteomics and 2.8--3.3 s with pymzML. Opening the file and
reading eight spectra at scattered positions took 0.053--0.058 s with mzmlpy and 1.1--2.1 s with pyteomics; pymzML's indexed lookup raised an
`AttributeError` on this file, although it works on the small example file. Full decoding is
thus of the same order in all three readers. The larger differences are in index
construction, random access and encoding coverage.

# Software design

`Mzml` is a context manager. On opening, it sniffs the encoding, selects a file backend and
parses the header metadata eagerly. Spectrum and chromatogram lookups accept an integer
position, a native identifier or a slice, and return records wrapped in frozen dataclasses.
CV-backed properties are parsed on first access; binary arrays are decoded on every access and
are never cached, so memory stays bounded by what the caller keeps. Absent CV terms return
`None` or an empty tuple, units are normalised (retention time in seconds, injection time in
milliseconds), and ion mobility is exposed whether a file stores it as a scan parameter or as
a binary array.

Five backends share one protocol: plain files with an XML offset index, whole files in
memory, pymzML-style self-indexed gzip, gzip read through rapidgzip's seekable index
[@knespel2023rapidgzip], and sequential gzip streaming. In the default `gzip_mode="auto"`,
mzmlpy uses an embedded index if the file has one, then rapidgzip if it is installed, and
otherwise decompresses into memory. It never writes files next to the input in this mode.
`write_indexed_gzip` converts any mzML into a self-indexed `.mzML.gz` that decompresses to
the original bytes exactly, is byte-for-byte deterministic, and can be read by pymzML; we
checked this by opening a converted `tests/data/example.mzML` with pymzML 2.7.0 and comparing
three spectra with mzmlpy's output.

`spectra.filter()` selects spectra by MS level, retention time, polarity, precursor m/z,
spectrum type, ion mobility and FAIMS voltage without decoding any array. On indexed readers,
a retention-time query first builds a cached table of scan times from the bytes that precede
each record's binary arrays. `validate()` streams through a file and returns a report of
structural problems (XML structure, list counts, identifiers, references, index agreement and
array metadata), optionally decoding every array or checking every index offset. It does not
repair the file and does not perform XSD or full CV validation. Errors form a small hierarchy
rooted at `MzmlError`, so callers can distinguish malformed data from a missing record.

Attribute names follow a vocabulary shared with the Bruker timsTOF reader **tdfpy**
[@tdfpy_zenodo] and the spectrum-processing library **spxtacular** [@spxtacular_zenodo]:
`rt` in seconds, `ook0` and `drift_time` for ion mobility, `precursor_mz`, and
`mz_tolerance_unit` taking `"da"` or `"ppm"`. spxtacular uses mzmlpy as its optional mzML
backend, and the shared names reduce renaming when code moves between the readers.

The optional MCP server (`python -m mzmlpy mcp --root DIR`) runs over local stdio and gives AI
clients 17 tools for file discovery, metadata, run summaries, validation, spectrum selection
and bounded array access, plus two export tools when an output directory is supplied. Paths
are confined to the data root and source files are never modified.

The package requires Python 3.12 or later and has a type-annotated public API. Its test suite runs
against real mzML files, including Thermo and Bruker exports and the re-encoded corpus, and
executes the code in the getting-started guide.

# Example usage

The following runs from the repository root on `tests/data/example.mzML` (four spectra, two
chromatograms):

```python
from mzmlpy import Mzml, validate

path = "tests/data/example.mzML"
print(validate(path, decode_binary=True).valid)

with Mzml(path) as reader:
    print(len(reader.spectra), len(reader.chromatograms))
    # Selection reads metadata only; no arrays are decoded here.
    for s in reader.spectra.filter(ms_level=2):
        print(s.id, s.rt, s.precursor_mz, s.precursor_charge)
        mz = s.mz  # decoded on access
        print(len(mz), mz.dtype)
```

Output:

```text
True
4 2
scan=20 359.43 445.34 2
10 float64
```

The file records this scan's start time as 5.9905 minutes; `rt` reports it in seconds.

# Research impact

Within the authors' software, mzmlpy is the mzML backend of spxtacular's reader layer
[@spxtacular_zenodo]. <!-- TODO(author): add any use of mzmlpy outside the tacular-omics
packages (labs, pipelines, publications). None is recorded in the repository, so none is
claimed here. -->

# AI usage disclosure

<!-- TODO(author): AI usage disclosure (tools, versions, what they were used for, how output
was verified). -->

# Acknowledgements

<!-- TODO(author): acknowledgements and funding. -->

# References
