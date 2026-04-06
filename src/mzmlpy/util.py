import gzip
import io
import os
import shutil
import tempfile
import xml.etree.ElementTree as ElementTree
from typing import BinaryIO, TextIO

try:
    from rapidgzip import RapidgzipFile

    _HAS_RAPIDGZIP = True
except ImportError:
    _HAS_RAPIDGZIP = False


def get_tag(element: ElementTree.Element) -> str:
    return element.tag.split("}")[-1] if "}" in element.tag else element.tag


def gzip_open_binary(path: str) -> BinaryIO:
    """Open a gzip file for binary reading, using rapidgzip if available."""
    if _HAS_RAPIDGZIP:
        return RapidgzipFile(path, parallelization=os.cpu_count() or 1)  # type: ignore[return-value]
    return gzip.open(path, "rb")


def gzip_open_text(path: str, encoding: str = "utf-8") -> TextIO:
    """Open a gzip file for text reading, using rapidgzip if available."""
    if _HAS_RAPIDGZIP:
        return io.TextIOWrapper(
            RapidgzipFile(path, parallelization=os.cpu_count() or 1),
            encoding=encoding,
        )
    return gzip.open(path, "rt", encoding=encoding)


def gzip_decompress(path: str) -> bytes:
    """Read and decompress an entire gzip file, using rapidgzip if available."""
    with gzip_open_binary(path) as f:
        return f.read()


def _get_cache_dir() -> str:
    """Return the mzmlpy cache directory path."""
    return os.path.join(tempfile.gettempdir(), "mzmlpy")


def clear_cache() -> None:
    """Remove all cached files from the mzmlpy temporary directory.

    Deletes the ``<tmpdir>/mzmlpy/`` directory and all its contents.
    This includes extracted ``.mzML`` files created by ``gzip_mode='extract'``.

    Example::

        from mzmlpy import clear_cache
        clear_cache()
    """
    cache_dir = _get_cache_dir()
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
