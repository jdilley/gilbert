# User & Authentication System

## Summary
Multi-user support with local accounts, external provider syncing, role-based access, and session authentication. Users always exist locally; external providers (Google Directory) sync to local accounts on demand.

## Details

### Interfaces
- `UserContext` (frozen dataclass) — immutable identity flowing through the system. Fields: user_id, email, display_name, roles (frozenset), provider, session_id, metadata. Class-level `SYSTEM` sentinel for unauthenticated ops.
- `AuthInfo` (frozen dataclass) — returned by auth providers after successful authentication.
- `AuthenticationService` (ABC) — pluggable auth backend. Each is a Service with `authentication_provider` capability. Methods: `get_login_method()`, `authenticate()`, `handle_callback()`.
- `LoginMethod` (dataclass) — describes how an auth method appears on the login page (form vs redirect button).
- `UserProviderService` (ABC) — external user source. Services with `user_provider` capability. Methods: `list_external_users()`, `get_external_user()`, `get_external_user_by_email()`.
- `ExternalUser` (dataclass) — user record from external provider.
- `UserBackend` (ABC) — user CRUD, provider links, roles, remote user cache.

### Services
- `UserService` — capability: `users`, `ai_tools`. Always registered. Wraps `StorageUserBackend`. Creates root user on startup. Discovers `UserProviderService` instances and syncs on demand during `list_users()`.
- `AuthService` — capability: `authentication`. Discovers `authentication_provider` services. Manages sessions in `auth_sessions` collection. Methods: `authenticate()`, `handle_callback()`, `get_login_methods()`, `validate_session()`, `invalidate_session()`.
- `LocalAuthenticationService` — capability: `authentication_provider`. Email/password auth with argon2. Renders form on login page.
- `GoogleAuthenticationService` — capability: `authentication_provider`. Google OAuth redirect flow. Renders "Sign in with Google" button.
- `GoogleDirectoryService` — capability: `user_provider`. Reads users/groups from Google Admin Directory API.

### Storage
- `StorageUserBackend` — implements `UserBackend` over `StorageBackend`. Collections: `users`, `provider_users`.
- Root user: id="root", email="root@localhost", is_root=true, cannot be deleted or linked to external providers.

### Web Auth
- `AuthMiddleware` — checks cookie/bearer token, validates session, redirects unauthenticated to login.
- Login page renders all available auth methods dynamically (forms and OAuth buttons with "or" dividers).
- Routes: GET `/auth/login`, POST `/auth/login/local`, GET `/auth/login/google/start`, GET `/auth/login/google/callback`, POST `/auth/logout`, GET `/auth/me`.
- Logout button in nav header.

### Configuration
- `AuthConfig`: enabled, providers list, default_roles, session_ttl_seconds, root_password.
- `GoogleConfig`: enabled, oauth_credential (name of api_key_pair credential for client_id/client_secret), accounts (named service account profiles).
- Each auth provider is registered based on `auth.providers` config entries.

## Related
- `src/gilbert/interfaces/auth.py` — UserContext, AuthInfo, AuthenticationService, LoginMethod, AuthProvider
- `src/gilbert/interfaces/users.py` — UserBackend, UserProviderService, ExternalUser
- `src/gilbert/core/services/auth.py` — AuthService (session mgmt + provider discovery)
- `src/gilbert/core/services/users.py` — UserService (with provider sync)
- `src/gilbert/integrations/local_auth.py` — LocalAuthenticationService
- `src/gilbert/integrations/google_auth.py` — GoogleAuthenticationService
- `src/gilbert/integrations/google_directory.py` — GoogleDirectoryService
- `src/gilbert/web/auth.py` — middleware and dependencies
- `src/gilbert/web/routes/auth.py` — auth routes
