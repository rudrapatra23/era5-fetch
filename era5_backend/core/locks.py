from __future__ import annotations

from collections import defaultdict
from threading import Lock


class LockRegistry:
    def __init__(self) -> None:
        self.manifest_lock = Lock()
        self.queue_lock = Lock()
        self._registry_lock = Lock()
        self._download_locks: defaultdict[str, Lock] = defaultdict(Lock)

    def download_lock(self, key: str) -> Lock:
        with self._registry_lock:
            return self._download_locks[key]


lock_registry = LockRegistry()
