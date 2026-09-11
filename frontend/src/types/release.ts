import type { BackendWorkflowStatus } from '../api/releases';
import type { WorkflowEvent } from './workflowEvent';

export type StatusType = 'Pending' | 'Running' | 'Completed' | 'Rejected' | 'Failed';

export type ValidationStatus = 'PASS' | 'FAIL' | 'ERROR';

export type ApprovalType = 'L3' | 'RM';

export type WorkflowStep =
  | 'PR Raised'
  | 'Jira Validation'
  | 'QA Validation'
  | 'L3 Approval'
  | 'L3 Approval Pending'
  | 'Waiting for Merge'
  | 'Generating Build'
  | 'RM Approval'
  | 'RM Approval Pending'
  | 'Deployment'
  | 'Completed';

export interface WorkflowActivity {
  id: string;
  srNo: number;
  name: string;
  soeId: string;
  team: string;
  activity: string;
  status: StatusType;
  time: string;
  remarks: string;
}

export interface QaCoverageRow {
  acId: string;
  source: string;
  criterion: string;
  coverage: string;
  implementation: string;
  reason: string;
}

export interface QaGeneratedTestRow {
  acId: string;
  generatedTest: string;
  testFile: string;
  summary: string;
  reason: string;
  status: 'PASS' | 'FAIL';
}

export interface Release {
  id: string;
  releaseBranch: string;
  pr: string;
  jira: string;
  qaSignOff: string;
  qaReason: string;
  qaSignOffAttachmentName: string;
  qaMode?: string;
  environment: string;
  releaseDate: string;
  status: string;
  currentStage: WorkflowStep;
  createdBy: string;
  createdDate: string;
  buildId: string;
  deploymentStatus: string;
  workflowActivities: WorkflowActivity[];
  workflowEvents: WorkflowEvent[];
  backendWorkflowStatus?: BackendWorkflowStatus;
  githubValidationStatus?: ValidationStatus | null;
  jiraValidationStatus?: ValidationStatus | null;
  qaValidationStatus?: ValidationStatus | null;
  jiraValidationErrors?: string[];
  qaValidationErrors?: string[];
  qaCoverageRows?: QaCoverageRow[];
  qaCoveragePercent?: number | null;
  qaGeneratedTests?: QaGeneratedTestRow[];
  qaGeneratedTestsRepo?: string;
  qaGeneratedTestsSha?: string;
}

export interface NewReleaseForm {
  releaseBranch: string;
  pr: string;
  jira: string;
  qaSignOff: string;
  qaReason: string;
  qaSignOffAttachment: File | null;
  environment: string;
  releaseDate: string;
}

export type QaValidationChoice = 'No' | 'Upload' | 'PrTests';

export const QA_SIGNOFF_ALLOWED_EXTENSIONS = [
  '.docx',
  '.json',
] as const;
