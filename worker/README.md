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
