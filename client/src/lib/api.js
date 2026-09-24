import axios from 'axios';

/**
 * Where the API lives. Defaults to same-origin `/api` (the Vite dev proxy, or
 * the Vercel rewrite in production). Set VITE_API_URL — e.g.
 * http://localhost:4000/api — to call the API directly; its CORS allowlist
 * must then include this app's origin.
 */
// `import.meta.env` only exists under Vite; plain Node (the unit tests) has none.
export const API_BASE_URL = (import.meta.env?.VITE_API_URL || '/api').replace(/\/+$/, '');

/**
 * The only axios instance the app uses.
 *
 * withCredentials is mandatory: the JWT lives in an httpOnly cookie, so the
 * browser must be told to send it. Without this every request is anonymous and
 * the failure looks like a broken session rather than a missing flag.
 */
export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

/** Set by AuthContext so the interceptor can hand off a hard logout. */
let onSessionExpired = null;
export const setSessionExpiredHandler = (handler) => {
  onSessionExpired = handler;
};

// Endpoints that must never trigger a refresh-and-retry: refresh failing is the
// signal the session is gone, and retrying login would replay credentials.
const NO_RETRY = ['/auth/refresh', '/auth/login', '/auth/logout', '/auth/register'];

/**
 * One refresh in flight at a time. Without this, a screen firing three requests
 * that all 401 would fire three refreshes — and since refresh rotates the token,
 * the second and third would present an already-revoked one and log the user out.
 */
let refreshInFlight = null;

const refreshSession = () => {
  refreshInFlight ??= api
    .post('/auth/refresh')
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error;

    const planCode = response?.data?.error?.code ?? response?.data?.error;
    if (planCode === 'quota_exceeded' || planCode === 'feature_unavailable') {
      window.dispatchEvent(new CustomEvent('reanmate:plan-wall', { detail: { code: planCode } }));
    }
    // Per-account usage limits an admin sets (DAILY_AI_LIMIT_REACHED, ...).
    if (typeof planCode === 'string' && /^(DAILY|MONTHLY)_[A-Z]+_LIMIT_REACHED$/.test(planCode)) {
      window.dispatchEvent(
        new CustomEvent('reanmate:usage-limit', { detail: { code: planCode, ...response.data.error.details } }),
      );
    }
    if (planCode === 'password_change_required') {
      window.dispatchEvent(new CustomEvent('reanmate:password-change'));
    }

    if (!response || response.status !== 401 || !config) {
      return Promise.reject(error);
    }

    const path = (config.url ?? '').replace(config.baseURL ?? '', '');
    if (NO_RETRY.some((p) => path.startsWith(p))) {
      return Promise.reject(error);
    }

    // Retry once, never twice — a loop here would hammer the API.
    if (config.__retried) {
      onSessionExpired?.();
      return Promise.reject(error);
    }
    config.__retried = true;

    try {
      await refreshSession();
    } catch (refreshError) {
      onSessionExpired?.();
      return Promise.reject(refreshError);
    }

    return api(config);
  },
);

/**
 * Normalises the server's { error: { code, message, details } } envelope into
 * something a form can render.
 *
 * zod rejections (422) carry a `details` array of { path, message }. Turning
 * those into per-field messages is what stops a strictObject rejection — a
 * misspelled survey answer, say — from looking like nothing happened.
 */
export const toFormError = (error) => {
  const payload = error?.response?.data?.error;

  if (!payload) {
    return { code: 'network', message: null, fields: {} };
  }

  const fields = {};

  if (Array.isArray(payload.details)) {
    for (const detail of payload.details) {
      // "answers.improveFirst" -> improveFirst, so the field owns its message.
      const key = String(detail.path ?? '').split('.').pop();
      if (key && !fields[key]) fields[key] = detail.message;
    }
  }

  // 409s name the clashing field directly.
  if (payload.details?.field) {
    fields[payload.details.field] = payload.message;
  }

  return {
    code: payload.code ?? 'unknown',
    message: payload.message ?? null,
    fields,
    // Structured details pass through untouched so a caller can read what the
    // code implies — quota_exceeded carries { used, limit }, file_too_large
    // carries { limit }. Array details are already flattened into `fields`.
    details: Array.isArray(payload.details) ? {} : (payload.details ?? {}),
  };
};
