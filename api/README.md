# CloudSentry API

## Run locally

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./api
cloudsentry-api
```

Then, in a second terminal:

```bash
curl -s localhost:8000/health
```

Expected response: `{"status":"ok"}`.

Stop the server with Ctrl+C. `DATABASE_URL` is optional for this skeleton. The default in `app/config.py` is a placeholder and is not used by `/health`.

## OpenAPI

With the API running, open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). The schema is at [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json).

`/docs` lists `GET /health` under **system**. **Inventory** includes resource list and get, dependency lookup, and `GET /spend/accounts` plus `GET /spend/environments`. The **proposals** group is tagged so those routes show up on the same page as they land.

```bash
curl -s 'localhost:8000/resources?account_id=111111111111&environment=development&resource_type=compute'
curl -s 'localhost:8000/resources/i-dev-062?year=2026&month=3'
```

Filters are `account_id`, `environment`, and `resource_type`. Each resource includes `monthly_cost_cents`, `cpu_avg`, and `cpu_peak` for one calendar month. Leave `year` and `month` off to use the latest month that has cost records. `cpu_avg` is the mean of that month's daily averages and `cpu_peak` is the highest daily peak, both for `cpu_percent`, rounded to two decimals. A disk or snapshot has null utilization. Set `year` and `month` together. An unknown id returns 404.

Dependency lookup returns typed edges: `source_resource_id`, `target_resource_id`, and `relationship`. Dependencies are edges leaving the resource. Dependents are edges pointing at it. A known resource with no edges returns an empty list.

```bash
curl -s localhost:8000/resources/i-prd-000/dependencies
curl -s localhost:8000/resources/db-prd-014/dependents
```

`i-prd-000` depends on `bucket-prd-021` (`reads_bucket`) and `db-prd-014` (`uses_database`). `db-prd-014` depends on `vol-prd-003` (`stores_on`).

Spend aggregates sum daily cost rows for one calendar month. Each line is converted to cents, then summed. `total_cents` is the sum of the slices. An account or environment with no cost rows in that month is omitted. Leave `year` and `month` off to use the latest month that has cost records.

```bash
curl -s 'localhost:8000/spend/accounts?year=2026&month=3'
curl -s 'localhost:8000/spend/environments?year=2026&month=3'
```

On a fresh March 2026 ingest those totals are development `111111111111` 428264 cents, staging `222222222222` 338760 cents, and production `333333333333` 411369 cents. Each account is one environment, so the environment totals match.

## Core schemas

`app/schemas.py` defines the inventory records: `Resource`, `Metric`, `CostRecord`, `Dependency`, `Incident`, and `Policy`. A resource carries `owner`, `team`, `environment`, `business_criticality`, and `tags`. Invalid values are rejected by Pydantic.

`app/proposals.py` defines `Finding`, `RiskAssessment`, and `OptimizationProposal`. A proposal includes cost, savings, confidence, evidence, actions, a rollback plan, and approval, execution, and verification statuses. `model_dump_json()` produces an API response.

`app/execution.py` defines `ExecutionRun`, `VerificationResult`, and `RealizedSavings`. Each record carries `proposal_id`. A run stores the actor, plan snapshot, timestamps, and rollback metadata. A verification result records predicted savings, realized savings, operational impact, and a status of `success`, `partial`, `rollback`, or `inconclusive`.

## Migrations

From the repository root, after Postgres is running:

```bash
pip install -e ./api
make migrate
```

`make migrate` upgrades to the latest revision. `make migrate-down` drops the core tables. Confirm the tables with:

```bash
docker compose exec postgres psql -U cloudsentry -d cloudsentry -c '\dt'
```
