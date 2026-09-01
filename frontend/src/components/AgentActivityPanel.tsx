import { useRef, useState } from 'react';
import type { WorkflowEvent } from '../types/workflowEvent';
import AgentActivityFeed from './AgentActivityFeed';

interface AgentActivityPanelProps {
  releaseId: string;
  environment: string;
  jiraIssueKey: string;
  events: WorkflowEvent[];
}

export default function AgentActivityPanel({
  releaseId,
  environment,
  jiraIssueKey,
  events,
}: AgentActivityPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const feedRef = useRef<HTMLDivElement>(null);

  return (
    <section className="detail-section agent-activity-section">
      <div className="agent-activity-header">
        <h3 className="section-title">Agent Activity</h3>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          {expanded ? 'Hide Agent Activity' : 'View Agent Activity'}
        </button>
      </div>
      {expanded ? (
        <div className="agent-activity-panel" ref={feedRef}>
          <AgentActivityFeed
            releaseId={releaseId}
            environment={environment}
            jiraIssueKey={jiraIssueKey}
            events={events}
            scrollContainerRef={feedRef}
          />
        </div>
      ) : null}
    </section>
  );
}
