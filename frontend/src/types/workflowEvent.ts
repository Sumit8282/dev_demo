export type WorkflowEventPhase = 'started' | 'check' | 'completed' | 'error' | 'info';

export type WorkflowEventAgent =
  | 'system'
  | 'orchestrator'
  | 'github'
  | 'jira'
  | 'qa'
  | 'l3'
  | 'merge'
  | 'build'
  | 'rm'
  | 'deploy';

export interface WorkflowEvent {
  id: string;
  timestamp: string;
  agent: WorkflowEventAgent | string;
  phase: WorkflowEventPhase | string;
  message: string;
  metadata?: Record<string, unknown>;
  simulated?: boolean;
}
