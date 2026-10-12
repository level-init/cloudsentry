# Simulator adapter boundary

The product loop talks to a cloud through one adapter. Today that adapter is the simulator on port 8001. Phase 8 replaces it with AWS. The proposal lifecycle stays the same.

The simulator package does not import the API or the worker, and it does not call AWS. The API should call the adapter, not simulator internals such as the seed, the hash profiles, or the in-memory world.

## Interface sketch

Two protocols. The simulator implements both over HTTP. The first AWS adapter implements reads only. Applies wait for Terraform, which is the preferred real execution path.

```python
from datetime import datetime
from typing import Protocol


class CloudReadAdapter(Protocol):
    def list_resources(self, **filters: str) -> list[object]: ...

    def get_resource(self, resource_id: str) -> object: ...

    def get_tags(self, resource_id: str) -> dict[str, str]: ...

    def get_metrics(
        self,
        resource_id: str,
        *,
        start: datetime,
        end: datetime,
        name: str | None = None,
    ) -> list[object]: ...

    def get_costs(self, resource_id: str, *, year: int, month: int) -> object: ...

    def get_dependencies(self, resource_id: str) -> list[object]: ...

    def get_dependents(self, resource_id: str) -> list[object]: ...

    def get_incidents(self, resource_id: str) -> list[object]: ...


class CloudApplyAdapter(Protocol):
    def stop(self, resource_id: str) -> object: ...

    def start(self, resource_id: str) -> object: ...

    def resize(self, resource_id: str, sku: str) -> object: ...

    def schedule(self, resource_id: str, schedule: str) -> object: ...

    def delete_unattached(self, resource_id: str) -> object: ...

    def storage_lifecycle(self, resource_id: str, storage_class: str) -> object: ...

    def rollback(self, action_id: str) -> object: ...
```

`object` here means the resource, sample, cost, edge, incident, or action record for that call. The HTTP shapes live in the simulator OpenAPI doc at `http://127.0.0.1:8001/docs`. This sketch is the swap point, not a second implementation.

## Endpoints and the AWS stand-in

| Simulator endpoint | Adapter method | Later AWS stand-in |
| --- | --- | --- |
| `GET /resources` | `list_resources` | Describe calls or AWS Config inventory |
| `GET /resources/{id}` | `get_resource` | Describe call for that type |
| `GET /resources/{id}/tags` | `get_tags` | Resource tags |
| `GET /resources/{id}/metrics` | `get_metrics` | CloudWatch |
| `GET /resources/{id}/costs` | `get_costs` | Cost Explorer or a CUR |
| `GET /resources/{id}/dependencies` | `get_dependencies` | No single AWS API. A thinner graph from the product. |
| `GET /resources/{id}/dependents` | `get_dependents` | Same as dependencies |
| `GET /resources/{id}/incidents` | `get_incidents` | Alarms or Health events |
| `POST /resources/{id}/actions/stop` | `stop` | Terraform change, not a direct mutate API |
| `POST /resources/{id}/actions/start` | `start` | Terraform change |
| `POST /resources/{id}/actions/resize` | `resize` | Terraform instance type change |
| `POST /resources/{id}/actions/schedule` | `schedule` | Scheduler or a tag, applied through Terraform |
| `POST /resources/{id}/actions/delete-unattached` | `delete_unattached` | Terraform destroy of an unused volume |
| `POST /resources/{id}/actions/storage-lifecycle` | `storage_lifecycle` | Terraform storage-class or lifecycle change |
| `POST /actions/{id}/rollback` | `rollback` | Revert the Terraform change |

`GET /health` is process liveness. It is not part of the cloud adapter.

`GET /clock`, `PUT /clock`, and `POST /clock/advance` exist so a demo can move the observation window without waiting. An AWS adapter uses real time ranges on CloudWatch and Cost Explorer. It does not expose a fake clock.

## Resource type mappings

| Simulator type | Id prefix | AWS resource | MVP use |
| --- | --- | --- | --- |
| `compute` | `i-` | EC2 instance | Idle compute, rightsizing, dev scheduling |
| `disk` | `vol-` | EBS volume | Unattached storage |
| `snapshot` | `snap-` | EBS snapshot | Unattached storage |
| `object_storage` | `bucket-` | S3 bucket | Storage lifecycle |
| `database` | `db-` | RDS instance | Inventory |
| `load_balancer` | `lb-` | Application load balancer | Inventory |
| `cluster` | `cluster-` | Small ECS-like cluster | Inventory |

Accounts use 12-digit ids and one environment each: `development`, `staging`, or `production`. Those names match the API `Environment` values.

| Simulator field | Values | AWS-like meaning |
| --- | --- | --- |
| Compute `sku` | `t3.medium`, `m5.large`, `m5.xlarge` | EC2 instance type |
| Compute `power_state` | `running`, `stopped` | EC2 instance state |
| Compute `schedule` | `always_on`, `weekdays-09-17` | On/off schedule. Not an EC2 attribute. |
| Disk `sku` | `gp3-100gb`, `gp3-500gb` | EBS gp3 volume size |
| Snapshot `sku` | `snapshot-100gb`, `snapshot-1tb` | Snapshot size |
| Object storage `sku` | `s3-standard-500gb`, `s3-standard-5tb` | S3 Standard, rough size |
| Object storage `storage_class` | `standard`, `infrequent_access` | S3 Standard or Standard-IA |
| Database `sku` | `db.t3.medium`, `db.m5.large` | RDS instance class |
| Load balancer `sku` | `alb` | Application load balancer |
| Cluster `sku` | `cluster-2xm5-large`, `cluster-4xm5-large` | Fiction for a small cluster |

## Intentionally fake

- Prices are a small stable list in cents, not the AWS price list and not a CUR. Stopped compute bills 0. A weekday schedule bills `rate * 40 // 168`. Infrequent access bills half the standard rate.
- Metrics are a deterministic function of the resource id, power state, schedule, and timestamp. They are not CloudWatch. Changing the SKU does not rewrite utilization.
- The company is 180 resources from RNG seed 30. Waste fixtures and the spike-trap are planted. They are not discoveries.
- Dependencies are inserted by the seed, including the chain `i-prd-000` → `db-prd-014` → `vol-prd-003`. AWS will not hand back that graph.
- Incidents are seeded records. `inc-prd-idle` on `i-prd-005` is a fixture.
- The clock starts at 2026-04-01 00:00 UTC. History before that is 120 days. Later days appear only after the clock advances.
- Rollback restores the previous simulator field. It does not call AWS and it does not revert a Terraform apply.
- There is no IAM, region, VPC, or organization model. One account has one environment.
- Apply actions mutate the in-memory world. They do not create a Terraform plan.

How to run the simulator, including the curl examples, is in [simulator/README.md](../simulator/README.md).
