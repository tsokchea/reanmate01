/**
 * Which permission an action on an account needs, by the account's kind — the
 * same table the server enforces (backend/app/services/rbac_service.py,
 * ACCOUNT_ACTIONS). Used only to decide which buttons to show.
 */
export const ACCOUNT_ACTIONS = {
  view: {
    student: ['users.view', 'students.view'],
    teacher: ['users.view', 'teachers.view'],
    admin: ['admins.view'],
    super_admin: ['admins.view'],
  },
  edit: {
    student: ['users.edit'],
    teacher: ['users.edit', 'teachers.manage'],
    admin: ['admins.edit'],
    super_admin: ['admins.edit'],
  },
  disable: {
    student: ['users.disable'],
    teacher: ['users.disable', 'teachers.manage'],
    admin: ['admins.disable'],
    super_admin: ['admins.disable'],
  },
  delete: {
    student: ['users.delete'],
    teacher: ['users.delete'],
    admin: ['admins.delete'],
    super_admin: ['admins.delete'],
  },
};

/** True when `admin` (from useAdmin) may try `action` on `account`. */
export const canAct = (admin, account, action) => {
  if (!account || account.id === admin.me?.user?.id) return false;
  if (account.kind === 'super_admin' && !admin.isSuperAdmin) return false;
  return admin.can(...ACCOUNT_ACTIONS[action][account.kind ?? 'student']);
};
