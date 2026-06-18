from __future__ import annotations

from pathlib import Path, PurePosixPath

from era5_fetch.core.config import Config


class FileService:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._config.ensure_directories()
        self._storage_root = config.storage_root
        self._temp_dir = config.temp_dir
        assert self._storage_root is not None
        assert self._temp_dir is not None

    def filename_for(self, year: int, month: int) -> str:
        return PurePosixPath(f"{year:04d}", f"hydrology_{year:04d}_{month:02d}.nc").as_posix()

    def temp_path_for(self, year: int, month: int) -> Path:
        return self._temp_dir / f"hydrology_{year:04d}_{month:02d}.nc.tmp"

    def path_for_filename(self, filename: str) -> Path:
        relative_path = Path(*PurePosixPath(filename).parts)
        path = (self._storage_root / relative_path).resolve()
        if not path.is_relative_to(self._storage_root):
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
