import assert from 'node:assert/strict';
import { test } from 'node:test';

import { canAct } from './accountActions.js';

const adminWith = (permissions, { isSuperAdmin = false, id = 'me' } = {}) => ({
  isSuperAdmin,
  me: { user: { id } },
  can: (...keys) => keys.some((key) => permissions.includes(key)),
});

test('a support admin sees no management actions', () => {
  const support = adminWith(['users.view', 'students.view', 'teachers.view', 'usage.view']);
  for (const action of ['edit', 'disable', 'delete']) {
    assert.equal(canAct(support, { id: 's1', kind: 'student' }, action), false);
  }
});

test('teachers.manage covers teachers but not students', () => {
  const admin = adminWith(['teachers.manage']);
  assert.equal(canAct(admin, { id: 't1', kind: 'teacher' }, 'disable'), true);
  assert.equal(canAct(admin, { id: 's1', kind: 'student' }, 'disable'), false);
  assert.equal(canAct(admin, { id: 't1', kind: 'teacher' }, 'delete'), false);
});

test('admin accounts need the admins.* permissions', () => {
  const usersOnly = adminWith(['users.edit', 'users.disable', 'users.delete']);
  assert.equal(canAct(usersOnly, { id: 'a1', kind: 'admin' }, 'edit'), false);
  assert.equal(canAct(adminWith(['admins.edit']), { id: 'a1', kind: 'admin' }, 'edit'), true);
});

test('only a super admin is offered actions on a super admin', () => {
  const target = { id: 'root', kind: 'super_admin' };
  assert.equal(canAct(adminWith(['admins.edit', 'admins.disable']), target, 'disable'), false);
  assert.equal(canAct(adminWith(['admins.disable'], { isSuperAdmin: true }), target, 'disable'), true);
});

test('nobody is offered actions on their own account', () => {
  const admin = adminWith(['admins.disable'], { isSuperAdmin: true, id: 'me' });
  assert.equal(canAct(admin, { id: 'me', kind: 'super_admin' }, 'disable'), false);
});
