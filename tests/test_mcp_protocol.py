"""Test tool discovery, structured results, errors, and the real stdio entry point."""

import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters  # noqa: E402

from mzmlpy.mcp import create_server  # noqa: E402

DATA = Path(__file__).parent / "data"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_protocol_tools(mode: str) -> None:
    async def exercise() -> None:
        async with asyncio.timeout(25), Client(create_server(DATA), mode=mode) as client:
            listing = await client.list_tools()
            assert {tool.name for tool in listing.tools} == {
                "inspect_file",
                "validate_file",
                "find_spectra",
                "get_spectrum",
                "get_chromatogram",
                "server_info",
                "list_files",
                "get_metadata",
                "summarize_run",
                "compare_runs",
                "get_spectra",
                "list_chromatograms",
                "get_array",
                "start_job",
                "get_job",
                "cancel_job",
                "release_job",
            }
            for tool in listing.tools:
                assert tool.annotations.read_only_hint == (tool.name not in {"start_job", "cancel_job", "release_job"})
                assert not tool.annotations.open_world_hint
                assert tool.output_schema
            for name, extra in [
                ("inspect_file", {}),
                ("summarize_run", {}),
                ("get_metadata", {"section": "processing"}),
                ("get_spectra", {"spectrum_ids": ["scan=19", "scan=20"]}),
                ("list_chromatograms", {"limit": 1}),
                ("get_array", {"record_id": "scan=19", "array_index": 0, "limit": 2}),
                ("validate_file", {"issue_limit": 1}),
                ("find_spectra", {"ms_level": 1, "limit": 1}),
                ("get_spectrum", {"spectrum_id": "scan=19", "include_peaks": True, "limit": 2}),
                ("get_chromatogram", {"chromatogram_id": "tic", "limit": 2}),
            ]:
                result = await client.call_tool(name, {"file": "example.mzML", **extra})
                assert not result.is_error, result
                assert result.structured_content["file"] == "example.mzML"
                assert result.structured_content["revision"]
                assert "data" in result.structured_content
            discovery = await client.call_tool("list_files", {"pattern": "example*"})
            assert not discovery.is_error, discovery
            comparison = await client.call_tool("compare_runs", {"files": ["example.mzML", "example.mzML.gz"]})
            assert not comparison.is_error, comparison
            assert comparison.structured_content["differences"] == {}
            resources = await client.list_resources()
            assert len(resources.resources) == 4
            for resource in resources.resources:
                result = await client.read_resource(resource.uri)
                assert result.contents
            prompts = await client.list_prompts()
            assert {item.name for item in prompts.prompts} == {"inspect_run", "compare_acquisition", "prepare_handoff"}
            prompt = await client.get_prompt("prepare_handoff", {"file": "example.mzML"})
            assert "Spectacular" in prompt.messages[0].content.text
            job = await client.call_tool(
                "start_job", {"operation": "summarize_run", "arguments": {"file": "example.mzML"}}
            )
            assert not job.is_error, job
            job_id = job.structured_content["job_id"]
            for _ in range(100):
                status = await client.call_tool("get_job", {"job_id": job_id})
                if status.structured_content["status"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(0.01)
            assert status.structured_content["status"] == "completed", status
            released = await client.call_tool("release_job", {"job_id": job_id})
            assert not released.is_error, released
            for name, args, message in [
                ("inspect_file", {"file": "../outside.mzML"}, "inside"),
                ("find_spectra", {"file": "example.mzML", "limit": 101}, "limit"),
                ("get_spectrum", {"file": "example.mzML", "spectrum_id": "absent"}, "absent"),
                ("inspect_file", {}, "file"),
            ]:
                result = await client.call_tool(name, args)
                assert result.is_error
                assert message in result.content[0].text

    asyncio.run(exercise())


def test_stdio_entry_point() -> None:
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mzmlpy", "mcp", "--root", str(DATA.resolve())],
        )
        async with asyncio.timeout(25), Client(parameters) as client:
            result = await client.call_tool(
                "get_chromatogram",
                {
                    "file": "example.mzML.gz",
                    "chromatogram_id": "tic",
                    "limit": 2,
                },
            )
            assert not result.is_error, result
            assert result.structured_content["data"]["points"] == [[0.0, 15.0], [1.0, 14.0]]

    asyncio.run(exercise())


def test_export_tools_and_resource(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with asyncio.timeout(25), Client(create_server(DATA, tmp_path)) as client:
            tools = await client.list_tools()
            assert {"export_records", "read_export"} <= {tool.name for tool in tools.tools}
            exported = await client.call_tool("export_records", {"file": "example.mzML", "record_ids": ["scan=19"]})
            assert not exported.is_error, exported
            data = exported.structured_content["data"]
            resource = await client.read_resource(data["uri"])
            assert "manifest" in resource.contents[0].text
            read = await client.call_tool("read_export", {"artifact_id": data["artifact_id"], "start_line": 1})
            assert not read.is_error, read
            assert read.structured_content["lines"][0]["id"] == "scan=19"

    asyncio.run(exercise())
