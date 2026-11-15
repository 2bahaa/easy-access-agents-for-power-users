"""Encryption of stored credentials (provider API keys, later MCP secrets).

`SECRET_ENCRYPTION_KEY` holds one or more comma-separated Fernet keys (AES-128-CBC +
HMAC-SHA256). The first key encrypts; all keys decrypt, so keys can be rotated by
prepending a new one. Plaintext secrets never leave the backend: API responses only say
whether a secret is set and show its last four characters.

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretsNotConfiguredError(RuntimeError):
    """No SECRET_ENCRYPTION_KEY: the server refuses to store secrets."""


class SecretDecryptionError(RuntimeError):
    """Stored secret cannot be decrypted with the configured keys (rotated away?)."""


class SecretBox:
    def __init__(self, keys: str) -> None:
        parts = [k.strip() for k in keys.split(",") if k.strip()]
        try:
            self._fernet = MultiFernet([Fernet(k.encode()) for k in parts]) if parts else None
        except ValueError as e:  # malformed key: fail fast at startup
            raise ValueError("SECRET_ENCRYPTION_KEY contains an invalid Fernet key") from e

    @property
    def configured(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            raise SecretsNotConfiguredError(
                "This server has no SECRET_ENCRYPTION_KEY configured, so it cannot store secrets"
            )
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        if self._fernet is None:
            raise SecretsNotConfiguredError("SECRET_ENCRYPTION_KEY is not configured")
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as e:
            raise SecretDecryptionError("Stored secret cannot be decrypted") from e


def secret_hint(plaintext: str) -> str:
    """Last four characters, for recognising a key without revealing it."""
    return f"…{plaintext[-4:]}" if len(plaintext) >= 8 else "…"
