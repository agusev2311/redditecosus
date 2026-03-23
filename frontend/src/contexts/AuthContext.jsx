import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { apiFetch, getStoredToken, setStoredToken } from "../api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(getStoredToken());
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [setupState, setSetupState] = useState({ loading: true, needsSetup: false });

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const setup = await apiFetch("/setup/status", { token: "" });
        if (cancelled) return;
        setSetupState({ loading: false, needsSetup: setup.needsSetup });
        if (!setup.needsSetup && token) {
          const me = await apiFetch("/auth/me", { token });
          if (!cancelled) {
            setUser(me.user);
          }
        }
      } catch {
        if (!cancelled) {
          setSetupState({ loading: false, needsSetup: false });
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function login(username, password) {
    const payload = await apiFetch("/auth/login", {
      method: "POST",
      token: "",
      body: { username, password },
    });
    setStoredToken(payload.token);
    setToken(payload.token);
    setUser(payload.user);
    setSetupState((current) => ({ ...current, needsSetup: false }));
    return payload.user;
  }

  function logout() {
    setStoredToken("");
    setToken("");
    setUser(null);
  }

  const value = useMemo(
    () => ({
      token,
      user,
      loading,
      setupState,
      login,
      logout,
      setUser,
      setSetupState,
    }),
    [token, user, loading, setupState]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
