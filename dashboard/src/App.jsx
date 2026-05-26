import { AuthProvider, useAuth } from "./useAuth.jsx";
import AuthPage from "./AuthPage";
import Dashboard from "./Dashboard";

function AppContent() {
  const { isAuthenticated, loading } = useAuth();

  // Show nothing while checking auth session
  if (loading) {
    return (
      <div style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--color-background-primary)",
      }}>
        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 12,
        }}>
          <div style={{
            fontSize: 20,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}>getABG</div>
          <div style={{
            width: 24,
            height: 24,
            border: "2px solid var(--color-border-tertiary)",
            borderTopColor: "var(--color-text-info)",
            borderRadius: "50%",
            animation: "spin 0.8s linear infinite",
          }} />
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <AuthPage />;
  }

  return <Dashboard />;
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}

export default App;
