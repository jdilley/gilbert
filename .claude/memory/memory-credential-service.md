# Credential Service

## Summary
Core service providing named credentials (API keys, username/password, Google service accounts) to other services and plugins. Credentials are defined in config YAML and served by name or type.

## Details

### Credential Types (`src/gilbert/interfaces/credentials.py`)
- `ApiKeyCredential` — `type: api_key`, has `api_key` field
- `UsernamePasswordCredential` — `type: username_password`, has `username` and `password`
- `GoogleServiceAccountCredential` — `type: google_service_account`, has `service_account_file` and optional `scopes` list
- `AnyCredential` — Pydantic discriminated union on `type` field for config parsing

### Service (`src/gilbert/core/services/credentials.py`)
`CredentialService` is a `Service` providing the `"credentials"` capability. API:
- `get(name) -> AnyCredential | None`
- `require(name) -> AnyCredential` (raises `LookupError` if missing)
- `get_by_type(cred_type) -> dict[str, AnyCredential]`
- `list_names() -> list[str]`

### Config Format
Credentials are named and typed in `credentials:` section of config YAML:
```yaml
credentials:
  my-openai:
    type: api_key
    api_key: sk-abc123
  google-calendar:
    type: google_service_account
    service_account_file: .gilbert/credentials/calendar-sa.json
    scopes:
      - https://www.googleapis.com/auth/calendar.readonly
```

Multiple credentials of the same type with different names are supported (e.g., multiple Google service accounts with different scopes).

### How other services use it
Services that need credentials declare `requires=frozenset({"credentials"})` or `optional=frozenset({"credentials"})` in their `ServiceInfo`, then use the resolver at start time:
```python
cred_svc = resolver.require_capability("credentials")
api_key = cred_svc.require("my-openai")
```

## Related
- `src/gilbert/interfaces/credentials.py` — credential type models
- `src/gilbert/core/services/credentials.py` — CredentialService
- `src/gilbert/config.py` — `credentials` field in GilbertConfig
- `tests/unit/test_credential_service.py` — 15 tests
- [Service System](memory-service-system.md) — how services work
- [Configuration and Data Directory](memory-config-and-data-dir.md) — config layering
