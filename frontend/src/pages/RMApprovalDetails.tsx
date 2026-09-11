import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  approveRmReleaseApi,
  getRmApprovalApi,
  rejectRmReleaseApi,
  type RMApprovalRequestInfo,
} from '../api/releases';
import GitHubIssuesCell from '../components/GitHubIssuesCell';
import StatusBadge from '../components/StatusBadge';
import { useAuth } from '../context/AuthContext';
import { useReleases } from '../context/ReleaseContext';
import { isGithubIssuesQa } from '../utils/githubIssueLinks';

export default function RMApprovalDetails() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { getRelease, updateReleaseFromBackend } = useReleases();
  const [approval, setApproval] = useState<RMApprovalRequestInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [rejectRemarks, setRejectRemarks] = useState('');
  const [approveComment, setApproveComment] = useState('');
  const [showRejectForm, setShowRejectForm] = useState(false);

  useEffect(() => {
    if (!id) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    getRmApprovalApi(id)
      .then((approvalData) => {
        if (!cancelled) setApproval(approvalData);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load RM approval request');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  const handleApprove = async () => {
    if (!id || !user) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const state = await approveRmReleaseApi(
        id,
        user.name,
        user.soeId,
        approveComment
      );
      updateReleaseFromBackend(state);
      navigate(`/release/${id}`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to approve release');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!id || !user || !rejectRemarks.trim()) {
      setActionError('Rejection remarks are required.');
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const state = await rejectRmReleaseApi(
        id,
        user.name,
        user.soeId,
        rejectRemarks.trim()
      );
      updateReleaseFromBackend(state);
      navigate('/approvals');
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to reject release');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="page">
        <div className="empty-state-page">
          <p>Loading RM approval request...</p>
        </div>
      </div>
    );
  }

  if (error || !approval) {
    return (
      <div className="page">
        <div className="empty-state-page">
          <h2>RM Approval Not Found</h2>
          <p>{error ?? 'The approval request could not be loaded.'}</p>
          <Link to="/approvals" className="btn btn-primary">
            Back to Approval Queue
          </Link>
        </div>
      </div>
    );
  }

  const isPending = approval.status === 'PENDING';
  const statuses = approval.approval_statuses;
  const linkedRelease = getRelease(approval.release_id);
  const usesGithubIssues = isGithubIssuesQa(linkedRelease?.qaMode);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="breadcrumb">
            <Link to="/approvals">Approval Queue</Link>
            <span>/</span>
            <span>{approval.release_id}</span>
          </div>
          <h2 className="page-title">RM Approval — {approval.release_id}</h2>
          <p className="page-description">
            Review build details and approve or reject deployment.
          </p>
        </div>
        <Link to="/approvals" className="btn btn-secondary">
          Back to Queue
        </Link>
      </div>

      <section className="detail-section">
        <h3 className="section-title">Release Request Summary</h3>
        <div className="table-container">
          <table className="data-table info-table">
            <tbody>
              <tr>
                <th>Release ID</th>
                <td>{approval.release_id}</td>
                <th>Status</th>
                <td>
                  <StatusBadge
                    status={
                      approval.status === 'PENDING'
                        ? 'Pending'
                        : approval.status === 'APPROVED'
                          ? 'Completed'
                          : 'Rejected'
                    }
                  />
                </td>
              </tr>
              <tr>
                <th>Release Branch</th>
                <td>{approval.release_branch}</td>
                <th>Release Version</th>
                <td>{approval.release_version}</td>
              </tr>
              <tr>
                <th>Build ID</th>
                <td>{approval.build_id}</td>
                <th>Target Environment</th>
                <td>{approval.target_environment}</td>
              </tr>
              <tr>
                <th>Deployment Window</th>
                <td colSpan={3}>{approval.deployment_window}</td>
              </tr>
              <tr>
                <th>PR Raised By</th>
                <td>{approval.raised_by || '-'}</td>
                <th>L3 Approved By</th>
                <td>{approval.l3_approved_by || '-'}</td>
              </tr>
              <tr>
                <th>PR Title</th>
                <td colSpan={3}>{approval.pr_title || '-'}</td>
              </tr>
              <tr>
                <th>GitHub PR</th>
                <td colSpan={3}>
                  <a
                    href={approval.github_pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link-muted"
                  >
                    {approval.github_pr_url}
                  </a>
                </td>
              </tr>
              <tr>
                <th>{usesGithubIssues ? 'GitHub Issues' : 'Jira Ticket'}</th>
                <td colSpan={3}>
                  {usesGithubIssues ? (
                    <GitHubIssuesCell issues={linkedRelease?.githubIssues} />
                  ) : approval.jira_url ? (
                    <a
                      href={approval.jira_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="link-muted"
                    >
                      {approval.jira_url}
                      {approval.jira_issue_key ? ` (${approval.jira_issue_key})` : ''}
                    </a>
                  ) : (
                    '-'
                  )}
                </td>
              </tr>
              <tr>
                <th>Approval Statuses</th>
                <td colSpan={3}>
                  GitHub: {statuses.github_validation ?? 'N/A'} | Jira:{' '}
                  {statuses.jira_validation ?? 'N/A'} | QA: {statuses.qa_validation ?? 'N/A'} | L3:{' '}
                  {statuses.l3_approval ?? 'N/A'} | Merge: {statuses.merge ?? 'N/A'} | Build:{' '}
                  {statuses.build ?? 'N/A'}
                </td>
              </tr>
              {isPending ? (
                <tr>
                  <th>Approval Link</th>
                  <td colSpan={3}>
                    <a
                      href={approval.approval_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="link-muted"
                    >
                      {approval.approval_url}
                    </a>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      {actionError && <div className="form-error">{actionError}</div>}

      {isPending ? (
        <section className="detail-section approval-actions-section">
          <h3 className="section-title">Approval Actions</h3>
          <div className="form-group approval-form-group">
            <label htmlFor="approve-comment">Comment (optional)</label>
            <textarea
              id="approve-comment"
              value={approveComment}
              onChange={(e) => setApproveComment(e.target.value)}
              rows={4}
              placeholder="Add an optional comment with your approval"
            />
          </div>
          <div className="approval-actions">
            <button
              type="button"
              className="btn btn-success"
              onClick={handleApprove}
              disabled={submitting}
            >
              Approve Release
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => setShowRejectForm((prev) => !prev)}
              disabled={submitting}
            >
              Reject Release
            </button>
          </div>

          {showRejectForm && (
            <div className="form-group approval-form-group reject-form">
              <label htmlFor="reject-remarks">Rejection Remarks</label>
              <textarea
                id="reject-remarks"
                value={rejectRemarks}
                onChange={(e) => setRejectRemarks(e.target.value)}
                rows={4}
                placeholder="Provide reason for rejection"
              />
              <button
                type="button"
                className="btn btn-danger btn-sm reject-form-submit"
                onClick={handleReject}
                disabled={submitting}
              >
                Confirm Reject
              </button>
            </div>
          )}
        </section>
      ) : (
        <section className="detail-section">
          <h3 className="section-title">Decision</h3>
          <p>
            {approval.status === 'APPROVED'
              ? `Approved by ${approval.approved_by ?? 'Release Manager'}${
                  approval.approval_comment ? `: ${approval.approval_comment}` : ''
                }`
              : `Rejected by ${approval.approved_by ?? 'Release Manager'}: ${approval.rejection_remarks ?? ''}`}
          </p>
        </section>
      )}
    </div>
  );
}
