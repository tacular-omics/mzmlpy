import copy
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import NamedTuple

from .constants import MzMLElement, XMLNamespace
from .elems import (
    DataProcessing,
    FileDescription,
    InstrumentConfiguration,
    ReferenceableParamGroup,
    Run,
    Sample,
    ScanSetting,
    Software,
)
from .regex_patterns import MZML_VERSION_PATTERN
from .util import get_tag


class CVElement(NamedTuple):
    """Named tuple for controlled vocabulary elements."""

    id: str
    full_name: str
    version: str
    uri: str


@dataclass(frozen=True)
class _MzMLContent:
    """Root mzML content structure."""

    # Required fields
    id: str
    version: str

    # Optional metadata
    cv_list: tuple[CVElement, ...] = ()
    file_description: FileDescription | None = None
    referenceable_param_groups: dict[str, ReferenceableParamGroup] = field(default_factory=dict)
    softwares: tuple[Software, ...] = ()
    instrument_configurations: dict[str, InstrumentConfiguration] = field(default_factory=dict)
    data_processes: dict[str, DataProcessing] = field(default_factory=dict)
    samples: tuple[Sample, ...] = ()
    scan_settings: dict[str, ScanSetting] = field(default_factory=dict)
    run: Run | None = None

    # XML attributes (rarely needed)
    xmlns: str | None = None
    xmlns_xsi: str | None = None
    xsi_schema_location: str | None = None


class MzMLContentBuilder:
    """Builder that parses mzML metadata from XML iterator."""

    def __init__(self) -> None:
        # Required fields
        self._id = ""
        self._version = ""

        # Optional metadata
        self._cv_list: list[CVElement] = []
        self._file_description: FileDescription | None = None
        self._referenceable_param_groups: list[ReferenceableParamGroup] = []
        self._software_list: list[Software] = []
        self._instrument_configurations: list[InstrumentConfiguration] = []
        self._data_processing_list: list[DataProcessing] = []
        self._sample_list: list[Sample] = []
        self._scan_settings_list: list[ScanSetting] = []
        self._run: Run | None = None

        # Extra metadata (not in MzMLContent)
        self.obo_version: str | None = None

        # Handler dispatch table
        self._handlers = {
            MzMLElement.CV: self._handle_cv,
            MzMLElement.FILE_DESCRIPTION: self._handle_file_description,
            MzMLElement.REFERENCEABLE_PARAM_GROUP_LIST: self._handle_referenceable_param_group_list,
            MzMLElement.SOFTWARE_LIST: self._handle_software_list,
            MzMLElement.SAMPLE_LIST: self._handle_sample_list,
            MzMLElement.SCAN_SETTINGS_LIST: self._handle_scan_settings_list,
            MzMLElement.INSTRUMENT_CONFIG_LIST: self._handle_instrument_configuration_list,
            MzMLElement.DATA_PROCESSING_LIST: self._handle_data_processing_list,
        }

    def parse_from_iterator(self, mzml_iter: Iterator[tuple[str, ElementTree.Element]]) -> None:
        """Parse metadata from mzML iterator until reaching run element."""
        for event, element in mzml_iter:
            if not isinstance(element, ElementTree.Element):
                raise RuntimeError(f"Expected ElementTree.Element, got {type(element)}")

            tag = get_tag(element)

            # Handle start events
            if event == "start":
                if tag == "mzML":
                    self._handle_mzml(element)
                elif tag == "run":
                    self._handle_run(element)
                    return  # Stop parsing after run starts

            # Handle end events with dispatch table
            if event == "end" and tag in self._handlers:
                self._handlers[tag](element)
                element.clear()  # Free memory

    # ========== Handler Methods ==========

    def _handle_mzml(self, element: ElementTree.Element) -> None:
        """Extract mzML root element attributes."""
        # Get version
        if version := element.attrib.get("version"):
            self._version = version
        else:
            schema_location = element.attrib.get(XMLNamespace.SCHEMA_LOCATION, "")
            if match := MZML_VERSION_PATTERN.search(schema_location):
                self._version = match.group()

        # Get ID
        self._id = element.attrib.get("id", "")

    def _handle_cv(self, element: ElementTree.Element) -> None:
        """Parse controlled vocabulary definition."""
        cv = CVElement(
            id=element.attrib.get("id", ""),
            full_name=element.attrib.get("fullName", ""),
            version=element.attrib.get("version", ""),
            uri=element.attrib.get("URI", ""),
        )
        self._cv_list.append(cv)

        # Track OBO version if this is MS ontology
        if cv.id == "MS":
            self.obo_version = cv.version

    def _handle_file_description(self, element: ElementTree.Element) -> None:
        """Parse file description."""
        self._file_description = FileDescription(element=copy.deepcopy(element))

    def _handle_referenceable_param_group_list(self, element: ElementTree.Element) -> None:
        """Parse referenceable parameter groups."""
        for child in element:
            if get_tag(child) == MzMLElement.REFERENCEABLE_PARAM_GROUP:
                self._referenceable_param_groups.append(ReferenceableParamGroup(element=copy.deepcopy(child)))

    def _handle_software_list(self, element: ElementTree.Element) -> None:
        """Parse software list."""
        for child in element:
            if get_tag(child) == MzMLElement.SOFTWARE:
                self._software_list.append(Software(element=copy.deepcopy(child)))

    def _handle_sample_list(self, element: ElementTree.Element) -> None:
        """Parse sample list."""
        for child in element:
            if get_tag(child) == MzMLElement.SAMPLE:
                self._sample_list.append(Sample(element=copy.deepcopy(child)))

    def _handle_scan_settings_list(self, element: ElementTree.Element) -> None:
        """Parse scan settings list."""
        for child in element:
            if get_tag(child) == MzMLElement.SCAN_SETTINGS:
                self._scan_settings_list.append(ScanSetting(element=copy.deepcopy(child)))

    def _handle_instrument_configuration_list(self, element: ElementTree.Element) -> None:
        """Parse instrument configuration list."""
        for child in element:
            if get_tag(child) == MzMLElement.INSTRUMENT_CONFIGURATION:
                self._instrument_configurations.append(InstrumentConfiguration(element=copy.deepcopy(child)))

    def _handle_data_processing_list(self, element: ElementTree.Element) -> None:
        """Parse data processing list."""
        for child in element:
            if get_tag(child) == MzMLElement.DATA_PROCESSING:
                self._data_processing_list.append(DataProcessing(element=copy.deepcopy(child)))

    def _handle_run(self, element: ElementTree.Element) -> None:
        """Parse run element (called on start event, before children loaded)."""
        self._run = Run(element=copy.deepcopy(element))

    # ========== Build Method ==========

    def build(self) -> _MzMLContent:
        """Build immutable MzMLContent from parsed data."""
        return _MzMLContent(
            id=self._id,
            version=self._version,
            cv_list=tuple(self._cv_list),
            file_description=self._file_description,
            referenceable_param_groups={rpg.id: rpg for rpg in self._referenceable_param_groups},
            softwares=tuple(self._software_list),
            samples=tuple(self._sample_list),
            scan_settings={ss.id: ss for ss in self._scan_settings_list},
            instrument_configurations={ic.id: ic for ic in self._instrument_configurations},
            data_processes={dp.id: dp for dp in self._data_processing_list},
            run=self._run,
        )
