"""Environment-driven settings. No secrets are hardcoded; AWS credentials come from the default boto3 chain (IAM roles).

`NEERAI_ENV=aws` turns on strict startup validation (see `validate_runtime`): production never silently falls back to
demo mode, anonymous access, local storage or an unspecified weather provider.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised at startup when mandatory production configuration is missing or unsafe."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEERAI_", extra="ignore")

    env: Literal["local", "aws"] = "local"
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    # "demo" = deterministic scripted model provider (no AWS needed); "bedrock" = Amazon Bedrock via Strands.
    agent_mode: Literal["demo", "bedrock"] = "demo"
    bedrock_model_id: str = "apac.amazon.nova-pro-v1:0"
    bedrock_region: str = "ap-south-1"
    bedrock_temperature: float = 0.2
    # botocore "standard" retry mode = exponential backoff with jitter; kept small to avoid retry storms.
    bedrock_max_attempts: int = Field(default=3, ge=1, le=5)

    # "mock" = deterministic simulated weather; "openmeteo" = live; "auto" = live with labelled simulated fallback.
    weather_provider: Literal["mock", "openmeteo", "auto"] = "mock"
    weather_scenario: str = "uncertain_rain"
    weather_timeout_s: float = 6.0

    database_url: str = "sqlite:///./neerai.db"
    repository: Literal["sql", "dynamodb"] = "sql"
    dynamodb_table: str = "neerai-documents"
    aws_region: str = "ap-south-1"
    reports_bucket: str = ""

    # Authentication: "none" = single anonymous local user; "cognito" = verify Cognito JWTs and scope all data per user.
    auth_mode: Literal["none", "cognito"] = "none"
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""

    # Async agent jobs: "inline" = background thread in the API process (local/dev); "sqs" = queue + worker service.
    queue_backend: Literal["inline", "sqs"] = "inline"
    jobs_queue_url: str = ""
    job_ttl_days: int = Field(default=7, ge=1, le=30)
    job_timeout_s: float = Field(default=100.0, ge=10)
    job_max_attempts: int = Field(default=3, ge=1, le=5)
    max_active_jobs_per_user: int = Field(default=2, ge=1)
    max_jobs_per_user_per_day: int = Field(default=40, ge=1)

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_body_bytes: int = 65536
    rate_limit_per_minute: int = 120  # in-process, local only; disabled when env == "aws" (WAF + per-user job quotas instead)
    agent_timeout_s: float = 60.0
    agent_max_tool_calls: int = 24
    agent_max_retries: int = 1
    auto_seed: bool = True
    # Legacy Lambda path only: when set, every request must carry header x-origin-verify. The ECS path enforces this at the ALB.
    origin_verify_secret: str = ""
    planning_horizon_days: int = Field(default=3, ge=1, le=7)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    def validate_runtime(self, role: Literal["api", "worker"] = "api") -> None:
        """Fail fast on missing/unsafe production configuration. A no-op for local development."""
        if self.env != "aws":
            return
        problems: list[str] = []
        if self.agent_mode != "bedrock":
            problems.append("NEERAI_AGENT_MODE must be 'bedrock' in aws env (demo mode is local only)")
        if self.repository != "dynamodb" or not self.dynamodb_table:
            problems.append("NEERAI_REPOSITORY must be 'dynamodb' with NEERAI_DYNAMODB_TABLE set")
        if self.queue_backend != "sqs" or not self.jobs_queue_url:
            problems.append("NEERAI_QUEUE_BACKEND must be 'sqs' with NEERAI_JOBS_QUEUE_URL set")
        if "weather_provider" not in self.model_fields_set:
            problems.append("NEERAI_WEATHER_PROVIDER must be set explicitly (openmeteo = strict live; auto = labelled fallback; mock = simulated)")
        if self.auto_seed:
            problems.append("NEERAI_AUTO_SEED must be false in aws env (demo farms are loaded per user on request)")
        if role == "api":
            if self.auth_mode != "cognito":
                problems.append("NEERAI_AUTH_MODE must be 'cognito' in aws env")
            if not (self.cognito_region and self.cognito_user_pool_id and self.cognito_client_id):
                problems.append("NEERAI_COGNITO_REGION, _USER_POOL_ID and _CLIENT_ID are required")
            if not self.cors_list or any("localhost" in o or "127.0.0.1" in o or o == "*" for o in self.cors_list):
                problems.append("NEERAI_CORS_ORIGINS must list only the deployed frontend origin(s)")
        if problems:
            raise ConfigError("invalid production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
