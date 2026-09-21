import type { BackendReleaseState } from '../api/releases';
import { BACKEND_POST_MERGE_STATUSES } from '../api/releases';
import type { QaCoverageRow, QaGapReviewUpdate, QaGeneratedTestRow, Release, StatusType, WorkflowActivity, WorkflowStep } from '../types/release';
import type { WorkflowEvent } from '../types/workflowEvent';
import { mapGithubIssuesFromState, isGithubIssuesQa } from './githubIssueLinks';
import { buildFailureNextActions } from './buildFailureGuidance';
import { formatDate, formatTime } from './helpers';
import { formatJiraValidationRemarks } from './jiraValidationMessages';
import { inferValidationFromEvents } from './workflowProgress';

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

function formatGithubIssuesScopeRemarks(state: BackendReleaseState): string {
  const labels = mapGithubIssuesFromState(state).map((issue) => issue.label);
  if (labels.length) {
    return `GitHub issues ${labels.join(', ')}`;
  }
  return 'GitHub issues used for scope (no Jira ticket)';
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

  // Validation results are only persisted when the orchestrator run finishes, so fall back to the
  // completed events to keep this table in step with the agent activity feed.
  const inferred = inferValidationFromEvents(state.workflow_events ?? []);
  const githubStatus = state.github_validation?.status ?? inferred.github ?? undefined;
  const jiraStatus = state.jira_validation?.status ?? inferred.jira ?? undefined;
  const qaStatus = state.qa_validation?.status ?? inferred.qa ?? undefined;
  const isValidating = state.workflow_status === 'VALIDATING';
  const skipJira = isGithubIssuesQa(state.qa_mode);

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
    activity: skipJira ? 'Scope Agent (GitHub)' : 'Scope Agent (Jira)',
    status: skipJira
      ? githubStatus
        ? validationToStatus(githubStatus)
        : isValidating
          ? 'Running'
          : 'Pending'
      : jiraStatus
        ? validationToStatus(jiraStatus)
        : githubStatus && isValidating
          ? 'Pending'
          : isValidating
            ? 'Running'
            : 'Pending',
    time: skipJira
      ? githubStatus
        ? formatBackendTime(state.updated_at)
        : '-'
      : jiraStatus
        ? formatBackendTime(state.updated_at)
        : '-',
    remarks: skipJira
      ? githubStatus === 'PASS'
        ? formatGithubIssuesScopeRemarks(state)
        : githubStatus
          ? formatGithubRemarks(state.github_validation)
          : '-'
      : jiraStatus
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
      : (jiraStatus || (skipJira && githubStatus === 'PASS')) && isValidating
        ? 'Running'
        : 'Pending',
    time: qaStatus ? formatBackendTime(state.updated_at) : '-',
    remarks: qaStatus
      ? state.qa_validation?.errors?.join('; ') ||
        (skipJira ? 'QA Validation is completed' : 'Validation complete')
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

function qaMethodLabel(state: BackendReleaseState): string {
  const mode = state.qa_mode;
  if (mode === 'pr_tests') return 'Live Jira + GitHub evidence';
  if (mode === 'github_issues') return 'Live GitHub issues + evidence';
  if (mode === 'upload') return 'Upload document';
  if (mode === 'not_required' || !state.qa_signoff_required) return 'No';
  return state.qa_signoff_required ? 'Yes' : 'No';
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function mapQaGapReviewUpdates(state: BackendReleaseState): {
  notes: string;
  updates: QaGapReviewUpdate[];
} {
  const qaMeta = asRecord(state.qa_validation?.metadata);
  const audit = asRecord(qaMeta?.gap_review);
  const notes = String(audit?.notes ?? '').trim();
  const raw = audit?.updates;
  if (!Array.isArray(raw)) {
    return { notes, updates: [] };
  }
  const updates = raw.flatMap((item) => {
    const row = asRecord(item);
    if (!row) return [];
    return [
      {
        acId: String(row.ac_id ?? '').trim(),
        changed: Boolean(row.changed),
        beforeCoverage: String(row.before_coverage ?? '').trim(),
        afterCoverage: String(row.after_coverage ?? '').trim(),
        beforeTestCases: String(row.before_test_cases ?? '').trim(),
        afterTestCases: String(row.after_test_cases ?? '').trim(),
      },
    ];
  });
  return { notes, updates };
}

export function mapQaCoverageRows(state: BackendReleaseState): QaCoverageRow[] {
  const qaMeta = asRecord(state.qa_validation?.metadata);
  const githubMeta = asRecord(state.github_validation?.metadata);
  const raw = qaMeta?.coverage_matrix;
  if (!Array.isArray(raw)) return [];
  const source = formatQaSource(state.qa_mode, qaMeta);
  const implementationFiles = collectImplementationFiles(githubMeta);
  return raw.flatMap((item) => {
    const row = asRecord(item);
    if (!row) return [];
    const acId = String(row.ac_id ?? '').trim();
    const criterion = String(row.acceptance_criterion ?? '').trim();
    if (!acId && !criterion) return [];
    const testCases = String(row.test_cases ?? '').trim();
    const coverage = String(row.coverage ?? '').trim();
    const testResult = String(row.test_result ?? '').trim();
    const reason = String(row.evidence_reason ?? '').trim();
    return [
      {
        acId,
        source,
        criterion,
        coverage: formatQaCoverage(coverage, testResult, testCases, qaMeta),
        implementation: formatQaImplementation(criterion, implementationFiles),
        reason: reason || '-',
      },
    ];
  });
}

function formatQaSource(
  qaMode: BackendReleaseState['qa_mode'],
  qaMeta: Record<string, unknown> | null
): string {
  if (qaMode === 'upload') return 'jira+qa_document';
  if (qaMode === 'pr_tests') return 'jira+github';
  if (qaMode === 'github_issues') return 'github_issues+github';
  const acSource = String(qaMeta?.ac_source ?? '').trim();
  if (acSource) return `jira+${acSource}`;
  return 'jira';
}

function formatQaCoverage(
  coverage: string,
  testResult: string,
  testCases: string,
  qaMeta: Record<string, unknown> | null
): string {
  const label = coverage.toLowerCase();
  const result = testResult.toLowerCase();
  let status = coverage || '-';
  if (label === 'fully covered') status = 'COVERED';
  else if (label === 'partially covered') status = 'PARTIAL';
  else if (label === 'covered but failed') {
    status = result.includes('fail')
      ? 'INSUFFICIENT — generated test failed'
      : 'INSUFFICIENT — test failed';
  } else if (label === 'unable to determine') status = 'INSUFFICIENT — unable to determine';
  else if (label === 'not covered') status = 'INSUFFICIENT — not covered';

  const documentDetail = testCases
    ? testCases
    : qaMeta?.testing_writeup_used === true
      ? 'PR Testing write-up'
      : '';
  return documentDetail ? `${status} (${documentDetail})` : status;
}

function collectImplementationFiles(githubMeta: Record<string, unknown> | null): string[] {
  const files = githubMeta?.changed_files;
  if (!Array.isArray(files)) return asStringList(githubMeta?.changed_file_names).filter((name) => !isLikelyTestFile(name));
  return files.flatMap((item) => {
    const row = asRecord(item);
    const name = String(row?.filename ?? row?.path ?? '').trim();
    if (!name || isLikelyTestFile(name)) return [];
    return [name];
  });
}

function formatQaImplementation(criterion: string, files: string[]): string {
  if (!files.length) return 'NOT ALIGNED';
  const tokens = criterion
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length > 3);
  const ranked = files
    .map((file) => {
      const lowered = file.toLowerCase();
      const score = tokens.reduce((total, token) => (lowered.includes(token) ? total + 1 : total), 0);
      return { file, score };
    })
    .sort((left, right) => right.score - left.score || left.file.localeCompare(right.file));
  const best = ranked[0];
  if (best && best.score > 0) return `ALIGNED (${best.file})`;
  if (files.length === 1) return `ALIGNED (${files[0]})`;
  return `REVIEW (${files.slice(0, 2).join(', ')})`;
}

function isLikelyTestFile(filename: string): boolean {
  const path = filename.replace(/\\/g, '/').toLowerCase();
  return (
    path.includes('/test/') ||
    path.includes('/tests/') ||
    path.includes('/__tests__/') ||
    path.includes('test_') ||
    path.includes('_test.') ||
    path.includes('.spec.') ||
    path.includes('.test.')
  );
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter(Boolean);
}

export function mapQaGeneratedTests(state: BackendReleaseState): QaGeneratedTestRow[] {
  const metadata = asRecord(state.qa_validation?.metadata);
  const raw = metadata?.generated_tests;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    const row = asRecord(item);
    if (!row) return [];
    const acId = String(row.ac_id ?? '').trim();
    if (!acId) return [];
    const status = String(row.status ?? 'FAIL').trim().toUpperCase() === 'PASS' ? 'PASS' : 'FAIL';
    return [
      {
        acId,
        generatedTest: String(row.generated_test ?? '').trim() || '-',
        testFile: String(row.test_file ?? '').trim() || '-',
        summary: String(row.summary ?? '').trim() || '-',
        reason: String(row.reason ?? '').trim() || '-',
        status,
      },
    ];
  });
}

function mapQaCoveragePercent(state: BackendReleaseState): number | null {
  const metadata = asRecord(state.qa_validation?.metadata);
  const value = metadata?.acceptance_criteria_coverage_percent;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function mapBackendToRelease(
  state: BackendReleaseState,
  createdByFallback = 'Release Portal'
): Release {
  const { status, currentStage } = mapWorkflowStatus(state);
  const createdBy = state.created_by?.trim() || createdByFallback;
  const gapReview = mapQaGapReviewUpdates(state);

  return {
    id: state.release_id,
    releaseBranch: state.release_branch,
    pr: state.github_pr_url,
    jira: state.jira_url,
    githubIssues: mapGithubIssuesFromState(state),
    qaSignOff: qaMethodLabel(state),
    qaReason: state.qa_signoff_not_required_reason ?? '',
    qaSignOffAttachmentName: state.qa_signoff_attachment?.filename ?? '',
    qaMode: state.qa_mode ?? '',
    environment: state.environment,
    releaseDate: state.release_date,
    status,
    currentStage,
    createdBy,
    createdDate: formatBackendDate(state.created_at),
    buildId: state.build_result?.build_id ?? '',
    buildFailureReason:
      state.workflow_status === 'BUILD_FAILED'
        ? state.build_result?.failure_reason ||
          state.failure_reasons?.[0] ||
          'CI/CD pipeline failed'
        : undefined,
    buildJobUrl:
      state.workflow_status === 'BUILD_FAILED'
        ? state.build_result?.job_url ?? undefined
        : undefined,
    buildNextActions:
      state.workflow_status === 'BUILD_FAILED'
        ? buildFailureNextActions(
            state.build_result?.failure_reason ||
              state.failure_reasons?.[0] ||
              'CI/CD pipeline failed',
            state.build_result?.job_url
          )
        : undefined,
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
    qaCoverageRows: mapQaCoverageRows(state),
    qaCoveragePercent: mapQaCoveragePercent(state),
    qaGapReviewUpdates: gapReview.updates,
    qaGapReviewNotes: gapReview.notes,
    qaGeneratedTests: mapQaGeneratedTests(state),
    qaGeneratedTestsRepo: String(asRecord(state.qa_validation?.metadata)?.generated_tests_repo ?? '').trim(),
    qaGeneratedTestsSha: String(asRecord(state.qa_validation?.metadata)?.generated_tests_sha ?? '').trim(),
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
