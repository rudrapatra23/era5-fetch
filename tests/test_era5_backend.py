from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import sys

from era5_backend.app import create_app
from era5_backend.core.config import Config
from era5_backend.core.hashing import soil_moisture_hash
from era5_backend.core.env import load_env_file
from era5_backend.services.file_service import FileService
from era5_backend.services.manifest_manager import ManifestEntry, ManifestManager, utc_now_iso
from era5_backend.services.scheduler import MonthlyScheduler, _month_window


class FakeCdsClient:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()

    def retrieve(self, name: str, request: dict[str, object], target: str) -> object:
        with self._lock:
            self.calls += 1
        Path(target).write_bytes(b"fake-grib")
        return None


def make_config(tmp_path: Path, max_months: int = 480) -> Config:
    return Config(
        storage_dir=tmp_path / "storage",
        logs_dir=tmp_path / "logs",
        manifest_path=tmp_path / "storage" / "manifest.json",
        max_months=max_months,
        retry_base_seconds=0,
        scheduler_enabled=False,
        cds_config_path=tmp_path / ".cdsapirc",
    )


def test_download_endpoint_caches_month(tmp_path: Path) -> None:
    cds = FakeCdsClient()
    app = create_app(make_config(tmp_path), cds_client=cds, start_scheduler=False)

    response = app.test_client().post("/download", json={"year": 2024, "month": 5})

    assert response.status_code == 200
    assert response.json["year"] == 2024
    assert response.json["month"] == 5
    assert response.json["cached"] is True
    assert "file" not in response.json
    assert cds.calls == 1


def test_concurrent_duplicate_download_uses_one_cds_call(tmp_path: Path) -> None:
    cds = FakeCdsClient()
    app = create_app(make_config(tmp_path), cds_client=cds, start_scheduler=False)
    services = app.config["ERA5_SERVICES"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: services.queue.download_month(2024, 6), range(4)))

    assert {entry.key for entry in results} == {results[0].key}
    assert cds.calls == 1


def test_trim_evicts_oldest_months_and_files(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, max_months=2)
    files = FileService(cfg)
    manifest = ManifestManager(cfg)
    variables = cfg.variables

    for year, month in [(2024, 1), (2024, 2), (2024, 3)]:
        key = soil_moisture_hash(year, month, variables)
        filename = files.filename_for(key, year, month)
        files.path_for_filename(filename).write_bytes(b"fake")
        manifest.upsert(
            ManifestEntry(
                key=key,
                year=year,
                month=month,
                filename=filename,
                size_bytes=4,
                created_at=utc_now_iso(),
            )
        )

    app = create_app(cfg, cds_client=FakeCdsClient(), start_scheduler=False)
    response = app.test_client().post("/queue/trim")

    assert response.status_code == 200
    assert response.json["count"] == 2
    assert response.json["evicted"][0]["year"] == 2024
    assert response.json["evicted"][0]["month"] == 1


def test_data_missing_is_sanitized(tmp_path: Path) -> None:
    app = create_app(make_config(tmp_path), cds_client=FakeCdsClient(), start_scheduler=False)

    response = app.test_client().get("/data?year=2024&month=5")

    assert response.status_code == 404
    assert response.json == {"year": 2024, "month": 5, "cached": False, "status": "missing"}


def test_scheduler_does_not_start_without_cds_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CDSAPI_URL", raising=False)
    monkeypatch.delenv("CDSAPI_KEY", raising=False)
    cfg = Config(
        storage_dir=tmp_path / "storage",
        logs_dir=tmp_path / "logs",
        manifest_path=tmp_path / "storage" / "manifest.json",
        retry_base_seconds=0,
        scheduler_enabled=True,
        cds_config_path=tmp_path / "missing-cdsapirc",
    )

    app = create_app(cfg, start_scheduler=True)
    services = app.config["ERA5_SERVICES"]

    assert services.scheduler.is_running is False


def test_env_file_loads_cds_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CDSAPI_URL", raising=False)
    monkeypatch.delenv("CDSAPI_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "CDSAPI_URL=https://example.test/api\nCDSAPI_KEY=test-key\n",
        encoding="utf-8",
    )

    loaded = load_env_file(tmp_path)
    cfg = Config(
        storage_dir=tmp_path / "storage",
        logs_dir=tmp_path / "logs",
        manifest_path=tmp_path / "storage" / "manifest.json",
        cds_config_path=tmp_path / "missing-cdsapirc",
    )

    assert loaded == tmp_path / ".env"
    assert cfg.cds_credentials_available() is True
    assert cfg.cds_api_url == "https://example.test/api"
    assert cfg.cds_api_key == "test-key"


def test_placeholder_cds_key_is_not_available(tmp_path: Path) -> None:
    cfg = Config(
        storage_dir=tmp_path / "storage",
        logs_dir=tmp_path / "logs",
        manifest_path=tmp_path / "storage" / "manifest.json",
        cds_config_path=tmp_path / "missing-cdsapirc",
        cds_api_url="https://cds.climate.copernicus.eu/api",
        cds_api_key="replace-with-your-cds-api-key",
    )

    assert cfg.cds_credentials_available() is False


def test_downloader_passes_env_credentials_to_cdsapi(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    class CapturingClient:
        def __init__(self, url: str | None = None, key: str | None = None) -> None:
            captured["url"] = url or ""
            captured["key"] = key or ""

    monkeypatch.setitem(sys.modules, "cdsapi", SimpleNamespace(Client=CapturingClient))
    cfg = Config(
        storage_dir=tmp_path / "storage",
        logs_dir=tmp_path / "logs",
        manifest_path=tmp_path / "storage" / "manifest.json",
        cds_api_url="https://example.test/api",
        cds_api_key="test-key",
    )
    app = create_app(cfg, start_scheduler=False)
    services = app.config["ERA5_SERVICES"]

    services.downloader._create_cds_client()

    assert captured == {"url": "https://example.test/api", "key": "test-key"}


def test_month_window_returns_oldest_to_newest() -> None:
    assert _month_window(2026, 5, 4) == [(2026, 2), (2026, 3), (2026, 4), (2026, 5)]
    assert _month_window(2026, 1, 3) == [(2025, 11), (2025, 12), (2026, 1)]


def test_scheduler_bootstraps_empty_cache(tmp_path: Path, monkeypatch) -> None:
    class RecordingQueue:
        def __init__(self) -> None:
            self.downloaded: list[tuple[int, int]] = []

        def count(self) -> int:
            return 0

        def is_cached(self, year: int, month: int) -> bool:
            return False

        def ensure_months(self, months: list[tuple[int, int]]) -> list[object]:
            self.downloaded.extend(months)
            return [object() for _ in months]

        def download_month(self, year: int, month: int) -> object:
            self.downloaded.append((year, month))
            return object()

    monkeypatch.setattr("era5_backend.services.scheduler.previous_month", lambda: (2026, 5))
    cfg = Config(
        storage_dir=tmp_path / "storage",
        logs_dir=tmp_path / "logs",
        manifest_path=tmp_path / "storage" / "manifest.json",
        scheduler_bootstrap_months=3,
    )
    queue = RecordingQueue()
    app = create_app(cfg, cds_client=FakeCdsClient(), start_scheduler=False)
    logger = app.logger
    scheduler = MonthlyScheduler(cfg, queue, logger)

    scheduler.trigger_once()

    assert queue.downloaded == [(2026, 3), (2026, 4), (2026, 5)]


def test_scheduler_bootstraps_missing_months_when_cache_is_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class PartialQueue:
        def __init__(self) -> None:
            self.cached = {(2026, 5)}
            self.requested: list[tuple[int, int]] = []

        def is_cached(self, year: int, month: int) -> bool:
            return (year, month) in self.cached

        def ensure_months(self, months: list[tuple[int, int]]) -> list[object]:
            self.requested.extend(months)
            return [object() for _ in months]

        def count(self) -> int:
            return len(self.cached)

        def download_month(self, year: int, month: int) -> object:
            self.requested.append((year, month))
            return object()

    monkeypatch.setattr("era5_backend.services.scheduler.previous_month", lambda: (2026, 5))
    cfg = Config(
        storage_dir=tmp_path / "storage",
        logs_dir=tmp_path / "logs",
        manifest_path=tmp_path / "storage" / "manifest.json",
        scheduler_bootstrap_months=3,
    )
    queue = PartialQueue()
    app = create_app(cfg, cds_client=FakeCdsClient(), start_scheduler=False)
    scheduler = MonthlyScheduler(cfg, queue, app.logger)

    scheduler.trigger_once()

    assert queue.requested == [(2026, 3), (2026, 4)]


def test_bootstrap_download_endpoint_downloads_missing_window(tmp_path: Path) -> None:
    cds = FakeCdsClient()
    app = create_app(make_config(tmp_path), cds_client=cds, start_scheduler=False)

    response = app.test_client().post(
        "/bootstrap-download",
        json={"months": 3, "newest_year": 2024, "newest_month": 5},
    )

    assert response.status_code == 200
    assert response.json["requested_months"] == 3
    assert response.json["downloaded_months"] == 3
    assert cds.calls == 3
