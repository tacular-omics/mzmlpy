from dataclasses import dataclass

from ..errors import MzmlError
from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class ReferenceableParamGroup(_ParamGroup):
    """A named group of CV and user parameters that can be referenced by other elements to avoid repetition."""

    @property
    def id(self) -> str:
        """Get the param group's ``id`` attribute, used by other elements to reference it.

        Raises:
            ValueError: If the ``id`` attribute is missing.
        """
        id = self.get_attribute("id")
        if id is None:
            raise MzmlError("ReferenceableParamGroup must have an 'id' attribute")
        return id

    def __repr__(self) -> str:
        return f"ReferenceableParamGroup(id='{self.id}')"

    def __str__(self) -> str:
        return self.__repr__()


__all__ = ["ReferenceableParamGroup"]
