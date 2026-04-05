# User & Authentication System

## Summary
Multi-user support with local accounts, external provider linking, role-based access, and session authentication. Users always exist locally; external providers (Google, Zoho) sync to local accounts.

## Details

### Interfaces
- `UserContext` (frozen dataclass) — immutable identity flowing through the system. Fields: user_id, email, display_name, roles (frozenset), provider, session_id, metadata. Class-level `SYSTEM` sentinel for unauthenticated ops.
- `AuthInfo` (frozen dataclass) — returned by auth providers after successful authentication.
- `AuthProvider` (ABC) — authenticate(), sync_users(), get_role_mappings(). Concrete: `LocalAuthProvider` (argon2 passwords).
- `UserBackend` (ABC) — user CRUD, provider links, roles, remote user cache.

### Services
- `UserService` — capability: `users`, `ai_tools`. Always registered (foundational). Wraps `StorageUserBackend`. Creates root user on startup. Protects root from deletion and external linking.
- `AuthService` — capability: `authentication`. Multi-backend aggregator over AuthProviders. Manages sessions in `auth_sessions` collection. Plugins add providers via `register_provider()`.

### Storage
- `StorageUserBackend` — implements `UserBackend` over `StorageBackend`. Collections: `users`, `provider_users`.
- Root user: id="root", email="root@localhost", is_root=true, cannot be deleted or linked to external providers.

### Context Propagation
- Hybrid: `contextvars` set by web middleware + explicit `user_ctx` param on key methods (e.g., `AIService.chat()`).
- `get_current_user()` / `set_current_user()` in `core/context.py`.

### Web Auth
- `AuthMiddleware` — checks cookie/bearer token, validates session, sets UserContext on request and contextvar.
- FastAPI dependencies: `get_user_context`, `require_authenticated`, `require_role(role)`.
- Routes: POST `/auth/login`, POST `/auth/logout`, GET `/auth/me`, POST `/auth/sync/{provider_type}`.

### Configuration
- `AuthConfig` in `config.py`: enabled, providers list, default_roles, session_ttl_seconds, root_password.
- Conversations now carry optional `user_id` for ownership.

### Roles
- Permissive by default — no checks unless explicitly configured.
- Roles are strings stored on user entities. External providers can map groups to roles.

## Related
- `src/gilbert/interfaces/auth.py` — UserContext, AuthInfo, AuthProvider
- `src/gilbert/interfaces/users.py` — UserBackend ABC
- `src/gilbert/core/context.py` — contextvars
- `src/gilbert/core/services/users.py` — UserService
- `src/gilbert/core/services/auth.py` — AuthService
- `src/gilbert/integrations/local_auth.py` — LocalAuthProvider
- `src/gilbert/storage/user_storage.py` — StorageUserBackend
- `src/gilbert/web/auth.py` — middleware and dependencies
- `src/gilbert/web/routes/auth.py` — auth endpoints
