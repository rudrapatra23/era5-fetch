from __future__ import annotations

from dataclasses import dataclass

from flask import Flask

from era5_backend.api.download_routes import create_download_blueprint
from era5_backend.api.health_routes import create_health_blueprint
from era5_backend.api.queue_routes import create_queue_blueprint
from era5_backend.api.status_routes import create_status_blueprint
from era5_backend.core.config import Config, config as default_config
from era5_backend.core.logger import configure_logging
from era5_backend.services.downloader import CdsClient, Downloader
from era5_backend.services.file_service import FileService
from era5_backend.services.manifest_manager import ManifestManager
from era5_backend.services.queue_service import QueueService
from era5_backend.services.scheduler import MonthlyScheduler


@dataclass(frozen=True)
class Services:
    manifest: ManifestManager
    files: FileService
    downloader: Downloader
    queue: QueueService
    scheduler: MonthlyScheduler


def create_app(
    config: Config | None = None,
    cds_client: CdsClient | None = None,
    start_scheduler: bool = True,
) -> Flask:
    runtime_config = config or default_config
    logger = configure_logging(runtime_config)
    files = FileService(runtime_config)
    manifest = ManifestManager(runtime_config)
    downloader = Downloader(runtime_config, manifest, files, logger, cds_client=cds_client)
    queue = QueueService(runtime_config, manifest, downloader, files, logger)
    scheduler = MonthlyScheduler(runtime_config, queue, logger)

    app = Flask(__name__)
    services = Services(manifest, files, downloader, queue, scheduler)
    app.config["ERA5_SERVICES"] = services
    app.config["ERA5_CONFIG"] = runtime_config

    app.register_blueprint(create_health_blueprint())
    app.register_blueprint(create_status_blueprint(runtime_config, queue, scheduler))
    app.register_blueprint(create_queue_blueprint(queue))
    app.register_blueprint(create_download_blueprint(manifest, queue))

    if start_scheduler and _scheduler_can_start(runtime_config, cds_client):
        scheduler.start()
    elif start_scheduler and runtime_config.scheduler_enabled:
        logger.warning(
            "Scheduler not started because CDS API credentials are missing. "
            "Set CDSAPI_URL and CDSAPI_KEY in .env, create %s, "
            "or set ERA5_SCHEDULER_ENABLED=false.",
            runtime_config.cds_config_path,
        )

    @app.teardown_appcontext
    def _teardown(_error: object | None = None) -> None:
        return None

    return app


def _scheduler_can_start(config: Config, cds_client: CdsClient | None) -> bool:
    if not config.scheduler_enabled:
        return False
    return cds_client is not None or config.cds_credentials_available()


def main() -> None:
    application = create_app()
    cfg = application.config["ERA5_CONFIG"]
    application.run(host=cfg.flask_host, port=cfg.flask_port, debug=False)


if __name__ == "__main__":
    main()
