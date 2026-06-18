from __future__ import annotations

from flask import Blueprint, jsonify

from era5_fetch.services.queue_service import QueueService


def create_queue_blueprint(queue: QueueService) -> Blueprint:
    blueprint = Blueprint("queue", __name__)

    @blueprint.get("/queue")
    def queue_status() -> tuple[object, int]:
        entries = queue.list_queue()
        return jsonify({"count": len(entries), "entries": entries}), 200

    @blueprint.post("/queue/trim")
    def trim_queue() -> tuple[object, int]:
        evicted = queue.trim()
        return jsonify(
            {
                "evicted": [entry.to_public_dict() for entry in evicted],
                "count": queue.count(),
                "status": "ready",
            }
        ), 200

    return blueprint
