import { useState } from 'react';
import { Link } from 'react-router-dom';

import { AccountLimitsModal, AdminFormModal } from '../../admin/AccountModals.jsx';
import { useAdmin } from '../../admin/AdminContext.jsx';
import { canAct } from '../../admin/accountActions.js';
import { useAccountActions } from '../../admin/useAccountActions.jsx';
import { useAdminQuery, useDebounced } from '../../admin/useAdminApi.js';
import {
  AdminButton,
  AdminIcon,
  Badge,
  Card,
  DataTable,
  ErrorBlock,
  KindBadge,
  Pagination,
  PageHeader,
  RowMenu,
  SearchInput,
  StatusBadge,
  useFormat,
} from '../../admin/ui.jsx';
import { useT } from '../../i18n/index.js';

export const AdminAdminsPage = () => {
  const t = useT();
  const fmt = useFormat();
  const admin = useAdmin();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(null); // null closed, {} create, account edit
  const [limitsFor, setLimitsFor] = useState(null);
  const q = useDebounced(search);
  const { data, status, reload } = useAdminQuery('/admin/admins', { q, page, pageSize: 20 });
  const { itemsFor, dialogs, setSecret } = useAccountActions({ onChanged: reload });

  const columns = [
    {
      key: 'name',
      header: t('admin.admins.columns.name'),
      render: (row) => (
        <span className="flex items-center gap-2">
          <Link to={`/admin/users/${row.id}`} className="font-semibold text-navy-800 hover:underline">
            {row.fullName || row.email}
          </Link>
          {row.id === admin.me?.user?.id && <Badge tone="navy">{t('admin.common.you')}</Badge>}
        </span>
      ),
    },
    { key: 'email', header: t('admin.admins.columns.email'), render: (row) => row.email, className: 'text-ink-600' },
    {
      key: 'role',
      header: t('admin.admins.columns.role'),
      render: (row) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <KindBadge kind={row.kind} />
          <span className="text-sm text-ink-600">{row.role?.name}</span>
        </span>
      ),
    },
    { key: 'status', header: t('admin.admins.columns.status'), render: (row) => <StatusBadge status={row.status} /> },
    {
      key: 'permissions',
      header: t('admin.admins.columns.permissions'),
      render: (row) =>
        row.kind === 'super_admin'
          ? t('admin.admins.allPermissions')
          : t('admin.admins.permissionsCount', { count: row.permissions.length }),
      className: 'whitespace-nowrap',
    },
    admin.can('limits.view') && {
      key: 'limit',
      header: t('admin.admins.columns.usageLimit'),
      render: (row) => (row.limits?.dailyAiTokens == null ? t('admin.common.unlimited') : fmt.number(row.limits.dailyAiTokens)),
      className: 'whitespace-nowrap',
    },
    { key: 'created', header: t('admin.admins.columns.created'), render: (row) => fmt.date(row.createdAt), className: 'whitespace-nowrap' },
    {
      key: 'lastLogin',
      header: t('admin.admins.columns.lastLogin'),
      render: (row) => (row.lastLoginAt ? fmt.dateTime(row.lastLoginAt) : t('admin.common.never')),
      className: 'whitespace-nowrap',
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('admin.admins.columns.actions')}</span>,
      className: 'text-right',
      render: (row) => {
        const self = row.id === admin.me?.user?.id;
        const mayEdit = self || canAct(admin, row, 'edit');
        const [view, ...rest] = itemsFor(row);
        return (
          <RowMenu
            label={t('admin.admins.columns.actions')}
            items={[
              view,
              mayEdit && { label: t('admin.common.edit'), onClick: () => setEditing(row) },
              mayEdit && !self && row.kind !== 'super_admin' && {
                label: t('admin.admins.permissions'),
                onClick: () => setEditing(row),
              },
              admin.can('limits.view') && { label: t('admin.admins.limits'), onClick: () => setLimitsFor(row) },
              ...rest.slice(1),
            ]}
          />
        );
      },
    },
  ].filter(Boolean);

  return (
    <>
      <PageHeader
        title={t('admin.admins.title')}
        subtitle={t('admin.admins.subtitle')}
        actions={
          admin.can('admins.create') && (
            <AdminButton onClick={() => setEditing({})}>
              <AdminIcon name="plus" className="size-4" />
              {t('admin.admins.create')}
            </AdminButton>
          )
        }
      />
      <Card bodyClassName="p-0">
        <div className="p-4">
          <SearchInput
            className="sm:max-w-sm"
            value={search}
            onChange={(value) => {
              setSearch(value);
              setPage(1);
            }}
          />
        </div>
        {status === 'error' ? (
          <div className="p-4">
            <ErrorBlock onRetry={reload} />
          </div>
        ) : (
          <>
            <DataTable caption={t('admin.admins.title')} columns={columns} rows={data?.admins ?? []} loading={status !== 'ready'} />
            <Pagination page={page} pageSize={20} total={data?.total} onPage={setPage} />
          </>
        )}
      </Card>
      {dialogs}
      <AdminFormModal
        open={editing !== null}
        account={editing?.id ? editing : null}
        onClose={() => setEditing(null)}
        onSaved={(result) => {
          setEditing(null);
          reload();
          if (result?.temporaryPassword) {
            setSecret({
              title: t('admin.users.tempPasswordTitle'),
              body: t('admin.users.tempPasswordBody', { name: result.admin.fullName }),
              value: result.temporaryPassword,
            });
          }
        }}
      />
      <AccountLimitsModal account={limitsFor} onClose={() => setLimitsFor(null)} onSaved={reload} />
    </>
  );
};
