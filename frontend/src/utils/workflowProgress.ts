import type { BackendWorkflowStatus } from '../api/releases';
import type { WorkflowEvent } from '../types/workflowEvent';
import type { WorkflowStep } from '../types/release';

export const WORKFLOW_STEPS: WorkflowStep[] = [
  'PR Raised',
  'Jira Validation',
  'QA Validation',
  'L3 Approval',
  'Waiting for Merge',
  'Generating Build',
  'RM Approval',
  'Deployment',
  'Completed',
];

type ValidationOutcome = 'PASS' | 'FAIL' | 'ERROR' | null;

export interface ValidationProgress {
  completedCount: number;
  currentIndex: number;
  failedIndex: number | null;
}

export interface StepVisualState {
  completed: boolean;
  current: boolean;
  failed: boolean;
  rejected: boolean;
}

function normalizeStatus(status?: string | null): ValidationOutcome {
  if (status === 'PASS' || status === 'FAIL' || status === 'ERROR') {
    return status;
  }
  return null;
}

function inferValidationFromEvents(events: WorkflowEvent[]): {
  github: ValidationOutcome;
  jira: ValidationOutcome;
  qa: ValidationOutcome;
} {
  let github: ValidationOutcome = null;
  let jira: ValidationOutcome = null;
  let qa: ValidationOutcome = null;

  for (const event of events) {
    const message = event.message;
    if (message.includes('GitHub PR validation completed')) {
      github = message.includes('PASS') ? 'PASS' : 'FAIL';
    }
    if (message.includes('Jira validation completed')) {
      jira = message.includes('PASS') ? 'PASS' : 'FAIL';
    }
    if (message.includes('QA sign-off validation completed')) {
      qa = message.includes('PASS') ? 'PASS' : 'FAIL';
    }
  }

  return { github, jira, qa };
}

function mergeValidationStatus(
  backendStatus: ValidationOutcome,
  eventStatus: ValidationOutcome
): ValidationOutcome {
  return backendStatus ?? eventStatus;
}

export function computeValidationProgress(
  githubStatus?: string | null,
  jiraStatus?: string | null,
  qaStatus?: string | null,
  workflowEvents: WorkflowEvent[] = []
): ValidationProgress {
  const inferred = inferValidationFromEvents(workflowEvents);
  const github = mergeValidationStatus(
    normalizeStatus(githubStatus),
    inferred.github
  );
  const jira = mergeValidationStatus(normalizeStatus(jiraStatus), inferred.jira);
  const qa = mergeValidationStatus(normalizeStatus(qaStatus), inferred.qa);

  if (github === null) {
    return { completedCount: 0, currentIndex: 0, failedIndex: null };
  }

  if (github !== 'PASS') {
    return { completedCount: 1, currentIndex: -1, failedIndex: null };
  }

  if (jira === null) {
    return { completedCount: 1, currentIndex: 1, failedIndex: null };
  }

  if (jira !== 'PASS') {
    return { completedCount: 1, currentIndex: 1, failedIndex: 1 };
  }

  if (qa === null) {
    return { completedCount: 2, currentIndex: 2, failedIndex: null };
  }

  if (qa !== 'PASS') {
    return { completedCount: 2, currentIndex: 2, failedIndex: 2 };
  }

  return { completedCount: 3, currentIndex: 3, failedIndex: null };
}

export function getPostValidationStepIndex(stage: WorkflowStep, status: string): number {
  if (status === 'Rejected') {
    return WORKFLOW_STEPS.indexOf('L3 Approval');
  }
  if (stage === 'L3 Approval Pending') {
    return WORKFLOW_STEPS.indexOf('L3 Approval');
  }
  if (stage === 'RM Approval Pending') {
    return WORKFLOW_STEPS.indexOf('RM Approval');
  }
  const idx = WORKFLOW_STEPS.indexOf(stage);
  return idx >= 0 ? idx : 0;
}

export function getWorkflowStepStates(options: {
  currentStage: WorkflowStep;
  status: string;
  githubStatus?: string | null;
  jiraStatus?: string | null;
  qaStatus?: string | null;
  workflowEvents?: WorkflowEvent[];
  visibleValidationCompleted: number;
}): StepVisualState[] {
  const {
    currentStage,
    status,
    githubStatus,
    jiraStatus,
    qaStatus,
    workflowEvents = [],
    visibleValidationCompleted,
  } = options;

  const validation = computeValidationProgress(
    githubStatus,
    jiraStatus,
    qaStatus,
    workflowEvents
  );
  const postIndex = getPostValidationStepIndex(currentStage, status);
  const isRejected = status === 'Rejected';
  const isFailed = status === 'Failed';
  const validationFinished =
    validation.completedCount >= 3 && validation.failedIndex === null;

  return WORKFLOW_STEPS.map((step, index) => {
    const state: StepVisualState = {
      completed: false,
      current: false,
      failed: false,
      rejected: false,
    };

    if (index < 3) {
      state.completed = index < visibleValidationCompleted;
      if (!validationFinished) {
        state.current =
          validation.currentIndex >= 0 &&
          index === validation.currentIndex &&
          !state.completed;
        state.failed = index === validation.failedIndex;
      }
      return state;
    }

    if (!validationFinished) {
      return state;
    }

    state.completed = !isRejected && !isFailed && index < postIndex;
    state.current = index === postIndex && !isRejected && !isFailed;
    state.failed = isFailed && index === postIndex;
    state.rejected = isRejected && step === 'L3 Approval';
    return state;
  });
}

export function isValidationPhase(backendWorkflowStatus?: BackendWorkflowStatus): boolean {
  return backendWorkflowStatus === 'VALIDATING';
}
