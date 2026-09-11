import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  approveL3ReleaseApi,
  getL3ApprovalApi,
  getQaSignoffAttachmentUrl,
  getReleaseApi,
  rejectL3ReleaseApi,
  type L3ApprovalRequestInfo,
} from '../api/releases';
import QaCoverageTable from '../components/QaCoverageTable';
import QaGeneratedTestsTable from '../components/QaGeneratedTestsTable';
import StatusBadge from '../components/StatusBadge';
import { useAuth } from '../context/AuthContext';
import { useReleases } from '../context/ReleaseContext';
import type { QaCoverageRow, QaGeneratedTestRow, ValidationStatus } from '../types/release';
import { mapQaCoverageRows, mapQaGeneratedTests } from '../utils/releaseMapper';

export default function L3ApprovalDetails() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { updateReleaseFromBackend } = useReleases();
  const [approval, setApproval] = useState<L3ApprovalRequestInfo | null>(null);
  const [qaCoverageRows, setQaCoverageRows] = useState<QaCoverageRow[]>([]);
  const [qaGeneratedTests, setQaGeneratedTests] = useState<QaGeneratedTestRow[]>([]);
  const [qaGeneratedTestsRepo, setQaGeneratedTestsRepo] = useState('');
  const [qaGeneratedTestsSha, setQaGeneratedTestsSha] = useState('');
  const [qaValidationStatus, setQaValidationStatus] = useState<ValidationStatus | null>(null);
  const [qaCoveragePercent, setQaCoveragePercent] = useState<number | null>(null);
  const [qaValidationErrors, setQaValidationErrors] = useState<string[]>([]);
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

    getL3ApprovalApi(id)
      .then((approvalData) => {
        if (!cancelled) setApproval(approvalData);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load L3 approval request');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    getReleaseApi(id)
      .then((state) => {
        if (cancelled) return;
        const metadata = state.qa_validation?.metadata;
        const percent = metadata?.acceptance_criteria_coverage_percent;
        setQaCoverageRows(mapQaCoverageRows(state));
        setQaGeneratedTests(mapQaGeneratedTests(state));
        setQaGeneratedTestsRepo(String(metadata?.generated_tests_repo ?? '').trim());
        setQaGeneratedTestsSha(String(metadata?.generated_tests_sha ?? '').trim());
        setQaValidationStatus(state.qa_validation?.status ?? null);
        setQaCoveragePercent(typeof percent === 'number' ? percent : null);
        setQaValidationErrors(state.qa_validation?.errors ?? []);
      })
      .catch(() => {
        if (!cancelled) {
          setQaCoverageRows([]);
        }
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
      const state = await approveL3ReleaseApi(
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
      const state = await rejectL3ReleaseApi(
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
          <p>Loading L3 approval request...</p>
        </div>
      </div>
    );
  }

  if (error || !approval) {
    return (
      <div className="page">
        <div className="empty-state-page">
          <h2>L3 Approval Not Found</h2>
          <p>{error ?? 'The approval request could not be loaded.'}</p>
          <Link to="/approvals" className="btn btn-primary">
            Back to Approval Queue
          </Link>
        </div>
      </div>
    );
  }

  const isPending = approval.status === 'PENDING';
  const riskScore = approval.risk_score;

  const riskLevelClass =
    riskScore?.level === 'HIGH'
      ? 'badge-failed'
      : riskScore?.level === 'MEDIUM'
        ? 'badge-pending'
        : 'badge-completed';

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="breadcrumb">
            <Link to="/approvals">Approval Queue</Link>
            <span>/</span>
            <span>{approval.release_id}</span>
          </div>
          <h2 className="page-title">L3 Approval — {approval.release_id}</h2>
          <p className="page-description">
            Review release details and approve or reject this PR request.
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
                <th>Environment</th>
                <td>{approval.environment}</td>
                <th>Release Date</th>
                <td>{approval.release_date}</td>
              </tr>
              <tr>
                <th>PR Raised By</th>
                <td>{approval.raised_by || '-'}</td>
                <th>PR Title</th>
                <td>{approval.pr_title || '-'}</td>
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
                <th>Jira Ticket</th>
                <td colSpan={3}>
                  <a
                    href={approval.jira_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link-muted"
                  >
                    {approval.jira_url} ({approval.jira_issue_key})
                  </a>
                </td>
              </tr>
              <tr>
                <th>QA Sign-off Required</th>
                <td>{approval.qa_signoff_required ? 'Yes' : 'No'}</td>
                <th>QA Document</th>
                <td>
                  {approval.has_qa_attachment && approval.qa_signoff_attachment_filename ? (
                    <a
                      href={getQaSignoffAttachmentUrl(approval.release_id)}
                      download={approval.qa_signoff_attachment_filename}
                      className="btn btn-secondary btn-sm"
                    >
                      Download {approval.qa_signoff_attachment_filename}
                    </a>
                  ) : (
                    '-'
                  )}
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

      <QaCoverageTable
        rows={qaCoverageRows}
        qaStatus={qaValidationStatus}
        coveragePercent={qaCoveragePercent}
        errors={qaValidationErrors}
      />

      <QaGeneratedTestsTable
        rows={qaGeneratedTests}
        repo={qaGeneratedTestsRepo}
        sha={qaGeneratedTestsSha}
      />

      {riskScore ? (
        <section className="detail-section">
          <h3 className="section-title">Release Risk Assessment</h3>
          <div className="table-container">
            <table className="data-table info-table">
              <tbody>
                <tr>
                  <th>Risk Score</th>
                  <td>{riskScore.score.toFixed(2)}</td>
                  <th>Risk Level</th>
                  <td>
                    <span className={`status-badge ${riskLevelClass}`}>
                      {riskScore.level}
                    </span>
                  </td>
                </tr>
                <tr>
                  <th>File Count Score</th>
                  <td>{(riskScore.breakdown.file_count_score ?? 0).toFixed(2)}</td>
                  <th>Lines Changed Score</th>
                  <td>{(riskScore.breakdown.lines_changed_score ?? 0).toFixed(2)}</td>
                </tr>
                <tr>
                  <th>Change Volume</th>
                  <td colSpan={3}>
                    {riskScore.metrics?.files_changed ?? 0} files changed,{' '}
                    {riskScore.metrics?.lines_changed ?? 0} lines of code modified (
                    {riskScore.metrics?.lines_added ?? 0} added,{' '}
                    {riskScore.metrics?.lines_deleted ?? 0} removed)
                  </td>
                </tr>
                {riskScore.high_risk_files.length > 0 ? (
                  <tr>
                    <th>High-Risk Files</th>
                    <td colSpan={3}>
                      <ul className="risk-file-list">
                        {riskScore.high_risk_files.map((file) => (
                          <li key={file.filepath}>
                            {file.filepath}{' '}
                            <span className="text-muted">
                              (failure rate: {(file.failure_rate * 100).toFixed(0)}%)
                            </span>
                          </li>
                        ))}
                      </ul>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

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
              ? `Approved by ${approval.approved_by ?? 'L3 Manager'}${
                  approval.approval_comment ? `: ${approval.approval_comment}` : ''
                }`
              : `Rejected by ${approval.approved_by ?? 'L3 Manager'}: ${approval.rejection_remarks ?? ''}`}
          </p>
        </section>
      )}
    </div>
  );
}
