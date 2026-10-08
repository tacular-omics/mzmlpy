"""Primary activation type with supplemental terms, and imzML external binary data."""

import pytest

from mzmlpy import Mzml, MzmlDecodeError
from mzmlpy.constants import CollisionDissociationTypeAccession as CD

_HEADER = '<?xml version="1.0" encoding="utf-8"?>\n<mzML xmlns="http://psi.hupo.org/ms/mzml" id="m" version="1.1.0">\n'
_FOOTER = "</mzML>\n"

_ETD = '<cvParam cvRef="MS" accession="MS:1000598" name="electron transfer dissociation" value=""/>'
_SUPP_BEAM = (
    '<cvParam cvRef="MS" accession="MS:1002678" name="supplemental beam-type collision-induced dissociation" value=""/>'
)
_SUPP_CID = '<cvParam cvRef="MS" accession="MS:1002679" name="supplemental collision-induced dissociation" value=""/>'
_HCD = '<cvParam cvRef="MS" accession="MS:1000422" name="beam-type collision-induced dissociation" value=""/>'


def _write(tmp_path, body):
    p = tmp_path / "t.mzML"
    p.write_text(_HEADER + body + _FOOTER, encoding="utf-8")
    return str(p)


def _activation(tmp_path, terms):
    body = (
        '<run id="r"><spectrumList count="1">'
        '<spectrum index="0" id="scan=1" defaultArrayLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="2"/>'
        '<precursorList count="1"><precursor><activation>'
        + "".join(terms)
        + "</activation></precursor></precursorList>"
        "</spectrum></spectrumList></run>"
    )
    with Mzml(_write(tmp_path, body)) as r:
        spec = next(iter(r.spectra))
        return spec.precursors[0].activation


@pytest.mark.parametrize("terms", [[_SUPP_BEAM, _ETD], [_ETD, _SUPP_BEAM]])
def test_ethcd_reports_etd(tmp_path, terms):
    act = _activation(tmp_path, terms)
    assert act.activation_type == CD.ELECTRON_TRANSFER_DISSOCIATION
    expected = {CD.ELECTRON_TRANSFER_DISSOCIATION, CD.SUPPLEMENTAL_BEAM_TYPE_COLLISION_INDUCED_DISSOCIATION}
    assert set(act.activation_types) == expected
    assert act.activation_types[0] == CD(terms[0].split('accession="')[1].split('"')[0])


def test_etcid_reports_etd(tmp_path):
    act = _activation(tmp_path, [_ETD, _SUPP_CID])
    assert act.activation_type == CD.ELECTRON_TRANSFER_DISSOCIATION
    assert act.activation_types == (
        CD.ELECTRON_TRANSFER_DISSOCIATION,
        CD.SUPPLEMENTAL_COLLISION_INDUCED_DISSOCIATION,
    )


def test_hcd_alone_unchanged(tmp_path):
    act = _activation(tmp_path, [_HCD])
    assert act.activation_type == CD.BEAM_TYPE_COLLISION_INDUCED_DISSOCIATION
    assert act.activation_types == (CD.BEAM_TYPE_COLLISION_INDUCED_DISSOCIATION,)


def test_supplemental_only_is_returned(tmp_path):
    act = _activation(tmp_path, [_SUPP_CID])
    assert act.activation_type == CD.SUPPLEMENTAL_COLLISION_INDUCED_DISSOCIATION


def test_no_dissociation_term(tmp_path):
    act = _activation(tmp_path, ['<cvParam cvRef="MS" accession="MS:1000045" name="collision energy" value="30"/>'])
    assert act.activation_type is None
    assert act.activation_types == ()


def test_imzml_external_data_raises(tmp_path):
    body = (
        '<run id="r"><spectrumList count="1">'
        '<spectrum index="0" id="scan=1" defaultArrayLength="3">'
        '<cvParam cvRef="MS" accession="MS:1000511" name="ms level" value="1"/>'
        '<binaryDataArrayList count="1"><binaryDataArray encodedLength="0">'
        '<cvParam cvRef="MS" accession="MS:1000523" name="64-bit float" value=""/>'
        '<cvParam cvRef="MS" accession="MS:1000576" name="no compression" value=""/>'
        '<cvParam cvRef="MS" accession="MS:1000514" name="m/z array" value=""/>'
        '<cvParam cvRef="IMS" accession="IMS:1000101" name="external data" value="true"/>'
        '<cvParam cvRef="IMS" accession="IMS:1000102" name="external offset" value="16"/>'
        '<cvParam cvRef="IMS" accession="IMS:1000103" name="external array length" value="3"/>'
        '<cvParam cvRef="IMS" accession="IMS:1000104" name="external encoded length" value="24"/>'
        "<binary/></binaryDataArray></binaryDataArrayList>"
        "</spectrum></spectrumList></run>"
    )
    with Mzml(_write(tmp_path, body)) as r:
        spec = next(iter(r.spectra))
        with pytest.raises(MzmlDecodeError, match=r"external binary data \(imzML \.ibd\) is not supported"):
            _ = spec.mz
