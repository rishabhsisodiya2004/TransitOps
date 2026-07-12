"""
TransitOps - Auth Router

POST /auth/login  — issues a JWT access token.
POST /auth/register — creates a new user (open in dev, restrict in prod).
"""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.config import get_settings
from backend.database import get_db
from backend.security import (
    create_access_token,
    get_current_user,
    hash_password,
    decode_access_token,
    verify_password,
)

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])

# Non-erroring bearer scheme: lets /auth/register be called with no token
# during first-user bootstrap, while still parsing a token when present.
_optional_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@router.post(
    "/login",
    response_model=schemas.TokenResponse,
    summary="Obtain a JWT access token",
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Accepts username (email) and password via OAuth2 form.
    Returns a signed JWT valid for ACCESS_TOKEN_EXPIRE_MINUTES.
    """
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled.",
        )

    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value},
        expires_delta=expires,
    )
    return schemas.TokenResponse(
        access_token=token,
        expires_in=int(expires.total_seconds()),
        user_role=user.role,
        user_id=user.id,
    )


def _optional_current_user(
    token: Optional[str] = Depends(_optional_oauth2),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """Resolve the caller if a valid token is present; otherwise return None."""
    if not token:
        return None
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if user_id is None:
        return None
    return db.query(models.User).filter(models.User.id == int(user_id)).first()


@router.post(
    "/register",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user (first user bootstraps; thereafter Fleet Manager only)",
)
def register(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    caller: Optional[models.User] = Depends(_optional_current_user),
):
    """
    RBAC-aware registration:
      • If no users exist yet, the request is allowed (bootstrap the first admin).
      • Otherwise the caller must be an authenticated Fleet Manager.
    """
    user_count = db.query(models.User).count()

    if user_count > 0:
        if caller is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to create additional users.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if caller.role != models.UserRole.FLEET_MANAGER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a Fleet Manager can register new users.",
            )

    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{payload.email}' is already registered.",
        )
    user = models.User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=schemas.UserResponse, summary="Get current user profile")
def me(current_user: models.User = Depends(get_current_user)):
    return current_user
