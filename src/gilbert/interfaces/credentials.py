"""Credential types — models for API keys, passwords, service accounts, etc."""

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class CredentialType(StrEnum):
    API_KEY = "api_key"
    USERNAME_PASSWORD = "username_password"
    GOOGLE_SERVICE_ACCOUNT = "google_service_account"


class ApiKeyCredential(BaseModel):
    """An API key credential."""

    type: Literal[CredentialType.API_KEY] = CredentialType.API_KEY
    api_key: str


class UsernamePasswordCredential(BaseModel):
    """A username/password credential."""

    type: Literal[CredentialType.USERNAME_PASSWORD] = CredentialType.USERNAME_PASSWORD
    username: str
    password: str


class GoogleServiceAccountCredential(BaseModel):
    """A Google service account credential referencing a JSON key file."""

    type: Literal[CredentialType.GOOGLE_SERVICE_ACCOUNT] = (
        CredentialType.GOOGLE_SERVICE_ACCOUNT
    )
    service_account_file: str
    scopes: list[str] = []


AnyCredential = Annotated[
    Union[ApiKeyCredential, UsernamePasswordCredential, GoogleServiceAccountCredential],
    Field(discriminator="type"),
]
