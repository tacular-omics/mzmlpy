import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from functools import cached_property
from typing import Protocol, runtime_checkable

from ..constants import MzMLElement
from ..errors import MzmlError
from .params import CvParam, ReferenceableParamGroupRef, UserParam


@runtime_checkable
class _DataTreeWrapperProtocol(Protocol):
    """Protocol defining the interface required by mixins."""

    element: ElementTree.Element

    @property
    def ns(self) -> str: ...

    @property
    def cv_params(self) -> tuple[CvParam, ...]: ...

    def get_cv_param(self, id: str) -> CvParam | None: ...

    def cv_float(self, id: str) -> float | None: ...

    def cv_int(self, id: str) -> int | None: ...

    @property
    def accessions(self) -> frozenset[str]: ...

    @property
    def names(self) -> frozenset[str]: ...

    @property
    def user_params(self) -> tuple[UserParam, ...]: ...

    @property
    def ref_params(self) -> tuple[ReferenceableParamGroupRef, ...]: ...


@dataclass(frozen=True)
class _DataTreeWrapper:
    # base class for any object that wraps an XML element

    element: ElementTree.Element

    def __post_init__(self):
        if not isinstance(self.element, ElementTree.Element):
            raise TypeError(f"Expected element to be an instance of ElementTree.Element, got {type(self.element)}")

    @cached_property
    def ns(self) -> str:
        """Get XML namespace from the element tag."""
        return match.group(0) if (match := re.match(r"\{.*\}", self.element.tag)) else ""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(element_tag='{self.element.tag}')"

    def __str__(self) -> str:
        return self.__repr__()

    def serialize(self) -> dict[str, object]:
        """Return the element as nested dicts: ``tag``, ``attributes``, ``text``, ``children``.

        The result is a fresh copy; changing it does not change the wrapped element.
        """
        return {
            "tag": self.element.tag,
            "attributes": dict(self.element.attrib),
            "text": self.element.text,
            "children": [_DataTreeWrapper(child).serialize() for child in self.element],
        }

    def get_attribute(self, attr_name: str) -> str | None:
        """Get an attribute value from the element."""
        return self.element.attrib.get(attr_name)


@dataclass(frozen=True)
class _ParamGroup(_DataTreeWrapper):
    @cached_property
    def cv_params(self) -> tuple[CvParam, ...]:
        """The element's cvParams, in document order."""
        cv_params: list[CvParam] = []
        for cv_param in self.element.findall(f"{self.ns}{MzMLElement.CV_PARAM}"):
            cv_param = cv_param.attrib
            # cvRef/accession/name are schema-required, but tolerate their absence with empty
            # defaults so one malformed cvParam does not break access to every other term.
            cv_params.append(
                CvParam(
                    cv_ref=cv_param.get("cvRef", ""),
                    accession=cv_param.get("accession", ""),
                    value=cv_param.get("value", None),
                    name=cv_param.get("name", ""),
                    unit_accession=cv_param.get("unitAccession", None),
                    unit_name=cv_param.get("unitName", None),
                    unit_cv_ref=cv_param.get("unitCvRef", None),
                )
            )
        return tuple(cv_params)

    def get_cv_param(self, id: str) -> CvParam | None:
        """Get a cvParam by accession or name, or None if absent."""
        for cv_param in self.cv_params:
            if cv_param.accession == id or cv_param.name == id:
                return cv_param
        return None

    def has_cv_param(self, id: str) -> bool:
        """Check if a cvParam with the given accession or name exists."""
        return any(cv_param.accession == id or cv_param.name == id for cv_param in self.cv_params)

    def cv_float(self, id: str) -> float | None:
        """Return a cvParam's value as a float, or None if the term is absent or has no value.

        Raises MzmlError naming the term and its bad value if the value is present but not
        numeric — more actionable than a bare "could not convert string to float".
        """
        cv_param = self.get_cv_param(id)
        if cv_param is None or cv_param.value is None:
            return None
        try:
            return float(cv_param.value)
        except ValueError as e:
            raise MzmlError(
                f"CV param {cv_param.name or id!r} ({id}) has a non-numeric value {cv_param.value!r}"
            ) from e

    def cv_int(self, id: str) -> int | None:
        """Return a cvParam's value as an int, or None if absent or valueless (see :meth:`cv_float`)."""
        cv_param = self.get_cv_param(id)
        if cv_param is None or cv_param.value is None:
            return None
        try:
            return int(cv_param.value)
        except ValueError as e:
            raise MzmlError(
                f"CV param {cv_param.name or id!r} ({id}) has a non-integer value {cv_param.value!r}"
            ) from e

    @cached_property
    def accessions(self) -> frozenset[str]:
        """All cvParam accessions."""
        return frozenset(cv_param.accession for cv_param in self.cv_params)

    @cached_property
    def names(self) -> frozenset[str]:
        """All cvParam names."""
        return frozenset(cv_param.name for cv_param in self.cv_params)

    @cached_property
    def user_params(self) -> tuple[UserParam, ...]:
        """The element's userParams, in document order."""
        user_params: list[UserParam] = []
        for user_param in self.element.findall(f"{self.ns}{MzMLElement.USER_PARAM}"):
            user_param = user_param.attrib
            user_params.append(
                UserParam(
                    name=user_param.get("name", ""),
                    value=user_param.get("value", None),
                    type_value=user_param.get("typeValue", None),
                    unit_accession=user_param.get("unitAccession", None),
                    unit_name=user_param.get("unitName", None),
                    unit_cv_ref=user_param.get("unitCvRef", None),
                )
            )
        return tuple(user_params)

    def get_user_param(self, name: str) -> UserParam | None:
        """Get a userParam by name."""
        for user_param in self.user_params:
            if user_param.name == name:
                return user_param
        return None

    def has_user_param(self, name: str) -> bool:
        """Check if a userParam with the given name exists."""
        return any(user_param.name == name for user_param in self.user_params)

    @cached_property
    def ref_params(self) -> tuple[ReferenceableParamGroupRef, ...]:
        """The element's referenceableParamGroupRefs, in document order."""
        ref_params: list[ReferenceableParamGroupRef] = []
        for ref_param in self.element.findall(f"{self.ns}{MzMLElement.REFERENCEABLE_PARAM_GROUP_REF}"):
            ref_param = ref_param.attrib
            ref_params.append(ReferenceableParamGroupRef(ref=ref_param.get("ref", "")))
        return tuple(ref_params)

    def get_ref_param(self, ref: str) -> ReferenceableParamGroupRef | None:
        """Get a referenceable parameter by ref."""
        for ref_param in self.ref_params:
            if ref_param.ref == ref:
                return ref_param
        return None

    def has_ref_param(self, ref: str) -> bool:
        """Check if a referenceable parameter with the given ref exists."""
        return any(ref_param.ref == ref for ref_param in self.ref_params)

    def __repr__(self) -> str:
        s = f"{self.__class__.__name__}("
        if self.cv_params:
            s += f"cv_params={len(self.cv_params)}, "
        if self.user_params:
            s += f"user_params={len(self.user_params)}, "
        if self.ref_params:
            s += f"ref_params={len(self.ref_params)}, "
        s = s.rstrip(", ") + ")"
        return s

    def __str__(self) -> str:
        return self.__repr__()


__all__: list[str] = []
