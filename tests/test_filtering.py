from io import BytesIO

import pytest

from mzmlpy import Mzml, SpectrumFilter


def reader() -> Mzml:
    body = []
    for index, (level, time, unit, polarity) in enumerate(
        [
            (1, "1", "UO:0000031", "MS:1000130"),
            (2, "120", "UO:0000010", "MS:1000129"),
            (2, "180000", "UO:0000028", "MS:1000130"),
            (2, None, None, None),
        ]
    ):
        metadata = f'<cvParam accession="MS:1000511" value="{level}"/>'
        if polarity:
            metadata += f'<cvParam accession="{polarity}"/>'
        if time:
            metadata += (
                f'<scanList count="1"><scan><cvParam accession="MS:1000016" value="{time}" '
                f'unitAccession="{unit}"/></scan></scanList>'
            )
        if level == 2:
            metadata += (
                '<precursorList count="1"><precursor><isolationWindow>'
                '<cvParam accession="MS:1000827" value="500"/>'
                '<cvParam accession="MS:1000828" value="2"/>'
                '<cvParam accession="MS:1000829" value="3"/>'
                "</isolationWindow></precursor></precursorList>"
            )
        body.append(
            f'<spectrum id="scan={index}" defaultArrayLength="0">{metadata}'
            '<binaryDataArrayList count="1"><binaryDataArray><binary>invalid!!!</binary>'
            "</binaryDataArray></binaryDataArrayList></spectrum>"
        )
    xml = '<mzML><run><spectrumList count="4">' + "".join(body) + "</spectrumList></run></mzML>"
    return Mzml(BytesIO(xml.encode()))


def test_filter_combines_metadata_and_normalizes_time_units() -> None:
    with reader() as source:
        assert [s.id for s in source.spectra.filter(ms_level=2, retention_time=(120, 180), polarity="positive")] == [
            "scan=2"
        ]
        assert [s.id for s in source.spectra.filter(retention_time=(None, 60))] == ["scan=0"]
        assert [s.id for s in source.spectra.filter(retention_time=(180, None))] == ["scan=2"]
        assert len(list(source.spectra.filter())) == 4
        assert len(list(source.spectra.filter(precursor_mz=(503, 505)))) == 3
        assert list(source.spectra.filter(precursor_mz=(504, 505))) == []


def test_filter_is_lazy_and_independent_of_next_cursor() -> None:
    with reader() as source:
        selected = source.spectra.filter(ms_level=1)
        assert iter(selected) is selected
        assert source.spectra.next().id == "scan=0"
        assert next(selected).id == "scan=0"
        assert source.spectra.next().id == "scan=1"
        with pytest.raises(StopIteration):
            next(selected)
        assert SpectrumFilter(ms_level=2).matches(source.spectra[1])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ms_level": 0},
        {"ms_level": True},
        {"polarity": "unknown"},
        {"retention_time": (2, 1)},
        {"retention_time": (-1, 1)},
        {"precursor_mz": (0, float("inf"))},
        {"precursor_mz": (float("nan"), None)},
    ],
)
def test_invalid_filter_fails_before_iteration(kwargs) -> None:
    with reader() as source, pytest.raises(ValueError):
        source.spectra.filter(**kwargs)


def test_selected_ion_fallback_and_missing_metadata() -> None:
    from xml.etree import ElementTree as ET

    from mzmlpy import Spectrum

    spectrum = Spectrum(
        ET.fromstring(
            "<spectrum><precursorList><precursor><selectedIonList><selectedIon>"
            '<cvParam accession="MS:1000744" value="600"/>'
            "</selectedIon></selectedIonList></precursor></precursorList></spectrum>"
        )
    )
    assert SpectrumFilter(precursor_mz=(600, 600)).matches(spectrum)
    assert not SpectrumFilter(ms_level=1).matches(spectrum)
    assert not SpectrumFilter(retention_time=(None, None)).matches(spectrum)
