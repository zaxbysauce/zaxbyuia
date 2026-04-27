"""Element handle cache with TTL.

UIA element handles are expensive to obtain (full tree walks). Tools often
want to round-trip an element through several calls, so we hand back an opaque
``handle`` token (a uuid) that maps to a live UIA control reference.

The cache is in-process only and entries expire after ``ttl_s`` seconds (default
120). The map is bounded (``max_entries=512``) — oldest entries are evicted.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from typing import Any


class ElementCache:
    """Thread-safe TTL cache mapping opaque handles -> UIA control objects."""

    def __init__(self, *, ttl_s: float = 120.0, max_entries: int = 512) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, control: Any) -> str:
        """Store a control and return an opaque handle."""
        token = uuid.uuid4().hex
        now = time.monotonic()
        with self._lock:
            self._data[token] = (control, now)
            self._data.move_to_end(token)
            self._evict_locked(now)
        return token

    def get(self, token: str) -> Any | None:
        """Return the cached control or ``None`` if missing/expired."""
        if not token:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(token)
            if entry is None:
                return None
            control, ts = entry
            if now - ts > self._ttl:
                del self._data[token]
                return None
            self._data.move_to_end(token)
            return control

    def discard(self, token: str) -> None:
        with self._lock:
            self._data.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def _evict_locked(self, now: float) -> None:
        # Drop expired
        for k in list(self._data.keys()):
            _, ts = self._data[k]
            if now - ts > self._ttl:
                del self._data[k]
        # Bound size
        while len(self._data) > self._max:
            self._data.popitem(last=False)


_cache = ElementCache()


def get_cache() -> ElementCache:
    """Return the process-global element cache."""
    return _cache
