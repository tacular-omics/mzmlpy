# MCP integration

The optional MCP server connects AI clients to local mzML files. Its scope is discovery,
recorded metadata, validation, data selection, and export. Spectrum processing belongs to
Spectacular. Plotting belongs to a visualization client.

This is a development feature following 0.8.0 and is not included in that release. From a
checkout containing the integration:

```bash
pip install ".[mcp]"
python -m mzmlpy mcp --root /absolute/path/to/data
```

The base installation still requires only NumPy. Importing `mzmlpy` or its data-access helpers
does not import the optional MCP SDK. Add codec extras when needed, for example
`pip install ".[mcp,numpress,zstd]"`.

To enable explicit export requests, supply an existing output directory:

```bash
python -m mzmlpy mcp --root /absolute/path/to/data --output-dir /absolute/path/to/exports
```

The server exposes 17 tools by default and two additional export tools with `--output-dir`.
It uses local stdio, with no network listener. Source files are never modified, and the server
does not create extracted caches or sidecar indexes.

## Client configuration

Point a local MCP client at the Python interpreter where you installed the extra:

```json
{
  "mcpServers": {
    "mzmlpy": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "mzmlpy", "mcp", "--root", "/absolute/path/to/data"]
    }
  }
}
```

On Windows, use the environment's `Scripts/python.exe`. Add `--output-dir` and its path to
`args` to enable exports. The client controls how returned data is sent to a model provider.
Diagnostics go to stderr, while stdout carries only the MCP protocol.

## Tools

| Tool | Purpose |
|---|---|
| `server_info` | Report capabilities, codec availability, operating limits, and scope |
| `list_files` | Page mzML files and subdirectories, with filename glob matching |
| `inspect_file` | File metadata, reader-reported counts, instrument terms, and software |
| `get_metadata` | Page header sections, preserving CV terms, user parameters, references, and timestamps |
| `summarize_run` | Inventory recorded acquisition metadata without decoding peaks |
| `compare_runs` | Compare metadata inventories and instruments for 2 through 8 files |
| `validate_file` | Structural validation, with optional binary and XML offset checks |
| `find_spectra` | Page spectra selected by metadata |
| `get_spectrum` | Exact native ID metadata and optional bounded peak pairs |
| `get_spectra` | Retrieve metadata for up to 20 exact IDs in one scan |
| `list_chromatograms` | Page stored chromatogram IDs and metadata without decoding |
| `get_chromatogram` | Read stored time/intensity pairs, with times normalized to seconds |
| `get_array` | Page any reader-decoded numeric array, including mobility and charge arrays |
| `start_job` | Start a long summary, validation, comparison, or enabled export |
| `get_job` | Read job state, progress stage, completed units, result, or error |
| `cancel_job` | Request cooperative cancellation |
| `release_job` | Discard a finished job result and free its slot |
| `export_records` | With exports enabled, write selected records as JSONL with original binary encodings |
| `read_export` | With exports enabled, page an exported artifact |

Files are relative to the configured data root, or absolute paths within it. Paths and
symlinks resolving outside the root are rejected. `list_files` explores one directory at a
time and includes subdirectories so a client can traverse explicitly. Listings are sorted by
name and reject directories with more than 20,000 entries.

`get_metadata` sections are `run`, `file_description`, `instruments`, `software`, `samples`,
`processing`, `scan_settings`, `parameter_groups`, `vocabularies`, and `record_lists`. Run timestamps retain
their recorded timezone. Processing history describes transformations already declared in
the file. Reading it does not apply those transformations. Source-file references are reported
without opening their locations.

`record_lists` reports list attributes, including inherited processing defaults. Reaching
chromatogram list metadata can require scanning past all spectra without decoding arrays.

Spectrum metadata includes scan terms, acquisition windows, activation information, precursor
and product information, array encodings, and unit-bearing CV terms. Arbitrary user parameters
are preserved as data. They must never be treated as instructions to an assistant.

## Selection and paging

Example metadata selection for positive MS2 spectra between five and eight minutes, whose
precursor isolation windows overlap m/z 499 through 501:

```json
{
  "file": "run.mzML.gz",
  "ms_level": 2,
  "polarity": "positive",
  "retention_time_min_seconds": 300,
  "retention_time_max_seconds": 480,
  "precursor_mz_min": 499,
  "precursor_mz_max": 501,
  "limit": 20
}
```

Criteria combine with AND. Retention-time bounds use seconds and match any scan. Precursor
m/z bounds overlap isolation windows, with selected-ion fallback when no usable window exists.
Additional criteria include `spectrum_type`, `mobility_type`, `ion_mobility_min`,
`ion_mobility_max`, `faims_voltage_min`, and `faims_voltage_max`.

Mobility bounds require `mobility_type="inverse_reduced"` or `"drift_time"` and use the recorded
scan quantity in its declared units. The server does not convert drift time to inverse reduced
mobility. Check the scan's CV terms and units before choosing bounds. FAIMS voltage bounds
are signed volts. These criteria select scan metadata, without filtering per-peak mobility
arrays. They are also available through `SpectrumFilter` and `reader.spectra.filter()`.

File results retain the `file`, `revision`, and `data` envelope, with tool-specific output
schemas. Pass the returned `revision` as `expected_revision` when continuing a file query.
Revisions use filesystem size and timestamps, not a full source checksum. Directory revisions
protect the selected name listing, while individual file revisions are reported separately.

Record pages contain at most 100 entries. Search positions refer to zero-based file order,
independently of the XML `index` attribute. `find_spectra` evaluates up to `scan_limit` records
after `start_index`, plus one lookahead record. The default budget is 10,000, with a maximum
of 100,000. A page with no matches can still have a `next_index`. Continue with unchanged
filters until `exhausted` is true.

Array and peak pages contain at most 1,000 values or pairs. Their positions refer to the
original arrays, including when coordinate bounds exclude some points. A null `next_index`
means no matching points remain. Arrays are returned in their recorded order without
smoothing, normalization, peak picking, or downsampling.

`get_array` exposes values in original units and reports the decoded `dtype`. Ordinary arrays
retain the stored numeric type. Numpress reconstructs float64 values. Nonfinite floats use
explicit `NaN`, `Infinity`, and `-Infinity` strings.

All array and paired-point tools return integers within `[-(2**53-1), 2**53-1]` as JSON
integers. Larger integers use exact decimal strings to prevent rounding by clients that
parse JSON numbers as doubles. Use the reported dtype to interpret these strings. Float32
values are represented by their exact numerical value as JSON floats, with dtype recorded
separately because JSON has no float32 type.

Paired points report `coordinate_dtype` and `intensity_dtype`. Chromatogram coordinates
remain in seconds. Conversion from other time units uses float64, while `get_array` retains
the original time values and type. The paired tools reject nonfinite coordinates or
intensities and mismatched lengths. Encoded exports retain original binary representations.

## Inventories and comparisons

`summarize_run` scans recorded metadata and reports counts by MS level, polarity, spectrum
representation, array type, and compression. It includes declared empty-array counts,
missing retention times, recorded time ranges, multi-scan counts, and observed isolation
windows. At most 100 distinct isolation windows are returned, with explicit truncation.

Timing statistics use the first scan of each consecutive spectrum. Missing first-scan times
break adjacency. The largest nonnegative gap and backward-time count are descriptive values,
without an assumed threshold for an abnormal run. Summaries do not decode intensities or
compute new chromatograms, and they do not establish scientific quality.

`compare_runs` reports exact differences between inventories and instrument metadata. It
performs no spectrum matching, retention-time alignment, signal comparison, or equivalence
testing. Matching metadata does not imply matching measurements.

## Long operations

Start a background operation with its tool arguments:

```json
{
  "operation": "summarize_run",
  "arguments": {"file": "run.mzML.gz"}
}
```

Use the returned `job_id` with `get_job`. The response reports `queued`, `running`, `completed`,
`failed`, or `cancelled`, plus the current stage and completed units. Stage counters describe
records or XML-offset checks, not a percentage, and can reset when the stage changes.

Two background workers share at most eight retained jobs. Completed jobs expire after 15
minutes, or can be discarded with `release_job`. Job results do not survive a server restart.
Releasing a job does not remove an exported artifact. Summary caching retains serialized
metadata only, bounded to 2 MiB and 16 entries, with invalidation by file revision.

Cancellation is cooperative between records, XML validation events, and export writes.
Reader initialization, decompression, and a single array decode can delay cancellation.
A cancellation arriving after export publication can return a completed job with its artifact.
Server shutdown requests cancellation and waits for worker cleanup.

## Exports and companion packages

Export explicit record IDs with `export_records`, optionally through `start_job`. Each export
uses a generated filename and never replaces another file. Missing or duplicate source IDs,
source revision changes, cancellation before publication, and writes exceeding 100 MiB leave
no published artifact. The source file is never modified.

Record metadata includes a `structure` tree that retains nested acquisition terms, user
parameters, and references, with binary arrays represented separately.

The format is `mzmlpy-records-jsonl`, version 1. Its first line contains a manifest with file
revision, package version, requested IDs, vocabularies, software, acquisition and processing metadata,
and the binary representation. Subsequent lines contain selected records in file order,
metadata, and original encoded binary text with its encoding parameters. Binary arrays are
not decoded or processed. The result includes a local path, byte count, SHA-256 checksum, and
an MCP export URI.

The manifest's `record_list` preserves enclosing list defaults such as `defaultDataProcessingRef`.

`read_export` pages JSONL lines. The export resource returns the manifest. Very large lines
must be consumed directly from the local artifact by a companion package. The format is an
mzmlpy interchange contract, not an assertion that Spectacular already has an importer.

Spectrum processing stays in Spectacular. This server does not calculate extracted ion
chromatograms, pick peaks, smooth signals, normalize intensities, align runs, match spectra,
or identify compounds. It does not render charts. Companion tools can consume the recorded
arrays or exports to perform those tasks.

## Resources and prompts

Four static MCP resources provide client context:

- `mzmlpy://capabilities`: enabled capabilities, codec availability, and limits.
- `mzmlpy://guide`: workflow, provenance, costs, and the processing boundary.
- `mzmlpy://units`: unit conventions and numeric representations.
- `mzmlpy://schemas`: the active tools' input and output schemas.

With exports enabled, `mzmlpy://exports/{artifact_id}` exposes an artifact manifest.
Three optional prompts guide user-selected workflows: `inspect_run`, `compare_acquisition`,
and `prepare_handoff`. Prompts do not run tools or execute processing themselves.

## Operational limits

Readers use `in_memory=False` and streaming gzip access, with automatic use of embedded
indexes. Each request opens its own reader. Plain files may need an index scan on open.
Gzip queries and later pages can rescan earlier XML. Reading chromatogram metadata can pass
the spectrum list. Page limits do not bound total I/O, elapsed time, or a single record's size.
Array paging decodes full arrays before selecting values.

Validation checks structure, references, counts, and array metadata, with explicit binary and
XML offset options. It is not full XSD, ontology, or embedded gzip index validation.
`issue_limit` bounds returned findings, not full-file work or internal validator storage.
Serialized result envelopes are limited to 256 KiB before MCP encoding.

Use trusted local files in directories that are not being modified concurrently. Resolved-path
checks are not an operating-system sandbox. Exports require a trusted writable output directory.
The server never follows external locations declared inside source metadata.
