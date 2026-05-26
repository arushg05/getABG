/**
 * getABG Auth Hook
 * Manages authentication state via httpOnly cookies (server-set).
 * Access tokens are in cookies — we can't read them client-side (by design).
 * We track user info from API responses and localStorage for display.
 */

import { useState, useEffect, useCallback, createContext, useContext } from "react";

const getApiUrl = () => {
  let base = (import.meta.env.VITE_API_URL || "http://localhost:5050/api").replace(/\/+$/, "");
  return base.endsWith("/api") ? base : `${base}/api`;
};
const API = getApiUrl();

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);       // { user_id, email, plan, verified, usage_today, daily_limit }
  const [loading, setLoading] = useState(true);  // true while checking session

  // ── Fetch current user from /auth/me (uses httpOnly cookie) ──
  const fetchMe = useCallback(async () => {
    try {
      const resp = await fetch(`${API}/auth/me`, { credentials: "include" });
      if (resp.ok) {
        const data = await resp.json();
        setUser(data);
        localStorage.setItem("getabg_user", JSON.stringify(data));
        return data;
      }

      // Access token expired — try refresh
      if (resp.status === 401) {
        const refreshResp = await fetch(`${API}/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (refreshResp.ok) {
          // Retry /me with new access token
          const retryResp = await fetch(`${API}/auth/me`, { credentials: "include" });
          if (retryResp.ok) {
            const data = await retryResp.json();
            setUser(data);
            localStorage.setItem("getabg_user", JSON.stringify(data));
            return data;
          }
        }
        // Refresh also failed — user is logged out
        setUser(null);
        localStorage.removeItem("getabg_user");
      }
    } catch (e) {
      // Network error — use cached user if available
      const cached = localStorage.getItem("getabg_user");
      if (cached) {
        try {
          setUser(JSON.parse(cached));
        } catch {
          setUser(null);
        }
      }
    }
    return null;
  }, []);

  // ── Boot: check session on mount ──
  useEffect(() => {
    fetchMe().finally(() => setLoading(false));
  }, [fetchMe]);

  // ── Auth actions ──
  const register = async (email, password) => {
    const resp = await fetch(`${API}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Registration failed");
    setUser(data);
    localStorage.setItem("getabg_user", JSON.stringify(data));
    return data;
  };

  const login = async (email, password) => {
    const resp = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Login failed");
    setUser(data);
    localStorage.setItem("getabg_user", JSON.stringify(data));
    return data;
  };

  const logout = async () => {
    try {
      await fetch(`${API}/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch (e) {
      // Proceed with local cleanup even if server call fails
    }
    setUser(null);
    localStorage.removeItem("getabg_user");
  };

  /**
   * Authenticated fetch wrapper.
   * Automatically includes credentials and retries once on 401 (token refresh).
   */
  const authFetch = useCallback(async (url, opts = {}) => {
    const doFetch = () =>
      fetch(url, {
        ...opts,
        credentials: "include",
      });

    let resp = await doFetch();

    if (resp.status === 401) {
      // Try refresh
      const refreshResp = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });

      if (refreshResp.ok) {
        const refreshData = await refreshResp.json();
        setUser((prev) => ({ ...prev, ...refreshData }));
        resp = await doFetch(); // Retry with new cookie
      } else {
        // Session dead
        setUser(null);
        localStorage.removeItem("getabg_user");
        throw new Error("Session expired. Please log in again.");
      }
    }

    return resp;
  }, []);

  const refreshUser = fetchMe;

  const value = {
    user,
    loading,
    isAuthenticated: !!user,
    isPro: user?.plan === "pro",
    register,
    login,
    logout,
    authFetch,
    refreshUser,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
