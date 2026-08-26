import contextlib
import gzip
import io
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
    tmp_path = f"{final_path}.{os.getpid()}.tmp"
    try:
        yield tmp_path
        os.replace(tmp_path, final_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


def source_signature(path: str) -> str:
    """Return a cheap content signature (size + high-resolution mtime) for a source file."""
    st = os.stat(path)
    return f"{st.st_size}:{st.st_mtime_ns}"


def cache_is_current(cache_path: str, source_path: str) -> bool:
    """Whether ``cache_path`` is a valid cache of ``source_path``.

    Validated against a ``<cache_path>.src`` sidecar recording the source's signature at build
    time. Comparing the *recorded* signature to the source's *current* one (rather than comparing
    file mtimes) correctly invalidates the cache when the source is replaced by an older or
    same-mtime-but-different-size file (e.g. restoring a backup), which a plain ``mtime >=`` check
    would wrongly treat as still current.
    """
    signature_path = cache_path + ".src"
    if not (os.path.exists(cache_path) and os.path.exists(signature_path)):
        return False
    try:
        with open(signature_path) as f:
            return f.read().strip() == source_signature(source_path)
    except OSError:
        return False


def write_cache_signature(cache_path: str, source_path: str) -> None:
    """Record the source's current signature next to a freshly written cache file."""
    with atomic_write_path(cache_path + ".src") as tmp_path, open(tmp_path, "w") as f:
        f.write(source_signature(source_path))


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
