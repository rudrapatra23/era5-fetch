from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from pathlib import Path
import time
from typing import Protocol

from era5_fetch.core.checksums import sha256_file
from era5_fetch.core.config import Config
from era5_fetch.core.hashing import month_bundle_hash
from era5_fetch.core.locks import LockRegistry, lock_registry
from era5_fetch.core.validation import validate_year_month
from era5_fetch.services.file_service import FileService
from era5_fetch.services.manifest_manager import ManifestEntry, ManifestManager, utc_now_iso


class CdsClient(Protocol):
    def retrieve(self, name: str, request: dict[str, object], target: str) -> object:
        ...


@dataclass(frozen=True)
class DownloadResult:
    success: bool
    local_path: Path
    year: int
    month: int
    variables: tuple[str, ...]
    file_size: int
    checksum: str
    created_at: str
    elapsed_seconds: float


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

    def ensure_downloaded(self, year: int, month: int) -> DownloadResult:
        validate_year_month(year, month)
        key = month_bundle_hash(year, month, self._config.dataset, self._config.variables)
        existing = self._manifest.get(key)
        if existing is not None:
            self._logger.info("Cache hit year=%s month=%s", year, month)
            return self._result_from_entry(existing)
        month_entry = self._manifest.find_month(year, month)
        if month_entry is not None:
            self._logger.info("Legacy cache hit year=%s month=%s", year, month)
            return self._result_from_entry(month_entry)

        with self._locks.download_lock(key):
            existing = self._manifest.get(key)
            if existing is not None:
                self._logger.info("Cache hit year=%s month=%s", year, month)
                return self._result_from_entry(existing)
            month_entry = self._manifest.find_month(year, month)
            if month_entry is not None:
                self._logger.info("Legacy cache hit year=%s month=%s", year, month)
                return self._result_from_entry(month_entry)
            return self._download_locked(key, year, month)

    def _download_locked(self, key: str, year: int, month: int) -> DownloadResult:
        filename = self._files.filename_for(year, month)
        target = self._files.path_for_filename(filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_target = self._files.temp_path_for(year, month)
        request = self._request(year, month)
        self._logger.info("Download started year=%s month=%s", year, month)
        started_at = time.perf_counter()

        for attempt in range(1, self._config.retry_attempts + 1):
            try:
                self._retrieve(request, temp_target)
                self._validate_artifact(temp_target)
                temp_target.replace(target)
                checksum = sha256_file(target)
                entry = ManifestEntry(
                    key=key,
                    year=year,
                    month=month,
                    filename=filename,
                    size_bytes=target.stat().st_size,
                    created_at=utc_now_iso(),
                    checksum=checksum,
                    variables=list(self._config.variable_aliases),
                )
                self._manifest.upsert(entry)
                self._logger.info("Download completed year=%s month=%s", year, month)
                return self._result_from_entry(entry, time.perf_counter() - started_at)
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
            "format": "netcdf",
        }

    def _result_from_entry(self, entry: ManifestEntry, elapsed_seconds: float = 0.0) -> DownloadResult:
        target = self._files.path_for_filename(entry.filename)
        checksum = entry.checksum or sha256_file(target)
        size_bytes = target.stat().st_size
        if entry.checksum != checksum or entry.size_bytes != size_bytes:
            entry = replace(entry, checksum=checksum, size_bytes=size_bytes)
            self._manifest.upsert(entry)
        return DownloadResult(
            success=True,
            local_path=target,
            year=entry.year,
            month=entry.month,
            variables=self._variables_for_entry(entry),
            file_size=size_bytes,
            checksum=checksum,
            created_at=entry.created_at,
            elapsed_seconds=elapsed_seconds,
        )

    def _validate_artifact(self, path: Path) -> None:
        if not path.exists():
            raise RuntimeError("downloaded file is missing")
        if path.stat().st_size <= 0:
            raise RuntimeError("downloaded file is empty")

    def _variables_for_entry(self, entry: ManifestEntry) -> tuple[str, ...]:
        if entry.variables:
            return tuple(entry.variables)
        if "soil_moisture" in entry.filename:
            return ("swvl1",)
        return self._config.variable_aliases
