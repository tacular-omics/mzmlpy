import datetime
import re
from dataclasses import dataclass

from .dtree_wrapper import _ParamGroup


@dataclass(frozen=True, repr=False)
class Run(_ParamGroup):
    @property
    def id(self) -> str | None:
        return self.get_attribute("id")

    @property
    def default_instrument_configuration_ref(self) -> str | None:
        return self.get_attribute("defaultInstrumentConfigurationRef")

    @property
    def default_source_file_ref(self) -> str | None:
        return self.get_attribute("defaultSourceFileRef")

    @property
    def sample_ref(self) -> str | None:
        return self.get_attribute("sampleRef")

    @property
    def start_time_stamp(self) -> datetime.datetime | None:
        # example: 2007-06-27T15:23:45.00035
        start_time_stamp_str = self.get_attribute("startTimeStamp")
        if start_time_stamp_str is None:
            return None

        # Remove timezone info if present
        start_time_stamp_str = re.sub(r"Z|[+-]\d{2}:\d{2}$", "", start_time_stamp_str)
        try:
            return datetime.datetime.fromisoformat(start_time_stamp_str)
        except ValueError:
            return None

    def __repr__(self) -> str:
        return (
            f"Run(id='{self.id}', default_instrument_configuration_ref='{self.default_instrument_configuration_ref}', "
            f"default_source_file_ref='{self.default_source_file_ref}', sample_ref='{self.sample_ref}', "
            f"start_time_stamp='{self.start_time_stamp}')"
        )

    def __str__(self) -> str:
        return self.__repr__()
