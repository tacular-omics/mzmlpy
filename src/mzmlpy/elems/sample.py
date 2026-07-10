from dataclasses import dataclass

from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class Sample(_ParamGroup):
    """A sample analyzed in the experiment, described by id, optional name, and CV parameters."""

    @property
    def id(self) -> str:
        """Get the sample's ``id`` attribute.

        Raises:
            ValueError: If the ``id`` attribute is missing.
        """
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Sample ID is missing")
        return id

    @property
    def name(self) -> str | None:
        """Get the sample's name, if present."""
        name = self.get_attribute("name")
        return name if name else None

    def __repr__(self) -> str:
        return f"Sample(id='{self.id}', name='{self.name}')"

    def __str__(self) -> str:
        return self.__repr__()
