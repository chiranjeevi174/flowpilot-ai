"""Authentication and token session service."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.core.security import (
    SecurityError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from flowpilot.models.password_reset_token import PasswordResetToken
from flowpilot.models.refresh_token import RefreshToken
from flowpilot.models.user import User
from flowpilot.schemas.auth import RegisterRequest
from flowpilot.services.email import EmailService

logger = get_logger("services.auth")


class AuthServiceError(Exception):
    """Base exception for authentication service errors."""


class DuplicateEmailError(AuthServiceError):
    """Raised when registering an email that already exists."""


class InvalidCredentialsError(AuthServiceError):
    """Raised when authentication credentials do not match."""

    def __init__(self, message: str, error_code: str = "INVALID_CREDENTIALS") -> None:
        super().__init__(message)
        self.error_code = error_code


class InactiveUserError(AuthServiceError):
    """Raised when an inactive user attempts to authenticate."""


class InvalidSessionError(AuthServiceError):
    """Raised when a refresh token session is invalid, expired, or compromised."""


class TokenError(AuthServiceError):
    """Raised when a password reset token is invalid, expired, or reused."""

    def __init__(self, message: str, error_code: str = "INVALID_TOKEN") -> None:
        super().__init__(message)
        self.error_code = error_code


class ExpiredTokenError(TokenError):
    """Raised when a reset token has expired."""

    def __init__(self, message: str = "Password reset token has expired.") -> None:
        super().__init__(message, error_code="EXPIRED_TOKEN")


class ReusedTokenError(TokenError):
    """Raised when a reset token has already been used."""

    def __init__(self, message: str = "Password reset token has already been used.") -> None:
        super().__init__(message, error_code="TOKEN_ALREADY_USED")


class RateLimitError(AuthServiceError):
    """Raised when rate limits are exceeded."""

    def __init__(self, message: str = "Too many attempts. Please try again later.") -> None:
        super().__init__(message)
        self.error_code = "RATE_LIMITED"


class AuthService:
    """Service orchestrating user authentication and refresh token rotation."""

    @staticmethod
    async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
        """Register a new user account with an Argon2-hashed password.

        Safely handles race conditions and prevents duplicate registrations.
        """
        normalized_email = data.email.strip().lower()

        # Check existing user
        existing = await db.execute(select(User).where(User.email == normalized_email))
        if existing.scalar_one_or_none() is not None:
            raise DuplicateEmailError("An account with this email address already exists.")

        user = User(
            email=normalized_email,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
            is_active=True,
        )
        db.add(user)

        try:
            await db.flush()
            await db.refresh(user)
        except IntegrityError as exc:
            await db.rollback()
            raise DuplicateEmailError("An account with this email address already exists.") from exc

        logger.info("New user registered successfully: id=%s", user.id)
        return user

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        email: str,
        password: str,
    ) -> User:
        """Authenticate user by email and password, avoiding email enumeration in production."""
        settings = get_settings()
        normalized_email = email.strip().lower()
        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()

        if user is None:
            # Perform dummy verification to prevent timing attack enumeration
            verify_password(
                password,
                "$argon2id$v=19$m=65536,t=3,p=4$dGVzdHNhbHQ$dGVzdGhhc2hkZHVtbXl2YWx1ZQ",
            )
            if settings.is_development:
                raise InvalidCredentialsError(
                    "No account found with this email address.",
                    error_code="USER_NOT_FOUND",
                )
            raise InvalidCredentialsError(
                "Invalid email or password.",
                error_code="INVALID_CREDENTIALS",
            )

        if not verify_password(password, user.password_hash):
            if settings.is_development:
                raise InvalidCredentialsError(
                    "Incorrect password. Please try again.",
                    error_code="INCORRECT_PASSWORD",
                )
            raise InvalidCredentialsError(
                "Invalid email or password.",
                error_code="INVALID_CREDENTIALS",
            )

        if not user.is_active:
            raise InactiveUserError("User account is inactive.")

        return user

    @classmethod
    async def create_session(
        cls,
        db: AsyncSession,
        user: User,
    ) -> tuple[str, str, int]:
        """Generate access and refresh tokens and persist the refresh token hash."""
        settings = get_settings()

        access_token = create_access_token(user.id)
        raw_refresh_token, family_id, expires_at = create_refresh_token(user.id)

        token_hash = hash_token(raw_refresh_token)
        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
            is_revoked=False,
        )
        db.add(refresh_record)
        await db.flush()

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return access_token, raw_refresh_token, expires_in

    @classmethod
    async def rotate_refresh_token(
        cls,
        db: AsyncSession,
        raw_token: str,
    ) -> tuple[str, str, int]:
        """Rotate an existing refresh token with replay detection.

        If a reused or revoked token is encountered, the entire token family is revoked.
        """
        settings = get_settings()

        try:
            payload = decode_token(raw_token, expected_type="refresh")
        except SecurityError as exc:
            raise InvalidSessionError(str(exc)) from exc

        token_hash = hash_token(raw_token)
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
        )
        record = result.scalar_one_or_none()

        # Replay detection: token record does not exist or was already revoked
        if record is None or record.is_revoked:
            fam_id_str = payload.get("fam")
            if fam_id_str:
                try:
                    family_id = uuid.UUID(fam_id_str)
                    await cls.revoke_token_family(db, family_id)
                    await db.commit()
                    logger.warning("Replay attack detected! Revoked token family: %s", family_id)
                except ValueError:
                    pass
            raise InvalidSessionError("Invalid or compromised refresh token.")

        # Check expiration
        now = datetime.now(UTC)
        if record.expires_at <= now:
            record.is_revoked = True
            await db.flush()
            raise InvalidSessionError("Refresh token has expired.")

        # Check user status
        user_result = await db.execute(select(User).where(User.id == record.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active:
            record.is_revoked = True
            await db.flush()
            raise InactiveUserError("User account is inactive or not found.")

        # Revoke the current token
        record.is_revoked = True

        # Issue new pair within the same token family
        access_token = create_access_token(user.id)
        new_raw_token, _, new_expires_at = create_refresh_token(
            user_id=user.id,
            family_id=record.family_id,
        )

        new_hash = hash_token(new_raw_token)
        new_record = RefreshToken(
            user_id=user.id,
            token_hash=new_hash,
            family_id=record.family_id,
            expires_at=new_expires_at,
            is_revoked=False,
        )
        db.add(new_record)
        await db.flush()

        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        return access_token, new_raw_token, expires_in

    @staticmethod
    async def revoke_refresh_token(
        db: AsyncSession,
        raw_token: str,
    ) -> None:
        """Revoke a single refresh token (used on logout)."""
        token_hash = hash_token(raw_token)
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .values(is_revoked=True)
        )
        await db.flush()

    @staticmethod
    async def revoke_token_family(
        db: AsyncSession,
        family_id: uuid.UUID,
    ) -> None:
        """Revoke all tokens belonging to a specific token family."""
        await db.execute(
            update(RefreshToken).where(RefreshToken.family_id == family_id).values(is_revoked=True)
        )
        await db.flush()

    @staticmethod
    async def revoke_all_user_sessions(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> None:
        """Revoke all active refresh token sessions for a user (e.g. after password reset)."""
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        await db.flush()

    @classmethod
    async def request_password_reset(
        cls,
        db: AsyncSession,
        email: str,
    ) -> tuple[str | None, str, bool]:
        """Generate a single-use password reset token, store its hash, and dispatch email."""
        settings = get_settings()
        normalized_email = email.strip().lower()

        result = await db.execute(select(User).where(User.email == normalized_email))
        user = result.scalar_one_or_none()

        raw_token: str | None = None
        email_delivered = False
        message = (
            "If an account exists with this email address, you will receive "
            "password reset instructions shortly."
        )

        if user is not None and user.is_active:
            # Invalidate previous unused reset tokens for this user
            await db.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.user_id == user.id, PasswordResetToken.is_used.is_(False))
                .values(is_used=True)
            )

            raw_token = secrets.token_urlsafe(32)
            token_hashed = hash_token(raw_token)
            expires_at = datetime.now(UTC) + timedelta(
                minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
            )

            reset_record = PasswordResetToken(
                user_id=user.id,
                token_hash=token_hashed,
                expires_at=expires_at,
                is_used=False,
            )
            db.add(reset_record)
            await db.flush()

            # Attempt application email dispatch
            reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
            email_res = await EmailService.send_password_reset_email(user.email, reset_url)
            email_delivered = email_res.delivered
            if not email_res.configured:
                logger.info(
                    "Password reset token generated for user id=%s. "
                    "Transactional email unconfigured.",
                    user.id,
                )

        return raw_token, message, email_delivered

    @staticmethod
    async def validate_reset_token(
        db: AsyncSession,
        raw_token: str,
    ) -> tuple[bool, str | None, str | None]:
        """Validate if a reset token is authentic, unused, and not expired."""
        token_hashed = hash_token(raw_token)
        result = await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hashed)
        )
        record = result.scalar_one_or_none()

        if record is None:
            return False, None, "Invalid reset token."

        if record.is_used:
            return False, None, "This password reset link has already been used."

        now = datetime.now(UTC)
        if record.expires_at <= now:
            return False, None, "This password reset link has expired."

        user_result = await db.execute(select(User).where(User.id == record.user_id))
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active:
            return False, None, "User account is inactive or not found."

        return True, user.email, None

    @classmethod
    async def reset_password(
        cls,
        db: AsyncSession,
        raw_token: str,
        new_password: str,
    ) -> User:
        """Consume a reset token, update user password hash, and invalidate all refresh sessions."""
        token_hashed = hash_token(raw_token)
        result = await db.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hashed)
            .with_for_update()
        )
        record = result.scalar_one_or_none()

        if record is None:
            raise TokenError("Invalid password reset token.", error_code="INVALID_TOKEN")

        if record.is_used:
            raise ReusedTokenError("Password reset token has already been used.")

        now = datetime.now(UTC)
        if record.expires_at <= now:
            raise ExpiredTokenError("Password reset token has expired.")

        user_result = await db.execute(
            select(User).where(User.id == record.user_id).with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if user is None or not user.is_active:
            raise InactiveUserError("User account is inactive or does not exist.")

        # Update password hash with Argon2id
        user.password_hash = hash_password(new_password)
        # Mark token as consumed
        record.is_used = True
        # Invalidate all active sessions for this user
        await cls.revoke_all_user_sessions(db, user.id)

        await db.flush()
        logger.info("Password reset successfully for user id=%s. All sessions revoked.", user.id)
        return user
