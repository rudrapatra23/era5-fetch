from __future__ import annotations

from pathlib import Path

from era5_backend.core.config import Config


class FileService:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._config.ensure_directories()
        self._storage_dir = config.storage_dir
        assert self._storage_dir is not None

    def filename_for(self, key: str, year: int, month: int) -> str:
        return f"era5_land_soil_moisture_{year:04d}_{month:02d}_{key[:16]}.grib"

    def path_for_filename(self, filename: str) -> Path:
        path = (self._storage_dir / filename).resolve()
        if not path.is_relative_to(self._storage_dir):
            raise ValueError("invalid storage filename")
        return path

    def delete(self, filename: str) -> bool:
        path = self.path_for_filename(filename)
        if not path.exists():
            return False
        path.unlink()
        return True

    def size(self, filename: str) -> int:
        return self.path_for_filename(filename).stat().st_size
