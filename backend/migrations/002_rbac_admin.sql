-- migrate: foreign-keys-off
-- ============================================================================
-- ReanMate — 002_rbac_admin
--
-- Role-based access control and the admin console:
--
--   roles, permissions, role_permissions   what an account may do
--   user_permissions                       extra grants on one admin account
--   role_limits, account_limits            how much it may use (role default,
--                                          then a per-account override)
--   usage_records                          what it has used, per UTC day
--   audit_logs                             append-only record of admin actions
--   login_events                           successful sign-ins
--   system_settings                        platform-wide switches
--
-- users is rebuilt (SQLite cannot alter a CHECK constraint) so it can hold
-- 'admin' and 'super_admin' accounts, point at a role, and carry the
-- must-change-password flag. Every existing row is copied as-is: students
-- stay students, teachers stay teachers, and nobody is given an admin role.
--
-- The first line tells scripts/migrate.py to run this file with foreign keys
-- off — the documented SQLite procedure for rebuilding a table other tables
-- reference (with them on, DROP TABLE users would cascade-delete every
-- child row). The runner re-checks every foreign key before committing.
-- ============================================================================

-- Refuse to run with foreign keys on (e.g. pasted into a SQLite shell), where
-- the users rebuild below would cascade-delete every child row.
CREATE TEMP TABLE migration_guard (foreign_keys INTEGER CHECK (foreign_keys = 0));
INSERT INTO migration_guard SELECT foreign_keys FROM pragma_foreign_keys;
DROP TABLE migration_guard;

-- ============================================================================
-- ROLES AND PERMISSIONS
-- ============================================================================

CREATE TABLE roles (
  id             TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  key            TEXT NOT NULL UNIQUE CHECK (key GLOB '[A-Z]*' AND key NOT GLOB '*[^A-Z0-9_]*' AND length(key) <= 64),
  name           TEXT NOT NULL CHECK (length(trim(name)) > 0),
  description    TEXT,
  -- Which kind of account may hold the role. Custom roles are always 'admin'.
  kind           TEXT NOT NULL CHECK (kind IN ('super_admin', 'admin', 'teacher', 'student')),
  is_system_role BOOLEAN NOT NULL DEFAULT 0,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Exactly one role each for super admins, teachers and students.
CREATE UNIQUE INDEX roles_one_per_fixed_kind ON roles (kind) WHERE kind <> 'admin';

CREATE TABLE permissions (
  id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  key         TEXT NOT NULL UNIQUE,
  category    TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE role_permissions (
  role_id       TEXT NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
  permission_id TEXT NOT NULL REFERENCES permissions (id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (role_id, permission_id)
);

CREATE INDEX role_permissions_permission_id_idx ON role_permissions (permission_id);

INSERT INTO permissions (key, category, description) VALUES
  ('users.view',         'users',       'View student and teacher accounts'),
  ('users.create',       'users',       'Create student and teacher accounts'),
  ('users.edit',         'users',       'Edit accounts and reset their passwords'),
  ('users.disable',      'users',       'Disable and re-enable accounts'),
  ('users.delete',       'users',       'Delete accounts'),
  ('students.view',      'students',    'View student accounts'),
  ('teachers.view',      'teachers',    'View teacher accounts'),
  ('teachers.manage',    'teachers',    'Edit, disable and enable teacher accounts'),
  ('admins.view',        'admins',      'View admin accounts'),
  ('admins.create',      'admins',      'Create admin accounts'),
  ('admins.edit',        'admins',      'Edit admin accounts, their roles and permissions'),
  ('admins.disable',     'admins',      'Disable and re-enable admin accounts'),
  ('admins.delete',      'admins',      'Delete admin accounts'),
  ('roles.view',         'roles',       'View roles and permissions'),
  ('roles.manage',       'roles',       'Create, edit and delete roles'),
  ('usage.view',         'usage',       'View AI and storage usage'),
  ('usage.manage',       'usage',       'Reset an account''s usage for today'),
  ('limits.view',        'limits',      'View usage limits'),
  ('limits.manage',      'limits',      'Change usage limits'),
  ('assignments.view',   'assignments', 'View assignments'),
  ('assignments.manage', 'assignments', 'Delete assignments'),
  ('flashcards.view',    'flashcards',  'View flashcard sets'),
  ('flashcards.manage',  'flashcards',  'Delete flashcard sets'),
  ('content.view',       'content',     'View uploaded materials and classes'),
  ('content.manage',     'content',     'Delete uploaded materials'),
  ('analytics.view',     'analytics',   'View platform statistics'),
  ('audit.view',         'audit',       'View the audit log'),
  ('settings.view',      'settings',    'View system settings'),
  ('settings.manage',    'settings',    'Change system settings');

INSERT INTO roles (key, name, description, kind, is_system_role) VALUES
  ('SUPER_ADMIN',     'Super Admin',     'Every permission. Cannot be restricted.',                    'super_admin', 1),
  ('FULL_ADMIN',      'Full Admin',      'Most administrative permissions, without admin management.', 'admin',       1),
  ('SUPPORT_ADMIN',   'Support Admin',   'Looks up accounts and their usage.',                         'admin',       1),
  ('CONTENT_ADMIN',   'Content Admin',   'Reviews and removes materials, assignments and flashcards.', 'admin',       1),
  ('ANALYTICS_ADMIN', 'Analytics Admin', 'Reads platform statistics and usage.',                       'admin',       1),
  ('TEACHER',         'Teacher',         'Teacher account. No admin access.',                          'teacher',     1),
  ('STUDENT',         'Student',         'Student account. No admin access.',                          'student',     1);

-- SUPER_ADMIN is granted everything in code as well; the rows are here so the
-- role editor shows what it holds.
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p WHERE r.key = 'SUPER_ADMIN';

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
 WHERE r.key = 'FULL_ADMIN'
   AND p.key NOT IN ('admins.create', 'admins.edit', 'admins.disable', 'admins.delete',
                     'roles.manage', 'settings.manage');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
 WHERE r.key = 'SUPPORT_ADMIN'
   AND p.key IN ('users.view', 'students.view', 'teachers.view', 'usage.view');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
 WHERE r.key = 'CONTENT_ADMIN'
   AND p.key IN ('content.view', 'content.manage', 'assignments.view', 'assignments.manage',
                 'flashcards.view', 'flashcards.manage');

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r, permissions p
 WHERE r.key = 'ANALYTICS_ADMIN'
   AND p.key IN ('analytics.view', 'usage.view');

-- ============================================================================
-- USERS (rebuilt)
-- ============================================================================

CREATE TABLE users_new (
  id                      TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  phone                   TEXT UNIQUE,
  email                   TEXT UNIQUE,
  password_hash           TEXT NOT NULL,
  full_name               TEXT,
  avatar_url              TEXT,
  role                    TEXT CHECK (role IN ('student', 'teacher', 'admin', 'super_admin')),
  role_id                 TEXT REFERENCES roles (id) ON DELETE RESTRICT,
  locale                  TEXT NOT NULL DEFAULT 'km' CHECK (locale IN ('km', 'en')),
  plan_tier               TEXT NOT NULL DEFAULT 'free' CHECK (plan_tier IN ('free', 'plus')),
  plan_status             TEXT NOT NULL DEFAULT 'active'
                            CHECK (plan_status IN ('active', 'trialing', 'past_due', 'canceled')),
  trial_started_at        TIMESTAMPTZ,
  trial_ends_at           TIMESTAMPTZ,
  plan_period_end         TIMESTAMPTZ,
  phone_verified_at       TIMESTAMPTZ,
  email_verified_at       TIMESTAMPTZ,
  onboarding_completed_at TIMESTAMPTZ,
  -- 'disabled' replaces the never-used 'suspended'.
  status                  TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'deleted')),
  must_change_password    BOOLEAN NOT NULL DEFAULT 0,
  last_seen_at            TIMESTAMPTZ,
  last_login_at           TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  CONSTRAINT users_needs_identifier CHECK (phone IS NOT NULL OR email IS NOT NULL),
  -- Admin accounts always have a role; student/teacher rows get theirs from a trigger.
  CONSTRAINT users_admin_has_role CHECK (role NOT IN ('admin', 'super_admin') OR role_id IS NOT NULL)
);

INSERT INTO users_new (
  id, phone, email, password_hash, full_name, avatar_url, role, role_id, locale,
  plan_tier, plan_status, trial_started_at, trial_ends_at, plan_period_end,
  phone_verified_at, email_verified_at, onboarding_completed_at, status,
  must_change_password, last_seen_at, last_login_at, created_at, updated_at
)
SELECT u.id, u.phone, u.email, u.password_hash, u.full_name, u.avatar_url, u.role,
       (SELECT r.id FROM roles r WHERE r.kind = u.role),
       u.locale, u.plan_tier, u.plan_status, u.trial_started_at, u.trial_ends_at, u.plan_period_end,
       u.phone_verified_at, u.email_verified_at, u.onboarding_completed_at,
       CASE u.status WHEN 'suspended' THEN 'disabled' ELSE u.status END,
       0, u.last_seen_at, u.last_seen_at, u.created_at, u.updated_at
  FROM users u;

DROP TABLE users;
ALTER TABLE users_new RENAME TO users;

CREATE INDEX users_role_idx      ON users (role);
CREATE INDEX users_role_id_idx   ON users (role_id);
CREATE INDEX users_plan_tier_idx ON users (plan_tier);
CREATE INDEX users_status_idx    ON users (status);
CREATE INDEX users_created_at_idx ON users (created_at);

CREATE TRIGGER users_set_updated_at AFTER UPDATE ON users FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE users SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

-- Students and teachers follow their account type: signup and the role picker
-- only write users.role, and these keep role_id in step.
CREATE TRIGGER users_default_role_on_insert AFTER INSERT ON users FOR EACH ROW
WHEN NEW.role_id IS NULL AND NEW.role IN ('student', 'teacher')
BEGIN UPDATE users SET role_id = (SELECT id FROM roles WHERE kind = NEW.role) WHERE id = NEW.id; END;

CREATE TRIGGER users_default_role_on_update AFTER UPDATE OF role ON users FOR EACH ROW
WHEN NEW.role IN ('student', 'teacher') AND NEW.role IS NOT OLD.role
BEGIN UPDATE users SET role_id = (SELECT id FROM roles WHERE kind = NEW.role) WHERE id = NEW.id; END;

-- A backstop under the service checks: an admin-kind role can never sit on a
-- student or teacher row, and an admin row always holds an admin-kind role.
CREATE TRIGGER users_role_kind_on_insert BEFORE INSERT ON users FOR EACH ROW
WHEN NEW.role_id IS NOT NULL
 AND (SELECT kind FROM roles WHERE id = NEW.role_id) IS NOT NEW.role
 AND (NEW.role IN ('admin', 'super_admin')
      OR (SELECT kind FROM roles WHERE id = NEW.role_id) IN ('admin', 'super_admin'))
BEGIN SELECT RAISE(ABORT, 'role_kind_mismatch'); END;

CREATE TRIGGER users_role_kind_on_update BEFORE UPDATE OF role, role_id ON users FOR EACH ROW
WHEN NEW.role_id IS NOT NULL
 AND (SELECT kind FROM roles WHERE id = NEW.role_id) IS NOT NEW.role
 AND (NEW.role IN ('admin', 'super_admin')
      OR (SELECT kind FROM roles WHERE id = NEW.role_id) IN ('admin', 'super_admin'))
BEGIN SELECT RAISE(ABORT, 'role_kind_mismatch'); END;

-- The platform always keeps one active super admin.
CREATE TRIGGER users_keep_last_super_admin BEFORE UPDATE OF status, role ON users FOR EACH ROW
WHEN OLD.role = 'super_admin' AND OLD.status = 'active'
 AND (NEW.status IS NOT 'active' OR NEW.role IS NOT 'super_admin')
 AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'super_admin' AND status = 'active' AND id <> OLD.id)
BEGIN SELECT RAISE(ABORT, 'last_active_super_admin'); END;

CREATE TRIGGER users_keep_last_super_admin_on_delete BEFORE DELETE ON users FOR EACH ROW
WHEN OLD.role = 'super_admin' AND OLD.status = 'active'
 AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'super_admin' AND status = 'active' AND id <> OLD.id)
BEGIN SELECT RAISE(ABORT, 'last_active_super_admin'); END;

-- Extra grants on top of an admin's role. Only ever a subset of what the
-- granting admin holds (enforced in admin_service).
CREATE TABLE user_permissions (
  user_id       TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  permission_id TEXT NOT NULL REFERENCES permissions (id) ON DELETE CASCADE,
  granted_by    TEXT REFERENCES users (id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  PRIMARY KEY (user_id, permission_id)
);

CREATE INDEX user_permissions_permission_id_idx ON user_permissions (permission_id);
CREATE INDEX user_permissions_granted_by_idx    ON user_permissions (granted_by);

-- ============================================================================
-- USAGE LIMITS
--
-- Resolution per field: account_limits (when not NULL) -> role_limits.
-- In role_limits NULL means "no limit"; in account_limits NULL means
-- "inherit the role default".
-- ============================================================================

CREATE TABLE role_limits (
  role_id                    TEXT PRIMARY KEY REFERENCES roles (id) ON DELETE CASCADE,
  daily_ai_tokens            INTEGER CHECK (daily_ai_tokens IS NULL OR daily_ai_tokens >= 0),
  monthly_ai_tokens          INTEGER CHECK (monthly_ai_tokens IS NULL OR monthly_ai_tokens >= 0),
  daily_pdf_uploads          INTEGER CHECK (daily_pdf_uploads IS NULL OR daily_pdf_uploads >= 0),
  monthly_pdf_uploads        INTEGER CHECK (monthly_pdf_uploads IS NULL OR monthly_pdf_uploads >= 0),
  daily_assignments          INTEGER CHECK (daily_assignments IS NULL OR daily_assignments >= 0),
  monthly_assignments        INTEGER CHECK (monthly_assignments IS NULL OR monthly_assignments >= 0),
  daily_flashcards           INTEGER CHECK (daily_flashcards IS NULL OR daily_flashcards >= 0),
  monthly_flashcards         INTEGER CHECK (monthly_flashcards IS NULL OR monthly_flashcards >= 0),
  daily_tutor_messages       INTEGER CHECK (daily_tutor_messages IS NULL OR daily_tutor_messages >= 0),
  monthly_tutor_messages     INTEGER CHECK (monthly_tutor_messages IS NULL OR monthly_tutor_messages >= 0),
  daily_file_storage_bytes   INTEGER CHECK (daily_file_storage_bytes IS NULL OR daily_file_storage_bytes >= 0),
  monthly_file_storage_bytes INTEGER CHECK (monthly_file_storage_bytes IS NULL OR monthly_file_storage_bytes >= 0),
  updated_by                 TEXT REFERENCES users (id) ON DELETE SET NULL,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX role_limits_updated_by_idx ON role_limits (updated_by);

CREATE TABLE account_limits (
  user_id                    TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
  daily_ai_tokens            INTEGER CHECK (daily_ai_tokens IS NULL OR daily_ai_tokens >= 0),
  monthly_ai_tokens          INTEGER CHECK (monthly_ai_tokens IS NULL OR monthly_ai_tokens >= 0),
  daily_pdf_uploads          INTEGER CHECK (daily_pdf_uploads IS NULL OR daily_pdf_uploads >= 0),
  monthly_pdf_uploads        INTEGER CHECK (monthly_pdf_uploads IS NULL OR monthly_pdf_uploads >= 0),
  daily_assignments          INTEGER CHECK (daily_assignments IS NULL OR daily_assignments >= 0),
  monthly_assignments        INTEGER CHECK (monthly_assignments IS NULL OR monthly_assignments >= 0),
  daily_flashcards           INTEGER CHECK (daily_flashcards IS NULL OR daily_flashcards >= 0),
  monthly_flashcards         INTEGER CHECK (monthly_flashcards IS NULL OR monthly_flashcards >= 0),
  daily_tutor_messages       INTEGER CHECK (daily_tutor_messages IS NULL OR daily_tutor_messages >= 0),
  monthly_tutor_messages     INTEGER CHECK (monthly_tutor_messages IS NULL OR monthly_tutor_messages >= 0),
  daily_file_storage_bytes   INTEGER CHECK (daily_file_storage_bytes IS NULL OR daily_file_storage_bytes >= 0),
  monthly_file_storage_bytes INTEGER CHECK (monthly_file_storage_bytes IS NULL OR monthly_file_storage_bytes >= 0),
  updated_by                 TEXT REFERENCES users (id) ON DELETE SET NULL,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX account_limits_updated_by_idx ON account_limits (updated_by);

CREATE TRIGGER roles_set_updated_at AFTER UPDATE ON roles FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE roles SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

CREATE TRIGGER role_limits_set_updated_at AFTER UPDATE ON role_limits FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE role_limits SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE role_id = NEW.role_id; END;

CREATE TRIGGER account_limits_set_updated_at AFTER UPDATE ON account_limits FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE account_limits SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE user_id = NEW.user_id; END;

-- Role defaults. Storage is in bytes (200 MB = 209715200).
INSERT INTO role_limits (role_id, daily_ai_tokens, monthly_ai_tokens, daily_pdf_uploads, monthly_pdf_uploads,
                         daily_assignments, monthly_assignments, daily_flashcards, monthly_flashcards,
                         daily_tutor_messages, monthly_tutor_messages,
                         daily_file_storage_bytes, monthly_file_storage_bytes)
SELECT id,
       CASE key WHEN 'STUDENT' THEN 100000 WHEN 'TEACHER' THEN 200000 ELSE 50000 END,
       CASE key WHEN 'STUDENT' THEN 2000000 WHEN 'TEACHER' THEN 4000000 ELSE 1000000 END,
       CASE key WHEN 'TEACHER' THEN 50 ELSE 20 END,
       CASE key WHEN 'TEACHER' THEN 1000 ELSE 300 END,
       100, 2000,
       200, 5000,
       CASE key WHEN 'STUDENT' THEN 100 ELSE 200 END,
       NULL,
       CASE key WHEN 'TEACHER' THEN 524288000 ELSE 209715200 END,
       CASE key WHEN 'TEACHER' THEN 5368709120 ELSE 2147483648 END
  FROM roles
 WHERE kind <> 'super_admin';

-- The super admin role is unlimited.
INSERT INTO role_limits (role_id) SELECT id FROM roles WHERE kind = 'super_admin';

-- ============================================================================
-- USAGE, per account per UTC day
-- ============================================================================

CREATE TABLE usage_records (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id             TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  date                DATE NOT NULL,
  ai_input_tokens     INTEGER NOT NULL DEFAULT 0 CHECK (ai_input_tokens >= 0),
  ai_output_tokens    INTEGER NOT NULL DEFAULT 0 CHECK (ai_output_tokens >= 0),
  ai_total_tokens     INTEGER NOT NULL DEFAULT 0 CHECK (ai_total_tokens >= 0),
  pdf_uploads         INTEGER NOT NULL DEFAULT 0 CHECK (pdf_uploads >= 0),
  assignments_created INTEGER NOT NULL DEFAULT 0 CHECK (assignments_created >= 0),
  flashcards_created  INTEGER NOT NULL DEFAULT 0 CHECK (flashcards_created >= 0),
  tutor_messages      INTEGER NOT NULL DEFAULT 0 CHECK (tutor_messages >= 0),
  storage_bytes       INTEGER NOT NULL DEFAULT 0 CHECK (storage_bytes >= 0),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  UNIQUE (user_id, date)
);

CREATE INDEX usage_records_date_idx ON usage_records (date);

CREATE TRIGGER usage_records_set_updated_at AFTER UPDATE ON usage_records FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
BEGIN UPDATE usage_records SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = NEW.id; END;

-- Backfill from the ledgers that already exist, so today's and this month's
-- totals are right the moment limits start being enforced.
INSERT INTO usage_records (user_id, date, ai_input_tokens, ai_output_tokens, ai_total_tokens)
SELECT user_id, substr(created_at, 1, 10),
       sum(COALESCE(prompt_tokens, 0)), sum(COALESCE(completion_tokens, 0)), sum(COALESCE(total_tokens, 0))
  FROM ai_generations
 WHERE user_id IS NOT NULL AND user_id IN (SELECT id FROM users)
 GROUP BY user_id, substr(created_at, 1, 10);

INSERT INTO usage_records (user_id, date, pdf_uploads, storage_bytes)
SELECT user_id, substr(created_at, 1, 10), count(*), sum(COALESCE(byte_size, 0))
  FROM kit_sources
 WHERE storage_path IS NOT NULL
 GROUP BY user_id, substr(created_at, 1, 10)
    ON CONFLICT (user_id, date) DO UPDATE
   SET pdf_uploads = usage_records.pdf_uploads + excluded.pdf_uploads,
       storage_bytes = usage_records.storage_bytes + excluded.storage_bytes;

INSERT INTO usage_records (user_id, date, assignments_created)
SELECT created_by, substr(created_at, 1, 10), count(*)
  FROM assignments
 WHERE created_by IS NOT NULL
 GROUP BY created_by, substr(created_at, 1, 10)
    ON CONFLICT (user_id, date) DO UPDATE
   SET assignments_created = usage_records.assignments_created + excluded.assignments_created;

INSERT INTO usage_records (user_id, date, flashcards_created)
SELECT user_id, substr(created_at, 1, 10), count(*)
  FROM flashcards
 GROUP BY user_id, substr(created_at, 1, 10)
    ON CONFLICT (user_id, date) DO UPDATE
   SET flashcards_created = usage_records.flashcards_created + excluded.flashcards_created;

-- ============================================================================
-- AUDIT LOG — append-only
--
-- No foreign keys on purpose: deleting or anonymising an account must never
-- rewrite (or cascade into) the record of what was done to it. The actor's
-- and target's labels are captured at write time for the same reason.
-- ============================================================================

CREATE TABLE audit_logs (
  id             TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  actor_user_id  TEXT,
  actor_label    TEXT,
  action         TEXT NOT NULL,
  target_user_id TEXT,
  target_label   TEXT,
  resource       TEXT,
  resource_id    TEXT,
  metadata       JSONTEXT NOT NULL DEFAULT '{}',
  ip_address     TEXT,
  user_agent     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX audit_logs_created_at_idx     ON audit_logs (created_at DESC);
CREATE INDEX audit_logs_actor_user_id_idx  ON audit_logs (actor_user_id, created_at DESC);
CREATE INDEX audit_logs_target_user_id_idx ON audit_logs (target_user_id, created_at DESC);
CREATE INDEX audit_logs_action_idx         ON audit_logs (action, created_at DESC);

CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END;

CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END;

-- ============================================================================
-- SIGN-INS AND SETTINGS
-- ============================================================================

CREATE TABLE login_events (
  id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || substr(hex(randomblob(2)), 2) || '-' || substr('89ab', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6)))),
  user_id    TEXT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  ip_address TEXT,
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX login_events_user_id_idx    ON login_events (user_id, created_at DESC);
CREATE INDEX login_events_created_at_idx ON login_events (created_at);

CREATE TABLE system_settings (
  key        TEXT PRIMARY KEY,
  value      JSONTEXT NOT NULL,
  updated_by TEXT REFERENCES users (id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX system_settings_updated_by_idx ON system_settings (updated_by);

INSERT INTO system_settings (key, value) VALUES
  ('usage_limits_enabled', 'true'),
  ('signups_enabled', 'true');
