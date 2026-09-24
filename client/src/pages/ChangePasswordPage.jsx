import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { roleHome } from '../auth/guards.jsx';
import { useAuth } from '../auth/AuthContext.jsx';
import { Button, FormAlert, TextField } from '../components/ui.jsx';
import { useT } from '../i18n/index.js';
import { toFormError } from '../lib/api.js';
import { Owl } from '../layouts/AuthLayout.jsx';

/**
 * Where an account with a temporary password lands (one an admin created or
 * reset). The API refuses everything else until this succeeds.
 */
export const ChangePasswordPage = () => {
  const t = useT();
  const navigate = useNavigate();
  const { changePassword, logout } = useAuth();
  const [values, setValues] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (field) => (event) => setValues((previous) => ({ ...previous, [field]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setErrors({});
    setFormError(null);
    if (values.newPassword !== values.confirmPassword) {
      setErrors({ confirmPassword: t('admin.account.mismatch') });
      return;
    }
    setBusy(true);
    try {
      const user = await changePassword({ currentPassword: values.currentPassword, newPassword: values.newPassword });
      navigate(roleHome(user), { replace: true });
    } catch (error) {
      const { code, message, fields } = toFormError(error);
      setErrors(fields);
      if (!Object.keys(fields).length) setFormError(code === 'network' ? t('errors.network') : (message ?? t('errors.generic')));
      setBusy(false);
    }
  };

  return (
    <main className="flex flex-1 flex-col">
      <header className="flex flex-col items-center pt-4 text-center">
        <Owl className="size-24" />
        <h1 className="mt-3 text-2xl font-bold text-navy-900">{t('admin.account.title')}</h1>
        <p className="mt-2 text-base text-ink-600">{t('admin.account.body')}</p>
      </header>
      <form onSubmit={submit} className="mt-8 space-y-5">
        <FormAlert>{formError}</FormAlert>
        <TextField
          label={t('admin.account.currentPassword')}
          type="password"
          autoComplete="current-password"
          value={values.currentPassword}
          onChange={set('currentPassword')}
          error={errors.currentPassword}
          required
        />
        <TextField
          label={t('admin.account.newPassword')}
          type="password"
          autoComplete="new-password"
          value={values.newPassword}
          onChange={set('newPassword')}
          error={errors.newPassword}
          required
        />
        <TextField
          label={t('admin.account.confirmPassword')}
          type="password"
          autoComplete="new-password"
          value={values.confirmPassword}
          onChange={set('confirmPassword')}
          error={errors.confirmPassword}
          required
        />
        <Button type="submit" disabled={busy}>
          {busy ? t('common.loading') : t('admin.account.submit')}
        </Button>
        <button type="button" onClick={logout} className="block w-full text-center font-semibold text-navy-700 hover:text-navy-900">
          {t('admin.nav.logout')}
        </button>
      </form>
    </main>
  );
};
