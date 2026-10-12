# CloudSentry Simulator

AWS-like fake cloud. Accounts, environments, and resources live in an in-memory inventory (`simulator.model`). The HTTP service can read that world and apply a small set of actions that roll back. This package does not import the API or the worker, and it does not call AWS.

## Inventory model

An account has a 12-digit id and one environment: `development`, `staging`, or `production`. Those names match the API `Environment` values. A resource belongs to one account and uses that account's environment. Resource ids are stable: `resource_id(type, suffix)` always returns the same string for the same inputs.

| Simulator type | ID prefix | AWS-like concept | MVP use |
| --- | --- | --- | --- |
| `compute` | `i-` | EC2 instance | Idle compute, rightsizing, dev scheduling |
| `disk` | `vol-` | EBS volume | Unattached storage |
| `snapshot` | `snap-` | EBS snapshot | Unattached storage |
| `object_storage` | `bucket-` | S3 bucket | Storage lifecycle |
| `database` | `db-` | RDS instance | Inventory |
| `load_balancer` | `lb-` | Application or network load balancer | Inventory |
| `cluster` | `cluster-` | Small ECS-like cluster | Inventory |

Suffixes are lowercase letters, digits, and hyphens, so a seed can choose `i-idle-dev` and get that id on every run.

## Company seed

From the repository root, after `make install`:

```bash
make seed-simulator
```

That command rebuilds the in-memory company from RNG seed `30`. Running it again replaces the previous inventory with the same one.

| Account | ID | Environment | Resources |
| --- | --- | --- | --- |
| payments-dev | `111111111111` | development | 70 |
| payments-staging | `222222222222` | staging | 50 |
| payments-prod | `333333333333` | production | 60 |

**180 resources** total. Each account includes every resource type. Compute is the most common. Ids look like `i-dev-000` and `vol-prd-014`.

## Metrics

Hourly samples cover the 120 days ending 2026-04-01 UTC, which is where the simulator clock starts. Compute has CPU, memory, network, and request series. Databases, load balancers, clusters, and object storage have the series that apply to them. Disks and snapshots do not. Later days exist only after the clock moves past them.

Each compute resource follows one stable profile. `steady_low` and `steady_mid` stay near a flat level, with a slow 30-day seasonal swing. `business_hours` rises on weekdays from 09:00 to 17:00 UTC. `spike_trap` stays low except for a Wednesday 15:00 UTC spike, so the peak is several times the average.

From the repository root:

```bash
make simulator-metrics
```

That prints average and peak CPU for one spike-trap resource and one steady resource.

## Billing

Each resource has one monthly rate, chosen from a small AWS-like price list and kept stable for that resource id. Daily line items split the projected rate across the days of the month, so the daily cents add back to that projection exactly. Account spend for a month is the sum of its resources. Unset power, schedule, and storage fields bill the list price, which is what the seed does.

| Type | SKUs | Monthly rate |
| --- | --- | --- |
| compute | `t3.medium`, `m5.large`, `m5.xlarge` | $30.37, $70.08, $140.16 |
| disk | `gp3-100gb`, `gp3-500gb` | $8.00, $40.00 |
| snapshot | `snapshot-100gb`, `snapshot-1tb` | $5.00, $50.00 |
| object storage | `s3-standard-500gb`, `s3-standard-5tb` | $11.50, $115.00 |
| database | `db.t3.medium`, `db.m5.large` | $49.64, $124.83 |
| load balancer | `alb` | $22.27 |
| cluster | `cluster-2xm5-large`, `cluster-4xm5-large` | $140.16, $280.32 |

Compute, database, load balancer, and cluster rates assume 730 hours. Storage rates are GB-month prices. From the repository root:

```bash
make simulator-billing
```

That prints March 2026 spend for each account. The daily-line total matches the sum of the monthly rates.

## Regeneration

Costs and metrics are derived again on every read from the resource as it is now. Repeating a query without another action returns the same numbers.

| Current state | Cost projection | Metrics |
| --- | --- | --- |
| Compute `running` and `always_on` | Full monthly SKU rate | Seeded profile |
| Compute `stopped` | 0 | Every sample is 0 |
| Compute `weekdays-09-17` | `rate * 40 // 168` | 0 outside weekdays 09:00–17:00 UTC |
| Compute SKU change | New SKU rate, same hours rule | Unchanged |
| Object storage `infrequent_access` | Half the standard rate, integer division | Unchanged |
| Other resources | List price | Unchanged |

Rollback restores the previous field, and the next read uses that restored state. Historical seeded queries stay on the list price until an action changes the resource.

## Tags

Every seeded resource has `owner`, `team`, `environment`, and `criticality` tags. The environment tag matches the account environment. Development resources are `low`. Staging resources are `medium`. Production databases, load balancers, and clusters are `high`, as are some other production resources. `resources_by_tag` filters the inventory. The HTTP read API comes later.

```bash
make simulator-tags
```

That prints tags for the first 10 resources and the count of production resources marked `criticality=high`.

## Dependencies

Edges are directed: the source depends on the target. Within each account, compute uses a database and reads a bucket, databases store on a disk, load balancers route to compute, and snapshots point at a disk. `dependencies` and `dependents` list the edges for one resource.

The planted production chain is `i-prd-000` uses `db-prd-014`, which stores on `vol-prd-003`.

```bash
make simulator-deps
```

That prints the chain and each hop.

## Incidents

Seeded incidents have a severity and a start time, and they point at a resource id. `incidents_for` lists the incidents for one resource. `i-prd-005` is a production compute instance with a steady low CPU profile, and it has high-severity incident `inc-prd-idle` on 2026-03-20, twelve days before the metric history ends.

```bash
make simulator-incidents
```

That prints the incident on `i-prd-005`.

## Waste scenarios

Named fixtures for the five MVP detectors, plus a spike-trap that must not be rightsized, are listed in [DEMO_SCENARIOS.md](DEMO_SCENARIOS.md).

```bash
make simulator-scenarios
```

The API listens on port **8000**. This service listens on port **8001**.

## Run locally

From the repository root:

```bash
source .venv/bin/activate
pip install -e ./simulator
cloudsentry-simulator
```

Then, in a second terminal:

```bash
curl -s -D - http://127.0.0.1:8001/health
curl -s http://127.0.0.1:8001/resources?limit=200
curl -s http://127.0.0.1:8001/resources/i-prd-017/metrics?name=cpu_percent
curl -s http://127.0.0.1:8001/resources/i-prd-017/costs
curl -s http://127.0.0.1:8001/resources/i-prd-000/dependencies
curl -s http://127.0.0.1:8001/resources/i-prd-005/incidents
```

`/health` returns `{"status":"ok"}`. `/resources` returns the 180-resource company. Metrics default to the 24 hours ending at the clock. Costs default to the month of the last observed day, which is March 2026 until the clock moves. Interactive docs are at [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs). Filters: `environment`, `account_id`, `resource_type`, and `scenario`.

## Clock

The clock starts at 2026-04-01 00:00 UTC. A day or hour is visible only when it is earlier than `now`. `GET /clock` reads it. `PUT /clock` sets it to a UTC timestamp after the start of seeded history. `POST /clock/advance` moves it forward by whole days. Setting the same timestamp again leaves it unchanged. Advancing is deterministic: the same start plus the same number of days always lands on the same instant.

Advancing 7 days from the start makes 2026-04-01 through 2026-04-07 observable. The default metric window becomes the last 24 hours before the new clock, and April cost lines appear for those seven days. March stays a full month because it is already behind the clock. Days after the clock are omitted, not billed as zero.

```bash
curl -s http://127.0.0.1:8001/clock
curl -s -X POST http://127.0.0.1:8001/clock/advance \
  -H 'content-type: application/json' \
  -d '{"days":7}'
curl -s 'http://127.0.0.1:8001/resources/i-dev-062/metrics?name=cpu_percent&start=2026-04-01T00:00:00Z&end=2026-04-08T00:00:00Z'
curl -s 'http://127.0.0.1:8001/resources/i-dev-062/costs?year=2026&month=4'
```

## Actions

| Action | Path | Applies to |
| --- | --- | --- |
| Stop | `POST /resources/{id}/actions/stop` | Running compute |
| Start | `POST /resources/{id}/actions/start` | Stopped compute |
| Resize | `POST /resources/{id}/actions/resize` | Compute, body `{"sku":"m5.large"}` |
| Schedule | `POST /resources/{id}/actions/schedule` | Development compute, body `{"schedule":"weekdays-09-17"}` |
| Delete unattached | `POST /resources/{id}/actions/delete-unattached` | Disk with no dependents |
| Storage lifecycle | `POST /resources/{id}/actions/storage-lifecycle` | Object storage, body `{"storage_class":"infrequent_access"}` |
| Rollback | `POST /actions/{action_id}/rollback` | A previous action |

Illegal actions return 400 with a short detail. Unknown resources and unknown action ids return 404. Rollback writes the previous field back. A second rollback of the same action is rejected.

```bash
curl -s -X POST http://127.0.0.1:8001/resources/i-dev-026/actions/schedule \
  -H 'content-type: application/json' \
  -d '{"schedule":"weekdays-09-17"}'
```

Stop the server with Ctrl+C.
