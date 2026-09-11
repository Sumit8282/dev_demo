import type { NewReleaseForm } from '../types/release';

const BASE = import.meta.env.VITE_API_BASE_URL ?? '';

export type BackendWorkflowStatus =
  | 'PENDING'
  | 'VALIDATING'
  | 'L3_APPROVAL_PENDING'
  | 'L3_APPROVED'
  | 'L3_REJECTED'
  | 'MERGE_PENDING'
  | 'MERGED'
  | 'MERGE_FAILED'
  | 'BUILD_PENDING'
  | 'BUILD_COMPLETED'
  | 'BUILD_FAILED'
  | 'RM_APPROVAL_PENDING'
  | 'RM_APPROVED'
  | 'RM_REJECTED'
  | 'DEPLOYMENT_COMPLETED'
  | 'HALTED'
  | 'VALIDATION_ERROR';

export interface QASignoffAttachmentInfo {
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface HighRiskFileInfo {
  filepath: string;
  failure_rate: number;
  lines_changed: number;
}

export interface ReleaseRiskScoreInfo {
  score: number;
  level: 'LOW' | 'MEDIUM' | 'HIGH';
  breakdown: {
    file_count_score?: number;
    lines_changed_score?: number;
    failure_rate_score?: number;
  };
  metrics?: {
    files_changed?: number;
    lines_added?: number;
    lines_deleted?: number;
    lines_changed?: number;
    file_count_limit?: number;
    lines_changed_limit?: number;
  };
  high_risk_files: HighRiskFileInfo[];
}

export interface L3ApprovalRequestInfo {
  release_id: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  approval_url: string;
  created_at: string;
  approved_by?: string | null;
  approver_soe_id?: string | null;
  approved_at?: string | null;
  approval_comment?: string | null;
  rejection_remarks?: string | null;
  release_branch: string;
  release_version: string;
  github_pr_url: string;
  github_pr_number: number;
  jira_url: string;
  jira_issue_key: string;
  environment: string;
  release_date: string;
  raised_by?: string | null;
  pr_title?: string | null;
  qa_signoff_required: boolean;
  has_qa_attachment: boolean;
  qa_signoff_attachment_filename?: string | null;
  risk_score?: ReleaseRiskScoreInfo | null;
}

export interface BuildResultInfo {
  build_id: string;
  status: 'PENDING' | 'COMPLETED' | 'FAILED';
  generated_at: string;
  release_version: string;
  target_environment: string;
  job_url?: string | null;
  logs_url?: string | null;
  commit_sha?: string | null;
  external_run_id?: string | null;
  failure_reason?: string | null;
  workflow_name?: string | null;
}

export interface ApprovalStatusSummaryInfo {
  github_validation?: string | null;
  jira_validation?: string | null;
  qa_validation?: string | null;
  l3_approval?: string | null;
  merge?: string | null;
  build?: string | null;
}

export interface RMApprovalRequestInfo {
  release_id: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  approval_url: string;
  approval_queue_url: string;
  created_at: string;
  approved_by?: string | null;
  approver_soe_id?: string | null;
  approved_at?: string | null;
  approval_comment?: string | null;
  rejection_remarks?: string | null;
  release_branch: string;
  release_version: string;
  github_pr_url: string;
  github_pr_number: number;
  jira_url: string;
  jira_issue_key: string;
  build_id: string;
  target_environment: string;
  deployment_window: string;
  approval_statuses: ApprovalStatusSummaryInfo;
  raised_by?: string | null;
  pr_title?: string | null;
}

export interface BackendWorkflowEvent {
  timestamp: string;
  agent: string;
  phase: string;
  message: string;
  metadata?: Record<string, unknown>;
  simulated?: boolean;
}

export interface BackendReleaseState {
  release_id: string;
  release_branch: string;
  release_version: string;
  github_pr_url: string;
  github_owner: string;
  github_repo: string;
  github_pr_number: number;
  jira_url: string;
  jira_issue_key: string;
  qa_signoff_required: boolean;
  qa_signoff_not_required_reason: string | null;
  qa_mode?: 'not_required' | 'upload' | 'pr_tests' | null;
  qa_signoff_attachment: QASignoffAttachmentInfo | null;
  environment: string;
  release_date: string;
  jira_validation?: ValidationResult | null;
  qa_validation?: ValidationResult | null;
  github_validation?: ValidationResult | null;
  overall_validation_status?: 'PASS' | 'FAIL' | 'ERROR' | null;
  workflow_status: BackendWorkflowStatus;
  failure_reasons: string[];
  github_comment_posted: boolean;
  l3_approval_request?: L3ApprovalRequestInfo | null;
  build_result?: BuildResultInfo | null;
  rm_approval_request?: RMApprovalRequestInfo | null;
  merge_result?: Record<string, unknown> | null;
  workflow_events?: BackendWorkflowEvent[];
  created_at: string;
  updated_at: string;
  created_by?: string | null;
}

interface ValidationResult {
  agent?: string;
  status?: 'PASS' | 'FAIL' | 'ERROR';
  checks?: Record<string, unknown>;
  errors?: string[];
  metadata?: Record<string, unknown>;
}

export interface CreateReleaseResponse {
  release_id: string;
  workflow_status: BackendWorkflowStatus;
  message: string;
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ');
    }
    return JSON.stringify(body);
  } catch {
    return response.statusText || `Request failed (${response.status})`;
  }
}

export function getQaSignoffAttachmentUrl(releaseId: string): string {
  return `${BASE}/api/releases/${encodeURIComponent(releaseId)}/qa-signoff-attachment`;
}

export async function createReleaseApi(
  form: NewReleaseForm,
  createdBy: string
): Promise<CreateReleaseResponse> {
  const formData = new FormData();
  formData.append('release_branch', form.releaseBranch.trim());
  formData.append('github_pr_url', form.pr.trim());
  formData.append('jira_url', form.jira.trim());
  formData.append('qa_signoff_required', form.qaSignOff === 'No' ? 'false' : 'true');
  formData.append(
    'qa_mode',
    form.qaSignOff === 'No' ? 'not_required' : form.qaSignOff === 'PrTests' ? 'pr_tests' : 'upload'
  );
  formData.append('environment', form.environment.trim());
  formData.append('release_date', form.releaseDate);
  formData.append('created_by', createdBy);

  if (form.qaSignOff === 'No' && form.qaReason.trim()) {
    formData.append('qa_signoff_not_required_reason', form.qaReason.trim());
  }

  if (form.qaSignOff === 'Upload' && form.qaSignOffAttachment) {
    formData.append('qa_signoff_attachment', form.qaSignOffAttachment);
  }

  const response = await fetch(`${BASE}/api/releases`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function getReleaseApi(releaseId: string): Promise<BackendReleaseState> {
  const response = await fetch(`${BASE}/api/releases/${encodeURIComponent(releaseId)}`);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function listReleasesApi(): Promise<BackendReleaseState[]> {
  const response = await fetch(`${BASE}/api/releases`);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function listL3ApprovalQueueApi(): Promise<BackendReleaseState[]> {
  const response = await fetch(`${BASE}/api/releases/l3-approval-queue`);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function listRmApprovalQueueApi(): Promise<BackendReleaseState[]> {
  const response = await fetch(`${BASE}/api/releases/rm-approval-queue`);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function getRmApprovalApi(releaseId: string): Promise<RMApprovalRequestInfo> {
  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/rm-approval`
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function getL3ApprovalMailApi(
  releaseId: string
): Promise<Record<string, unknown> & { approval_url: string; approval_link?: string }> {
  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/l3-approval-mail`
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function getL3ApprovalApi(releaseId: string): Promise<L3ApprovalRequestInfo> {
  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/l3-approval`
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function approveL3ReleaseApi(
  releaseId: string,
  approverName: string,
  approverSoeId: string,
  comment?: string
): Promise<BackendReleaseState> {
  const payload: Record<string, string> = {
    approver_name: approverName,
    approver_soe_id: approverSoeId,
  };
  const trimmedComment = comment?.trim();
  if (trimmedComment) {
    payload.comment = trimmedComment;
  }

  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/l3/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function rejectL3ReleaseApi(
  releaseId: string,
  approverName: string,
  approverSoeId: string,
  remarks: string
): Promise<BackendReleaseState> {
  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/l3/reject`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approver_name: approverName,
        approver_soe_id: approverSoeId,
        remarks,
      }),
    }
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function approveRmReleaseApi(
  releaseId: string,
  approverName: string,
  approverSoeId: string,
  comment?: string
): Promise<BackendReleaseState> {
  const payload: Record<string, string> = {
    approver_name: approverName,
    approver_soe_id: approverSoeId,
  };
  const trimmedComment = comment?.trim();
  if (trimmedComment) {
    payload.comment = trimmedComment;
  }

  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/rm/approve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function rejectRmReleaseApi(
  releaseId: string,
  approverName: string,
  approverSoeId: string,
  remarks: string
): Promise<BackendReleaseState> {
  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/rm/reject`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approver_name: approverName,
        approver_soe_id: approverSoeId,
        remarks,
      }),
    }
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export async function completeDeploymentApi(releaseId: string): Promise<BackendReleaseState> {
  const response = await fetch(
    `${BASE}/api/releases/${encodeURIComponent(releaseId)}/deployment/complete`,
    { method: 'POST' }
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return response.json();
}

export const TERMINAL_WORKFLOW_STATUSES: ReadonlySet<BackendWorkflowStatus> = new Set([
  'L3_APPROVAL_PENDING',
  'L3_REJECTED',
  'RM_APPROVAL_PENDING',
  'RM_APPROVED',
  'RM_REJECTED',
  'DEPLOYMENT_COMPLETED',
  'MERGE_FAILED',
  'BUILD_FAILED',
  'HALTED',
  'VALIDATION_ERROR',
]);

export const BACKEND_POST_MERGE_STATUSES: ReadonlySet<BackendWorkflowStatus> = new Set([
  'MERGED',
  'BUILD_PENDING',
  'BUILD_COMPLETED',
  'BUILD_FAILED',
  'RM_APPROVAL_PENDING',
  'RM_APPROVED',
  'RM_REJECTED',
  'DEPLOYMENT_COMPLETED',
]);
