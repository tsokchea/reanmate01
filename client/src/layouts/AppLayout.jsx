import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext.jsx';
import { useT } from '../i18n/index.js';

/**
 * Shell for the signed-in app: a scrolling body above a fixed bottom tab bar,
 * capped near a phone width because every screen in docs/screens/ is a phone
 * mockup.
 *
 * The tab set is not fixed — docs/screens/02-dashboard/01 shows four tabs and
 * the Classes variant shows five — so `Classes` appears only for a user who has
 * one. The prototype user is a student with a class, so it shows.
 */

const STUDENT_TABS = [
  { to: '/', labelKey: 'nav.home', Icon: HomeIcon, end: true },
  { to: '/kits', labelKey: 'nav.kits', Icon: KitsIcon },
  { to: '/classes', labelKey: 'nav.classes', Icon: ClassesIcon },
  { to: '/assistant', labelKey: 'nav.assistant', Icon: AssistantIcon },
  { to: '/profile', labelKey: 'nav.profile', Icon: ProfileIcon },
];

/**
 * A teacher does not have study kits; they have classes to run and work to
 * mark, which is what the reference draws along the bottom of every teacher
 * screen.
 *
 * These live here rather than on each teacher page because there is exactly one
 * tab bar per app. The teacher dashboard used to draw its own on top of this
 * one, which is why that screen showed two.
 */
const TEACHER_TABS = [
  { to: '/teacher', labelKey: 'teacher.home', Icon: HomeIcon, end: true },
  { to: '/teacher/classes', labelKey: 'teacher.classesNav', Icon: ClassesIcon },
  { to: '/teacher/assignments', labelKey: 'teacher.assignmentsNav', Icon: AssignmentsIcon },
  { to: '/teacher/assistant', labelKey: 'teacher.assistantNav', Icon: AssistantIcon },
  { to: '/teacher/profile', labelKey: 'teacher.profileNav', Icon: ProfileIcon },
];

export const AppLayout = () => {
  const t = useT();
  const { pathname } = useLocation();
  const { user } = useAuth();
  // Holds the code, not a boolean: a countable cap and a plan-gated feature are
  // different messages, and showing "you have reached your free limit" for a
  // Plus-only feature tells the user to delete things that are not the problem.
  const [planWall, setPlanWall] = useState(null);
  useEffect(() => {
    const show = (event) => setPlanWall(event.detail?.code ?? 'quota_exceeded');
    window.addEventListener('reanmate:plan-wall', show);
    return () => window.removeEventListener('reanmate:plan-wall', show);
  }, []);
  // A usage limit is not a plan upsell: it is an allowance, and it resets.
  const [usageLimit, setUsageLimit] = useState(null);
  useEffect(() => {
    const show = (event) => setUsageLimit(event.detail?.code ?? null);
    window.addEventListener('reanmate:usage-limit', show);
    return () => window.removeEventListener('reanmate:usage-limit', show);
  }, []);

  // Immersive screens (quiz, flashcards, tutor) own the full height and hide
  // the tab bar, matching the screenshots where it is absent.
  const immersive = /^\/(quiz|flashcards|tutor|study|practice)\b/.test(pathname);

  // Role first, path second: a teacher keeps their own tabs on the shared
  // screens (assistant, profile), and anyone who opens a /teacher URL gets a
  // bar whose tabs actually go somewhere.
  const tabs = user?.role === 'teacher' || pathname.startsWith('/teacher')
    ? TEACHER_TABS
    : STUDENT_TABS;

  return (
    <div className="min-h-dvh bg-canvas">
      <div className="mx-auto flex min-h-dvh w-full max-w-[26rem] flex-col bg-canvas">
        {planWall && <div className="sticky top-0 z-30 flex items-center gap-3 bg-gold-400 px-4 py-3 text-sm font-semibold text-navy-900"><span className="flex-1">{t(planWall === 'feature_unavailable' ? 'plan.featureWall' : 'kits.quotaTitle')}</span><Link to="/" className="underline">{t('profile.upgrade')}</Link><button type="button" onClick={() => setPlanWall(null)} aria-label={t('common.close')}>×</button></div>}
        {usageLimit && (
          <div role="alert" className="sticky top-0 z-30 flex items-center gap-3 bg-danger-50 px-4 py-3 text-sm font-semibold text-danger-600">
            <span className="flex-1">{t(`usageLimits.${usageLimit}`)}</span>
            <button type="button" onClick={() => setUsageLimit(null)} aria-label={t('common.close')}>×</button>
          </div>
        )}
        <div className={immersive ? 'min-h-0 flex-1 overflow-y-auto' : 'min-h-0 flex-1 overflow-y-auto pb-24'}>
          <Outlet />
        </div>

        {!immersive && (
          <nav
            aria-label={t('nav.home')}
            className="fixed bottom-0 z-20 w-full max-w-[26rem] border-t border-tint-200 bg-white/95 backdrop-blur"
          >
            <ul className="flex items-stretch justify-around px-1 pb-[env(safe-area-inset-bottom)]">
              {tabs.map(({ to, labelKey, Icon, end }) => (
                <li key={to} className="flex-1">
                  {/*
                    The reference tints every icon the same brand blue and sets
                    every label in black — the active tab is marked by a filled
                    icon, not by colour. NavLink still sets aria-current, so the
                    state is announced even though it is not a colour change.
                  */}
                  <NavLink
                    to={to}
                    end={end}
                    className="flex flex-col items-center gap-1 py-2.5 text-xs font-bold"
                  >
                    {({ isActive }) => (
                      <>
                        <span className="text-brand-600">
                          <Icon filled={isActive} />
                        </span>
                        <span className="text-ink-900">{t(labelKey)}</span>
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>
    </div>
  );
};

/**
 * Navy hero used at the top of Home, Kits and Classes.
 *
 * The bottom edge is rounded and the fill is the `.hero-panel` gradient plus
 * its clipped facet — see index.css. The canvas shows through at the corners,
 * so the panel reads as a card rather than a painted edge.
 *
 * `isolate` opens the stacking context that keeps that facet (z-index -1)
 * above the gradient but behind the content.
 */
export const NavyHeader = ({ children, className = '', ...props }) => (
  <header
    className={`hero-panel relative isolate overflow-hidden rounded-b-3xl px-5 pb-7 pt-6 text-white ${className}`}
    {...props}
  >
    {children}
  </header>
);

/**
 * Header for the kits flow — a back arrow over a title whose last word is gold,
 * with the open-book mark at the right. `tile` places an icon ahead of the
 * title (a kit's folder) and `meta` a line beneath it (its material count).
 *
 * The gold accent is the title's last space-separated word. Khmer writes
 * without spaces between words, so a Khmer title has no last word to find; it
 * renders entirely white rather than splitting at a meaningless point.
 *
 * `splitAccent` turns that accent off. A file name is not a phrase — "keys.pdf"
 * picked out in gold reads as a mistake — so the screens headed by one of those
 * rather than a kit title pass false.
 */
export const KitsHeader = ({ to = '/', title, meta, tile, action, splitAccent = true, className = '', ...props }) => {
  const t = useT();
  const cut = splitAccent ? title.trimEnd().lastIndexOf(' ') : -1;
  const lead = cut === -1 ? title : title.slice(0, cut);
  const accent = cut === -1 ? null : title.slice(cut + 1);

  return (
    <header
      className={`hero-panel relative isolate overflow-hidden rounded-b-3xl px-5 pb-7 pt-5 text-white ${className}`}
      {...props}
    >
      {/* The reference puts a ⋮ opposite the back arrow on the kit header;
          `action` is that slot, and screens without one keep the bare arrow. */}
      <div className="flex items-start justify-between gap-3">
        <Link
          to={to}
          aria-label={t('common.back')}
          className="-ml-1 inline-flex rounded-lg p-1 transition-opacity hover:opacity-80"
        >
          <svg viewBox="0 0 24 24" className="size-7" fill="none" aria-hidden="true">
            <path
              d="M11 5 4 12l7 7M4.5 12H20"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </Link>
        {action}
      </div>

      <div className="mt-2 flex items-center gap-3">
        {tile}
        <div className="min-w-0 flex-1">
          <h1 className="text-[1.95rem] font-extrabold leading-[1.1] tracking-tight">
            {lead}
            {accent && (
              <>
                {' '}
                <span className="text-gold-300">{accent}</span>
              </>
            )}
          </h1>
          {meta && <p className="mt-0.5 text-base font-semibold text-white/85">{meta}</p>}
        </div>
        <img
          src="/brand/reanmate-logo-open-book.png"
          alt=""
          aria-hidden="true"
          className="h-[5.25rem] w-auto shrink-0 object-contain drop-shadow-sm"
        />
      </div>
    </header>
  );
};

/** The kit folder tile that sits ahead of a kit title in the header. */
export const KitFolderTile = () => (
  <span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-white/25 text-white/95 shadow-sm">
    <svg viewBox="0 0 24 24" className="size-8" fill="none" aria-hidden="true">
      <path
        d="M3 7a2 2 0 0 1 2-2h4.6l2 2.4H19a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
        fill="currentColor"
        fillOpacity="0.55"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  </span>
);

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.9,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
};

function HomeIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true" {...stroke} fill={filled ? 'currentColor' : 'none'}>
      <path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
    </svg>
  );
}

function KitsIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true" {...stroke} fill={filled ? 'currentColor' : 'none'}>
      <path d="M3 8h18v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M3 8l2-4h14l2 4M10 12h4" stroke="currentColor" fill="none" />
    </svg>
  );
}

/**
 * A group of three, not the book the old tab bar used — the reference nav
 * draws Classes as people. The outer shoulder arcs keep `fill="none"` so the
 * filled (active) variant solidifies the heads without closing those arcs into
 * lozenges.
 */
function ClassesIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true" {...stroke} fill={filled ? 'currentColor' : 'none'}>
      <circle cx="12" cy="7" r="3.3" />
      <path d="M6.5 20.3a5.5 5.5 0 0 1 11 0z" />
      <circle cx="4.4" cy="10.4" r="2.2" />
      <circle cx="19.6" cy="10.4" r="2.2" />
      <path d="M1 18.8a3.5 3.5 0 0 1 4.3-3.4M23 18.8a3.5 3.5 0 0 0-4.3-3.4" stroke="currentColor" fill="none" />
    </svg>
  );
}

function AssistantIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true" {...stroke} fill={filled ? 'currentColor' : 'none'}>
      <rect x="4" y="5" width="16" height="13" rx="3" />
      <path d="M8 21v-3M16 21v-3M9 5V3M15 5V3" />
      <circle cx="9" cy="11" r="1.2" fill="currentColor" />
      <circle cx="15" cy="11" r="1.2" fill="currentColor" />
      <path d="M9 15h6" />
    </svg>
  );
}

/** Assignments: a marked-up page, for the teacher's review queue. */
function AssignmentsIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" className="size-6" fill="none" aria-hidden="true">
      <path
        d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinejoin="round"
      />
      <path
        d="M14 3v5h5"
        stroke={filled ? '#fff' : 'currentColor'}
        strokeWidth="1.9"
        strokeLinejoin="round"
      />
      <path
        d="m8.75 13.5 1.6 1.6 3.4-3.4"
        stroke={filled ? '#fff' : 'currentColor'}
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ProfileIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" className="size-6" aria-hidden="true" {...stroke} fill={filled ? 'currentColor' : 'none'}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 21a7.5 7.5 0 0 1 15 0" />
    </svg>
  );
}
