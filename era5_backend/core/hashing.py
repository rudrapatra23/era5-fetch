from __future__ import annotations

import hashlib
import json


def soil_moisture_hash(year: int, month: int, variables: tuple[str, ...]) -> str:
    payload = {
        "dataset": "era5-land-monthly-soil-moisture",
        "year": year,
        "month": month,
        "variables": sorted(variables),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
