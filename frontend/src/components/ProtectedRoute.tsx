import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { buildReturnPath, peekPostLoginRedirect, savePostLoginRedirect } from '../utils/postLoginRedirect';

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="auth-loading">
        <div className="auth-loading-card">
          <div className="auth-spinner" aria-hidden="true" />
          <p>Signing you in…</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    const returnPath = buildReturnPath(location.pathname, location.search);
    savePostLoginRedirect(returnPath);
    return <Navigate to="/login" replace state={{ from: returnPath }} />;
  }

  return children;
}
