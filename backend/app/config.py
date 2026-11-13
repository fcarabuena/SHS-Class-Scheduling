from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

ROOT_DIR = Path(__file__).resolve().parents[2]


def _origin(value: str) -> str:
    """'https://site.app/' or ' "https://Site.app/register" ' -> 'https://site.app' (what browsers send)."""
    value = value.strip().strip("\"'").strip()
    parts = urlsplit(value)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else value.rstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "shs_scheduler"
    # A hosted database's full connection string (for example from Neon). When set, the
    # POSTGRES_* values above are ignored.
    database_url_text: str = Field(default="", validation_alias="DATABASE_URL")

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480

    cors_origins: str = "http://localhost:3000"

    max_import_bytes: int = 2 * 1024 * 1024
    max_import_rows: int = 5000

    # Where the web app is reached; used to build public share links.
    public_app_url: str = "http://localhost:3000"
    # Comma-separated emails of the people who run the whole platform (all schools).
    platform_admin_emails: str = ""
    # Shared secret a payment provider signs its webhook calls with. Empty = webhook off.
    billing_webhook_secret: str = ""

    # Web push for people who follow a section's timetable. Empty = following is off.
    # Generate a pair with: python -m app.push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # A contact the push services can reach about this server (mailto: or https:).
    vapid_subject: str = "mailto:noreply@example.com"

    # Rate limits, as "attempts/seconds".
    rate_limit_login: str = "10/300"
    rate_limit_register: str = "5/3600"
    rate_limit_public: str = "120/60"

    @property
    def allowed_origins(self) -> list[str]:
        """Websites allowed to call the API: CORS_ORIGINS plus the site in PUBLIC_APP_URL, tidied up,
        so a stray space, quote, trailing slash or path in a setting cannot lock the website out."""
        return sorted({_origin(v) for v in [*self.cors_origins.split(","), self.public_app_url] if v.strip()})

    @property
    def platform_admins(self) -> set[str]:
        return {e.strip().lower() for e in self.platform_admin_emails.split(",") if e.strip()}

    @property
    def database_url(self) -> URL:
        if self.database_url_text:
            # Used as given (host, SSL options...); only the driver is set to the one this app uses.
            return make_url(self.database_url_text).set(drivername="postgresql+psycopg")
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


settings = Settings()
