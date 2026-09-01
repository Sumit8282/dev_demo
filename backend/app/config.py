"""Application configuration loaded from environment variables."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to backend/ so uvicorn finds it regardless of CWD.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    llm_provider: str = Field(default="", alias="LLM_PROVIDER")
    llm_model: str = Field(default="", alias="LLM_MODEL")
    llm_api_key: SecretStr = Field(default=SecretStr(""), alias="LLM_API_KEY")
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")
    use_llm_agents: bool = Field(default=True, alias="USE_LLM_AGENTS")

    jira_mcp_url: str = Field(
        default="https://mcp.atlassian.com/v1/mcp",
        alias="JIRA_MCP_URL",
    )
    jira_email: str = Field(default="", alias="JIRA_EMAIL")
    jira_api_token: SecretStr = Field(default=SecretStr(""), alias="JIRA_API_TOKEN")
    jira_allowed_release_statuses: str = Field(
        default="In Progress",
        alias="JIRA_ALLOWED_RELEASE_STATUSES",
    )
    jira_l3_approved_status: str = Field(
        default="Released",
        alias="JIRA_L3_APPROVED_STATUS",
    )
    jira_deployment_completed_status: str = Field(
        default="Resolved",
        alias="JIRA_DEPLOYMENT_COMPLETED_STATUS",
    )
    jira_cloud_id: str = Field(default="", alias="JIRA_CLOUD_ID")

    github_personal_access_token: SecretStr = Field(
        default=SecretStr(""),
        alias="GITHUB_PERSONAL_ACCESS_TOKEN",
    )
    github_mcp_transport: Literal["http", "stdio"] = Field(
        default="http",
        alias="GITHUB_MCP_TRANSPORT",
    )
    github_mcp_url: str = Field(
        default="https://api.githubcopilot.com/mcp/",
        alias="GITHUB_MCP_URL",
    )
    github_mcp_docker_image: str = Field(
        default="ghcr.io/github/github-mcp-server",
        alias="GITHUB_MCP_DOCKER_IMAGE",
    )
    github_mcp_toolsets: str = Field(
        default="pull_requests,issues",
        alias="GITHUB_MCP_TOOLSETS",
    )

    ci_provider: Literal["stub", "github_actions"] = Field(
        default="stub",
        alias="CI_PROVIDER",
    )
    ci_trigger_mode: Literal["observe", "dispatch"] = Field(
        default="observe",
        alias="CI_TRIGGER_MODE",
    )
    github_actions_workflow: str = Field(
        default="release-build.yml",
        alias="GITHUB_ACTIONS_WORKFLOW",
    )
    github_actions_poll_interval_seconds: int = Field(
        default=10,
        alias="GITHUB_ACTIONS_POLL_INTERVAL_SECONDS",
    )
    github_actions_poll_timeout_seconds: int = Field(
        default=1800,
        alias="GITHUB_ACTIONS_POLL_TIMEOUT_SECONDS",
    )
    github_actions_discover_timeout_seconds: int = Field(
        default=120,
        alias="GITHUB_ACTIONS_DISCOVER_TIMEOUT_SECONDS",
    )
    ci_fallback_to_stub: bool = Field(
        default=False,
        alias="CI_FALLBACK_TO_STUB",
    )

    qa_dev_signoff_status: str = Field(default="", alias="QA_DEV_SIGNOFF_STATUS")

    release_database_path: str = Field(
        default="",
        alias="RELEASE_DATABASE_PATH",
    )

    portal_base_url: str = Field(
        default="http://localhost:5173",
        alias="PORTAL_BASE_URL",
    )
    l3_manager_email: str = Field(default="", alias="L3_MANAGER_EMAIL")
    rm_manager_email: str = Field(default="", alias="RM_MANAGER_EMAIL")

    mail_enabled: bool = Field(default=False, alias="MAIL_ENABLED")
    mail_from: str = Field(default="", alias="MAIL_FROM")
    gmail_user: str = Field(default="", alias="GMAIL_USER")
    gmail_app_password: SecretStr = Field(default=SecretStr(""), alias="GMAIL_APP_PASSWORD")
    gmail_smtp_host: str = Field(default="smtp.gmail.com", alias="GMAIL_SMTP_HOST")
    gmail_smtp_port: int = Field(default=587, alias="GMAIL_SMTP_PORT")

    @property
    def gmail_app_password_normalized(self) -> str:
        """Google app passwords are often copied with spaces; strip all whitespace."""
        return "".join(self.gmail_app_password.get_secret_value().split())

    @property
    def mail_from_address(self) -> str:
        return (self.mail_from or self.gmail_user).strip()

    @property
    def mail_configured(self) -> bool:
        return (
            self.mail_enabled
            and bool(self.gmail_user.strip())
            and bool(self.gmail_app_password_normalized)
            and bool(self.mail_from_address)
        )

    @property
    def l3_manager_emails(self) -> list[str]:
        return [
            email.strip()
            for email in self.l3_manager_email.split(",")
            if email.strip()
        ]

    @property
    def rm_manager_emails(self) -> list[str]:
        return [
            email.strip()
            for email in self.rm_manager_email.split(",")
            if email.strip()
        ]

    @property
    def allowed_jira_statuses(self) -> list[str]:
        return [
            status.strip()
            for status in self.jira_allowed_release_statuses.split(",")
            if status.strip()
        ]

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def release_db_path(self) -> Path:
        configured = self.release_database_path.strip()
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = _BACKEND_ROOT / path
            return path
        return _BACKEND_ROOT / "db" / "releases.db"

    @property
    def llm_enabled(self) -> bool:
        return (
            self.use_llm_agents
            and bool(self.llm_provider.strip())
            and bool(self.llm_model.strip())
            and bool(self.llm_api_key.get_secret_value().strip())
        )


def get_settings() -> Settings:
    """Load application settings from environment / `.env`."""
    return Settings()
