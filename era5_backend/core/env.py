from __future__ import annotations

import os
from pathlib import Path


def load_env_file(project_root: Path) -> Path | None:
    for env_path in _candidate_paths(project_root):
        if env_path.exists() and env_path.is_file():
            _load_pairs(env_path)
            return env_path
    return None


def _candidate_paths(project_root: Path) -> tuple[Path, ...]:
    cwd_env = Path.cwd() / ".env"
    root_env = project_root / ".env"
    package_env = project_root / "era5_backend" / ".env"
    return tuple(dict.fromkeys((cwd_env.resolve(), root_env.resolve(), package_env.resolve())))


def _load_pairs(env_path: Path) -> None:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value
