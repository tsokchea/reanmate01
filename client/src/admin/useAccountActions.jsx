import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useT } from '../i18n/index.js';
import { useAdmin } from './AdminContext.jsx';
import { canAct } from './accountActions.js';
import { ConfirmDialog, SecretDialog } from './ui.jsx';
import { adminErrorText, adminRequest } from './useAdminApi.js';
import { toFormError } from '../lib/api.js';

/**
 * Disable / enable / delete / reset password for one account, each behind a
 * confirmation. Returns the menu items to show for an account (only the ones
 * this admin may attempt) and the dialogs to render once.
 */
export const useAccountActions = ({ onChanged, onDeleted } = {}) => {
  const t = useT();
  const admin = useAdmin();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(null);
  const [secret, setSecret] = useState(null);

  const run = (request) => async () => {
    try {
      return await request();
    } catch (error) {
      const failure = new Error(adminErrorText(t, toFormError(error)));
      failure.text = failure.message;
      throw failure;
    }
  };

  const nameOf = (account) => account.fullName || account.email || account.phone;

  const itemsFor = (account, { includeView = true } = {}) => {
    const name = nameOf(account);
    const base = account.kind === 'admin' || account.kind === 'super_admin' ? 'admins' : 'users';
    return [
      includeView && { label: t('admin.common.view'), onClick: () => navigate(`/admin/users/${account.id}`) },
      admin.can('usage.view') && {
        label: t('admin.users.viewUsage'),
        onClick: () => navigate(`/admin/users/${account.id}#usage`),
      },
      canAct(admin, account, 'disable') && account.status === 'active' && {
        label: t('admin.users.disable'),
        danger: true,
        onClick: () =>
          setConfirm({
            title: t('admin.users.confirmDisableTitle', { name }),
            body: t('admin.users.confirmDisableBody'),
            confirmLabel: t('admin.users.disable'),
            danger: true,
            onConfirm: run(async () => {
              await adminRequest('post', `/admin/users/${account.id}/disable`);
              onChanged?.();
            }),
          }),
      },
      canAct(admin, account, 'disable') && account.status === 'disabled' && {
        label: t('admin.users.enable'),
        onClick: () =>
          setConfirm({
            title: t('admin.users.confirmEnableTitle', { name }),
            body: t('admin.users.confirmEnableBody'),
            confirmLabel: t('admin.users.enable'),
            onConfirm: run(async () => {
              await adminRequest('post', `/admin/users/${account.id}/enable`);
              onChanged?.();
            }),
          }),
      },
      canAct(admin, account, 'edit') && {
        label: t('admin.users.resetPassword'),
        onClick: () =>
          setConfirm({
            title: t('admin.users.confirmResetTitle', { name }),
            body: t('admin.users.confirmResetBody'),
            confirmLabel: t('admin.users.resetPassword'),
            danger: true,
            onConfirm: run(async () => {
              const result = await adminRequest('post', `/admin/users/${account.id}/reset-password`);
              setSecret({
                title: t('admin.users.tempPasswordTitle'),
                body: t('admin.users.tempPasswordBody', { name }),
                value: result.temporaryPassword,
              });
              onChanged?.();
            }),
          }),
      },
      canAct(admin, account, 'delete') && {
        label: base === 'admins' ? t('admin.admins.delete') : t('admin.users.delete'),
        danger: true,
        onClick: () =>
          setConfirm({
            title: t('admin.users.confirmDeleteTitle', { name }),
            body: t('admin.users.confirmDeleteBody'),
            confirmLabel: t('admin.common.delete'),
            danger: true,
            onConfirm: run(async () => {
              await adminRequest('delete', `/admin/${base}/${account.id}`);
              (onDeleted ?? onChanged)?.();
            }),
          }),
      },
    ];
  };

  const dialogs = (
    <>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
    </>
  );

  return { itemsFor, dialogs, setSecret };
};
