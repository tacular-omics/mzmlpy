from dataclasses import dataclass

from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class Software(_ParamGroup):
    """Software used to acquire or process the data, identified by id and version."""

    @property
    def id(self) -> str:
        """Get the software's ``id`` attribute.

        Raises:
            ValueError: If the ``id`` attribute is missing.
        """
        id = self.get_attribute("id")
        if id is None:
            raise ValueError("Software ID is missing")
        return id

    @property
    def version(self) -> str | None:
        """Get the software's version string, if present."""
        return self.get_attribute("version")

    def __repr__(self) -> str:
        return f"Software(id='{self.id}', version='{self.version}')"

    def __str__(self) -> str:
        return self.__repr__()
