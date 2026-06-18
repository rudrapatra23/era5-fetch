from __future__ import annotations

from flask import Blueprint, jsonify


def create_health_blueprint() -> Blueprint:
    blueprint = Blueprint("health", __name__)

    @blueprint.get("/health")
    def health() -> tuple[object, int]:
        return jsonify({"status": "ok"}), 200

    @blueprint.get("/")
    def index() -> tuple[object, int]:
        return jsonify(
            {
                "service": "era5_fetch",
                "status": "ready",
                "endpoints": {
                    "health": "GET /health",
                    "status": "GET /status",
                    "queue": "GET /queue",
                    "files": "GET /files",
                    "data": "GET /data?year=YYYY&month=MM",
                    "download": "POST /download",
                    "bulk_download": "POST /bulk-download",
                    "bootstrap_download": "POST /bootstrap-download",
                    "trim": "POST /queue/trim",
                },
            }
        ), 200

    return blueprint
