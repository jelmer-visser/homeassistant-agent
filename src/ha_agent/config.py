"""Configuration loaded from environment variables / .env file."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Home Assistant
    ha_base_url: str = "http://localhost:8123"
    ha_token: str

    # Anthropic
    anthropic_api_key: str

    # Scheduling
    agent_interval_minutes: int = 30
    history_hours: int = 24
    max_history_points: int = 48          # per sensor — ~30-min buckets over 24h

    # Sensors config file
    sensors_config_path: Path = Path("config/sensors.yaml")

    # Delivery
    notify_ha: bool = True
    enable_web_ui: bool = False
    web_ui_port: int = 8080

    # Logging
    log_level: str = "INFO"
    log_dir: Path = Path("logs")

    # Electricity pricing
    tariff_type: str = "fixed"            # "fixed" or "dynamic"
    fixed_day_rate: float = 0.359         # €/kWh day tariff
    fixed_night_rate: float = 0.303       # €/kWh night tariff

    # Nord Pool sensor entity ID (used when tariff_type="dynamic")
    nordpool_entity_id: str = "sensor.nordpool_kwh_nl_eur_3_10_021"

    @field_validator("ha_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("log_dir")
    @classmethod
    def ensure_log_dir(cls, v: Path) -> Path:
        v.mkdir(parents=True, exist_ok=True)
        return v


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
