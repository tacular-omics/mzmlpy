from dataclasses import dataclass
from typing import Literal, TypeVar
from xml.etree.ElementTree import Element

# Type variables for spectrum and chromatogram
_SpectrumType = Literal["spectrum"]
_ChromatogramType = Literal["chromatogram"]

ElementTypeVar = TypeVar("ElementTypeVar", _SpectrumType, _ChromatogramType)


@dataclass(frozen=True)
class MzmlXMLElement[ElementTypeVar: (_SpectrumType, _ChromatogramType)]:
    """Generic XML element container with type-safe element_type."""

    element: Element
    element_type: ElementTypeVar


# Type aliases for convenience and type safety
SpectrumElement = MzmlXMLElement[Literal["spectrum"]]
ChromatogramElement = MzmlXMLElement[Literal["chromatogram"]]
