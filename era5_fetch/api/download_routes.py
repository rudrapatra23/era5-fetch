from __future__ import annotations

from flask import Blueprint, jsonify, request

from era5_fetch.core.validation import parse_int, validate_year_month
from era5_fetch.services.manifest_manager import ManifestManager
from era5_fetch.services.queue_service import QueueService
from era5_fetch.services.scheduler import _month_window


def create_download_blueprint(
    manifest: ManifestManager,
    queue: QueueService,
) -> Blueprint:
    blueprint = Blueprint("download", __name__)

    @blueprint.get("/data")
    def data_status() -> tuple[object, int]:
        try:
            year, month = _year_month_from_args()
            validate_year_month(year, month)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        entry = manifest.find_month(year, month)
        if entry is None:
            return jsonify({"year": year, "month": month, "cached": False, "status": "missing"}), 404
        return jsonify(entry.to_public_dict()), 200

    @blueprint.get("/files")
    def files() -> tuple[object, int]:
        entries = [entry.to_public_dict() for entry in manifest.list_entries()]
        return jsonify({"count": len(entries), "files": entries}), 200

    @blueprint.get("/download")
    def download_usage() -> tuple[object, int]:
        return jsonify(
            {
                "error": "method not allowed",
                "message": "Use POST /download with JSON body {'year': 2024, 'month': 5}.",
                "example_powershell": (
                    "Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5001/download "
                    "-ContentType 'application/json' -Body '{\"year\":2024,\"month\":5}'"
                ),
            }
        ), 405

    @blueprint.post("/download")
    def download() -> tuple[object, int]:
        try:
            payload = request.get_json(silent=True) or {}
            year = parse_int(payload.get("year"), "year")
            month = parse_int(payload.get("month"), "month")
            entry = queue.download_month(year, month)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": "download failed", "detail": str(exc)}), 502
        return jsonify(entry.to_public_dict()), 200

    @blueprint.post("/bulk-download")
    def bulk_download() -> tuple[object, int]:
        try:
            months = _months_from_payload(request.get_json(silent=True) or {})
            entries = [queue.download_month(year, month).to_public_dict() for year, month in months]
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": "bulk download failed", "detail": str(exc)}), 502
        return jsonify({"count": len(entries), "entries": entries, "status": "ready"}), 200

    @blueprint.post("/bootstrap-download")
    def bootstrap_download() -> tuple[object, int]:
        try:
            payload = request.get_json(silent=True) or {}
            months_count = parse_int(payload.get("months", 24), "months")
            year = parse_int(payload.get("newest_year"), "newest_year") if "newest_year" in payload else None
            month = parse_int(payload.get("newest_month"), "newest_month") if "newest_month" in payload else None
            newest_year, newest_month = _newest_month(year, month)
            months = _month_window(newest_year, newest_month, months_count)
            entries = [entry.to_public_dict() for entry in queue.ensure_months(months)]
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"error": "bootstrap download failed", "detail": str(exc)}), 502
        return jsonify(
            {
                "requested_months": len(months),
                "downloaded_months": len(entries),
                "entries": entries,
                "status": "ready",
            }
        ), 200

    return blueprint


def _year_month_from_args() -> tuple[int, int]:
    return parse_int(request.args.get("year"), "year"), parse_int(request.args.get("month"), "month")


def _newest_month(year: int | None, month: int | None) -> tuple[int, int]:
    if year is None and month is None:
        from era5_fetch.core.validation import previous_month

        return previous_month()
    if year is None or month is None:
        raise ValueError("newest_year and newest_month must be provided together")
    validate_year_month(year, month)
    return year, month


def _months_from_payload(payload: dict[str, object]) -> list[tuple[int, int]]:
    raw_months = payload.get("months")
    if isinstance(raw_months, list):
        months = [
            (parse_int(item.get("year"), "year"), parse_int(item.get("month"), "month"))
            for item in raw_months
            if isinstance(item, dict)
        ]
        if len(months) != len(raw_months):
            raise ValueError("months must contain objects with year and month")
    else:
        months = _range_from_payload(payload)
    for year, month in months:
        validate_year_month(year, month)
    return months


def _range_from_payload(payload: dict[str, object]) -> list[tuple[int, int]]:
    start_year = parse_int(payload.get("start_year"), "start_year")
    start_month = parse_int(payload.get("start_month"), "start_month")
    end_year = parse_int(payload.get("end_year"), "end_year")
    end_month = parse_int(payload.get("end_month"), "end_month")
    validate_year_month(start_year, start_month)
    validate_year_month(end_year, end_month)
    if (start_year, start_month) > (end_year, end_month):
        raise ValueError("start month must be before or equal to end month")
    months: list[tuple[int, int]] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months
