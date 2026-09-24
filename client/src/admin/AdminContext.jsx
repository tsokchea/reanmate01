import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { api } from '../lib/api.js';

/**
 * The signed-in admin's role and permissions, read from GET /api/admin/me.
 *
 * Used only to decide what to SHOW — which sidebar links, which buttons. The
 * server checks every request on its own, so a link hidden here and called by
 * hand is still refused with a 403.
 */
const AdminContext = createContext(null);

export const AdminProvider = ({ children }) => {
  const [state, setState] = useState({ status: 'loading', me: null });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get('/admin/me');
      setState({ status: 'ready', me: data });
    } catch (error) {
      setState({ status: 'error', me: null, code: error?.response?.data?.error?.code });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const value = useMemo(() => {
    const permissions = new Set(state.me?.permissions ?? []);
    return {
      ...state,
      reload: load,
      isSuperAdmin: Boolean(state.me?.isSuperAdmin),
      /** True when the admin holds ANY of `keys`. */
      can: (...keys) => keys.some((key) => permissions.has(key)),
    };
  }, [state, load]);

  return <AdminContext.Provider value={value}>{children}</AdminContext.Provider>;
};

export const useAdmin = () => {
  const context = useContext(AdminContext);
  if (!context) throw new Error('useAdmin must be used inside <AdminProvider>');
  return context;
};
