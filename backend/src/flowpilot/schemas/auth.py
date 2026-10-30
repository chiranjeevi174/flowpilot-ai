"""Authentication request and response schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Schema for user registration."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plaintext password (min 8 chars, max 128 chars)",
    )
    full_name: str | None = Field(
        default=None,
        max_length=255,
        description="Optional display name of the user",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email address to lowercase."""
        return value.strip().lower()

    @field_validator("full_name")
    @classmethod
    def clean_full_name(cls, value: str | None) -> str | None:
        """Strip surrounding whitespace from full name."""
        if value is not None:
            cleaned = value.strip()
            return cleaned if cleaned else None
        return None


class LoginRequest(BaseModel):
    """Schema for user credentials authentication."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email address to lowercase."""
        return value.strip().lower()


class TokenResponse(BaseModel):
    """Schema representing an access token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifespan in seconds")


class RefreshTokenRequest(BaseModel):
    """Schema for refresh token endpoint payload (optional when using HttpOnly cookie)."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = Field(
        default=None,
        description="Refresh token (can alternatively be sent via HttpOnly cookie)",
    )


class MessageResponse(BaseModel):
    """Generic status or informational response."""

    message: str


class ForgotPasswordRequest(BaseModel):
    """Schema for requesting a password reset email."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email address to lowercase."""
        return value.strip().lower()


class ForgotPasswordResponse(BaseModel):
    """Response after a password recovery request."""

    message: str
    email_sent: bool
    dev_reset_url: str | None = None


class ValidateTokenResponse(BaseModel):
    """Response indicating whether a reset token is valid."""

    valid: bool
    email: str | None = None
    reason: str | None = None


class ResetPasswordRequest(BaseModel):
    """Schema for setting a new password with a reset token."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, description="Cryptographic password reset token")
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Plaintext password (min 8 chars, max 128 chars)",
    )


class AuthErrorResponse(BaseModel):
    """Structured authentication error response."""

    detail: str
    error_code: str
