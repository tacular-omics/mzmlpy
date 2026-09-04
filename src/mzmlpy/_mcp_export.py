"""Atomic exports of recorded mzML data, without spectral processing."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from . import Mzml, __version__
from ._mcp_metadata import (
    array_metadata,
    chromatogram_metadata,
    metadata_tree,
    record_list_attributes,
    spectrum_metadata,
)
from ._mcp_types import ArtifactData, ExportPage
from ._progress import checkpoint

if TYPE_CHECKING:
    from .mcp import MzmlTools


def export_records(service: "MzmlTools", path: Path, revision: str, record_ids: list[str], kind: str) -> ArtifactData:
    """Publish a complete export only after verifying every requested ID and the source revision."""
    assert service.output_dir is not None
    identifier = uuid4().hex
    temporary = service.output_dir / f".{identifier}.partial"
    destination = service.output_dir / f"{identifier}.jsonl"
    digest = hashlib.sha256()
    byte_count = 0
    found: set[str] = set()
    wanted = set(record_ids)
    try:
        with temporary.open("xb") as output, Mzml(path, in_memory=False, gzip_mode="stream") as reader:

            def write_line(value: Any) -> None:
                nonlocal byte_count
                chunks = json.JSONEncoder(allow_nan=False, ensure_ascii=False).iterencode(value)
                for chunk in chunks:
                    checkpoint("exporting records", len(found))
                    data = chunk.encode("utf-8")
                    byte_count += len(data)
                    if byte_count > 104_857_599:
                        raise ValueError("Export exceeds 100 MiB. Select fewer records")
                    output.write(data)
                    digest.update(data)
                output.write(b"\n")
                digest.update(b"\n")
                byte_count += 1

            header = {
                "format": "mzmlpy-records-jsonl",
                "format_version": 1,
                "package_version": __version__,
                "file": path.relative_to(service.root).as_posix(),
                "revision": revision,
                "kind": kind,
                "record_list": record_list_attributes(path, kind),
                "requested_ids": record_ids,
                "record_order": "file order",
                "binary_representation": "Original encoded binary text and declared encoding metadata.",
                "processing_applied": False,
                "mzml_version": reader.version,
                "run_attributes": dict(reader.run.element.attrib) if reader.run else None,
                "vocabularies": [cv._asdict() for cv in reader.cvs.values()],
                "instruments": [metadata_tree(item) for item in reader.instrument_configurations.values()],
                "software": [metadata_tree(item) for item in reader.softwares.values()],
                "file_description": metadata_tree(reader.file_description) if reader.file_description else None,
                "samples": [metadata_tree(item) for item in reader.samples.values()],
                "scan_settings": [metadata_tree(item) for item in reader.scan_settings.values()],
                "parameter_groups": [metadata_tree(item) for item in reader.referenceable_param_groups.values()],
                "processing_history": [metadata_tree(item) for item in reader.data_processes.values()],
                "source_files": [metadata_tree(item) for item in reader.file_description.source_files]
                if reader.file_description
                else [],
            }
            write_line({"manifest": header})
            lookup = reader.spectra if kind == "spectrum" else reader.chromatograms
            for position, record in enumerate(lookup):
                checkpoint("scanning export source", position)
                if record.id not in wanted:
                    continue
                if record.id in found:
                    raise ValueError(f"Duplicate native ID {record.id!r} in export source")
                found.add(record.id)
                arrays = []
                for array in record.binary_arrays:
                    binary = array.element.find(f"{array.ns}binary")
                    arrays.append(
                        {**array_metadata(array), "encoded_binary": binary.text if binary is not None else None}
                    )
                metadata = spectrum_metadata(record) if kind == "spectrum" else chromatogram_metadata(record)
                write_line(
                    {"kind": kind, "id": record.id, "position": position, "metadata": metadata, "arrays": arrays}
                )
            if found != wanted:
                raise ValueError(f"Missing record IDs: {sorted(wanted - found)}")
            service._source(str(path), revision)
            checkpoint("publishing export", len(found))
            output.flush()
            os.fsync(output.fileno())
        # Link publication never replaces an existing artifact, even on a name collision.
        os.link(temporary, destination)
        return {
            "artifact_id": identifier,
            "path": str(destination),
            "uri": f"mzmlpy://exports/{identifier}",
            "format": "mzmlpy-records-jsonl",
            "format_version": 1,
            "record_count": len(found),
            "byte_count": byte_count,
            "sha256": digest.hexdigest(),
            "processing_applied": False,
        }
    finally:
        temporary.unlink(missing_ok=True)


def read_export(output_dir: Path, artifact_id: str, start_line: int, limit: int) -> ExportPage:
    if not re.fullmatch(r"[0-9a-f]{32}", artifact_id):
        raise ValueError("Invalid artifact ID")
    path = output_dir / f"{artifact_id}.jsonl"
    if path.is_symlink() or not path.resolve().is_relative_to(output_dir):
        raise ValueError("Artifact must remain inside the configured output directory")
    values = []
    with path.open("rb") as handle:
        for index in range(start_line + limit + 1):
            checkpoint("reading export", index)
            line = handle.readline(262_145)
            if not line:
                return {"artifact_id": artifact_id, "lines": values, "next_line": None}
            if not line.endswith(b"\n"):
                raise ValueError("Export line is too large for MCP. Read the local artifact with a companion package")
            if index == start_line + limit:
                return {"artifact_id": artifact_id, "lines": values, "next_line": index}
            if index >= start_line:
                values.append(json.loads(line))
    raise AssertionError("Unreachable")
