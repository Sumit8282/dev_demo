export function jiraTicketNotFoundMessage(issueKey: string): string {
  return `Jira ticket ${issueKey} does not exist.`;
}

export function isJiraTicketNotFoundMessage(message: string): boolean {
  const lowered = message.trim().toLowerCase();
  return (
    lowered.includes('does not exist') ||
    lowered.includes('not found') ||
    lowered.includes('was not found')
  );
}

export function resolveJiraTicketNotFoundMessage(
  issueKey: string,
  errors?: string[] | null
): string {
  const canonical = jiraTicketNotFoundMessage(issueKey);
  if (errors?.some(isJiraTicketNotFoundMessage)) {
    return canonical;
  }
  return canonical;
}

export function extractJiraTicketNotFoundMessage(
  errors: string[] | undefined,
  issueKey: string
): string | null {
  if (errors?.some(isJiraTicketNotFoundMessage)) {
    return resolveJiraTicketNotFoundMessage(issueKey, errors);
  }
  return null;
}

export function resolveJiraCheckErrorMessage(
  event: { metadata?: Record<string, unknown> },
  issueKey: string
): string | null {
  const metadataMessage = event.metadata?.error_message;
  if (typeof metadataMessage === 'string' && metadataMessage.trim()) {
    return metadataMessage.trim();
  }

  const metadataErrors = event.metadata?.errors;
  if (Array.isArray(metadataErrors)) {
    const messages = metadataErrors.filter((item): item is string => typeof item === 'string');
    const notFound = extractJiraTicketNotFoundMessage(messages, issueKey);
    if (notFound) return notFound;
  }

  return null;
}

export function resolveJiraValidationFailureMessage(
  metadata: Record<string, unknown> | undefined,
  issueKey: string
): string | null {
  const metadataErrors = metadata?.errors;
  if (Array.isArray(metadataErrors)) {
    const messages = metadataErrors.filter((item): item is string => typeof item === 'string');
    const notFound = extractJiraTicketNotFoundMessage(messages, issueKey);
    if (notFound) return notFound;
    if (messages.length > 0) return messages.join('; ');
  }
  return null;
}

export function formatJiraValidationRemarks(
  validation:
    | {
        status?: string | null;
        errors?: string[] | null;
        checks?: { ticket_exists?: boolean | null } | null;
      }
    | null
    | undefined,
  issueKey: string
): string {
  if (!validation) return '-';

  const notFound = extractJiraTicketNotFoundMessage(validation.errors ?? undefined, issueKey);
  if (notFound) return notFound;
  if (!validation.checks?.ticket_exists && validation.status === 'FAIL') {
    return resolveJiraTicketNotFoundMessage(issueKey, validation.errors ?? undefined);
  }
  if (validation.errors?.length) return validation.errors.join('; ');
  if (validation.status === 'PASS') return 'Scope validated';
  if (validation.status === 'FAIL') return 'Scope validation failed';
  return 'Scope validation error';
}
