import { useEffect, useId, useRef, useState } from 'react';

import { formatNumber, useLanguage, useT } from '../i18n/index.js';

/**
 * Building blocks for the admin console, in the app's own tokens (navy, tint,
 * ink, danger; the card and field radii). The console is a desktop tool that
 * still works on a phone: tables scroll sideways inside their card and the
 * sidebar becomes a drawer.
 */

export const cx = (...parts) => parts.filter(Boolean).join(' ');

// --- formatting -------------------------------------------------------------------------

export const useFormat = () => {
  const { language } = useLanguage();
  const locale = language === 'km' ? 'km-KH' : 'en-GB';
  const digits = (text) => formatNumber(text, language);
  return {
    language,
    digits,
    number: (value) => (value === null || value === undefined ? '—' : digits(new Intl.NumberFormat('en-US').format(value))),
    compact: (value) =>
      value === null || value === undefined
        ? '—'
        : digits(new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)),
    date: (iso) => (iso ? digits(new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(iso))) : '—'),
    dateTime: (iso) =>
      iso ? digits(new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))) : '—',
  };
};

// --- icons ------------------------------------------------------------------------------

const ICONS = {
  dashboard: 'M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z',
  users: 'M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm13 9v-1a4 4 0 0 0-3-3.87M16 3.13a3.5 3.5 0 0 1 0 6.75',
  student: 'm22 9-10-5L2 9l10 5 10-5Zm-16 2.5V16c0 1.66 2.69 3 6 3s6-1.34 6-3v-4.5M22 9v6',
  teacher: 'M4 5h16v10H4zM8 19h8M12 15v4M7 9h6',
  shield: 'M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6l-8-3Zm-3 9 2 2 4-4',
  content: 'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z',
  course: 'M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5v-15ZM4 20.5A2.5 2.5 0 0 0 6.5 23H20',
  file: 'M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8M8 17h5',
  assignment: 'M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1Zm-3 2h12v14H6V6Zm3 6 2 2 4-4',
  cards: 'M8 3h11a2 2 0 0 1 2 2v11M5 7h11a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z',
  usage: 'M4 20V10m6 10V4m6 16v-7m6 7H2',
  limits: 'M12 21a9 9 0 1 1 9-9M12 12l4-4M12 3v2M3 12h2',
  key: 'M15 7a4 4 0 1 1-3.87 5H9v2H7v2H4v-3l6.13-6.13A4 4 0 0 1 15 7Zm1 0h.01',
  audit: 'M9 5h11M9 12h11M9 19h11M4 5h.01M4 12h.01M4 19h.01',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.07-.4.1-.8.1-1.2Z',
  logout: 'M15 17l5-5-5-5M20 12H9M12 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'M6 6l12 12M18 6 6 18',
  plus: 'M12 5v14M5 12h14',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.35-4.35',
  chevronLeft: 'm15 18-6-6 6-6',
  chevronRight: 'm9 18 6-6-6-6',
  more: 'M12 12h.01M19 12h.01M5 12h.01',
  lock: 'M7 11V7a5 5 0 0 1 10 0v4M5 11h14v10H5V11Z',
};

export const AdminIcon = ({ name, className = 'size-5' }) => (
  <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
    <path d={ICONS[name]} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// --- layout -----------------------------------------------------------------------------

export const PageHeader = ({ title, subtitle, actions, back }) => (
  <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
    <div className="min-w-0">
      {back}
      <h1 className="text-3xl font-bold text-navy-900">{title}</h1>
      {subtitle && <p className="mt-1 text-base text-ink-600">{subtitle}</p>}
    </div>
    {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
  </header>
);

export const Card = ({ title, actions, children, className, bodyClassName }) => (
  <section className={cx('min-w-0 rounded-card border border-tint-200 bg-white', className)}>
    {(title || actions) && (
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-tint-100 px-5 py-3.5">
        {title && <h2 className="text-lg font-bold text-navy-900">{title}</h2>}
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    )}
    <div className={bodyClassName ?? 'p-5'}>{children}</div>
  </section>
);

/** A row of numbers inside one card — not a card per number. */
export const StatGrid = ({ items }) => (
  <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 xl:grid-cols-6">
    {items.map(({ label, value, tone }) => (
      <div key={label} className="min-w-0">
        <dt className="truncate text-sm font-semibold text-ink-600">{label}</dt>
        <dd className={cx('mt-1 text-3xl font-bold', tone === 'danger' ? 'text-danger-600' : 'text-navy-900')}>
          {value}
        </dd>
      </div>
    ))}
  </dl>
);

// --- controls ---------------------------------------------------------------------------

export const AdminButton = ({ variant = 'primary', size = 'md', className, children, ...props }) => {
  const variants = {
    primary: 'bg-navy-800 text-white hover:bg-navy-900 disabled:bg-ink-400',
    secondary: 'border border-tint-200 bg-white text-navy-800 hover:bg-tint-100 disabled:text-ink-400',
    danger: 'bg-danger-600 text-white hover:bg-danger-600/90 disabled:bg-ink-400',
    ghost: 'text-navy-700 hover:bg-tint-100 disabled:text-ink-400',
    dangerGhost: 'text-danger-600 hover:bg-danger-50 disabled:text-ink-400',
  };
  const sizes = { sm: 'px-3 py-1.5 text-sm', md: 'px-4 py-2 text-base' };
  return (
    <button
      type="button"
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-field font-semibold transition-colors',
        'disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-700/30',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
};

const inputClass =
  'w-full rounded-field border border-tint-200 bg-white px-3 py-2 text-base text-navy-900 placeholder:text-ink-400 focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-700/20 disabled:bg-canvas disabled:text-ink-500';

export const Field = ({ label, hint, error, children, className }) => {
  const id = useId();
  return (
    <div className={cx('space-y-1.5', className)}>
      {label && (
        <label htmlFor={id} className="block text-sm font-semibold text-navy-900">
          {label}
        </label>
      )}
      {typeof children === 'function' ? children(id) : children}
      {error ? (
        <p role="alert" className="text-sm font-medium text-danger-600">
          {error}
        </p>
      ) : (
        hint && <p className="text-sm text-ink-500">{hint}</p>
      )}
    </div>
  );
};

export const Input = ({ label, hint, error, className, ...props }) => (
  <Field label={label} hint={hint} error={error} className={className}>
    {(id) => (
      <input id={id} aria-invalid={error ? 'true' : undefined} className={cx(inputClass, error && 'border-danger-600')} {...props} />
    )}
  </Field>
);

export const Textarea = ({ label, hint, error, className, ...props }) => (
  <Field label={label} hint={hint} error={error} className={className}>
    {(id) => <textarea id={id} rows={3} className={inputClass} {...props} />}
  </Field>
);

export const Select = ({ label, options, className, selectClassName, ...props }) => (
  <Field label={label} className={className}>
    {(id) => (
      <select id={id} className={cx(inputClass, 'pr-8', selectClassName)} {...props}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    )}
  </Field>
);

export const SearchInput = ({ value, onChange, placeholder, className }) => {
  const t = useT();
  return (
    <label className={cx('relative block', className)}>
      <span className="sr-only">{t('admin.common.search')}</span>
      <AdminIcon name="search" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-500" />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder ?? t('admin.common.searchPlaceholder')}
        className={cx(inputClass, 'pl-9')}
      />
    </label>
  );
};

export const Checkbox = ({ checked, onChange, disabled, label, description, title }) => (
  <label
    title={title}
    className={cx('flex items-start gap-2.5 rounded-field px-2 py-1.5', disabled ? 'cursor-not-allowed opacity-70' : 'cursor-pointer hover:bg-canvas')}
  >
    <input
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(event) => onChange?.(event.target.checked)}
      className="mt-0.5 size-4 shrink-0 accent-navy-800"
    />
    <span className="min-w-0">
      <span className="block text-base font-medium text-navy-900">{label}</span>
      {description && <span className="block text-sm text-ink-500">{description}</span>}
    </span>
  </label>
);

export const Toggle = ({ checked, onChange, disabled, label, description }) => (
  <label className={cx('flex items-start justify-between gap-6 py-3', disabled ? 'cursor-not-allowed' : 'cursor-pointer')}>
    <span>
      <span className="block text-base font-semibold text-navy-900">{label}</span>
      {description && <span className="mt-0.5 block text-sm text-ink-600">{description}</span>}
    </span>
    <span className="relative mt-0.5 inline-flex shrink-0">
      <input
        type="checkbox"
        role="switch"
        className="peer sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="h-6 w-11 rounded-full bg-ink-400 transition-colors peer-checked:bg-navy-800 peer-focus-visible:ring-2 peer-focus-visible:ring-navy-700/30 peer-disabled:opacity-60" />
      <span className="absolute left-0.5 top-0.5 size-5 rounded-full bg-white shadow transition-transform peer-checked:translate-x-5" />
    </span>
  </label>
);

export const Tabs = ({ tabs, value, onChange, label }) => (
  <div role="tablist" aria-label={label} className="relative flex gap-1 overflow-x-auto border-b border-tint-200">
    {tabs.map((tab) => (
      <button
        key={tab.value}
        type="button"
        role="tab"
        aria-selected={value === tab.value}
        onClick={() => onChange(tab.value)}
        className={cx(
          '-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-base font-semibold transition-colors',
          value === tab.value ? 'border-navy-800 text-navy-900' : 'border-transparent text-ink-600 hover:text-navy-800',
        )}
      >
        {tab.label}
      </button>
    ))}
  </div>
);

/** Range pills (Today / 7 days / ...). */
export const Segmented = ({ options, value, onChange, label }) => (
  <div role="radiogroup" aria-label={label} className="inline-flex rounded-field border border-tint-200 bg-white p-0.5">
    {options.map((option) => (
      <button
        key={option.value}
        type="button"
        role="radio"
        aria-checked={value === option.value}
        onClick={() => onChange(option.value)}
        className={cx(
          'rounded-[0.7rem] px-3 py-1 text-sm font-semibold transition-colors',
          value === option.value ? 'bg-navy-800 text-white' : 'text-ink-600 hover:text-navy-800',
        )}
      >
        {option.label}
      </button>
    ))}
  </div>
);

// --- status ------------------------------------------------------------------------------

const TONES = {
  green: 'bg-success-500/10 text-[#0b7a3b] ring-success-500/30',
  red: 'bg-danger-50 text-danger-600 ring-danger-600/20',
  gray: 'bg-canvas text-ink-600 ring-tint-200',
  navy: 'bg-tint-100 text-navy-800 ring-tint-200',
  gold: 'bg-gold-300/25 text-[#8a5a00] ring-gold-500/40',
};

export const Badge = ({ tone = 'gray', children }) => (
  <span className={cx('inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-bold ring-1 ring-inset', TONES[tone])}>
    {children}
  </span>
);

export const StatusBadge = ({ status }) => {
  const t = useT();
  const tone = status === 'active' ? 'green' : status === 'disabled' ? 'red' : 'gray';
  return <Badge tone={tone}>{t(`admin.status.${status}`)}</Badge>;
};

export const KindBadge = ({ kind }) => {
  const t = useT();
  const tone = kind === 'super_admin' ? 'gold' : kind === 'admin' ? 'navy' : 'gray';
  return <Badge tone={tone}>{t(`admin.kind.${kind}`)}</Badge>;
};

/** used / limit with a bar; no limit shows the count alone. */
export const UsageBar = ({ used, limit, format = (value) => value }) => {
  const t = useT();
  if (limit === null || limit === undefined) {
    return <p className="text-sm text-ink-600">{t('admin.limits.usedUnlimited', { used: format(used) })}</p>;
  }
  const percent = limit === 0 ? 100 : Math.min(100, Math.round((used / limit) * 100));
  const color = percent >= 100 ? 'bg-danger-600' : percent >= 80 ? 'bg-gold-500' : 'bg-navy-700';
  return (
    <div>
      <div className="h-2 overflow-hidden rounded-full bg-tint-100" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div className={cx('h-full rounded-full', color)} style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-1 text-sm text-ink-600">{t('admin.limits.used', { used: format(used), limit: format(limit) })}</p>
    </div>
  );
};

export const Alert = ({ tone = 'danger', children }) =>
  children ? (
    <p
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cx(
        'rounded-field px-4 py-3 text-base font-medium',
        tone === 'danger' ? 'bg-danger-50 text-danger-600' : 'bg-tint-100 text-navy-800',
      )}
    >
      {children}
    </p>
  ) : null;

export const Spinner = ({ className = 'size-6' }) => (
  <span className={cx('inline-block animate-spin rounded-full border-2 border-tint-200 border-t-navy-800', className)} aria-hidden="true" />
);

export const LoadingBlock = () => {
  const t = useT();
  return (
    <div className="flex items-center justify-center py-16" role="status">
      <Spinner />
      <span className="sr-only">{t('common.loading')}</span>
    </div>
  );
};

export const ErrorBlock = ({ text, onRetry }) => {
  const t = useT();
  return (
    <div className="rounded-card border border-danger-600/20 bg-danger-50 p-6 text-center">
      <p className="font-semibold text-danger-600">{text ?? t('admin.common.loadFailed')}</p>
      {onRetry && (
        <AdminButton variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          {t('common.retry')}
        </AdminButton>
      )}
    </div>
  );
};

// --- tables ------------------------------------------------------------------------------

/**
 * columns: [{ key, header, render(row), className }]. Wide tables scroll
 * sideways inside their card instead of pushing the page wider than the screen.
 */
export const DataTable = ({ columns, rows, rowKey = (row) => row.id, loading, emptyText, caption }) => {
  const t = useT();
  return (
    // relative: absolutely positioned children (sr-only labels) stay inside the scroller.
    <div className="relative overflow-x-auto">
      <table className="min-w-full text-left text-base">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-tint-200 bg-canvas">
            {columns.map((column) => (
              <th key={column.key} scope="col" className={cx('whitespace-nowrap px-4 py-2.5 text-xs font-bold uppercase tracking-wide text-ink-500', column.className)}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={cx(loading && 'opacity-60')}>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-b border-tint-100 last:border-0 hover:bg-canvas/70">
              {columns.map((column) => (
                <td key={column.key} className={cx('px-4 py-3 align-middle text-navy-900', column.className)}>
                  {column.render ? column.render(row) : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
          {!rows.length && (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-ink-500">
                {emptyText ?? t('admin.common.empty')}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

export const Pagination = ({ page, pageSize, total, onPage }) => {
  const t = useT();
  const pages = Math.max(1, Math.ceil((total ?? 0) / pageSize));
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-tint-100 px-4 py-3 text-sm text-ink-600">
      <span>{t('admin.common.results', { count: total ?? 0 })}</span>
      <div className="flex items-center gap-2">
        <AdminButton variant="secondary" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <AdminIcon name="chevronLeft" className="size-4" />
          {t('admin.common.previous')}
        </AdminButton>
        <span>{t('admin.common.pageOf', { page, pages })}</span>
        <AdminButton variant="secondary" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          {t('admin.common.next')}
          <AdminIcon name="chevronRight" className="size-4" />
        </AdminButton>
      </div>
    </div>
  );
};

/**
 * A small "…" menu for row actions. The menu is position: fixed, anchored to
 * its button, so a table's scroll container cannot clip it. Closes on outside
 * click, Escape, scroll and resize.
 */
export const RowMenu = ({ label, items }) => {
  const [anchor, setAnchor] = useState(null);
  const buttonRef = useRef(null);
  const menuRef = useRef(null);
  useEffect(() => {
    if (!anchor) return undefined;
    const close = (event) => {
      if (event.type === 'keydown' && event.key !== 'Escape') return;
      if (event.type === 'mousedown' && (menuRef.current?.contains(event.target) || buttonRef.current?.contains(event.target))) return;
      setAnchor(null);
    };
    const events = ['mousedown', 'keydown', 'resize'];
    events.forEach((name) => window.addEventListener(name, close));
    window.addEventListener('scroll', close, true);
    return () => {
      events.forEach((name) => window.removeEventListener(name, close));
      window.removeEventListener('scroll', close, true);
    };
  }, [anchor]);
  const visible = items.filter(Boolean);
  if (!visible.length) return null;
  const toggle = () => {
    if (anchor) return setAnchor(null);
    const rect = buttonRef.current.getBoundingClientRect();
    // Open toward whichever side has room, capped to it (the menu scrolls if needed).
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const spaceAbove = rect.top - 12;
    const below = spaceBelow >= visible.length * 40 + 8 || spaceBelow >= spaceAbove;
    return setAnchor({
      right: Math.max(8, window.innerWidth - rect.right),
      maxHeight: Math.max(120, below ? spaceBelow : spaceAbove),
      ...(below ? { top: rect.bottom + 4 } : { bottom: window.innerHeight - rect.top + 4 }),
    });
  };
  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={Boolean(anchor)}
        onClick={toggle}
        className="grid size-8 place-items-center rounded-field text-navy-700 hover:bg-tint-100"
      >
        <AdminIcon name="more" className="size-5" />
      </button>
      {anchor && (
        <div
          ref={menuRef}
          role="menu"
          style={{ position: 'fixed', ...anchor }}
          className="z-40 min-w-48 overflow-y-auto rounded-field border border-tint-200 bg-white p-1 text-left shadow-lg"
        >
          {visible.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setAnchor(null);
                item.onClick();
              }}
              className={cx(
                'block w-full rounded-[0.6rem] px-3 py-2 text-left text-base font-medium',
                item.danger ? 'text-danger-600 hover:bg-danger-50' : 'text-navy-900 hover:bg-tint-100',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </>
  );
};

// --- dialogs -----------------------------------------------------------------------------

export const Modal = ({ open, title, onClose, children, footer, wide }) => {
  const t = useT();
  const titleId = useId();
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => event.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-navy-900/40 p-0 sm:items-center sm:p-4" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cx('flex max-h-[92dvh] w-full flex-col rounded-t-card bg-white shadow-xl sm:rounded-card', wide ? 'sm:max-w-3xl' : 'sm:max-w-lg')}
      >
        <div className="flex items-center justify-between gap-4 border-b border-tint-100 px-5 py-4">
          <h2 id={titleId} className="text-xl font-bold text-navy-900">
            {title}
          </h2>
          <button type="button" onClick={onClose} aria-label={t('admin.common.close')} className="grid size-8 place-items-center rounded-field text-ink-600 hover:bg-tint-100">
            <AdminIcon name="close" className="size-5" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-tint-100 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
};

/**
 * Every destructive or access-changing action goes through this. `onConfirm`
 * may throw; its error is shown in the dialog rather than closing it.
 */
export const ConfirmDialog = ({ request, onClose }) => {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    setBusy(false);
    setError(null);
  }, [request]);
  if (!request) return null;
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await request.onConfirm();
      onClose();
    } catch (failure) {
      setError(failure?.text ?? failure?.message ?? t('admin.errors.generic'));
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      title={request.title}
      onClose={busy ? () => {} : onClose}
      footer={
        <>
          <AdminButton variant="secondary" onClick={onClose} disabled={busy}>
            {t('admin.common.cancel')}
          </AdminButton>
          <AdminButton variant={request.danger ? 'danger' : 'primary'} onClick={confirm} disabled={busy}>
            {busy ? t('admin.common.saving') : request.confirmLabel ?? t('admin.common.confirm')}
          </AdminButton>
        </>
      }
    >
      <p className="text-base text-ink-600">{request.body}</p>
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
    </Modal>
  );
};

/** Shows a one-time secret (a temporary password) with a copy button. */
export const SecretDialog = ({ secret, onClose }) => {
  const t = useT();
  const [copied, setCopied] = useState(false);
  if (!secret) return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret.value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Modal
      open
      title={secret.title}
      onClose={onClose}
      footer={<AdminButton onClick={onClose}>{t('admin.common.close')}</AdminButton>}
    >
      <p className="text-base text-ink-600">{secret.body}</p>
      <div className="mt-4 flex items-center gap-2 rounded-field border border-tint-200 bg-canvas p-3">
        <code className="min-w-0 flex-1 break-all font-mono text-lg font-semibold text-navy-900">{secret.value}</code>
        <AdminButton variant="secondary" size="sm" onClick={copy}>
          {copied ? t('admin.common.copied') : t('admin.common.copy')}
        </AdminButton>
      </div>
    </Modal>
  );
};

// --- chart --------------------------------------------------------------------------------

/**
 * A plain SVG bar chart: one metric over the chosen buckets. No chart library —
 * the console needs bars and a baseline, not a dependency.
 */
export const BarChart = ({ points, metric, label, formatValue, formatBucket }) => {
  const max = Math.max(1, ...points.map((point) => point[metric] ?? 0));
  const width = 720;
  const height = 200;
  const gap = points.length > 40 ? 1 : 3;
  const bar = (width - gap * (points.length - 1)) / points.length;
  const labelEvery = Math.ceil(points.length / 8);
  return (
    <figure>
      <svg viewBox={`0 0 ${width} ${height + 24}`} className="h-auto w-full" role="img" aria-label={label}>
        <line x1="0" x2={width} y1={height} y2={height} stroke="var(--color-tint-200)" />
        {[0.25, 0.5, 0.75].map((fraction) => (
          <line key={fraction} x1="0" x2={width} y1={height * (1 - fraction)} y2={height * (1 - fraction)} stroke="var(--color-tint-100)" strokeDasharray="4 4" />
        ))}
        {points.map((point, index) => {
          const value = point[metric] ?? 0;
          const barHeight = (value / max) * (height - 8);
          const x = index * (bar + gap);
          return (
            <g key={point.bucket}>
              <rect x={x} y={height - barHeight} width={bar} height={barHeight} rx={Math.min(3, bar / 3)} fill="var(--color-navy-700)">
                <title>{`${formatBucket(point.bucket)}: ${formatValue(value)}`}</title>
              </rect>
              {index % labelEvery === 0 && (
                <text x={x + bar / 2} y={height + 16} textAnchor="middle" fontSize="11" fill="var(--color-ink-500)">
                  {formatBucket(point.bucket)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="sr-only">{label}</figcaption>
    </figure>
  );
};
