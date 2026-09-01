const STORAGE_KEY = 'postLoginRedirect';

/** Persist the route to open after Microsoft sign-in (survives MSAL redirect). */
export function savePostLoginRedirect(path: string): void {
  const normalized = path.trim();
  if (!normalized || normalized === '/login') {
    return;
  }
  sessionStorage.setItem(STORAGE_KEY, normalized);
}

export function peekPostLoginRedirect(): string | null {
  return sessionStorage.getItem(STORAGE_KEY);
}

export function consumePostLoginRedirect(): string | null {
  const path = sessionStorage.getItem(STORAGE_KEY);
  if (path) {
    sessionStorage.removeItem(STORAGE_KEY);
  }
  return path;
}

export function buildReturnPath(pathname: string, search = ''): string {
  return `${pathname}${search}`;
}
