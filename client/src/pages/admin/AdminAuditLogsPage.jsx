import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';

import { useAdminQuery, useDebounced } from '../../admin/useAdminApi.js';
import { AdminButton, Badge, Card, ErrorBlock, Input, Pagination, PageHeader, Select, useFormat } from '../../admin/ui.jsx';
import { useT } from '../../i18n/index.js';

const EMPTY = { from: '', to: '', actor: '', action: '', target: '' };

// Date inputs give a local day; the API wants an instant. `to` is inclusive of that day.
const startOf = (day) => (day ? new Date(`${day}T00:00:00`).toISOString() : undefined);
const endOf = (day) => (day ? new Date(new Date(`${day}T00:00:00`).getTime() + 86_400_000).toISOString() : undefined);

export const AdminAuditLogsPage = () => {
  const t = useT();
  const fmt = useFormat();
  const [filters, setFilters] = useState(EMPTY);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const actor = useDebounced(filters.actor);
  const target = useDebounced(filters.target);
  const { data, status, reload } = useAdminQuery('/admin/audit-logs', {
    from: startOf(filters.from),
    to: endOf(filters.to),
    actor,
    target,
    action: filters.action,
    page,
    pageSize: 25,
  });

  const set = (field) => (event) => {
    setFilters((previous) => ({ ...previous, [field]: event.target.value }));
    setPage(1);
  };
  const tone = (action) =>
    /DELETED|DISABLED|DENIED/.test(action) ? 'red' : /CREATED|ENABLED/.test(action) ? 'green' : /PERMISSION|LIMIT|ROLE/.test(action) ? 'gold' : 'navy';

  return (
    <>
      <PageHeader title={t('admin.audit.title')} subtitle={t('admin.audit.subtitle')} />
      <Card bodyClassName="p-0">
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-6 lg:items-end">
          <Input label={t('admin.audit.filters.from')} type="date" value={filters.from} onChange={set('from')} />
          <Input label={t('admin.audit.filters.to')} type="date" value={filters.to} onChange={set('to')} />
          <Input label={t('admin.audit.filters.admin')} value={filters.actor} onChange={set('actor')} />
          <Select
            label={t('admin.audit.filters.action')}
            value={filters.action}
            onChange={set('action')}
            options={[
              { value: '', label: t('admin.audit.filters.anyAction') },
              ...(data?.actions ?? []).map((action) => ({ value: action, label: t(`admin.audit.action.${action}`) })),
            ]}
          />
          <Input label={t('admin.audit.filters.target')} value={filters.target} onChange={set('target')} />
          <AdminButton
            variant="ghost"
            onClick={() => {
              setFilters(EMPTY);
              setPage(1);
            }}
          >
            {t('admin.audit.filters.clear')}
          </AdminButton>
        </div>
        {status === 'error' ? (
          <div className="p-4">
            <ErrorBlock onRetry={reload} />
          </div>
        ) : (
          <>
            <div className="relative overflow-x-auto">
              <table className={`min-w-full text-left text-base ${status !== 'ready' ? 'opacity-60' : ''}`}>
                <caption className="sr-only">{t('admin.audit.title')}</caption>
                <thead>
                  <tr className="border-b border-tint-200 bg-canvas text-xs font-bold uppercase tracking-wide text-ink-500">
                    {['date', 'admin', 'action', 'target', 'ip', 'details'].map((column) => (
                      <th key={column} scope="col" className="whitespace-nowrap px-4 py-2.5">
                        {t(`admin.audit.columns.${column}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(data?.logs ?? []).map((log) => (
                    <Fragment key={log.id}>
                      <tr className="border-b border-tint-100">
                        <td className="whitespace-nowrap px-4 py-3 text-ink-600">{fmt.dateTime(log.createdAt)}</td>
                        <td className="px-4 py-3">
                          {log.actorId ? (
                            <Link to={`/admin/users/${log.actorId}`} className="text-navy-800 hover:underline">
                              {log.actor}
                            </Link>
                          ) : (
                            <span className="text-ink-600">{log.actor ?? t('admin.audit.system')}</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Badge tone={tone(log.action)}>{t(`admin.audit.action.${log.action}`)}</Badge>
                        </td>
                        <td className="px-4 py-3 text-navy-900">{log.target ?? (log.resource ? `${log.resource} ${log.resourceId ?? ''}` : '—')}</td>
                        <td className="whitespace-nowrap px-4 py-3 font-mono text-sm text-ink-600">{log.ipAddress ?? '—'}</td>
                        <td className="px-4 py-3">
                          <AdminButton variant="ghost" size="sm" aria-expanded={open === log.id} onClick={() => setOpen(open === log.id ? null : log.id)}>
                            {open === log.id ? t('admin.audit.hide') : t('admin.audit.show')}
                          </AdminButton>
                        </td>
                      </tr>
                      {open === log.id && (
                        <tr className="border-b border-tint-100 bg-canvas">
                          <td colSpan={6} className="px-4 py-3">
                            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-sm text-navy-900">
                              {JSON.stringify({ resource: log.resource, resourceId: log.resourceId, userAgent: log.userAgent, ...log.metadata }, null, 2)}
                            </pre>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                  {status === 'ready' && !data?.logs.length && (
                    <tr>
                      <td colSpan={6} className="px-4 py-12 text-center text-ink-500">
                        {t('admin.common.empty')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={25} total={data?.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
};
