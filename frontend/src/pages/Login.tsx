import { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import PortalLogo from '../components/PortalLogo';
import { azureRedirectUri } from '../config/authConfig';
import { useAuth } from '../context/AuthContext';
import { peekPostLoginRedirect, savePostLoginRedirect } from '../utils/postLoginRedirect';

function MicrosoftIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  );
}

export default function Login() {
  const { isAuthenticated, isLoading, login } = useAuth();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? '/';

  useEffect(() => {
    if (isAuthenticated) return;
    setError(null);
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <div className="login-page">
        <div className="login-card">
          <div className="auth-spinner" aria-hidden="true" />
          <p className="login-loading-text">Checking your session…</p>
        </div>
      </div>
    );
  }

  if (isAuthenticated) {
    const returnPath = peekPostLoginRedirect() ?? redirectTo;
    if (returnPath && returnPath !== '/login') {
      return (
        <div className="login-page">
          <div className="login-card">
            <div className="auth-spinner" aria-hidden="true" />
            <p className="login-loading-text">Redirecting to approval page…</p>
          </div>
        </div>
      );
    }
    return <Navigate to="/" replace />;
  }

  const handleLogin = async () => {
    setSubmitting(true);
    setError(null);
    try {
      savePostLoginRedirect(redirectTo);
      await login();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <PortalLogo size={56} />
          <div>
            <h1 className="login-title">Release Management Portal</h1>
            <p className="login-subtitle">Automated release workflow</p>
          </div>
        </div>

        <p className="login-description">
          Sign in with your Citi Microsoft account to manage releases, approvals, and deployment workflows.
        </p>

        {error && (
          <div className="form-error login-error" role="alert">
            {error}
          </div>
        )}

        <button
          type="button"
          className="btn btn-microsoft"
          onClick={() => void handleLogin()}
          disabled={submitting}
        >
          <MicrosoftIcon />
          {submitting ? 'Redirecting…' : 'Sign in with Microsoft'}
        </button>

        <p className="login-footer">
          Access is restricted to authorized team members.
        </p>

        <p className="login-azure-hint">
          Azure redirect URI for this app: <code>{azureRedirectUri}</code>
        </p>
      </div>
    </div>
  );
}
