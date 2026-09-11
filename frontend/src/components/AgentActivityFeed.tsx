import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import type { WorkflowEvent } from '../types/workflowEvent';
import {
  formatWorkflowEventsForFeed,
  type AgentActivityContext,
} from '../utils/agentActivityDocument';
import { formatTime } from '../utils/helpers';

const AGENT_LABELS: Record<string, string> = {
  system: 'System',
  orchestrator: 'Orchestrator',
  jira: 'Scope Agent',
  qa: 'QA Agent',
  l3: 'L3 Agent',
  merge: 'Merge agent',
  build: 'Build Agent',
  rm: 'RM Agent',
  deploy: 'Deploy Agent',
};

const PHASE_LABELS: Record<string, string> = {
  started: 'Started',
  check: 'Check',
  completed: 'Completed',
  error: 'Error',
  info: 'Info',
};

const EVENT_REVEAL_DELAY_MS = 700;

function formatEventTime(timestamp: string): string {
  try {
    return formatTime(new Date(timestamp));
  } catch {
    return timestamp;
  }
}

function agentLabel(agent: string): string {
  if (agent === 'github') return 'Orchestrator';
  return AGENT_LABELS[agent] ?? agent;
}

function phaseClass(phase: string): string {
  switch (phase) {
    case 'started':
      return 'agent-event-phase--started';
    case 'check':
      return 'agent-event-phase--check';
    case 'completed':
      return 'agent-event-phase--completed';
    case 'error':
      return 'agent-event-phase--error';
    default:
      return 'agent-event-phase--info';
  }
}

function useStaggeredEvents(
  events: WorkflowEvent[],
  releaseId: string,
  delayMs: number
): WorkflowEvent[] {
  const [visibleCount, setVisibleCount] = useState(() => events.length);
  const releaseKeyRef = useRef(releaseId);

  useEffect(() => {
    if (releaseId !== releaseKeyRef.current) {
      releaseKeyRef.current = releaseId;
      setVisibleCount(events.length);
      return;
    }

    if (events.length < visibleCount) {
      setVisibleCount(events.length);
      return;
    }

    if (visibleCount >= events.length) {
      return;
    }

    const timer = window.setTimeout(() => {
      setVisibleCount((count) => Math.min(count + 1, events.length));
    }, delayMs);

    return () => window.clearTimeout(timer);
  }, [events.length, visibleCount, delayMs, releaseId]);

  return events.slice(0, visibleCount);
}

interface AgentActivityFeedProps {
  releaseId: string;
  environment: string;
  jiraIssueKey: string;
  events: WorkflowEvent[];
  scrollContainerRef?: RefObject<HTMLDivElement | null>;
}

export default function AgentActivityFeed({
  releaseId,
  environment,
  jiraIssueKey,
  events,
  scrollContainerRef,
}: AgentActivityFeedProps) {
  const logContext: AgentActivityContext = useMemo(
    () => ({
      releaseId,
      environment,
      jiraIssueKey,
      targetBranch: 'main',
    }),
    [releaseId, environment, jiraIssueKey]
  );

  const preparedEvents = useMemo(
    () => formatWorkflowEventsForFeed(events, logContext),
    [events, logContext]
  );

  const visibleEvents = useStaggeredEvents(preparedEvents, releaseId, EVENT_REVEAL_DELAY_MS);

  useEffect(() => {
    if (!scrollContainerRef?.current) return;
    scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
  }, [visibleEvents.length, scrollContainerRef]);

  if (preparedEvents.length === 0) {
    return (
      <div className="agent-activity-empty">
        No agent activity yet. Events will appear here as the workflow runs.
      </div>
    );
  }

  return (
    <div className="agent-activity-feed" role="log" aria-live="polite">
      {visibleEvents.map((event) => (
        <div key={event.id} className="agent-activity-row agent-activity-row--revealed">
          <span className="agent-activity-time">{formatEventTime(event.timestamp)}</span>
          <span className="agent-activity-agent">{agentLabel(String(event.agent))}</span>
          <span className={`agent-activity-phase ${phaseClass(String(event.phase))}`}>
            {PHASE_LABELS[String(event.phase)] ?? event.phase}
          </span>
          <span className="agent-activity-message">{event.message}</span>
        </div>
      ))}
    </div>
  );
}
