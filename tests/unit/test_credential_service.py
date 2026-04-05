"""Tests for CredentialService and credential config parsing."""

import pytest

from gilbert.config import GilbertConfig
from gilbert.core.services.credentials import CredentialService
from gilbert.interfaces.credentials import (
    ApiKeyCredential,
    CredentialType,
    GoogleServiceAccountCredential,
    UsernamePasswordCredential,
)


@pytest.fixture
def creds() -> dict[str, ApiKeyCredential | UsernamePasswordCredential | GoogleServiceAccountCredential]:
    return {
        "openai": ApiKeyCredential(api_key="sk-test123"),
        "home-assistant": ApiKeyCredential(api_key="eyJtoken"),
        "lutron": UsernamePasswordCredential(username="admin", password="secret"),
        "google-cal": GoogleServiceAccountCredential(
            service_account_file=".gilbert/credentials/cal.json",
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        ),
        "google-drive": GoogleServiceAccountCredential(
            service_account_file=".gilbert/credentials/drive.json",
        ),
    }


@pytest.fixture
def service(creds: dict) -> CredentialService:
    return CredentialService(creds)


# --- Get by name ---


def test_get_existing(service: CredentialService) -> None:
    cred = service.get("openai")
    assert cred is not None
    assert isinstance(cred, ApiKeyCredential)
    assert cred.api_key == "sk-test123"


def test_get_missing(service: CredentialService) -> None:
    assert service.get("nonexistent") is None


# --- Require ---


def test_require_existing(service: CredentialService) -> None:
    cred = service.require("lutron")
    assert isinstance(cred, UsernamePasswordCredential)
    assert cred.username == "admin"
    assert cred.password == "secret"


def test_require_missing_raises(service: CredentialService) -> None:
    with pytest.raises(LookupError, match="nonexistent"):
        service.require("nonexistent")


# --- Get by type ---


def test_get_by_type_api_key(service: CredentialService) -> None:
    api_keys = service.get_by_type(CredentialType.API_KEY)
    assert len(api_keys) == 2
    assert "openai" in api_keys
    assert "home-assistant" in api_keys


def test_get_by_type_username_password(service: CredentialService) -> None:
    result = service.get_by_type(CredentialType.USERNAME_PASSWORD)
    assert len(result) == 1
    assert "lutron" in result


def test_get_by_type_google(service: CredentialService) -> None:
    result = service.get_by_type(CredentialType.GOOGLE_SERVICE_ACCOUNT)
    assert len(result) == 2
    assert "google-cal" in result
    assert "google-drive" in result


def test_get_by_type_empty(service: CredentialService) -> None:
    empty_service = CredentialService({})
    assert empty_service.get_by_type(CredentialType.API_KEY) == {}


# --- List names ---


def test_list_names(service: CredentialService) -> None:
    names = service.list_names()
    assert names == ["google-cal", "google-drive", "home-assistant", "lutron", "openai"]


def test_list_names_empty() -> None:
    assert CredentialService({}).list_names() == []


# --- Service info ---


def test_service_info(service: CredentialService) -> None:
    info = service.service_info()
    assert info.name == "credentials"
    assert "credentials" in info.capabilities


# --- Google credential details ---


def test_google_credential_scopes(service: CredentialService) -> None:
    cred = service.require("google-cal")
    assert isinstance(cred, GoogleServiceAccountCredential)
    assert cred.scopes == ["https://www.googleapis.com/auth/calendar.readonly"]
    assert cred.service_account_file == ".gilbert/credentials/cal.json"


def test_google_credential_no_scopes(service: CredentialService) -> None:
    cred = service.require("google-drive")
    assert isinstance(cred, GoogleServiceAccountCredential)
    assert cred.scopes == []


# --- Config parsing ---


def test_config_parses_credentials() -> None:
    raw = {
        "credentials": {
            "my-key": {"type": "api_key", "api_key": "test-key"},
            "my-login": {
                "type": "username_password",
                "username": "user",
                "password": "pass",
            },
            "my-google": {
                "type": "google_service_account",
                "service_account_file": "sa.json",
                "scopes": ["scope1"],
            },
        }
    }
    config = GilbertConfig.model_validate(raw)
    assert len(config.credentials) == 3
    assert isinstance(config.credentials["my-key"], ApiKeyCredential)
    assert isinstance(config.credentials["my-login"], UsernamePasswordCredential)
    assert isinstance(config.credentials["my-google"], GoogleServiceAccountCredential)


def test_config_empty_credentials() -> None:
    config = GilbertConfig.model_validate({})
    assert config.credentials == {}
