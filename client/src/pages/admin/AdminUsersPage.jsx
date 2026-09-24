import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useAdmin } from '../../admin/AdminContext.jsx';
import { useAccountActions } from '../../admin/useAccountActions.jsx';
import { adminErrorText, adminRequest, useAdminQuery, useDebounced } from '../../admin/useAdminApi.js';
import {
  AdminButton,
  AdminIcon,
  Alert,
  Card,
  DataTable,
  ErrorBlock,
  Input,
  KindBadge,
  Modal,
  Pagination,
  PageHeader,
  RowMenu,
  SearchInput,
  Select,
  StatusBadge,
  Tabs,
  useFormat,
} from '../../admin/ui.jsx';
import { useT } from '../../i18n/index.js';
import { toFormError } from '../../lib/api.js';

// Which permissions show each tab — the server applies the same rule to the query.
const TABS = [
  { value: 'all', need: ['users.view', 'students.view', 'teachers.view', 'admins.view'] },
  { value: 'students', need: ['users.view', 'students.view'] },
  { value: 'teachers', need: ['users.view', 'teachers.view'] },
  { value: 'admins', need: ['admins.view'] },
  { value: 'disabled', need: ['users.view', 'students.view', 'teachers.view', 'admins.view'] },
];

/**
 * /admin/users with tabs, and — with `fixedTab` — the Students and Teachers
 * pages, which are the same list pinned to one kind.
 */
export const AdminUsersPage = ({ fixedTab }) => {
  const t = useT();
  const fmt = useFormat();
  const admin = useAdmin();
  const tabs = TABS.filter((tab) => admin.can(...tab.need));
  const [tab, setTab] = useState(fixedTab ?? 'all');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('created');
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const q = useDebounced(search);
  const activeTab = fixedTab ?? tab;

  const { data, status, reload } = useAdminQuery('/admin/users', { tab: activeTab, q, sort, page, pageSize: 20 });
  const { itemsFor, dialogs, setSecret } = useAccountActions({ onChanged: reload });

  const title = fixedTab ? t(`admin.users.${fixedTab}Title`) : t('admin.users.title');

  const columns = [
    {
      key: 'name',
      header: t('admin.users.columns.name'),
      render: (user) => (
        <Link to={`/admin/users/${user.id}`} className="font-semibold text-navy-800 hover:underline">
          {user.fullName || user.email || user.phone}
        </Link>
      ),
    },
    { key: 'email', header: t('admin.users.columns.email'), render: (user) => user.email || user.phone || t('admin.users.noEmail'), className: 'text-ink-600' },
    {
      key: 'role',
      header: t('admin.users.columns.role'),
      render: (user) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <KindBadge kind={user.kind} />
          {(user.kind === 'admin' || user.kind === 'super_admin') && <span className="text-sm text-ink-600">{user.role?.name}</span>}
        </span>
      ),
    },
    { key: 'status', header: t('admin.users.columns.status'), render: (user) => <StatusBadge status={user.status} /> },
    { key: 'created', header: t('admin.users.columns.created'), render: (user) => fmt.date(user.createdAt), className: 'whitespace-nowrap' },
    {
      key: 'lastLogin',
      header: t('admin.users.columns.lastLogin'),
      render: (user) => (user.lastLoginAt ? fmt.dateTime(user.lastLoginAt) : t('admin.common.never')),
      className: 'whitespace-nowrap',
    },
    {
      key: 'ai',
      header: t('admin.users.columns.aiUsage'),
      render: (user) =>
        t('admin.users.aiTodayMonth', { today: fmt.compact(user.aiUsage?.todayTokens ?? 0), month: fmt.compact(user.aiUsage?.monthTokens ?? 0) }),
      className: 'whitespace-nowrap',
    },
    {
      key: 'actions',
      header: <span className="sr-only">{t('admin.users.columns.actions')}</span>,
      render: (user) => <RowMenu label={t('admin.users.columns.actions')} items={itemsFor(user)} />,
      className: 'text-right',
    },
  ];

  return (
    <>
      <PageHeader
        title={title}
        subtitle={t('admin.users.subtitle')}
        actions={
          admin.can('users.create') && (
            <AdminButton onClick={() => setCreating(true)}>
              <AdminIcon name="plus" className="size-4" />
              {t('admin.users.create')}
            </AdminButton>
          )
        }
      />
      <Card bodyClassName="p-0">
        {!fixedTab && tabs.length > 1 && (
          <div className="px-4 pt-2">
            <Tabs
              label={title}
              value={tab}
              onChange={(value) => {
                setTab(value);
                setPage(1);
              }}
              tabs={tabs.map((item) => ({ value: item.value, label: t(`admin.users.tabs.${item.value}`) }))}
            />
          </div>
        )}
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
            label={t('admin.users.sort.label')}
            className="sm:w-48"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
            options={['created', 'name', 'lastLogin', 'aiUsage'].map((value) => ({ value, label: t(`admin.users.sort.${value}`) }))}
          />
        </div>
        {status === 'error' ? (
          <div className="p-4">
            <ErrorBlock onRetry={reload} />
          </div>
        ) : (
          <>
            <DataTable caption={title} columns={columns} rows={data?.users ?? []} loading={status !== 'ready'} />
            <Pagination page={page} pageSize={20} total={data?.total} onPage={setPage} />
          </>
        )}
      </Card>
      {dialogs}
      <CreateUserModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(result) => {
          setCreating(false);
          reload();
          if (result.temporaryPassword) {
            setSecret({
              title: t('admin.users.tempPasswordTitle'),
              body: t('admin.users.tempPasswordBody', { name: result.user.fullName }),
              value: result.temporaryPassword,
            });
          }
        }}
      />
    </>
  );
};

const EMPTY = { fullName: '', email: '', phone: '', role: 'student', temporaryPassword: '' };

const CreateUserModal = ({ open, onClose, onCreated }) => {
  const t = useT();
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (field) => (event) => setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const close = () => {
    setForm(EMPTY);
    setError(null);
    onClose();
  };

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries(form).filter(([, value]) => value !== ''));
      const result = await adminRequest('post', '/admin/users', body);
      setForm(EMPTY);
      onCreated(result);
    } catch (failure) {
      setError(toFormError(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title={t('admin.users.createTitle')}
      footer={
        <>
          <AdminButton variant="secondary" onClick={close}>
            {t('admin.common.cancel')}
          </AdminButton>
          <AdminButton type="submit" form="create-user" disabled={busy}>
            {busy ? t('admin.common.saving') : t('admin.users.create')}
          </AdminButton>
        </>
      }
    >
      <form id="create-user" onSubmit={submit} className="space-y-4">
        {error && !Object.keys(error.fields).length && <Alert>{adminErrorText(t, error)}</Alert>}
        <Input label={t('admin.users.fullName')} value={form.fullName} onChange={set('fullName')} error={error?.fields.fullName} required />
        <Input label={t('admin.users.email')} type="email" value={form.email} onChange={set('email')} error={error?.fields.email} />
        <Input label={t('admin.users.phone')} type="tel" value={form.phone} onChange={set('phone')} error={error?.fields.phone} />
        <Select
          label={t('admin.users.accountType')}
          value={form.role}
          onChange={set('role')}
          options={[
            { value: 'student', label: t('admin.kind.student') },
            { value: 'teacher', label: t('admin.kind.teacher') },
          ]}
        />
        <Input
          label={t('admin.users.temporaryPassword')}
          type="text"
          autoComplete="off"
          value={form.temporaryPassword}
          onChange={set('temporaryPassword')}
          hint={t('admin.users.temporaryPasswordHint')}
          error={error?.fields.temporaryPassword}
        />
      </form>
    </Modal>
  );
};
