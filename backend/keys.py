"""API key generation + hashing.

API keys carry their own entropy (~24 bytes of randomness), so SHA-256 is
sufficient: there's no dictionary attack to defend against. We don't need
bcrypt/argon2 here; those are for low-entropy human passwords.
"""
import hashlib
import secrets

API_KEY_PREFIX = "bk_"
SESSION_PREFIX = "bks_"


def generate_key() -> str:
    """Return a fresh plaintext API key. Show this to the user exactly once."""
    return API_KEY_PREFIX + secrets.token_urlsafe(24)


def generate_session_token() -> str:
    """Return a fresh session bearer token."""
    return SESSION_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Stable hex digest of a plaintext key or session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Backwards-compat alias for callers that already import hash_key.
hash_key = hash_token


def prefix_for_display(api_key: str, length: int = 12) -> str:
    """First N chars of a key, used as a non-secret display fingerprint."""
    return api_key[:length]


def is_session_token(token: str) -> bool:
    return token.startswith(SESSION_PREFIX)


def is_api_key(token: str) -> bool:
    return token.startswith(API_KEY_PREFIX) and not token.startswith(SESSION_PREFIX)
