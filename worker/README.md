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

That runs `python -m worker.main ingest-inventory`. The log line is `inventory ingest created=N updated=M total=T absent=A`.

Rules:

- `GET /resources` is followed with `limit` and `offset` until every resource in `total` is read.
- Each simulator resource becomes one `resources` row. A later full sync that omits it sets `present` to false and leaves the row in place.
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

## Billing

Each simulator daily line becomes one `cost_records` row linked to its resource. `amount` is dollars (`cents / 100`). `period_start` is that UTC day and `period_end` is the next UTC day. The job reads December 2025 through the last day before the simulator clock. March 2026 is a full month when the clock is still 2026-04-01. Run inventory ingestion first.

`monthly_cents(year, month)` sums those rows back to integer cents for one resource or one account. That sum matches the simulator month total. A second run updates the same resource and period, so the row count does not grow.

```bash
make ingest-billing
```

That runs `python -m worker.main ingest-billing`. The log line is `billing ingest created=N updated=M records=R`.

## Dependencies, incidents, and tags

`make ingest-knowledge` refreshes every simulator resource, including `owner`, `team`, `business_criticality`, and the tag map. It then stores dependency edges and incidents. An edge is unique for its source, target, and relationship. An incident is unique for its id. Lookup is `dependencies_of(resource_id)` and `IncidentRepository.for_resource(resource_id)`.

The planted production edge is `i-prd-000` `uses_database` `db-prd-014`. `i-prd-005` has incident `inc-prd-idle`. A second run updates those same rows.

```bash
make ingest-knowledge
```

That runs `python -m worker.main ingest-knowledge`. The log line includes `resources_absent`.

## Re-ingestion

A second full sync updates existing rows. It does not insert another copy.

| Entity | Upsert key |
| --- | --- |
| resources | `resource_id` |
| metric_rollups | `resource_id`, `name`, `day` |
| cost_records | `resource_id`, `period_start` |
| dependencies | `source_resource_id`, `target_resource_id`, `relationship` |
| incidents | `incident_id` |

Inventory and knowledge syncs compare the full simulator resource list with the table. A resource that is no longer in that list stays in the database with `present` set to false. Its rollups, cost records, dependency edges, and incidents stay too, so history is not deleted. A later sync that includes the resource sets `present` back to true. These jobs are full snapshots, not a change stream.

## Detectors

`make detect` runs every registered detector over present resources and upserts the findings. The log line is `detect detectors=N created=C updated=U findings=F`. A finding is stored by `finding_id`. A second run updates that id.

The built-in `noop` detector returns no findings. The built-in `sample` detector returns one finding for each present resource tagged `scenario=sample`. The finding includes that resource id and an evidence list.

`idle_compute` looks at the 30 days ending the day after the latest `cpu_percent` rollup. A present compute resource is idle when that window is complete and all of these stay under the cap: CPU average 15, CPU peak 25, request average 20, request peak 30. Evidence lists those four numbers and the resource tags. `i-dev-062` matches. `i-prd-017` does not: its CPU average is low, and its peak is 100. A flat low VM such as `i-prd-013` also matches; rightsizing it is a later detector.

Add a detector by creating a class with `name` and `detect(self, resources, session) -> list[Finding]`, then register an instance in `worker/worker/detectors/__init__.py`:

```python
default_registry().register(MyDetector())
```

`Finding` requires `finding_id`, at least one `resource_ids` entry, `category`, `summary`, and `evidence`. Use a stable id such as `{detector}-{resource_id}` so the next batch updates the same row. Detectors only return findings. The batch runner writes them.
