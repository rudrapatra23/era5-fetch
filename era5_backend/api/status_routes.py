from __future__ import annotations

from flask import Blueprint, jsonify

from era5_backend.core.config import Config
from era5_backend.services.queue_service import QueueService
from era5_backend.services.scheduler import MonthlyScheduler


def create_status_blueprint(
    config: Config,
    queue: QueueService,
    scheduler: MonthlyScheduler,
) -> Blueprint:
    blueprint = Blueprint("status", __name__)

    @blueprint.get("/status")
    def status() -> tuple[object, int]:
        return jsonify(
            {
                "status": "ready",
                "cached_months": queue.count(),
                "max_months": config.max_months,
                "scheduler_running": scheduler.is_running,
            }
        ), 200

    return blueprint
