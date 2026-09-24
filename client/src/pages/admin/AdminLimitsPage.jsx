import { useEffect, useMemo, useState } from 'react';

import { useAdmin } from '../../admin/AdminContext.jsx';
import { LIMIT_ROWS, LimitsEditor, formToLimits, limitsToForm } from '../../admin/forms.jsx';
import { adminErrorText, adminRequest, useAdminQuery } from '../../admin/useAdminApi.js';
import { AdminButton, Alert, Card, DataTable, ErrorBlock, KindBadge, LoadingBlock, Modal, PageHeader, useFormat } from '../../admin/ui.jsx';
import { formatBytes } from '../../lib/format.js';
import { useT } from '../../i18n/index.js';
import { toFormError } from '../../lib/api.js';

/** Platform-wide defaults: one row per role. Per-account overrides live on each account. */
export const AdminLimitsPage = () => {
  const t = useT();
  const fmt = useFormat();
  const admin = useAdmin();
  const { data, status, reload } = useAdminQuery('/admin/limits/defaults');
  const [editing, setEditing] = useState(null);

  const show = (field, value) => {
    if (value === null || value === undefined) return t('admin.common.unlimited');
    return field.endsWith('StorageBytes') ? formatBytes(value, fmt.language) : fmt.compact(value);
  };

  const mayEdit = (role) =>
    admin.can('limits.manage') &&
    (admin.isSuperAdmin || (role.kind !== 'super_admin' && role.id !== admin.me?.user?.role?.id));

  const columns = [
    {
      key: 'role',
      header: t('admin.users.columns.role'),
      render: (role) => (
        <span className="flex flex-col gap-1">
          <span className="font-semibold">{role.name}</span>
          <KindBadge kind={role.kind} />
        </span>
      ),
    },
    ...LIMIT_ROWS.map(([group, daily, monthly]) => ({
      key: group,
      header: t(`admin.limitGroup.${group}`),
      className: 'whitespace-nowrap',
      render: (role) => (
        <span className="text-sm">
          <span className="block">
            {t('admin.limitGroup.daily')}: <strong>{show(daily, role.limits[daily])}</strong>
          </span>
          <span className="block text-ink-600">
            {t('admin.limitGroup.monthly')}: {show(monthly, role.limits[monthly])}
          </span>
        </span>
      ),
    })),
    {
      key: 'actions',
      header: <span className="sr-only">{t('admin.common.actions')}</span>,
      className: 'text-right',
      render: (role) =>
        mayEdit(role) && (
          <AdminButton variant="secondary" size="sm" onClick={() => setEditing(role)}>
            {t('admin.common.edit')}
          </AdminButton>
        ),
    },
  ];

  return (
    <>
      <PageHeader title={t('admin.limits.title')} subtitle={t('admin.limits.subtitle')} />
      {status === 'loading' && <LoadingBlock />}
      {status === 'error' && <ErrorBlock onRetry={reload} />}
      {data && (
        <Card title={t('admin.limits.roleDefaults')} bodyClassName="p-0">
          <DataTable caption={t('admin.limits.roleDefaults')} columns={columns} rows={data.roles} />
        </Card>
      )}
      <RoleLimitsModal
        role={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          reload();
        }}
      />
    </>
  );
};

const RoleLimitsModal = ({ role, onClose, onSaved }) => {
  const t = useT();
  const initial = useMemo(() => limitsToForm(role?.limits), [role]);
  const [value, setValue] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    setValue(initial);
    setError(null);
  }, [initial]);

  if (!role) return null;
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const changes = formToLimits(value, initial);
      if (Object.keys(changes).length) await adminRequest('patch', `/admin/limits/defaults/${role.id}`, changes);
      onSaved();
    } catch (failure) {
      setError(toFormError(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title={t('admin.limits.editRole', { name: role.name })}
      footer={
        <>
          <AdminButton variant="secondary" onClick={onClose}>
            {t('admin.common.cancel')}
          </AdminButton>
          <AdminButton onClick={save} disabled={busy}>
            {busy ? t('admin.common.saving') : t('admin.common.save')}
          </AdminButton>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-ink-600">{t('admin.limits.emptyMeansUnlimited')}</p>
        {error && <Alert>{adminErrorText(t, error)}</Alert>}
        <LimitsEditor value={value} onChange={setValue} placeholders={{}} />
      </div>
    </Modal>
  );
};
