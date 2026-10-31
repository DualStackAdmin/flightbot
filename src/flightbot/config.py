"""Mərkəzləşdirilmiş konfiqurasiya. Bütün dəyərlər mühit dəyişənlərindən (və ya .env) gəlir."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Ümumi ---
    env: Literal["dev", "prod", "test"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False
    sentry_dsn: str = ""
    metrics_port: int = 9100
    default_tenant_id: int = 1

    # --- Verilənlər bazası ---
    database_url: str = "postgresql+asyncpg://flightbot:flightbot@localhost:5432/flightbot_dev"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    # PgBouncer (transaction mode) arxasında 0 təyin edin.
    db_statement_cache_size: int = 100

    # --- Redis (FSM, keş, rate limiter). Heç bir kritik data yoxdur: bildirişlər Postgres-dədir. ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Telegram ---
    bot_token: SecretStr = SecretStr("")
    bot_mode: Literal["polling", "webhook"] = "polling"
    webhook_base_url: str = ""
    webhook_path: str = "/telegram/webhook"
    webhook_secret: SecretStr = SecretStr("")
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    # Telegram: ~30 msg/s qlobal. 5 msg/s canlı istifadəçi cavabları üçün ehtiyat.
    telegram_global_rps: float = 25.0
    telegram_user_rps: float = 1.0

    # --- Qiymət provayderi ---
    provider: Literal["fake", "travelpayouts"] = "fake"
    travelpayouts_token: SecretStr = SecretStr("")
    # Partnyor ID (marker). Real Travelpayouts kabinetində təsdiqləyin.
    travelpayouts_marker: str = "794979"
    provider_rps: float = 3.0
    provider_timeout_s: float = 15.0

    # --- Worker-lər ---
    poller_batch: int = 20
    poller_concurrency: int = 5
    poller_lease_s: int = 300
    poller_idle_s: float = 2.0
    broadcaster_batch: int = 40
    broadcaster_concurrency: int = 10
    broadcaster_lease_s: int = 120
    broadcaster_idle_s: float = 1.0
    broadcaster_max_attempts: int = 5
    janitor_interval_s: int = 3600

    # --- Sakit saatlar: bildiriş bu pəncərədə yox, pəncərə bitəndə göndərilir (istifadəçi söndürə bilər) ---
    quiet_tz: str = "Asia/Baku"
    quiet_start_hour: int = 23
    quiet_end_hour: int = 8

    # --- Məhsul ---
    default_language: Literal["az", "ru", "en"] = "az"
    default_home_iata: str = "GYD"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
