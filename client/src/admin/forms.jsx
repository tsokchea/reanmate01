import { useT } from '../i18n/index.js';
import { Checkbox, Input } from './ui.jsx';

/**
 * Two editors shared by the admin, role, account and limits screens.
 */

// Limits in display order: [group, daily field, monthly field]. Storage is
// edited in MB and sent in bytes.
export const LIMIT_ROWS = [
  ['ai', 'dailyAiTokens', 'monthlyAiTokens'],
  ['uploads', 'dailyPdfUploads', 'monthlyPdfUploads'],
  ['assignments', 'dailyAssignments', 'monthlyAssignments'],
  ['flashcards', 'dailyFlashcards', 'monthlyFlashcards'],
  ['tutor', 'dailyTutorMessages', 'monthlyTutorMessages'],
  ['storage', 'dailyFileStorageBytes', 'monthlyFileStorageBytes'],
];

const MB = 1024 * 1024;
const isStorage = (field) => field.endsWith('StorageBytes');

/** API limits -> form strings ('' means null). */
export const limitsToForm = (limits) =>
  Object.fromEntries(
    LIMIT_ROWS.flatMap(([, daily, monthly]) => [daily, monthly]).map((field) => {
      const value = limits?.[field];
      if (value === null || value === undefined) return [field, ''];
      return [field, String(isStorage(field) ? Math.round((value / MB) * 100) / 100 : value)];
    }),
  );

/**
 * Form strings -> API payload. Only fields that differ from `initial` are
 * sent, so saving an untouched form changes nothing (and audits nothing).
 */
export const formToLimits = (form, initial = {}) => {
  const out = {};
  for (const [field, raw] of Object.entries(form)) {
    if (raw === (initial[field] ?? '')) continue;
    const text = String(raw).trim();
    if (text === '') {
      out[field] = null;
      continue;
    }
    const number = Number(text);
    out[field] = isStorage(field) ? Math.round(number * MB) : Math.round(number);
  }
  return out;
};

export const LimitsEditor = ({ value, onChange, placeholders, disabled, errors }) => {
  const t = useT();
  const set = (field) => (event) => onChange({ ...value, [field]: event.target.value });
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[28rem] text-left">
        <thead>
          <tr className="text-xs font-bold uppercase tracking-wide text-ink-500">
            <th scope="col" className="pb-2 pr-3" />
            <th scope="col" className="pb-2 pr-3">{t('admin.limitGroup.daily')}</th>
            <th scope="col" className="pb-2">{t('admin.limitGroup.monthly')}</th>
          </tr>
        </thead>
        <tbody>
          {LIMIT_ROWS.map(([group, daily, monthly]) => (
            <tr key={group} className="border-t border-tint-100">
              <th scope="row" className="py-2 pr-3 text-base font-semibold text-navy-900">
                {t(`admin.limitGroup.${group}`)}
              </th>
              {[daily, monthly].map((field) => (
                <td key={field} className="py-2 pr-3 last:pr-0">
                  <Input
                    aria-label={`${t(`admin.limitGroup.${group}`)} — ${t(field === daily ? 'admin.limitGroup.daily' : 'admin.limitGroup.monthly')}`}
                    type="number"
                    min="0"
                    step={isStorage(field) ? '0.01' : '1'}
                    inputMode="decimal"
                    value={value[field] ?? ''}
                    onChange={set(field)}
                    placeholder={placeholders?.[field] ?? ''}
                    disabled={disabled}
                    error={errors?.[field]}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

/** Placeholder text for an override field: what the account gets if it is left empty. */
export const limitPlaceholders = (defaults, t) =>
  Object.fromEntries(
    Object.entries(limitsToForm(defaults)).map(([field, text]) => [field, text === '' ? t('admin.common.unlimited') : text]),
  );

/**
 * Permission checkboxes grouped by category.
 *   selected   — keys currently ticked
 *   locked     — keys ticked and fixed (they come from the role)
 *   grantable  — keys this admin may hand out; others are shown but disabled
 */
export const PermissionPicker = ({ catalogue, selected, locked = [], grantable, onChange, disabled }) => {
  const t = useT();
  const selectedSet = new Set(selected);
  const lockedSet = new Set(locked);
  const toggle = (key, on) => {
    const next = new Set(selectedSet);
    if (on) next.add(key);
    else next.delete(key);
    onChange([...next].sort());
  };
  return (
    <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
      {catalogue.map((group) => (
        <fieldset key={group.category} className="min-w-0">
          <legend className="mb-1 text-sm font-bold uppercase tracking-wide text-ink-500">
            {t(`admin.permCategory.${group.category}`)}
          </legend>
          {group.permissions.map(({ key }) => {
            const isLocked = lockedSet.has(key);
            const mayGrant = !grantable || grantable.has(key);
            return (
              <Checkbox
                key={key}
                checked={isLocked || selectedSet.has(key)}
                disabled={disabled || isLocked || (!mayGrant && !selectedSet.has(key))}
                onChange={(on) => toggle(key, on)}
                label={t(`admin.perm.${key}`)}
                description={isLocked ? t('admin.admins.fromRole') : undefined}
                title={!mayGrant ? t('admin.admins.cannotGrant') : undefined}
              />
            );
          })}
        </fieldset>
      ))}
    </div>
  );
};
