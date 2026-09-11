"""QA Validation Agent — hybrid AC/test-case extract then coverage mapping."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm_runner import create_langchain_agent, invoke_structured_agent
from app.agents.tools.mcp_tools import build_jira_mcp_tools
from app.config import Settings, get_settings
from app.mcp.jira_mcp import JiraMCPClient
from app.models.qa_llm_validation import (
    QAAcceptanceCriteriaExtract,
    QAAcceptanceCriterion,
    QADraftTestBundle,
    QAGeneratedTest,
    QAGeneratedTestBundle,
    QALLMValidationOutput,
    QATestCase,
    QATestCaseExtract,
)
from app.models.qa_signoff import SignOffRequest
from app.models.validation import QAChecks, QAValidationResult, ValidationStatus
from app.prompts import format_prompt, load_prompt
from app.services.qa_coverage_evaluator import (
    apply_coverage_constraints,
    extract_test_cases_from_text,
    format_signoff_facts,
    merge_test_cases,
    normalize_test_result,
)
from app.services.generated_test_runner import GeneratedTestRunner
from app.services.generated_test_source import build_generated_test_code
from app.services.github_issue_acs import collect_github_issue_acceptance_criteria
from app.services.github_pr_client import GitHubPRClient
from app.services.github_repo_evidence import GitHubRepoEvidenceClient
from app.services.qa_pr_test_gate import (
    build_pr_test_document,
    changed_production_files,
    collect_pr_test_files,
    extract_github_metadata,
    extract_pr_testing_writeup,
    format_generated_test_repo_context,
    format_lane2_comment,
    uncovered_acceptance_criteria,
)
from app.services.qa_signoff_service import QASignoffService, get_qa_signoff_service

logger = logging.getLogger(__name__)


class QAAgent:
    def __init__(
        self,
        signoff_service: QASignoffService | None = None,
        settings: Settings | None = None,
        jira_client: JiraMCPClient | None = None,
        repo_evidence_client: GitHubRepoEvidenceClient | None = None,
        generated_test_runner: GeneratedTestRunner | None = None,
        github_pr_client: GitHubPRClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.signoff_service = signoff_service or get_qa_signoff_service()
        self._jira_client = jira_client
        self._repo_evidence_client = repo_evidence_client
        self._github_pr_client = github_pr_client
        self._generated_test_runner = generated_test_runner or GeneratedTestRunner(
            settings=self.settings
        )

    async def validate_async(
        self,
        *,
        release_id: str,
        qa_signoff_required: bool,
        environment: str,
        release_version: str,
        qa_signoff_not_required_reason: str | None = None,
        pr_title: str | None = None,
        qa_signoff_attachment: dict | None = None,
        jira_issue_key: str | None = None,
        jira_validation: Any | None = None,
        qa_mode: str | None = None,
        github_validation: Any | None = None,
    ) -> QAValidationResult:
        logger.info(
            "[QA_AGENT] Starting sign-off validation for release %s (required=%s)",
            release_id,
            qa_signoff_required,
        )

        resolved_mode = (qa_mode or ("not_required" if not qa_signoff_required else "upload")).strip().lower()

        if not qa_signoff_required or resolved_mode == "not_required":
            result = self.signoff_service.validate_not_required(
                qa_signoff_not_required_reason=qa_signoff_not_required_reason,
            )
            result.metadata.setdefault("environment", environment)
            result.metadata.setdefault("release_version", release_version)
            result.metadata.setdefault("qa_mode", "not_required")
            logger.info("[QA_AGENT] Sign-off validation result: %s", result.status.value)
            return result

        if resolved_mode == "pr_tests":
            return await self._validate_pr_tests(
                release_id=release_id,
                environment=environment,
                release_version=release_version,
                qa_signoff_required=qa_signoff_required,
                pr_title=pr_title,
                jira_issue_key=jira_issue_key,
                jira_validation=jira_validation,
                github_validation=github_validation,
            )

        if resolved_mode == "github_issues":
            return await self._validate_github_issues(
                release_id=release_id,
                environment=environment,
                release_version=release_version,
                qa_signoff_required=qa_signoff_required,
                pr_title=pr_title,
                jira_issue_key=jira_issue_key,
                github_validation=github_validation,
            )

        checks = QAChecks(signoff_required=True, signoff_completed=False)
        metadata: dict[str, Any] = {
            "environment": environment,
            "release_version": release_version,
            "expected_pr_title": pr_title or "",
            "jira_issue_key": jira_issue_key or "",
            "hybrid_pipeline": True,
            "qa_mode": "upload",
            "qa_lane": 1,
        }

        if not qa_signoff_attachment or not qa_signoff_attachment.get("filename"):
            return QAValidationResult(
                status=ValidationStatus.FAIL,
                checks=checks,
                errors=["QA sign-off attachment is required but was not provided."],
                metadata=metadata,
            )

        try:
            filename, qa_document_text = self.signoff_service.load_qa_document_text(
                release_id=release_id,
                attachment=qa_signoff_attachment,
            )
            metadata["attachment_filename"] = filename
            metadata["qa_document_text_length"] = len(qa_document_text)
        except ValueError as exc:
            return QAValidationResult(
                status=ValidationStatus.FAIL,
                checks=checks,
                errors=[str(exc)],
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("[QA_AGENT] Failed to read attachment for %s", release_id)
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=[f"Failed to process QA sign-off attachment: {exc}"],
                metadata=metadata,
            )

        if not self.settings.llm_enabled:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=[
                    "LLM is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, and LLM_BASE_URL."
                ],
                metadata=metadata,
            )

        mapper_agent = self.build_langchain_agent()
        tc_agent = self.build_tc_extract_agent()
        if mapper_agent is None or tc_agent is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["Failed to initialize QA LLM agent."],
                metadata=metadata,
            )

        jira_description, jira_comments, acceptance_criteria = _extract_jira_context(
            jira_validation
        )
        if not acceptance_criteria and jira_issue_key:
            fetched_description, fetched_comments, fetched_acs = (
                await self._prefetch_jira_acceptance_criteria(jira_issue_key)
            )
            acceptance_criteria = fetched_acs
            jira_description = jira_description or fetched_description
            jira_comments = jira_comments or fetched_comments

        logger.info(
            "[QA_AGENT] Code-extracted %d acceptance criteria from Jira %s",
            len(acceptance_criteria),
            jira_issue_key or "(none)",
        )

        signoff = _load_structured_signoff(
            self.signoff_service,
            release_id=release_id,
            attachment=qa_signoff_attachment,
        )
        if signoff is not None:
            metadata["signoff_test_plan_status"] = signoff.test_plan_status
            metadata["signoff_open_blocker_or_critical_bugs"] = (
                signoff.open_blocker_or_critical_bugs
            )

        ac_resolution, tc_extract = await asyncio.gather(
            self._resolve_acceptance_criteria(
                provided=acceptance_criteria,
                jira_issue_key=jira_issue_key,
                jira_description=jira_description,
                jira_comments=jira_comments,
            ),
            self._extract_test_cases(
                agent=tc_agent,
                attachment_filename=filename,
                qa_document_text=qa_document_text,
            ),
        )

        if ac_resolution is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["QA AC extract agent did not return structured acceptance criteria."],
                metadata=metadata,
            )
        if tc_extract is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["QA test-case extract agent did not return structured test cases."],
                metadata=metadata,
            )

        extracted_acs, ac_source = ac_resolution
        extracted_tests = merge_test_cases(
            extract_test_cases_from_text(qa_document_text),
            tc_extract.test_cases,
        )
        metadata["ac_source"] = ac_source
        metadata["extracted_test_case_count"] = len(extracted_tests)
        logger.info(
            "[QA_AGENT] Hybrid extract complete ac_source=%s acs=%d test_cases=%d",
            ac_source,
            len(extracted_acs),
            len(extracted_tests),
        )

        llm_result = await self._map_coverage(
            agent=mapper_agent,
            release_id=release_id,
            environment=environment,
            release_version=release_version,
            qa_signoff_required=qa_signoff_required,
            pr_title=pr_title,
            jira_issue_key=jira_issue_key,
            attachment_filename=filename,
            acceptance_criteria=extracted_acs,
            test_cases=extracted_tests,
            signoff=signoff,
        )
        if llm_result is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["QA LLM agent did not return a structured validation result."],
                metadata=metadata,
            )

        llm_result = apply_coverage_constraints(
            llm_result,
            acceptance_criteria=extracted_acs,
            test_cases=extracted_tests,
            signoff=signoff,
            )

        result = _to_qa_validation_result(
            llm_result,
            checks=checks,
            metadata=metadata,
            provided_acceptance_criteria=[item.text for item in extracted_acs],
        )
        github_meta = extract_github_metadata(github_validation)
        await self._attach_generated_tests(
            result,
            acceptance_criteria=extracted_acs,
            existing_tests=qa_document_text,
            jira_issue_key=jira_issue_key,
            head_sha=str(github_meta.get("head_sha") or ""),
            owner=str(github_meta.get("owner") or ""),
            repo=str(github_meta.get("repo") or ""),
        )
        return result

    async def _validate_pr_tests(
        self,
        *,
        release_id: str,
        environment: str,
        release_version: str,
        qa_signoff_required: bool,
        pr_title: str | None,
        jira_issue_key: str | None,
        jira_validation: Any | None,
        github_validation: Any | None,
    ) -> QAValidationResult:
        return await self._run_lane1_coverage(
            release_id=release_id,
            environment=environment,
            release_version=release_version,
            qa_signoff_required=qa_signoff_required,
            pr_title=pr_title,
            jira_issue_key=jira_issue_key,
            jira_validation=jira_validation,
            github_validation=github_validation,
            qa_mode="pr_tests",
        )

    async def _validate_github_issues(
        self,
        *,
        release_id: str,
        environment: str,
        release_version: str,
        qa_signoff_required: bool,
        pr_title: str | None,
        jira_issue_key: str | None,
        github_validation: Any | None,
    ) -> QAValidationResult:
        collected = await self._prefetch_github_issue_acceptance_criteria(github_validation)
        refs = list(collected.get("refs") or [])
        fetched = list(collected.get("fetched") or [])
        criteria = list(collected.get("criteria") or [])
        extra = {
            "ac_source": "github_issues",
            "github_issue_numbers": list(collected.get("github_issue_numbers") or []),
            "github_issues_fetched": fetched,
        }
        if not refs:
            return QAValidationResult(
                status=ValidationStatus.FAIL,
                checks=QAChecks(signoff_required=True, signoff_completed=False),
                errors=["No GitHub issues linked from the PR."],
                metadata={
                    "environment": environment,
                    "release_version": release_version,
                    "qa_mode": "github_issues",
                    "qa_lane": 1,
                    **extra,
                },
            )
        if not fetched:
            return QAValidationResult(
                status=ValidationStatus.FAIL,
                checks=QAChecks(signoff_required=True, signoff_completed=False),
                errors=[
                    "Linked GitHub issues could not be fetched or were pull requests."
                ],
                metadata={
                    "environment": environment,
                    "release_version": release_version,
                    "qa_mode": "github_issues",
                    "qa_lane": 1,
                    **extra,
                },
            )
        return await self._run_lane1_coverage(
            release_id=release_id,
            environment=environment,
            release_version=release_version,
            qa_signoff_required=qa_signoff_required,
            pr_title=pr_title,
            jira_issue_key=jira_issue_key,
            jira_validation=None,
            github_validation=github_validation,
            qa_mode="github_issues",
            provided_criteria=criteria,
            extra_metadata=extra,
        )

    async def _prefetch_github_issue_acceptance_criteria(
        self,
        github_validation: Any | None,
    ) -> dict[str, Any]:
        client = self._github_pr_client
        owns_client = False
        if client is None:
            client = GitHubPRClient(settings=self.settings)
            owns_client = True
        try:
            return await collect_github_issue_acceptance_criteria(github_validation, client)
        except Exception as exc:
            logger.warning("[QA_AGENT] GitHub issue AC collection failed: %s", exc)
            return {"refs": [], "fetched": [], "criteria": [], "github_issue_numbers": []}
        finally:
            if owns_client:
                await client.aclose()

    async def _run_lane1_coverage(
        self,
        *,
        release_id: str,
        environment: str,
        release_version: str,
        qa_signoff_required: bool,
        pr_title: str | None,
        jira_issue_key: str | None,
        jira_validation: Any | None,
        github_validation: Any | None,
        qa_mode: str,
        provided_criteria: list[QAAcceptanceCriterion] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> QAValidationResult:
        checks = QAChecks(signoff_required=True, signoff_completed=False)
        github_meta = extract_github_metadata(github_validation)
        head_sha = str(github_meta.get("head_sha") or "")
        pr_test_files = collect_pr_test_files(github_validation)
        testing_writeup = extract_pr_testing_writeup(github_validation)
        repo_evidence = await self._collect_repo_evidence(github_validation)
        repo_test_files = list(repo_evidence.get("repo_test_files") or [])
        ci_status = str(repo_evidence.get("ci_status") or "")
        qa_document_text = build_pr_test_document(
            pr_test_files,
            head_sha=head_sha,
            repo_test_files=repo_test_files,
            testing_writeup=testing_writeup,
            ci_status=ci_status,
        )
        metadata: dict[str, Any] = {
            "environment": environment,
            "release_version": release_version,
            "expected_pr_title": pr_title or "",
            "jira_issue_key": jira_issue_key or "",
            "hybrid_pipeline": True,
            "qa_mode": qa_mode,
            "qa_lane": 1,
            "head_sha": head_sha,
            "pr_test_files": [item["filename"] for item in pr_test_files],
            "pr_test_file_count": len(pr_test_files),
            "repo_test_files": [item["filename"] for item in repo_test_files],
            "repo_test_file_count": len(repo_test_files),
            "testing_writeup_used": bool(testing_writeup),
            "ci_status": ci_status,
            "qa_document_text_length": len(qa_document_text),
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        logger.info(
            "[QA_AGENT] Lane 1 real-data gate for %s mode=%s sha=%s pr_tests=%d repo_tests=%d writeup=%s ci=%s",
            release_id,
            qa_mode,
            head_sha or "(none)",
            len(pr_test_files),
            len(repo_test_files),
            "yes" if testing_writeup else "no",
            ci_status or "none",
        )

        if not self.settings.llm_enabled:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=[
                    "LLM is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, and LLM_BASE_URL."
                ],
                metadata=metadata,
            )

        mapper_agent = self.build_langchain_agent()
        tc_agent = self.build_tc_extract_agent()
        if mapper_agent is None or tc_agent is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["Failed to initialize QA LLM agent."],
                metadata=metadata,
            )

        if provided_criteria is None:
            jira_description, jira_comments, acceptance_criteria = _extract_jira_context(
                jira_validation
            )
            if not acceptance_criteria and jira_issue_key:
                fetched_description, fetched_comments, fetched_acs = (
                    await self._prefetch_jira_acceptance_criteria(jira_issue_key)
                )
                acceptance_criteria = fetched_acs
                jira_description = jira_description or fetched_description
                jira_comments = jira_comments or fetched_comments
            ac_resolution, tc_extract = await asyncio.gather(
                self._resolve_acceptance_criteria(
                    provided=acceptance_criteria,
                    jira_issue_key=jira_issue_key,
                    jira_description=jira_description,
                    jira_comments=jira_comments,
                ),
                self._extract_test_cases(
                    agent=tc_agent,
                    attachment_filename="pr-tests",
                    qa_document_text=qa_document_text,
                ),
            )
            if ac_resolution is None:
                return QAValidationResult(
                    status=ValidationStatus.ERROR,
                    checks=checks,
                    errors=["QA AC extract agent did not return structured acceptance criteria."],
                    metadata=metadata,
                )
            extracted_acs, ac_source = ac_resolution
            metadata["ac_source"] = ac_source
        else:
            extracted_acs = provided_criteria
            metadata.setdefault("ac_source", "github_issues")
            tc_extract = await self._extract_test_cases(
                agent=tc_agent,
                attachment_filename="pr-tests",
                qa_document_text=qa_document_text,
            )
        if tc_extract is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["QA test-case extract agent did not return structured test cases."],
                metadata=metadata,
            )

        extracted_tests = merge_test_cases(
            extract_test_cases_from_text(qa_document_text),
            tc_extract.test_cases,
        )
        metadata["extracted_test_case_count"] = len(extracted_tests)

        llm_result = await self._map_coverage(
            agent=mapper_agent,
            release_id=release_id,
            environment=environment,
            release_version=release_version,
            qa_signoff_required=qa_signoff_required,
            pr_title=pr_title,
            jira_issue_key=jira_issue_key,
            attachment_filename="pr-tests",
            acceptance_criteria=extracted_acs,
            test_cases=extracted_tests,
            signoff=None,
        )
        if llm_result is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["QA LLM agent did not return a structured validation result."],
                metadata=metadata,
            )

        llm_result = apply_coverage_constraints(
            llm_result,
            acceptance_criteria=extracted_acs,
            test_cases=extracted_tests,
            signoff=None,
        )
        if ci_status.lower() == "failure":
            llm_result.status = ValidationStatus.FAIL
            if not any("ci" in error.lower() or "check" in error.lower() for error in llm_result.errors):
                llm_result.errors.append(
                    f"GitHub checks for SHA {head_sha or 'unknown'} did not pass ({ci_status})."
                )
        result = _to_qa_validation_result(
            llm_result,
            checks=checks,
            metadata=metadata,
            provided_acceptance_criteria=[item.text for item in extracted_acs],
        )
        await self._attach_generated_tests(
            result,
            acceptance_criteria=extracted_acs,
            existing_tests=qa_document_text,
            jira_issue_key=jira_issue_key,
            head_sha=head_sha,
            owner=str(github_meta.get("owner") or ""),
            repo=str(github_meta.get("repo") or ""),
            repo_files=format_generated_test_repo_context(
                source_files=list(repo_evidence.get("source_files") or []),
                changed_files=changed_production_files(github_validation),
                source_excerpt=str(repo_evidence.get("source_excerpt") or ""),
            ),
        )
        if result.status != ValidationStatus.PASS:
            await self._attach_lane2_drafts(
                result,
                acceptance_criteria=extracted_acs,
                uncovered=uncovered_acceptance_criteria(llm_result.coverage_matrix),
                existing_tests=qa_document_text,
                jira_issue_key=jira_issue_key,
                head_sha=head_sha,
            )
        return result

    async def _collect_repo_evidence(self, github_validation: Any | None) -> dict[str, Any]:
        empty = {"repo_test_files": [], "source_files": [], "source_excerpt": "", "ci_status": ""}
        client = self._repo_evidence_client
        if client is None:
            token = ""
            try:
                raw = self.settings.github_personal_access_token.get_secret_value()
                token = raw.strip() if isinstance(raw, str) else ""
            except Exception:
                token = ""
            if not token:
                return empty
            client = GitHubRepoEvidenceClient(settings=self.settings)
            self._repo_evidence_client = client
        try:
            return await client.collect_lane1_evidence(github_validation)
        except Exception as exc:
            logger.warning("[QA_AGENT] Repo evidence collection failed: %s", exc)
            return empty

    async def _attach_generated_tests(
        self,
        result: QAValidationResult,
        *,
        acceptance_criteria: list[QAAcceptanceCriterion],
        existing_tests: str,
        jira_issue_key: str | None,
        head_sha: str,
        owner: str = "",
        repo: str = "",
        repo_files: str = "",
    ) -> None:
        if not acceptance_criteria:
            result.metadata["generated_tests"] = []
            return
        bundle = await self._generate_executable_tests(
            acceptance_criteria=acceptance_criteria,
            existing_tests=existing_tests,
            jira_issue_key=jira_issue_key,
            head_sha=head_sha,
            repo_files=repo_files,
        )
        for item in bundle.tests:
            criterion = next(
                (row for row in acceptance_criteria if row.ac_id == item.ac_id),
                None,
            )
            if criterion is None:
                continue
            item.test_file = f"tests/generated/{criterion.ac_id.lower()}_test.py"
            item.test_code = build_generated_test_code(criterion, repo_files)
        result.metadata["generated_tests_repo"] = f"{owner}/{repo}".strip("/") if owner and repo else ""
        result.metadata["generated_tests_sha"] = head_sha
        try:
            executed = await self._generated_test_runner.run(
                bundle.tests,
                owner=owner,
                repo=repo,
                sha=head_sha,
            )
        except Exception as exc:
            logger.warning("[QA_AGENT] Generated test runner failed: %s", exc)
            executed = bundle.tests
            for item in executed:
                if item.status.upper() not in {"PASS", "FAIL"}:
                    item.status = "FAIL"
                if not item.reason:
                    item.reason = f"Could not execute generated test: {exc}"
        result.metadata["generated_tests"] = [
            item.model_dump(exclude={"test_code"}) for item in executed
        ]
        result.metadata["generated_test_count"] = len(executed)
        result.metadata["generated_test_pass_count"] = sum(
            1 for item in executed if item.status.upper() == "PASS"
        )

    async def _generate_executable_tests(
        self,
        *,
        acceptance_criteria: list[QAAcceptanceCriterion],
        existing_tests: str,
        jira_issue_key: str | None,
        head_sha: str,
        repo_files: str = "",
    ) -> QAGeneratedTestBundle:
        empty = QAGeneratedTestBundle()
        try:
            agent = self.build_generated_test_agent()
        except Exception as exc:
            logger.warning("[QA_AGENT] Generated test agent init failed: %s", exc)
            return empty
        if agent is None:
            return empty
        criteria_text = "\n".join(
            f"- {item.ac_id}: {item.text}" for item in acceptance_criteria
        )
        user_message = format_prompt(
            "qa_generated_test_user",
            jira_issue_key=(jira_issue_key or "").strip() or "(not provided)",
            head_sha=head_sha or "(unknown)",
            acceptance_criteria=criteria_text,
            existing_tests=(existing_tests or "")[:12000],
            repo_files=(repo_files or "")[:8000] or "(no source file list)",
        )
        result = await invoke_structured_agent(
            agent,
            user_message=user_message,
            response_model=QAGeneratedTestBundle,
        )
        if result is None:
            return empty
        by_id = {item.ac_id.strip().upper(): item for item in result.tests if item.ac_id}
        aligned: list[QAGeneratedTest] = []
        for criterion in acceptance_criteria:
            key = criterion.ac_id.strip().upper()
            item = by_id.get(key) or QAGeneratedTest(
                ac_id=criterion.ac_id,
                generated_test=f"test_{criterion.ac_id.lower().replace('-', '_')}",
                test_file="tests/test_generated.py",
                summary=f"Generated test for {criterion.ac_id}.",
                status="FAIL",
                reason="Generator omitted this acceptance criterion.",
            )
            item.ac_id = criterion.ac_id
            aligned.append(item)
        return QAGeneratedTestBundle(tests=aligned)

    async def _attach_lane2_drafts(
        self,
        result: QAValidationResult,
        *,
        acceptance_criteria: list[QAAcceptanceCriterion],
        uncovered: list,
        existing_tests: str,
        jira_issue_key: str | None,
        head_sha: str,
    ) -> None:
        bundle = await self._generate_lane2_drafts(
            uncovered=uncovered,
            existing_tests=existing_tests,
            jira_issue_key=jira_issue_key,
            head_sha=head_sha,
        )
        drafts = [item.model_dump() for item in bundle.drafts]
        result.metadata["qa_lane"] = 2
        result.metadata["lane2_optional"] = True
        result.metadata["lane2_developer_instructions"] = bundle.developer_instructions
        result.metadata["lane2_draft_tests"] = drafts
        result.metadata["lane2_comment"] = format_lane2_comment(
            head_sha=head_sha,
            uncovered=uncovered,
            drafts=bundle.drafts,
        )
        if not uncovered and acceptance_criteria:
            result.metadata["lane2_note"] = (
                "Lane 1 failed. Generate or commit tests, then re-run the release "
                "so Lane 1 checks the new SHA."
            )

    async def _generate_lane2_drafts(
        self,
        *,
        uncovered: list,
        existing_tests: str,
        jira_issue_key: str | None,
        head_sha: str,
    ) -> QADraftTestBundle:
        empty = QADraftTestBundle()
        if not uncovered:
            return empty
        agent = self.build_lane2_draft_agent()
        if agent is None:
            return empty
        uncovered_text = "\n".join(
            f"- {row.ac_id}: {row.acceptance_criterion} ({row.coverage})"
            for row in uncovered
        )
        user_message = format_prompt(
            "qa_lane2_draft_user",
            jira_issue_key=(jira_issue_key or "").strip() or "(not provided)",
            head_sha=head_sha or "(unknown)",
            uncovered_criteria=uncovered_text,
            existing_tests=existing_tests[:12000],
        )
        result = await invoke_structured_agent(
            agent,
            user_message=user_message,
            response_model=QADraftTestBundle,
        )
        return result or empty

    async def _resolve_acceptance_criteria(
        self,
        *,
        provided: list[str],
        jira_issue_key: str | None,
        jira_description: str,
        jira_comments: str,
    ) -> tuple[list[QAAcceptanceCriterion], str] | None:
        """Use code-extracted ACs when present; otherwise run the short AC extractor."""
        if provided:
            return _criteria_from_texts(provided), "code"

        agent = self.build_ac_extract_agent()
        if agent is None:
            logger.warning("[QA_AGENT] Failed to initialize AC extract agent")
            return None

        user_message = format_prompt(
            "qa_ac_extract_user",
            jira_issue_key=(jira_issue_key or "").strip() or "(not provided)",
            jira_description=jira_description or "(not provided)",
            jira_comments=jira_comments or "(none provided)",
        )
        result = await invoke_structured_agent(
            agent,
            user_message=user_message,
            response_model=QAAcceptanceCriteriaExtract,
        )
        if result is None:
            return None
        if result.no_acceptance_criteria_found:
            return [], "llm"
        return _normalize_extracted_criteria(result.acceptance_criteria), "llm"

    async def _extract_test_cases(
        self,
        *,
        agent: Any,
        attachment_filename: str,
        qa_document_text: str,
    ) -> QATestCaseExtract | None:
        user_message = format_prompt(
            "qa_tc_extract_user",
            attachment_filename=attachment_filename,
            qa_document_text=qa_document_text,
        )
        result = await invoke_structured_agent(
            agent,
            user_message=user_message,
            response_model=QATestCaseExtract,
        )
        if result is None:
            return None
        result.test_cases = [
            QATestCase(
                test_case_id=item.test_case_id.strip(),
                scenario=item.scenario.strip(),
                expected_result=item.expected_result.strip(),
                status=normalize_test_result(item.status) if item.status else "",
            )
            for item in result.test_cases
            if item.test_case_id.strip()
        ]
        return result

    async def _map_coverage(
        self,
        *,
        agent: Any,
        release_id: str,
        environment: str,
        release_version: str,
        qa_signoff_required: bool,
        pr_title: str | None,
        jira_issue_key: str | None,
        attachment_filename: str,
        acceptance_criteria: list[QAAcceptanceCriterion],
        test_cases: list[QATestCase],
        signoff: SignOffRequest | None = None,
    ) -> QALLMValidationOutput | None:
        user_message = format_prompt(
            "qa_agent_user",
            release_id=release_id,
            environment=environment,
            release_version=release_version,
            qa_signoff_required=qa_signoff_required,
            pr_title=(pr_title or "").strip() or "(not provided)",
            jira_issue_key=(jira_issue_key or "").strip() or "(not provided)",
            attachment_filename=attachment_filename,
            signoff_facts=format_signoff_facts(signoff),
            acceptance_criteria=_format_acceptance_criteria(acceptance_criteria),
            test_cases=_format_test_cases(test_cases),
        )
        return await invoke_structured_agent(
            agent,
            user_message=user_message,
            response_model=QALLMValidationOutput,
        )

    async def _prefetch_jira_acceptance_criteria(
        self,
        issue_key: str,
    ) -> tuple[str, str, list[str]]:
        """Fetch Jira ACs when the Jira agent did not pass them through."""
        from app.agents.tools.mcp_tools import _with_jira_client
        from app.utils.jira_fields import (
            extract_acceptance_criteria,
            extract_issue_comments,
            extract_issue_description,
        )

        async def _fetch(client: JiraMCPClient) -> tuple[str, str, list[str]]:
            issue = await client.get_issue(issue_key)
            description = extract_issue_description(issue) or ""
            comments = extract_issue_comments(issue)
            comment_lines = [
                f"- {item.get('author', 'unknown')}: {item.get('body', '')}"
                for item in comments
                if isinstance(item, dict)
            ]
            comments_text = "\n".join(comment_lines)
            criteria = extract_acceptance_criteria(description)
            if not criteria:
                for item in comments:
                    if isinstance(item, dict):
                        criteria.extend(extract_acceptance_criteria(item.get("body") or ""))
                if not criteria:
                    criteria = extract_acceptance_criteria(comments_text)
            return description, comments_text, _unique_criteria(criteria)

        try:
            return await _with_jira_client(self._jira_client, _fetch)
        except Exception as exc:
            logger.warning("[QA_AGENT] Unable to prefetch Jira ACs for %s: %s", issue_key, exc)
            return "", "", []

    def get_mcp_tools(self) -> list:
        return build_jira_mcp_tools(self._jira_client)

    def build_ac_extract_agent(self, llm: BaseChatModel | None = None):
        return create_langchain_agent(
            settings=self.settings,
            tools=self.get_mcp_tools(),
            system_prompt=load_prompt("qa_ac_extract_system"),
            name="qa_ac_extract_agent",
            response_format=QAAcceptanceCriteriaExtract,
            llm=llm,
        )

    def build_tc_extract_agent(self, llm: BaseChatModel | None = None):
        return create_langchain_agent(
            settings=self.settings,
            tools=[],
            system_prompt=load_prompt("qa_tc_extract_system"),
            name="qa_tc_extract_agent",
            response_format=QATestCaseExtract,
            llm=llm,
        )

    def build_langchain_agent(self, llm: BaseChatModel | None = None):
        return create_langchain_agent(
            settings=self.settings,
            tools=[],
            system_prompt=load_prompt("qa_agent_system"),
            name="qa_agent",
            response_format=QALLMValidationOutput,
            llm=llm,
        )

    def build_lane2_draft_agent(self, llm: BaseChatModel | None = None):
        return create_langchain_agent(
            settings=self.settings,
            tools=[],
            system_prompt=load_prompt("qa_lane2_draft_system"),
            name="qa_lane2_draft_agent",
            response_format=QADraftTestBundle,
            llm=llm,
        )

    def build_generated_test_agent(self, llm: BaseChatModel | None = None):
        return create_langchain_agent(
            settings=self.settings,
            tools=[],
            system_prompt=load_prompt("qa_generated_test_system"),
            name="qa_generated_test_agent",
            response_format=QAGeneratedTestBundle,
            llm=llm,
        )


def _load_structured_signoff(
    signoff_service: QASignoffService,
    *,
    release_id: str,
    attachment: dict[str, Any],
) -> SignOffRequest | None:
    try:
        parsed = signoff_service.load_structured_signoff(
            release_id=release_id,
            attachment=attachment,
        )
    except Exception as exc:
        logger.info("[QA_AGENT] Structured sign-off fields unavailable: %s", exc)
        return None
    return parsed if isinstance(parsed, SignOffRequest) else None


def _extract_jira_context(jira_validation: Any | None) -> tuple[str, str, list[str]]:
    if jira_validation is None:
        return "", "", []

    if hasattr(jira_validation, "metadata"):
        metadata = jira_validation.metadata or {}
    elif isinstance(jira_validation, dict):
        metadata = jira_validation.get("metadata") or {}
    else:
        metadata = {}

    description = metadata.get("jira_description")
    if not isinstance(description, str):
        description = metadata.get("description") or ""

    comments = metadata.get("jira_comments") or metadata.get("comments") or []
    if isinstance(comments, list):
        comment_lines = []
        for item in comments:
            if isinstance(item, dict):
                author = item.get("author") or item.get("displayName") or "unknown"
                body = item.get("body") or item.get("text") or ""
                comment_lines.append(f"- {author}: {body}")
            else:
                comment_lines.append(f"- {item}")
        comments_text = "\n".join(comment_lines)
    elif isinstance(comments, str):
        comments_text = comments
    else:
        comments_text = ""

    return (
        str(description).strip(),
        comments_text.strip(),
        _acceptance_criteria_from_jira_metadata(
            metadata,
            str(description),
            comments_text,
        ),
    )


def _acceptance_criteria_from_jira_metadata(
    metadata: dict[str, Any],
    description: str = "",
    comments: str = "",
) -> list[str]:
    raw = metadata.get("acceptance_criteria")
    if isinstance(raw, list):
        parsed = [str(item).strip() for item in raw if str(item).strip()]
        if parsed:
            return parsed

    matrix = metadata.get("validation_matrix") or []
    criteria: list[str] = []
    seen: set[str] = set()
    for row in matrix:
        if not isinstance(row, dict):
            continue
        text = str(row.get("jira_requirement") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        criteria.append(text)
    if criteria:
        return criteria

    from app.utils.jira_fields import extract_acceptance_criteria

    parsed = extract_acceptance_criteria(description)
    if parsed:
        return parsed
    return _unique_criteria(extract_acceptance_criteria(comments))


def _criteria_from_texts(texts: list[str]) -> list[QAAcceptanceCriterion]:
    return [
        QAAcceptanceCriterion(ac_id=f"AC-{index:02d}", text=text.strip())
        for index, text in enumerate(texts, start=1)
        if text.strip()
    ]


def _normalize_extracted_criteria(
    items: list[QAAcceptanceCriterion],
) -> list[QAAcceptanceCriterion]:
    normalized: list[QAAcceptanceCriterion] = []
    for index, item in enumerate(items, start=1):
        text = item.text.strip()
        if not text:
            continue
        ac_id = item.ac_id.strip() or f"AC-{index:02d}"
        normalized.append(QAAcceptanceCriterion(ac_id=ac_id, text=text))
    return normalized


def _unique_criteria(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        text = item.strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _format_acceptance_criteria(criteria: list[QAAcceptanceCriterion]) -> str:
    if not criteria:
        return (
            "None extracted from the Jira ticket yet. "
            "Set no_acceptance_criteria_found. Do not invent Acceptance Criteria."
        )
    lines = [
        "These criteria were already extracted from the JIRA ticket. They exist. "
        "Use this list. Do not report them as missing. Do not invent extra ACs."
    ]
    for item in criteria:
        lines.append(f"- {item.ac_id}: {item.text}")
    return "\n".join(lines)


def _format_test_cases(test_cases: list[QATestCase]) -> str:
    if not test_cases:
        return "No test cases were extracted from the QA document."
    lines: list[str] = []
    for item in test_cases:
        lines.append(f"- {item.test_case_id}: {item.scenario or '(no scenario)'}")
        if item.expected_result:
            lines.append(f"  Expected: {item.expected_result}")
        if item.status:
            lines.append(f"  Status: {item.status}")
    return "\n".join(lines)


_MISSING_AC_MARKERS = (
    "no explicit acceptance criteria",
    "missing explicit acceptance criteria",
    "no acceptance criteria found",
)


def _is_missing_ac_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in _MISSING_AC_MARKERS)


def _to_qa_validation_result(
    llm_result: QALLMValidationOutput,
    *,
    checks: QAChecks,
    metadata: dict[str, Any],
    provided_acceptance_criteria: list[str] | None = None,
) -> QAValidationResult:
    provided = [item for item in (provided_acceptance_criteria or []) if item]
    no_ac_found = llm_result.no_acceptance_criteria_found
    errors = list(llm_result.errors)
    status = llm_result.status

    if provided:
        no_ac_found = False
        errors = [error for error in errors if not _is_missing_ac_error(error)]
        if status == ValidationStatus.FAIL and not llm_result.coverage_matrix:
            logger.warning(
                "[QA_AGENT] LLM reported missing ACs despite %d provided criteria",
                len(provided),
            )
            if not errors:
                errors = [
                    "QA agent did not map the acceptance criteria already found on the Jira ticket."
                ]

    metadata = {
        **metadata,
        "validation_summary": llm_result.validation_summary,
        "coverage_matrix": [row.model_dump() for row in llm_result.coverage_matrix],
        "acceptance_criteria_coverage_percent": llm_result.acceptance_criteria_coverage_percent,
        "passed_acceptance_criteria_percent": llm_result.passed_acceptance_criteria_percent,
        "no_acceptance_criteria_found": no_ac_found,
        "provided_acceptance_criteria": provided,
    }

    if status == ValidationStatus.PASS:
        return QAValidationResult(
            status=ValidationStatus.PASS,
            checks=QAChecks(
                signoff_required=True,
                signoff_completed=True,
            ),
            metadata=metadata,
        )

    if status == ValidationStatus.FAIL and not errors:
        errors = ["QA acceptance-criteria validation failed."]

    return QAValidationResult(
        status=status,
        checks=checks,
        errors=errors,
        metadata=metadata,
    )
