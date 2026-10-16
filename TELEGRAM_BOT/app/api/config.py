from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """Configuration settings for FastAPI backend."""

    DEMO_MODE: bool = False
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    # Provider and integration settings
    AI_PROVIDER_TYPE: str = "auto"  # "auto", "http", "direct", "demo", "not_configured"
    ADAL_NAVIGATOR_URL: str = "http://127.0.0.1:8001"
    ADAL_SOURCES_PATH: str = ""
    HTTP_TIMEOUT_SECONDS: float = 15.0

    # LLM keys (optional, for direct in-process RAG router)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODELS: str = ""
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = ""
    OLLAMA_TIMEOUT_SECONDS: float = 90.0   # Qwen3.5 thinking models need ~39s; 90s is safe headroom
    OLLAMA_NUM_PREDICT: int = 512           # Max tokens per response; keeps generation fast (~5-8s)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = ApiSettings()
