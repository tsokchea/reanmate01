import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { AdminProvider, useAdmin } from '../admin/AdminContext.jsx';
import { AdminButton, AdminIcon, Badge, ErrorBlock, LoadingBlock, cx } from '../admin/ui.jsx';
import { useAuth } from '../auth/AuthContext.jsx';
import { LanguageSwitcher, useT } from '../i18n/index.js';
import { BrandLogo } from './AuthLayout.jsx';

/**
 * The admin console shell: a sidebar of sections, filtered to what the
 * signed-in admin may open, beside a wide content column.
 *
 * `need` lists the permissions a link needs (any one of them). Hiding a link
 * is only a courtesy — every page's API calls are checked on the server.
 */
export const ADMIN_NAV = [
  { items: [{ to: '/admin', labelKey: 'admin.nav.dashboard', icon: 'dashboard', end: true, need: [] }] },
  {
    headingKey: 'admin.nav.sectionPeople',
    items: [
      { to: '/admin/users', labelKey: 'admin.nav.users', icon: 'users', need: ['users.view', 'students.view', 'teachers.view', 'admins.view'] },
      { to: '/admin/students', labelKey: 'admin.nav.students', icon: 'student', need: ['users.view', 'students.view'] },
      { to: '/admin/teachers', labelKey: 'admin.nav.teachers', icon: 'teacher', need: ['users.view', 'teachers.view'] },
      { to: '/admin/admins', labelKey: 'admin.nav.admins', icon: 'shield', need: ['admins.view'] },
    ],
  },
  {
    headingKey: 'admin.nav.sectionContent',
    items: [
      { to: '/admin/courses', labelKey: 'admin.nav.courses', icon: 'course', need: ['content.view'] },
      { to: '/admin/pdfs', labelKey: 'admin.nav.pdfs', icon: 'file', need: ['content.view'] },
      { to: '/admin/assignments', labelKey: 'admin.nav.assignments', icon: 'assignment', need: ['assignments.view'] },
      { to: '/admin/flashcards', labelKey: 'admin.nav.flashcards', icon: 'cards', need: ['flashcards.view'] },
    ],
  },
  {
    headingKey: 'admin.nav.sectionUsage',
    items: [
      { to: '/admin/usage', labelKey: 'admin.nav.usage', icon: 'usage', need: ['usage.view'] },
      { to: '/admin/limits', labelKey: 'admin.nav.limits', icon: 'limits', need: ['limits.view'] },
    ],
  },
  {
    headingKey: 'admin.nav.sectionSystem',
    items: [
      { to: '/admin/roles', labelKey: 'admin.nav.roles', icon: 'key', need: ['roles.view', 'roles.manage'] },
      { to: '/admin/audit-logs', labelKey: 'admin.nav.auditLogs', icon: 'audit', need: ['audit.view'] },
      { to: '/admin/settings', labelKey: 'admin.nav.settings', icon: 'settings', need: ['settings.view', 'settings.manage'] },
    ],
  },
];

const Sidebar = ({ onNavigate }) => {
  const t = useT();
  const { can, me } = useAdmin();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const user = me?.user;

  const sections = ADMIN_NAV.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.need.length || can(...item.need)),
  })).filter((section) => section.items.length);

  const signOut = async () => {
    await logout();
    navigate('/auth', { replace: true });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 px-5 pb-4 pt-5">
        <BrandLogo className="h-9 max-w-[9rem]" />
        <Badge tone="navy">{t('admin.kind.admin')}</Badge>
      </div>
      <nav aria-label={t('admin.nav.label')} className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        {sections.map((section, index) => (
          <div key={section.headingKey ?? index} className="mt-4 first:mt-0">
            {section.headingKey && (
              <p className="px-3 pb-1.5 text-xs font-bold uppercase tracking-wider text-ink-500">{t(section.headingKey)}</p>
            )}
            <ul className="space-y-0.5">
              {section.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cx(
                        'flex items-center gap-3 rounded-field px-3 py-2 text-base font-semibold transition-colors',
                        isActive ? 'bg-tint-100 text-navy-900' : 'text-ink-600 hover:bg-canvas hover:text-navy-800',
                      )
                    }
                  >
                    <AdminIcon name={item.icon} className="size-5 shrink-0" />
                    <span className="truncate">{t(item.labelKey)}</span>
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className="border-t border-tint-200 p-4">
        <div className="flex items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-full bg-navy-800 text-base font-bold text-white" aria-hidden="true">
            {(user?.fullName || user?.email || '?').slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-semibold text-navy-900">{user?.fullName || user?.email}</p>
            <p className="truncate text-sm text-ink-600">{user?.role?.name}</p>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between gap-2">
          <LanguageSwitcher className="rounded-field border border-tint-200 bg-white px-3 py-1.5 text-sm font-semibold text-navy-700 hover:bg-tint-100" />
          <AdminButton variant="ghost" size="sm" onClick={signOut}>
            <AdminIcon name="logout" className="size-4" />
            {t('admin.nav.logout')}
          </AdminButton>
        </div>
      </div>
    </div>
  );
};

const Shell = () => {
  const t = useT();
  const { status, reload } = useAdmin();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => setDrawerOpen(false), [pathname]);

  return (
    <div className="min-h-dvh bg-canvas lg:flex">
      <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 border-r border-tint-200 bg-white lg:block">
        {status === 'ready' && <Sidebar />}
      </aside>

      {/* Phone and tablet: a top bar and an off-canvas drawer. */}
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-tint-200 bg-white px-4 py-2.5 lg:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label={t('admin.nav.openMenu')}
          className="grid size-10 place-items-center rounded-field text-navy-800 hover:bg-tint-100"
        >
          <AdminIcon name="menu" className="size-6" />
        </button>
        <p className="font-bold text-navy-900">{t('admin.consoleTitle')}</p>
        <span className="size-10" aria-hidden="true" />
      </div>
      {drawerOpen && status === 'ready' && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button type="button" aria-label={t('admin.nav.closeMenu')} className="absolute inset-0 bg-navy-900/40" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-white shadow-xl">
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {status === 'loading' && <LoadingBlock />}
          {status === 'error' && <ErrorBlock onRetry={reload} />}
          {status === 'ready' && <Outlet />}
        </div>
      </main>
    </div>
  );
};

export const AdminLayout = () => (
  <AdminProvider>
    <Shell />
  </AdminProvider>
);

/** Page-level courtesy gate: explains a missing permission instead of showing a broken page. */
export const RequirePermission = ({ need, children }) => {
  const t = useT();
  const { can } = useAdmin();
  if (need.length && !can(...need)) {
    return <ErrorBlock text={t('admin.errors.permission_denied')} />;
  }
  return children;
};
