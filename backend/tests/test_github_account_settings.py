"""GITHUB_ACCOUNT selects which personal access token GitHub clients use."""

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def test_default_account_keeps_primary_token() -> None:
    settings = Settings(
        GITHUB_ACCOUNT="default",
        GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("ghp_default"),
        GITHUB_PERSONAL_ACCESS_TOKEN_CLIENT=SecretStr("ghp_client"),
    )
    assert settings.github_personal_access_token.get_secret_value() == "ghp_default"


def test_client_account_uses_client_token() -> None:
    settings = Settings(
        GITHUB_ACCOUNT="client",
        GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("ghp_default"),
        GITHUB_PERSONAL_ACCESS_TOKEN_CLIENT=SecretStr("ghp_client"),
    )
    assert settings.github_personal_access_token.get_secret_value() == "ghp_client"


def test_client_account_requires_client_token() -> None:
    with pytest.raises(ValidationError, match="GITHUB_PERSONAL_ACCESS_TOKEN_CLIENT"):
        Settings(
            GITHUB_ACCOUNT="client",
            GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("ghp_default"),
            GITHUB_PERSONAL_ACCESS_TOKEN_CLIENT=SecretStr("  "),
        )
