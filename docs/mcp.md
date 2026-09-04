# MCP server

The optional MCP integration lets AI applications inspect local mzML files through five
read-only tools. It is a development feature following 0.8.0 and is not included in that release.
Install from a checkout containing this feature:

```bash
pip install ".[mcp]"
python -m mzmlpy mcp --root /absolute/path/to/data
```

The `mcp` extra installs the official MCP Python SDK. The base package still requires only
NumPy, and importing `mzmlpy` does not import the SDK. Add `numpress` or `zstd` to the extras
when those codecs are needed, for example `pip install ".[mcp,numpress,zstd]"`.

## Connect a client

Configure an MCP client that supports local stdio servers to launch the Python interpreter
where you installed the extra. A typical client configuration is:

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

On Windows, use the environment's `Scripts/python.exe` path. The directory must already
exist. The server communicates over stdin and stdout. Diagnostics go to stderr.

Each tool takes a file path relative to the configured directory, or an absolute path within
it. Parent traversal and symlinks that resolve outside the directory are rejected. The server
opens no network listener and creates no extracted caches or index sidecars. The chosen MCP
client controls how returned data is subsequently used or sent to a model provider.

## Tools

| Tool | Purpose | Main controls |
|---|---|---|
| `inspect_file` | File metadata, reader-reported counts, instrument terms, software, first 100 chromatogram IDs | `file` |
| `validate_file` | Structural checks and optional binary or XML offset checks | `decode_binary`, `check_index`, `issue_limit` |
| `find_spectra` | Search metadata with AND criteria, without binary decoding | MS level, retention time, polarity, precursor m/z, `limit`, `scan_limit` |
| `get_spectrum` | Exact native ID metadata and optional peak pairs | `spectrum_id`, `include_peaks`, m/z bounds, `start_index`, `limit` |
| `get_chromatogram` | Exact chromatogram ID and time/intensity pairs | `chromatogram_id`, time bounds, `start_index`, `limit` |

Every result contains `file`, a filesystem `revision`, and a `data` object. Instrument and
precursor terms retain their CV accessions and unit metadata. File metadata is untrusted data,
including free text. It must not be treated as instructions to an assistant.

Example `find_spectra` arguments for positive MS2 spectra between five and eight minutes whose
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

Retention-time bounds use seconds and match any scan. All bounds are inclusive. Precursor
filtering uses isolation-window overlap, with selected-ion m/z fallback when no usable window
exists. This identifies acquisition records, without identifying their compounds.

## Paging and units

`find_spectra` returns at most 100 spectra per call. `start_index` and `next_index` refer to
zero-based positions in file order, independently of the spectrum's XML `index` attribute.
Use `next_index` as the next `start_index`, with the same filters. Supply the returned
`revision` as `expected_revision` to detect file changes between pages.

A search evaluates at most `scan_limit` spectra after its starting position, plus one lookahead
record to establish whether another page exists. The default is 10,000, with a maximum of
100,000. A page with no matches can still have a `next_index`. Continue until `exhausted` is
true. An exhausted result means the query reached the end, not that the file was validated.

Peak and chromatogram pages contain `[coordinate, intensity]` pairs in original array order.
They return at most 1,000 points per call, with a default of 100. They use original array
positions for `start_index` and `next_index`, even when coordinate bounds exclude some points.
A null `next_index` means no matching points remain. `total_points` counts the full array,
while `returned_points` counts the current page. No downsampling or intensity normalization
is applied. `get_spectrum` returns metadata only unless `include_peaks=true`.

Spectrum coordinates use m/z. Chromatogram times are normalized to seconds, with the source
unit also reported. Missing or unsupported chromatogram time units are errors. Intensity
units are returned as declared, or null when unspecified. Mismatched array lengths and
nonfinite array values are errors rather than silently altered measurements.

## Cost and validation scope

Readers use `in_memory=False` and streaming gzip access, with automatic use of embedded gzip
indexes. Each call opens its own reader. Plain files may need an index scan on open, and gzip
queries or later search pages can rescan earlier XML. Reading chromatogram metadata can require
passing the spectrum list. Search limits bound records evaluated after the start position,
not total I/O, elapsed time, or a single record's size.

Array paging decodes full coordinate and intensity arrays before selecting points. A small
page does not bound decoding memory. Client cancellation may wait for synchronous file work
to finish. Use this local server with trusted files in a directory that other processes are
not modifying concurrently. Path checks are not an operating-system sandbox.

`validate_file` scans the full file. The default checks structure, counts, references, and array
metadata. Binary decoding and XML offset checks are explicit options. It does not perform full
XSD or ontology validation, or validate the embedded gzip index. `issue_limit` caps returned
findings at 1,000, without limiting internal validation work or storage. `issue_count`,
`issues_truncated`, `valid`, and `complete` always describe the full report.

Serialized result envelopes are limited to 256 KiB before MCP encoding. Oversized results fail
with an actionable error. Reduce the page size or use the Python API for unusually large
metadata or full arrays.
