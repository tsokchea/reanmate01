"""Create (or promote) a super admin — ``python -m scripts.create_super_admin`` from backend/.

The admin console can create every other admin, but the first super admin has
to come from somewhere, and a public signup must never be able to become one.
This script is that somewhere: it needs shell access to the server.

  python -m scripts.create_super_admin --email owner@example.com --name "Owner"
      Creates the account. The password comes from SUPER_ADMIN_PASSWORD, or
      is asked for on the terminal, or (with --generate) is generated and
      printed once. Either way it is temporary: the first sign-in must
      choose a new one.

  python -m scripts.create_super_admin --promote owner@example.com
      Makes an existing account a super admin.

Both are recorded in the audit log as actions by "system".
"""

import argparse
import datetime as dt
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extensions import query_one, transaction  # noqa: E402
from app.models import admin as admin_db  # noqa: E402
from app.models import audit as audit_db  # noqa: E402
from app.services.admin_accounts_service import temporary_password  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402

MIN_PASSWORD = 8


def _super_role():
    role = query_one("SELECT id FROM roles WHERE kind = 'super_admin'")
    if not role:
        raise SystemExit("The roles table has no super admin role — run `python -m scripts.migrate` first.")
    return role["id"]


def _audit(tx, action, account_id, email, metadata):
    audit_db.insert(tx, actor_user_id=None, actor_label="system", action=action, target_user_id=account_id,
                    target_label=email, resource="user", resource_id=account_id, metadata=metadata,
                    ip_address=None, user_agent="scripts.create_super_admin")


def create(email, name, password):
    email = email.strip().lower()
    if admin_db.email_or_phone_taken(email=email, phone=None)["email"]:
        raise SystemExit(f"{email} is already registered. Use --promote {email} to make it a super admin.")
    role_id = _super_role()
    with transaction() as tx:
        created = admin_db.create_account(
            tx, full_name=name, email=email, phone=None, password_hash=hash_password(password),
            role="super_admin", role_id=role_id, status="active", locale="en",
            verified_at=dt.datetime.now(dt.timezone.utc),
        )
        _audit(tx, "ADMIN_CREATED", created["id"], email, {"role": "SUPER_ADMIN", "via": "cli"})
    return created["id"]


def promote(email):
    email = email.strip().lower()
    account = query_one("SELECT id, role, status FROM users WHERE email = $1", [email])
    if not account or account["status"] == "deleted":
        raise SystemExit(f"No account uses {email}.")
    role_id = _super_role()
    with transaction() as tx:
        tx.query("UPDATE users SET role = 'super_admin', role_id = $2, status = 'active' WHERE id = $1",
                 [account["id"], role_id])
        _audit(tx, "ADMIN_UPDATED", account["id"], email,
               {"role": "SUPER_ADMIN", "from": account["role"], "via": "cli"})
    return account["id"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email")
    parser.add_argument("--name", default="Super Admin")
    parser.add_argument("--generate", action="store_true", help="generate the temporary password and print it")
    parser.add_argument("--promote", metavar="EMAIL", help="make an existing account a super admin")
    args = parser.parse_args(argv)

    if args.promote:
        user_id = promote(args.promote)
        print(f"[super-admin] {args.promote} is now a super admin ({user_id}).")
        return 0

    if not args.email:
        parser.error("--email is required (or use --promote EMAIL)")

    if args.generate:
        password = temporary_password()
    else:
        password = os.environ.get("SUPER_ADMIN_PASSWORD") or getpass.getpass("Temporary password: ")
    if len(password) < MIN_PASSWORD:
        raise SystemExit(f"Use at least {MIN_PASSWORD} characters.")

    user_id = create(args.email, args.name, password)
    print(f"[super-admin] created {args.email} ({user_id}). The first sign-in must choose a new password.")
    if args.generate:
        print(f"[super-admin] temporary password: {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
