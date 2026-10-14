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
- `sku` and `storage_class` are stored. `name`, `power_state`, and `schedule` are not columns and are not stored.
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

`make detect` runs every registered detector over present resources and upserts the findings. That is the manual trigger. `make detect-schedule` is the scheduled path: one invocation is one cron tick. Run it every `DETECTION_INTERVAL_SECONDS` (default 3600). A queue is not required. Each path logs `detect started` and `detect finished` with the trigger, the run id, and the detector, created, updated, and finding counts. Both insert one `detection_runs` row. A finding is stored by `finding_id`. A later tick updates that id instead of inserting another row.

The built-in `noop` detector returns no findings. The built-in `sample` detector returns one finding for each present resource tagged `scenario=sample`. The finding includes that resource id and an evidence list.

`idle_compute` looks at the 30 days ending the day after the latest `cpu_percent` rollup. A present compute resource is idle when that window is complete and all of these stay under the cap: CPU average 15, CPU peak 25, request average 20, request peak 30. Evidence lists those four numbers and the resource tags. `i-dev-062` matches. `i-prd-017` does not: its CPU average is low, and its peak is 100. A flat low VM such as `i-prd-013` also matches; rightsizing it is a separate detector.

`compute_rightsizing` uses that same 30-day window. The compute ladder is `t3.medium`, `m5.large`, `m5.xlarge`, and each step has twice the capacity of the step below. The detector recommends only the next smaller SKU, and only when the average is under `RIGHTSIZING_AVG_MAX` (default 15) and the projected peak on that next size stays under `(1 - RIGHTSIZING_HEADROOM) * 100`. Headroom defaults to 0.5, so the projected peak must stay under 50. `i-prd-013` is an `m5.xlarge` with a peak near 12, so the recommendation is `m5.large`. `i-prd-017` peaks at 100. That projects to 200 on `m5.large` and 400 on `t3.medium`, so it is not offered the two-step drop. Run inventory ingestion again after upgrading so `sku` is stored.

`development_scheduling` uses the environment tag. Development and staging compute qualify when the same 30-day window stays busy on Saturday and Sunday: weekend and weekday CPU averages both at or above 20, with at least 8 weekend days and 20 weekdays. The finding recommends `weekdays-09-17`, which is 09:00-17:00 UTC Monday through Friday. `i-dev-026` matches. Production does not, and a dev VM that is already quiet on weekends does not.

`unattached_storage` flags a present disk with nothing depending on it, and a non-production snapshot with nothing depending on it, once the cost history is at least `STORAGE_AGE_DAYS` old. The default is 30 days. Age is the number of days from the first cost row to the last. Evidence includes `attach_state`, `age_days`, and `monthly_cost_cents` for the latest month. `vol-dev-042` is the planted unattached disk. Production snapshots are left alone.

`storage_lifecycle` proposes a rule for two planted fixtures. Standard object storage whose latest month costs at least `LIFECYCLE_COST_CENTS` (default 5000) gets `transition-to-infrequent-access`. `bucket-prd-022` is `s3-standard-5tb` and matches. A 500 GB standard bucket does not, and a bucket already on `infrequent_access` does not. A non-production snapshot at that cost, with nothing depending on it, and at least `LIFECYCLE_RETENTION_DAYS` old (default 90) gets `expire-after-90-days`. `snap-dev-007` matches. Evidence includes the current tier, an access proxy, and the monthly cost. For a bucket the proxy is the 30-day request average. For a snapshot it is `unused`. Production snapshots are left alone. Run inventory ingestion again after upgrading so `storage_class` is stored. A standard SKU such as `s3-standard-5tb` still counts as the standard tier when the class is empty.

## Proposals

`make propose` reads stored findings and writes one pending Optimization Proposal for each MVP category. Sample findings are ignored. The action and the rollback are templates:

| Category | Action | Rollback |
| --- | --- | --- |
| `idle_compute` | `stop {id}` | `start {id}` |
| `compute_rightsizing` | `resize {id} to {sku}` | `resize {id}` back to the current sku |
| `development_scheduling` | `schedule {id} weekdays-09-17` | `schedule {id} always_on` |
| `unattached_storage` | `delete {id}` | recreate the disk or snapshot |
| `storage_lifecycle` | transition to `infrequent_access`, or `expire {id}` | transition back to `standard`, or recreate the snapshot from its source disk |

Current cost is the latest month. `worker/worker/savings.py` is the only savings math. Stop and delete predict 0. A weekday schedule predicts `cents * 40 // 168`. Infrequent access predicts half. Resize uses the simulator monthly rate for the target sku. `predicted_monthly_savings` is current minus that prediction. The same cents always produce the same savings. Evidence from the finding is copied, and a `success_metric` line is added. Dependencies are `relationship target` strings. Preconditions restate the detector gate. Confidence is 0.8. `worker/worker/risk.py` scores the resource from its environment, criticality, CPU peak, dependencies, dependents, and incidents. Production, a high peak, dependents, and incidents raise the score, so `i-prd-017` scores above `i-dev-062`. The rounded score maps to a class: under 0.20 is `SAFE_AUTOMATION`, under 0.45 is `APPROVAL_REQUIRED`, under 0.75 is `ENGINEERING_REVIEW_REQUIRED`, and 0.75 or more is `REJECTED`. `SAFE_AUTOMATION` still waits for a person to approve. v1 does not execute it. A `REJECTED` proposal cannot be approved or queued unless a policy with effect `allow` lists the action `approve_rejected`. That policy is absent by default. Seeded org rules in `api/app/default_policies.yaml` prohibit deleting a production database, so that proposal cannot be approved or queued. Scheduling development compute requires approval and stays approvable. Allowing a development stop is for later guarded automation and still waits for a person in v1. The strictest matching rule wins. A rightsizing veto is `REJECTED` even when the score is lower. `i-prd-017` is not resized. Its average would pass, and the peak of 100 projects to 200 on `m5.large` and 400 on `t3.medium`. `rightsizing_veto` records that refusal, and `make propose` stores a `REJECTED` proposal with action `reject resize of i-prd-017 to m5.large` and no savings. That proposal is not an approvable downsize. The JSON fields are the ones in the product overview.

A later run skips a pending proposal with the same resource ids and the same action. Rejecting that proposal lets a new id be created. The log line is `propose created=N skipped=S`.

## Precision on the seeded company

The five detectors are rules. They do not look up the `scenario` tag. The required hits are the ids in [simulator/DEMO_SCENARIOS.md](../simulator/DEMO_SCENARIOS.md). `worker/tests/test_seeded_waste.py` plants those ids and runs in CI with the rest of `make test`.

| Detector | Required hit |
| --- | --- |
| `idle_compute` | `i-dev-062` |
| `compute_rightsizing` | `i-prd-013`, recommended `m5.large`, not `t3.medium` |
| `development_scheduling` | `i-dev-026` |
| `unattached_storage` | `vol-dev-042` and `snap-dev-007` |
| `storage_lifecycle` | `bucket-prd-022` and `snap-dev-007` |

Two overlaps are expected. `i-prd-013` is flat and low, so it is idle and a rightsizing candidate. `snap-dev-007` is an unused development snapshot and a retention candidate.

`i-prd-017` is the spike-trap negative. Its CPU average is about 7, which is under the idle cap and under `RIGHTSIZING_AVG_MAX`, so the average alone would pass. The Wednesday peak near 100 vetoes both findings. Projecting that peak onto `m5.large` is 200, and onto `t3.medium` is 400, so it is not offered the two-step drop. It is production, so scheduling does not apply either.

`i-prd-005` is the soft case. It is not in the demo table. It is a production `m5.large` with a flat low CPU, and it has incident `inc-prd-idle`. Idle detection and one-step rightsizing to `t3.medium` both still match. The incident does not suppress a finding. Softening that proposal belongs to risk classification, which is later than detection.

The other 180 resources can match the same rules. Extra idle VMs, unattached disks, and always-on development or staging compute are true positives. A failure is a missing required id, or a finding on `i-prd-017`.

Add a detector by creating a class with `name` and `detect(self, resources, session) -> list[Finding]`, then register an instance in `worker/worker/detectors/__init__.py`:

```python
default_registry().register(MyDetector())
```

`Finding` requires `finding_id`, at least one `resource_ids` entry, `category`, `summary`, and `evidence`. Use a stable id such as `{detector}-{resource_id}` so the next batch updates the same row. Detectors only return findings. The batch runner writes them.
