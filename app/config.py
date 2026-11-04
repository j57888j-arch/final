from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False,
        extra="ignore", populate_by_name=True,
    )

    bot_token: SecretStr = Field(default=SecretStr(""), alias="BOT_TOKEN")
    bot_username: str = Field(default="", alias="BOT_USERNAME")
    database_url: str = Field(default="sqlite+aiosqlite:///./weraqambot.db", alias="DATABASE_URL")
    redis_url: str = Field(default="", alias="REDIS_URL")
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")
    admin_chat_id: str = Field(default="", alias="ADMIN_CHAT_ID")

    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    default_currency: str = Field(default="UZS", alias="DEFAULT_CURRENCY")
    money_scale: int = Field(default=100, alias="MONEY_SCALE", ge=1, le=10000)

    payment_mode: Literal["disabled", "manual", "test"] = Field(default="disabled", alias="PAYMENT_MODE")
    payment_card_number: str = Field(default="", alias="PAYMENT_CARD_NUMBER")
    payment_card_holder: str = Field(default="", alias="PAYMENT_CARD_HOLDER")
    telegram_stars_enabled: bool = Field(default=False, alias="TELEGRAM_STARS_ENABLED")
    click_enabled: bool = Field(default=False, alias="CLICK_ENABLED")
    click_merchant_id: str = Field(default="", alias="CLICK_MERCHANT_ID")
    click_service_id: str = Field(default="", alias="CLICK_SERVICE_ID")
    click_secret_key: SecretStr = Field(default=SecretStr(""), alias="CLICK_SECRET_KEY")
    phone_encryption_key: SecretStr = Field(default=SecretStr(""), alias="PHONE_ENCRYPTION_KEY")

    webhook_url: str = Field(default="", alias="WEBHOOK_URL")
    webhook_secret: SecretStr = Field(default=SecretStr(""), alias="WEBHOOK_SECRET")
    auto_create_tables: bool = Field(default=True, alias="AUTO_CREATE_TABLES")
    support_username: str = Field(default="", alias="SUPPORT_USERNAME")
    sentry_dsn: SecretStr = Field(default=SecretStr(""), alias="SENTRY_DSN")
    outbox_poll_seconds: float = Field(default=2.0, alias="OUTBOX_POLL_SECONDS", gt=0)
    outbox_batch_size: int = Field(default=25, alias="OUTBOX_BATCH_SIZE", ge=1, le=500)
    payment_expiration_minutes: int = Field(default=30, alias="PAYMENT_EXPIRATION_MINUTES", ge=5, le=1440)
    referral_bonus_minor: int = Field(default=0, alias="REFERRAL_BONUS_MINOR", ge=0)
    max_broadcast_per_minute: int = Field(default=25, alias="MAX_BROADCAST_PER_MINUTE", ge=1, le=100)

    @field_validator("default_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("DEFAULT_CURRENCY must be a 3-letter currency code")
        return value

    @property
    def admin_ids(self) -> set[int]:
        values: set[int] = set()
        for item in self.admin_ids_raw.split(","):
            item = item.strip()
            if item:
                try:
                    values.add(int(item))
                except ValueError as exc:
                    raise ValueError(f"Invalid Telegram ID in ADMIN_IDS: {item}") from exc
        return values

    @property
    def async_database_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        return url

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def check_production_requirements(self) -> "Settings":
        if self.is_production and not self.redis_url:
            raise ValueError("REDIS_URL is required in production (FSM must be persistent)")
        if self.is_production and not self.database_url.strip().startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
            raise ValueError("Production DATABASE_URL must point to PostgreSQL")
        if self.is_production and not self.admin_ids:
            raise ValueError("ADMIN_IDS must contain at least one bootstrap administrator")
        if self.is_production and not self.bot_token.get_secret_value().strip():
            raise ValueError("BOT_TOKEN is required in production")
        if self.click_enabled:
            raise ValueError(
                "CLICK adapter is intentionally disabled in this build. Keep CLICK_ENABLED=false "
                "until the merchant Prepare/Complete signature contract is implemented and tested."
            )
        return self


def get_settings() -> Settings:
    return Settings()
