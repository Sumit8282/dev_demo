"""Prompt loader tests."""

import pytest

from app.prompts import format_prompt, load_prompt


def test_load_orchestrator_prompt():
    prompt = load_prompt("orchestrator_system")
    assert "Release Orchestrator" in prompt
    user = load_prompt("orchestrator_user")
    assert "{release_id}" in user


def test_load_jira_agent_prompts():
    system = load_prompt("jira_agent_system")
    user = load_prompt("jira_agent_user")
    assert "Acceptance Criteria" in system
    assert "JIRA–PR Validation Summary" in system
    assert "{code_change_summary}" in user
    assert "{pr_title}" in user
    assert "{jira_ticket_snapshot}" in user


def test_load_qa_agent_prompts():
    system = load_prompt("qa_agent_system")
    user = load_prompt("qa_agent_user")
    assert "Acceptance Criteria" in system
    assert "{test_cases}" in user
    assert "{jira_issue_key}" in user
    assert "{acceptance_criteria}" in user
    assert "{signoff_facts}" in user
    assert "intent, not keyword" in system.lower() or "not keyword" in system.lower()


def test_load_qa_hybrid_extract_prompts():
    ac_system = load_prompt("qa_ac_extract_system")
    ac_user = load_prompt("qa_ac_extract_user")
    tc_system = load_prompt("qa_tc_extract_system")
    tc_user = load_prompt("qa_tc_extract_user")
    assert "Acceptance Criterion" in ac_system
    assert "{jira_description}" in ac_user
    assert "test case" in tc_system.lower()
    assert "{qa_document_text}" in tc_user


def test_load_qa_generated_test_prompts():
    system = load_prompt("qa_generated_test_system")
    user = load_prompt("qa_generated_test_user")
    assert "generated test" in system.lower()
    assert "assert_mentioned" in system
    assert "selenium" in system.lower()
    assert "{acceptance_criteria}" in user
    assert "{head_sha}" in user
    assert "{repo_files}" in user


def test_load_qa_lane2_draft_prompts():
    system = load_prompt("qa_lane2_draft_system")
    user = load_prompt("qa_lane2_draft_user")
    assert "draft" in system.lower()
    assert "{uncovered_criteria}" in user
    assert "{head_sha}" in user


def test_format_prompt_substitutes_placeholders():
    rendered = format_prompt(
        "jira_agent_user",
        issue_key="SCRUM-6",
        expected_release_version="v2.4.0",
        allowed_statuses="Resolved, Closed",
        jira_ticket_snapshot="- AC-01: Remove Offerings option",
        pr_title="SCRUM-6: Fix offerings",
        pr_description="Fix offerings dropdown click handler",
        pr_comments="- qa: Looks good",
        code_change_summary="Files changed: 2",
    )
    assert "SCRUM-6" in rendered
    assert "v2.4.0" in rendered
    assert "Resolved, Closed" in rendered
    assert "Fix offerings dropdown click handler" in rendered
    assert "Files changed: 2" in rendered


def test_load_prompt_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_prompt_file")
