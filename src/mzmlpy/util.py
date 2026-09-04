import contextlib
import gzip
import io
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterator
from typing import BinaryIO, TextIO

try:
    from rapidgzip import RapidgzipFile

    _HAS_RAPIDGZIP = True
except ImportError:
    _HAS_RAPIDGZIP = False


def get_tag(element: ElementTree.Element) -> str:
    return element.tag.split("}")[-1] if "}" in element.tag else element.tag


def expand_param_group_refs(
    element: ElementTree.Element, templates: dict[str, list[tuple[str, dict[str, str]]]]
) -> ElementTree.Element:
    """Expand referenceable parameter groups into an XML element tree in place.

    Directly specified parameters take precedence over inherited ones. Reference nodes remain in
    place to preserve provenance, and repeated expansion is idempotent.
    """
    if not templates:
        return element

    targets = [
        (child, [ref.get("ref") for ref in child if get_tag(ref) == "referenceableParamGroupRef"])
        for child in element.iter()
    ]
    for child, group_ids in targets:
        if not group_ids:
            continue
        ns = child.tag[: child.tag.index("}") + 1] if "}" in child.tag else ""
        seen_cv = {param.get("accession") for param in child if get_tag(param) == "cvParam"}
        seen_user = {param.get("name") for param in child if get_tag(param) == "userParam"}
        for group_id in group_ids:
            if group_id is None:
                continue
            for local_name, attributes in templates.get(group_id, []):
                if local_name == "cvParam":
                    if attributes.get("accession") in seen_cv:
                        continue
                    seen_cv.add(attributes.get("accession"))
                else:
                    if attributes.get("name") in seen_user:
                        continue
                    seen_user.add(attributes.get("name"))
                ElementTree.SubElement(child, f"{ns}{local_name}", dict(attributes))
    return element


def gzip_open_binary(path: str) -> BinaryIO:
    """Open a gzip file for binary reading, using rapidgzip if available."""
    from .embedded_indexed_gzip import is_embedded_indexed_gzip

    if is_embedded_indexed_gzip(path):
        return gzip.open(path, "rb")
    if _HAS_RAPIDGZIP:
        return RapidgzipFile(path, parallelization=os.cpu_count() or 1)  # type: ignore[return-value]
    return gzip.open(path, "rb")


def gzip_open_text(path: str, encoding: str = "utf-8") -> TextIO:
    """Open a gzip file for text reading, using rapidgzip if available."""
    from .embedded_indexed_gzip import is_embedded_indexed_gzip

    if is_embedded_indexed_gzip(path):
        return gzip.open(path, "rt", encoding=encoding)
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


@contextlib.contextmanager
def atomic_write_path(final_path: str) -> Iterator[str]:
    """Yield a temporary path in the same directory, then atomically move it into place.

    Writing a cache file directly is not crash-safe: if the process is interrupted mid-write,
    a truncated file is left behind with a fresh mtime, which downstream ``mtime``-based currency
    checks then trust forever. Writing to a sibling temp file and ``os.replace``-ing it means a
    reader only ever sees the complete old file or the complete new one. On failure the temp file
    is removed and the original (if any) is left untouched.
    """
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(final_path)}.", suffix=".tmp", dir=os.path.dirname(os.path.abspath(final_path))
    )
    os.close(fd)
    try:
        yield tmp_path
        os.replace(tmp_path, final_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


def source_signature(path: str) -> str:
    """Identify a source and its current filesystem revision without reading its data."""
    st = os.stat(path)
    return json.dumps([os.path.realpath(path), st.st_size, st.st_mtime_ns, st.st_ctime_ns])


def cache_is_current(cache_path: str, source_path: str) -> bool:
    """Check source identity, revision, and the cached payload's size and timestamp."""
    try:
        with open(cache_path + ".src") as handle:
            signature = json.load(handle)
        st = os.stat(cache_path)
        return (
            isinstance(signature, dict)
            and signature.get("source") == source_signature(source_path)
            and signature.get("cache") == [st.st_size, st.st_mtime_ns]
        )
    except (OSError, ValueError):
        return False


def write_cache_signature(cache_path: str, source_path: str, expected_source: str | None = None) -> None:
    """Publish cache metadata only if the source stayed unchanged during construction."""
    signature = source_signature(source_path)
    if expected_source is not None and signature != expected_source:
        raise OSError("Source changed while building its cache. Reopen the reader to retry.")
    st = os.stat(cache_path)
    with atomic_write_path(cache_path + ".src") as tmp_path, open(tmp_path, "w") as handle:
        json.dump({"source": signature, "cache": [st.st_size, st.st_mtime_ns]}, handle)


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
