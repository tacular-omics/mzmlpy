"""Bounded result storage and cooperative background jobs for the local MCP server."""

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Literal
from uuid import uuid4

from ._progress import _progress


class OperationCancelled(RuntimeError):
    """Raised at a cooperative checkpoint after cancellation is requested."""


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    operation: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    stage: str
    completed_units: int
    cancel_requested: bool
    result: Any = None
    error: str | None = None


class ResultCache:
    """Thread-safe LRU cache of serialized metadata results, bounded to 2 MiB."""

    def __init__(self, max_bytes: int = 2_097_152) -> None:
        self.max_bytes = max_bytes
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                return None
            self._entries.move_to_end(key)
            return json.loads(value)

    def put(self, key: str, value: Any) -> None:
        payload = json.dumps(value, allow_nan=False).encode()
        if len(payload) > self.max_bytes:
            return
        with self._lock:
            self._size -= len(self._entries.pop(key, b""))
            self._entries[key] = payload
            self._size += len(payload)
            while self._size > self.max_bytes or len(self._entries) > 16:
                _, removed = self._entries.popitem(last=False)
                self._size -= len(removed)


class JobManager:
    """Two workers and at most eight retained jobs, with a 15 minute result lifetime."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mzmlpy")
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._closed = False

    def submit(self, operation: str, work: Callable[[], Any]) -> JobStatus:
        with self._lock:
            if self._closed:
                raise ValueError("The job manager is closed")
            now = time.monotonic()
            self._expire(now)
            if len(self._jobs) >= 8:
                raise ValueError("Eight jobs are retained. Release a finished job before starting another")
            identifier = uuid4().hex
            entry = {
                "job_id": identifier,
                "operation": operation,
                "status": "queued",
                "stage": "queued",
                "completed_units": 0,
                "cancel_requested": False,
                "result": None,
                "error": None,
                "event": threading.Event(),
                "finished": None,
            }
            self._jobs[identifier] = entry
            self._pool.submit(self._run, entry, work)
            return self._snapshot(entry)

    def _expire(self, now: float) -> None:
        for identifier, entry in list(self._jobs.items()):
            if entry["finished"] is not None and now - entry["finished"] > 900:
                del self._jobs[identifier]

    def _run(self, entry: dict[str, Any], work: Callable[[], Any]) -> None:
        def progress(stage: str, units: int) -> None:
            with self._lock:
                if entry["event"].is_set():
                    raise OperationCancelled("Operation cancelled")
                entry["stage"] = stage
                entry["completed_units"] = units

        token = _progress.set(progress)
        try:
            with self._lock:
                entry["status"] = "running"
            progress("starting", 0)
            result = work()
            if is_dataclass(result) and not isinstance(result, type):
                result = asdict(result)
            payload = json.dumps(result, allow_nan=False)
            if len(payload.encode()) > 262_144:
                raise ValueError("Job result exceeds 256 KiB")
            with self._lock:
                # Export publication is the commit point. Do not discard an artifact result
                # after a completed write just because a late cancellation arrived.
                entry.update(status="completed", stage="completed", result=json.loads(payload))
        except OperationCancelled:
            with self._lock:
                entry.update(status="cancelled", stage="cancelled")
        except Exception as error:
            with self._lock:
                entry.update(status="failed", stage="failed", error=str(error)[:2000])
        finally:
            _progress.reset(token)
            with self._lock:
                entry["finished"] = time.monotonic()

    def _snapshot(self, entry: dict[str, Any]) -> JobStatus:
        return JobStatus(**{name: deepcopy(entry[name]) for name in JobStatus.__dataclass_fields__})

    def get(self, job_id: str) -> JobStatus:
        with self._lock:
            self._expire(time.monotonic())
            if job_id not in self._jobs:
                raise ValueError("Unknown or expired job ID")
            return self._snapshot(self._jobs[job_id])

    def cancel(self, job_id: str) -> JobStatus:
        with self._lock:
            self.get(job_id)
            entry = self._jobs[job_id]
            if entry["status"] in {"queued", "running"}:
                entry["cancel_requested"] = True
                entry["event"].set()
            return self._snapshot(entry)

    def release(self, job_id: str) -> dict[str, bool]:
        with self._lock:
            status = self.get(job_id)
            if status.status in {"queued", "running"}:
                raise ValueError("Cancel the job and wait for it to finish before releasing it")
            del self._jobs[job_id]
            return {"released": True}

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for entry in self._jobs.values():
                entry["event"].set()
        self._pool.shutdown(wait=True)
