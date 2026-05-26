"""
getABG Admin CLI — Manage Users and Plans
Allows manual plan upgrading, user verification, and user listing.
"""

import sys
import os

# Add parent directory to path so we can import auth
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth.user_db import UserDB

DB_PATH = os.path.join("api", "users.db")


def print_help():
    print("getABG User Management Tool")
    print("Usage:")
    print("  py manage_users.py list                 - List all registered users")
    print("  py manage_users.py upgrade <email>      - Upgrade a user's plan to 'pro'")
    print("  py manage_users.py downgrade <email>    - Downgrade a user's plan to 'free'")
    print("  py manage_users.py verify <email>       - Manually mark a user as verified")


def list_users(db: UserDB):
    users = db._fetch_all("SELECT user_id, email, plan, verified, created_at FROM Users")
    if not users:
        print("No users found in the database.")
        return

    print(f"\n{'Email':<30} | {'Plan':<8} | {'Verified':<8} | {'User ID':<36} | {'Created At'}")
    print("-" * 110)
    for u in users:
        verified_str = "Yes" if u["verified"] else "No"
        print(f"{u['email']:<30} | {u['plan']:<8} | {verified_str:<8} | {u['user_id']:<36} | {u['created_at']}")
    print()


def upgrade_user(db: UserDB, email: str):
    user = db.get_user_by_email(email)
    if not user:
        print(f"Error: User with email '{email}' not found.")
        return

    db.set_plan(user["user_id"], "pro", "manual_upgrade")
    print(f"Success: Upgraded {email} to 'pro' plan.")


def downgrade_user(db: UserDB, email: str):
    user = db.get_user_by_email(email)
    if not user:
        print(f"Error: User with email '{email}' not found.")
        return

    db.set_plan(user["user_id"], "free", None)
    print(f"Success: Downgraded {email} to 'free' plan.")


def verify_user(db: UserDB, email: str):
    user = db.get_user_by_email(email)
    if not user:
        print(f"Error: User with email '{email}' not found.")
        return

    db.set_verified(user["user_id"])
    print(f"Success: Marked {email} as verified.")


def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {DB_PATH}. Make sure you run this from the project root.")
        sys.exit(1)

    db = UserDB(DB_PATH)

    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "list":
        list_users(db)
    elif cmd == "upgrade":
        if len(sys.argv) < 3:
            print("Error: Missing email address.")
            print_help()
            sys.exit(1)
        upgrade_user(db, sys.argv[2])
    elif cmd == "downgrade":
        if len(sys.argv) < 3:
            print("Error: Missing email address.")
            print_help()
            sys.exit(1)
        downgrade_user(db, sys.argv[2])
    elif cmd == "verify":
        if len(sys.argv) < 3:
            print("Error: Missing email address.")
            print_help()
            sys.exit(1)
        verify_user(db, sys.argv[2])
    else:
        print(f"Error: Unknown command '{cmd}'")
        print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
