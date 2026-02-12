from dataclasses import dataclass

from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class Sample(_ParamGroup):
    @property
    def id(self) -> str:
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Sample ID is missing")
        return id

    @property
    def name(self) -> str | None:
        name = self.get_attribute("name")
        return name if name else None

    def __repr__(self) -> str:
        return f"Sample(id='{self.id}', name='{self.name}')"

    def __str__(self) -> str:
        return self.__repr__()
