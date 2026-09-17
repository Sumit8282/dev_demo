import { useEffect, useMemo, useRef, useState } from 'react';
import type { WorkflowStep } from '../types/release';
import type { WorkflowEvent } from '../types/workflowEvent';
import {
  WORKFLOW_STEPS,
  computeValidationProgress,
  getWorkflowStepStates,
} from '../utils/workflowProgress';

const STEP_REVEAL_DELAY_MS = 650;

interface WorkflowProgressBarProps {
  releaseId: string;
  currentStage: WorkflowStep;
  status: string;
  githubValidationStatus?: string | null;
  jiraValidationStatus?: string | null;
  qaValidationStatus?: string | null;
  workflowEvents?: WorkflowEvent[];
  qaMode?: string;
}

function useStaggeredValidationCompleted(
  targetCount: number,
  releaseId: string,
  delayMs: number
): number {
  const [visibleCount, setVisibleCount] = useState(() => targetCount);
  const releaseKeyRef = useRef(releaseId);

  useEffect(() => {
    if (releaseId !== releaseKeyRef.current) {
      releaseKeyRef.current = releaseId;
      setVisibleCount(targetCount);
      return;
    }

    if (targetCount < visibleCount) {
      setVisibleCount(targetCount);
      return;
    }

    if (visibleCount >= targetCount) {
      return;
    }

    const timer = window.setTimeout(() => {
      setVisibleCount((count) => Math.min(count + 1, targetCount));
    }, delayMs);

    return () => window.clearTimeout(timer);
  }, [targetCount, visibleCount, delayMs, releaseId]);

  return visibleCount;
}

export default function WorkflowProgressBar({
  releaseId,
  currentStage,
  status,
  githubValidationStatus,
  jiraValidationStatus,
  qaValidationStatus,
  workflowEvents = [],
  qaMode = '',
}: WorkflowProgressBarProps) {
  const skipJira = qaMode === 'github_issues';
  const validationProgress = useMemo(
    () =>
      computeValidationProgress(
        githubValidationStatus,
        jiraValidationStatus,
        qaValidationStatus,
        workflowEvents,
        skipJira
      ),
    [githubValidationStatus, jiraValidationStatus, qaValidationStatus, workflowEvents, skipJira]
  );

  const visibleValidationCompleted = useStaggeredValidationCompleted(
    validationProgress.completedCount,
    releaseId,
    STEP_REVEAL_DELAY_MS
  );

  const stepStates = useMemo(
    () =>
      getWorkflowStepStates({
        currentStage,
        status,
        githubStatus: githubValidationStatus,
        jiraStatus: jiraValidationStatus,
        qaStatus: qaValidationStatus,
        workflowEvents,
        visibleValidationCompleted,
        skipJira,
      }),
    [
      currentStage,
      status,
      githubValidationStatus,
      jiraValidationStatus,
      qaValidationStatus,
      workflowEvents,
      visibleValidationCompleted,
      skipJira,
    ]
  );

  return (
    <div className="workflow-progress">
      <h3 className="section-title">Workflow Progress</h3>
      <div className="progress-bar-container">
        {WORKFLOW_STEPS.map((step, index) => {
          const { completed, current, failed, rejected } = stepStates[index];
          const stepLabel =
            step === 'Scope Agent'
              ? skipJira
                ? 'Scope Agent (GitHub)'
                : 'Scope Agent (Jira)'
              : step;

          return (
            <div key={step} className="progress-step-wrapper">
              <div
                className={`progress-step ${
                  completed ? 'completed progress-step--revealed' : ''
                } ${current && !failed ? 'current' : ''} ${
                  failed ? 'failed' : ''
                } ${rejected ? 'rejected' : ''}`}
              >
                <div className="step-circle">
                  {completed ? (
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                      <path d="M5.5 10.5L2 7l1-1 2.5 2.5L11 3l1 1-6.5 6.5z" />
                    </svg>
                  ) : failed ? (
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                      <path
                        d="M2.5 2.5l7 7M9.5 2.5l-7 7"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                      />
                    </svg>
                  ) : (
                    <span>{index + 1}</span>
                  )}
                </div>
                <span className="step-label">{stepLabel}</span>
              </div>
              {index < WORKFLOW_STEPS.length - 1 && (
                <div className={`progress-connector ${completed ? 'completed' : ''}`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
