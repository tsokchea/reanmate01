import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useAdmin } from '../../admin/AdminContext.jsx';
import { canAct } from '../../admin/accountActions.js';
import { adminErrorText, adminRequest, useAdminQuery, useDebounced } from '../../admin/useAdminApi.js';
import {
  Card,
  ConfirmDialog,
  DataTable,
  ErrorBlock,
  KindBadge,
  Pagination,
  PageHeader,
  RowMenu,
  SearchInput,
  Select,
  UsageBar,
  useFormat,
} from '../../admin/ui.jsx';
import { formatBytes } from '../../lib/format.js';
import { useT } from '../../i18n/index.js';
import { toFormError } from '../../lib/api.js';

export const AdminUsagePage = () => {
  const t = useT();
  const fmt = useFormat();
  const admin = useAdmin();
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('');
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState(null);
  const q = useDebounced(search);
  const { data, status, reload } = useAdminQuery('/admin/usage', { q, kind, page, pageSize: 20 });

  const resetToday = (row) =>
    setConfirm({
      title: t('admin.usage.confirmResetTitle', { name: row.fullName || row.email }),
      body: t('admin.usage.confirmResetBody'),
      confirmLabel: t('admin.usage.resetToday'),
      onConfirm: async () => {
        try {
          await adminRequest('post', `/admin/usage/${row.id}/reset`);
          reload();
        } catch (error) {
          const failure = new Error(adminErrorText(t, toFormError(error)));
          failure.text = failure.message;
          throw failure;
        }
      },
    });

  const columns = [
    {
      key: 'account',
      header: t('admin.usage.columns.account'),
      render: (row) => (
        <span className="flex flex-col gap-1">
          <Link to={`/admin/users/${row.id}#usage`} className="font-semibold text-navy-800 hover:underline">
            {row.fullName || row.email || row.phone}
          </Link>
          <span className="flex items-center gap-1.5 text-sm text-ink-600">
            <KindBadge kind={row.kind} />
            {row.email}
          </span>
        </span>
      ),
    },
    {
      key: 'today',
      header: t('admin.usage.columns.tokensToday'),
      className: 'min-w-44',
      render: (row) => <UsageBar used={row.today.aiTotalTokens} limit={row.limits.dailyAiTokens} format={fmt.compact} />,
    },
    {
      key: 'month',
      header: t('admin.usage.columns.tokensMonth'),
      className: 'min-w-44',
      render: (row) => <UsageBar used={row.month.aiTotalTokens} limit={row.limits.monthlyAiTokens} format={fmt.compact} />,
    },
    { key: 'tutor', header: t('admin.usage.columns.tutorToday'), render: (row) => fmt.number(row.today.tutorMessages) },
    { key: 'uploads', header: t('admin.usage.columns.uploadsMonth'), render: (row) => fmt.number(row.month.pdfUploads) },
    {
      key: 'storage',
      header: t('admin.usage.columns.storageMonth'),
      className: 'whitespace-nowrap',
      render: (row) => formatBytes(row.month.storageBytes, fmt.language),
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('admin.common.actions')}</span>,
      className: 'text-right',
      render: (row) => (
        <RowMenu
          label={t('admin.common.actions')}
          items={[
            admin.can('usage.manage') &&
              (row.kind !== 'super_admin' || admin.isSuperAdmin) &&
              (row.id !== admin.me?.user?.id || admin.isSuperAdmin) &&
              (row.kind !== 'admin' || admin.isSuperAdmin || canAct(admin, row, 'view')) && {
                label: t('admin.usage.resetToday'),
                onClick: () => resetToday(row),
              },
          ]}
        />
      ),
    },
  ];

  const kindOptions = [
    { value: '', label: t('admin.usage.allKinds') },
    ...['student', 'teacher', 'admin', 'super_admin'].map((value) => ({ value, label: t(`admin.kind.${value}`) })),
  ];

  return (
    <>
      <PageHeader title={t('admin.usage.title')} subtitle={t('admin.usage.subtitle')} />
      <Card bodyClassName="p-0">
        <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          <SearchInput
            className="sm:max-w-sm sm:flex-1"
            value={search}
            onChange={(value) => {
              setSearch(value);
              setPage(1);
            }}
          />
          <Select
            label={t('admin.users.columns.role')}
            className="sm:w-56"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value);
              setPage(1);
            }}
            options={kindOptions}
          />
        </div>
        {status === 'error' ? (
          <div className="p-4">
            <ErrorBlock onRetry={reload} />
          </div>
        ) : (
          <>
            <DataTable caption={t('admin.usage.title')} columns={columns} rows={data?.accounts ?? []} loading={status !== 'ready'} />
            <Pagination page={page} pageSize={20} total={data?.total} onPage={setPage} />
          </>
        )}
      </Card>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </>
  );
};
