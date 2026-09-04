import base64
import gzip
import json
import struct
from pathlib import Path

import pytest

from mzmlpy import Mzml, validate, write_indexed_gzip
from mzmlpy.__main__ import main


def record(identifier: str = "scan=1", payload: str | None = None, length: int = 2) -> str:
    if payload is None:
        payload = base64.b64encode(struct.pack("<dd", 100.0, 200.0)).decode()
    return (
        f'<spectrum id="{identifier}" index="0" defaultArrayLength="{length}">'
        '<cvParam accession="MS:1000511" name="ms level" value="1"/>'
        f'<binaryDataArrayList count="1"><binaryDataArray encodedLength="{len(payload)}">'
        '<cvParam accession="MS:1000523" name="64-bit float"/>'
        '<cvParam accession="MS:1000576" name="no compression"/>'
        '<cvParam accession="MS:1000514" name="m/z array"/>'
        f"<binary>{payload}</binary></binaryDataArray></binaryDataArrayList></spectrum>"
    )


def write_file(tmp_path: Path, body: str, *, count: int = 1, header: str = "", indexed: bool = False) -> Path:
    xml = (
        '<mzML xmlns="http://psi.hupo.org/ms/mzml" id="validation" version="1.1.0">'
        f'{header}<run id="r"><spectrumList count="{count}">{body}</spectrumList></run></mzML>'
    )
    if indexed:
        xml = '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml">' + xml
        offset = xml.index("<spectrum id=")
        index_offset = len(xml.encode())
        xml += (
            f'<indexList count="1"><index name="spectrum"><offset idRef="scan=1">{offset}</offset>'
            f"</index></indexList><indexListOffset>{index_offset}</indexListOffset></indexedmzML>"
        )
    path = tmp_path / "input.mzML"
    path.write_text(xml)
    return path


def codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


@pytest.mark.parametrize("compressed", [False, True])
def test_valid_file_structural_and_binary_checks(tmp_path: Path, compressed: bool) -> None:
    path = write_file(tmp_path, record(), indexed=True)
    if compressed:
        output = path.with_suffix(".mzML.gz")
        output.write_bytes(gzip.compress(path.read_bytes()))
        path = output
    report = validate(path)
    assert report.valid and report.complete
    assert report.spectrum_count == 1
    assert report.chromatogram_count == report.arrays_decoded == report.index_entries_checked == 0
    report = validate(path, decode_binary=True, check_index=True)
    assert report.valid
    assert report.arrays_decoded == report.index_entries_checked == 1
    assert json.loads(json.dumps(report.to_dict()))["valid"] is True


def test_binary_decoding_is_opt_in(tmp_path: Path) -> None:
    path = write_file(tmp_path, record(payload="!!!!!!!!"))
    assert validate(path).valid
    report = validate(path, decode_binary=True)
    assert not report.valid
    assert "decode_error" in codes(report)
    assert "spectrum[scan=1]/binaryDataArray[0]" in report.issues[0].location


def test_decode_checks_lengths_and_per_array_override(tmp_path: Path) -> None:
    path = write_file(tmp_path, record(length=3))
    assert "array_length_mismatch" in codes(validate(path, decode_binary=True))
    path.write_text(
        path.read_text().replace("<binaryDataArray encodedLength=", '<binaryDataArray arrayLength="2" encodedLength=')
    )
    assert validate(path, decode_binary=True).valid


def test_report_accumulates_structural_findings(tmp_path: Path) -> None:
    body = record() + record()
    body = body.replace('<cvParam accession="MS:1000523" name="64-bit float"/>', "")
    body = body.replace("<spectrum id=", '<spectrum dataProcessingRef="missing" id=')
    path = write_file(tmp_path, body)
    report = validate(path)
    assert not report.valid
    assert {"count_mismatch", "duplicate_id", "missing_reference", "unsupported_or_missing_encoding"} <= codes(report)
    assert report.spectrum_count == 2


def test_validation_expands_parameter_groups(tmp_path: Path) -> None:
    group = (
        '<referenceableParamGroupList count="1"><referenceableParamGroup id="encoding">'
        '<cvParam accession="MS:1000523" name="64-bit float"/>'
        '<cvParam accession="MS:1000576" name="no compression"/>'
        "</referenceableParamGroup></referenceableParamGroupList>"
    )
    body = record().replace('<cvParam accession="MS:1000523" name="64-bit float"/>', "")
    body = body.replace(
        '<cvParam accession="MS:1000576" name="no compression"/>', '<referenceableParamGroupRef ref="encoding"/>'
    )
    path = write_file(tmp_path, body, header=group)
    assert validate(path, decode_binary=True).valid


def test_bad_index_ids_and_offsets_are_reported_without_repair(tmp_path: Path) -> None:
    path = write_file(tmp_path, record(), indexed=True)
    path.write_text(path.read_text().replace('idRef="scan=1"', 'idRef="missing"'))
    original = path.read_bytes()
    report = validate(path, check_index=True)
    assert {"index_ids_mismatch", "invalid_index_offset"} <= codes(report)
    assert path.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["input.mzML"]


def test_malformed_xml_returns_partial_report(tmp_path: Path) -> None:
    path = write_file(tmp_path, record())
    path.write_bytes(path.read_bytes()[:-7])
    report = validate(path)
    assert not report.complete and not report.valid
    assert report.spectrum_count == 1
    assert "parse_error" in codes(report)
    with pytest.raises(OSError):
        validate(tmp_path / "missing.mzML")


def test_reader_validation_preserves_cursor_and_supports_embedded(tmp_path: Path) -> None:
    path = write_file(tmp_path, record() + record("scan=2"), count=2)
    output = tmp_path / "indexed.mzML.gz"
    write_indexed_gzip(path, output)
    for source in (path, output):
        with Mzml(source, in_memory=False) as reader:
            assert reader.spectra.next().id == "scan=1"
            assert reader.validate(decode_binary=True).valid
            assert reader.spectra.next().id == "scan=2"


def test_cli_commands_and_exit_codes(tmp_path: Path, capsys) -> None:
    path = write_file(tmp_path, record())
    assert main(["validate", str(path), "--decode-binary"]) == 0
    assert json.loads(capsys.readouterr().out)["arrays_decoded"] == 1
    assert main(["inspect", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["spectrum_count"] == 1
    output = tmp_path / "cli.mzML.gz"
    assert main(["index-gzip", str(path), str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["output_path"] == str(output)
    path.write_text("<broken")
    assert main(["validate", str(path)]) == 1
    assert not json.loads(capsys.readouterr().out)["valid"]
    assert main(["validate", str(tmp_path / "absent")]) == 2
    assert "absent" in capsys.readouterr().err
