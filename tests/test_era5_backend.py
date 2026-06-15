from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import sys

from era5_backend.app import create_app
from era5_backend.core.config import Config
from era5_backend.services.downloader import DownloadResult
from era5_backend.services.file_service import FileService
from era5_backend.services.manifest_manager import ManifestEntry, ManifestManager, utc_now_iso
from era5_backend.services.scheduler import MonthlyScheduler, _month_window


class FakeCdsClient:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests: list[tuple[str, dict[str, object], str]] = []

    def retrieve(self, name: str, request: dict[str, object], target: str) -> object:
        with self._lock:
            self.requests.append((name, request, target))
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
    services = app.config["ERA5_SERVICES"]

    response = app.test_client().post("/download", json={"year": 2024, "month": 5})

    assert response.status_code == 200
    assert response.json["year"] == 2024
    assert response.json["month"] == 5
    assert response.json["cached"] is True
    assert "file" not in response.json
    assert len(cds.requests) == 1
    _, request, target = cds.requests[0]
    assert request["variable"] == [
        "total_precipitation",
        "volumetric_soil_water_layer_1",
        "surface_runoff",
    ]
    assert request["format"] == "netcdf"
    assert target.replace("\\", "/").endswith("tmp/hydrology_2024_05.nc.tmp")
    result = services.downloader.ensure_downloaded(2024, 5)
    assert isinstance(result, DownloadResult)
    assert result.success is True
    assert result.local_path == services.files.path_for_filename("2024/hydrology_2024_05.nc")
    assert result.variables == ("tp", "swvl1", "ro")
    assert result.file_size > 0
    assert len(result.checksum) == 64


def test_concurrent_duplicate_download_uses_one_cds_call(tmp_path: Path) -> None:
    cds = FakeCdsClient()
    app = create_app(make_config(tmp_path), cds_client=cds, start_scheduler=False)
    services = app.config["ERA5_SERVICES"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: services.queue.download_month(2024, 6), range(4)))

    assert {entry.key for entry in results} == {results[0].key}
    assert len(cds.requests) == 1


def test_trim_evicts_oldest_months_and_files(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, max_months=2)
    files = FileService(cfg)
    manifest = ManifestManager(cfg)

    for year, month in [(2024, 1), (2024, 2), (2024, 3)]:
        filename = files.filename_for(year, month)
        path = files.path_for_filename(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake")
        manifest.upsert(
            ManifestEntry(
                key=f"key-{year}-{month}",
                year=year,
                month=month,
                filename=filename,
                size_bytes=4,
                created_at=utc_now_iso(),
                variables=["tp", "swvl1", "ro"],
            )
        )

    app = create_app(cfg, cds_client=FakeCdsClient(), start_scheduler=False)
    response = app.test_client().post("/queue/trim")

    assert response.status_code == 200
    assert response.json["count"] == 2
    assert response.json["evicted"][0]["year"] == 2024
    assert response.json["evicted"][0]["month"] == 1
    assert files.path_for_filename(files.filename_for(2024, 1)).exists() is False


def test_legacy_soil_moisture_month_remains_readable(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    cfg.storage_dir.mkdir(parents=True, exist_ok=True)
    legacy_name = "era5_land_soil_moisture_2024_05_legacy.grib"
    (cfg.storage_dir / legacy_name).write_bytes(b"legacy")
    cfg.manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "legacy-key": {
                        "key": "legacy-key",
                        "year": 2024,
                        "month": 5,
                        "filename": legacy_name,
                        "size_bytes": 6,
                        "created_at": utc_now_iso(),
                        "status": "ready",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(cfg, cds_client=FakeCdsClient(), start_scheduler=False)

    response = app.test_client().post("/download", json={"year": 2024, "month": 5})

    assert response.status_code == 200
    assert response.json["month"] == 5
    assert response.json["cached"] is True


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


def test_scheduler_bootstraps_missing_months_when_cache_is_partial(tmp_path: Path, monkeypatch) -> None:
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
    assert len(cds.requests) == 3


def test_month_window_returns_oldest_to_newest() -> None:
    assert _month_window(2026, 5, 4) == [(2026, 2), (2026, 3), (2026, 4), (2026, 5)]
    assert _month_window(2026, 1, 3) == [(2025, 11), (2025, 12), (2026, 1)]
