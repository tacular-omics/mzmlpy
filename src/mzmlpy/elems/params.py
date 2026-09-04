from dataclasses import dataclass
from datetime import timedelta

from ..constants import TimeUnitAccession


@dataclass(frozen=True)
class _Param:
    name: str
    value: str | None
    unit_accession: str | None
    unit_name: str | None
    unit_cv_ref: str | None

    @property
    def to_timedelta(self) -> timedelta | None:
        """Convert this CvParam to a timedelta object if it has a time unit, otherwise return None."""
        if self.value is None:
            return None
        unit_name = {
            TimeUnitAccession.MILLISECOND: "millisecond",
            TimeUnitAccession.SECOND: "second",
            TimeUnitAccession.MINUTE: "minute",
            TimeUnitAccession.HOUR: "hour",
        }.get(self.unit_accession, self.unit_name)
        if unit_name is None:
            return None

        try:
            time_val = float(self.value)
        except (TypeError, ValueError):
            return None

        match unit_name.lower():
            case "millisecond":
                return timedelta(milliseconds=time_val)
            case "second":
                return timedelta(seconds=time_val)
            case "minute":
                return timedelta(minutes=time_val)
            case "hour":
                return timedelta(hours=time_val)
            case _:
                # Not a time-valued parameter (e.g. an m/z or intensity unit) — the property is
                # documented to return None in that case rather than raising.
                return None


@dataclass(frozen=True)
class CvParam(_Param):
    """A controlled vocabulary parameter with a CV reference and accession number."""

    cv_ref: str
    accession: str


@dataclass(frozen=True)
class UserParam(_Param):
    """A user-defined parameter with an arbitrary name and optional type annotation."""

    name: str
    type_value: str | None


@dataclass(frozen=True)
class ReferenceableParamGroupRef:
    """A reference to a referenceable parameter group by its id string."""

    ref: str
