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

export interface Release {
  id: string;
  releaseBranch: string;
  pr: string;
  jira: string;
  qaSignOff: string;
  qaReason: string;
  qaSignOffAttachmentName: string;
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

export const QA_SIGNOFF_ALLOWED_EXTENSIONS = [
  '.docx',
  '.json',
] as const;
