# ERA5-Land Hydrology Downloader

Production-ready Flask microservice and background daemon for downloading,
caching, and serving monthly ERA5-Land hydrology bundles from the Copernicus
Climate Data Store.

## Features

- One monthly CDS request per bundle.
- One cache entry, lock, and artifact per month.
- Bundled hydrology NetCDF output for `total_precipitation` (`tp`),
  `volumetric_soil_water_layer_1` (`swvl1`), and `surface_runoff` (`ro`).
- Background scheduler for latest-month refresh and bootstrap backfill.
- Download lock deduplication for concurrent duplicate requests.
- Self-cleaning month-based cache with automatic eviction.
- Atomic manifest persistence and startup validation.
- Backward-compatible Flask API and legacy soil-moisture cache readability.
- Immutable `DownloadResult` values with checksum and elapsed-time metadata.

## Package Boundary

The package scope is intentionally narrow:

```text
CDS -> Download -> Validate -> Local Storage -> DownloadResult
```

It does not know about S3, Zarr conversion, HydraAtlas, FastAPI ingestion, or
cloud deployment concerns.

## Storage Layout

New downloads are stored under the configured storage root as one NetCDF per
month, partitioned by year:

```text
storage_root/
2025/
hydrology_2025_01.nc
hydrology_2025_02.nc
2026/
hydrology_2026_01.nc
manifest.json
locks/
tmp/
```

Each NetCDF contains the full hydrology bundle. Legacy flat soil-moisture files
already present in the manifest remain readable.

## Install

Python 3.11 or newer is required.

```bash
pip install -r era5_backend/requirements.txt
```

## Configuration

The service loads environment values from a top-level `.env` file when present.
Environment variables override file values.

```text
CDSAPI_URL=https://cds.climate.copernicus.eu/api
CDSAPI_KEY=your-cds-api-key
```

Supported settings:

- `ERA5_STORAGE_ROOT`: Override bundle and manifest storage root.
- `ERA5_STORAGE_DIR`: Legacy alias for `ERA5_STORAGE_ROOT`.
- `ERA5_LOGS_DIR`: Override log directory.
- `ERA5_MANIFEST_PATH`: Override manifest location.
- `ERA5_MAX_MONTHS`: Rolling cache size in months. Default `480`.
- `ERA5_RETRY_ATTEMPTS`: Download retry count. Default `5`.
- `ERA5_RETRY_BASE_SECONDS`: Exponential backoff base seconds. Default `2`.
- `ERA5_SCHEDULER_ENABLED`: Enable scheduler. Default `true`.
- `ERA5_SCHEDULER_INTERVAL_SECONDS`: Scheduler interval. Default `86400`.
- `ERA5_BOOTSTRAP_MONTHS`: Startup bootstrap window. Default `24`.
- `ERA5_FLASK_HOST`: Flask bind host. Default `0.0.0.0`.
- `ERA5_FLASK_PORT`: Flask bind port. Default `5055`.
- `CDSAPI_URL`: CDS API endpoint.
- `CDSAPI_KEY`: CDS API key.

The runtime bundle is configured in code through `Config.era5_variables` and
defaults to the hydrology set above.

## Run

Start the packaged application:

```bash
python -m era5_backend.app
```

Or run the helper entrypoint:

```bash
python run.py
```

Default service URL:

```text
http://127.0.0.1:5055
```

## API

```text
GET  /health
GET  /status
GET  /queue
GET  /files
GET  /data?year=YYYY&month=MM
POST /download
POST /bulk-download
POST /bootstrap-download
POST /queue/trim
```

Download one month:

```bash
curl -X POST http://localhost:5055/download \
  -H "Content-Type: application/json" \
  -d "{\"year\":2024,\"month\":5}"
```

Bootstrap the latest 24-month window:

```bash
curl -X POST http://localhost:5055/bootstrap-download \
  -H "Content-Type: application/json" \
  -d "{\"months\":24}"
```

## Manifest Model

Each month maps to exactly one artifact and one manifest entry. The entry stores
the relative filename, checksum, and bundled variable aliases while public API
responses remain sanitized and backward compatible.

## Versioning

This refactor establishes the frozen reusable downloader contract released as
`v1.0.0`. Future changes should be bug fixes or backward-compatible maintenance.

## Development

Install test dependencies with:

```bash
pip install -e .[test]
```

Run the focused test suite with:

```bash
pytest -q
```
