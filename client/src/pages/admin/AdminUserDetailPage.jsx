import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';

import { AccountLimitsModal, AdminFormModal } from '../../admin/AccountModals.jsx';
import { useAdmin } from '../../admin/AdminContext.jsx';
import { canAct } from '../../admin/accountActions.js';
import { LIMIT_ROWS } from '../../admin/forms.jsx';
import { useAccountActions } from '../../admin/useAccountActions.jsx';
import { adminErrorText, adminRequest, useAdminQuery } from '../../admin/useAdminApi.js';
import {
  AdminButton,
  AdminIcon,
  Alert,
  Badge,
  Card,
  ErrorBlock,
  Input,
  KindBadge,
  LoadingBlock,
  Modal,
  PageHeader,
  RowMenu,
  Select,
  StatusBadge,
  UsageBar,
  useFormat,
} from '../../admin/ui.jsx';
import { formatBytes } from '../../lib/format.js';
import { useT } from '../../i18n/index.js';
import { toFormError } from '../../lib/api.js';

// usage field for each limit row (the limit rows come from forms.jsx)
const USAGE_FOR = {
  ai: 'aiTotalTokens',
  uploads: 'pdfUploads',
  assignments: 'assignmentsCreated',
  flashcards: 'flashcardsCreated',
  tutor: 'tutorMessages',
  storage: 'storageBytes',
};

export const AdminUserDetailPage = () => {
  const t = useT();
  const fmt = useFormat();
  const admin = useAdmin();
  const { userId } = useParams();
  const { hash } = useLocation();
  const { data, status, error, reload } = useAdminQuery(`/admin/users/${userId}`);
  const [editing, setEditing] = useState(false);
  const [limitsOpen, setLimitsOpen] = useState(false);
  const { itemsFor, dialogs } = useAccountActions({ onChanged: reload, onDeleted: () => window.history.back() });

  useEffect(() => {
    if (data && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: 'start' });
  }, [data, hash]);

  const back = (
    <Link to="/admin/users" className="mb-2 inline-flex items-center gap-1 text-sm font-semibold text-navy-700 hover:underline">
      <AdminIcon name="chevronLeft" className="size-4" />
      {t('admin.userDetail.back')}
    </Link>
  );

  if (status === 'loading') return <LoadingBlock />;
  if (status === 'error') return <>{back}<ErrorBlock text={adminErrorText(t, error)} onRetry={reload} /></>;

  const user = data.user;
  const isAdminAccount = user.kind === 'admin' || user.kind === 'super_admin';
  const isSelf = user.id === admin.me?.user?.id;
  const mayEdit = isSelf ? isAdminAccount && admin.can('admins.edit') : canAct(admin, user, 'edit');
  const formatValue = (group) => (value) => (group === 'storage' ? formatBytes(value, fmt.language) : fmt.number(value));

  return (
    <>
      <PageHeader
        back={back}
        title={user.fullName || user.email || user.phone}
        subtitle={user.email || user.phone}
        actions={
          <>
            {mayEdit && (
              <AdminButton variant="secondary" onClick={() => setEditing(true)}>
                {isAdminAccount ? t('admin.userDetail.manageAdmin') : t('admin.userDetail.editProfile')}
              </AdminButton>
            )}
            <RowMenu label={t('admin.common.actions')} items={itemsFor(user, { includeView: false }).slice(1)} />
          </>
        }
      />

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title={t('admin.userDetail.profile')} className="xl:col-span-1">
          <dl className="space-y-3 text-base">
            <Row label={t('admin.userDetail.role')}>
              <span className="flex flex-wrap items-center gap-1.5">
                <KindBadge kind={user.kind} />
                <span className="text-ink-600">{user.role?.name}</span>
              </span>
            </Row>
            <Row label={t('admin.userDetail.status')}>
              <span className="flex flex-wrap items-center gap-1.5">
                <StatusBadge status={user.status} />
                {user.mustChangePassword && <Badge tone="gold">{t('admin.userDetail.mustChange')}</Badge>}
              </span>
            </Row>
            <Row label={t('admin.userDetail.email')}>{user.email || '—'}</Row>
            <Row label={t('admin.userDetail.phone')}>{user.phone || '—'}</Row>
            <Row label={t('admin.userDetail.created')}>{fmt.dateTime(user.createdAt)}</Row>
            <Row label={t('admin.userDetail.lastLogin')}>{user.lastLoginAt ? fmt.dateTime(user.lastLoginAt) : t('admin.common.never')}</Row>
            <Row label={t('admin.userDetail.lastSeen')}>{user.lastSeenAt ? fmt.dateTime(user.lastSeenAt) : t('admin.common.never')}</Row>
          </dl>
          {isAdminAccount && (
            <div className="mt-5 border-t border-tint-100 pt-4">
              <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-ink-500">{t('admin.userDetail.permissions')}</h3>
              {user.kind === 'super_admin' ? (
                <p className="text-base text-ink-600">{t('admin.admins.superAdminNote')}</p>
              ) : (
                <ul className="flex flex-wrap gap-1.5">
                  {user.permissions.map((key) => (
                    <li key={key}>
                      <Badge tone={user.extraPermissions?.includes(key) ? 'gold' : 'navy'}>{t(`admin.perm.${key}`)}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Card>

        {data.usage && (
          <Card
            title={t('admin.userDetail.usage')}
            className="xl:col-span-2"
            actions={
              data.limits && (
                <AdminButton variant="secondary" size="sm" onClick={() => setLimitsOpen(true)}>
                  {admin.can('limits.manage') && !isSelf ? t('admin.userDetail.editLimits') : t('admin.userDetail.limits')}
                </AdminButton>
              )
            }
          >
            <div id="usage" className="relative overflow-x-auto">
              <table className="w-full min-w-[32rem] text-left text-base">
                <thead>
                  <tr className="text-xs font-bold uppercase tracking-wide text-ink-500">
                    <th scope="col" className="pb-2 pr-4" />
                    <th scope="col" className="pb-2 pr-4">{t('admin.userDetail.today')}</th>
                    <th scope="col" className="pb-2">{t('admin.userDetail.month')}</th>
                  </tr>
                </thead>
                <tbody>
                  {LIMIT_ROWS.map(([group, daily, monthly]) => {
                    const field = USAGE_FOR[group];
                    return (
                      <tr key={group} className="border-t border-tint-100 align-top">
                        <th scope="row" className="py-3 pr-4 font-semibold text-navy-900">{t(`admin.limitGroup.${group}`)}</th>
                        <td className="w-2/5 py-3 pr-4">
                          <UsageBar used={data.usage.today[field]} limit={data.limits?.effective[daily]} format={formatValue(group)} />
                        </td>
                        <td className="w-2/5 py-3">
                          <UsageBar used={data.usage.month[field]} limit={data.limits?.effective[monthly]} format={formatValue(group)} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-sm text-ink-600">
              {t('admin.userDetail.storageTotal')}: {formatBytes(data.usage.storageBytesTotal, fmt.language)}
            </p>
          </Card>
        )}
      </div>

      {data.activity && (
        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <ActivityCard
            title={t('admin.userDetail.recentAi')}
            items={data.activity.ai}
            render={(item) => [`${item.kind} · ${item.model ?? ''}`, t('admin.userDetail.tokens', { count: item.totalTokens ?? 0 }), item.createdAt]}
          />
          <ActivityCard
            title={t('admin.userDetail.recentUploads')}
            items={data.activity.uploads}
            render={(item) => [item.title, `${item.kitTitle} · ${formatBytes(item.byteSize, fmt.language)}`, item.createdAt]}
          />
          <ActivityCard
            title={t('admin.userDetail.recentAssignments')}
            items={data.activity.assignments}
            render={(item) => [item.title, `${item.classTitle} · ${t(`admin.userDetail.relation.${item.relation}`)}`, item.at]}
          />
          <ActivityCard
            title={t('admin.userDetail.recentLogins')}
            items={data.activity.logins}
            render={(item) => [item.ipAddress ?? '—', item.userAgent ?? '', item.createdAt]}
          />
        </div>
      )}

      {data.audit && (
        <Card title={t('admin.userDetail.auditTrail')} className="mt-6" bodyClassName="p-0">
          {data.audit.length ? (
            <ul className="divide-y divide-tint-100">
              {data.audit.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
                  <span className="font-semibold text-navy-900">{t(`admin.audit.action.${entry.action}`)}</span>
                  <span className="text-sm text-ink-600">
                    {entry.actor ?? t('admin.audit.system')} · {fmt.dateTime(entry.createdAt)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-5 py-6 text-ink-500">{t('admin.userDetail.noActivity')}</p>
          )}
        </Card>
      )}

      {dialogs}
      {isAdminAccount ? (
        <AdminFormModal
          open={editing}
          account={user}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            reload();
          }}
        />
      ) : (
        <EditUserModal
          open={editing}
          user={user}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            reload();
          }}
        />
      )}
      <AccountLimitsModal account={limitsOpen ? user : null} onClose={() => setLimitsOpen(false)} onSaved={reload} />
    </>
  );
};

const Row = ({ label, children }) => (
  <div className="flex items-start justify-between gap-4">
    <dt className="text-ink-600">{label}</dt>
    <dd className="min-w-0 text-right font-medium text-navy-900">{children}</dd>
  </div>
);

const ActivityCard = ({ title, items, render }) => {
  const t = useT();
  const fmt = useFormat();
  return (
    <Card title={title} bodyClassName="p-0">
      {items.length ? (
        <ul className="divide-y divide-tint-100">
          {items.map((item) => {
            const [primary, secondary, at] = render(item);
            return (
              <li key={`${item.id}-${at}`} className="flex items-start justify-between gap-3 px-5 py-2.5">
                <span className="min-w-0">
                  <span className="block truncate font-medium text-navy-900">{primary}</span>
                  <span className="block truncate text-sm text-ink-600">{secondary}</span>
                </span>
                <span className="shrink-0 text-sm text-ink-500">{fmt.dateTime(at)}</span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="px-5 py-6 text-ink-500">{t('admin.userDetail.noActivity')}</p>
      )}
    </Card>
  );
};

const EditUserModal = ({ open, user, onClose, onSaved }) => {
  const t = useT();
  const admin = useAdmin();
  const [form, setForm] = useState({ fullName: '', email: '', phone: '', role: 'student' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (open) {
      setForm({ fullName: user.fullName ?? '', email: user.email ?? '', phone: user.phone ?? '', role: user.kind });
      setError(null);
    }
  }, [open, user]);

  const set = (field) => (event) => setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body = {};
    if (form.fullName !== (user.fullName ?? '')) body.fullName = form.fullName;
    if (form.email !== (user.email ?? '') && form.email) body.email = form.email;
    if (form.phone !== (user.phone ?? '') && form.phone) body.phone = form.phone;
    if (form.role !== user.kind) body.role = form.role;
    try {
      if (Object.keys(body).length) await adminRequest('patch', `/admin/users/${user.id}`, body);
      onSaved();
    } catch (failure) {
      setError(toFormError(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('admin.userDetail.editProfile')}
      footer={
        <>
          <AdminButton variant="secondary" onClick={onClose}>
            {t('admin.common.cancel')}
          </AdminButton>
          <AdminButton type="submit" form="edit-user" disabled={busy}>
            {busy ? t('admin.common.saving') : t('admin.common.save')}
          </AdminButton>
        </>
      }
    >
      <form id="edit-user" onSubmit={submit} className="space-y-4">
        {error && !Object.keys(error.fields).length && <Alert>{adminErrorText(t, error)}</Alert>}
        <Input label={t('admin.users.fullName')} value={form.fullName} onChange={set('fullName')} error={error?.fields.fullName} />
        <Input label={t('admin.users.email')} type="email" value={form.email} onChange={set('email')} error={error?.fields.email} />
        <Input label={t('admin.users.phone')} type="tel" value={form.phone} onChange={set('phone')} error={error?.fields.phone} />
        {admin.can('users.edit') && (
          <Select
            label={t('admin.users.accountType')}
            value={form.role}
            onChange={set('role')}
            options={[
              { value: 'student', label: t('admin.kind.student') },
              { value: 'teacher', label: t('admin.kind.teacher') },
            ]}
          />
        )}
      </form>
    </Modal>
  );
};
