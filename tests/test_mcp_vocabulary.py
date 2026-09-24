"""Guard the MCP tool schemas against vocabulary drift from the reader API and tacular.types.

Walks every tool's input and output schema (following $defs), bans old names, checks the
Da/ppm switch naming, rejects unknown arguments, and keeps find_spectra row keys aligned
with Spectrum attributes.
"""

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest

pytest.importorskip("mcp")
from mcp import Client  # noqa: E402

from mzmlpy import Spectrum  # noqa: E402
from mzmlpy.constants import ToleranceUnit  # noqa: E402
from mzmlpy.mcp import create_server  # noqa: E402

DATA = Path(__file__).parent / "data"

BANNED = re.compile(
    r"^(unit|tolerance_type|.*_tolerance_type|retention_time.*|missing_retention_time|inverse_reduced.*|"
    r"ion_mobility_.*|target_mz|scan_start_time|ce|tic|TIC|time|one_over_k0.*|mz_begin|mz_end|window_group|"
    r"monoisotopic_mz)$"
)
# Output-only unit descriptors of stored chromatograms; they are not Da/ppm switches.
ALLOWED_UNIT_NAMES = {"coordinate_unit", "source_time_unit", "intensity_unit"}
# find_spectra row keys that are not Spectrum attributes.
MCP_ONLY_ROW_KEYS = {"position"}

# Minimal arguments per tool. Values only need the right shape: the bogus argument must be
# rejected before the tool body runs.
MINIMAL_ARGS: dict[str, dict[str, Any]] = {
    "server_info": {},
    "list_files": {},
    "inspect_file": {"file": "example.mzML"},
    "get_metadata": {"file": "example.mzML", "section": "processing"},
    "validate_file": {"file": "example.mzML"},
    "summarize_run": {"file": "example.mzML"},
    "compare_runs": {"files": ["example.mzML", "example.mzML.gz"]},
    "find_spectra": {"file": "example.mzML"},
    "get_spectrum": {"file": "example.mzML", "spectrum_id": "scan=19"},
    "get_spectra": {"file": "example.mzML", "spectrum_ids": ["scan=19"]},
    "list_chromatograms": {"file": "example.mzML"},
    "get_chromatogram": {"file": "example.mzML", "chromatogram_id": "tic"},
    "get_array": {"file": "example.mzML", "record_id": "scan=19", "array_index": 0},
    "start_job": {"operation": "summarize_run", "arguments": {"file": "example.mzML"}},
    "get_job": {"job_id": "absent"},
    "cancel_job": {"job_id": "absent"},
    "release_job": {"job_id": "absent"},
    "export_records": {"file": "example.mzML", "record_ids": ["scan=19"]},
    "read_export": {"artifact_id": "absent"},
}


def schema_props(schema: dict[str, Any], path: str) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield (path, name, subschema) for every property, following each $ref into $defs once."""
    defs = schema.get("$defs", {})
    seen: set[str] = set()

    def walk(node: Any, where: str) -> Iterator[tuple[str, str, dict[str, Any]]]:
        if not isinstance(node, dict):
            return
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name not in seen:
                seen.add(name)
                yield from walk(defs.get(name, {}), f"{where}<{name}>")
        for key, value in (node.get("properties") or {}).items():
            yield f"{where}.{key}", key, value
            yield from walk(value, f"{where}.{key}")
        for key in ("items", "anyOf", "oneOf", "allOf", "additionalProperties"):
            value = node.get(key)
            for child in value if isinstance(value, list) else [value]:
                yield from walk(child, where)

    yield from walk(schema, path)


def enum_values(schema: dict[str, Any]) -> set[Any]:
    values: set[Any] = set()
    for option in [schema, *schema.get("anyOf", [])]:
        values |= set(option.get("enum", []))
        if "const" in option:
            values.add(option["const"])
    return values


@pytest.fixture(scope="module")
def tools(tmp_path_factory: pytest.TempPathFactory) -> list[Any]:
    server = create_server(DATA, tmp_path_factory.mktemp("exports"))
    return asyncio.run(server.list_tools())


def _properties(tools: list[Any], *, kinds: tuple[str, ...] = ("in", "out")) -> list[tuple[str, str, dict[str, Any]]]:
    found = []
    for tool in tools:
        schemas = {"in": tool.input_schema, "out": tool.output_schema or {}}
        for kind in kinds:
            found.extend(schema_props(schemas[kind], f"{tool.name}:{kind}"))
    return found


def test_no_banned_names(tools: list[Any]) -> None:
    banned = sorted(path for path, name, _ in _properties(tools) if BANNED.match(name))
    assert banned == []


def test_tolerance_switches(tools: list[Any]) -> None:
    for path, name, schema in _properties(tools):
        if "tolerance" in name and name.endswith("unit"):
            assert name == "tolerance_unit" or name.endswith("_tolerance_unit"), path
            assert enum_values(schema) <= set(get_args(ToleranceUnit)), path
    inputs = [
        path
        for path, name, _ in _properties(tools, kinds=("in",))
        if name.endswith("unit") and not name.endswith("tolerance_unit")
    ]
    assert inputs == []
    outputs = {
        name
        for _, name, _ in _properties(tools, kinds=("out",))
        if name.endswith("unit") and not name.endswith("tolerance_unit")
    }
    assert outputs <= ALLOWED_UNIT_NAMES


def test_unknown_argument_rejected(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with asyncio.timeout(20), Client(create_server(DATA, tmp_path)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == set(MINIMAL_ARGS), "add new tools to MINIMAL_ARGS"
            for name, args in MINIMAL_ARGS.items():
                result = await client.call_tool(name, {**args, "__bogus__": 1})
                assert result.is_error, name
                assert "__bogus__" in result.content[0].text, name
            # A renamed filter must fail loudly instead of returning unfiltered spectra.
            result = await client.call_tool("find_spectra", {"file": "example.mzML", "mz_range": [100, 200]})
            assert result.is_error
            assert "mz_range" in result.content[0].text

    asyncio.run(exercise())


def test_record_keys_match_library() -> None:
    async def exercise() -> None:
        async with asyncio.timeout(20), Client(create_server(DATA)) as client:
            result = await client.call_tool("find_spectra", {"file": "example.mzML", "limit": 4})
            assert not result.is_error, result
            rows = result.structured_content["data"]["spectra"]
            assert rows
            public = {name for name in dir(Spectrum) if not name.startswith("_")}
            for row in rows:
                assert set(row) - MCP_ONLY_ROW_KEYS <= public, set(row) - MCP_ONLY_ROW_KEYS - public
            summary = await client.call_tool("summarize_run", {"file": "example.mzML"})
            assert {"rt_min", "rt_max", "rt_span", "missing_rt"} <= set(summary.structured_content["data"])

    asyncio.run(exercise())
