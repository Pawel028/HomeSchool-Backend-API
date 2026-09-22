"""Run the whole backend without Docker: embedded PostgreSQL + migrations + seed + a content admin + the API.

    python scripts/dev_server.py [--port 8000] [--data-dir .devdb]

Development only (needs the dev requirements: pgserver). Prints the admin login. Ctrl+C stops the API and PostgreSQL.
The data directory is kept between runs; delete it for a clean database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--data-dir", default=str(ROOT / ".devdb"))
    ap.add_argument("--admin-email", default="admin@example.com")
    ap.add_argument("--admin-password", default="dev-admin-password-1")
    ap.add_argument(
        "--cors", default="http://localhost:5173,http://localhost:4173,http://localhost:4280,http://localhost:3000"
    )
    args = ap.parse_args()

    import pgserver
    import uvicorn

    server = pgserver.get_server(args.data_dir, cleanup_mode="stop")
    admin_uri = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    os.environ.update(
        APP_ENV="dev",
        EXPOSE_DEV_OTP="true",
        OTP_PROVIDER="console",
        CORS_ORIGINS=args.cors,
        JWT_SECRET="local-dev-only-jwt-secret-not-for-deployment",
        LOG_JSON="false",
        LOG_LEVEL="INFO",
        DATABASE_URL=admin_uri,
        SEED_ON_STARTUP="false",
    )

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from app import cli, config, db

    with create_engine(make_url(admin_uri), isolation_level="AUTOCOMMIT").connect() as c:
        if not c.execute(text("select 1 from pg_database where datname = 'homeschool'")).scalar():
            c.execute(text("create database homeschool"))
    admin_url = make_url(admin_uri).set(database="homeschool")
    os.environ["DATABASE_URL"] = admin_url.render_as_string(hide_password=False)
    config.reset_settings_cache()
    cli.migrate()
    cli.ensure_app_role("homeschool_app", "local-dev-only-app-password")
    os.environ["DATABASE_URL"] = admin_url.set(
        username="homeschool_app", password="local-dev-only-app-password"
    ).render_as_string(hide_password=False)
    config.reset_settings_cache()
    db.dispose_engine()
    cli.seed_from_path(str(ROOT / "seed" / "launch-bundle.json"), auto_publish=True)
    os.environ["ADMIN_PASSWORD"] = args.admin_password
    cli.create_admin(args.admin_email, "Local Admin", "super_admin")
    print(
        f"\nAPI:   http://127.0.0.1:{args.port}   (docs at /docs)\nAdmin: {args.admin_email} / {args.admin_password}\n"
    )
    try:
        uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=args.port, log_level="info")
    finally:
        server.cleanup()


if __name__ == "__main__":
    main()
