"""Secret encryption and the provider base-URL (SSRF) guard."""

import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.crypto import SecretBox, SecretDecryptionError, SecretsNotConfiguredError, secret_hint
from app.services.errors import DomainValidationError
from app.services.provider_service import validate_base_url


def test_roundtrip_and_ciphertext_hides_plaintext() -> None:
    box = SecretBox(Fernet.generate_key().decode())
    token = box.encrypt("sk-live-1234567890")
    assert "sk-live" not in token
    assert box.decrypt(token) == "sk-live-1234567890"


def test_key_rotation() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = SecretBox(old).encrypt("secret")
    rotated = SecretBox(f"{new},{old}")
    assert rotated.decrypt(token) == "secret"  # old ciphertexts still readable
    assert SecretBox(new).decrypt(rotated.encrypt("x")) == "x"  # new key encrypts
    with pytest.raises(SecretDecryptionError):
        SecretBox(new).decrypt(token)  # old key removed


def test_unconfigured_and_invalid_keys() -> None:
    box = SecretBox("")
    assert not box.configured
    with pytest.raises(SecretsNotConfiguredError):
        box.encrypt("x")
    with pytest.raises(ValueError):
        SecretBox("not-a-fernet-key")


def test_secret_hint() -> None:
    assert secret_hint("sk-abcdefgh1234") == "…1234"
    assert secret_hint("short") == "…"


SETTINGS = Settings(provider_blocked_hosts="internal.corp, 10.9.9.9")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:1234/v1",
        "http://localhost:11434",
        "https://api.openai.com/v1/",
        "http://192.168.1.20:8000/v1",  # LAN model servers are a supported use case
    ],
)
def test_allowed_base_urls(url: str) -> None:
    assert validate_base_url(url, SETTINGS) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "http://metadata.google.internal/computeMetadata/v1",
        "http://[fe80::1]:8080",  # link-local IPv6
        "http://user:pass@example.com/v1",
        "http://internal.corp/v1",  # blocked by configuration
        "http://10.9.9.9/v1",
        "not a url",
    ],
)
def test_rejected_base_urls(url: str) -> None:
    with pytest.raises(DomainValidationError):
        validate_base_url(url, SETTINGS)


def test_empty_base_url_means_default() -> None:
    assert validate_base_url(None, SETTINGS) is None
    assert validate_base_url("  ", SETTINGS) is None
