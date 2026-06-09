"""Notification dispatcher config — read from env vars at startup."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Kafka
    kafka_bootstrap: str = Field(default="", alias="KAFKA_BOOTSTRAP")
    kafka_topic: str = Field(default="po.status.changed", alias="KAFKA_TOPIC")
    kafka_group_id: str = Field(default="notification-dispatcher", alias="KAFKA_GROUP_ID")

    # Channels — empty = disabled
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")
    teams_webhook_url: str = Field(default="", alias="TEAMS_WEBHOOK_URL")

    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="noreply@procurement-agent.local", alias="SMTP_FROM")

    # PostgreSQL (used only to resolve recipient email from a txn_id)
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="procurement_agent", alias="DB_NAME")
    db_user: str = Field(default="", alias="DB_USER")
    db_password: str = Field(default="", alias="DB_PASSWORD")
