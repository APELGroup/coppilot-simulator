"""User management routes (admin only)."""
import os

from fastapi import APIRouter, Depends

from auth_utils import require_admin
from db import get_db_users, save_user, update_user_role, delete_user
from schemas import CreateUserRequest, UpdateUserRoleRequest

router = APIRouter()


@router.get("/users")
def list_users(_cu: dict = Depends(require_admin)):
    return get_db_users() or []


def _make_initials(name: str) -> str:
    parts = name.strip().split()
    parts = [p for p in parts if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@router.post("/users")
def create_user_endpoint(request: CreateUserRequest, _cu: dict = Depends(require_admin)):
    import time as _time
    import bcrypt as _bcrypt
    user_id = f"u-{int(_time.time() * 1000)}"
    initials = _make_initials(request.name)
    # Give admin-created users the default seed password so they can log in
    _default_pw = os.getenv("SEED_USER_PASSWORD", "DtLab2025!")
    hashed = _bcrypt.hashpw(_default_pw.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
    save_user(id=user_id, name=request.name, email=request.email,
              role=request.role, initials=initials, hashed_password=hashed)
    return get_db_users() or []


@router.put("/users/{user_id}/role")
def update_user_role_endpoint(user_id: str, request: UpdateUserRoleRequest, _cu: dict = Depends(require_admin)):
    update_user_role(user_id, request.role)
    return get_db_users() or []


@router.delete("/users/{user_id}", status_code=204)
def delete_user_endpoint(user_id: str, _cu: dict = Depends(require_admin)):
    delete_user(user_id)
