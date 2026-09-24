import { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';

import { useAdmin } from '../../admin/AdminContext.jsx';
import { adminErrorText, adminRequest, useAdminQuery, useDebounced } from '../../admin/useAdminApi.js';
import {
  Badge,
  Card,
  ConfirmDialog,
  DataTable,
  ErrorBlock,
  Pagination,
  PageHeader,
  RowMenu,
  SearchInput,
  Select,
  useFormat,
} from '../../admin/ui.jsx';
import { formatBytes } from '../../lib/format.js';
import { useT } from '../../i18n/index.js';
import { toFormError } from '../../lib/api.js';

const SOURCE_KINDS = ['pdf', 'image', 'youtube', 'link', 'topic', 'text', 'document'];

// section -> API list, what it needs to view and to delete
const SECTIONS = {
  sources: { path: '/admin/content/sources', view: 'content.view', manage: 'content.manage', remove: '/admin/content/sources' },
  classes: { path: '/admin/content/classes', view: 'content.view', manage: null, remove: null },
  assignments: { path: '/admin/content/assignments', view: 'assignments.view', manage: 'assignments.manage', remove: '/admin/content/assignments' },
  flashcards: { path: '/admin/content/flashcards', view: 'flashcards.view', manage: 'flashcards.manage', remove: '/admin/content/flashcards' },
};

/** /admin/content redirects to the first section this admin may open. */
export const AdminContentIndex = () => {
  const { can } = useAdmin();
  const first = [['classes', '/admin/courses'], ['sources', '/admin/pdfs'], ['assignments', '/admin/assignments'], ['flashcards', '/admin/flashcards']]
    .find(([section]) => can(SECTIONS[section].view));
  return <Navigate to={first ? first[1] : '/admin'} replace />;
};

export const AdminContentPage = ({ section }) => {
  const t = useT();
  const fmt = useFormat();
  const admin = useAdmin();
  const config = SECTIONS[section];
  const [search, setSearch] = useState('');
  const [kind, setKind] = useState('');
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState(null);
  const q = useDebounced(search);
  const params = section === 'sources' ? { q, kind, page, pageSize: 20 } : { q, page, pageSize: 20 };
  const { data, status, reload } = useAdminQuery(config.path, params);
  const canDelete = config.manage && admin.can(config.manage);

  const owner = (person) => (
    <Link to={`/admin/users/${person.id}`} className="text-navy-800 hover:underline">
      {person.name || person.email}
    </Link>
  );

  const remove = (item, name) =>
    setConfirm({
      title: t('admin.content.confirmDeleteTitle', { name }),
      body: t('admin.content.confirmDeleteBody'),
      confirmLabel: t('admin.common.delete'),
      danger: true,
      onConfirm: async () => {
        try {
          await adminRequest('delete', `${config.remove}/${item.id}`);
          reload();
        } catch (error) {
          const failure = new Error(adminErrorText(t, toFormError(error)));
          failure.text = failure.message;
          throw failure;
        }
      },
    });

  const actions = (nameOf) => ({
    key: 'actions',
    header: <span className="sr-only">{t('admin.common.actions')}</span>,
    className: 'text-right',
    render: (item) => (
      <RowMenu label={t('admin.common.actions')} items={[canDelete && { label: t('admin.common.delete'), danger: true, onClick: () => remove(item, nameOf(item)) }]} />
    ),
  });

  const created = { key: 'created', header: t('admin.content.columns.created'), render: (item) => fmt.date(item.createdAt), className: 'whitespace-nowrap' };

  const columns = {
    sources: [
      { key: 'title', header: t('admin.content.columns.title'), render: (item) => <span className="font-semibold">{item.title}</span> },
      { key: 'kind', header: t('admin.content.columns.kind'), render: (item) => <Badge>{t(`admin.content.kind.${item.kind}`)}</Badge> },
      { key: 'owner', header: t('admin.content.columns.owner'), render: (item) => owner(item.owner) },
      { key: 'kit', header: t('admin.content.columns.kit'), render: (item) => item.kitTitle, className: 'text-ink-600' },
      { key: 'status', header: t('admin.content.columns.status'), render: (item) => item.status },
      { key: 'size', header: t('admin.content.columns.size'), render: (item) => formatBytes(item.byteSize, fmt.language), className: 'whitespace-nowrap' },
      created,
      actions((item) => item.title),
    ],
    classes: [
      { key: 'title', header: t('admin.content.columns.title'), render: (item) => <span className="font-semibold">{item.title}</span> },
      { key: 'teacher', header: t('admin.content.columns.teacher'), render: (item) => owner(item.teacher) },
      { key: 'students', header: t('admin.content.columns.students'), render: (item) => fmt.number(item.studentCount) },
      { key: 'assignments', header: t('admin.content.columns.assignments'), render: (item) => fmt.number(item.assignmentCount) },
      { key: 'status', header: t('admin.content.columns.status'), render: (item) => item.status },
      created,
    ],
    assignments: [
      { key: 'title', header: t('admin.content.columns.title'), render: (item) => <span className="font-semibold">{item.title}</span> },
      { key: 'course', header: t('admin.content.columns.course'), render: (item) => item.classTitle, className: 'text-ink-600' },
      { key: 'teacher', header: t('admin.content.columns.teacher'), render: (item) => owner(item.teacher) },
      { key: 'due', header: t('admin.content.columns.due'), render: (item) => fmt.date(item.dueAt), className: 'whitespace-nowrap' },
      { key: 'submissions', header: t('admin.content.columns.submissions'), render: (item) => fmt.number(item.submissionCount) },
      created,
      actions((item) => item.title),
    ],
    flashcards: [
      { key: 'source', header: t('admin.content.columns.source'), render: (item) => <span className="font-semibold">{item.sourceTitle ?? '—'}</span> },
      { key: 'owner', header: t('admin.content.columns.owner'), render: (item) => owner(item.owner) },
      { key: 'cards', header: t('admin.content.columns.cards'), render: (item) => fmt.number(item.cardCount) },
      { key: 'language', header: t('admin.content.columns.language'), render: (item) => item.language?.toUpperCase() },
      created,
      actions((item) => item.sourceTitle ?? item.id),
    ],
  }[section];

  if (!admin.can(config.view)) return <ErrorBlock text={t('admin.errors.permission_denied')} />;

  return (
    <>
      <PageHeader title={t(`admin.content.tabs.${section}`)} subtitle={t('admin.content.subtitle')} />
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
          {section === 'sources' && (
            <Select
              label={t('admin.content.columns.kind')}
              className="sm:w-48"
              value={kind}
              onChange={(event) => {
                setKind(event.target.value);
                setPage(1);
              }}
              options={[{ value: '', label: t('admin.common.all') }, ...SOURCE_KINDS.map((value) => ({ value, label: t(`admin.content.kind.${value}`) }))]}
            />
          )}
        </div>
        {status === 'error' ? (
          <div className="p-4">
            <ErrorBlock onRetry={reload} />
          </div>
        ) : (
          <>
            <DataTable caption={t(`admin.content.tabs.${section}`)} columns={columns} rows={data?.items ?? []} loading={status !== 'ready'} />
            <Pagination page={page} pageSize={20} total={data?.total} onPage={setPage} />
          </>
        )}
      </Card>
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </>
  );
};
