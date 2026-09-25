"""Application settings.

Precedence (highest first): real environment variables (for example from Azure Container Apps / Key Vault),
then the env file for the selected environment (.env.dev, .env.nonprod, .env.prod, .env.test; in dev/test also the
untracked .env.local), then defaults.
The environment is chosen with APP_ENV (dev | nonprod | prod | test). Secrets never live in the env files.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

AppEnv = Literal["dev", "nonprod", "prod", "test"]
PLACEHOLDER_SECRETS = {"", "change-me", "changeme", "dev-secret-change-me"}


def env_file_for(app_env: str) -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f".env.{app_env}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    app_env: AppEnv = "dev"
    app_name: str = "homeschool-api"
    log_level: str = "INFO"
    log_json: bool = True

    # HTTP
    cors_origins: str = ""  # comma separated
    trusted_hosts: str = "*"

    # Database (components are used unless DATABASE_URL is set)
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "homeschool"
    db_user: str = "homeschool"
    db_password: SecretStr = SecretStr("")
    db_sslmode: str = "prefer"
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # Tokens
    jwt_secret: SecretStr = SecretStr("dev-secret-change-me")
    jwt_issuer: str = "homeschool-api"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    child_token_minutes: int = 60
    elevation_minutes: int = 5

    # Guardian verification (OTP + declaration is the MVP method, see 23_COMPLIANCE_DPDP)
    otp_provider: Literal["console", "webhook", "disabled"] = (
        "console"  # console = writes the code to the log (dev/test/nonprod only)
    )
    otp_webhook_url: str | None = None  # webhook = POST {"to", "message"} to your SMS gateway
    otp_webhook_token: SecretStr = SecretStr("")
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    expose_dev_otp: bool = False  # returns the code in the API response: local development only
    otp_static_test_code: str | None = None  # TESTING ONLY: forces every generated OTP to this fixed
    # value, so a whole group of testers can share one known code instead of each needing real delivery.
    # Never allowed when APP_ENV=prod (guarded below): would let anyone verify as guardian for any phone
    # number without ever receiving anything.
    declaration_notice_version: str = "2026-09-draft"

    # Features and client policy
    min_app_version: str = "0.1.0"
    enable_recommendations: bool = True
    seed_on_startup: bool = False
    seed_bundle_path: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str | URL:
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value() or None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"sslmode": self.db_sslmode},
        )

    @property
    def is_deployed(self) -> bool:
        return self.app_env in ("nonprod", "prod")

    @model_validator(mode="after")
    def _guard_deployed_environments(self) -> Settings:
        if self.is_deployed:
            secret = self.jwt_secret.get_secret_value()
            if secret in PLACEHOLDER_SECRETS or len(secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters in nonprod/prod")
            if self.expose_dev_otp:
                raise ValueError("EXPOSE_DEV_OTP must be false in nonprod/prod")
            if "*" in self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must list explicit origins in nonprod/prod")
            if not self.database_url and not self.db_password.get_secret_value():
                raise ValueError("DB_PASSWORD (or DATABASE_URL) must be set in nonprod/prod")
            if self.db_sslmode in ("disable", "allow", "prefer"):
                raise ValueError("DB_SSLMODE must be require or stronger in nonprod/prod")
            if self.app_env == "prod" and self.otp_provider != "webhook":
                raise ValueError("OTP_PROVIDER must be webhook in prod (the console provider writes codes to the log)")
            if self.app_env == "prod" and self.otp_static_test_code:
                raise ValueError("OTP_STATIC_TEST_CODE must never be set in prod")
            if self.otp_provider == "webhook" and not (self.otp_webhook_url or "").startswith("https://"):
                raise ValueError("OTP_WEBHOOK_URL must be an https URL when OTP_PROVIDER=webhook")
        return self


@lru_cache
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "dev")
    files = [env_file_for(app_env)]
    if app_env in ("dev", "test"):
        files.append(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.local")
        )  # untracked overrides
    return Settings(_env_file=files)  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    get_settings.cache_clear()
