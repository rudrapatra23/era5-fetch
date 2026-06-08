from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from era5_backend.core.config import Config
from era5_backend.core.locks import LockRegistry, lock_registry


@dataclass(frozen=True)
class ManifestEntry:
    key: str
    year: int
    month: int
    filename: str
    size_bytes: int
    created_at: str
    status: str = "ready"

    def to_public_dict(self) -> dict[str, int | bool | str]:
        return {
            "year": self.year,
            "month": self.month,
            "cached": self.status == "ready",
            "status": self.status,
            "key": self.key,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }


class ManifestManager:
    def __init__(self, config: Config, locks: LockRegistry = lock_registry) -> None:
        self._config = config
        self._locks = locks
        self._entries: dict[str, ManifestEntry] = {}
        self._manifest_path = config.manifest_path
        assert self._manifest_path is not None
        self._storage_dir = config.storage_dir
        assert self._storage_dir is not None
        self._load_and_validate()

    def _load_and_validate(self) -> None:
        with self._locks.manifest_lock:
            if not self._manifest_path.exists():
                self._write_locked()
                return
            try:
                content = self._manifest_path.read_text(encoding="utf-8").strip()
                if not content:
                    self._write_locked()
                    return
                data = json.loads(content)
            except json.JSONDecodeError:
                self._write_locked()
                return
            raw_entries = data.get("entries", {})
            valid_entries: dict[str, ManifestEntry] = {}
            for key, raw in raw_entries.items():
                entry = ManifestEntry(**raw)
                file_path = self._storage_dir / entry.filename
                if file_path.exists() and entry.key == key:
                    valid_entries[key] = entry
            self._entries = valid_entries
            self._write_locked()

    def _write_locked(self) -> None:
        payload = {
            "version": 1,
            "entries": {key: asdict(entry) for key, entry in self._entries.items()},
        }
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._manifest_path.parent,
            delete=False,
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self._manifest_path)

    def get(self, key: str) -> ManifestEntry | None:
        with self._locks.manifest_lock:
            return self._entries.get(key)

    def find_month(self, year: int, month: int) -> ManifestEntry | None:
        with self._locks.manifest_lock:
            for entry in self._entries.values():
                if entry.year == year and entry.month == month:
                    return entry
            return None

    def upsert(self, entry: ManifestEntry) -> None:
        with self._locks.manifest_lock:
            self._entries[entry.key] = entry
            self._write_locked()

    def remove(self, key: str) -> ManifestEntry | None:
        with self._locks.manifest_lock:
            entry = self._entries.pop(key, None)
            if entry is not None:
                self._write_locked()
            return entry

    def list_entries(self) -> list[ManifestEntry]:
        with self._locks.manifest_lock:
            return sorted(self._entries.values(), key=lambda item: (item.year, item.month))

    def count(self) -> int:
        with self._locks.manifest_lock:
            return len(self._entries)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
