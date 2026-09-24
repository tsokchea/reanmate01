import { useCallback, useEffect, useRef, useState } from 'react';

import { api, toFormError } from '../lib/api.js';

/**
 * Data access for the admin console. Every call goes to /api/admin, where the
 * server re-checks the admin's permissions; nothing here is a security check.
 */

/** Drops empty values so a cleared filter disappears from the query string. */
export const cleanParams = (params) =>
  Object.fromEntries(
    Object.entries(params ?? {}).filter(([, value]) => value !== undefined && value !== null && value !== ''),
  );

/**
 * GET `path` with `params`, re-fetching whenever either changes.
 * `status` is loading | ready | error; `reload()` fetches again in place.
 */
export const useAdminQuery = (path, params) => {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  const key = path ? `${path}?${new URLSearchParams(cleanParams(params)).toString()}` : null;
  const latest = useRef(key);

  const load = useCallback(async () => {
    if (!key) return;
    latest.current = key;
    setState((previous) => ({ ...previous, status: previous.data ? 'refreshing' : 'loading', error: null }));
    try {
      const { data } = await api.get(key);
      // Only the newest request may land: typing in a search box fires several.
      if (latest.current === key) setState({ status: 'ready', data, error: null });
    } catch (error) {
      if (latest.current === key) setState({ status: 'error', data: null, error: toFormError(error) });
    }
  }, [key]);

  useEffect(() => {
    load();
  }, [load]);

  return { ...state, reload: load };
};

export const adminRequest = async (method, path, body) => {
  const { data } = await api.request({ method, url: path, data: body });
  return data;
};

/** An error's code as a translated sentence, falling back to the generic one. */
export const adminErrorText = (t, error) => {
  if (!error) return null;
  const code = error.code === 'conflict' && error.details?.code ? error.details.code : error.code;
  const key = `admin.errors.${code}`;
  const text = t(key);
  if (text !== key) return text;
  if (code === 'network') return t('errors.network');
  return error.message || t('admin.errors.generic');
};

/** Debounces a value — search boxes query the server, so not on every keystroke. */
export const useDebounced = (value, delay = 300) => {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
};
