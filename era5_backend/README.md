# ERA5-Land Soil Moisture Backend

Self-contained Flask backend for pre-downloading and serving cached ERA5-Land
monthly soil moisture metadata. It is independent of any existing application
and can be imported as a package or run as a standalone microservice.

## Features

- ERA5-Land monthly GRIB downloads through the CDS API.
- In-memory manifest cache with a single shared manifest lock.
- Atomic `manifest.json` writes and startup cleanup of stale entries.
- SHA256 cache keys per year/month/variable request.
- Per-hash download locks so duplicate concurrent requests trigger one download.
- Rolling 40-year queue with automatic oldest-month eviction.
- Daemon scheduler that refreshes the newest available month without blocking Flask.
- Sanitized REST responses that never expose internal filesystem paths.
- Production logging to rotating log files and stdout.

## Setup

Install Python 3.11 or newer, then install dependencies:

```bash
pip install -r era5_backend/requirements.txt
```

Create a top-level `.env` file from `.env.example` and add your CDS API
credentials:

```text
CDSAPI_URL=https://cds.climate.copernicus.eu/api
CDSAPI_KEY=your-cds-api-key
```

The backend also supports the official `cdsapi` `.cdsapirc` file in your home
directory. Process environment variables take precedence over `.env` values.

## Run

```bash
python -m era5_backend.app
```

Default server:

```text
http://0.0.0.0:5055
```

## Environment

- `ERA5_STORAGE_DIR`: Override GRIB and manifest storage directory.
- `ERA5_LOGS_DIR`: Override log directory.
- `ERA5_MANIFEST_PATH`: Override manifest location.
- `ERA5_MAX_MONTHS`: Rolling cache size, defaults to `480`.
- `ERA5_RETRY_ATTEMPTS`: Download retry count, defaults to `5`.
- `ERA5_RETRY_BASE_SECONDS`: Exponential backoff base, defaults to `2`.
- `ERA5_SCHEDULER_ENABLED`: Enable scheduler, defaults to `true`.
- `ERA5_SCHEDULER_INTERVAL_SECONDS`: Scheduler loop interval, defaults to one day.
- `ERA5_BOOTSTRAP_MONTHS`: Months to download when cache is empty, defaults to `24`.
- `ERA5_FLASK_HOST`: Flask host, defaults to `0.0.0.0`.
- `ERA5_FLASK_PORT`: Flask port, defaults to `5055`.
- `CDSAPI_URL`: CDS API endpoint.
- `CDSAPI_KEY`: CDS API key.

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

Bulk download explicit months:

```json
{
  "months": [
    {"year": 2024, "month": 4},
    {"year": 2024, "month": 5}
  ]
}
```

Bulk download a range:

```json
{
  "start_year": 2023,
  "start_month": 1,
  "end_year": 2024,
  "end_month": 12
}
```

Download the latest 24-month bootstrap window immediately:

```bash
curl -X POST http://localhost:5055/bootstrap-download \
  -H "Content-Type: application/json" \
  -d "{\"months\":24}"
```

Example sanitized response:

```json
{
  "year": 2024,
  "month": 5,
  "cached": true,
  "status": "ready"
}
```

## Testing

```bash
pytest -q
```

The tests use a fake CDS client and do not call the network.
