"""
getABG Auth — Flask Middleware
@require_auth decorator for protecting API endpoints.
"""

from functools import wraps
from flask import request, jsonify, g

from auth.jwt_utils import decode_access_token
import jwt as pyjwt


def require_auth(f):
    """
    Decorator that enforces authentication via httpOnly access_token cookie.
    Injects g.user_id, g.email, g.plan into Flask request context.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return f(*args, **kwargs)

        token = request.cookies.get("access_token")

        # Fallback: also accept Authorization header for API clients / testing
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]

        if not token:
            return jsonify({"error": "Authentication required", "code": "AUTH_REQUIRED"}), 401

        try:
            payload = decode_access_token(token)
            g.user_id = payload["sub"]
            g.email = payload["email"]
            # Use the JWT plan claim. Endpoints that need authoritative plan
            # data (e.g., backtest quota) should re-check via the shared
            # user_db instance from server.py. This avoids creating a new
            # UserDB + running schema DDL on every single request.
            g.plan = payload["plan"]
        except pyjwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired", "code": "TOKEN_EXPIRED"}), 401
        except pyjwt.InvalidTokenError as e:
            return jsonify({"error": f"Invalid token: {str(e)}", "code": "INVALID_TOKEN"}), 401

        return f(*args, **kwargs)

    return decorated


def require_verified(f):
    """
    Decorator that enforces email verification.
    Must be used AFTER @require_auth (requires g.user_id to be set).
    Checks the user DB to ensure the user is verified.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Import here to avoid circular imports
        from auth.user_db import UserDB
        import os

        db_path = os.path.join(os.path.dirname(__file__), "..", "api", "users.db")
        user_db = UserDB(db_path)
        user = user_db.get_user_by_id(g.user_id)

        if not user or not user.get("verified"):
            return jsonify({
                "error": "Email verification required for this action",
                "code": "VERIFICATION_REQUIRED"
            }), 403

        return f(*args, **kwargs)

    return decorated
