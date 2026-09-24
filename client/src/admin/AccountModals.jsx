import { useEffect, useMemo, useState } from 'react';

import { useT } from '../i18n/index.js';
import { toFormError } from '../lib/api.js';
import { useAdmin } from './AdminContext.jsx';
import { LimitsEditor, PermissionPicker, formToLimits, limitPlaceholders, limitsToForm } from './forms.jsx';
import { AdminButton, Alert, Input, LoadingBlock, Modal, Select } from './ui.jsx';
import { adminErrorText, adminRequest, useAdminQuery } from './useAdminApi.js';

/**
 * Create or edit an admin account: identity, role, extra permissions and
 * (with limits.manage) usage limits. `account` is null to create.
 *
 * The pickers only offer what this admin could grant; the server applies the
 * same rule and is what actually enforces it.
 */
export const AdminFormModal = ({ open, account, onClose, onSaved }) => {
  const t = useT();
  const admin = useAdmin();
  const isEdit = Boolean(account);
  const isSelf = isEdit && account.id === admin.me?.user?.id;
  const roles = useAdminQuery(open ? '/admin/roles' : null);
  const catalogue = useAdminQuery(open ? '/admin/permissions' : null);
  const limitsQuery = useAdminQuery(open && isEdit && admin.can('limits.view') ? `/admin/limits/${account.id}` : null);

  const [form, setForm] = useState(null);
  const [limits, setLimits] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const adminRoles = useMemo(
    () => (roles.data?.roles ?? []).filter((role) => role.kind === 'admin' || (role.kind === 'super_admin' && admin.isSuperAdmin)),
    [roles.data, admin.isSuperAdmin],
  );

  // Seed the form once the roles are in.
  useEffect(() => {
    if (!open) {
      setForm(null);
      setError(null);
      return;
    }
    if (form || !adminRoles.length) return;
    setForm({
      fullName: account?.fullName ?? '',
      email: account?.email ?? '',
      temporaryPassword: '',
      roleId: account?.role?.id ?? adminRoles.find((role) => role.key === 'SUPPORT_ADMIN')?.id ?? adminRoles[0].id,
      status: 'active',
      permissions: account?.extraPermissions ?? [],
    });
  }, [open, adminRoles, account, form]);

  const initialLimits = useMemo(() => limitsToForm(limitsQuery.data?.overrides), [limitsQuery.data]);
  useEffect(() => setLimits(initialLimits), [initialLimits]);

  const role = adminRoles.find((item) => item.id === form?.roleId);
  const isSuperRole = role?.kind === 'super_admin';
  const grantable = admin.isSuperAdmin ? null : new Set(admin.me?.permissions ?? []);
  const canSetLimits = admin.can('limits.manage') && !isSelf;
  const set = (field) => (event) => setForm((previous) => ({ ...previous, [field]: event.target.value }));
  const defaults = isEdit ? limitsQuery.data?.defaults : role?.limits;

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const limitChanges = canSetLimits ? formToLimits(limits, initialLimits) : {};
      const permissions = isSuperRole ? [] : form.permissions.filter((key) => !(role?.permissions ?? []).includes(key));
      let saved;
      if (isEdit) {
        const body = { fullName: form.fullName, email: form.email };
        if (!isSelf) Object.assign(body, { roleId: form.roleId, permissions });
        saved = await adminRequest('patch', `/admin/admins/${account.id}`, body);
        if (Object.keys(limitChanges).length) await adminRequest('patch', `/admin/limits/${account.id}`, limitChanges);
      } else {
        const body = { fullName: form.fullName, email: form.email, roleId: form.roleId, status: form.status, permissions };
        if (form.temporaryPassword) body.temporaryPassword = form.temporaryPassword;
        if (Object.keys(limitChanges).length) body.limits = limitChanges;
        saved = await adminRequest('post', '/admin/admins', body);
      }
      onSaved(saved);
    } catch (failure) {
      setError(toFormError(failure));
    } finally {
      setBusy(false);
    }
  };

  const loading = !form || catalogue.status === 'loading' || (isEdit && limitsQuery.status === 'loading');

  return (
    <Modal
      open={open}
      wide
      onClose={onClose}
      title={isEdit ? t('admin.admins.editTitle', { name: account.fullName || account.email }) : t('admin.admins.createTitle')}
      footer={
        <>
          <AdminButton variant="secondary" onClick={onClose}>
            {t('admin.common.cancel')}
          </AdminButton>
          <AdminButton type="submit" form="admin-form" disabled={busy || loading}>
            {busy ? t('admin.common.saving') : isEdit ? t('admin.common.save') : t('admin.admins.create')}
          </AdminButton>
        </>
      }
    >
      {loading ? (
        <LoadingBlock />
      ) : (
        <form id="admin-form" onSubmit={submit} className="space-y-6">
          {error && !Object.keys(error.fields).length && <Alert>{adminErrorText(t, error)}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label={t('admin.users.fullName')} value={form.fullName} onChange={set('fullName')} error={error?.fields.fullName} required />
            <Input label={t('admin.users.email')} type="email" value={form.email} onChange={set('email')} error={error?.fields.email} required />
            {!isEdit && (
              <Input
                label={t('admin.users.temporaryPassword')}
                autoComplete="off"
                value={form.temporaryPassword}
                onChange={set('temporaryPassword')}
                hint={t('admin.users.temporaryPasswordHint')}
                error={error?.fields.temporaryPassword}
              />
            )}
            <Select
              label={t('admin.admins.role')}
              value={form.roleId}
              onChange={set('roleId')}
              disabled={isSelf}
              options={adminRoles.map((item) => ({ value: item.id, label: item.name }))}
            />
            {!isEdit && (
              <Select
                label={t('admin.admins.status')}
                value={form.status}
                onChange={set('status')}
                options={[
                  { value: 'active', label: t('admin.status.active') },
                  { value: 'disabled', label: t('admin.status.disabled') },
                ]}
              />
            )}
          </div>

          <section>
            <h3 className="text-lg font-bold text-navy-900">{t('admin.admins.permissionsTitle')}</h3>
            <p className="mb-3 mt-0.5 text-sm text-ink-600">
              {isSuperRole ? t('admin.admins.superAdminNote') : isSelf ? t('admin.errors.cannot_modify_self') : t('admin.admins.permissionsHint')}
            </p>
            {!isSuperRole && catalogue.data && (
              <PermissionPicker
                catalogue={catalogue.data.permissions}
                selected={form.permissions}
                locked={role?.permissions ?? []}
                grantable={grantable}
                disabled={isSelf}
                onChange={(permissions) => setForm((previous) => ({ ...previous, permissions }))}
              />
            )}
          </section>

          {canSetLimits && (
            <section>
              <h3 className="text-lg font-bold text-navy-900">{t('admin.admins.limitsTitle')}</h3>
              <p className="mb-3 mt-0.5 text-sm text-ink-600">{t('admin.admins.limitsHint')}</p>
              <LimitsEditor value={limits} onChange={setLimits} placeholders={limitPlaceholders(defaults, t)} />
            </section>
          )}
        </form>
      )}
    </Modal>
  );
};

/** One account's limit overrides; an empty field falls back to the role default. */
export const AccountLimitsModal = ({ account, onClose, onSaved }) => {
  const t = useT();
  const admin = useAdmin();
  const query = useAdminQuery(account ? `/admin/limits/${account.id}` : null);
  const initial = useMemo(() => limitsToForm(query.data?.overrides), [query.data]);
  const [value, setValue] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => setValue(initial), [initial]);
  useEffect(() => setError(null), [account]);

  const readOnly = !admin.can('limits.manage') || account?.id === admin.me?.user?.id;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const changes = formToLimits(value, initial);
      if (Object.keys(changes).length) await adminRequest('patch', `/admin/limits/${account.id}`, changes);
      onSaved?.();
      onClose();
    } catch (failure) {
      setError(toFormError(failure));
    } finally {
      setBusy(false);
    }
  };

  if (!account) return null;
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title={t('admin.limits.accountTitle', { name: account.fullName || account.email })}
      footer={
        <>
          <AdminButton variant="secondary" onClick={onClose}>
            {t('admin.common.cancel')}
          </AdminButton>
          {!readOnly && (
            <AdminButton onClick={save} disabled={busy || query.status !== 'ready'}>
              {busy ? t('admin.common.saving') : t('admin.common.save')}
            </AdminButton>
          )}
        </>
      }
    >
      {query.status === 'loading' && <LoadingBlock />}
      {query.status === 'error' && <Alert>{adminErrorText(t, query.error)}</Alert>}
      {query.data && (
        <div className="space-y-3">
          <p className="text-sm text-ink-600">{t('admin.admins.limitsHint')}</p>
          {error && <Alert>{adminErrorText(t, error)}</Alert>}
          <LimitsEditor value={value} onChange={setValue} placeholders={limitPlaceholders(query.data.defaults, t)} disabled={readOnly} />
        </div>
      )}
    </Modal>
  );
};
