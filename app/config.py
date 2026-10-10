"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Storage and limits
    MAX_UPLOAD_MB: int = 50
    STORAGE_DIR: str = "uploads"

    # Database
    DATABASE_URL: str = "sqlite:///./geo_measure.db"

    # Accuracy check
    DIFF_THRESHOLD_PCT: float = 0.5  # 0.5% threshold for geodesic fallback

    # Zip safety
    MAX_ZIP_ENTRIES: int = 500
    MAX_UNCOMPRESSED_MB: int = 200

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def max_uncompressed_bytes(self) -> int:
        return self.MAX_UNCOMPRESSED_MB * 1024 * 1024

    @property
    def storage_path(self) -> Path:
        path = Path(self.STORAGE_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
