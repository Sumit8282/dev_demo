"""Release API routes."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.agents.orchestrator import Orchestrator
from app.agents.orchestrator_agent import build_release_orchestrator
from app.models.validation import MergeResultStatus
from app.models.l3_approval import (
    L3ApprovalActionRequest,
    L3ApprovalMailDraft,
    L3ApprovalRejectRequest,
    L3ApprovalRequest,
    L3ApprovalStatus,
)
from app.models.rm_approval import (
    RMApprovalActionRequest,
    RMApprovalNotificationDraft,
    RMApprovalRejectRequest,
    RMApprovalRequest,
    RMApprovalStatus,
)
from app.models.release import (
    ReleaseCreateResponse,
    ReleaseRequest,
    ReleaseStateResponse,
    WorkflowStatus,
)
from app.services.attachment_store import get_qa_signoff_attachment_path, save_qa_signoff_attachment
from app.services.jira_workflow_service import JiraWorkflowService
from app.services.l3_mail_store import load_l3_approval_mail_draft
from app.services.rm_mail_store import load_rm_approval_notification_draft
from app.services.release_store import release_store
from app.services.workflow_events import emit_workflow_event
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase
from app.utils.parsers import (
    extract_github_pr_parts,
    extract_jira_issue_key,
    extract_release_version,
)
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/releases", tags=["releases"])


def _get_orchestrator_agent():
    """Build a fresh orchestrator so it always uses current settings/MCP config."""
    return build_release_orchestrator(Orchestrator())


async def _l3_update_jira_after_approval(release_id: str) -> None:
    state = release_store.get(release_id)
    if not state:
        return
    issue_key = state.get("jira_issue_key")
    if not issue_key:
        logger.warning("[L3_AGENT] No Jira issue key for release %s", release_id)
        return
    from app.agents.l3_agent import L3Agent

    await L3Agent().update_jira_ticket_status(
        issue_key=issue_key,
        release_id=release_id,
        low_risk=False,
    )


async def _jira_on_build_completed(release_id: str, build_id: str) -> None:
    state = release_store.get(release_id)
    if not state:
        return
    issue_key = state.get("jira_issue_key")
    if not issue_key or not build_id:
        logger.warning(
            "[JIRA_WORKFLOW] Missing Jira issue or build ID for release %s", release_id
        )
        return
    await JiraWorkflowService().on_build_completed(
        issue_key=issue_key,
        release_id=release_id,
        build_id=build_id,
        environment=str(state.get("environment") or ""),
    )


async def _jira_on_deployment_completed(release_id: str) -> None:
    state = release_store.get(release_id)
    if not state:
        return
    issue_key = state.get("jira_issue_key")
    if not issue_key:
        logger.warning("[JIRA_WORKFLOW] No Jira issue key for release %s", release_id)
        return
    build_result = state.get("build_result") or {}
    build_id = build_result.get("build_id") if isinstance(build_result, dict) else None
    await JiraWorkflowService().on_deployment_completed(
        issue_key=issue_key,
        release_id=release_id,
        environment=str(state.get("environment") or ""),
        build_id=str(build_id) if build_id else None,
    )


async def _auto_complete_deployment_after_rm_approve(release_id: str) -> None:
    """Fallback: complete deployment and update Jira if the UI does not trigger it."""
    import asyncio

    await asyncio.sleep(8)
    state = release_store.get(release_id)
    if not state or state.get("workflow_status") != WorkflowStatus.RM_APPROVED.value:
        return

    logger.info("[DEPLOY] Auto-completing deployment for release %s", release_id)
    updated = release_store.update(
        release_id,
        {"workflow_status": WorkflowStatus.DEPLOYMENT_COMPLETED.value},
    )
    if not updated:
        return
    emit_workflow_event(
        release_id,
        agent=WorkflowEventAgent.ORCHESTRATOR,
        phase=WorkflowEventPhase.COMPLETED,
        message=f"Deployment completed on {state.get('environment', '')}",
        metadata={"environment": state.get("environment"), "auto_completed": True},
    )
    await _jira_on_deployment_completed(release_id)


async def _execute_workflow(release_id: str, initial_state: ReleaseState) -> None:
    logger.info("[RELEASE] Starting workflow for %s", release_id)
    try:
        final_state = await _get_orchestrator_agent().ainvoke(initial_state)
        release_store.update(release_id, final_state)
        workflow_status = final_state.get("workflow_status")
        if workflow_status == WorkflowStatus.HALTED.value:
            logger.info("[WORKFLOW] Release %s HALTED", release_id)
        elif workflow_status == WorkflowStatus.L3_APPROVAL_PENDING.value:
            logger.info("[WORKFLOW] Release %s awaiting L3 approval", release_id)
        elif workflow_status == WorkflowStatus.MERGED.value:
            logger.info("[WORKFLOW] Release %s merged (low risk auto-merge)", release_id)
            await _execute_post_merge_workflow(release_id)
        elif workflow_status == WorkflowStatus.MERGE_FAILED.value:
            logger.warning("[WORKFLOW] Release %s low risk auto-merge failed", release_id)
        elif workflow_status == WorkflowStatus.VALIDATION_ERROR.value:
            logger.error("[WORKFLOW] Release %s validation error", release_id)
    except Exception:
        logger.exception("[WORKFLOW] Unexpected workflow failure for %s", release_id)
        release_store.update(
            release_id,
            {
                "workflow_status": WorkflowStatus.VALIDATION_ERROR.value,
                "failure_reasons": ["Unexpected workflow execution failure."],
            },
        )
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.ORCHESTRATOR,
            phase=WorkflowEventPhase.ERROR,
            message="Unexpected workflow execution failure",
        )


async def _execute_merge(release_id: str) -> None:
    logger.info("[MERGE] Starting auto-merge workflow for %s", release_id)
    state = release_store.get(release_id)
    if not state:
        logger.error("[MERGE] Release %s not found", release_id)
        return

    release_store.update(release_id, {"workflow_status": WorkflowStatus.MERGE_PENDING.value})
    state = release_store.get(release_id)
    if not state:
        logger.error("[MERGE] Release %s not found after status update", release_id)
        return

    try:
        orchestrator = Orchestrator()
        merge_result = await orchestrator.run_merge(state)
        merge_payload = merge_result.model_dump(mode="json")

        if merge_result.status == MergeResultStatus.MERGED:
            release_store.update(
                release_id,
                {
                    "workflow_status": WorkflowStatus.MERGED.value,
                    "merge_result": merge_payload,
                },
            )
            logger.info("[MERGE] Release %s merged successfully", release_id)
            await _execute_post_merge_workflow(release_id)
        else:
            release_store.update(
                release_id,
                {
                    "workflow_status": WorkflowStatus.MERGE_FAILED.value,
                    "merge_result": merge_payload,
                    "failure_reasons": merge_result.errors,
                },
            )
            logger.warning(
                "[MERGE] Release %s merge failed: %s",
                release_id,
                "; ".join(merge_result.errors) or merge_result.status.value,
            )
    except Exception:
        logger.exception("[MERGE] Unexpected merge workflow failure for %s", release_id)
        release_store.update(
            release_id,
            {
                "workflow_status": WorkflowStatus.MERGE_FAILED.value,
                "failure_reasons": ["Unexpected auto-merge workflow failure."],
            },
        )
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.MERGE,
            phase=WorkflowEventPhase.ERROR,
            message="Unexpected auto-merge workflow failure",
        )


async def _execute_post_merge_workflow(release_id: str) -> None:
    """Run build generation and RM approval preparation after a successful merge."""
    logger.info("[POST_MERGE] Starting build + RM approval workflow for %s", release_id)
    state = release_store.get(release_id)
    if not state:
        logger.error("[POST_MERGE] Release %s not found", release_id)
        return

    release_store.update(release_id, {"workflow_status": WorkflowStatus.BUILD_PENDING.value})
    state = release_store.get(release_id)
    if not state:
        logger.error("[POST_MERGE] Release %s not found after status update", release_id)
        return

    try:
        orchestrator = Orchestrator()

        async def _on_run_discovered(build_result) -> None:
            release_store.update(
                release_id,
                {
                    "workflow_status": WorkflowStatus.BUILD_PENDING.value,
                    "build_result": build_result.model_dump(mode="json"),
                },
            )
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.BUILD,
                phase=WorkflowEventPhase.STARTED,
                message=(
                    f"CI/CD run discovered — {build_result.build_id}"
                    + (f" ({build_result.job_url})" if build_result.job_url else "")
                ),
                metadata={
                    "build_id": build_result.build_id,
                    "job_url": build_result.job_url,
                    "commit_sha": build_result.commit_sha,
                },
            )

        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.BUILD,
            phase=WorkflowEventPhase.STARTED,
            message="Build agent started — generating release build",
        )
        build_payload = await orchestrator.run_build_generation(
            state,
            on_run_discovered=_on_run_discovered,
        )
        build_status = (
            str(build_payload.get("status") or "").upper()
            if isinstance(build_payload, dict)
            else ""
        )
        if build_status == "FAILED":
            failure_reason = (
                str(build_payload.get("failure_reason") or "CI/CD pipeline failed.")
                if isinstance(build_payload, dict)
                else "CI/CD pipeline failed."
            )
            release_store.update(
                release_id,
                {
                    "workflow_status": WorkflowStatus.BUILD_FAILED.value,
                    "build_result": build_payload,
                    "failure_reasons": [failure_reason],
                },
            )
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.BUILD,
                phase=WorkflowEventPhase.ERROR,
                message=f"Build failed — {failure_reason}",
                metadata={
                    "build_id": build_payload.get("build_id")
                    if isinstance(build_payload, dict)
                    else None,
                    "job_url": build_payload.get("job_url")
                    if isinstance(build_payload, dict)
                    else None,
                },
            )
            logger.warning("[POST_MERGE] Release %s build failed: %s", release_id, failure_reason)
            return

        release_store.update(
            release_id,
            {
                "workflow_status": WorkflowStatus.BUILD_COMPLETED.value,
                "build_result": build_payload,
            },
        )
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.BUILD,
            phase=WorkflowEventPhase.COMPLETED,
            message=(
                f"Build generated successfully — {build_payload.get('build_id')}"
                if isinstance(build_payload, dict)
                else "Build generated successfully"
            ),
            metadata={
                "build_id": build_payload.get("build_id")
                if isinstance(build_payload, dict)
                else None,
                "job_url": build_payload.get("job_url")
                if isinstance(build_payload, dict)
                else None,
            },
        )
        build_id = build_payload.get("build_id") if isinstance(build_payload, dict) else None
        if build_id:
            await _jira_on_build_completed(release_id, str(build_id))

        state = release_store.get(release_id)
        if not state:
            logger.error("[POST_MERGE] Release %s not found after build generation", release_id)
            return

        rm_request, _notification_path = await orchestrator.run_rm_approval_preparation(
            state,
            build_result=build_payload,
        )
        release_store.update(
            release_id,
            {
                "workflow_status": WorkflowStatus.RM_APPROVAL_PENDING.value,
                "rm_approval_request": rm_request,
            },
        )
        logger.info(
            "[POST_MERGE] Release %s awaiting RM approval",
            release_id,
        )
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.RM,
            phase=WorkflowEventPhase.COMPLETED,
            message="RM approval request created",
            metadata={"approval_url": rm_request.get("approval_url")},
        )
    except Exception:
        logger.exception("[POST_MERGE] Unexpected post-merge workflow failure for %s", release_id)
        release_store.update(
            release_id,
            {
                "workflow_status": WorkflowStatus.BUILD_FAILED.value,
                "failure_reasons": ["Unexpected post-merge workflow failure."],
            },
        )
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.BUILD,
            phase=WorkflowEventPhase.ERROR,
            message="Unexpected post-merge workflow failure",
        )


def _build_initial_state(
    request: ReleaseRequest,
    *,
    qa_signoff_attachment: dict[str, str | int] | None = None,
) -> ReleaseState:
    release_version = extract_release_version(request.release_branch)
    jira_issue_key = extract_jira_issue_key(str(request.jira_url))
    github_owner, github_repo, github_pr_number = extract_github_pr_parts(str(request.github_pr_url))

    attachment_state = None
    if qa_signoff_attachment:
        attachment_state = {
            "filename": qa_signoff_attachment["filename"],
            "content_type": qa_signoff_attachment["content_type"],
            "size_bytes": qa_signoff_attachment["size_bytes"],
        }

    return {
        "release_id": release_store.generate_release_id(),
        "release_branch": request.release_branch,
        "release_version": release_version,
        "github_pr_url": str(request.github_pr_url),
        "github_owner": github_owner,
        "github_repo": github_repo,
        "github_pr_number": github_pr_number,
        "jira_url": str(request.jira_url),
        "jira_issue_key": jira_issue_key,
        "qa_signoff_required": request.qa_signoff_required,
        "qa_signoff_not_required_reason": request.qa_signoff_not_required_reason,
        "qa_signoff_attachment": attachment_state,
        "environment": request.environment,
        "release_date": request.release_date,
        "created_by": request.created_by,
    }


async def _parse_json_request(request: Request) -> tuple[ReleaseRequest, UploadFile | None]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid JSON request body.",
        ) from exc
    try:
        return ReleaseRequest.model_validate(payload), None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


async def _parse_multipart_request(
    request: Request,
) -> tuple[ReleaseRequest, UploadFile | None]:
    form = await request.form()
    try:
        release_request = ReleaseRequest(
            release_branch=str(form.get("release_branch", "")),
            github_pr_url=str(form.get("github_pr_url", "")),
            jira_url=str(form.get("jira_url", "")),
            qa_signoff_required=str(form.get("qa_signoff_required", "false")).lower() in {"true", "1", "yes"},
            qa_signoff_not_required_reason=form.get("qa_signoff_not_required_reason") or None,
            environment=str(form.get("environment", "")),
            release_date=date.fromisoformat(str(form.get("release_date", ""))),
            created_by=form.get("created_by") or None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    attachment = form.get("qa_signoff_attachment")
    upload = attachment if isinstance(attachment, StarletteUploadFile) else None
    return release_request, upload


@router.post("", response_model=ReleaseCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_release(
    request: Request,
    background_tasks: BackgroundTasks,
) -> ReleaseCreateResponse:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        release_request, qa_signoff_attachment = await _parse_multipart_request(request)
    else:
        release_request, qa_signoff_attachment = await _parse_json_request(request)

    if release_request.qa_signoff_required:
        if qa_signoff_attachment is None or not qa_signoff_attachment.filename:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="QA sign-off attachment is required when qa_signoff_required is true.",
            )
    elif qa_signoff_attachment is not None and qa_signoff_attachment.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="QA sign-off attachment should only be provided when qa_signoff_required is true.",
        )

    try:
        initial_state = _build_initial_state(release_request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    release_id = initial_state["release_id"]

    if qa_signoff_attachment is not None and qa_signoff_attachment.filename:
        saved_attachment = await save_qa_signoff_attachment(release_id, qa_signoff_attachment)
        initial_state["qa_signoff_attachment"] = {
            "filename": saved_attachment["filename"],
            "content_type": saved_attachment["content_type"],
            "size_bytes": saved_attachment["size_bytes"],
        }

    release_store.create(initial_state)
    logger.info("[RELEASE] Created release %s", release_id)
    emit_workflow_event(
        release_id,
        agent=WorkflowEventAgent.SYSTEM,
        phase=WorkflowEventPhase.COMPLETED,
        message=f"Release {release_id} created — workflow started",
    )

    background_tasks.add_task(_execute_workflow, release_id, initial_state)

    return ReleaseCreateResponse(
        release_id=release_id,
        workflow_status=WorkflowStatus.VALIDATING,
        message="Release workflow started.",
    )


@router.get("", response_model=list[ReleaseStateResponse])
async def list_releases() -> list[ReleaseStateResponse]:
    return [release_store.to_response(state) for state in release_store.list_all()]


@router.get("/l3-approval-queue", response_model=list[ReleaseStateResponse])
async def list_l3_approval_queue() -> list[ReleaseStateResponse]:
    releases = [
        state
        for state in release_store.list_all()
        if state.get("workflow_status") == WorkflowStatus.L3_APPROVAL_PENDING.value
    ]
    return [release_store.to_response(state) for state in releases]


@router.get("/rm-approval-queue", response_model=list[ReleaseStateResponse])
async def list_rm_approval_queue() -> list[ReleaseStateResponse]:
    releases = [
        state
        for state in release_store.list_all()
        if state.get("workflow_status") == WorkflowStatus.RM_APPROVAL_PENDING.value
    ]
    return [release_store.to_response(state) for state in releases]


@router.get("/{release_id}", response_model=ReleaseStateResponse)
async def get_release(release_id: str) -> ReleaseStateResponse:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    return release_store.to_response(state)


@router.get("/{release_id}/l3-approval", response_model=L3ApprovalRequest)
async def get_l3_approval(release_id: str) -> L3ApprovalRequest:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )

    raw = state.get("l3_approval_request")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No L3 approval request for release {release_id}.",
        )
    return L3ApprovalRequest.model_validate(raw)


@router.get("/{release_id}/l3-approval-mail", response_model=L3ApprovalMailDraft)
async def get_l3_approval_mail(release_id: str) -> L3ApprovalMailDraft:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )

    mail_draft = load_l3_approval_mail_draft(release_id)
    if not mail_draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No L3 approval mail draft for release {release_id}.",
        )
    return mail_draft


@router.post("/{release_id}/l3/approve", response_model=ReleaseStateResponse)
async def approve_l3_release(
    release_id: str,
    body: L3ApprovalActionRequest,
    background_tasks: BackgroundTasks,
) -> ReleaseStateResponse:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    if state.get("workflow_status") != WorkflowStatus.L3_APPROVAL_PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Release is not pending L3 approval.",
        )

    raw = state.get("l3_approval_request")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No L3 approval request for release {release_id}.",
        )

    now = datetime.now(timezone.utc)
    approval_request = L3ApprovalRequest.model_validate(raw)
    approval_comment = body.comment.strip() if body.comment and body.comment.strip() else None
    updated_request = approval_request.model_copy(
        update={
            "status": L3ApprovalStatus.APPROVED,
            "approved_by": body.approver_name.strip(),
            "approver_soe_id": body.approver_soe_id.strip(),
            "approved_at": now,
            "approval_comment": approval_comment,
        }
    )

    updated = release_store.update(
        release_id,
        {
            "workflow_status": WorkflowStatus.L3_APPROVED.value,
            "l3_approval_request": updated_request.model_dump(mode="json"),
        },
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    emit_workflow_event(
        release_id,
        agent=WorkflowEventAgent.L3,
        phase=WorkflowEventPhase.COMPLETED,
        message=f"L3 approval granted by {body.approver_name.strip()}",
        metadata={"approver": body.approver_name.strip()},
    )
    background_tasks.add_task(_l3_update_jira_after_approval, release_id)
    background_tasks.add_task(_execute_merge, release_id)
    return release_store.to_response(updated)


@router.post("/{release_id}/l3/reject", response_model=ReleaseStateResponse)
async def reject_l3_release(
    release_id: str,
    body: L3ApprovalRejectRequest,
) -> ReleaseStateResponse:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    if state.get("workflow_status") != WorkflowStatus.L3_APPROVAL_PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Release is not pending L3 approval.",
        )

    raw = state.get("l3_approval_request")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No L3 approval request for release {release_id}.",
        )

    now = datetime.now(timezone.utc)
    approval_request = L3ApprovalRequest.model_validate(raw)
    updated_request = approval_request.model_copy(
        update={
            "status": L3ApprovalStatus.REJECTED,
            "approved_by": body.approver_name.strip(),
            "approver_soe_id": body.approver_soe_id.strip(),
            "approved_at": now,
            "rejection_remarks": body.remarks.strip(),
        }
    )

    updated = release_store.update(
        release_id,
        {
            "workflow_status": WorkflowStatus.L3_REJECTED.value,
            "l3_approval_request": updated_request.model_dump(mode="json"),
            "failure_reasons": [body.remarks.strip()],
        },
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    emit_workflow_event(
        release_id,
        agent=WorkflowEventAgent.L3,
        phase=WorkflowEventPhase.COMPLETED,
        message=f"L3 approval rejected by {body.approver_name.strip()}",
        metadata={"approver": body.approver_name.strip(), "remarks": body.remarks.strip()},
    )
    return release_store.to_response(updated)


@router.get("/{release_id}/rm-approval", response_model=RMApprovalRequest)
async def get_rm_approval(release_id: str) -> RMApprovalRequest:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )

    raw = state.get("rm_approval_request")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No RM approval request for release {release_id}.",
        )
    return RMApprovalRequest.model_validate(raw)


@router.get("/{release_id}/rm-approval-notification", response_model=RMApprovalNotificationDraft)
async def get_rm_approval_notification(release_id: str) -> RMApprovalNotificationDraft:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )

    notification_draft = load_rm_approval_notification_draft(release_id)
    if not notification_draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No RM approval notification draft for release {release_id}.",
        )
    return notification_draft


@router.post("/{release_id}/rm/approve", response_model=ReleaseStateResponse)
async def approve_rm_release(
    release_id: str,
    body: RMApprovalActionRequest,
    background_tasks: BackgroundTasks,
) -> ReleaseStateResponse:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    if state.get("workflow_status") != WorkflowStatus.RM_APPROVAL_PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Release is not pending RM approval.",
        )

    raw = state.get("rm_approval_request")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No RM approval request for release {release_id}.",
        )

    now = datetime.now(timezone.utc)
    approval_request = RMApprovalRequest.model_validate(raw)
    approval_comment = body.comment.strip() if body.comment and body.comment.strip() else None
    updated_request = approval_request.model_copy(
        update={
            "status": RMApprovalStatus.APPROVED,
            "approved_by": body.approver_name.strip(),
            "approver_soe_id": body.approver_soe_id.strip(),
            "approved_at": now,
            "approval_comment": approval_comment,
        }
    )

    updated = release_store.update(
        release_id,
        {
            "workflow_status": WorkflowStatus.RM_APPROVED.value,
            "rm_approval_request": updated_request.model_dump(mode="json"),
        },
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    emit_workflow_event(
        release_id,
        agent=WorkflowEventAgent.RM,
        phase=WorkflowEventPhase.COMPLETED,
        message=f"RM approval granted by {body.approver_name.strip()}",
        metadata={"approver": body.approver_name.strip()},
    )
    background_tasks.add_task(_auto_complete_deployment_after_rm_approve, release_id)
    return release_store.to_response(updated)


@router.post("/{release_id}/rm/reject", response_model=ReleaseStateResponse)
async def reject_rm_release(
    release_id: str,
    body: RMApprovalRejectRequest,
) -> ReleaseStateResponse:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    if state.get("workflow_status") != WorkflowStatus.RM_APPROVAL_PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Release is not pending RM approval.",
        )

    raw = state.get("rm_approval_request")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No RM approval request for release {release_id}.",
        )

    now = datetime.now(timezone.utc)
    approval_request = RMApprovalRequest.model_validate(raw)
    updated_request = approval_request.model_copy(
        update={
            "status": RMApprovalStatus.REJECTED,
            "approved_by": body.approver_name.strip(),
            "approver_soe_id": body.approver_soe_id.strip(),
            "approved_at": now,
            "rejection_remarks": body.remarks.strip(),
        }
    )

    updated = release_store.update(
        release_id,
        {
            "workflow_status": WorkflowStatus.RM_REJECTED.value,
            "rm_approval_request": updated_request.model_dump(mode="json"),
            "failure_reasons": [body.remarks.strip()],
        },
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    emit_workflow_event(
        release_id,
        agent=WorkflowEventAgent.RM,
        phase=WorkflowEventPhase.COMPLETED,
        message=f"RM approval rejected by {body.approver_name.strip()}",
        metadata={"approver": body.approver_name.strip(), "remarks": body.remarks.strip()},
    )
    return release_store.to_response(updated)


@router.post("/{release_id}/deployment/complete", response_model=ReleaseStateResponse)
async def complete_deployment(
    release_id: str,
    background_tasks: BackgroundTasks,
) -> ReleaseStateResponse:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    if state.get("workflow_status") == WorkflowStatus.DEPLOYMENT_COMPLETED.value:
        return release_store.to_response(state)

    if state.get("workflow_status") != WorkflowStatus.RM_APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Release is not ready for deployment completion.",
        )

    updated = release_store.update(
        release_id,
        {"workflow_status": WorkflowStatus.DEPLOYMENT_COMPLETED.value},
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )
    emit_workflow_event(
        release_id,
        agent=WorkflowEventAgent.ORCHESTRATOR,
        phase=WorkflowEventPhase.COMPLETED,
        message=f"Deployment completed on {state.get('environment', '')}",
        metadata={"environment": state.get("environment")},
    )
    background_tasks.add_task(_jira_on_deployment_completed, release_id)
    return release_store.to_response(updated)


@router.get("/{release_id}/qa-signoff-attachment")
async def download_qa_signoff_attachment(release_id: str) -> FileResponse:
    state = release_store.get(release_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Release {release_id} not found.",
        )

    attachment = state.get("qa_signoff_attachment")
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No QA sign-off attachment for this release.",
        )

    path = get_qa_signoff_attachment_path(release_id, attachment["filename"])
    return FileResponse(
        path,
        media_type=attachment.get("content_type", "application/octet-stream"),
        filename=attachment["filename"],
    )
