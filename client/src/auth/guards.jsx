import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from './AuthContext.jsx';
import { isDemo } from '../mock/mode.js';
import { FullPageSpinner } from '../components/FullPageSpinner.jsx';

/**
 * The next step of the SIGNUP wizard, given how far through it the new account
 * is. Used only right after registration and to move between onboarding steps.
 *
 * Onboarding is deliberately not a gate. An existing account that never
 * finished it — or chose "I'll choose later" on the role screen — signs in
 * straight to the dashboard; being handed the same survey on every login is
 * not onboarding, it is a toll booth. The survey is optional personalisation
 * (nothing reads the answers back yet) and `users.role` is nullable by design.
 */
export const signupDestination = ({ onboarding, role }) => {
  if (role === 'teacher') return '/teacher';
  if (!onboarding.completedAt) return '/onboarding/survey/1';
  return '/';
};

export const isAdminUser = (user) => user?.role === 'admin' || user?.role === 'super_admin';

export const roleHome = (user) => {
  if (user?.must_change_password) return '/account/password';
  if (isAdminUser(user)) return '/admin';
  return user?.role === 'teacher' ? '/teacher' : '/student';
};

export const RoleHomeRedirect = () => {
  const { user } = useAuth();
  return <Navigate to={roleHome(user)} replace />;
};

/**
 * Resolved once: the auth flow either runs against the real session or it does
 * not, and that cannot change while the app is running.
 *
 * These guards enforce real redirects against the live session. Set
 * VITE_DEMO=true to get URL-reachable screens back for design review.
 */
const DEMO = isDemo();

/**
 * Hooks run before any branch so the call order is identical on every render —
 * DEMO is a build-time constant, but an early return above a hook is still a
 * rules-of-hooks violation and would break the moment it became dynamic.
 */

/** Blocks a route until the session is known, then requires one. */
export const RequireAuth = () => {
  const { isLoading, isAuthenticated, user } = useAuth();
  const location = useLocation();

  // Prototype mode: every screen stays reachable by URL for review.
  if (DEMO) return <Outlet />;
  if (isLoading) return <FullPageSpinner />;

  if (!isAuthenticated) {
    // Remember where they were headed so login can send them back.
    return <Navigate to="/auth" replace state={{ from: location.pathname }} />;
  }

  // A temporary password opens nothing but the screen that replaces it (the
  // API enforces the same).
  if (user?.must_change_password && location.pathname !== '/account/password') {
    return <Navigate to="/account/password" replace />;
  }

  return <Outlet />;
};

/**
 * The admin console. Only decides where to send people — /api/admin checks
 * every request against the account's role and permissions on its own.
 */
export const RequireAdmin = () => {
  const { isLoading, isAuthenticated, user } = useAuth();

  if (DEMO) return <Outlet />;
  if (isLoading) return <FullPageSpinner />;
  if (!isAuthenticated) return <Navigate to="/auth" replace />;
  if (!isAdminUser(user)) return <Navigate to={roleHome(user)} replace />;

  return <Outlet />;
};

export const RequireTeacher = () => {
  const { isLoading, isAuthenticated, user } = useAuth();

  if (DEMO) return <Outlet />;
  if (isLoading) return <FullPageSpinner />;
  if (!isAuthenticated) return <Navigate to="/auth" replace />;
  if (user?.role !== 'teacher') return <Navigate to={roleHome(user)} replace />;

  return <Outlet />;
};

/** Teachers do not use the student personalization and plan onboarding. */
export const RequireStudentOnboarding = () => {
  const { isLoading, isAuthenticated, user } = useAuth();

  if (DEMO) return <Outlet />;
  if (isLoading) return <FullPageSpinner />;
  if (!isAuthenticated) return <Navigate to="/auth" replace />;
  if (user?.role === 'teacher') return <Navigate to="/teacher" replace />;
  if (isAdminUser(user)) return <Navigate to="/admin" replace />;

  return <Outlet />;
};

/** Keeps a signed-in user off the auth screens. */
export const RequireGuest = () => {
  const { isLoading, isAuthenticated, user } = useAuth();

  if (DEMO) return <Outlet />;
  if (isLoading) return <FullPageSpinner />;
  if (isAuthenticated) return <Navigate to={roleHome(user)} replace />;

  return <Outlet />;
};
