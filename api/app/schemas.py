"""Core inventory schemas.

These are the shared records for resources, telemetry, cost, dependencies,
incidents, and automation policy. Optimization proposals live in app.proposals.
Database tables for these models are created by `make migrate`.
The SQLAlchemy mappings live in `app.tables`.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Environment(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


class BusinessCriticality(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class PolicyEffect(StrEnum):
    allow = "allow"
    require_approval = "require_approval"
    prohibit = "prohibit"


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    environment: Environment
    owner: str = Field(min_length=1)
    team: str = Field(min_length=1)
    business_criticality: BusinessCriticality
    tags: dict[str, str] = Field(default_factory=dict)
    present: bool = True
    sku: str | None = None
    storage_class: str | None = None


class ResourceSummary(Resource):
    monthly_cost_cents: int = Field(ge=0)
    cpu_avg: float | None = None
    cpu_peak: float | None = None
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)


class ResourceList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ResourceSummary]
    total: int = Field(ge=0)


class AccountSpend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1)
    monthly_cost_cents: int = Field(ge=0)


class EnvironmentSpend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Environment
    monthly_cost_cents: int = Field(ge=0)


class AccountSpendReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    items: list[AccountSpend]
    total_cents: int = Field(ge=0)


class EnvironmentSpendReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    items: list[EnvironmentSpend]
    total_cents: int = Field(ge=0)


class MetricRollup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    day: date
    avg_value: float
    peak_value: float
    unit: str = Field(min_length=1)


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    timestamp: datetime
    value: float
    unit: str = Field(min_length=1)


class CostRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    period_start: datetime
    period_end: datetime
    amount: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @model_validator(mode="after")
    def period_end_is_after_start(self) -> "CostRecord":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class Dependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_resource_id: str = Field(min_length=1)
    target_resource_id: str = Field(min_length=1)
    relationship: str = Field(min_length=1)

    @model_validator(mode="after")
    def endpoints_differ(self) -> "Dependency":
        if self.source_resource_id == self.target_resource_id:
            raise ValueError("source_resource_id and target_resource_id must differ")
        return self


class DependencyList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    items: list[Dependency]
    total: int = Field(ge=0)


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    severity: BusinessCriticality
    started_at: datetime
    summary: str = Field(min_length=1)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    effect: PolicyEffect
    actions: list[str] = Field(min_length=1)
