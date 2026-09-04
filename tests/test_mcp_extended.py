"""Integration coverage for metadata inventories, jobs, discovery and lossless exports."""

import base64
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from mzmlpy import Mzml, Spectrum, SpectrumFilter
from mzmlpy._mcp_runtime import JobManager, OperationCancelled, ResultCache
from mzmlpy._progress import _progress, checkpoint
from mzmlpy.mcp import MzmlTools

DATA = Path(__file__).parent / "data"


@pytest.fixture
def service(tmp_path: Path):
    root = tmp_path / "data"
    root.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    shutil.copyfile(DATA / "example.mzML", root / "run.mzML")
    shutil.copyfile(DATA / "example.mzML.gz", root / "run.mzML.gz")
    tools = MzmlTools(root, output)
    try:
        yield tools
    finally:
        tools.close()


def test_discovery_pages_and_directory_changes(service: MzmlTools) -> None:
    (service.root / "nested").mkdir()
    (service.root / "ignore.txt").write_text("not mzML")
    first = service.list_files(limit=1)
    assert first["entries"][0]["file"] == "nested"
    assert first["entries"][0]["is_directory"]
    second = service.list_files(start_index=first["next_index"], expected_revision=first["revision"])
    assert [item["file"] for item in second["entries"]] == ["run.mzML", "run.mzML.gz"]
    assert service.list_files(pattern="*.gz")["entries"][0]["file"] == "run.mzML.gz"
    (service.root / "another").mkdir()
    with pytest.raises(ValueError, match="changed"):
        service.list_files(expected_revision=first["revision"])
    with pytest.raises(ValueError, match="inside"):
        service.list_files("..")


def test_metadata_sections_preserve_timezone_and_processing_history(service: MzmlTools) -> None:
    path = service.root / "run.mzML"
    text = path.read_text().replace(
        'startTimeStamp="2007-06-27T15:23:45.00035"', 'startTimeStamp="2007-06-27T15:23:45.00035+02:00"'
    )
    path.write_text(text)
    for section in [
        "run",
        "file_description",
        "instruments",
        "software",
        "samples",
        "processing",
        "scan_settings",
        "parameter_groups",
        "vocabularies",
        "record_lists",
    ]:
        result = service.get_metadata(path.name, section=section)
        assert result.data["section"] == section
        assert isinstance(result.data["items"], list)
    run = service.get_metadata(path.name).data["items"][0]
    assert run["attributes"]["startTimeStamp"].endswith("+02:00")
    processing = service.get_metadata(path.name, section="processing").data["items"]
    assert processing and "processingMethod" in json.dumps(processing)


def test_summary_is_metadata_only_and_cache_tracks_revision(service: MzmlTools) -> None:
    path = service.root / "run.mzML"
    first = service.summarize_run(path.name)
    assert first.data["spectrum_count"] == 4
    assert first.data["chromatogram_count"] == 2
    assert sum(first.data["ms_levels"].values()) == 4
    assert first.data["binary_arrays_decoded"] is False
    # Returning a mutable result must not allow a client to corrupt the cached snapshot.
    first.data["ms_levels"].clear()
    assert service.summarize_run(path.name).data["ms_levels"]
    text = path.read_text().replace('value="353.43"', 'value="351.43"')
    path.write_text(text + "\n")
    assert service.summarize_run(path.name).revision != first.revision
    with pytest.raises(ValueError, match="changed"):
        service.summarize_run(path.name, expected_revision=first.revision)
    import re

    path.write_text(re.sub(r"<binary>.*?</binary>", "<binary>invalid!!!</binary>", text, flags=re.S))
    assert service.summarize_run(path.name).data["spectrum_count"] == 4


def test_comparison_reports_only_metadata_differences(service: MzmlTools) -> None:
    assert service.compare_runs(["run.mzML", "run.mzML.gz"])["differences"] == {}
    path = service.root / "run.mzML"
    path.write_text(path.read_text().replace('name="LCQ Deca"', 'name="Other instrument"'))
    result = service.compare_runs([path.name, "run.mzML.gz"])
    assert "instruments" in result["differences"]
    with pytest.raises(ValueError, match="distinct"):
        service.compare_runs([path.name, str(path)])


def test_batches_and_chromatogram_discovery(service: MzmlTools) -> None:
    result = service.get_spectra("run.mzML.gz", ["scan=20", "missing", "scan=19"])
    assert [item["id"] for item in result.data["spectra"]] == ["scan=20", "scan=19"]
    assert result.data["missing_ids"] == ["missing"]
    assert result.data["spectra"][0]["precursors"][0]["activation"]
    assert "binaryDataArrayList" not in json.dumps(result.data["spectra"][0]["structure"])
    first = service.list_chromatograms("run.mzML.gz", limit=1)
    second = service.list_chromatograms("run.mzML.gz", start_index=first.data["next_index"])
    assert first.data["chromatograms"][0]["id"] == "tic"
    assert second.data["chromatograms"][0]["id"] == "sic"
    assert second.data["next_index"] is None


def test_arbitrary_array_values_and_units(service: MzmlTools) -> None:
    result = service.get_array("run.mzML", "tic", 0, kind="chromatogram", start_index=2, limit=2)
    assert result.data["values"] == [2.0, 3.0]
    assert result.data["next_index"] == 4
    assert result.data["metadata"]["terms"][-1]["unit_name"] == "second"
    with pytest.raises(ValueError, match="array_index"):
        service.get_array("run.mzML", "scan=19", 99)


def test_raw_exports_round_trip_binary_and_never_modify_source(service: MzmlTools) -> None:
    before = (service.root / "run.mzML").read_bytes()
    exported = service.export_records("run.mzML", ["scan=20", "scan=19"])
    artifact = Path(exported.data["path"])
    content = artifact.read_bytes()
    assert exported.data["sha256"] == hashlib.sha256(content).hexdigest()
    lines = [json.loads(line) for line in content.splitlines()]
    assert lines[0]["manifest"]["processing_applied"] is False
    assert lines[0]["manifest"]["software"]
    assert lines[0]["manifest"]["file_description"]
    assert lines[0]["manifest"]["record_list"]["attributes"]["defaultDataProcessingRef"] == "pwiz_processing"
    assert [record["id"] for record in lines[1:]] == ["scan=19", "scan=20"]
    with Mzml(service.root / "run.mzML") as reader:
        for record in lines[1:]:
            original = reader.spectra[record["id"]]
            for expected, actual in zip(original.binary_arrays, record["arrays"], strict=True):
                assert base64.b64decode(actual["encoded_binary"]) == base64.b64decode(
                    expected.element.find(f"{expected.ns}binary").text
                )
    assert (service.root / "run.mzML").read_bytes() == before
    page = service.read_export(exported.data["artifact_id"])
    assert page["next_line"] == 1
    assert "manifest" in page["lines"][0]
    assert service.read_export(exported.data["artifact_id"], start_line=1, limit=2)["next_line"] is None
    second = service.export_records("run.mzML", ["scan=19"])
    assert second.data["artifact_id"] != exported.data["artifact_id"]
    assert artifact.exists()


def test_chromatogram_export_preserves_nested_acquisition_metadata(service: MzmlTools) -> None:
    path = service.root / "run.mzML"
    tree = ET.parse(path)
    ns = "{http://psi.hupo.org/ms/mzml}"
    chromatogram = tree.find(f".//{ns}chromatogram[@id='sic']")
    assert chromatogram is not None
    ET.SubElement(chromatogram, f"{ns}userParam", {"name": "acquisition note", "value": "retain me"})
    mzml = tree.find(f"{ns}mzML")
    assert mzml is not None
    ET.ElementTree(mzml).write(path, encoding="utf-8", xml_declaration=True)
    result = service.export_records(path.name, ["sic"], kind="chromatogram")
    lines = Path(result.data["path"]).read_text().splitlines()
    record = json.loads(lines[1])
    metadata = record["metadata"]
    assert metadata["user_params"][0]["value"] == "retain me"
    children = metadata["structure"]["children"]
    assert {"precursor", "product", "userParam"} <= {child["tag"] for child in children}
    assert all(child["tag"] != "binaryDataArrayList" for child in children)
    assert service.get_chromatogram(path.name, "sic").data["metadata"] == metadata


def test_compressed_record_list_defaults_are_available(service: MzmlTools) -> None:
    result = service.get_metadata("run.mzML.gz", section="record_lists")
    assert [item["tag"] for item in result.data["items"]] == ["spectrumList", "chromatogramList"]
    assert all(item["attributes"]["defaultDataProcessingRef"] == "pwiz_processing" for item in result.data["items"])
    result = service.export_records("run.mzML.gz", ["sic"], kind="chromatogram")
    header = service.read_export(result.data["artifact_id"])["lines"][0]["manifest"]
    assert header["record_list"]["tag"] == "chromatogramList"


def test_failed_export_leaves_no_partial_artifact(service: MzmlTools) -> None:
    assert service.output_dir is not None
    with pytest.raises(ValueError, match="Missing"):
        service.export_records("run.mzML", ["scan=19", "missing"])
    assert not list(service.output_dir.iterdir())
    with pytest.raises(ValueError, match="Invalid"):
        service.read_export("../run.mzML")
    without = MzmlTools(service.root)
    try:
        with pytest.raises(ValueError, match="output directory"):
            without.export_records("run.mzML", ["scan=19"])
    finally:
        without.close()


def wait_job(service: MzmlTools, job_id: str):
    until = time.monotonic() + 10
    while time.monotonic() < until:
        result = service.get_job(job_id)
        if result.status not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    pytest.fail("Job did not finish")


def test_jobs_complete_fail_and_release(service: MzmlTools) -> None:
    job = service.start_job("summarize_run", {"file": "run.mzML"})
    result = wait_job(service, job.job_id)
    assert result.status == "completed"
    assert result.result["data"]["spectrum_count"] == 4
    assert service.release_job(job.job_id) == {"released": True}
    with pytest.raises(ValueError, match="Unknown"):
        service.get_job(job.job_id)
    failed = service.start_job("validate_file", {"file": "missing.mzML"})
    assert wait_job(service, failed.job_id).status == "failed"
    with pytest.raises(ValueError):
        service.start_job("summarize_run", {"bogus": 1})


def test_job_cancellation_and_capacity() -> None:
    manager = JobManager()
    started = threading.Event()
    unblock = threading.Event()

    def work():
        started.set()
        unblock.wait(5)
        checkpoint("working", 1)
        return {"done": True}

    try:
        jobs = [manager.submit("test", work) for _ in range(8)]
        assert started.wait(5)
        with pytest.raises(ValueError, match="Eight"):
            manager.submit("test", work)
        cancelled = manager.cancel(jobs[0].job_id)
        assert cancelled.cancel_requested
        with pytest.raises(ValueError, match="Cancel"):
            manager.release(jobs[0].job_id)
        unblock.set()
        until = time.monotonic() + 5
        while manager.get(jobs[0].job_id).status in {"queued", "running"} and time.monotonic() < until:
            time.sleep(0.01)
        assert manager.get(jobs[0].job_id).status == "cancelled"
    finally:
        unblock.set()
        manager.close()


def test_validation_and_export_have_cooperative_checkpoints(service: MzmlTools) -> None:
    def stop(stage: str, count: int):
        if "validating" in stage or "export" in stage:
            raise OperationCancelled("stop")

    token = _progress.set(stop)
    try:
        with pytest.raises(OperationCancelled):
            service.validate_file("run.mzML")
        with pytest.raises(OperationCancelled):
            service.export_records("run.mzML", ["scan=19"])
    finally:
        _progress.reset(token)
    assert not list(service.output_dir.iterdir())


def test_cache_eviction_and_copy_isolation() -> None:
    cache = ResultCache(max_bytes=50)
    cache.put("a", {"x": [1]})
    value = cache.get("a")
    value["x"].append(2)
    assert cache.get("a") == {"x": [1]}
    cache.put("b", {"long": "x" * 35})
    assert cache.get("a") is None


def test_mobility_and_spectrum_type_filters_keep_quantities_distinct() -> None:
    spectrum = Spectrum(
        ET.fromstring("""<spectrum id="x"><cvParam accession="MS:1000127"/>
      <scanList><scan><cvParam accession="MS:1002815" value="1.1"/>
      <cvParam accession="MS:1001581" value="-45"/></scan></scanList></spectrum>""")
    )
    assert SpectrumFilter(spectrum_type="centroid", faims_voltage=(-50, -40)).matches(spectrum)
    assert not SpectrumFilter(spectrum_type="profile").matches(spectrum)
    assert not SpectrumFilter(mobility_type="drift_time", ion_mobility=(1, 2)).matches(spectrum)
    with pytest.raises(ValueError, match="explicit"):
        SpectrumFilter(ion_mobility=(1, 2))
