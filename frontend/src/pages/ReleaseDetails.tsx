import { useEffect, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getQaSignoffAttachmentUrl } from '../api/releases';
import { BACKEND_POST_MERGE_STATUSES } from '../api/releases';
import AgentActivityPanel from '../components/AgentActivityPanel';
import GitHubIssuesCell from '../components/GitHubIssuesCell';
import QaCoverageTable from '../components/QaCoverageTable';
import QaGeneratedTestsTable from '../components/QaGeneratedTestsTable';
import StatusBadge from '../components/StatusBadge';
import WorkflowProgressBar from '../components/WorkflowProgressBar';
import { useReleases } from '../context/ReleaseContext';
import { useReleasePolling } from '../hooks/useReleasePolling';
import { extractJiraIssueKey } from '../utils/agentActivityDocument';
import { isGithubIssuesQa } from '../utils/githubIssueLinks';

export default function ReleaseDetails() {
  const { id } = useParams<{ id: string }>();
  const { getRelease, advanceWorkflow, updateReleaseFromBackend } = useReleases();
  const release = id ? getRelease(id) : undefined;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const shouldPollBackend =
    !!release &&
    !['RM Approved', 'Completed', 'Rejected'].includes(release.status) &&
    !['RM_APPROVED', 'RM_REJECTED', 'L3_REJECTED', 'MERGE_FAILED', 'BUILD_FAILED', 'HALTED', 'VALIDATION_ERROR', 'DEPLOYMENT_COMPLETED'].includes(
      release.backendWorkflowStatus ?? ''
    );

  useReleasePolling(id, updateReleaseFromBackend, shouldPollBackend);

  useEffect(() => {
    if (!release || release.status === 'Rejected' || release.status === 'Completed') {
      return;
    }

    const isBackendPostMerge =
      !!release.backendWorkflowStatus &&
      BACKEND_POST_MERGE_STATUSES.has(release.backendWorkflowStatus);

    const hasPendingStep = release.workflowActivities.some(
      (a) =>
        (a.activity === 'Generating Build' && a.status === 'Running') ||
        (a.activity === 'Deployment of Build' &&
          (a.status === 'Pending' || a.status === 'Running'))
    );

    const isRmApprovalPending =
      release.backendWorkflowStatus === 'RM_APPROVAL_PENDING' ||
      release.workflowActivities.some(
        (a) => a.activity === 'Waiting for RM Approval' && a.status === 'Pending'
      );

    const hasBackendMergeInProgress =
      release.backendWorkflowStatus === 'L3_APPROVED' ||
      release.backendWorkflowStatus === 'MERGE_PENDING' ||
      release.backendWorkflowStatus === 'MERGED' ||
      release.backendWorkflowStatus === 'MERGE_FAILED' ||
      release.backendWorkflowStatus === 'BUILD_FAILED' ||
      release.workflowEvents.some((event) => event.agent === 'merge' && !event.simulated);

    const hasDeploymentStep = release.workflowActivities.some(
      (a) =>
        a.activity === 'Deployment of Build' &&
        (a.status === 'Pending' || a.status === 'Running')
    );

    const shouldAdvanceDeployment =
      release.backendWorkflowStatus === 'RM_APPROVED' && hasDeploymentStep;

    if (
      (hasPendingStep &&
        !isRmApprovalPending &&
        !hasBackendMergeInProgress &&
        !isBackendPostMerge &&
        release.status !== 'Rejected') ||
      shouldAdvanceDeployment
    ) {
      timerRef.current = setTimeout(() => {
        if (id) advanceWorkflow(id);
      }, 3000);
    }

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [release, id, advanceWorkflow]);

  if (!release) {
    return (
      <div className="page">
        <div className="empty-state-page">
          <h2>Release Not Found</h2>
          <p>The release you are looking for does not exist.</p>
          <Link to="/" className="btn btn-primary">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const jiraIssueKey = extractJiraIssueKey(release.jira);
  const usesGithubIssues = isGithubIssuesQa(release.qaMode);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="breadcrumb">
            <Link to="/">Dashboard</Link>
            <span>/</span>
            <span>{release.id}</span>
          </div>
          <h2 className="page-title">Release Details — {release.id}</h2>
        </div>
        <Link to="/" className="btn btn-secondary">
          Back to Dashboard
        </Link>
      </div>

      <section className="detail-section">
        <h3 className="section-title">Release Information</h3>
        <div className="table-container">
          <table className="data-table info-table">
            <tbody>
              <tr>
                <th>Release Branch</th>
                <td>{release.releaseBranch}</td>
                <th>PR</th>
                <td>
                  <a href={release.pr} target="_blank" rel="noopener noreferrer" className="link-muted">
                    {release.pr}
                  </a>
                </td>
              </tr>
              <tr>
                <th>{usesGithubIssues ? 'GitHub Issues' : 'JIRA'}</th>
                <td>
                  {usesGithubIssues ? (
                    <GitHubIssuesCell issues={release.githubIssues} />
                  ) : release.jira ? (
                    <a href={release.jira} target="_blank" rel="noopener noreferrer" className="link-muted">
                      {release.jira}
                    </a>
                  ) : (
                    '-'
                  )}
                </td>
                <th>QA validation</th>
                <td>{release.qaSignOff || '-'}</td>
              </tr>
              <tr>
                <th>QA Reason</th>
                <td>{release.qaReason || '-'}</td>
                <th>QA Sign-off Attachment</th>
                <td>
                  {release.qaSignOffAttachmentName ? (
                    <a
                      href={getQaSignoffAttachmentUrl(release.id)}
                      download={release.qaSignOffAttachmentName}
                      className="btn btn-secondary btn-sm"
                    >
                      Download {release.qaSignOffAttachmentName}
                    </a>
                  ) : (
                    '-'
                  )}
                </td>
              </tr>
              <tr>
                <th>Environment</th>
                <td>{release.environment}</td>
                <th>Release Date</th>
                <td>{release.releaseDate}</td>
              </tr>
              <tr>
                <th>Current Status</th>
                <td>
                  <StatusBadge status={release.status} />
                </td>
                <th>Build ID</th>
                <td>{release.buildId || '-'}</td>
              </tr>
              <tr>
                <th>Deployment Status</th>
                <td colSpan={3}>
                  {release.deploymentStatus === '-' ? (
                    '-'
                  ) : (
                    <StatusBadge status={release.deploymentStatus} />
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <WorkflowProgressBar
        releaseId={release.id}
        currentStage={release.currentStage}
        status={release.status}
        githubValidationStatus={release.githubValidationStatus}
        jiraValidationStatus={release.jiraValidationStatus}
        qaValidationStatus={release.qaValidationStatus}
        workflowEvents={release.workflowEvents}
        qaMode={release.qaMode}
      />

      <QaCoverageTable
        rows={release.qaCoverageRows}
        qaStatus={release.qaValidationStatus}
        coveragePercent={release.qaCoveragePercent}
        errors={release.qaValidationErrors}
      />

      <QaGeneratedTestsTable
        rows={release.qaGeneratedTests}
        repo={release.qaGeneratedTestsRepo}
        sha={release.qaGeneratedTestsSha}
      />

      <AgentActivityPanel
        releaseId={release.id}
        environment={release.environment}
        jiraIssueKey={jiraIssueKey}
        events={release.workflowEvents}
      />

      <section className="detail-section">
        <h3 className="section-title">Workflow Activity</h3>
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Sr No</th>
                <th>Name</th>
                <th>Team</th>
                <th>Activity</th>
                <th>Status</th>
                <th>Time</th>
                <th>Remarks</th>
              </tr>
            </thead>
            <tbody>
              {release.workflowActivities.map((activity) => (
                <tr key={activity.id}>
                  <td>{activity.srNo}</td>
                  <td>{activity.name || '-'}</td>
                  <td>{activity.team}</td>
                  <td>{activity.activity}</td>
                  <td>
                    <StatusBadge status={activity.status} />
                  </td>
                  <td>{activity.time}</td>
                  <td>{activity.remarks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
