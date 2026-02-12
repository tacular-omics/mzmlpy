"""Collection of regular expressions to catch spectrum XML-tags."""

import re
from re import Pattern

SPECTRUM_ID_PATTERN: Pattern[str] = re.compile(r'="{0,1}([0-9]*)"{0,1}>{0,1}$')
FILE_ENCODING_PATTERN: Pattern[bytes] = re.compile(b'encoding="(?P<encoding>[A-Za-z0-9-]*)"')
SPECTRUM_CLOSE_PATTERN: Pattern[bytes] = re.compile(b"</spectrum>")
CHROMATOGRAM_CLOSE_PATTERN: Pattern[bytes] = re.compile(b"</chromatogram>")
INDEX_LIST_OFFSET_PATTERN: Pattern[bytes] = re.compile(
    b"<indexListOffset>(?P<indexListOffset>[0-9]*)</indexListOffset>"
)
MZML_VERSION_PATTERN: Pattern[str] = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
