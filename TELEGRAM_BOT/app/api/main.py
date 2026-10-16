import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import health, questions, sources
from app.api.services.adal_rag_provider import register_context_provider, ContextAwareAIProvider
from app.api.services.ai_provider import get_ai_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager: initializes context-aware AI/RAG provider on server startup."""
    register_context_provider()
    yield


app = FastAPI(
    title="Adal Navigator API",
    version="1.0.0",
    description=(
        "Backend API для проекта Adal Navigator (хакатон «Адал қоғам»).\n\n"
        "Служит промежуточным слоем между интерфейсом Telegram-бота и AI/RAG модулем.\n\n"
        "Интегрирован с Adal Navigator AI/RAG системой и автоматически регистрирует "
        "контекстно-зависимый провайдер при запуске."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS middleware for open internal or local integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(questions.router)
app.include_router(sources.router)


@app.get("/api/v1/context", tags=["Context"], summary="Информация о текущем AI/RAG провайдере")
async def get_context():
    """Возвращает информацию о текущем активном AI/RAG провайдере и окружении."""
    provider = get_ai_provider()
    if isinstance(provider, ContextAwareAIProvider):
        return await provider.get_context_info()
    return {
        "active_provider_class": provider.__class__.__name__,
        "is_custom": True,
    }


if __name__ == "__main__":
    import uvicorn
    from app.api.config import settings

    uvicorn.run(
        "app.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
    )
