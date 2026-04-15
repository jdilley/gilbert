"""Credential types — models for API keys, passwords, service accounts, etc."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class CredentialType(StrEnum):
    API_KEY = "api_key"
    API_KEY_PAIR = "api_key_pair"
    USERNAME_PASSWORD = "username_password"


class ApiKeyCredential(BaseModel):
    """An API key credential."""

    type: Literal[CredentialType.API_KEY] = CredentialType.API_KEY
    api_key: str


class ApiKeyPairCredential(BaseModel):
    """A client ID + client secret credential (e.g., OAuth2 client credentials)."""

    type: Literal[CredentialType.API_KEY_PAIR] = CredentialType.API_KEY_PAIR
    client_id: str
    client_secret: str


class UsernamePasswordCredential(BaseModel):
    """A username/password credential."""

    type: Literal[CredentialType.USERNAME_PASSWORD] = CredentialType.USERNAME_PASSWORD
    username: str
    password: str


AnyCredential = Annotated[
    ApiKeyCredential | ApiKeyPairCredential | UsernamePasswordCredential,
    Field(discriminator="type"),
]
