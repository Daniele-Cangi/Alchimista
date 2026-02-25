from __future__ import annotations

import threading


class InflightGate:
    def __init__(self, limit: int):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = limit
        self._active = 0
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(limit)

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def try_enter(self) -> bool:
        if not self._semaphore.acquire(blocking=False):
            return False
        with self._lock:
            self._active += 1
        return True

    def leave(self) -> None:
        with self._lock:
            if self._active <= 0:
                raise RuntimeError("leave called without active request")
            self._active -= 1
        self._semaphore.release()
