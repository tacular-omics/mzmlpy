"""Regression tests for the code-review fixes (items 1-9)."""

from datetime import timedelta
from io import BytesIO

import pytest

from mzmlpy import Mzml
from mzmlpy.elems.params import CvParam

EXAMPLE = "tests/data/example.mzML"


def test_construction_failure_closes_file_object(monkeypatch):
    """#1 — if metadata parsing raises, the FileInterface is closed so nothing leaks."""
    from mzmlpy import run
    from mzmlpy.file_interface import FileInterface

    closed = []
    orig_close = FileInterface.close

    def tracking_close(self):
        closed.append(True)
        orig_close(self)

    monkeypatch.setattr(FileInterface, "close", tracking_close)

    def boom(self):
        raise RuntimeError("simulated parse failure")

    monkeypatch.setattr(run.Mzml, "_parse_metadata", boom)

    with pytest.raises(RuntimeError):
        run.Mzml(EXAMPLE)

    assert closed, "FileInterface.close() must be called when metadata parsing fails"


def test_read_to_spec_end_truncated_raises_not_hangs():
    """#3 — a truncated element (no closing tag before EOF) raises instead of looping forever."""
    with Mzml(EXAMPLE) as reader:
        handler = reader._file_object.file_handler  # StandardMzml
        truncated = BytesIO(b"<spectrum id='x'>payload with no closing tag before EOF")
        with pytest.raises(ValueError):
            handler._read_to_spec_end(truncated)


def test_next_advances_and_reset():
    """#5 — next() is a real cursor that advances and can be reset."""
    with Mzml(EXAMPLE) as reader:
        lookup = reader.spectra
        first = lookup.next()
        second = lookup.next()
        assert first.id == "scan=19"
        assert second.id == "scan=20"
        assert first.id != second.id

        lookup.reset()
        assert lookup.next().id == first.id


def test_next_stops_at_end():
    """#5 — next() raises StopIteration once exhausted."""
    with Mzml(EXAMPLE) as reader:
        lookup = reader.spectra
        for _ in range(len(lookup)):
            lookup.next()
        with pytest.raises(StopIteration):
            lookup.next()


def test_negative_index_returns_from_end():
    """#8 — lookup[-1] mirrors list semantics, consistent with slicing."""
    with Mzml(EXAMPLE) as reader:
        n = len(reader.spectra)
        assert reader.spectra[-1].id == reader.spectra[n - 1].id
        assert reader.spectra[-1].id == "sample=1 period=1 cycle=22 experiment=1"
        assert reader.chromatograms[-1].id == "sic"


def _cv(value, unit_name):
    return CvParam(
        name="p",
        value=value,
        unit_accession=None,
        unit_name=unit_name,
        unit_cv_ref="MS",
        cv_ref="MS",
        accession="MS:1",
    )


def test_to_timedelta_non_time_unit_returns_none():
    """#7 — a non-time unit returns None rather than raising ValueError."""
    assert _cv("123.4", "m/z").to_timedelta is None


def test_to_timedelta_non_numeric_returns_none():
    """#7 — a non-numeric value returns None rather than raising."""
    assert _cv("not-a-number", "second").to_timedelta is None


def test_to_timedelta_valid_time_still_works():
    """#7 — legitimate time units still convert."""
    assert _cv("2", "minute").to_timedelta == timedelta(minutes=2)
    assert _cv("500", "millisecond").to_timedelta == timedelta(milliseconds=500)


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_iteration_yields_detached_but_intact_spectra(filename):
    """Iteration detaches elements from the tree for memory, but collected spectra stay usable.

    This would fail if iteration used element.clear() instead of parent.remove(): every retained
    spectrum would be emptied once iteration advanced past it.
    """
    with Mzml(filename) as reader:
        collected = list(reader.spectra)  # hold every spectrum past the end of iteration
        # Access data on all of them *after* iteration has fully completed.
        ids = [s.id for s in collected]
        assert ids == ["scan=19", "scan=20", "scan=21", "sample=1 period=1 cycle=22 experiment=1"]
        assert all(len(s.cv_params) > 0 for s in collected)
        assert collected[0].mz is not None and len(collected[0].mz) == 15
        # A term resolved from a param group must also survive detachment.
        assert collected[0].polarity == "positive"


@pytest.mark.parametrize("filename", ["tests/data/example.mzML", "tests/data/example.mzML.gz"])
def test_tic_resolved_regardless_of_id_casing(filename):
    """#1 — TIC is found via its CV term even when the id is 'tic' (not the hardcoded 'TIC')."""
    with Mzml(filename) as reader:
        tic = reader.TIC
        assert tic is not None
        assert tic.id == "tic"


def test_tic_none_when_absent(monkeypatch):
    """#1 — a file with no TIC still yields None (KeyError absence path preserved)."""
    with Mzml(EXAMPLE) as reader:
        # No chromatogram carries the TIC term and 'TIC' id is absent -> None, not an error.
        monkeypatch.setattr(type(reader._file_object), "chromatogram_ids", property(lambda self: []))
        monkeypatch.setattr(
            reader._file_object.file_handler,
            "get_chromatogram_by_id",
            lambda identifier: (_ for _ in ()).throw(KeyError(identifier)),
        )
        assert reader.TIC is None


def test_duplicate_id_warns_and_keeps_last():
    """#2 — building an {id: item} map warns on a collision instead of silently dropping."""
    from mzmlpy.run import _index_by_id

    class Item:
        def __init__(self, i, tag):
            self.id = i
            self.tag = tag

    items = [Item("a", 1), Item("b", 2), Item("a", 3)]
    with pytest.warns(UserWarning, match="Duplicate"):
        result = _index_by_id(items, "thing")
    assert len(result) == 2
    assert result["a"].tag == 3  # last occurrence wins


def test_cache_signature_invalidates_on_source_change(tmp_path):
    """#3 — cache currency tracks source size+mtime, so restoring an older/different source
    invalidates the cache (a plain mtime>= check would not)."""
    import os

    from mzmlpy.util import cache_is_current, write_cache_signature

    src = tmp_path / "src.gz"
    cache = tmp_path / "cache.mzML"
    src.write_bytes(b"AAAA")
    cache.write_bytes(b"decoded")

    assert not cache_is_current(str(cache), str(src))  # no signature yet
    write_cache_signature(str(cache), str(src))
    assert cache_is_current(str(cache), str(src))

    # Same size but older mtime (e.g. restoring a backup) — must invalidate.
    st = os.stat(src)
    older = st.st_mtime - 1000
    os.utime(src, (older, older))
    assert not cache_is_current(str(cache), str(src))


@pytest.mark.parametrize("in_memory", [True, False])
def test_multibyte_utf8_element_parses(tmp_path, in_memory):
    """#4 — a spectrum containing multi-byte UTF-8 parses correctly.

    The byte range is read from the binary handle; the old text-handle read used the byte length
    as a character count and over-read past </spectrum> on multi-byte content.
    """
    value = "µ Ångström ∑ test"  # µ, Å, ö, ∑ — all multi-byte in UTF-8
    doc = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<indexedmzML xmlns="http://psi.hupo.org/ms/mzml"><mzML><run id="r">\n'
        '<spectrumList count="1">\n'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">\n'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>\n'
        f'<userParam name="note" value="{value}"/>\n'
        "</spectrum>\n</spectrumList></run></mzML></indexedmzML>\n"
    )
    path = tmp_path / "multibyte.mzML"
    path.write_text(doc, encoding="utf-8")

    with Mzml(str(path), in_memory=in_memory) as reader:
        s = reader.spectra[0]
        assert s.id == "scan=1"
        note = s.get_user_param("note")
        assert note is not None
        assert note.value == value


def test_binary_decode_values_correct():
    """#6 — decoded arrays keep correct values (little-endian dtype pinning is a no-op here)."""
    with Mzml(EXAMPLE) as reader:
        mz = reader.spectra[0].mz
        assert mz is not None and len(mz) > 0
        # Values must be monotonic and in a sane numeric range — a byte-swapped float64 decode
        # would produce garbage (e.g. ~1e300 or denormals), not a clean 0..14 ramp.
        assert (mz[1:] >= mz[:-1]).all()
        assert float(mz.min()) >= 0
        assert float(mz.max()) < 100000
