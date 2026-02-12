from dataclasses import dataclass

from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class Software(_ParamGroup):
    @property
    def id(self) -> str:
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Software ID is missing")
        return id

    @property
    def version(self) -> str | None:
        return self.get_attribute("version")

    def __repr__(self) -> str:
        return f"Software(id='{self.id}', version='{self.version}')"

    def __str__(self) -> str:
        return self.__repr__()
