import { useEffect, useState } from 'react';

import { useAdmin } from '../../admin/AdminContext.jsx';
import { PermissionPicker } from '../../admin/forms.jsx';
import { adminErrorText, adminRequest, useAdminQuery } from '../../admin/useAdminApi.js';
import {
  AdminButton,
  AdminIcon,
  Alert,
  Badge,
  Card,
  ConfirmDialog,
  ErrorBlock,
  Input,
  LoadingBlock,
  Modal,
  PageHeader,
  Textarea,
} from '../../admin/ui.jsx';
import { useT } from '../../i18n/index.js';
import { toFormError } from '../../lib/api.js';

export const AdminRolesPage = () => {
  const t = useT();
  const admin = useAdmin();
  const roles = useAdminQuery('/admin/roles');
  const catalogue = useAdminQuery('/admin/permissions');
  const [editing, setEditing] = useState(null); // null closed, {} create, role edit
  const [confirm, setConfirm] = useState(null);
  const canManage = admin.can('roles.manage');

  const remove = (role) =>
    setConfirm({
      title: t('admin.roles.confirmDeleteTitle', { name: role.name }),
      body: t('admin.roles.confirmDeleteBody'),
      confirmLabel: t('admin.roles.delete'),
      danger: true,
      onConfirm: async () => {
        try {
          await adminRequest('delete', `/admin/roles/${role.id}`);
          roles.reload();
        } catch (error) {
          const failure = new Error(adminErrorText(t, toFormError(error)));
          failure.text = failure.message;
          throw failure;
        }
      },
    });

  // A non-super admin can only edit roles it does not hold and whose
  // permissions it already has — the server enforces the same.
  const mayEdit = (role) =>
    canManage &&
    role.editable &&
    (admin.isSuperAdmin ||
      (role.id !== admin.me?.user?.role?.id && role.permissions.every((key) => admin.me.permissions.includes(key))));

  return (
    <>
      <PageHeader
        title={t('admin.roles.title')}
        subtitle={t('admin.roles.subtitle')}
        actions={
          canManage && (
            <AdminButton onClick={() => setEditing({})}>
              <AdminIcon name="plus" className="size-4" />
              {t('admin.roles.create')}
            </AdminButton>
          )
        }
      />
      {(roles.status === 'loading' || catalogue.status === 'loading') && <LoadingBlock />}
      {(roles.status === 'error' || catalogue.status === 'error') && <ErrorBlock onRetry={roles.reload} />}
      {roles.data && catalogue.data && (
        <div className="grid gap-4 lg:grid-cols-2">
          {roles.data.roles.map((role) => (
            <Card
              key={role.id}
              title={
                <span className="flex flex-wrap items-center gap-2">
                  {role.name}
                  <Badge tone={role.isSystemRole ? 'gray' : 'navy'}>{t(role.isSystemRole ? 'admin.roles.system' : 'admin.roles.custom')}</Badge>
                  {!role.editable && (
                    <Badge tone="gray">
                      <AdminIcon name="lock" className="mr-1 size-3" />
                      {t('admin.roles.locked')}
                    </Badge>
                  )}
                </span>
              }
              actions={
                mayEdit(role) && (
                  <>
                    <AdminButton variant="secondary" size="sm" onClick={() => setEditing(role)}>
                      {t('admin.common.edit')}
                    </AdminButton>
                    {!role.isSystemRole && (
                      <AdminButton variant="dangerGhost" size="sm" onClick={() => remove(role)}>
                        {t('admin.common.delete')}
                      </AdminButton>
                    )}
                  </>
                )
              }
            >
              <p className="text-sm text-ink-600">
                <code className="font-mono text-navy-800">{role.key}</code> · {t(`admin.roles.kind.${role.kind}`)} ·{' '}
                {t('admin.roles.accounts', { count: role.userCount })}
              </p>
              {role.description && <p className="mt-2 text-base text-navy-900">{role.description}</p>}
              <div className="mt-3">
                {role.kind === 'super_admin' ? (
                  <p className="text-base text-ink-600">{t('admin.admins.superAdminNote')}</p>
                ) : role.permissions.length ? (
                  <ul className="flex flex-wrap gap-1.5">
                    {role.permissions.map((key) => (
                      <li key={key}>
                        <Badge tone="navy">{t(`admin.perm.${key}`)}</Badge>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-base text-ink-500">{t(role.editable ? 'admin.common.none' : 'admin.roles.lockedHint')}</p>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      <RoleModal
        role={editing}
        catalogue={catalogue.data?.permissions ?? []}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          roles.reload();
        }}
      />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </>
  );
};

const RoleModal = ({ role, catalogue, onClose, onSaved }) => {
  const t = useT();
  const admin = useAdmin();
  const isEdit = Boolean(role?.id);
  const [form, setForm] = useState({ name: '', key: '', description: '', permissions: [] });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!role) return;
    setForm({ name: role.name ?? '', key: role.key ?? '', description: role.description ?? '', permissions: role.permissions ?? [] });
    setError(null);
  }, [role]);

  const set = (field) => (event) => setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { name: form.name, description: form.description || null, permissions: form.permissions };
      if (isEdit) await adminRequest('patch', `/admin/roles/${role.id}`, body);
      else await adminRequest('post', '/admin/roles', { ...body, ...(form.key ? { key: form.key } : {}) });
      onSaved();
    } catch (failure) {
      setError(toFormError(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={Boolean(role)}
      wide
      onClose={onClose}
      title={isEdit ? t('admin.roles.editTitle', { name: role.name }) : t('admin.roles.createTitle')}
      footer={
        <>
          <AdminButton variant="secondary" onClick={onClose}>
            {t('admin.common.cancel')}
          </AdminButton>
          <AdminButton type="submit" form="role-form" disabled={busy}>
            {busy ? t('admin.common.saving') : isEdit ? t('admin.common.save') : t('admin.roles.create')}
          </AdminButton>
        </>
      }
    >
      <form id="role-form" onSubmit={submit} className="space-y-5">
        {error && !Object.keys(error.fields).length && <Alert>{adminErrorText(t, error)}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label={t('admin.roles.name')} value={form.name} onChange={set('name')} error={error?.fields.name} required />
          <Input
            label={t('admin.roles.key')}
            value={form.key}
            onChange={set('key')}
            disabled={isEdit}
            hint={isEdit ? undefined : t('admin.roles.keyHint')}
            error={error?.fields.key}
          />
        </div>
        <Textarea label={t('admin.roles.description')} value={form.description} onChange={set('description')} />
        <section>
          <h3 className="mb-2 text-lg font-bold text-navy-900">{t('admin.roles.permissions')}</h3>
          <PermissionPicker
            catalogue={catalogue}
            selected={form.permissions}
            grantable={admin.isSuperAdmin ? null : new Set(admin.me?.permissions ?? [])}
            onChange={(permissions) => setForm((previous) => ({ ...previous, permissions }))}
          />
        </section>
      </form>
    </Modal>
  );
};
