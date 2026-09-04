"""Collection of regular expressions to catch spectrum XML-tags."""

import re
from re import Pattern

FILE_ENCODING_PATTERN: Pattern[bytes] = re.compile(rb"encoding\s*=\s*['\"](?P<encoding>[A-Za-z0-9._-]+)['\"]")
SPECTRUM_CLOSE_PATTERN: Pattern[bytes] = re.compile(b"</spectrum>")
CHROMATOGRAM_CLOSE_PATTERN: Pattern[bytes] = re.compile(b"</chromatogram>")
INDEX_LIST_OFFSET_PATTERN: Pattern[bytes] = re.compile(
    rb"<(?:[\w.-]+:)?indexListOffset\s*>\s*(?P<indexListOffset>[0-9]+)\s*</(?:[\w.-]+:)?indexListOffset\s*>"
)
MZML_VERSION_PATTERN: Pattern[str] = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
