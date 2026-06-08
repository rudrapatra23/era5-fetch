from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Protocol

from era5_backend.core.config import Config
from era5_backend.core.hashing import soil_moisture_hash
from era5_backend.core.locks import LockRegistry, lock_registry
from era5_backend.core.validation import validate_year_month
from era5_backend.services.file_service import FileService
from era5_backend.services.manifest_manager import ManifestEntry, ManifestManager, utc_now_iso


class CdsClient(Protocol):
    def retrieve(self, name: str, request: dict[str, object], target: str) -> object:
        ...


class Downloader:
    def __init__(
        self,
        config: Config,
        manifest: ManifestManager,
        files: FileService,
        logger: logging.Logger,
        locks: LockRegistry = lock_registry,
        cds_client: CdsClient | None = None,
    ) -> None:
        self._config = config
        self._manifest = manifest
        self._files = files
        self._logger = logger
        self._locks = locks
        self._cds_client = cds_client

    def ensure_downloaded(self, year: int, month: int) -> ManifestEntry:
        validate_year_month(year, month)
        key = soil_moisture_hash(year, month, self._config.variables)
        existing = self._manifest.get(key)
        if existing is not None:
            self._logger.info("Cache hit year=%s month=%s", year, month)
            return existing

        with self._locks.download_lock(key):
            existing = self._manifest.get(key)
            if existing is not None:
                self._logger.info("Cache hit year=%s month=%s", year, month)
                return existing
            return self._download_locked(key, year, month)

    def _download_locked(self, key: str, year: int, month: int) -> ManifestEntry:
        filename = self._files.filename_for(key, year, month)
        target = self._files.path_for_filename(filename)
        temp_target = target.with_suffix(".grib.tmp")
        request = self._request(year, month)
        self._logger.info("Download started year=%s month=%s", year, month)

        for attempt in range(1, self._config.retry_attempts + 1):
            try:
                self._retrieve(request, temp_target)
                temp_target.replace(target)
                entry = ManifestEntry(
                    key=key,
                    year=year,
                    month=month,
                    filename=filename,
                    size_bytes=target.stat().st_size,
                    created_at=utc_now_iso(),
                )
                self._manifest.upsert(entry)
                self._logger.info("Download completed year=%s month=%s", year, month)
                return entry
            except Exception:
                if temp_target.exists():
                    temp_target.unlink()
                if attempt >= self._config.retry_attempts:
                    self._logger.exception("Download failed year=%s month=%s", year, month)
                    raise
                self._logger.warning(
                    "Retry attempt %s/%s year=%s month=%s",
                    attempt + 1,
                    self._config.retry_attempts,
                    year,
                    month,
                )
                time.sleep(self._config.retry_base_seconds * (2 ** (attempt - 1)))
        raise RuntimeError("download retry loop exited unexpectedly")

    def _retrieve(self, request: dict[str, object], target: Path) -> None:
        client = self._cds_client or self._create_cds_client()
        client.retrieve(self._config.dataset, request, str(target))

    def _create_cds_client(self) -> CdsClient:
        try:
            import cdsapi
        except ImportError as exc:
            raise RuntimeError("cdsapi is required for ERA5 downloads") from exc
        if self._config.cds_api_url and self._config.cds_api_key:
            return cdsapi.Client(url=self._config.cds_api_url, key=self._config.cds_api_key)
        return cdsapi.Client()

    def _request(self, year: int, month: int) -> dict[str, object]:
        return {
            "product_type": "monthly_averaged_reanalysis",
            "variable": list(self._config.variables),
            "year": f"{year:04d}",
            "month": f"{month:02d}",
            "time": "00:00",
            "format": "grib",
        }
