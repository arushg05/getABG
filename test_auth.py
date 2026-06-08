"""Quick smoke test for auth package."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth.user_db import UserDB
from auth.jwt_utils import generate_access_token, decode_access_token, generate_refresh_token, verify_refresh_token_hash

db_path = os.path.join(tempfile.gettempdir(), "test_getabg.db")
db = UserDB(db_path)

# Test user creation
uid = db.create_user("test@example.com", "hashed_pw")
user = db.get_user_by_email("test@example.com")
assert user is not None
assert user["email"] == "test@example.com"
assert user["plan"] == "free"
print(f"[PASS] User created: email={user['email']}, plan={user['plan']}")

# Test duplicate email normalization
try:
    db.create_user(" TEST@Example.com ", "hashed_pw")
    raise AssertionError("Duplicate email should not be allowed")
except ValueError as exc:
    assert "already exists" in str(exc)
print("[PASS] Duplicate email detection works")

# Test usage tracking
db.increment_usage(uid, "2025-05-26")
db.increment_usage(uid, "2025-05-26")
db.increment_usage(uid, "2025-05-26")
usage = db.get_daily_usage(uid, "2025-05-26")
assert usage == 3
print(f"[PASS] Usage tracking: {usage}/3")

# Test plan upgrade
db.set_plan(uid, "pro", "rzp_pay_123")
user = db.get_user_by_id(uid)
assert user["plan"] == "pro"
print(f"[PASS] Plan upgraded to: {user['plan']}")

# Test JWT
token = generate_access_token(uid, "test@example.com", "free")
decoded = decode_access_token(token)
assert decoded["sub"] == uid
assert decoded["plan"] == "free"
print(f"[PASS] JWT encode/decode OK")

# Test refresh token
tid, raw, thash, exp = generate_refresh_token()
assert verify_refresh_token_hash(raw, thash)
db.store_refresh_token(tid, uid, thash, exp)
stored = db.get_refresh_token(tid)
assert stored is not None
db.revoke_refresh_token(tid)
revoked = db.get_refresh_token(tid)
assert revoked is None
print(f"[PASS] Refresh token lifecycle OK")

os.remove(db_path)
print("\n=== ALL TESTS PASSED ===")
