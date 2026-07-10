from dataclasses import dataclass

from ..constants import MzMLElement, SelectedIonAccession
from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class Target(_ParamGroup):
    """A targeted m/z entry within a scan settings target list."""

    @property
    def mz(self) -> float | None:
        """Get the targeted m/z value, if present."""
        # Use the shared cv_float helper so a non-numeric value yields an actionable error and an
        # absent value returns None, instead of a bare float() raising a raw ValueError.
        return self.cv_float(SelectedIonAccession.SELECTED_ION_MZ)


@dataclass(frozen=True)
class SourceFileRef:
    """A reference to a source file by its id string."""

    ref: str


@dataclass(frozen=True, repr=False)
class ScanSetting(_ParamGroup):
    """Scan acquisition settings including source file references and target m/z lists."""

    @property
    def id(self) -> str:
        """Get the scan setting's ``id`` attribute.

        Raises:
            ValueError: If the ``id`` attribute is missing.
        """
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("ScanSetting ID is missing")
        return id

    @property
    def source_file_refs(self) -> tuple[SourceFileRef, ...]:
        """Get the referenced source files' ``id``s for this scan setting."""
        source_file_ref_list = self.element.find(f"./{self.ns}{MzMLElement.SOURCE_FILE_REF_LIST}")
        if source_file_ref_list is None:
            return ()

        refs = source_file_ref_list.findall(f"./{self.ns}{MzMLElement.SOURCE_FILE_REF}")
        return tuple(SourceFileRef(ref=ref.attrib.get("ref", "")) for ref in refs)

    @property
    def targets(self) -> tuple[Target, ...]:
        """Get the targeted m/z entries for this scan setting."""
        target_list = self.element.find(f"./{self.ns}{MzMLElement.TARGET_LIST}")
        if target_list is None:
            return ()

        target_elements = target_list.findall(f"./{self.ns}{MzMLElement.TARGET}")
        return tuple(Target(element=te) for te in target_elements)

    def __repr__(self) -> str:
        return f"ScanSetting(id='{self.id}', source_file_refs={self.source_file_refs}, targets={self.targets})"

    def __str__(self) -> str:
        return self.__repr__()
