from dataclasses import dataclass

from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class ReferenceableParamGroup(_ParamGroup):
    @property
    def id(self) -> str:
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("ReferenceableParamGroup must have an 'id' attribute")
        return id

    def __repr__(self) -> str:
        return f"ReferenceableParamGroup(id='{self.id}')"

    def __str__(self) -> str:
        return self.__repr__()
