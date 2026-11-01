# API Spec: Authentication

Huinsight is a single-user application. This document describes the implemented
password and bearer-token flow; it does not define GitHub access or Cloud Run IAM.
Production serves API routes under `/api`; local development also serves unprefixed
routes only when neither `UIS_GCS_BUCKET` nor `UIS_AUTH_TOKEN` is set.

## Credential setup and storage

- On first startup, `src/api/main.py` seeds the single `auth_credentials` row (`id=1`).
  It hashes `UIS_AUTH_TOKEN` with bcrypt, or generates a one-time password and writes
  it to the startup log if the variable is absent. An existing row is never replaced
  by a later environment-variable change.
- `auth_credentials` stores `password_hash`, `token_version` (initially `1`), and
  `updated_at` in DuckDB. The raw password is not stored in that table.
- Startup loads the hash and version into `src/api/auth_cache.py`. Login and bearer
  validation use that in-memory cache rather than opening DuckDB connections while
  a sync may hold a write connection. Password change and global logout update the
  database and refresh the cache immediately. This assumes one serving process;
  the Cloud Run deployment sets `--max-instances=1`.
- `UIS_AUTH_TOKEN` is also the middleware's auth-enabled switch. If it is unset,
  the middleware allows all requests, even if a credential row exists. Set it for
  any reachable deployment. In Cloud Run it comes from GCP Secret Manager.

## `POST /api/auth/login`

Unauthenticated. Request: `{ "password": "string" }`.

- `200`: `{ "token": "<password>.<token_version>" }` after bcrypt verification.
  This is a password-bearing token, not a random or signed session token. It has
  no separate expiry; it remains valid until the password or version changes.
- `401`: `{ "detail": "Invalid password" }`.
- `503`: auth is not configured or its stored hash is corrupt.

The frontend stores the returned token in `localStorage` under `uis-auth-token`.
`authFetch` sends it as `Authorization: Bearer <token>` on API requests and clears
local storage on a `401` response. Local logout removes only that browser's token;
it does not revoke tokens held by other browsers.

## Request validation and exemptions

`BearerTokenMiddleware` compares the version in a bearer token with the cached
version and checks the password part against the cached bcrypt hash. Missing or
invalid credentials return `401` with `WWW-Authenticate: Bearer`.

When auth is enabled, these requests bypass bearer validation:

- `OPTIONS` requests; `GET /health` and `GET /health/deep`.
- `POST /api/auth/login`.
- Non-`/api/` GET requests for the SPA shell and static assets. API routers are
  mounted only under `/api` when auth or GCS mode is enabled.
- `GET /api/sync/stream` with a valid stream ticket (see below).

`POST /api/settings/sources/fetch/{reader}` also accepts a Google-signed OIDC ID
token from the configured Cloud Scheduler service account. The middleware verifies
its audience, service-account email, and signature; otherwise it falls back to
normal password-bearer validation. This exception applies only to that fetch path.

## `GET /api/auth/validate`

Requires a valid bearer token. Returns `200 { "ok": true }`; invalid or missing
tokens receive the middleware's `401` response. The current frontend does not
call this endpoint on page load: it initially treats a locally stored token as
present, and an API `401` clears it.

## `POST /api/auth/change-password`

Requires a valid bearer token and
`{ "current_password": "string", "new_password": "string" }`.
The endpoint verifies the current password, bcrypt-hashes the new one, increments
`token_version`, refreshes the cache, and returns
`200 { "token": "<new_password>.<new_version>" }`. Earlier tokens are invalid.
An incorrect current password returns `401`; a new password containing `.`
returns `400` because `.` separates the token version. The backend does not
enforce a minimum password length.

## `POST /api/auth/logout-all`

Requires a valid bearer token. Increments `token_version`, refreshes the cache,
and returns `200 { "ok": true }`. This invalidates previously issued tokens,
including the caller's. It does not change the password; a new login can issue
a token with the new version.

## Sync log SSE ticket

Native `EventSource` cannot send the bearer header. The frontend first calls
`POST /api/sync/stream-ticket` with its normal bearer token and receives
`{ "ticket": "<random-ticket>" }`. It then connects to
`GET /api/sync/stream?ticket=<random-ticket>`. Tickets are generated with
`secrets.token_urlsafe(32)`, kept in memory, valid only for this stream, and
reusable for 10 minutes so EventSource can reconnect. `?token=<password>` is
not accepted. The in-memory store also assumes a single serving process.

## Schema

```sql
CREATE TABLE IF NOT EXISTS auth_credentials (
    id INTEGER PRIMARY KEY DEFAULT 1,
    password_hash VARCHAR NOT NULL,
    token_version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
