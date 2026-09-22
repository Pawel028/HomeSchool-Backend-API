# backend-api

Python (FastAPI) backend for the HomeSchooling platform: accounts and families, guardian verification (India's
DPDP Act), child profiles and child-scoped sessions, the curriculum/activity catalogue, weekly planning, activity
sessions with server-side scoring, the mastery/streak progress model, recommendations, and a content-admin API.
Single service, one PostgreSQL database, Row-Level Security as a second line of defence behind application checks.

## Contents

```
app/                the application (config, db/RLS, security, errors, services/, routers/, cli.py, main.py)
migrations/          Alembic; migrations/versions/0001_initial.py is the full schema as one script (see below)
seed/launch-bundle.json  the 15 launch activities + taxonomy, built from ../content-curriculum
tests/               pytest; runs against a REAL PostgreSQL (embedded via pgserver, or TEST_DATABASE_URL in CI)
scripts/             export_contracts.py, sync_contracts.py, dev_server.py (no-Docker local run)
.env.dev / .env.nonprod / .env.prod / .env.test / .env.example / .env.local.example
Dockerfile, docker-compose.yml
```

## Install (Windows PowerShell or macOS/Linux)

Requires Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

## Run locally without Docker (fastest way to try the API)

```bash
python scripts/dev_server.py
```

Brings up an embedded PostgreSQL (no install needed — the `pgserver` package), runs migrations, creates the
least-privilege `homeschool_app` database role, seeds `seed/launch-bundle.json` (15 published activities), creates a
`super_admin` (prints the email/password), and serves the API at `http://127.0.0.1:8000` (interactive docs at
`/docs` since `APP_ENV=dev`). Ctrl+C stops the API and the embedded database together.

## Run locally with Docker

```bash
docker compose up --build
```

Starts PostgreSQL 16, a one-shot `release` job (migrations + the app database role + seed), then the API on
`http://localhost:8000`. See `docker-compose.yml`'s comments for the (local-only) default credentials.

## Environment files

`APP_ENV` (`dev` / `nonprod` / `prod` / `test`) picks `.env.<APP_ENV>`, loaded by `app/config.py`'s `Settings`
(pydantic-settings) with real environment variables always taking precedence over the file. **No `.env.*` file
in this repo contains a secret** — `.env.dev`/`.env.nonprod`/`.env.prod` hold only non-secret defaults; secrets
(`DB_PASSWORD`, `JWT_SECRET`, `OTP_WEBHOOK_TOKEN`) come from real environment variables (Key Vault references in
Azure, or `.env.local` — git-ignored — for a native local run against the docker-compose database; see
`.env.local.example`). `Settings._guard_deployed_environments` **refuses to start** in `nonprod`/`prod` with a
placeholder JWT secret, `CORS_ORIGINS=*`, `DB_SSLMODE` below `require`, `EXPOSE_DEV_OTP=true`, or (in `prod`)
anything but the `webhook` OTP provider with an `https://` URL — misconfiguration fails fast instead of running
insecurely. `.env.example` documents every setting the API reads.

## Database and migrations

`migrations/versions/0001_initial.py` is the whole schema as one hand-written SQL migration (not
autogenerate) — every table, index, the `content` schema, and the Row-Level Security policies (`family_isolation`
on `children`, `consents`, `plans`, `plan_items`, `activity_sessions`, `skill_evidence`, `skill_mastery`, enforced
with `FORCE ROW LEVEL SECURITY` so even the table owner can't bypass it — the API itself connects as a separate,
non-superuser role, `homeschool_app`, that cannot bypass RLS either). `app/db.py` writes the caller's identity
(`app.user_id` for a parent, `app.family_id` for a child token) into Postgres session settings at the start of
every transaction; `app_can_access_family()` (SQL function) is what the RLS policies call.

```bash
python -m app.cli migrate              # alembic upgrade head
python -m app.cli ensure-app-role       # creates/rotates the homeschool_app role (needs admin DB credentials)
python -m app.cli seed --path seed/launch-bundle.json --publish
python -m app.cli create-admin --email you@example.com --name "You" --role super_admin
python -m app.cli release               # migrate + ensure-app-role (if APP_DB_PASSWORD set) + seed (if SEED_BUNDLE_PATH set)
```

`python -m app.cli --help` documents every command; `release` is what `docker-compose.yml`, `scripts/dev_server.py`
and the Azure Container Apps release Job all call.

## Testing

```bash
pytest                       # embedded PostgreSQL (pgserver) if TEST_DATABASE_URL is unset
ruff check . && ruff format --check .
```

120 tests, all against a real PostgreSQL with real migrations and real RLS (no mocked database) — auth and token
rotation, PIN lockout tiers, guardian verification, child-token isolation, RLS enforcement at the SQL level
(including that the application role cannot bypass it, alter the schema, or edit the audit log), the mastery and
streak rules against the shared `api-contracts` test vectors, activity-session scoring for every step type,
content admin/publishing/bundle-import workflows, and the CLI. CI (`.github/workflows/ci.yml`) runs the same
suite against a `postgres:16` service container.

## Keeping the API contract in sync

```bash
python scripts/export_contracts.py --out ../api-contracts   # regenerates openapi.json + errors.yaml
python scripts/sync_contracts.py                            # refreshes vendored copies (activity schema, test vectors, seed bundle)
```

CI fails if `openapi.json` has drifted from what's committed in `../api-contracts` (soft-fails if that sibling
repo isn't checked out next to this one).

## Deploying

See the project's deployment guide (PDF) for the full Azure walkthrough. In short: `Dockerfile` builds the image,
`.github/workflows/deploy.yml` builds it into Azure Container Registry, runs the release Job, then updates the
Container App — all names come from the `infra` repo's Terraform outputs.
