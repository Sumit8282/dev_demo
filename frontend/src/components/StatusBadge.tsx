import type { StatusType } from '../types/release';

interface StatusBadgeProps {
  status: string;
}

const statusClassMap: Record<string, string> = {
  Pending: 'badge-pending',
  Running: 'badge-running',
  Completed: 'badge-completed',
  Rejected: 'badge-rejected',
  Failed: 'badge-failed',
  'PR Request Raised': 'badge-running',
  Validating: 'badge-running',
  Approved: 'badge-completed',
  'RM Approved': 'badge-completed',
  'Deployment Successful': 'badge-completed',
};

function normalizeStatus(status: string): StatusType | string {
  const known: StatusType[] = ['Pending', 'Running', 'Completed', 'Rejected', 'Failed'];
  if (known.includes(status as StatusType)) return status;
  if (status === 'PR Request Raised') return 'Running';
  if (status === 'Validating') return 'Running';
  if (status === 'Approved') return 'Completed';
  return status;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = normalizeStatus(status);
  const className = statusClassMap[normalized] || statusClassMap[status] || 'badge-pending';

  return <span className={`status-badge ${className}`}>{status}</span>;
}
