from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://cloudsentry:cloudsentry@localhost:5432/cloudsentry"


def get_settings() -> Settings:
    return Settings()
