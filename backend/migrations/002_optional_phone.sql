-- ============================================================================
-- 002_optional_phone
--
-- 001_init made `phone` NOT NULL on the assumption that phone was the identity.
-- docs/screens/01-auth-onboarding/01-auth-signup-phone shows the opposite: the
-- signup form marks email as the required field and labels the phone input
-- "Phone number(optional)".
--
-- So phone becomes nullable, and a CHECK enforces the real rule — an account
-- needs at least one of the two. Both stay UNIQUE; Postgres allows many NULLs
-- in a UNIQUE column, which is exactly what an optional identifier needs.
-- ============================================================================

ALTER TABLE users ALTER COLUMN phone DROP NOT NULL;

ALTER TABLE users
  ADD CONSTRAINT users_needs_identifier
  CHECK (phone IS NOT NULL OR email IS NOT NULL);

COMMENT ON CONSTRAINT users_needs_identifier ON users IS
  'An account is reachable by phone, email, or both — never neither.';
