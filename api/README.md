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

`/docs` lists `GET /health` under **system**. **Inventory** includes resource list and get, dependency lookup, and `GET /spend/accounts` plus `GET /spend/environments`. **Proposals** lists and gets optimization proposals, approves or rejects a pending one, and lists the approval audit.

```bash
curl -s 'localhost:8000/proposals?status=pending&risk_class=SAFE_AUTOMATION&environment=development&team=payments&category=idle_compute&limit=20&offset=0'
curl -s localhost:8000/proposals/proposal-idle_compute-i-dev-062
```

`status` is the approval status. `environment` and `team` come from a linked resource. `category` is the proposal category. `limit` defaults to 50, with a maximum of 100. `offset` defaults to 0. `total` counts every match, not just the page. An unknown id returns 404. An unknown status or risk class returns 422.

A pending proposal can be approved, rejected, or cancelled. Any other approval change is refused, including approving a proposal that is already approved. Each change stores the actor, the time, and the reason. A `REJECTED` risk class still cannot be approved unless an allow policy lists `approve_rejected`.

`POST /proposals/{id}/approve` and `POST /proposals/{id}/reject` return the updated proposal. Until sign-in exists, send the actor in the `X-Actor` header. The API trusts that header. The body is the reason.

```bash
curl -s -X POST localhost:8000/proposals/proposal-idle_compute-i-dev-062/approve \
  -H 'Content-Type: application/json' \
  -H 'X-Actor: ada' \
  -d '{"reason":"the idle instance can stop"}'
curl -s -X POST localhost:8000/proposals/proposal-idle_compute-i-dev-062/reject \
  -H 'Content-Type: application/json' \
  -H 'X-Actor: ada' \
  -d '{"reason":"keep this instance running"}'
```

Approve sets `approval_status` to `approved`. Reject sets it to `rejected` and stores the reason. A missing proposal returns 404. A missing `X-Actor` header or a blank reason returns 422. An illegal change, including a second approve, returns 409.

`GET /proposals/{id}/audit` lists those rows, oldest first. Approve and reject each append one row. There is no update or delete route, and the table rejects both. A proposal with no decision returns an empty list.

```bash
curl -s localhost:8000/proposals/proposal-idle_compute-i-dev-062/audit
```

`POST /proposals/{id}/execute` queues an approved proposal. It does not change the simulator. A pending, rejected, or cancelled proposal returns 409, including a proposal labeled `SAFE_AUTOMATION`. An allow policy does not skip approval. A prohibit policy returns 409 even when the stored status is already approved. Queueing, running, or marking success through the status update is refused until the proposal is approved.

```bash
curl -s -X POST localhost:8000/proposals/proposal-idle_compute-i-dev-062/execute
```

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

`app/schemas.py` defines the inventory records: `Resource`, `Metric`, `CostRecord`, `Dependency`, `Incident`, and `Policy`. A resource carries `owner`, `team`, `environment`, `business_criticality`, and `tags`. Invalid values are rejected by Pydantic. A policy names an effect (`allow`, `require_approval`, or `prohibit`) and the actions it covers. `environment` and `resource_type` narrow the match. Leave either one empty to match every value.

`app/policy.py` loads `app/default_policies.yaml`. The strictest matching rule wins. When nothing matches, the decision is `require_approval`. `PolicyRepository.seed_defaults()` inserts any missing default. Migration `0009` does that on upgrade. Deleting a production database is prohibited, so that proposal cannot be approved or queued. Scheduling development compute requires approval and can still be approved. Allowing a development stop is reserved for later guarded automation. v1 does not execute it.

`app/proposals.py` defines `Finding`, `RiskAssessment`, and `OptimizationProposal`. A proposal includes cost, savings, confidence, evidence, and approval, execution, and verification statuses. The plan is always populated: `preconditions`, `execution_steps`, `rollback`, and `success_metrics`. Each list must contain at least one non-blank line. `execution_steps` is stored as `proposed_actions`, and `rollback` is stored as `rollback_plan`. `api/tests/fixtures/sample_proposal.json` is a complete example. `narrative` is optional text. The worker writes it and rejects a narrative whose savings or risk numbers differ from the structured fields. `model_dump_json()` produces an API response.

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
