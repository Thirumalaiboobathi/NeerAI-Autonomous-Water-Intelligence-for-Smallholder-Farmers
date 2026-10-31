"""Environment-driven settings. No secrets are hardcoded; AWS credentials come from the default boto3 chain."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEERAI_", extra="ignore")

    env: Literal["local", "aws"] = "local"
    # "demo" = deterministic scripted model provider (no AWS needed); "bedrock" = Amazon Bedrock via Strands.
    agent_mode: Literal["demo", "bedrock"] = "demo"
    bedrock_model_id: str = "apac.amazon.nova-pro-v1:0"
    bedrock_region: str = "ap-south-1"
    bedrock_temperature: float = 0.2

    # "mock" = deterministic simulated weather; "openmeteo" = live; "auto" = live with labelled simulated fallback.
    weather_provider: Literal["mock", "openmeteo", "auto"] = "mock"
    weather_scenario: str = "uncertain_rain"
    weather_timeout_s: float = 6.0

    database_url: str = "sqlite:///./neerai.db"
    repository: Literal["sql", "dynamodb"] = "sql"
    dynamodb_table: str = "neerai-documents"
    reports_bucket: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_minute: int = 120
    agent_timeout_s: float = 60.0
    agent_max_tool_calls: int = 24
    agent_max_retries: int = 1
    auto_seed: bool = True
    # When set, every request must carry header x-origin-verify with this value (CloudFront adds it); blocks direct origin access.
    origin_verify_secret: str = ""
    planning_horizon_days: int = Field(default=3, ge=1, le=7)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
