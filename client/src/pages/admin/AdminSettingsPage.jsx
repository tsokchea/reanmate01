import { useState } from 'react';

import { useAdmin } from '../../admin/AdminContext.jsx';
import { adminErrorText, adminRequest, useAdminQuery } from '../../admin/useAdminApi.js';
import { Alert, Card, ErrorBlock, LoadingBlock, PageHeader, Toggle } from '../../admin/ui.jsx';
import { useT } from '../../i18n/index.js';
import { toFormError } from '../../lib/api.js';

export const AdminSettingsPage = () => {
  const t = useT();
  const admin = useAdmin();
  const { data, status, reload } = useAdminQuery('/admin/settings');
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const canManage = admin.can('settings.manage');
  const current = settings ?? data?.settings;

  // Each switch saves on its own, so an admin never leaves with an unsaved toggle.
  const change = (name) => async (value) => {
    const previous = current;
    setSettings({ ...current, [name]: value });
    setError(null);
    setSaved(false);
    try {
      const result = await adminRequest('patch', '/admin/settings', { [name]: value });
      setSettings(result.settings);
      setSaved(true);
    } catch (failure) {
      setSettings(previous);
      setError(adminErrorText(t, toFormError(failure)));
    }
  };

  return (
    <>
      <PageHeader title={t('admin.settings.title')} subtitle={t('admin.settings.subtitle')} />
      {status === 'loading' && <LoadingBlock />}
      {status === 'error' && <ErrorBlock onRetry={reload} />}
      {current && (
        <Card className="max-w-2xl">
          <div className="space-y-3">
            {!canManage && <Alert tone="info">{t('admin.settings.readOnly')}</Alert>}
            {error && <Alert>{error}</Alert>}
            <div className="divide-y divide-tint-100">
              <Toggle
                label={t('admin.settings.usageLimitsEnabled')}
                description={t('admin.settings.usageLimitsHint')}
                checked={current.usageLimitsEnabled}
                disabled={!canManage}
                onChange={change('usageLimitsEnabled')}
              />
              <Toggle
                label={t('admin.settings.signupsEnabled')}
                description={t('admin.settings.signupsHint')}
                checked={current.signupsEnabled}
                disabled={!canManage}
                onChange={change('signupsEnabled')}
              />
            </div>
            <p role="status" className="text-sm text-ink-600">
              {saved ? t('admin.common.saved') : ''}
            </p>
          </div>
        </Card>
      )}
    </>
  );
};
