"""
JWT authentication utilities for the SimBench backend.

Provides password hashing, token creation/verification, and FastAPI
dependency functions (get_current_user, require_admin) for route protection.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

# ── Configuration (override via environment variables) ───────────────────────

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production-dtlab-key-2025")
ALGORITHM = "HS256"
EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# ── Crypto helpers (direct bcrypt — avoids passlib/bcrypt>=4 incompatibility) ─

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the stored bcrypt *hashed* value."""
    return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Token helpers ─────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """
    Sign a JWT with the given payload and an expiry of EXPIRE_HOURS hours.
    The caller is responsible for putting the right claims in *data*
    (sub, email, role, name).
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS)
    payload["exp"] = expire
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """
    Decode and verify a JWT.  Returns the payload dict on success,
    or None if the token is invalid or expired.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── FastAPI dependency functions ──────────────────────────────────────────────

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    FastAPI dependency.  Validates the Bearer token from the Authorization
    header and returns the decoded user dict:
      {"user_id", "email", "role", "name"}

    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "user_id": payload.get("sub"),
        "email":   payload.get("email"),
        "role":    payload.get("role"),
        "name":    payload.get("name"),
    }


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    FastAPI dependency.  Extends get_current_user and additionally
    requires the caller to have role == "admin".

    Raises HTTP 403 for any authenticated non-admin user.
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
