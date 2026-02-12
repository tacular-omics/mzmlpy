from dataclasses import dataclass

from ..constants import MzMLElement
from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class Target(_ParamGroup):
    @property
    def mz(self) -> float | None:
        cv = self.get_cvparm("MS:1000744")
        return float(cv.value) if cv is not None and cv.value is not None else None


@dataclass(frozen=True)
class SourceFileRef:
    ref: str


@dataclass(frozen=True, repr=False)
class ScanSetting(_ParamGroup):
    @property
    def id(self) -> str:
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("ScanSetting ID is missing")
        return id

    @property
    def source_file_refs(self) -> tuple[SourceFileRef, ...]:
        source_file_ref_list = self.element.find(f"./{self.ns}{MzMLElement.SOURCE_FILE_REF_LIST}")
        if source_file_ref_list is None:
            return ()

        refs = source_file_ref_list.findall(f"./{self.ns}{MzMLElement.SOURCE_FILE_REF}")
        return tuple(SourceFileRef(ref=ref.attrib.get("ref", "")) for ref in refs)

    @property
    def targets(self) -> tuple[Target, ...]:
        target_list = self.element.find(f"./{self.ns}{MzMLElement.TARGET_LIST}")
        if target_list is None:
            return ()

        target_elements = target_list.findall(f"./{self.ns}{MzMLElement.TARGET}")
        return tuple(Target(element=te) for te in target_elements)

    def __repr__(self) -> str:
        return f"ScanSetting(id='{self.id}', source_file_refs={self.source_file_refs}, targets={self.targets})"

    def __str__(self) -> str:
        return self.__repr__()
