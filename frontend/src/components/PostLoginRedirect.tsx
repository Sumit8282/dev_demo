import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { consumePostLoginRedirect } from '../utils/postLoginRedirect';

/** After MSAL redirect, send the user to the approval (or other) page they originally opened. */
export default function PostLoginRedirect() {
  const { isAuthenticated, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (isLoading || !isAuthenticated) {
      return;
    }

    const returnPath = consumePostLoginRedirect();
    if (!returnPath || returnPath === '/login') {
      return;
    }

    const currentPath = `${location.pathname}${location.search}`;
    if (currentPath !== returnPath) {
      navigate(returnPath, { replace: true });
    }
  }, [isAuthenticated, isLoading, location.pathname, location.search, navigate]);

  return null;
}
