"""Exception hierarchy for mzmlpy.

Every error mzmlpy raises for bad input data or bad arguments is an :class:`MzmlError`. It
subclasses :class:`ValueError`, so ``except ValueError`` handlers keep working.

A lookup by an id that is not in the file raises :class:`MzmlRecordNotFoundError`, which is
also a :class:`KeyError`. An integer index out of range raises :class:`IndexError`, and an
argument of the wrong type raises :class:`TypeError`.
"""

import contextlib
from collections.abc import Iterator
from xml.etree.ElementTree import ParseError


class MzmlError(ValueError):
    """Base class for mzmlpy errors about invalid data or invalid arguments."""


class MzmlParseError(MzmlError):
    """The XML is empty, not well-formed, truncated, or not mzML.

    Wraps the underlying :class:`xml.etree.ElementTree.ParseError` (available as
    ``__cause__``) when there is one.
    """


class MzmlOffsetIndexError(MzmlError):
    """An offset index (the mzML ``indexList``, a cached index or an embedded gzip index) is
    inconsistent with the file."""


class MzmlRecordNotFoundError(MzmlError, KeyError):
    """No spectrum, chromatogram or other record has the requested id."""

    def __str__(self) -> str:
        # KeyError.__str__ would repr() the message; keep it readable.
        return str(self.args[0]) if self.args else ""


class MzmlDecodeError(MzmlError):
    """A binary data array cannot be decoded (bad base64, unsupported type, wrong length)."""


@contextlib.contextmanager
def _parse_errors(source: str | None = None) -> Iterator[None]:
    """Re-raise a raw XML ``ParseError`` as :class:`MzmlParseError`."""
    try:
        yield
    except ParseError as error:
        where = f"{source}: " if source else ""
        raise MzmlParseError(f"{where}invalid or truncated mzML XML ({error})") from error


__all__ = [
    "MzmlError",
    "MzmlParseError",
    "MzmlOffsetIndexError",
    "MzmlDecodeError",
    "MzmlRecordNotFoundError",
]
