/**
 * getABG — Auth Page
 * Login / Register with animated transitions and premium dark UI.
 */

import { useState } from "react";
import { useAuth } from "./useAuth.jsx";

export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "register"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (mode === "register") {
        if (password !== confirmPassword) {
          throw new Error("Passwords don't match");
        }
        if (password.length < 8) {
          throw new Error("Password must be at least 8 characters");
        }
        await register(email, password);
      } else {
        await login(email, password);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const toggleMode = () => {
    setMode(mode === "login" ? "register" : "login");
    setError(null);
    setConfirmPassword("");
  };

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "2rem",
      background: "var(--color-background-primary)",
      position: "relative",
      overflow: "hidden",
    }}>
      {/* Background gradient orbs */}
      <div style={{
        position: "absolute",
        width: 500,
        height: 500,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(56,189,248,0.08) 0%, transparent 70%)",
        top: "-15%",
        right: "-10%",
        pointerEvents: "none",
      }} />
      <div style={{
        position: "absolute",
        width: 400,
        height: 400,
        borderRadius: "50%",
        background: "radial-gradient(circle, rgba(139,92,246,0.06) 0%, transparent 70%)",
        bottom: "-10%",
        left: "-5%",
        pointerEvents: "none",
      }} />

      <div style={{
        width: "100%",
        maxWidth: 400,
        position: "relative",
        zIndex: 1,
      }}>
        {/* Logo */}
        <div style={{
          textAlign: "center",
          marginBottom: 32,
        }}>
          <div style={{
            fontSize: 28,
            fontWeight: 600,
            letterSpacing: "-0.02em",
            marginBottom: 4,
          }}>
            getABG
          </div>
          <div style={{
            fontSize: 13,
            color: "var(--color-text-tertiary)",
            letterSpacing: "0.02em",
          }}>
            Quantitative Backtesting Platform
          </div>
        </div>

        {/* Card */}
        <div style={{
          background: "var(--color-background-secondary)",
          border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "var(--border-radius-lg)",
          padding: "28px 24px",
          backdropFilter: "blur(20px)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.3), 0 0 0 0.5px rgba(255,255,255,0.05) inset",
        }}>
          {/* Tab Switcher */}
          <div style={{
            display: "flex",
            gap: 0,
            marginBottom: 24,
            background: "var(--color-background-primary)",
            borderRadius: "var(--border-radius-md)",
            padding: 3,
          }}>
            {["login", "register"].map((tab) => (
              <button
                key={tab}
                onClick={() => { setMode(tab); setError(null); }}
                style={{
                  flex: 1,
                  padding: "8px 0",
                  fontSize: 13,
                  fontWeight: 500,
                  border: "none",
                  borderRadius: 6,
                  cursor: "pointer",
                  transition: "all 0.2s ease",
                  background: mode === tab
                    ? "var(--color-background-secondary)"
                    : "transparent",
                  color: mode === tab
                    ? "var(--color-text-primary)"
                    : "var(--color-text-tertiary)",
                  boxShadow: mode === tab
                    ? "0 1px 3px rgba(0,0,0,0.2)"
                    : "none",
                }}
              >
                {tab === "login" ? "Sign In" : "Create Account"}
              </button>
            ))}
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} style={{
            display: "flex",
            flexDirection: "column",
            gap: 14,
          }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <label style={{
                fontSize: 11,
                fontWeight: 500,
                color: "var(--color-text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
                style={{ fontSize: 13, padding: "10px 12px" }}
              />
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <label style={{
                fontSize: 11,
                fontWeight: 500,
                color: "var(--color-text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}>Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? "Min 8 characters" : "••••••••"}
                required
                minLength={mode === "register" ? 8 : undefined}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
                style={{ fontSize: 13, padding: "10px 12px" }}
              />
            </div>

            {mode === "register" && (
              <div style={{
                display: "flex",
                flexDirection: "column",
                gap: 5,
                animation: "fadeIn 0.2s ease",
              }}>
                <label style={{
                  fontSize: 11,
                  fontWeight: 500,
                  color: "var(--color-text-secondary)",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}>Confirm Password</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter password"
                  required
                  autoComplete="new-password"
                  style={{ fontSize: 13, padding: "10px 12px" }}
                />
              </div>
            )}

            {error && (
              <div style={{
                background: "var(--color-background-danger)",
                color: "var(--color-text-danger)",
                borderRadius: "var(--border-radius-md)",
                padding: "8px 12px",
                fontSize: 12,
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}>
                <span style={{ fontSize: 14 }}>⚠</span>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{
                padding: "11px 0",
                fontSize: 13,
                fontWeight: 600,
                borderRadius: "var(--border-radius-md)",
                border: "none",
                cursor: loading ? "wait" : "pointer",
                background: "linear-gradient(135deg, #38BDF8, #818CF8)",
                color: "#fff",
                opacity: loading ? 0.7 : 1,
                transition: "opacity 0.2s, transform 0.1s",
                letterSpacing: "0.01em",
                marginTop: 4,
              }}
            >
              {loading
                ? (mode === "register" ? "Creating account…" : "Signing in…")
                : (mode === "register" ? "Create Account" : "Sign In")
              }
            </button>
          </form>

          {/* Toggle link */}
          <div style={{
            textAlign: "center",
            marginTop: 18,
            fontSize: 12,
            color: "var(--color-text-tertiary)",
          }}>
            {mode === "login" ? "Don't have an account?" : "Already have an account?"}{" "}
            <button
              onClick={toggleMode}
              style={{
                background: "none",
                border: "none",
                color: "var(--color-text-info)",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 500,
                padding: 0,
                textDecoration: "underline",
                textDecorationColor: "rgba(56,189,248,0.3)",
                textUnderlineOffset: 2,
              }}
            >
              {mode === "login" ? "Create one" : "Sign in"}
            </button>
          </div>
        </div>

        {/* Footer note */}
        <div style={{
          textAlign: "center",
          marginTop: 20,
          fontSize: 11,
          color: "var(--color-text-tertiary)",
          lineHeight: 1.5,
        }}>
          Free tier includes <strong style={{ color: "var(--color-text-secondary)" }}>3 backtests/day</strong>.{" "}
          Upgrade to Pro for unlimited access.
        </div>
      </div>
    </div>
  );
}
