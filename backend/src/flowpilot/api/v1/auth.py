"""Authentication endpoints for user registration, login, rotation, and logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import Settings, get_settings
from flowpilot.core.rate_limit import check_rate_limit
from flowpilot.db.session import get_db
from flowpilot.models.user import User
from flowpilot.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    MessageResponse,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    ValidateTokenResponse,
)
from flowpilot.schemas.user import UserResponse
from flowpilot.services.auth import (
    AuthService,
    DuplicateEmailError,
    ExpiredTokenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidSessionError,
    ReusedTokenError,
    TokenError,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_refresh_cookie(
    response: Response,
    refresh_token: str,
    settings: Settings,
) -> None:
    """Set a secure HttpOnly cookie containing the rotating refresh token."""
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=f"{settings.API_V1_PREFIX}/auth",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    """Delete the refresh token HttpOnly cookie."""
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=f"{settings.API_V1_PREFIX}/auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Creates a new user account with Argon2id password hashing.",
)
async def register(
    data: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    """Register a new user account."""
    try:
        user = await AuthService.register_user(db, data)
        return UserResponse.model_validate(user)
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user",
    description=(
        "Authenticates user credentials, sets an HttpOnly refresh cookie, and returns "
        "a short-lived Bearer access token."
    ),
)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Authenticate user credentials and create a new session."""
    client_ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit(f"login:{client_ip}", max_requests=10, window_seconds=60):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Too many attempts. Please try again later.",
                "error_code": "RATE_LIMITED",
            },
        )

    try:
        user = await AuthService.authenticate_user(db, data.email, data.password)
        access_token, refresh_token, expires_in = await AuthService.create_session(db, user)
        _set_refresh_cookie(response, refresh_token, settings)
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=expires_in,
        )
    except InvalidCredentialsError as exc:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc), "error_code": exc.error_code},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InactiveUserError as exc:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(exc), "error_code": "INACTIVE_USER"},
        )


@router.post(
    "/dev-impersonate",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Development user session creation",
)
async def dev_impersonate(
    data: dict[str, str],
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Dev-only endpoint to switch active user session for browser testing."""
    if settings.is_production:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    email = (data.get("email") or "").strip().lower()
    user = await db.scalar(select(User).where(User.email == email))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    access_token, refresh_token, expires_in = await AuthService.create_session(db, user)
    _set_refresh_cookie(response, refresh_token, settings)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token",
    description=(
        "Rotates the refresh token (read from HttpOnly cookie or JSON body) with replay "
        "detection, issuing a fresh access token."
    ),
)
async def refresh_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    body: RefreshTokenRequest | None = None,
) -> TokenResponse:
    """Rotate the refresh token and obtain a new access token."""
    token = None
    if body and body.refresh_token:
        token = body.refresh_token
    else:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token was not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        new_access, new_refresh, expires_in = await AuthService.rotate_refresh_token(db, token)
        _set_refresh_cookie(response, new_refresh, settings)
        return TokenResponse(
            access_token=new_access,
            token_type="bearer",
            expires_in=expires_in,
        )
    except InvalidSessionError as exc:
        _clear_refresh_cookie(response, settings)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InactiveUserError as exc:
        _clear_refresh_cookie(response, settings)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Logout user",
    description="Revokes the active refresh token session and clears authentication cookies.",
)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    body: RefreshTokenRequest | None = None,
) -> MessageResponse:
    """Revoke session and clear cookies."""
    token = None
    if body and body.refresh_token:
        token = body.refresh_token
    else:
        token = request.cookies.get(settings.AUTH_COOKIE_NAME)

    if token:
        await AuthService.revoke_refresh_token(db, token)

    _clear_refresh_cookie(response, settings)
    return MessageResponse(message="Successfully logged out.")


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    status_code=status.HTTP_200_OK,
    summary="Request password reset",
    description=(
        "Initiates password recovery by generating a single-use token and dispatching an email."
    ),
)
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ForgotPasswordResponse:
    """Request password reset link."""
    client_ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit(
        f"forgot_password:{client_ip}", max_requests=5, window_seconds=60
    ):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Too many attempts. Please try again later.",
                "error_code": "RATE_LIMITED",
            },
        )

    raw_token, message, email_delivered = await AuthService.request_password_reset(db, data.email)
    dev_url = (
        f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
        if (settings.is_development and not email_delivered and raw_token)
        else None
    )

    return ForgotPasswordResponse(
        message=message,
        email_sent=email_delivered,
        dev_reset_url=dev_url,
    )


@router.get(
    "/reset-password/validate",
    response_model=ValidateTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate password reset token",
    description="Checks if a password reset token is authentic, unused, and unexpired.",
)
async def validate_reset_token(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ValidateTokenResponse:
    """Check reset token validity."""
    valid, email, reason = await AuthService.validate_reset_token(db, token)
    return ValidateTokenResponse(valid=valid, email=email, reason=reason)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset password",
    description="Sets a new password using a valid reset token and revokes all active sessions.",
)
async def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """Reset password and consume token."""
    client_ip = request.client.host if request.client else "unknown"
    if not await check_rate_limit(
        f"reset_password:{client_ip}", max_requests=10, window_seconds=60
    ):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Too many attempts. Please try again later.",
                "error_code": "RATE_LIMITED",
            },
        )

    try:
        await AuthService.reset_password(db, data.token, data.password)
        return MessageResponse(
            message="Password has been reset successfully. Please log in with your new password."
        )
    except ExpiredTokenError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "error_code": exc.error_code},
        )
    except ReusedTokenError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "error_code": exc.error_code},
        )
    except TokenError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": str(exc), "error_code": exc.error_code},
        )
    except InactiveUserError as exc:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(exc), "error_code": "INACTIVE_USER"},
        )
