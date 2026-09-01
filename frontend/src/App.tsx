import { useState } from 'react';
import { BrowserRouter, Route, Routes, useNavigate } from 'react-router-dom';
import Layout, { type OutletContextType } from './components/Layout';
import NewReleaseModal from './components/NewReleaseModal';
import ProtectedRoute from './components/ProtectedRoute';
import PostLoginRedirect from './components/PostLoginRedirect';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ReleaseProvider, useReleases } from './context/ReleaseContext';
import ApprovalQueue from './pages/ApprovalQueue';
import L3ApprovalDetails from './pages/L3ApprovalDetails';
import Login from './pages/Login';
import RMApprovalDetails from './pages/RMApprovalDetails';
import ReleaseDashboard from './pages/ReleaseDashboard';
import ReleaseDetails from './pages/ReleaseDetails';
import type { NewReleaseForm } from './types/release';
import './index.css';

function AppRoutes() {
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const { createRelease } = useReleases();
  const { user } = useAuth();
  const navigate = useNavigate();

  const outletContext: OutletContextType = {
    onNewRelease: () => {
      setSubmitError(null);
      setModalOpen(true);
    },
  };

  const handleCreateRelease = async (form: NewReleaseForm) => {
    if (!user) return;

    setSubmitting(true);
    setSubmitError(null);
    try {
      const release = await createRelease(form, user.name);
      setModalOpen(false);
      navigate(`/release/${release.id}`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to create release');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <PostLoginRedirect />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout outletContext={outletContext} />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<ReleaseDashboard />} />
          <Route path="/release/:id" element={<ReleaseDetails />} />
          <Route path="/approvals" element={<ApprovalQueue />} />
          <Route path="/approvals/l3/:id" element={<L3ApprovalDetails />} />
          <Route path="/approvals/rm/:id" element={<RMApprovalDetails />} />
        </Route>
      </Routes>
      <NewReleaseModal
        isOpen={modalOpen}
        onClose={() => {
          if (!submitting) setModalOpen(false);
        }}
        onSubmit={handleCreateRelease}
        submitting={submitting}
        submitError={submitError}
      />
    </>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ReleaseProvider>
          <AppRoutes />
        </ReleaseProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
