import pytest
from pydantic import ValidationError

from core.config import Settings


def test_defaults_are_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_env == "test"
    assert settings.auth_mode == "local"


def test_pilot_rejects_anthropic_provider() -> None:
    with pytest.raises(ValidationError, match="not allowed when APP_ENV=pilot"):
        Settings(_env_file=None, app_env="pilot", ai_provider="anthropic")


def test_pilot_accepts_local_provider() -> None:
    settings = Settings(_env_file=None, app_env="pilot", ai_provider="ollama")
    assert settings.ai_provider == "ollama"


def test_secrets_are_not_shown_in_repr() -> None:
    settings = Settings(_env_file=None, mysql_app_password="s3cret-value")
    assert "s3cret-value" not in repr(settings)
