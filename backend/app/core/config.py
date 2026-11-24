import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.signing import KEY_ID_PATTERN, InvalidKeyError, load_private_key, load_public_key


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = "local"
    database_url: str = "postgresql+psycopg:///fikso_dev"

    jwt_secret: SecretStr = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # Secure cookies need HTTPS; only local development may turn this off.
    cookie_secure: bool = True

    cors_origins: list[str] = []

    # Per client IP and window. In-process: valid for one backend instance (ARCHITECTURE §7).
    rate_limit_window_seconds: int = 60
    rate_limit_login: int = 10
    rate_limit_register: int = 5
    # SMS sign-in codes requested per client IP and window (each one costs an SMS).
    rate_limit_sms_code: int = 3
    rate_limit_upload: int = 10
    rate_limit_enabled: bool = True
    # "postgres" shares limits across processes and hosts (required in production); "memory" is per process.
    rate_limit_backend: Literal["memory", "postgres"] = "postgres"
    rate_limit_request_photo: int = 15
    # Proxies whose X-Forwarded-For is believed (CIDRs, e.g. the load balancer). Empty: the peer address
    # is used.
    trusted_proxies: list[str] = []

    log_level: str = "INFO"

    # W-ID authority (R-CAT-16): production is the only issuer of permanent catalogue IDs, staging only
    # receives production exports, local/test databases are isolated fixtures whose packages nobody accepts.
    catalogue_role: Literal["issuer", "receiver", "isolated"] = "isolated"
    # Ed25519 package signing (R-CAT-17). Production: private key + key ID. Staging: public keys only, so it
    # can verify packages but never sign one that would pass as production. Keys: base64 of the raw 32 bytes.
    catalogue_signing_private_key: SecretStr | None = None
    catalogue_signing_key_id: str | None = Field(default=None, pattern=KEY_ID_PATTERN)
    catalogue_trusted_public_keys: dict[str, str] = {}
    catalogue_revoked_key_ids: list[str] = []

    # Private evidence files (R-MST-15). Local directory for dev/test; must not be under any served path.
    storage_local_dir: str = "var/uploads"
    # Processed public catalogue images (OQ-10): a different directory from private files, never mixed.
    storage_public_dir: str = "var/public-media"
    # File storage: "local" directories (dev/test) or S3-compatible object storage with two separate buckets.
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None
    s3_region: str = "eu-central-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_private_bucket: str | None = None
    s3_public_bucket: str | None = None
    # SSE-S3 (AES256); turn off only for an S3-compatible service that does not support it.
    s3_server_side_encryption: bool = True
    rate_limit_public: int = 120
    public_cache_seconds: int = 60
    rate_limit_requests: int = 20
    rate_limit_location: int = 6
    # Maps/geocoding/ETA provider (Q-02 open). "none": straight-line ETA at the fallback speed, and address
    # geocoding through the development stub, which production refuses.
    maps_provider: Literal["none", "google", "osrm"] = "none"
    # Unset: the stub in local/test only, no geocoder elsewhere (clients then share their device location).
    geocoder: Literal["stub", "none", "google"] | None = None
    google_maps_api_key: SecretStr | None = None
    osrm_base_url: str | None = None
    provider_timeout_seconds: float = Field(default=4.0, gt=0, le=30)
    sms_provider: Literal["none", "messente"] = "none"
    messente_api_username: str | None = None
    messente_api_password: SecretStr | None = None
    sms_sender: str | None = None
    # Shared secret in the delivery-report callback URL (?token=...), so nobody else can mark SMS delivered.
    sms_webhook_token: SecretStr | None = None
    # Public origin of the app (e.g. https://app.fiksoapp.eu): cookie-authenticated POSTs from other
    # origins fail.
    app_origin: str | None = None
    # Q-29: expiry warnings in the master and admin UI start this many days before `valid_until`.
    qualification_expiry_warning_days: int = Field(default=30, ge=0)

    @model_validator(mode="after")
    def _check_catalogue_role(self) -> "Settings":
        if self.geocoder is None:
            self.geocoder = "stub" if self.environment in ("local", "test") else "none"
        if self.environment == "production" and self.geocoder == "stub":
            raise ValueError("The development geocoder stub must not be used in production (GEOCODER).")
        if (self.environment == "production") != (self.catalogue_role == "issuer"):
            raise ValueError("CATALOGUE_ROLE must be 'issuer' in production and only there.")
        has_private = self.catalogue_signing_private_key is not None
        if self.catalogue_role == "issuer" and not (has_private and self.catalogue_signing_key_id):
            raise ValueError("The issuer needs CATALOGUE_SIGNING_PRIVATE_KEY and CATALOGUE_SIGNING_KEY_ID.")
        if self.catalogue_role == "receiver":
            if has_private:
                raise ValueError("A receiver must not hold the catalogue signing private key.")
            if not self.catalogue_trusted_public_keys:
                raise ValueError("A receiver needs at least one key in CATALOGUE_TRUSTED_PUBLIC_KEYS.")
        try:
            if self.catalogue_signing_private_key is not None:
                load_private_key(self.catalogue_signing_private_key.get_secret_value())
            for key_id, public_key in self.catalogue_trusted_public_keys.items():
                if not re.match(KEY_ID_PATTERN, key_id):
                    raise ValueError(f"invalid key ID {key_id!r}")
                load_public_key(public_key)
        except InvalidKeyError as exc:
            # Never echo key material: only the kind of problem.
            raise ValueError(f"Invalid catalogue signing key: {exc}") from None
        return self

    @model_validator(mode="after")
    def _check_providers_and_production(self) -> "Settings":
        """Fail at start-up on a configuration that would silently misbehave. Secrets are never echoed."""
        problems = []
        if "google" in (self.geocoder, self.maps_provider) and self.google_maps_api_key is None:
            problems.append("GOOGLE_MAPS_API_KEY is required for the google geocoder/maps provider")
        if self.maps_provider == "osrm" and not self.osrm_base_url:
            problems.append("OSRM_BASE_URL is required for MAPS_PROVIDER=osrm")
        if self.sms_provider == "messente" and not (
            self.messente_api_username
            and self.messente_api_password
            and self.sms_sender
            and self.sms_webhook_token
        ):
            problems.append(
                "MESSENTE_API_USERNAME/PASSWORD, SMS_SENDER and SMS_WEBHOOK_TOKEN are required for SMS"
            )
        if self.storage_backend == "s3":
            if not (self.s3_private_bucket and self.s3_public_bucket):
                problems.append("S3_PRIVATE_BUCKET and S3_PUBLIC_BUCKET are required for STORAGE_BACKEND=s3")
            elif self.s3_private_bucket == self.s3_public_bucket:
                problems.append("private and public files must use two different buckets")
            if (self.s3_access_key_id is None) != (self.s3_secret_access_key is None):
                problems.append(
                    "set both S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY, or neither (instance role)"
                )
        if self.environment in ("production", "staging"):
            if self.storage_backend != "s3":
                problems.append(
                    "STORAGE_BACKEND=s3 is required outside local/test (local disks are per host)"
                )
            if self.rate_limit_backend != "postgres":
                problems.append("RATE_LIMIT_BACKEND=postgres is required outside local/test")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true outside local/test")
            if not (self.app_origin and self.app_origin.startswith("https://")):
                problems.append("APP_ORIGIN (https://...) is required outside local/test")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
