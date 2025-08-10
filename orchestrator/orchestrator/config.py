from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg2://postgres:postgres@db:5432/orchestrator"
    )
    api_title: str = "Codex Orchestrator API"
    api_version: str = "0.1.0"
    require_approval: bool = True
    cors_origins: str = "*"
    rate_limit_per_min: int = 1000
    secret_key: str | None = None
    scheduler_background_interval: float = 0.0  # seconds; 0 disables
    max_retries: int = 2
    backoff_base_seconds: int = 30

    class Config:
        env_prefix = "ORCH_"
        env_file = ".env"


settings = Settings()
