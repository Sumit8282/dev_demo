"""LangChain tools that invoke Jira and QA sub-agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool

if TYPE_CHECKING:
    from app.agents.jira_agent import JiraAgent
    from app.agents.qa_agent import QAAgent


def build_jira_agent_tool(jira_agent: JiraAgent):
    """Create a LangChain tool that runs Jira release validation."""

    @tool
    async def jira_agent_tool(issue_key: str, expected_release_version: str) -> dict:
        """Validate a Jira ticket for release readiness."""
        result = await jira_agent.validate(
            issue_key=issue_key,
            expected_release_version=expected_release_version,
        )
        return result.model_dump()

    return jira_agent_tool


def build_qa_agent_tool(qa_agent: QAAgent):
    """Create a LangChain tool that runs QA sign-off validation."""

    @tool
    async def qa_agent_tool(
        release_id: str,
        qa_signoff_required: bool,
        environment: str,
        release_version: str,
        qa_signoff_not_required_reason: str | None = None,
        pr_title: str | None = None,
        qa_signoff_attachment: dict | None = None,
    ) -> dict:
        """Validate QA sign-off requirements for a release."""
        result = await qa_agent.validate_async(
            release_id=release_id,
            qa_signoff_required=qa_signoff_required,
            environment=environment,
            release_version=release_version,
            qa_signoff_not_required_reason=qa_signoff_not_required_reason,
            pr_title=pr_title,
            qa_signoff_attachment=qa_signoff_attachment,
        )
        return result.model_dump()

    return qa_agent_tool
