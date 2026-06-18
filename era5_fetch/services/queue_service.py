from __future__ import annotations

import logging

from era5_fetch.core.config import Config
from era5_fetch.core.locks import LockRegistry, lock_registry
from era5_fetch.services.downloader import Downloader
from era5_fetch.services.file_service import FileService
from era5_fetch.services.manifest_manager import ManifestEntry, ManifestManager


class QueueService:
    def __init__(
        self,
        config: Config,
        manifest: ManifestManager,
        downloader: Downloader,
        files: FileService,
        logger: logging.Logger,
        locks: LockRegistry = lock_registry,
    ) -> None:
        self._config = config
        self._manifest = manifest
        self._downloader = downloader
        self._files = files
        self._logger = logger
        self._locks = locks

    def download_month(self, year: int, month: int) -> ManifestEntry:
        with self._locks.queue_lock:
            self._downloader.ensure_downloaded(year, month)
            entry = self._require_month(year, month)
            self._trim_unlocked()
            return entry

    def ensure_months(self, months: list[tuple[int, int]]) -> list[ManifestEntry]:
        entries: list[ManifestEntry] = []
        with self._locks.queue_lock:
            for year, month in months:
                if self.is_cached(year, month):
                    self._logger.info("Cache hit year=%s month=%s", year, month)
                    continue
                self._downloader.ensure_downloaded(year, month)
                entries.append(self._require_month(year, month))
            self._trim_unlocked()
        return entries

    def is_cached(self, year: int, month: int) -> bool:
        return self._manifest.find_month(year, month) is not None

    def trim(self) -> list[ManifestEntry]:
        with self._locks.queue_lock:
            return self._trim_unlocked()

    def _trim_unlocked(self) -> list[ManifestEntry]:
        evicted: list[ManifestEntry] = []
        entries = self._manifest.list_entries()
        overflow = len(entries) - self._config.max_months
        if overflow <= 0:
            return evicted

        for entry in entries[:overflow]:
            removed = self._manifest.remove(entry.key)
            if removed is None:
                continue
            self._files.delete(removed.filename)
            evicted.append(removed)
            self._logger.info("Evicted oldest month year=%s month=%s", entry.year, entry.month)
        return evicted

    def list_queue(self) -> list[dict[str, int | bool | str]]:
        return [entry.to_public_dict() for entry in self._manifest.list_entries()]

    def count(self) -> int:
        return self._manifest.count()

    def _require_month(self, year: int, month: int) -> ManifestEntry:
        entry = self._manifest.find_month(year, month)
        if entry is None:
            raise RuntimeError(f"missing manifest entry for {year:04d}-{month:02d}")
        return entry
