from dataclasses import dataclass
from datetime import timedelta


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
        if self.value is None or self.unit_name is None:
            return None

        time_val = float(self.value)
        time_unit = self.unit_name.lower()

        match time_unit:
            case "millisecond":
                return timedelta(milliseconds=time_val)
            case "second":
                return timedelta(seconds=time_val)
            case "minute":
                return timedelta(minutes=time_val)
            case "hour":
                return timedelta(hours=time_val)
            case _:
                raise ValueError(f"Unknown time unit: {self.unit_name}")


@dataclass(frozen=True)
class CvParam(_Param):
    cv_ref: str
    accession: str


@dataclass(frozen=True)
class UserParam(_Param):
    name: str
    type_value: str | None


@dataclass(frozen=True)
class ReferenceableParamGroupRef:
    ref: str
