import type { GitHubIssueLink } from '../types/release';

interface GitHubIssuesCellProps {
  issues?: GitHubIssueLink[];
  emptyText?: string;
}

export default function GitHubIssuesCell({
  issues = [],
  emptyText = 'Linked from PR',
}: GitHubIssuesCellProps) {
  if (!issues.length) {
    return <span>{emptyText}</span>;
  }

  return (
    <span className="github-issue-links">
      {issues.map((issue, index) => (
        <span key={issue.url} className="github-issue-link-item">
          {index > 0 ? <span className="github-issue-sep">, </span> : null}
          <a
            href={issue.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-muted"
            title={issue.title ? `${issue.label} ${issue.title}` : issue.label}
          >
            {issue.label}
          </a>
        </span>
      ))}
    </span>
  );
}
