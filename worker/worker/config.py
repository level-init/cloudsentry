from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://cloudsentry:cloudsentry@localhost:5432/cloudsentry"
    simulator_base_url: str = "http://127.0.0.1:8001"
    rightsizing_headroom: float = Field(default=0.5, ge=0, lt=1)
    rightsizing_avg_max: float = Field(default=15, gt=0, le=100)
    storage_age_days: int = Field(default=30, ge=0)
    lifecycle_cost_cents: int = Field(default=5000, ge=0)
    lifecycle_retention_days: int = Field(default=90, ge=0)


def get_settings() -> Settings:
    return Settings()
