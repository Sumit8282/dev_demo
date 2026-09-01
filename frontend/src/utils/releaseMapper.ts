import type { BackendReleaseState } from '../api/releases';
import { BACKEND_POST_MERGE_STATUSES } from '../api/releases';
import type { Release, StatusType, WorkflowActivity, WorkflowStep } from '../types/release';
import type { WorkflowEvent } from '../types/workflowEvent';
import { formatDate, formatTime } from './helpers';
import { formatJiraValidationRemarks } from './jiraValidationMessages';

let activityCounter = 0;
let workflowEventCounter = 0;

export function mapBackendWorkflowEvents(
  events: BackendReleaseState['workflow_events']
): WorkflowEvent[] {
  return (events ?? []).map((event, index) => ({
    id: `backend-${index}-${event.timestamp}`,
    timestamp: event.timestamp,
    agent: event.agent,
    phase: event.phase,
    message: event.message,
    metadata: event.metadata,
    simulated: event.simulated ?? false,
  }));
}

export function createLocalWorkflowEvent(
  partial: Omit<WorkflowEvent, 'id' | 'simulated'> & { simulated?: boolean }
): WorkflowEvent {
  workflowEventCounter += 1;
  return {
    id: `local-${workflowEventCounter}`,
    simulated: true,
    ...partial,
  };
}

export function mergeWorkflowEvents(
  backendEvents: WorkflowEvent[],
  localEvents: WorkflowEvent[]
): WorkflowEvent[] {
  const backendKeys = new Set(
    backendEvents.map((event) => `${event.timestamp}|${event.message}`)
  );
  const merged = [...backendEvents];
  for (const event of localEvents) {
    const key = `${event.timestamp}|${event.message}`;
    if (!backendKeys.has(key)) {
      merged.push(event);
    }
  }
  return merged.sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );
}

function nextActivityId(): string {
  activityCounter += 1;
  return `act-${activityCounter}`;
}

function validationToStatus(status?: string | null, pendingStatus: StatusType = 'Pending'): StatusType {
  if (!status) return pendingStatus;
  if (status === 'PASS') return 'Completed';
  if (status === 'FAIL') return 'Rejected';
  return 'Failed';
}

function formatBackendDate(iso: string): string {
  try {
    return formatDate(new Date(iso));
  } catch {
    return iso;
  }
}

function formatBackendTime(iso: string): string {
  try {
    return formatTime(new Date(iso));
  } catch {
    return '-';
  }
}

function formatGithubRemarks(
  validation: BackendReleaseState['github_validation']
): string {
  if (!validation) return '-';
  if (validation.errors?.length) return validation.errors.join('; ');
  if (validation.status === 'PASS') return 'GitHub PR validated';
  if (validation.status === 'FAIL') return validation.errors?.join('; ') || 'GitHub PR validation failed';
  return 'GitHub PR validation error';
}

function mergeFailureRemarks(state: BackendReleaseState): string {
  const mergeResult = state.merge_result as { errors?: string[]; failure_summary?: string } | null | undefined;
  if (mergeResult?.failure_summary) return mergeResult.failure_summary;
  if (mergeResult?.errors?.length) return mergeResult.errors.join('; ');
  if (state.failure_reasons?.length) return state.failure_reasons.join('; ');
  return 'Auto merge failed';
}

const AI_TEAM = 'AI';

function appendL3ApprovedActivity(
  activities: WorkflowActivity[],
  state: BackendReleaseState,
  srNo: number
): number {
  const l3 = state.l3_approval_request;
  activities.push({
    id: nextActivityId(),
    srNo: srNo++,
    name: l3?.approved_by ?? '',
    soeId: l3?.approver_soe_id ?? '',
    team: 'L3',
    activity: 'Approved Release',
    status: 'Completed',
    time: l3?.approved_at ? formatBackendTime(l3.approved_at) : formatBackendTime(state.updated_at),
    remarks: 'Approved',
  });
  return srNo;
}

function appendPostMergeActivities(
  activities: WorkflowActivity[],
  state: BackendReleaseState,
  srNo: number
): number {
  const buildResult = state.build_result;
  const buildId = buildResult?.build_id ?? '';
  const rm = state.rm_approval_request;
  const postMergeStatuses = BACKEND_POST_MERGE_STATUSES;

  if (!postMergeStatuses.has(state.workflow_status)) {
    return srNo;
  }

  if (state.workflow_status === 'MERGED' || state.workflow_status === 'BUILD_PENDING') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'CI/CD',
      soeId: '',
      team: 'CI/CD',
      activity: 'Generating Build',
      status: 'Running',
      time: formatBackendTime(state.updated_at),
      remarks: buildResult?.job_url
        ? buildResult.job_url
        : state.workflow_status === 'MERGED'
          ? 'Build starting after merge'
          : 'Build generation in progress',
    });
    return srNo;
  }

  if (state.workflow_status === 'BUILD_FAILED') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'CI/CD',
      soeId: '',
      team: 'CI/CD',
      activity: 'Generating Build',
      status: 'Failed',
      time: buildResult?.generated_at
        ? formatBackendTime(buildResult.generated_at)
        : formatBackendTime(state.updated_at),
      remarks: buildResult?.failure_reason || buildId || 'CI/CD pipeline failed',
    });
    return srNo;
  }

  if (
    state.workflow_status === 'BUILD_COMPLETED' ||
    state.workflow_status === 'RM_APPROVAL_PENDING' ||
    state.workflow_status === 'RM_APPROVED' ||
    state.workflow_status === 'RM_REJECTED' ||
    state.workflow_status === 'DEPLOYMENT_COMPLETED'
  ) {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'CI/CD',
      soeId: '',
      team: 'CI/CD',
      activity: 'Generating Build',
      status: 'Completed',
      time: buildResult?.generated_at
        ? formatBackendTime(buildResult.generated_at)
        : formatBackendTime(state.updated_at),
      remarks: buildResult?.job_url || buildId || 'Build generated',
    });
  }

  if (state.workflow_status === 'RM_APPROVAL_PENDING') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: '',
      soeId: '',
      team: 'RM',
      activity: 'Waiting for RM Approval',
      status: 'Pending',
      time: '-',
      remarks: buildId || '-',
    });
    return srNo;
  }

  if (state.workflow_status === 'RM_APPROVED') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: rm?.approved_by ?? '',
      soeId: rm?.approver_soe_id ?? '',
      team: 'RM',
      activity: 'RM Approved Release',
      status: 'Completed',
      time: rm?.approved_at ? formatBackendTime(rm.approved_at) : formatBackendTime(state.updated_at),
      remarks: rm?.approval_comment ?? 'Approved',
    });
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: '',
      soeId: '',
      team: 'RM',
      activity: 'Deployment of Build',
      status: 'Pending',
      time: '-',
      remarks: '-',
    });
    return srNo;
  }

  if (state.workflow_status === 'DEPLOYMENT_COMPLETED') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: rm?.approved_by ?? '',
      soeId: rm?.approver_soe_id ?? '',
      team: 'RM',
      activity: 'RM Approved Release',
      status: 'Completed',
      time: rm?.approved_at ? formatBackendTime(rm.approved_at) : formatBackendTime(state.updated_at),
      remarks: rm?.approval_comment ?? 'Approved',
    });
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: rm?.approved_by ?? '',
      soeId: rm?.approver_soe_id ?? '',
      team: 'RM',
      activity: 'Deployment of Build',
      status: 'Completed',
      time: formatBackendTime(state.updated_at),
      remarks: 'Deployment completed',
    });
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'Agent',
      soeId: '',
      team: AI_TEAM,
      activity: `Deployment Completed on ${state.environment}`,
      status: 'Completed',
      time: formatBackendTime(state.updated_at),
      remarks: 'Deployment Successful',
    });
    return srNo;
  }

  if (state.workflow_status === 'RM_REJECTED') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: rm?.approved_by ?? '',
      soeId: rm?.approver_soe_id ?? '',
      team: 'RM',
      activity: 'RM Rejected Release',
      status: 'Rejected',
      time: rm?.approved_at ? formatBackendTime(rm.approved_at) : formatBackendTime(state.updated_at),
      remarks: rm?.rejection_remarks ?? state.failure_reasons.join('; ') ?? 'Rejected',
    });
  }

  return srNo;
}

function buildWorkflowActivities(state: BackendReleaseState, createdBy: string): WorkflowActivity[] {
  const activities: WorkflowActivity[] = [];
  let srNo = 1;

  activities.push({
    id: nextActivityId(),
    srNo: srNo++,
    name: createdBy,
    soeId: '',
    team: 'DEV',
    activity: 'PR Request Raised',
    status: 'Completed',
    time: formatBackendTime(state.created_at),
    remarks: 'PR Submitted',
  });

  const githubStatus = state.github_validation?.status;
  const jiraStatus = state.jira_validation?.status;
  const qaStatus = state.qa_validation?.status;
  const isValidating = state.workflow_status === 'VALIDATING';

  activities.push({
    id: nextActivityId(),
    srNo: srNo++,
    name: 'Agent',
    soeId: '',
    team: AI_TEAM,
    activity: 'GitHub PR Validation',
    status: githubStatus
      ? validationToStatus(githubStatus)
      : isValidating
        ? 'Running'
        : 'Pending',
    time: githubStatus ? formatBackendTime(state.updated_at) : '-',
    remarks: githubStatus
      ? formatGithubRemarks(state.github_validation)
      : '-',
  });

  activities.push({
    id: nextActivityId(),
    srNo: srNo++,
    name: 'Agent',
    soeId: '',
    team: AI_TEAM,
    activity: 'Jira Validation',
    status: jiraStatus
      ? validationToStatus(jiraStatus)
      : githubStatus && isValidating
        ? 'Pending'
        : isValidating
          ? 'Running'
          : 'Pending',
    time: jiraStatus ? formatBackendTime(state.updated_at) : '-',
    remarks: jiraStatus
      ? formatJiraValidationRemarks(state.jira_validation, state.jira_issue_key)
      : '-',
  });

  activities.push({
    id: nextActivityId(),
    srNo: srNo++,
    name: 'Agent',
    soeId: '',
    team: AI_TEAM,
    activity: 'QA Validation',
    status: qaStatus
      ? validationToStatus(qaStatus)
      : jiraStatus && isValidating
        ? 'Running'
        : 'Pending',
    time: qaStatus ? formatBackendTime(state.updated_at) : '-',
    remarks: qaStatus
      ? state.qa_validation?.errors?.join('; ') || 'Validation complete'
      : '-',
  });

  if (state.workflow_status === 'L3_APPROVAL_PENDING') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: '',
      soeId: '',
      team: 'L3',
      activity: 'Waiting for Approval',
      status: 'Pending',
      time: '-',
      remarks: 'Sent to L3',
    });
  }

  if (
    state.workflow_status === 'L3_APPROVED' ||
    state.workflow_status === 'MERGE_PENDING' ||
    state.workflow_status === 'MERGED' ||
    state.workflow_status === 'MERGE_FAILED'
  ) {
    srNo = appendL3ApprovedActivity(activities, state, srNo);
  }

  if (state.workflow_status === 'L3_APPROVED' || state.workflow_status === 'MERGE_PENDING') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'Agent',
      soeId: '',
      team: 'CI/CD',
      activity: 'Waiting for Merge',
      status: state.workflow_status === 'MERGE_PENDING' ? 'Running' : 'Pending',
      time: state.workflow_status === 'MERGE_PENDING' ? formatBackendTime(state.updated_at) : '-',
      remarks: state.workflow_status === 'MERGE_PENDING' ? 'Auto-merge in progress' : '-',
    });
  }

  if (state.workflow_status === 'MERGED') {
    const mergeResult = state.merge_result as {
      merge_sha?: string | null;
      merge_method?: string | null;
      merged_at?: string | null;
    } | null | undefined;
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'Agent',
      soeId: '',
      team: 'CI/CD',
      activity: 'Waiting for Merge',
      status: 'Completed',
      time: mergeResult?.merged_at ? formatBackendTime(mergeResult.merged_at) : formatBackendTime(state.updated_at),
      remarks: mergeResult?.merge_sha
        ? `Merged (${mergeResult.merge_sha.slice(0, 7)})`
        : 'Auto merge completed',
    });
    srNo = appendPostMergeActivities(activities, state, srNo);
  } else if (BACKEND_POST_MERGE_STATUSES.has(state.workflow_status)) {
    const mergeResult = state.merge_result as {
      merge_sha?: string | null;
      merged_at?: string | null;
    } | null | undefined;
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'Agent',
      soeId: '',
      team: 'CI/CD',
      activity: 'Waiting for Merge',
      status: 'Completed',
      time: mergeResult?.merged_at ? formatBackendTime(mergeResult.merged_at) : formatBackendTime(state.updated_at),
      remarks: mergeResult?.merge_sha
        ? `Merged (${mergeResult.merge_sha.slice(0, 7)})`
        : 'Auto merge completed',
    });
    srNo = appendPostMergeActivities(activities, state, srNo);
  }

  if (state.workflow_status === 'MERGE_FAILED') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'Agent',
      soeId: '',
      team: 'CI/CD',
      activity: 'Waiting for Merge',
      status: 'Failed',
      time: formatBackendTime(state.updated_at),
      remarks: mergeFailureRemarks(state),
    });
  }

  if (state.workflow_status === 'L3_REJECTED') {
    const l3 = state.l3_approval_request;
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: l3?.approved_by ?? '',
      soeId: l3?.approver_soe_id ?? '',
      team: 'L3',
      activity: 'Rejected Release',
      status: 'Rejected',
      time: l3?.approved_at ? formatBackendTime(l3.approved_at) : formatBackendTime(state.updated_at),
      remarks: l3?.rejection_remarks ?? state.failure_reasons.join('; ') ?? 'Rejected',
    });
  }

  if (state.workflow_status === 'HALTED' || state.workflow_status === 'VALIDATION_ERROR') {
    activities.push({
      id: nextActivityId(),
      srNo: srNo++,
      name: 'Agent',
      soeId: '',
      team: AI_TEAM,
      activity: 'Validation Failed',
      status: state.workflow_status === 'VALIDATION_ERROR' ? 'Failed' : 'Rejected',
      time: formatBackendTime(state.updated_at),
      remarks: state.failure_reasons.join('; ') || 'Validation failed',
    });
  }

  return activities;
}

function mapWorkflowStatus(state: BackendReleaseState): {
  status: string;
  currentStage: WorkflowStep;
} {
  switch (state.workflow_status) {
    case 'VALIDATING':
      return { status: 'Validating', currentStage: 'PR Raised' };
    case 'L3_APPROVAL_PENDING':
      return { status: 'PR Request Raised', currentStage: 'L3 Approval Pending' };
    case 'L3_APPROVED':
      return { status: 'Approved', currentStage: 'Waiting for Merge' };
    case 'MERGE_PENDING':
      return { status: 'Approved', currentStage: 'Waiting for Merge' };
    case 'MERGED':
      return { status: 'Approved', currentStage: 'Generating Build' };
    case 'BUILD_PENDING':
      return { status: 'Approved', currentStage: 'Generating Build' };
    case 'BUILD_COMPLETED':
      return { status: 'Approved', currentStage: 'Generating Build' };
    case 'BUILD_FAILED':
      return { status: 'Failed', currentStage: 'Generating Build' };
    case 'RM_APPROVAL_PENDING':
      return { status: 'PR Request Raised', currentStage: 'RM Approval Pending' };
    case 'RM_APPROVED':
      return { status: 'RM Approved', currentStage: 'Deployment' };
    case 'DEPLOYMENT_COMPLETED':
      return { status: 'Completed', currentStage: 'Completed' };
    case 'RM_REJECTED':
      return { status: 'Rejected', currentStage: 'RM Approval' };
    case 'MERGE_FAILED':
      return { status: 'Failed', currentStage: 'Waiting for Merge' };
    case 'L3_REJECTED':
      return { status: 'Rejected', currentStage: 'L3 Approval' };
    case 'HALTED':
      return { status: 'Rejected', currentStage: 'L3 Approval' };
    case 'VALIDATION_ERROR':
      return { status: 'Failed', currentStage: 'QA Validation' };
    default:
      return { status: state.workflow_status, currentStage: 'PR Raised' };
  }
}

export function mapBackendToRelease(
  state: BackendReleaseState,
  createdByFallback = 'Release Portal'
): Release {
  const { status, currentStage } = mapWorkflowStatus(state);
  const createdBy = state.created_by?.trim() || createdByFallback;

  return {
    id: state.release_id,
    releaseBranch: state.release_branch,
    pr: state.github_pr_url,
    jira: state.jira_url,
    qaSignOff: state.qa_signoff_required ? 'Yes' : 'No',
    qaReason: state.qa_signoff_not_required_reason ?? '',
    qaSignOffAttachmentName: state.qa_signoff_attachment?.filename ?? '',
    environment: state.environment,
    releaseDate: state.release_date,
    status,
    currentStage,
    createdBy,
    createdDate: formatBackendDate(state.created_at),
    buildId: state.build_result?.build_id ?? '',
    deploymentStatus:
      state.workflow_status === 'DEPLOYMENT_COMPLETED'
        ? 'Deployment Successful'
        : state.workflow_status === 'RM_APPROVED'
          ? 'Pending'
          : '-',
    workflowActivities: buildWorkflowActivities(state, createdBy),
    workflowEvents: mapBackendWorkflowEvents(state.workflow_events),
    backendWorkflowStatus: state.workflow_status,
    githubValidationStatus: state.github_validation?.status ?? null,
    jiraValidationStatus: state.jira_validation?.status ?? null,
    qaValidationStatus: state.qa_validation?.status ?? null,
    jiraValidationErrors: state.jira_validation?.errors ?? [],
    qaValidationErrors: state.qa_validation?.errors ?? [],
  };
}

function hasBackendMergeEvents(state: BackendReleaseState): boolean {
  return (state.workflow_events ?? []).some((event) => event.agent === 'merge');
}

function isBackendMergeLifecycle(state: BackendReleaseState): boolean {
  return (
    state.workflow_status === 'L3_APPROVED' ||
    state.workflow_status === 'MERGE_PENDING' ||
    state.workflow_status === 'MERGED' ||
    state.workflow_status === 'MERGE_FAILED' ||
    BACKEND_POST_MERGE_STATUSES.has(state.workflow_status) ||
    hasBackendMergeEvents(state)
  );
}

function isBackendPostMergeLifecycle(state: BackendReleaseState): boolean {
  return BACKEND_POST_MERGE_STATUSES.has(state.workflow_status);
}

/** Merge backend validation state into an existing release (preserves local approval steps). */
export function mergeBackendState(existing: Release, state: BackendReleaseState): Release {
  const backendMapped = mapBackendToRelease(state, existing.createdBy);

  if (isBackendPostMergeLifecycle(state)) {
    return {
      ...backendMapped,
      workflowEvents: mergeWorkflowEvents(
        backendMapped.workflowEvents,
        existing.workflowEvents.filter((event) => event.simulated)
      ),
    };
  }

  if (isBackendMergeLifecycle(state)) {
    return {
      ...backendMapped,
      workflowEvents: mergeWorkflowEvents(
        backendMapped.workflowEvents,
        existing.workflowEvents.filter((event) => event.simulated && event.agent !== 'merge')
      ),
    };
  }

  const hasLocalPostApprovalSteps = existing.workflowActivities.some(
    (a) =>
      a.activity === 'Waiting for Merge' ||
      a.activity === 'Generating Build' ||
      a.activity === 'Waiting for RM Approval' ||
      a.activity === 'Deployment of Build'
  );

  if ((hasLocalPostApprovalSteps || existing.status === 'RM Approved') && !isBackendPostMergeLifecycle(state)) {
    return existing;
  }

  if (
    existing.workflowActivities.some(
      (a) => a.activity === 'Waiting for Approval' && a.status === 'Pending'
    ) &&
    backendMapped.workflowActivities.some(
      (a) => a.activity === 'Approved Release' || a.activity === 'Rejected Release'
    )
  ) {
    return backendMapped;
  }

  if (
    state.workflow_status === 'L3_APPROVED' &&
    existing.status !== 'Approved' &&
    existing.status !== 'Completed'
  ) {
    return backendMapped;
  }

  return {
    ...backendMapped,
    createdBy: state.created_by?.trim() || existing.createdBy,
    workflowEvents: mergeWorkflowEvents(
      backendMapped.workflowEvents,
      existing.workflowEvents.filter((event) => event.simulated)
    ),
  };
}
