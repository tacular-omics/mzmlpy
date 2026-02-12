from dataclasses import dataclass

from ..constants import MzMLElement
from .dtree_wrapper import _DataTreeWrapper, _ParamGroup


@dataclass(frozen=True, repr=False)
class ProcessingMethod(_ParamGroup):
    @property
    def order(self) -> int | None:
        order = self.get_attribute("order")
        return int(order) if order is not None else None

    @property
    def software_ref(self) -> str | None:
        return self.get_attribute("softwareRef")

    def __repr__(self) -> str:
        return f"ProcessingMethod(order={self.order}, software_ref='{self.software_ref}', cv_params={self.cv_params})"

    def __str__(self) -> str:
        return self.__repr__()


@dataclass(frozen=True)
class DataProcessing(_DataTreeWrapper):
    @property
    def id(self) -> str:
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("DataProcessing ID is missing")
        return id

    @property
    def processing_methods(self) -> tuple[ProcessingMethod, ...]:
        method_elements = self.element.findall(f"./{self.ns}{MzMLElement.PROCESSING_METHOD}")
        return tuple(ProcessingMethod(element=me) for me in method_elements)

    def __repr__(self) -> str:
        return f"DataProcessing(id='{self.id}', processing_methods={self.processing_methods})"

    def __str__(self) -> str:
        return self.__repr__()
