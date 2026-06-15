from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

from era5_backend.core.env import load_env_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_env_file(PROJECT_ROOT)


@dataclass(frozen=True)
class Era5Variable:
    name: str
    alias: str


DEFAULT_ERA5_VARIABLES: tuple[Era5Variable, ...] = (
    Era5Variable(name="total_precipitation", alias="tp"),
    Era5Variable(name="volumetric_soil_water_layer_1", alias="swvl1"),
    Era5Variable(name="surface_runoff", alias="ro"),
)


@dataclass(frozen=True)
class Config:
    package_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    storage_root: Path | None = None
    storage_dir: Path | None = None
    logs_dir: Path | None = None
    manifest_path: Path | None = None
    temp_dir: Path | None = None
    locks_dir: Path | None = None
    dataset: str = "reanalysis-era5-land-monthly-means"
    variables: tuple[str, ...] | None = None
    era5_variables: tuple[Era5Variable, ...] | None = None
    max_months: int = 480
    retry_attempts: int = 5
    retry_base_seconds: float = 2.0
    scheduler_enabled: bool = True
    scheduler_check_interval_seconds: int = 86_400
    scheduler_bootstrap_months: int = 24
    flask_host: str = "0.0.0.0"
    flask_port: int = 5055
    cds_config_path: Path | None = None
    cds_api_url: str | None = None
    cds_api_key: str | None = None

    def __post_init__(self) -> None:
        root = self.package_root
        resolved_variables = _resolve_variables(self.variables, self.era5_variables)
        object.__setattr__(self, "era5_variables", resolved_variables)
        object.__setattr__(self, "variables", tuple(variable.name for variable in resolved_variables))
        storage = self.storage_root or self.storage_dir or Path(
            os.getenv("ERA5_STORAGE_ROOT", os.getenv("ERA5_STORAGE_DIR", str(root / "storage")))
        )
        logs = self.logs_dir or Path(os.getenv("ERA5_LOGS_DIR", str(root / "logs")))
        resolved_storage = Path(storage).resolve()
        object.__setattr__(self, "storage_root", resolved_storage)
        object.__setattr__(self, "storage_dir", resolved_storage)
        object.__setattr__(self, "logs_dir", Path(logs).resolve())
        manifest = os.getenv("ERA5_MANIFEST_PATH")
        manifest_path = self.manifest_path
        if manifest_path is None and manifest:
            manifest_path = Path(manifest).resolve()
        object.__setattr__(
            self,
            "manifest_path",
            manifest_path or resolved_storage / "manifest.json",
        )
        temp_dir = self.temp_dir or resolved_storage / "tmp"
        locks_dir = self.locks_dir or resolved_storage / "locks"
        object.__setattr__(self, "temp_dir", Path(temp_dir).resolve())
        object.__setattr__(self, "locks_dir", Path(locks_dir).resolve())
        cds_config = self.cds_config_path or Path(
            os.getenv("CDSAPI_RC", str(Path.home() / ".cdsapirc"))
        )
        object.__setattr__(self, "cds_config_path", Path(cds_config).resolve())
        object.__setattr__(self, "cds_api_url", self.cds_api_url or os.getenv("CDSAPI_URL"))
        object.__setattr__(self, "cds_api_key", self.cds_api_key or os.getenv("CDSAPI_KEY"))

    @property
    def variable_aliases(self) -> tuple[str, ...]:
        assert self.era5_variables is not None
        return tuple(variable.alias for variable in self.era5_variables)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            max_months=int(os.getenv("ERA5_MAX_MONTHS", "480")),
            retry_attempts=int(os.getenv("ERA5_RETRY_ATTEMPTS", "5")),
            retry_base_seconds=float(os.getenv("ERA5_RETRY_BASE_SECONDS", "2")),
            scheduler_enabled=os.getenv("ERA5_SCHEDULER_ENABLED", "true").lower()
            in {"1", "true", "yes"},
            scheduler_check_interval_seconds=int(
                os.getenv("ERA5_SCHEDULER_INTERVAL_SECONDS", "86400")
            ),
            scheduler_bootstrap_months=int(os.getenv("ERA5_BOOTSTRAP_MONTHS", "24")),
            flask_host=os.getenv("ERA5_FLASK_HOST", "0.0.0.0"),
            flask_port=int(os.getenv("ERA5_FLASK_PORT", "5055")),
        )

    def cds_credentials_available(self) -> bool:
        assert self.cds_config_path is not None
        if self.cds_api_url and self.cds_api_key and self.cds_api_key != "replace-with-your-cds-api-key":
            return True
        return self.cds_config_path.exists() and self.cds_config_path.stat().st_size > 0

    def ensure_directories(self) -> None:
        assert self.storage_root is not None
        assert self.storage_dir is not None
        assert self.logs_dir is not None
        assert self.temp_dir is not None
        assert self.locks_dir is not None
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.locks_dir.mkdir(parents=True, exist_ok=True)


def _resolve_variables(
    variables: tuple[str, ...] | None,
    era5_variables: tuple[Era5Variable, ...] | None,
) -> tuple[Era5Variable, ...]:
    if era5_variables is not None:
        return era5_variables
    if variables is not None:
        return tuple(Era5Variable(name=name, alias=name) for name in variables)
    return DEFAULT_ERA5_VARIABLES


config = Config.from_env()
