import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext.jsx';
import { roleHome, signupDestination } from '../auth/guards.jsx';
import { Button, FormAlert, OptionCard, TextField } from '../components/ui.jsx';
import { Owl, Wordmark } from '../layouts/AuthLayout.jsx';
import { toFormError } from '../lib/api.js';
import { useT, useLanguage } from '../i18n/index.js';

/**
 * docs/screens/01-auth-onboarding/01-auth-signup-phone.
 *
 * That screen carries a Log in / Sign up segmented toggle, so one page serves
 * both modes rather than splitting into two near-identical screens.
 *
 * Field requirements follow the design and migration 002: email is required,
 * phone is optional. The API accepts either, but the form asks for the one the
 * design marks as required.
 */

const OAUTH_PROVIDERS = [
  { id: 'google', label: 'Google' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'facebook', label: 'Facebook' },
];

export const AuthPage = () => {
  const t = useT();
  const { language } = useLanguage();
  const navigate = useNavigate();
  // RequireAuth records where an unauthenticated visitor was headed.
  const location = useLocation();
  const { register, login } = useAuth();

  const [mode, setMode] = useState('signup');
  const [role, setRole] = useState(null);
  const [values, setValues] = useState({
    fullName: '',
    email: '',
    phone: '',
    password: '',
    identifier: '',
  });
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (field) => (event) => {
    const { value } = event.target;
    setValues((prev) => ({ ...prev, [field]: value }));
    // Clear the field's error as soon as they start fixing it.
    setErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));
  };

  const switchMode = (next) => {
    setMode(next);
    setErrors({});
    setFormError(null);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setErrors({});
    setFormError(null);

    try {
      if (mode === 'signup') {
        const user = await register({
          fullName: values.fullName,
          email: values.email || undefined,
          phone: values.phone || undefined,
          password: values.password,
          locale: language,
          role,
        });
        if (user?.role === 'teacher') {
          navigate('/teacher', { replace: true });
          return;
        }
      } else {
        const user = await login({ identifier: values.identifier, password: values.password });
        navigate(location.state?.from ?? roleHome(user), { replace: true });
        return;
      }
      // Signup continues to the optional personal study survey. Returning users
      // go to the page they requested or the dashboard.
      const destination = signupDestination({
        onboarding: { roleChosen: true, completedAt: null },
        role,
      });
      navigate(destination, { replace: true });
    } catch (error) {
      const { code, message, fields } = toFormError(error);
      setErrors(fields);
      // Only surface a form-level message when no field owns it, so the user
      // is never told the same thing twice.
      if (Object.keys(fields).length === 0) {
        setFormError(
          code === 'network'
            ? t('errors.network')
            : code === 'unauthorized'
              ? t('auth.badCredentials')
              : code === 'signups_disabled'
                ? t('auth.signupsDisabled')
                : (message ?? t('errors.generic')),
        );
      }
      setBusy(false);
    }
  };

  const isSignup = mode === 'signup';

  return (
    <main className="flex flex-1 flex-col">
      <header className="flex flex-col items-center pt-4 text-center">
        <Owl variant="default" className="size-28" />
        <Wordmark className="mt-1 text-4xl" />
        <h1 className="mt-3 text-xl font-bold text-navy-900">{t('auth.tagline')}</h1>
      </header>

      {/* Log in / Sign up toggle */}
      <div
        role="tablist"
        aria-label={t('auth.modeToggle')}
        className="mt-6 grid grid-cols-2 rounded-full bg-tint-100 p-1"
      >
        {['login', 'signup'].map((value) => (
          <button
            key={value}
            role="tab"
            type="button"
            aria-selected={mode === value}
            onClick={() => switchMode(value)}
            className={`rounded-full py-3 text-base font-semibold transition-colors ${
              mode === value ? 'bg-navy-800 text-white' : 'text-navy-800'
            }`}
          >
            {t(value === 'login' ? 'auth.logIn' : 'auth.signUp')}
          </button>
        ))}
      </div>

      {/* OAuth — rendered per the design, disabled until a provider is configured */}
      <div className="mt-5 space-y-3">
        {OAUTH_PROVIDERS.map((provider) => (
          <button
            key={provider.id}
            type="button"
            disabled
            aria-disabled="true"
            title={t('auth.oauthUnavailable')}
            className="flex w-full cursor-not-allowed items-center justify-center gap-3 rounded-full border border-tint-200 bg-white py-3.5 text-base font-semibold text-navy-900 opacity-55"
          >
            <ProviderMark id={provider.id} />
            {t('auth.continueWith', { provider: provider.label })}
          </button>
        ))}
        <p className="text-center text-sm text-ink-500">{t('auth.oauthUnavailable')}</p>
      </div>

      <div className="my-6 flex items-center gap-3" aria-hidden="true">
        <span className="h-px flex-1 bg-tint-200" />
        <span className="text-sm text-ink-500">
          {t(isSignup ? 'auth.orSignUpWithEmail' : 'auth.orLogInWithEmail')}
        </span>
        <span className="h-px flex-1 bg-tint-200" />
      </div>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <FormAlert>{formError}</FormAlert>

        {isSignup ? (
          <>
            <TextField
              label={t('auth.fullNameLabel')}
              placeholder={t('auth.fullNamePlaceholder')}
              value={values.fullName}
              onChange={set('fullName')}
              error={errors.fullName}
              autoComplete="name"
              required
            />
            <TextField
              label={t('auth.emailLabel')}
              placeholder={t('auth.emailPlaceholder')}
              type="email"
              value={values.email}
              onChange={set('email')}
              error={errors.email}
              autoComplete="email"
              required
            />
            <TextField
              label={t('auth.phoneOptionalLabel')}
              placeholder={t('auth.phonePlaceholder')}
              type="tel"
              value={values.phone}
              onChange={set('phone')}
              error={errors.phone}
              autoComplete="tel"
            />
            <div className="space-y-3" role="radiogroup" aria-label={t('onboarding.roleTitle')}>
              <p className="text-sm font-semibold text-navy-900">{t('onboarding.roleTitle')}</p>
              <OptionCard
                name="role"
                value="student"
                checked={role === 'student'}
                onChange={setRole}
                icon={<span aria-hidden="true" className="text-2xl">🎓</span>}
                title={t('onboarding.roleStudent')}
                description={t('onboarding.roleStudentHint')}
              />
              <OptionCard
                name="role"
                value="teacher"
                checked={role === 'teacher'}
                onChange={setRole}
                icon={<span aria-hidden="true" className="text-2xl">📚</span>}
                title={t('onboarding.roleTeacher')}
                description={t('onboarding.roleTeacherHint')}
              />
            </div>
          </>
        ) : (
          <TextField
            label={t('auth.identifierLabel')}
            placeholder={t('auth.identifierPlaceholder')}
            value={values.identifier}
            onChange={set('identifier')}
            error={errors.identifier}
            autoComplete="username"
            required
          />
        )}

        <TextField
          label={t(isSignup ? 'auth.createPasswordLabel' : 'auth.passwordLabel')}
          placeholder={t(isSignup ? 'auth.passwordPlaceholder' : 'auth.passwordLoginPlaceholder')}
          type="password"
          value={values.password}
          onChange={set('password')}
          error={errors.password}
          autoComplete={isSignup ? 'new-password' : 'current-password'}
          required
        />

        <Button type="submit" disabled={busy || (isSignup && !role)} className="mt-2">
          {busy ? t('common.loading') : t(isSignup ? 'auth.createAccount' : 'auth.logIn')}
        </Button>
      </form>

      <p className="mt-4 text-center text-sm text-ink-500">
        {t(isSignup ? 'auth.haveAccount' : 'auth.noAccount')}{' '}
        <button
          type="button"
          onClick={() => switchMode(isSignup ? 'login' : 'signup')}
          className="font-semibold text-navy-700"
        >
          {t(isSignup ? 'auth.logIn' : 'auth.signUp')}
        </button>
      </p>

      <p className="mt-6 text-center text-xs text-ink-400">{t('auth.termsNotice')}</p>
    </main>
  );
};

/** Brand marks, drawn inline so no external asset or network request is needed. */
const ProviderMark = ({ id }) => {
  if (id === 'google') {
    return (
      <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
        <path fill="#4285F4" d="M23 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.2a5.3 5.3 0 0 1-2.3 3.5v2.9h3.7c2.2-2 3.4-5 3.4-8.6Z" />
        <path fill="#34A853" d="M12 23.5c3.1 0 5.7-1 7.6-2.8l-3.7-2.9c-1 .7-2.3 1.1-3.9 1.1-3 0-5.5-2-6.4-4.7H1.8v3C3.7 21 7.6 23.5 12 23.5Z" />
        <path fill="#FBBC05" d="M5.6 14.2a6.9 6.9 0 0 1 0-4.4v-3H1.8a11.5 11.5 0 0 0 0 10.4l3.8-3Z" />
        <path fill="#EA4335" d="M12 5.1c1.7 0 3.2.6 4.4 1.7l3.3-3.3C17.7 1.6 15.1.5 12 .5 7.6.5 3.7 3 1.8 6.8l3.8 3c.9-2.7 3.4-4.7 6.4-4.7Z" />
      </svg>
    );
  }
  if (id === 'telegram') {
    return (
      <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
        <circle cx="12" cy="12" r="11" fill="#2AABEE" />
        <path fill="#fff" d="m6 12.2 10.3-4c.5-.2.9.1.8.8l-1.8 8.3c-.1.5-.5.7-1 .4l-2.7-2-1.3 1.3c-.2.2-.3.2-.6.2l.2-2.8 5-4.5c.2-.2 0-.3-.3-.2l-6.2 3.9-2.6-.8c-.6-.2-.6-.6.2-.9Z" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="#1877F2" />
      <path fill="#fff" d="M15.5 13.5 16 10h-3.3V7.8c0-1 .5-1.9 2-1.9h1.5V2.9S14.9 2.6 13.6 2.6c-2.6 0-4.3 1.6-4.3 4.5V10H6.3v3.5h3v8.4h3.4v-8.4h2.8Z" />
    </svg>
  );
};
