import type { WorkflowEvent } from '../types/workflowEvent';
import {
  resolveJiraCheckErrorMessage,
  resolveJiraTicketNotFoundMessage,
  resolveJiraValidationFailureMessage,
} from './jiraValidationMessages';

export type ActivityLineType =
  | 'title'
  | 'intro'
  | 'section'
  | 'phase'
  | 'check'
  | 'detail'
  | 'update'
  | 'divider'
  | 'summary';

export interface ActivityLine {
  id: string;
  type: ActivityLineType;
  text: string;
  phaseLabel?: string;
  passed?: boolean;
  sectionKey?: string;
}

export interface AgentActivityContext {
  releaseId: string;
  environment: string;
  jiraIssueKey: string;
  targetBranch?: string;
}

function isPassed(event: WorkflowEvent): boolean {
  if (event.metadata?.passed === true) return true;
  if (event.metadata?.passed === false) return false;
  return event.message.includes('PASS') || event.message.includes('passed');
}

function isFailed(event: WorkflowEvent): boolean {
  if (event.metadata?.passed === false) return true;
  return event.message.includes('FAIL') || event.message.includes('failed');
}

function extractApproverName(message: string): string {
  const match = message.match(/(?:granted|rejected) by\s+(.+)$/i);
  return match?.[1]?.trim() ?? message.replace(/^L3 approval (granted|rejected) by\s+/i, '').trim();
}

function parseSourceBranch(message: string): string | null {
  const match = message.match(/Source branch match \(([^)]+)\)/i);
  return match?.[1] ?? null;
}

function parseBuildId(message: string): string | null {
  const match = message.match(/Build generated successfully —\s*(.+)$/i);
  return match?.[1]?.trim() ?? null;
}

function shouldSkipEvent(event: WorkflowEvent): boolean {
  if (event.message.startsWith('Target branch present')) return true;
  if (event.message.startsWith('Fix version matches release — PASS')) return true;
  if (
    event.agent === 'l3' &&
    (event.message.includes('low risk') ||
      event.message.includes('auto-merging') ||
      event.message.includes('merged-notification'))
  ) {
    return true;
  }
  if (
    event.agent === 'merge' &&
    event.phase === 'check'
  ) {
    return true;
  }
  if (
    event.agent === 'orchestrator' &&
    event.message.includes('All validations passed') &&
    event.message.includes('low risk')
  ) {
    return true;
  }
  return false;
}

function parseJiraTransitionStatus(message: string): string | null {
  const patterns = [
    /Updating Jira ticket \S+ to (.+?) after deployment/i,
    /Transitioning Jira ticket \S+ to (.+?)(?:\.|$)/i,
    /Jira ticket \S+ updated to (.+?) after deployment/i,
    /Jira ticket \S+ set to (.+?)(?:\s+with|\s+after|\.|$)/i,
    /Jira ticket \S+ transitioned to (.+?)(?:\.|$)/i,
  ];

  for (const pattern of patterns) {
    const match = message.match(pattern);
    if (match?.[1]) {
      return match[1].trim();
    }
  }

  return null;
}

function isPostDeploymentJiraMessage(message: string): boolean {
  return (
    message.includes('after deployment') ||
    message.includes('Completing Jira ticket') ||
    (message.includes('Jira ticket') && message.includes('deployment comment'))
  );
}

function isL3JiraStatusUpdateMessage(message: string): boolean {
  return (
    message.includes('Transitioning Jira ticket') ||
    message.includes('transitioned to') ||
    message.includes('Failed to transition Jira ticket')
  );
}

function l3JiraUpdateContext(event: WorkflowEvent): 'low_risk' | 'approval' {
  return event.metadata?.low_risk_auto_approval === true ? 'low_risk' : 'approval';
}

function l3JiraUpdateStartedText(status: string | null, context: 'low_risk' | 'approval'): string {
  if (context === 'low_risk') {
    return status
      ? `Updating Jira ticket to ${status} after low risk auto-approval.`
      : 'Updating Jira ticket status after low risk auto-approval.';
  }
  return status
    ? `Updating Jira ticket to ${status} after L3 approval.`
    : 'Updating Jira ticket status after L3 approval.';
}

function l3JiraUpdateCompletedText(status: string | null, context: 'low_risk' | 'approval'): string {
  if (context === 'low_risk') {
    return status
      ? `Jira ticket updated to ${status} after low risk auto-approval.`
      : 'Jira ticket status updated successfully after low risk auto-approval.';
  }
  return status
    ? `Jira ticket updated to ${status} after L3 approval.`
    : 'Jira ticket status updated successfully after L3 approval.';
}

function mapEventToLines(event: WorkflowEvent, ctx: AgentActivityContext): ActivityLine[] {
  if (shouldSkipEvent(event)) return [];

  const agent = String(event.agent);
  const phase = String(event.phase);
  const msg = event.message;
  const id = event.id;

  if (agent === 'system' && msg.includes('created')) {
    return [
      {
        id: `${id}-intro`,
        type: 'intro',
        text: 'Release created successfully. Workflow initiated.',
      },
    ];
  }

  if (agent === 'orchestrator' && phase === 'started' && msg.includes('workflow validation')) {
    return [
      {
        id: `${id}-orch-start`,
        type: 'phase',
        sectionKey: 'orchestrator',
        phaseLabel: 'Started',
        text: 'Release workflow validation initiated.',
      },
    ];
  }

  if (agent === 'orchestrator' && msg.includes('All validations passed')) {
    if (msg.includes('low risk') || msg.includes('merged automatically')) {
      return [];
    }
    return [
      {
        id: `${id}-orch-update`,
        type: 'update',
        sectionKey: 'l3',
        text: 'All validations passed. L3 approval pending.',
      },
    ];
  }

  if (
    agent === 'orchestrator' &&
    phase === 'info' &&
    (msg.includes('Risk score:') || msg.includes('Release risk score'))
  ) {
    const score =
      typeof event.metadata?.risk_score === 'number'
        ? event.metadata.risk_score.toFixed(2)
        : null;
    const level =
      typeof event.metadata?.risk_level === 'string' ? event.metadata.risk_level : null;
    const riskText =
      score && level
        ? `Risk score: ${score} — Risk level: ${level}`
        : msg.replace('Release risk score — ', 'Risk score: ');

    return [
      {
        id: `${id}-risk-score`,
        type: 'detail',
        sectionKey: 'orchestrator',
        text: riskText,
      },
    ];
  }

  const isGithubPhase =
    agent === 'github' ||
    (agent === 'orchestrator' &&
      (msg.includes('GitHub PR validation') ||
        msg.startsWith('PR ') ||
        msg.startsWith('Source branch') ||
        msg.startsWith('Target branch') ||
        msg.startsWith('PR comments')));

  if (isGithubPhase && (phase === 'started' || msg.includes('GitHub PR validation started'))) {
    return [
      {
        id: `${id}-gh-start`,
        type: 'phase',
        sectionKey: 'github',
        phaseLabel: 'Started',
        text: 'Validating pull request.',
      },
    ];
  }

  if (isGithubPhase && phase === 'check') {
    if (msg.startsWith('PR exists')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'github',
          passed: isPassed(event),
          text: 'Pull request exists',
        },
      ];
    }
    if (msg.startsWith('PR is open')) return [];
    if (msg.startsWith('Source branch match')) {
      const branch = parseSourceBranch(msg);
      return [
        {
          id,
          type: 'check',
          sectionKey: 'github',
          passed: isPassed(event),
          text: branch
            ? `Source branch \`${branch}\` matches expected branch`
            : 'Source branch matches expected branch',
        },
      ];
    }
    if (msg.startsWith('Target branch')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'github',
          passed: isPassed(event),
          text: `Target branch \`${ctx.targetBranch ?? 'main'}\` is valid`,
        },
      ];
    }
    if (msg.startsWith('PR comments retrieved')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'github',
          passed: isPassed(event),
          text: 'PR comments retrieved successfully',
        },
      ];
    }
  }

  if (
    isGithubPhase &&
    phase === 'completed' &&
    (msg.includes('GitHub PR validation completed') || msg.includes('GitHub PR validation'))
  ) {
    const passed = isPassed(event) || msg.includes('PASS');
    const lines: ActivityLine[] = [];
    if (passed) {
      lines.push({
        id: `${id}-gh-target`,
        type: 'check',
        sectionKey: 'github',
        passed: true,
        text: `Target branch \`${ctx.targetBranch ?? 'main'}\` is valid`,
      });
    }
    lines.push({
      id: `${id}-gh-complete`,
      type: 'phase',
      sectionKey: 'github',
      phaseLabel: 'Completed',
      text: passed ? 'GitHub PR validation passed.' : 'GitHub PR validation failed.',
    });
    return lines;
  }

  if (agent === 'jira' && phase === 'started') {
    if (isPostDeploymentJiraMessage(msg)) {
      const status = parseJiraTransitionStatus(msg);
      return [
        {
          id: `${id}-deploy-jira-start`,
          type: 'phase',
          sectionKey: 'deploy',
          phaseLabel: 'Started',
          text: status
            ? `Updating Jira ticket to ${status} after deployment.`
            : 'Updating Jira ticket status after deployment.',
        },
      ];
    }
    if (msg.includes('Adding build comment')) {
      return [];
    }
    if (msg.includes('Jira validation started') || msg.includes('validation started')) {
      return [
        {
          id: `${id}-jira-start`,
          type: 'phase',
          sectionKey: 'jira',
          phaseLabel: 'Started',
          text: 'Validating Jira ticket.',
        },
      ];
    }
    return [];
  }

  if (agent === 'jira' && phase === 'completed') {
    if (isPostDeploymentJiraMessage(msg) || (msg.includes('Jira ticket') && msg.includes('after deployment'))) {
      const status = parseJiraTransitionStatus(msg);
      return [
        {
          id: `${id}-deploy-jira-complete`,
          type: 'phase',
          sectionKey: 'deploy',
          phaseLabel: 'Completed',
          text: status
            ? `Jira ticket updated to ${status} after deployment.`
            : 'Jira ticket status updated successfully after deployment.',
        },
      ];
    }
  }

  if (agent === 'jira' && phase === 'check') {
    if (msg.startsWith('Jira ticket exists')) {
      const passed = isPassed(event);
      if (!passed) {
        const errorMessage =
          resolveJiraCheckErrorMessage(event, ctx.jiraIssueKey) ??
          resolveJiraTicketNotFoundMessage(ctx.jiraIssueKey);
        return [
          {
            id,
            type: 'check',
            sectionKey: 'jira',
            passed: false,
            text: errorMessage,
          },
        ];
      }
      return [
        {
          id,
          type: 'check',
          sectionKey: 'jira',
          passed: true,
          text: 'Jira ticket exists',
        },
      ];
    }
    if (msg.startsWith('Jira status valid')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'jira',
          passed: isPassed(event),
          text: 'Jira status is valid',
        },
      ];
    }
    if (msg.startsWith('Fix version matches release — FAIL')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'jira',
          passed: false,
          text: 'Fix version matches the release',
        },
      ];
    }
    if (msg.startsWith('Code validation successful') || msg.startsWith('Description matches PR')) {
      const passed = isPassed(event);
      const lines: ActivityLine[] = [
        {
          id,
          type: 'check',
          sectionKey: 'jira',
          passed,
          text: 'Jira description matches the PR',
        },
      ];
      if (passed) {
        lines.push({
          id: `${id}-jira-criteria`,
          type: 'check',
          sectionKey: 'jira',
          passed: true,
          text: 'All expected criteria are validated with PR',
        });
      }
      return lines;
    }
    if (msg.startsWith('Code validation failed')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'jira',
          passed: false,
          text: 'Jira description matches the PR',
        },
      ];
    }
  }

  if (agent === 'jira' && phase === 'completed' && msg.includes('Jira validation completed')) {
    const passed = isPassed(event) || msg.includes('PASS');
    const lines: ActivityLine[] = [];
    if (passed) {
      lines.push({
        id: `${id}-jira-fix`,
        type: 'check',
        sectionKey: 'jira',
        passed: true,
        text: 'Fix version matches the release',
      });
    }
    const failureMessage = resolveJiraValidationFailureMessage(event.metadata, ctx.jiraIssueKey);
    lines.push({
      id: `${id}-jira-complete`,
      type: 'phase',
      sectionKey: 'jira',
      phaseLabel: 'Completed',
      text: passed
        ? 'Jira validation passed.'
        : failureMessage ?? 'Jira validation failed.',
    });
    return lines;
  }

  if (agent === 'qa' && phase === 'started') {
    return [
      {
        id: `${id}-qa-start`,
        type: 'phase',
        sectionKey: 'qa',
        phaseLabel: 'Started',
        text: 'Validating QA sign-off.',
      },
    ];
  }

  if (agent === 'qa' && phase === 'check') {
    if (msg.includes('sign-off attachment') || msg.includes('sign-off not required')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'qa',
          passed: isPassed(event),
          text: 'QA sign-off attachment verified',
        },
      ];
    }
    if (msg.includes('No open bugs') || msg.includes('Open bugs')) {
      return [
        {
          id,
          type: 'check',
          sectionKey: 'qa',
          passed: isPassed(event),
          text: 'No open bugs found',
        },
      ];
    }
  }

  if (agent === 'qa' && phase === 'completed' && msg.includes('QA sign-off validation completed')) {
    return [
      {
        id: `${id}-qa-complete`,
        type: 'phase',
        sectionKey: 'qa',
        phaseLabel: 'Completed',
        text: isPassed(event) || msg.includes('PASS') ? 'QA validation passed.' : 'QA validation failed.',
      },
    ];
  }

  if (agent === 'l3' && phase === 'started') {
    if (isL3JiraStatusUpdateMessage(msg)) {
      const status = parseJiraTransitionStatus(msg);
      return [
        {
          id: `${id}-l3-jira-start`,
          type: 'phase',
          sectionKey: 'l3',
          phaseLabel: 'Started',
          text: l3JiraUpdateStartedText(status, l3JiraUpdateContext(event)),
        },
      ];
    }
    if (msg.includes('low risk') || msg.includes('auto-merging')) {
      return [];
    }
    if (msg.includes('Creating L3 approval request')) {
      return [
        {
          id: `${id}-l3-start`,
          type: 'phase',
          sectionKey: 'l3',
          phaseLabel: 'Started',
          text: 'L3 approval request created.',
        },
      ];
    }
    return [];
  }

  if (agent === 'l3' && phase === 'completed') {
    if (msg.includes('merged-notification')) {
      return [];
    }
    if (isL3JiraStatusUpdateMessage(msg)) {
      const status = parseJiraTransitionStatus(msg);
      return [
        {
          id: `${id}-l3-jira-complete`,
          type: 'phase',
          sectionKey: 'l3',
          phaseLabel: 'Completed',
          text: l3JiraUpdateCompletedText(status, l3JiraUpdateContext(event)),
        },
      ];
    }
    if (msg.includes('approval granted')) {
      const approver = extractApproverName(msg);
      return [
        {
          id: `${id}-l3-approved`,
          type: 'phase',
          sectionKey: 'l3',
          phaseLabel: 'Completed',
          text: `L3 approval granted by **${approver}**.`,
        },
      ];
    }
    if (msg.includes('approval rejected')) {
      const approver = extractApproverName(msg);
      return [
        {
          id: `${id}-l3-rejected`,
          type: 'phase',
          sectionKey: 'l3',
          phaseLabel: 'Completed',
          text: `L3 approval rejected by **${approver}**.`,
        },
      ];
    }
    if (msg.includes('email sent') || msg.includes('approval request')) {
      return [
        {
          id: `${id}-l3-sent`,
          type: 'phase',
          sectionKey: 'l3',
          phaseLabel: 'Completed',
          text: 'Approval request sent; awaiting approver.',
        },
      ];
    }
  }

  if (agent === 'l3' && phase === 'error' && isL3JiraStatusUpdateMessage(msg)) {
    const status = parseJiraTransitionStatus(msg);
    return [
      {
        id,
        type: 'phase',
        sectionKey: 'l3',
        phaseLabel: 'Error',
        text: status
          ? `Failed to update Jira ticket to ${status}.`
          : 'Failed to update Jira ticket status.',
      },
    ];
  }

  if (agent === 'deploy' && phase === 'started') {
    if (isPostDeploymentJiraMessage(msg) || msg.includes('Updating Jira ticket')) {
      const status = parseJiraTransitionStatus(msg);
      return [
        {
          id: `${id}-deploy-jira-start`,
          type: 'phase',
          sectionKey: 'deploy',
          phaseLabel: 'Started',
          text: status
            ? `Updating Jira ticket to ${status} after deployment.`
            : 'Updating Jira ticket status after deployment.',
        },
      ];
    }
    return [
      {
        id: `${id}-deploy-start`,
        type: 'phase',
        sectionKey: 'deploy',
        phaseLabel: 'Started',
        text: `Deployment initiated to ${ctx.environment}.`,
      },
    ];
  }

  if (agent === 'deploy' && phase === 'completed') {
    if (msg.includes('Jira ticket') && (msg.includes('updated to') || msg.includes('set to') || msg.includes('transitioned to'))) {
      const status = parseJiraTransitionStatus(msg);
      return [
        {
          id: `${id}-deploy-jira-complete`,
          type: 'phase',
          sectionKey: 'deploy',
          phaseLabel: 'Completed',
          text: status
            ? `Jira ticket updated to ${status} after deployment.`
            : 'Jira ticket status updated successfully after deployment.',
        },
      ];
    }
    if (msg.includes('deployment') && msg.includes('completed')) {
      return [
        {
          id: `${id}-deploy-complete`,
          type: 'phase',
          sectionKey: 'deploy',
          phaseLabel: 'Completed',
          text: `Deployment completed successfully on ${ctx.environment}. ✅`,
        },
      ];
    }
  }

  if (agent === 'merge' && phase === 'started') {
    return [
      {
        id: `${id}-merge-start`,
        type: 'phase',
        sectionKey: 'merge',
        phaseLabel: 'Started',
        text: `Merging PR into \`${ctx.targetBranch ?? 'main'}\`.`,
      },
    ];
  }

  if (agent === 'merge' && phase === 'completed') {
    const merged =
      msg.includes('Merge result:') ||
      msg.includes('automatically merged by Release Automation') ||
      msg.includes('squash-merged successfully') ||
      msg.includes('merged successfully') ||
      msg.includes('Merge completed') ||
      (isPassed(event) && !isFailed(event));
    if (merged) {
      return [
        {
          id: `${id}-merge-complete`,
          type: 'phase',
          sectionKey: 'merge',
          phaseLabel: 'Completed',
          text: 'PR merged successfully.',
        },
      ];
    }
  }

  if (agent === 'merge' && phase === 'error') {
    return [
      {
        id,
        type: 'phase',
        sectionKey: 'merge',
        phaseLabel: 'Completed',
        text: msg.replace(/^Pre-merge validation failed:/i, 'Merge failed:'),
      },
    ];
  }

  if (agent === 'build' && phase === 'started') {
    return [
      {
        id: `${id}-build-start`,
        type: 'phase',
        sectionKey: 'build',
        phaseLabel: 'Started',
        text: 'Generating release build.',
      },
    ];
  }

  if (agent === 'build' && phase === 'completed' && msg.includes('Build generated')) {
    const buildId = parseBuildId(msg);
    const lines: ActivityLine[] = [
      {
        id: `${id}-build-complete`,
        type: 'phase',
        sectionKey: 'build',
        phaseLabel: 'Completed',
        text: 'Build generated successfully.',
      },
    ];
    if (buildId) {
      lines.push({
        id: `${id}-build-id`,
        type: 'detail',
        sectionKey: 'build',
        text: `Build ID: \`${buildId}\``,
      });
    }
    return lines;
  }

  if (agent === 'rm' && phase === 'started') {
    return [
      {
        id: `${id}-rm-start`,
        type: 'phase',
        sectionKey: 'rm',
        phaseLabel: 'Started',
        text: 'RM approval requested.',
      },
    ];
  }

  if (agent === 'rm' && phase === 'completed' && msg.includes('RM approval request created')) {
    return [];
  }

  if (agent === 'rm' && phase === 'completed' && msg.includes('RM approval granted')) {
    return [
      {
        id: `${id}-rm-approved`,
        type: 'phase',
        sectionKey: 'rm',
        phaseLabel: 'Completed',
        text: `RM approval granted by **${extractApproverName(msg)}**.`,
      },
    ];
  }

  if (
    agent === 'orchestrator' &&
    phase === 'completed' &&
    msg.includes('Deployment completed')
  ) {
    return [
      {
        id: `${id}-deploy-complete`,
        type: 'phase',
        sectionKey: 'deploy',
        phaseLabel: 'Completed',
        text: `Deployment completed successfully on ${ctx.environment}. ✅`,
      },
    ];
  }

  if (phase === 'error') {
    return [
      {
        id,
        type: 'phase',
        sectionKey: agent,
        phaseLabel: 'Error',
        text: msg,
      },
    ];
  }

  return [];
}

function stripInlineMarkdown(text: string): string {
  return text.replace(/\*\*/g, '').replace(/`/g, '');
}

function sectionKeyToAgent(sectionKey?: string): string {
  if (!sectionKey || sectionKey === 'orchestrator' || sectionKey === 'github') {
    return 'orchestrator';
  }
  return sectionKey;
}

function lineToWorkflowEvent(line: ActivityLine, source: WorkflowEvent): WorkflowEvent | null {
  if (['title', 'section', 'divider', 'summary'].includes(line.type)) {
    return null;
  }

  if (line.type === 'intro') {
    return {
      ...source,
      id: line.id,
      agent: 'system',
      phase: 'completed',
      message: line.text,
    };
  }

  const agent = sectionKeyToAgent(line.sectionKey);

  if (line.type === 'check') {
    const icon = line.passed ? '✓' : '✗';
    return {
      ...source,
      id: line.id,
      agent,
      phase: 'check',
      message: `${icon} ${stripInlineMarkdown(line.text)}`,
    };
  }

  if (line.type === 'update') {
    return {
      ...source,
      id: line.id,
      agent: 'orchestrator',
      phase: 'info',
      message: `Orchestrator Update — ${line.text}`,
    };
  }

  if (line.type === 'detail') {
    return {
      ...source,
      id: line.id,
      agent,
      phase: 'info',
      message: stripInlineMarkdown(line.text),
    };
  }

  if (line.type === 'phase') {
    const phase =
      line.phaseLabel === 'Started'
        ? 'started'
        : line.phaseLabel === 'Error'
          ? 'error'
          : 'completed';
    return {
      ...source,
      id: line.id,
      agent,
      phase,
      message: stripInlineMarkdown(line.text),
    };
  }

  return null;
}

function filterPostMergeJiraValidationStarted(events: WorkflowEvent[]): WorkflowEvent[] {
  const mergeCompleteIndex = events.findIndex(
    (event) =>
      event.agent === 'merge' &&
      event.phase === 'completed' &&
      event.message === 'PR merged successfully.'
  );
  if (mergeCompleteIndex < 0) return events;

  return events.filter((event, index) => {
    if (index <= mergeCompleteIndex) return true;
    if (
      event.agent === 'jira' &&
      event.phase === 'started' &&
      event.message === 'Validating Jira ticket.'
    ) {
      return false;
    }
    return true;
  });
}

function appendWorkflowSuccessSummary(
  events: WorkflowEvent[],
  environment: string
): WorkflowEvent[] {
  const deployCompleteIndex = events.findIndex(
    (event) =>
      event.agent === 'deploy' &&
      event.phase === 'completed' &&
      event.message.includes('Deployment completed')
  );
  if (deployCompleteIndex < 0) return events;

  const summaryText = `Release workflow progressing successfully: Validation Passed → L3 Approved → PR Merged → Build Generated → ${environment} Deployed`;
  if (events.some((event) => event.message === summaryText)) {
    return events;
  }

  const anchor = events[deployCompleteIndex];
  const summaryEvent: WorkflowEvent = {
    ...anchor,
    id: `${anchor.id}-workflow-summary`,
    agent: 'system',
    phase: 'info',
    message: summaryText,
  };

  return [...events, summaryEvent];
}

function dedupeWorkflowEvents(events: WorkflowEvent[]): WorkflowEvent[] {
  let seenGithubStarted = false;
  let seenMergeStarted = false;
  let seenMergeCompleted = false;
  let seenTargetBranch = false;

  return events.filter((event) => {
    if (event.phase === 'check' && event.message.includes('Target branch')) {
      if (seenTargetBranch) return false;
      seenTargetBranch = true;
      return true;
    }

    if (event.phase === 'started' && event.agent === 'merge') {
      if (seenMergeStarted) return false;
      seenMergeStarted = true;
      return true;
    }

    if (event.phase === 'started' && (event.agent === 'github' || event.agent === 'orchestrator')) {
      const isGithubStart =
        event.message.includes('Validating pull request') ||
        event.message.includes('GitHub PR validation');
      if (isGithubStart) {
        if (seenGithubStarted) return false;
        seenGithubStarted = true;
      }
    }

    if (
      event.phase === 'completed' &&
      event.agent === 'merge' &&
      event.message === 'PR merged successfully.'
    ) {
      if (seenMergeCompleted) return false;
      seenMergeCompleted = true;
      return true;
    }

    return true;
  });
}

function ensureDeployStartedEvents(events: WorkflowEvent[], environment: string): WorkflowEvent[] {
  const completeIndex = events.findIndex(
    (event) =>
      event.agent === 'deploy' &&
      event.phase === 'completed' &&
      event.message.includes('Deployment completed')
  );
  if (completeIndex < 0) return events;

  const hasStarted = events.some(
    (event) => event.agent === 'deploy' && event.phase === 'started'
  );
  if (hasStarted) return events;

  const completeEvent = events[completeIndex];
  const startedEvent: WorkflowEvent = {
    ...completeEvent,
    id: `${completeEvent.id}-deploy-start-synth`,
    phase: 'started',
    message: `Deployment initiated to ${environment}.`,
  };

  return [
    ...events.slice(0, completeIndex),
    startedEvent,
    ...events.slice(completeIndex),
  ];
}

/** Format raw workflow events into user-friendly log lines for the table feed. */
export function formatWorkflowEventsForFeed(
  events: WorkflowEvent[],
  ctx: AgentActivityContext
): WorkflowEvent[] {
  const sorted = [...events].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  const output: WorkflowEvent[] = [];

  for (const event of sorted) {
    const lines = mapEventToLines(event, ctx);
    for (const line of lines) {
      const mapped = lineToWorkflowEvent(line, event);
      if (mapped) output.push(mapped);
    }
  }

  return appendWorkflowSuccessSummary(
    filterPostMergeJiraValidationStarted(
      ensureDeployStartedEvents(dedupeWorkflowEvents(output), ctx.environment)
    ),
    ctx.environment
  );
}

export function extractJiraIssueKey(jiraUrl: string): string {
  try {
    const pathname = new URL(jiraUrl).pathname;
    const segment = pathname.split('/').filter(Boolean).pop();
    return segment ?? 'Ticket';
  } catch {
    const match = jiraUrl.match(/[A-Z][A-Z0-9]+-\d+/);
    return match?.[0] ?? 'Ticket';
  }
}
