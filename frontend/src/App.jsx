import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import Shell from "./components/Shell";
import { useAuth } from "./contexts/AuthContext";
import DashboardPage from "./pages/DashboardPage";
import DuplicatesPage from "./pages/DuplicatesPage";
import LibraryPage from "./pages/LibraryPage";
import LoginPage from "./pages/LoginPage";
import ReviewPage from "./pages/ReviewPage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import ShareViewPage from "./pages/ShareViewPage";
import SharesPage from "./pages/SharesPage";
import ShortsPage from "./pages/ShortsPage";
import TagsPage from "./pages/TagsPage";
import UploadPage from "./pages/UploadPage";
import UsersPage from "./pages/UsersPage";

function LoadingScreen() {
  return (
    <div className="fullscreen-center">
      <div className="glass splash-card">
        <p className="eyebrow">mediahub</p>
        <h1>Поднимаю библиотеку…</h1>
      </div>
    </div>
  );
}

function ProtectedLayout() {
  const { user, loading, setupState } = useAuth();
  const location = useLocation();
  if (loading || setupState.loading) {
    return <LoadingScreen />;
  }
  if (setupState.needsSetup && location.pathname !== "/setup") {
    return <Navigate to="/setup" replace />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <Shell />;
}

export default function App() {
  const { loading, setupState, user } = useAuth();

  if (loading || setupState.loading) {
    return <LoadingScreen />;
  }

  return (
    <Routes>
      <Route path="/share/:token" element={<ShareViewPage />} />
      <Route
        path="/setup"
        element={setupState.needsSetup ? <SetupPage /> : <Navigate to={user ? "/" : "/login"} replace />}
      />
      <Route
        path="/login"
        element={!setupState.needsSetup && !user ? <LoginPage /> : <Navigate to="/" replace />}
      />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/shorts" element={<ShortsPage />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/tags" element={<TagsPage />} />
        <Route path="/duplicates" element={<DuplicatesPage />} />
        <Route path="/shares" element={<SharesPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
