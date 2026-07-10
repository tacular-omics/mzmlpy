"""Tests for the IM-MS/DIA CV-term accessors added per the PSI recommendation v1.0.

Covers front-end ion mobility filtering (FAIMS/SelexION), the DIA merged-concept file-content
terms, and the "no isolation" isolation-window marker. Objects are built directly from real XML
fragments (no mocking), matching the pattern in test_regression_fixes.py.
"""

from xml.etree import ElementTree

from mzmlpy.elems.file_desc import FileContent
from mzmlpy.spectra import IsolationWindow, Scan

# --- Front-end ion mobility filtering (§3.6) ---


def test_faims_compensation_voltage() -> None:
    element = ElementTree.fromstring(
        '<scan><cvParam accession="MS:1001581" name="FAIMS compensation voltage" value="-54.0"/></scan>'
    )
    assert Scan(element).faims_compensation_voltage == -54.0


def test_faims_compensation_voltage_absent() -> None:
    assert Scan(ElementTree.fromstring("<scan></scan>")).faims_compensation_voltage is None


def test_selexion_voltages() -> None:
    element = ElementTree.fromstring(
        "<scan>"
        '<cvParam accession="MS:1003394" name="SelexION separation voltage" value="124.0"/>'
        '<cvParam accession="MS:1003371" name="SelexION compensation voltage" value="20.0"/>'
        "</scan>"
    )
    scan = Scan(element)
    assert scan.selexion_separation_voltage == 124.0
    assert scan.selexion_compensation_voltage == 20.0


# --- "no isolation" marker (§3.5) ---


def test_no_isolation_marker_present() -> None:
    element = ElementTree.fromstring(
        '<isolationWindow><cvParam accession="MS:1003159" name="no isolation" value=""/></isolationWindow>'
    )
    window = IsolationWindow(element)
    assert window.no_isolation is True
    # A "no isolation" window carries no target/offsets.
    assert window.target_mz is None


def test_no_isolation_false_for_normal_window() -> None:
    element = ElementTree.fromstring(
        '<isolationWindow><cvParam accession="MS:1000827" name="isolation window target m/z" value="500.0"/>'
        "</isolationWindow>"
    )
    window = IsolationWindow(element)
    assert window.no_isolation is False
    assert window.target_mz == 500.0


# --- DIA merged-concept file-content terms (§3.3) ---


def test_dia_acquisition_diapasef() -> None:
    element = ElementTree.fromstring(
        '<fileContent><cvParam accession="MS:1003225" '
        'name="data independent acquisition from dissociation of sequential mass ranges after ion mobility separation" '
        'value=""/></fileContent>'
    )
    fc = FileContent(element)
    assert fc.is_dia is True
    assert fc.dia_acquisition == "MS:1003225"


def test_dia_acquisition_sonar() -> None:
    element = ElementTree.fromstring(
        '<fileContent><cvParam accession="MS:1003228" name="SONAR" value=""/></fileContent>'
    )
    assert FileContent(element).dia_acquisition == "MS:1003228"


def test_dia_acquisition_absent_for_dda() -> None:
    element = ElementTree.fromstring(
        '<fileContent><cvParam accession="MS:1000580" name="MSn spectrum" value=""/></fileContent>'
    )
    fc = FileContent(element)
    assert fc.is_dia is False
    assert fc.dia_acquisition is None
