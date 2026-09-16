import StatusBadge from './StatusBadge';
import type { QaCoverageRow, QaGapReviewUpdate, ValidationStatus } from '../types/release';

interface QaCoverageTableProps {
  rows?: QaCoverageRow[];
  qaStatus?: ValidationStatus | null;
  coveragePercent?: number | null;
  errors?: string[];
  gapReviewUpdates?: QaGapReviewUpdate[];
  gapReviewNotes?: string;
}

function coverageBadgeStatus(coverage: string): string {
  const value = coverage.trim().toUpperCase();
  if (value.startsWith('COVERED')) return 'COVERED';
  if (value.startsWith('PARTIAL')) return 'PARTIAL';
  if (value.startsWith('INSUFFICIENT')) return 'INSUFFICIENT';
  return coverage || '-';
}

function implementationBadgeStatus(implementation: string): string {
  const value = implementation.trim().toUpperCase();
  if (value.startsWith('ALIGNED')) return 'ALIGNED';
  if (value.startsWith('REVIEW')) return 'REVIEW';
  if (value.startsWith('NOT ALIGNED')) return 'NOT ALIGNED';
  return implementation || '-';
}

function cellDetail(value: string): string {
  const emDash = value.split('—')[1]?.trim();
  const start = value.indexOf('(');
  const end = value.lastIndexOf(')');
  const parenthetical = start >= 0 && end > start ? value.slice(start + 1, end).trim() : '';
  if (emDash && parenthetical) {
    const withoutParen = emDash.replace(/\s*\(.*\)\s*$/, '').trim();
    return parenthetical ? `${withoutParen} (${parenthetical})` : withoutParen;
  }
  if (emDash) return emDash.replace(/\s*\(.*\)\s*$/, '').trim();
  return parenthetical;
}

export default function QaCoverageTable({
  rows = [],
  qaStatus = null,
  coveragePercent = null,
  errors = [],
  gapReviewUpdates = [],
  gapReviewNotes = '',
}: QaCoverageTableProps) {
  const hasRun = Boolean(qaStatus || rows.length);
  if (!hasRun) {
    return null;
  }

  const changedUpdates = gapReviewUpdates.filter((item) => item.changed);

  return (
    <section className="detail-section">
      <h3 className="section-title">QA Acceptance Criteria Checks</h3>
      <div className="qa-coverage-summary">
        <span>
          QA status: <strong>{qaStatus || 'Pending'}</strong>
        </span>
        <span>
          Coverage:{' '}
          <strong>{coveragePercent == null ? '-' : `${coveragePercent}%`}</strong>
        </span>
      </div>
      {errors.length > 0 && (
        <p className="qa-coverage-errors">{errors.join('; ')}</p>
      )}
      {changedUpdates.length > 0 ? (
        <div className="qa-gap-review">
          <h4 className="qa-gap-review-title">Gap-review agent (one pass)</h4>
          {gapReviewNotes ? <p className="qa-gap-review-notes">{gapReviewNotes}</p> : null}
          <div className="table-container">
            <table className="data-table qa-gap-review-table">
              <thead>
                <tr>
                  <th>AC</th>
                  <th>Before</th>
                  <th>After</th>
                  <th>Tests before</th>
                  <th>Tests after</th>
                </tr>
              </thead>
              <tbody>
                {changedUpdates.map((item) => (
                  <tr key={item.acId}>
                    <td>{item.acId || '-'}</td>
                    <td>{item.beforeCoverage || '-'}</td>
                    <td>{item.afterCoverage || '-'}</td>
                    <td>{item.beforeTestCases || '-'}</td>
                    <td>{item.afterTestCases || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      <div className="table-container">
        <table className="data-table qa-coverage-table">
          <thead>
            <tr>
              <th>AC</th>
              <th>Source</th>
              <th>Criterion</th>
              <th>Coverage</th>
              <th>Implementation</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6}>No acceptance-criteria coverage results yet.</td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={`${row.acId || 'ac'}-${index}`}>
                  <td>{row.acId || '-'}</td>
                  <td>{row.source || '-'}</td>
                  <td>{row.criterion || '-'}</td>
                  <td>
                    <div className="qa-coverage-cell">
                      <StatusBadge status={coverageBadgeStatus(row.coverage)} />
                      {cellDetail(row.coverage) ? (
                        <span className="qa-coverage-detail">{cellDetail(row.coverage)}</span>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    <div className="qa-coverage-cell">
                      <StatusBadge status={implementationBadgeStatus(row.implementation)} />
                      {cellDetail(row.implementation) ? (
                        <span className="qa-coverage-detail">{cellDetail(row.implementation)}</span>
                      ) : null}
                    </div>
                  </td>
                  <td>{row.reason || '-'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
