"""Internal cooperative checkpoints for long reader operations."""

from collections.abc import Callable
from contextvars import ContextVar

_progress: ContextVar[Callable[[str, int], None] | None] = ContextVar("mzmlpy_progress", default=None)


def checkpoint(stage: str, completed: int = 0) -> None:
    """Notify the current operation, if it installed a progress callback."""
    callback = _progress.get()
    if callback is not None:
        callback(stage, completed)
