import StatusBadge from './StatusBadge';
import type { QaCoverageRow, ValidationStatus } from '../types/release';

interface QaCoverageTableProps {
  rows?: QaCoverageRow[];
  qaStatus?: ValidationStatus | null;
  coveragePercent?: number | null;
  errors?: string[];
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
}: QaCoverageTableProps) {
  const hasRun = Boolean(qaStatus || rows.length);
  if (!hasRun) {
    return null;
  }

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
