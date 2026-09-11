import { useEffect, useMemo, useState } from 'react';
import { Link, useOutletContext } from 'react-router-dom';
import GitHubIssuesCell from '../components/GitHubIssuesCell';
import SearchBox from '../components/SearchBox';
import StatusBadge from '../components/StatusBadge';
import type { OutletContextType } from '../components/Layout';
import { useReleases } from '../context/ReleaseContext';
import { isGithubIssuesQa } from '../utils/githubIssueLinks';

export default function ReleaseDashboard() {
  const { releases, loading, error, refreshReleases } = useReleases();
  const { onNewRelease } = useOutletContext<OutletContextType>();
  const [search, setSearch] = useState('');

  const filteredReleases = useMemo(() => {
    const query = search.toLowerCase().trim();
    if (!query) return releases;

    return releases.filter(
      (r) =>
        r.id.toLowerCase().includes(query) ||
        r.pr.toLowerCase().includes(query) ||
        r.jira.toLowerCase().includes(query) ||
        (r.githubIssues ?? []).some(
          (issue) =>
            issue.label.toLowerCase().includes(query) ||
            issue.title.toLowerCase().includes(query) ||
            String(issue.number).includes(query)
        ) ||
        r.createdBy.toLowerCase().includes(query) ||
        r.status.toLowerCase().includes(query)
    );
  }, [releases, search]);

  useEffect(() => {
    const hasActiveWorkflow = releases.some((r) => r.status === 'Validating');
    if (!hasActiveWorkflow) return;

    const intervalId = setInterval(() => {
      void refreshReleases();
    }, 5000);

    return () => clearInterval(intervalId);
  }, [releases, refreshReleases]);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h2 className="page-title">Release Dashboard</h2>
          <p className="page-description">
            View and manage all release requests across environments
          </p>
        </div>
      </div>

      <div className="page-toolbar">
        <SearchBox value={search} onChange={setSearch} />
        <button type="button" className="btn btn-secondary" onClick={() => void refreshReleases()}>
          Refresh
        </button>
        <button type="button" className="btn btn-primary" onClick={onNewRelease}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M8 2a.75.75 0 0 1 .75.75v4.5h4.5a.75.75 0 0 1 0 1.5h-4.5v4.5a.75.75 0 0 1-1.5 0v-4.5h-4.5a.75.75 0 0 1 0-1.5h4.5v-4.5A.75.75 0 0 1 8 2z" />
          </svg>
          New Release
        </button>
      </div>

      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}

      <div className="table-container">
        <table className="data-table dashboard-table">
          <colgroup>
            <col className="col-id" />
            <col className="col-branch" />
            <col className="col-url" />
            <col className="col-url" />
            <col className="col-env" />
            <col className="col-date" />
            <col className="col-stage" />
            <col className="col-status" />
            <col className="col-user" />
            <col className="col-date" />
            <col className="col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>Release ID</th>
              <th>Release Branch</th>
              <th>PR</th>
              <th>Jira / Issues</th>
              <th>Environment</th>
              <th>Release Date</th>
              <th>Current Stage</th>
              <th>Status</th>
              <th>Created By</th>
              <th>Created Date</th>
              <th className="col-actions-cell">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={11} className="empty-state">
                  Loading releases…
                </td>
              </tr>
            ) : filteredReleases.length === 0 ? (
              <tr>
                <td colSpan={11} className="empty-state">
                  {releases.length === 0
                    ? 'No release requests yet. Click "+ New Release" to create one.'
                    : 'No releases match your search criteria.'}
                </td>
              </tr>
            ) : (
              filteredReleases.map((release) => (
                <tr key={release.id}>
                  <td>
                    <Link to={`/release/${release.id}`} className="link-primary">
                      {release.id}
                    </Link>
                  </td>
                  <td>{release.releaseBranch}</td>
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
                    {isGithubIssuesQa(release.qaMode) ? (
                      <GitHubIssuesCell issues={release.githubIssues} />
                    ) : release.jira ? (
                      <a
                        href={release.jira}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="link-muted cell-truncate-text"
                        title={release.jira}
                      >
                        {release.jira}
                      </a>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td>{release.environment}</td>
                  <td>{release.releaseDate}</td>
                  <td>{release.currentStage}</td>
                  <td>
                    <StatusBadge status={release.status} />
                  </td>
                  <td>{release.createdBy}</td>
                  <td>{release.createdDate}</td>
                  <td className="col-actions-cell">
                    <Link to={`/release/${release.id}`} className="btn btn-link">
                      View Details
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
