"""Data-plane settings, read from environment variables and the environment's env file."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Host-run tools (pytest, alembic, uvicorn) default to the test environment.
# The pilot environment must always be selected explicitly (ADR-011).
_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_DEFAULT_ENV_FILE, extra="ignore")

    app_env: Literal["test", "pilot"] = "test"
    auth_mode: Literal["local"] = "local"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3307
    # One MySQL user per role (schema.md Section 2.1). Containers get only what they need:
    # the api/worker containers never receive the migrator or root passwords.
    mysql_app_user: str = "app_rw"
    mysql_app_password: SecretStr = SecretStr("")
    mysql_migrator_user: str = "migrator"
    mysql_migrator_password: SecretStr = SecretStr("")
    mysql_report_user: str = "report_ro"
    mysql_report_password: SecretStr = SecretStr("")
    mysql_ai_user: str = "ai_ro"
    mysql_ai_password: SecretStr = SecretStr("")

    redis_url: str = "redis://127.0.0.1:6380/0"
    qdrant_url: str = "http://127.0.0.1:6333"

    tally_url: str = "http://localhost:9000"
    # How long one Tally request may take before the sync checks Tally and splits the
    # request (ADR-022); a connection can override it with config.timeout_sec.
    tally_timeout_sec: float = 120.0
    # The quick "does Tally answer at all?" check after a timeout.
    tally_ping_timeout_sec: float = 15.0
    # How often the worker checks which connections are due for a sync (SYN-001); each
    # connection's own interval is ledgerbridge_system.connections.sync_interval_sec.
    sync_tick_sec: int = 60
    # Default interval of the deletion check, which lists every key in the source (SYN-003);
    # a connection can override it with config.deletion_check_interval_sec.
    deletion_check_interval_sec: int = 3600
    # Largest difference accepted between our balances and the source's (VAL-002); exact by
    # default. A connection can override it with config.validation_tolerance.
    validation_tolerance: Decimal = Decimal(0)

    ai_provider: Literal["anthropic", "ollama"] = "anthropic"
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = ""
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = ""

    token_signing_key: SecretStr = SecretStr("")
    credentials_enc_key: SecretStr = SecretStr("")

    frontend_origin: str = "http://localhost:5175"

    @model_validator(mode="after")
    def _client_data_stays_local(self) -> Self:
        # PIL-005: client data never goes to the Anthropic API.
        if self.app_env == "pilot" and self.ai_provider == "anthropic":
            raise ValueError("AI_PROVIDER=anthropic is not allowed when APP_ENV=pilot")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
