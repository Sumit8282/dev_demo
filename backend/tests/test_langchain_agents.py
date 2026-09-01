"""Verify release workflow components are LangChain agents, not plain Python coordinators."""

from datetime import datetime, timezone

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.agents.jira_agent import JiraAgent
from app.agents.l3_agent import L3Agent, _L3AgentRun
from app.agents.merge_agent import MergeAgent, _MergeAgentRun
from app.agents.orchestrator import Orchestrator
from app.agents.orchestrator_agent import ReleaseOrchestratorAgent
from app.agents.qa_agent import QAAgent
from app.agents.rm_agent import RMAgent, _RMAgentRun
from app.agents.workflow_context import WorkflowRunContext
from app.config import Settings
from app.models.build_result import BuildResult, BuildStatus


def _llm_settings():
    return Settings(
        USE_LLM_AGENTS=True,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4.1",
        LLM_API_KEY="test-key",
        LLM_BASE_URL="https://example.com/v1",
    )


def _fake_llm():
    return FakeListChatModel(responses=["ok"])


def test_jira_and_qa_are_langchain_agents():
    settings = _llm_settings()
    jira = JiraAgent(settings=settings).build_langchain_agent(llm=_fake_llm())
    qa = QAAgent(settings=settings).build_langchain_agent(llm=_fake_llm())
    assert jira is not None
    assert qa is not None
    assert hasattr(jira, "ainvoke")
    assert hasattr(qa, "ainvoke")


def test_orchestrator_l3_merge_rm_are_langchain_agents():
    settings = _llm_settings()
    ctx = WorkflowRunContext(state={"release_id": "REL-1", "jira_issue_key": "ABC-1"})
    orchestrator = ReleaseOrchestratorAgent(orchestrator=Orchestrator(), settings=settings)
    l3 = L3Agent(settings=settings)
    merge = MergeAgent(settings=settings)
    rm = RMAgent(settings=settings)

    orchestrator_agent = orchestrator.build_langchain_agent(ctx, llm=_fake_llm())
    l3_agent = l3.build_langchain_agent(_L3AgentRun(), llm=_fake_llm())
    merge_agent = merge.build_langchain_agent(_MergeAgentRun(state={}), llm=_fake_llm())
    rm_agent = rm.build_langchain_agent(
        _RMAgentRun(
            state={"release_id": "REL-1", "jira_issue_key": "ABC-1", "environment": "UAT"},
            build_result=BuildResult(
                build_id="BUILD-1",
                status=BuildStatus.COMPLETED,
                generated_at=datetime.now(timezone.utc),
                release_version="v1",
                target_environment="UAT",
            ),
        ),
        llm=_fake_llm(),
    )

    for compiled in (orchestrator_agent, l3_agent, merge_agent, rm_agent):
        assert compiled is not None
        assert hasattr(compiled, "ainvoke")


def test_create_langchain_agent_requires_a_model():
    from unittest.mock import patch

    from app.agents.llm_runner import create_langchain_agent

    with patch("app.agents.llm_runner.resolve_chat_model", return_value=None):
        assert create_langchain_agent(
            tools=[],
            system_prompt="test",
            name="test_agent",
        ) is None
