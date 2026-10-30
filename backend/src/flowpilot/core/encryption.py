"""Authenticated symmetric encryption and key management for LLM BYOK credentials."""

import hashlib
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from flowpilot.core.config import get_settings


class EncryptionError(Exception):
    """Base exception for cryptographic operations."""


class EncryptionConfigurationError(EncryptionError):
    """Raised when encryption keys are missing, invalid, or misconfigured."""


class DecryptionError(EncryptionError):
    """Raised when decryption fails (e.g. invalid key or corrupted ciphertext)."""


def generate_fernet_key() -> str:
    """Generate a new urlsafe base64-encoded 32-byte Fernet key."""
    return Fernet.generate_key().decode("utf-8")


@lru_cache
def get_multi_fernet(keys_tuple: tuple[str, ...]) -> MultiFernet:
    """Create and cache a MultiFernet instance from a sequence of Fernet keys."""
    if not keys_tuple:
        raise EncryptionConfigurationError("No encryption keys configured.")

    fernets: list[Fernet] = []
    for idx, key in enumerate(keys_tuple):
        stripped = key.strip()
        try:
            fernets.append(Fernet(stripped.encode("utf-8")))
        except Exception as exc:
            msg = f"Invalid Fernet encryption key at position {idx}."
            raise EncryptionConfigurationError(msg) from exc

    return MultiFernet(fernets)


def get_cipher() -> MultiFernet:
    """Retrieve the application-configured MultiFernet cipher."""
    settings = get_settings()
    keys = tuple(k.strip() for k in settings.LLM_ENCRYPTION_KEYS if k.strip())
    if not keys:
        msg = (
            "LLM_ENCRYPTION_KEYS is not configured. "
            "Provide at least one valid base64-encoded 32-byte Fernet key."
        )
        raise EncryptionConfigurationError(msg)

    return get_multi_fernet(keys)


def encrypt_api_key(plain_api_key: str) -> str:
    """Encrypt a plaintext API key using authenticated MultiFernet encryption.

    Args:
        plain_api_key: The raw provider API key.

    Returns:
        Base64-encoded ciphertext string.
    """
    if not plain_api_key or not plain_api_key.strip():
        raise ValueError("API key must not be empty.")

    cipher = get_cipher()
    try:
        ciphertext_bytes = cipher.encrypt(plain_api_key.strip().encode("utf-8"))
        return ciphertext_bytes.decode("utf-8")
    except Exception as exc:
        msg = "Failed to encrypt API key."
        raise EncryptionError(msg) from exc


def decrypt_api_key(encrypted_api_key: str) -> str:
    """Decrypt an encrypted API key using MultiFernet.

    Args:
        encrypted_api_key: The stored ciphertext string.

    Returns:
        The decrypted plaintext API key.
    """
    if not encrypted_api_key or not encrypted_api_key.strip():
        raise ValueError("Ciphertext must not be empty.")

    cipher = get_cipher()
    try:
        decrypted_bytes = cipher.decrypt(encrypted_api_key.strip().encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Decryption failed: corrupted ciphertext or mismatched encryption key."
        ) from exc
    except Exception as exc:
        raise DecryptionError("Decryption operation failed.") from exc


def rotate_encrypted_key(encrypted_api_key: str) -> str:
    """Re-encrypt ciphertext with the primary encryption key (rotation support)."""
    cipher = get_cipher()
    try:
        rotated_bytes = cipher.rotate(encrypted_api_key.strip().encode("utf-8"))
        return rotated_bytes.decode("utf-8")
    except Exception as exc:
        raise DecryptionError("Key rotation failed for ciphertext.") from exc


def generate_key_fingerprint(api_key: str) -> str:
    """Generate a safe, non-reversible fingerprint of an API key for safe display.

    Format: '<prefix>...<suffix> (<hash_snippet>)'
    Example: 'sk-proj...9xyz (hash:a1b2c3d4)'
    """
    clean_key = api_key.strip()
    if not clean_key:
        return "empty"

    sha = hashlib.sha256(clean_key.encode("utf-8")).hexdigest()[:8]

    # Handle standard provider prefixes if present (e.g. sk-, AIza)
    prefix_match = re.match(r"^([a-zA-Z0-9_-]{3,8})", clean_key)
    prefix = prefix_match.group(1) if prefix_match and len(clean_key) >= 12 else clean_key[:3]
    suffix = clean_key[-4:] if len(clean_key) >= 8 else clean_key[-2:]

    return f"{prefix}...{suffix} (sha256:{sha})"
