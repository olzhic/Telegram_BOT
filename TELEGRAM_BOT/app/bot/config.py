from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Configuration settings for Telegram Bot."""

    TELEGRAM_BOT_TOKEN: str = ""
    API_BASE_URL: str = "http://127.0.0.1:8000"
    API_TIMEOUT_SECONDS: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


bot_settings = BotSettings()
