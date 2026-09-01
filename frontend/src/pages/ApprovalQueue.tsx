import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import SearchBox from '../components/SearchBox';
import type { ApprovalType, Release } from '../types/release';
import { useReleases } from '../context/ReleaseContext';

function getL3ApproverName(release: Release): string {
  return (
    release.workflowActivities.find(
      (activity) =>
        activity.team === 'L3' &&
        (activity.activity === 'Approved Release' || activity.activity === 'Rejected Release')
    )?.name?.trim() || '-'
  );
}

function filterReleases(releases: Release[], query: string) {
  const q = query.toLowerCase().trim();
  if (!q) return releases;

  return releases.filter(
    (r) =>
      r.id.toLowerCase().includes(q) ||
      r.pr.toLowerCase().includes(q) ||
      r.jira.toLowerCase().includes(q) ||
      r.createdBy.toLowerCase().includes(q) ||
      getL3ApproverName(r).toLowerCase().includes(q) ||
      r.status.toLowerCase().includes(q)
  );
}

interface ApprovalTableProps {
  releases: Release[];
  type: ApprovalType;
  emptyMessage: string;
}

function ApprovalTable({
  releases,
  type,
  emptyMessage,
}: ApprovalTableProps) {
  return (
    <div className="table-container">
      <table className="data-table approval-table">
        <colgroup>
          <col style={{ width: '130px' }} />
          <col style={{ width: '160px' }} />
          <col style={{ width: '160px' }} />
          <col style={{ width: '110px' }} />
          <col style={{ width: '120px' }} />
          <col style={{ width: '90px' }} />
          <col style={{ width: '110px' }} />
          <col style={{ width: '140px' }} />
          <col style={{ width: '150px' }} />
          <col style={{ width: '220px' }} />
        </colgroup>
        <thead>
          <tr>
            <th>Release ID</th>
            <th>PR</th>
            <th>JIRA</th>
            <th>Developer</th>
            <th>L3 Approver</th>
            <th>Environment</th>
            <th>Release Date</th>
            <th>Requested On</th>
            <th>Current Stage</th>
            <th className="col-actions-cell">Actions</th>
          </tr>
        </thead>
        <tbody>
          {releases.length === 0 ? (
            <tr>
              <td colSpan={9} className="empty-state">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            releases.map((release) => (
              <tr key={release.id}>
                <td>
                  <Link to={`/release/${release.id}`} className="link-primary">
                    {release.id}
                  </Link>
                </td>
                <td className="cell-truncate">
                  <a
                    href={release.pr}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link-muted cell-truncate-text"
                    title={release.pr}
                  >
                    {release.pr}
                  </a>
                </td>
                <td className="cell-truncate">
                  <a
                    href={release.jira}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link-muted cell-truncate-text"
                    title={release.jira}
                  >
                    {release.jira}
                  </a>
                </td>
                <td>{release.createdBy}</td>
                <td>{getL3ApproverName(release)}</td>
                <td>{release.environment}</td>
                <td>{release.releaseDate}</td>
                <td>{release.createdDate}</td>
                <td>{release.currentStage}</td>
                <td className="actions-cell col-actions-cell">
                  {type === 'L3' ? (
                    <Link
                      to={`/approvals/l3/${release.id}`}
                      className="btn btn-primary btn-sm"
                    >
                      Review &amp; Approve
                    </Link>
                  ) : (
                    <Link
                      to={`/approvals/rm/${release.id}`}
                      className="btn btn-primary btn-sm"
                    >
                      Review &amp; Approve
                    </Link>
                  )}
                  <Link to={`/release/${release.id}`} className="btn btn-link btn-sm">
                    View Details
                  </Link>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function ApprovalQueue() {
  const { releases, refreshReleases } = useReleases();
  const [search, setSearch] = useState('');

  useEffect(() => {
    void refreshReleases();
    const intervalId = window.setInterval(() => {
      void refreshReleases();
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [refreshReleases]);

  const l3PendingApprovals = useMemo(() => {
    return releases.filter(
      (r) =>
        (r.backendWorkflowStatus === 'L3_APPROVAL_PENDING' ||
          r.workflowActivities.some(
            (a) => a.activity === 'Waiting for Approval' && a.status === 'Pending'
          )) &&
        r.status !== 'Rejected'
    );
  }, [releases]);

  const rmPendingApprovals = useMemo(() => {
    return releases.filter(
      (r) =>
        (r.backendWorkflowStatus === 'RM_APPROVAL_PENDING' ||
          r.workflowActivities.some(
            (a) => a.activity === 'Waiting for RM Approval' && a.status === 'Pending'
          )) &&
        r.status !== 'Rejected'
    );
  }, [releases]);

  const filteredL3 = useMemo(
    () => filterReleases(l3PendingApprovals, search),
    [l3PendingApprovals, search]
  );

  const filteredRm = useMemo(
    () => filterReleases(rmPendingApprovals, search),
    [rmPendingApprovals, search]
  );

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h2 className="page-title">Approval Queue</h2>
          <p className="page-description">
            Review and approve releases pending L3 and RM approval
          </p>
        </div>
      </div>

      <div className="page-toolbar">
        <SearchBox value={search} onChange={setSearch} />
      </div>

      <section className="approval-section">
        <h3 className="section-title">L3 Approval</h3>
        <ApprovalTable
          releases={filteredL3}
          type="L3"
          emptyMessage={
            l3PendingApprovals.length === 0
              ? 'No releases pending L3 approval.'
              : 'No L3 approvals match your search criteria.'
          }
        />
      </section>

      <section className="approval-section">
        <h3 className="section-title">RM Approval</h3>
        <ApprovalTable
          releases={filteredRm}
          type="RM"
          emptyMessage={
            rmPendingApprovals.length === 0
              ? 'No releases pending RM approval.'
              : 'No RM approvals match your search criteria.'
          }
        />
      </section>
    </div>
  );
}
