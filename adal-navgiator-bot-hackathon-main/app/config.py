from functools import cached_property
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and the local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "production"] = "production"

    database_url: str = "postgresql+asyncpg://adal_app:change-me@db:5432/adal"
    chat_id_hmac_secret: str = ""
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    llm_provider_order: str = "gemini,openrouter,ollama"
    gemini_api_key: str = ""
    gemini_model: str = ""
    openrouter_api_key: str = ""
    openrouter_models: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    embedding_model: str = "bge-m3"
    ollama_embedding_url: str = "http://localhost:11434/api/embed"
    llm_timeout_cloud_s: float = 15
    llm_timeout_local_s: float = 60
    llm_breaker_failures: int = Field(default=3, ge=1)
    llm_breaker_cooldown_s: float = Field(default=60, gt=0)
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    retrieval_min_score: float = Field(default=0.45, ge=-1, le=1)
    max_message_length: int = Field(default=4000, ge=1, le=20000)

    @property
    def database_url_configured(self) -> bool:
        """Whether DATABASE_URL came from the environment/.env instead of the local default."""
        return "database_url" in self.model_fields_set

    @cached_property
    def provider_order(self) -> list[str]:
        return [name.strip().lower() for name in self.llm_provider_order.split(",") if name.strip()]

    @cached_property
    def openrouter_model_list(self) -> list[str]:
        return [name.strip() for name in self.openrouter_models.split(",") if name.strip()]
