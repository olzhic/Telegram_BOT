from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Configuration settings for FastAPI backend."""

    DEMO_MODE: bool = False
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = ApiSettings()
