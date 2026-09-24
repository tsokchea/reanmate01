import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { api, setSessionExpiredHandler } from '../lib/api.js';
import { isDemo, loadDemoFixtures } from '../mock/mode.js';

/**
 * Holds the signed-in user and their onboarding state — the two things the
 * router needs to decide where someone belongs.
 *
 * `status` distinguishes "still checking" from "definitely signed out", which
 * matters: guarding on `user == null` alone would bounce a signed-in user to
 * login for the split second before GET /api/auth/me returns.
 */
const AuthContext = createContext(null);

/**
 * Resolved once at module load. When true the whole auth flow is served from
 * fixtures — no /api call, no cookie, mockUser signed in. See src/mock/mode.js.
 */
const DEMO = isDemo();
const DEMO_ROLE_KEY = 'reanmate.demo.role';

const readDemoRole = () => (DEMO ? window.localStorage.getItem(DEMO_ROLE_KEY) : null);

const EMPTY_ONBOARDING = {
  roleChosen: false,
  surveyAnswers: {},
  surveySkipped: false,
  completedAt: null,
};

export const AuthProvider = ({ children }) => {
  const [status, setStatus] = useState('loading'); // loading | authenticated | anonymous
  const [user, setUser] = useState(null);
  const [onboarding, setOnboarding] = useState(EMPTY_ONBOARDING);

  const applySession = useCallback((payload) => {
    setUser(payload.user);
    setOnboarding(payload.onboarding ?? EMPTY_ONBOARDING);
    setStatus('authenticated');
  }, []);

  const clearSession = useCallback(() => {
    setUser(null);
    setOnboarding(EMPTY_ONBOARDING);
    setStatus('anonymous');
  }, []);

  /** Re-reads the session from the server; the source of truth is the cookie. */
  const reload = useCallback(async () => {
    // Prototype mode never calls the API — see src/mock/mode.js.
    if (DEMO) {
      const { mockOnboarding, mockUser } = await loadDemoFixtures();
      const role = readDemoRole() ?? mockUser.role;
      const data = {
        user: { ...mockUser, role },
        onboarding: { ...mockOnboarding, roleChosen: Boolean(role) },
      };
      applySession(data);
      return data;
    }
    try {
      const { data } = await api.get('/auth/me');
      applySession(data);
      return data;
    } catch {
      clearSession();
      return null;
    }
  }, [applySession, clearSession]);

  // Lets the axios interceptor drop us to anonymous when a refresh fails,
  // rather than leaving a stale user in state while every request 401s.
  useEffect(() => {
    setSessionExpiredHandler(clearSession);
    return () => setSessionExpiredHandler(null);
  }, [clearSession]);

  useEffect(() => {
    reload();
  }, [reload]);

  const register = useCallback(
    async (payload) => {
      if (DEMO) {
        const { mockOnboarding, mockUser } = await loadDemoFixtures();
        const data = {
          user: { ...mockUser, role: payload.role },
          onboarding: { ...mockOnboarding, roleChosen: Boolean(payload.role) },
        };
        window.localStorage.setItem(DEMO_ROLE_KEY, payload.role);
        applySession(data);
        return data.user;
      }
      const { data } = await api.post('/auth/register', payload);
      // Registration returns the user but not onboarding state; read it back so
      // the router can route on a complete picture.
      setUser(data.user);
      setStatus('authenticated');
      await reload();
      return data.user;
    },
    [reload],
  );

  const login = useCallback(
    async (payload) => {
      if (DEMO) return (await reload()).user;
      const { data } = await api.post('/auth/login', payload);
      setUser(data.user);
      setStatus('authenticated');
      await reload();
      return data.user;
    },
    [reload],
  );

  const logout = useCallback(async () => {
    try {
      if (!DEMO) await api.post('/auth/logout');
      else window.localStorage.removeItem(DEMO_ROLE_KEY);
    } finally {
      // Clear locally even if the call failed — the user asked to be signed out.
      clearSession();
    }
  }, [clearSession]);

  const chooseRole = useCallback(async (role) => {
    if (DEMO) {
      const { mockUser } = await loadDemoFixtures();
      window.localStorage.setItem(DEMO_ROLE_KEY, role);
      setUser((prev) => ({ ...prev, role }));
      setOnboarding((prev) => ({ ...prev, roleChosen: true }));
      return { ...mockUser, role };
    }
    const { data } = await api.post('/onboarding/role', { role });
    setUser(data.user);
    setOnboarding((prev) => ({ ...prev, roleChosen: true }));
    return data.user;
  }, []);

  /** Replaces a temporary (or any) password; the server re-issues the session. */
  const changePassword = useCallback(
    async (payload) => {
      const { data } = await api.post('/auth/password', payload);
      setUser(data.user);
      await reload();
      return data.user;
    },
    [reload],
  );

  // The API answers 403 password_change_required when an admin has just reset
  // this account's password; re-reading the session lets the guard route to
  // the password screen.
  useEffect(() => {
    const onPasswordChange = () => reload();
    window.addEventListener('reanmate:password-change', onPasswordChange);
    return () => window.removeEventListener('reanmate:password-change', onPasswordChange);
  }, [reload]);

  const submitSurvey = useCallback(async ({ answers, skipped = false, complete = false }) => {
    if (DEMO) {
      const { mockOnboarding } = await loadDemoFixtures();
      const next = { ...mockOnboarding, surveyAnswers: { ...answers } };
      setOnboarding(next);
      return { answers: next.surveyAnswers, skipped, completedAt: next.completedAt };
    }
    const { data } = await api.post('/onboarding/survey', { answers, skipped, complete });
    setOnboarding((prev) => ({
      ...prev,
      surveyAnswers: data.survey.answers,
      surveySkipped: data.survey.skipped,
      completedAt: data.survey.completedAt,
    }));
    if (data.user) setUser(data.user);
    return data.survey;
  }, []);

  const value = useMemo(
    () => ({
      status,
      user,
      onboarding,
      isAuthenticated: status === 'authenticated',
      isLoading: status === 'loading',
      register,
      login,
      logout,
      reload,
      chooseRole,
      submitSurvey,
      changePassword,
    }),
    [status, user, onboarding, register, login, logout, reload, chooseRole, submitSurvey, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>');
  return context;
};
