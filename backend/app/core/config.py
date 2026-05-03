"""应用配置 - 基于 pydantic-settings"""

import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，从环境变量和 .env 文件读取"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库
    DATABASE_URL: str = "postgresql+psycopg://quiz_user:quiz_pass@localhost:5432/quiz_app"

    # JWT
    JWT_SECRET_KEY: str = "jwt-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 7 天

    # 文件上传
    MAX_UPLOAD_SIZE_MB: int = 50

    # 存储
    STORAGE_ROOT: str = "./storage"

    # AI 配置
    AI_API_BASE_URL: str = "https://api.openai.com"
    AI_API_KEY: str = ""
    AI_MODEL: str = "gpt-4o-mini"

    # Worker 配置
    WORKER_LEASE_SECONDS: int = 600
    WORKER_POLL_INTERVAL_SECONDS: int = 3

    # 加密密钥（用于 SystemSetting 加密）
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    SYSTEM_SETTINGS_ENCRYPTION_KEY: Optional[str] = None

    @property
    def upload_max_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


settings = Settings()
