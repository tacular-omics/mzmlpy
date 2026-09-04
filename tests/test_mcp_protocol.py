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
            }
            for tool in listing.tools:
                assert tool.annotations.read_only_hint
                assert not tool.annotations.open_world_hint
                assert tool.output_schema
            for name, extra in [
                ("inspect_file", {}),
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
