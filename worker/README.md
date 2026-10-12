# CloudSentry Worker

Background jobs live here. `cloudsentry-worker` with no arguments checks settings and exits. `ingest-inventory` copies simulator resources into Postgres. The worker calls the simulator over HTTP. It does not import the simulator package.

## Run locally

From the repository root:

```bash
source .venv/bin/activate
pip install -e ./api
pip install -e ./worker
cloudsentry-worker
```

Expected log line: `worker ok`. The process exits with code 0.

`DATABASE_URL` defaults to the local Compose database. `SIMULATOR_BASE_URL` defaults to `http://127.0.0.1:8001`.

## Inventory ingestion

The simulator must be running. From the repository root, after `make migrate`:

```bash
make ingest-inventory
```

That runs `python -m worker.main ingest-inventory`. The log line is `inventory ingest created=N updated=M total=T`.

Rules:

- `GET /resources` is followed with `limit` and `offset` until every resource in `total` is read.
- Each simulator resource becomes one `resources` row. The row count matches that total.
- `owner`, `team`, and `business_criticality` are copied from the `owner`, `team`, and `criticality` tags. A resource missing one of those tags fails the job.
- `name`, `sku`, `power_state`, `schedule`, and `storage_class` are not columns and are not stored.
- Metrics and billing are not ingested.
- Running the job again updates the existing `resource_id` rows. `created` is 0 and the table does not grow.

## Metric rollups

Hourly samples are not copied into Postgres. The job stores one daily rollup per resource and metric name: `avg_value` is that day's mean and `peak_value` is that day's maximum. The window starts at 2025-12-02 00:00 UTC and ends at the simulator clock. Disks and snapshots have no series, so they add no rows. Run inventory ingestion first so every simulator resource already has a row.

A detector query uses calendar days, start inclusive and end exclusive. Because each stored day is a full simulator day, the 30-day average is the mean of the daily averages and the 30-day peak is the max of the daily peaks. For the planted idle VM `i-dev-062`, the 30 days ending 2026-04-01 are `2026-03-02` through `2026-03-31`.

Running the job again updates the same resource, name, and day. The rollup count does not grow.

```bash
make ingest-metrics
```

That runs `python -m worker.main ingest-metrics`. The log line is `metrics ingest created=N updated=M rollups=R resources=S`.
