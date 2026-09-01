export function formatTime(date: Date = new Date()): string {
  return date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

export function formatDate(date: Date = new Date()): string {
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function generateReleaseId(count: number): string {
  const year = new Date().getFullYear();
  return `REL-${year}-${String(count).padStart(4, '0')}`;
}

export function generateBuildId(): string {
  const now = new Date();
  const dateStr = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
  const random = String(Math.floor(Math.random() * 999) + 1).padStart(3, '0');
  return `BUILD-${dateStr}-${random}`;
}

export function extractDeveloperFromPr(pr: string): string {
  try {
    const parts = pr.split('/');
    const repoPart = parts[parts.length - 1] || 'Developer';
    return repoPart.replace(/[^a-zA-Z0-9-_]/g, '') || 'Developer';
  } catch {
    return 'Developer';
  }
}
