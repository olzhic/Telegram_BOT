import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import health, questions, sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Adal Navigator API",
    version="1.0.0",
    description=(
        "Backend API для проекта Adal Navigator (хакатон «Адал қоғам»).\n\n"
        "Служит промежуточным слоем между интерфейсом Telegram-бота и AI/RAG модулем.\n\n"
        "Разработчики AI/RAG могут реализовать интерфейс `BaseAIProvider` в "
        "`app/api/services/ai_provider.py` и зарегистрировать свой класс через `register_ai_provider()`."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
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


if __name__ == "__main__":
    import uvicorn
    from app.api.config import settings

    uvicorn.run(
        "app.api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
    )
