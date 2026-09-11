import StatusBadge from './StatusBadge';
import type { QaGeneratedTestRow } from '../types/release';

interface QaGeneratedTestsTableProps {
  rows?: QaGeneratedTestRow[];
  repo?: string;
  sha?: string;
}

export default function QaGeneratedTestsTable({
  rows = [],
  repo = '',
  sha = '',
}: QaGeneratedTestsTableProps) {
  if (!rows.length) {
    return null;
  }

  const passed = rows.filter((row) => row.status === 'PASS').length;

  return (
    <section className="detail-section">
      <h3 className="section-title">Generated Tests (PASS/FAIL)</h3>
      <div className="qa-coverage-summary">
        <span>
          Generated: <strong>{rows.length}</strong>
        </span>
        <span>
          PASS: <strong>{passed}</strong>
        </span>
        <span>
          FAIL: <strong>{rows.length - passed}</strong>
        </span>
        {repo ? (
          <span>
            GitHub: <strong>{repo}{sha ? `@${sha.slice(0, 7)}` : ''}</strong>
          </span>
        ) : null}
      </div>
      <div className="table-container">
        <table className="data-table qa-coverage-table">
          <thead>
            <tr>
              <th>AC</th>
              <th>Generated test</th>
              <th>Test file</th>
              <th>Summary</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.acId}-${row.generatedTest}-${index}`}>
                <td>{row.acId}</td>
                <td>
                  <div className="qa-coverage-cell">
                    <StatusBadge status={row.status} />
                    <span className="qa-coverage-detail">{row.generatedTest}</span>
                  </div>
                </td>
                <td>{row.testFile}</td>
                <td>{row.summary}</td>
                <td>{row.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
