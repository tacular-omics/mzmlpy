from dataclasses import dataclass

from ..constants import MzMLElement
from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class _Component(_ParamGroup):
    @property
    def order(self) -> int | None:
        order = self.get_attribute("order")
        if order is not None:
            return int(order)
        return None


@dataclass(frozen=True, repr=False)
class SourceComponent(_Component):
    pass


@dataclass(frozen=True, repr=False)
class AnalyzerComponent(_Component):
    pass


@dataclass(frozen=True, repr=False)
class DetectorComponent(_Component):
    pass


@dataclass(frozen=True, repr=False)
class InstrumentConfiguration(_ParamGroup):
    @property
    def id(self) -> str:
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("InstrumentConfiguration ID is missing")
        return id

    @property
    def software_ref(self) -> str | None:
        sw_ref_element = self.element.find(f"./{self.ns}{MzMLElement.SOFTWARE_REF}")
        if sw_ref_element is not None:
            return sw_ref_element.attrib.get("ref")
        return None

    @property
    def source_components(self) -> tuple[SourceComponent, ...]:
        component_list = self.element.find(f"./{self.ns}{MzMLElement.COMPONENT_LIST}")
        if component_list is None:
            return ()
        source_elements = component_list.findall(f"./{self.ns}{MzMLElement.SOURCE}")
        return tuple(SourceComponent(element=se) for se in source_elements)

    @property
    def analyzer_components(self) -> tuple[AnalyzerComponent, ...]:
        component_list = self.element.find(f"./{self.ns}{MzMLElement.COMPONENT_LIST}")
        if component_list is None:
            return ()
        analyzer_elements = component_list.findall(f"./{self.ns}{MzMLElement.ANALYZER}")
        return tuple(AnalyzerComponent(element=ae) for ae in analyzer_elements)

    @property
    def detector_components(self) -> tuple[DetectorComponent, ...]:
        component_list = self.element.find(f"./{self.ns}{MzMLElement.COMPONENT_LIST}")
        if component_list is None:
            return ()
        detector_elements = component_list.findall(f"./{self.ns}{MzMLElement.DETECTOR}")
        return tuple(DetectorComponent(element=de) for de in detector_elements)

    def __repr__(self) -> str:
        return (
            f"InstrumentConfiguration(id='{self.id}', "
            f"sources={len(self.source_components)}, "
            f"analyzers={len(self.analyzer_components)}, "
            f"detectors={len(self.detector_components)})"
        )

    def __str__(self) -> str:
        return self.__repr__()
