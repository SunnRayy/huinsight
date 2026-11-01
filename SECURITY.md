# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for a security vulnerability.

Use GitHub's private vulnerability reporting instead: go to this repo's
**Security** tab → **Report a vulnerability**. That opens a private
conversation with the maintainer, is the standard GitHub-native mechanism,
and doesn't require exchanging contact details up front.

Include what you'd include in any good bug report: what you found, how to
reproduce it, and what you think the impact is. If it's a credential or
data-exposure issue, please avoid including a real example that leaks
someone else's data.

There's no fixed SLA — this is a single-maintainer project — but a genuine
security report will be prioritized over everything else in the backlog.

## What's in scope

- The application code (`src/`, `ux-command-center/`) and its API surface.
- The deploy pipeline (`.github/workflows/`, `Dockerfile`) — e.g. a way to
  exfiltrate secrets from a CI run, or a container escape.
- Auth bypass on a deployed instance (see the model below).

## What's explicitly out of scope

- Vulnerabilities in third-party dependencies with no Huinsight-specific exploit
  path — report those upstream instead (though a heads-up is still welcome).
- "This stores my financial data in a database I control" — that's the
  design, not a bug. Huinsight is a single-user, self-hosted tool; there is no
  multi-tenant isolation to break because there's no multi-tenancy.
- Denial-of-service against your own self-hosted instance.

## Security model, briefly

Huinsight is a **single-user, self-hosted** application — not a multi-tenant SaaS.
There is no user database, no signup flow, no per-user row-level access
control, because there's exactly one user per deployment: whoever holds the
auth token.

- **Auth**: `UIS_AUTH_TOKEN` supplies the initial password and enables the
  bearer middleware. The first boot stores a bcrypt hash and token version in
  DuckDB. The login response and each bearer header contain the password plus
  version; they are not short-lived session tokens. Password change and
  logout-all invalidate earlier versions. See [`docs/api-specs/auth.md`](docs/api-specs/auth.md)
  for the exact endpoints and exemptions. A deployment without `UIS_AUTH_TOKEN`
  has authentication disabled, regardless of whether the DB has a credential.
- **Secrets**: API keys and the initial auth password come from environment
  variables / GCP Secret Manager, never the repository. Local development uses
  a gitignored `.env`. The password hash and version are stored in DuckDB;
  the browser keeps the password-bearing token in `localStorage`. If no initial
  password is configured, first boot generates one and writes it once to the
  startup log. Treat logs and browser storage accordingly.
- **Database**: DuckDB, a single file. Locally, filesystem permissions are
  your only access control — treat `data/unified.duckdb` like you'd treat
  any file containing your brokerage statements, because that's what it is.
  On Cloud Run, the file lives in a private GCS bucket, downloaded into the
  container at startup and flushed back on writes; the bucket itself needs
  the same IAM discipline as any other private storage.
- **Your own source files**: CSVs/Excel workbooks you point a reader at
  never leave your machine (local) or your configured storage (cloud) except
  through the sync pipeline you control.

If you're self-hosting on Cloud Run, `--allow-unauthenticated` in
`deploy.yml` means the *endpoint* is public — the configured application
authentication is what actually gates access, not network-level restriction.
If you want network
restriction too (e.g. IAP, a VPC), that's a deployment choice this project
doesn't currently make for you.
