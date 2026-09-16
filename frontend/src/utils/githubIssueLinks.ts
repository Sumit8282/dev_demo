import type { GitHubIssueLink } from '../types/release';

const ISSUE_REF_RE = /^([^/#\s]+)\/([^/#\s]+)#(\d+)$/;
const AC_ID_RE = /^GH-(\d+)(?:-\d+)?$/i;

export function isGithubIssuesQa(qaMode?: string | null): boolean {
  return (qaMode ?? '').trim().toLowerCase() === 'github_issues';
}

export function parseOwnerRepoFromGithubUrl(url: string): { owner: string; repo: string } | null {
  const match = url.trim().match(/github\.com\/([^/]+)\/([^/#?]+)/i);
  if (!match) return null;
  return { owner: match[1], repo: match[2].replace(/\.git$/i, '') };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function toIssueLink(
  owner: string,
  repo: string,
  number: number,
  title = '',
  prOwner = '',
  prRepo = ''
): GitHubIssueLink | null {
  if (!owner || !repo || !Number.isFinite(number) || number <= 0) return null;
  const sameRepo =
    prOwner &&
    prRepo &&
    owner.toLowerCase() === prOwner.toLowerCase() &&
    repo.toLowerCase() === prRepo.toLowerCase();
  return {
    owner,
    repo,
    number,
    title: title.trim(),
    url: `https://github.com/${owner}/${repo}/issues/${number}`,
    label: sameRepo ? `#${number}` : `${owner}/${repo}#${number}`,
  };
}

function uniqueIssues(issues: GitHubIssueLink[]): GitHubIssueLink[] {
  const seen = new Set<string>();
  const unique: GitHubIssueLink[] = [];
  for (const issue of issues) {
    const key = `${issue.owner.toLowerCase()}/${issue.repo.toLowerCase()}#${issue.number}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(issue);
  }
  return unique.sort((left, right) => left.number - right.number || left.label.localeCompare(right.label));
}

function issuesFromFetched(
  fetched: unknown,
  prOwner: string,
  prRepo: string
): GitHubIssueLink[] {
  if (!Array.isArray(fetched)) return [];
  return fetched.flatMap((item) => {
    const row = asRecord(item);
    if (!row) return [];
    const number = Number(row.number);
    const link = toIssueLink(
      String(row.owner ?? '').trim(),
      String(row.repo ?? '').trim(),
      number,
      String(row.title ?? ''),
      prOwner,
      prRepo
    );
    return link ? [link] : [];
  });
}

function issuesFromRefs(refs: unknown, prOwner: string, prRepo: string): GitHubIssueLink[] {
  if (!Array.isArray(refs)) return [];
  return refs.flatMap((item) => {
    if (typeof item !== 'string') return [];
    const match = item.trim().match(ISSUE_REF_RE);
    if (!match) return [];
    const link = toIssueLink(match[1], match[2], Number(match[3]), '', prOwner, prRepo);
    return link ? [link] : [];
  });
}

function issuesFromCoverage(matrix: unknown, prOwner: string, prRepo: string): GitHubIssueLink[] {
  if (!Array.isArray(matrix) || !prOwner || !prRepo) return [];
  return matrix.flatMap((item) => {
    const row = asRecord(item);
    const acId = String(row?.ac_id ?? '').trim();
    const match = acId.match(AC_ID_RE);
    if (!match) return [];
    const link = toIssueLink(prOwner, prRepo, Number(match[1]), '', prOwner, prRepo);
    return link ? [link] : [];
  });
}

export function mapGithubIssuesFromState(state: {
  github_pr_url?: string | null;
  qa_validation?: { metadata?: Record<string, unknown> | null } | null;
}): GitHubIssueLink[] {
  const pr = parseOwnerRepoFromGithubUrl(state.github_pr_url ?? '');
  const prOwner = pr?.owner ?? '';
  const prRepo = pr?.repo ?? '';
  const metadata = asRecord(state.qa_validation?.metadata) ?? {};

  const fetched = issuesFromFetched(metadata.github_issues_fetched, prOwner, prRepo);
  if (fetched.length) return uniqueIssues(fetched);

  const refs = issuesFromRefs(metadata.github_issue_numbers, prOwner, prRepo);
  if (refs.length) return uniqueIssues(refs);

  return uniqueIssues(issuesFromCoverage(metadata.coverage_matrix, prOwner, prRepo));
}
