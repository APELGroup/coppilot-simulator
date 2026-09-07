"""Authentication routes: login, register, current-user, password change."""
from fastapi import APIRouter, Depends, HTTPException

from auth_utils import hash_password, verify_password, create_access_token, get_current_user
from db import db_available, get_user_by_email, save_user, update_user_password
from schemas import LoginRequest, RegisterRequest, ChangePasswordRequest
from routers.users import _make_initials

router = APIRouter()


@router.post("/auth/login")
def login(request: LoginRequest):
    if not db_available():
        raise HTTPException(status_code=503, detail="Authentication service unavailable (database not connected)")
    user_data = get_user_by_email(request.email)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user_data.get("hashed_password"):
        raise HTTPException(status_code=401, detail="Account not activated — contact an admin")
    if not verify_password(request.password, user_data["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token({
        "sub":   user_data["id"],
        "email": user_data["email"],
        "role":  user_data["role"],
        "name":  user_data["name"],
    })
    # Return API-safe user dict (strip hashed_password)
    user_api = {k: v for k, v in user_data.items() if k != "hashed_password"}
    user_api["isSelf"] = user_api.pop("is_self", False)
    return {"access_token": token, "token_type": "bearer", "user": user_api}


@router.post("/auth/register", status_code=201)
def register(request: RegisterRequest):
    if not db_available():
        raise HTTPException(status_code=503, detail="Registration unavailable (database not connected)")
    existing = get_user_by_email(request.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    import time as _time
    user_id = f"u-{int(_time.time() * 1000)}"
    hashed = hash_password(request.password)
    initials = _make_initials(request.name)
    result = save_user(
        id=user_id,
        name=request.name,
        email=request.email,
        role=request.role,
        initials=initials,
        hashed_password=hashed,
    )
    if result is None:
        raise HTTPException(status_code=503, detail="Registration failed — could not save user")
    token = create_access_token({
        "sub":   user_id,
        "email": request.email,
        "role":  request.role,
        "name":  request.name,
    })
    return {"access_token": token, "token_type": "bearer", "user": result}


@router.get("/auth/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """Return the JWT payload for the authenticated user."""
    return current_user


@router.post("/auth/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    user_data = get_user_by_email(current_user["email"])
    if not user_data or not user_data.get("hashed_password"):
        raise HTTPException(status_code=400, detail="Cannot change password for this account")
    if not verify_password(request.current_password, user_data["hashed_password"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    new_hash = hash_password(request.new_password)
    if not update_user_password(user_data["id"], new_hash):
        raise HTTPException(status_code=503, detail="Could not update password (database error)")
    return {"message": "Password updated successfully"}
