# Errors

Every error mzmlpy raises for bad data or bad arguments is an `MzmlError`, which subclasses
`ValueError`. A lookup by an id that is not in the file raises `MzmlRecordNotFoundError`, which
is also a `KeyError`. An integer index out of range raises `IndexError`, and an argument of the
wrong type raises `TypeError`.

::: mzmlpy.errors.MzmlError

::: mzmlpy.errors.MzmlParseError

::: mzmlpy.errors.MzmlOffsetIndexError

::: mzmlpy.errors.MzmlDecodeError

::: mzmlpy.errors.MzmlRecordNotFoundError
