import logging
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.answer import AnswerPipeline
from app.ai.intent import classify_message
from app.ai.llm.providers import GeminiProvider, OllamaProvider, OpenRouterProvider
from app.ai.llm.router import LLMRouter
from app.ai.retrieval import OllamaEmbedder, PostgresRetriever
from app.api.models import ChatRequest, ChatResponse
from app.application.dialogue_service import DialogueService
from app.config import Settings
from app.i18n import detect_language, text as localized_text
from app.persistence.conversation_repository import PostgresConversationRepository
from app.persistence.db import create_database
from app.observability import configure_logging

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"
DATABASE_HINT = (
    "Check that .env exists, DATABASE_URL is correct, and PostgreSQL is running and reachable."
)

# Composition root: wires settings, DB, LLM router, retriever, answer pipeline, dialogue service
# Exposes POST /chat and GET /health; all business logic lives in injected callables


def configured_providers(settings: Settings):
    """Build only providers whose required credentials and model settings are present.
    Order follows LLM_PROVIDER_ORDER env var (e.g., gemini,openrouter,ollama)."""
    providers = []
    for name in settings.provider_order:
        if name == "gemini" and settings.gemini_api_key and settings.gemini_model:
            providers.append(
                GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
            )
        elif name == "openrouter" and settings.openrouter_api_key and settings.openrouter_model_list:
            providers.append(
                OpenRouterProvider(
                    api_key=settings.openrouter_api_key,
                    models=settings.openrouter_model_list,
                )
            )
        elif name == "ollama" and settings.ollama_model:
            providers.append(
                OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model)
            )
        elif name == "gemini":
            missing = []
            if not settings.gemini_api_key:
                missing.append("api_key")
            if not settings.gemini_model:
                missing.append("model")
            logger.warning(
                "llm provider=gemini outcome=disabled reason=missing_%s",
                "_and_".join(missing),
            )
        elif name == "openrouter":
            missing = []
            if not settings.openrouter_api_key:
                missing.append("api_key")
            if not settings.openrouter_model_list:
                missing.append("models")
            logger.warning(
                "llm provider=openrouter outcome=disabled reason=missing_%s",
                "_and_".join(missing),
            )
        elif name == "ollama":
            logger.warning("llm provider=ollama outcome=disabled reason=missing_model")
    return providers


def create_app(
    settings: Settings | None = None,
    dialogue_service: DialogueService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Application lifespan: configure logging, wire all dependencies, dispose on shutdown."""
        active_settings = settings or Settings()
        configure_logging(active_settings.log_level)
        application.state.settings = active_settings
        if dialogue_service is None:
            # This is the composition root: infrastructure and AI dependencies are wired once here.
            if not active_settings.database_url_configured:
                logger.warning(
                    "startup database_url=default outcome=check_configuration "
                    "hint=Set DATABASE_URL in .env"
                )
            engine, sessions = create_database(active_settings.database_url)
            router = LLMRouter(
                configured_providers(active_settings),
                cloud_timeout_s=active_settings.llm_timeout_cloud_s,
                local_timeout_s=active_settings.llm_timeout_local_s,
                breaker_failures=active_settings.llm_breaker_failures,
                breaker_cooldown_s=active_settings.llm_breaker_cooldown_s,
            )
            retriever = PostgresRetriever(
                sessions,
                OllamaEmbedder(
                    endpoint=active_settings.ollama_embedding_url,
                    model=active_settings.embedding_model,
                    timeout_s=active_settings.llm_timeout_local_s,
                ),
                active_settings,
            )
            answer_pipeline = AnswerPipeline(router)
            application.state.dialogue_service = DialogueService(
                repository=PostgresConversationRepository(sessions),
                classifier=lambda message: classify_message(router, message),
                retriever=retriever.search,
                answerer=answer_pipeline.answer,
                hmac_secret=active_settings.chat_id_hmac_secret,
                max_message_length=active_settings.max_message_length,
            )
            application.state.engine = engine
            application.state.sessions = sessions
            application.state.router = router
            if not router.providers:
                logger.warning(
                    "startup llm=unconfigured hint=Set provider credentials and model names in .env"
                )
        else:
            application.state.dialogue_service = dialogue_service
            application.state.engine = None
            application.state.router = None
        try:
            yield
        finally:
            if application.state.engine is not None:
                await application.state.engine.dispose()

    application = FastAPI(title="Adal Navigator", version="0.1.0", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    def error_response(
        request: Request,
        *,
        status_code: int,
        stage: str,
        error_type: str,
        message: str | None = None,
    ) -> JSONResponse:
            """Build localized error response; include diagnostics only in development."""
            language = detect_language(message or getattr(request.state, "message", ""))
            key = "api_unavailable" if status_code >= 500 else "api_request_failed"
            if status_code == 413:
                key = "message_too_long"
            content = {"detail": localized_text(language, key)}
            active_settings: Settings = request.app.state.settings
            if active_settings.app_env == "development":
                content["diagnostics"] = {
                    "stage": stage,
                    "error_type": error_type,
                    "request_id": getattr(request.state, "request_id", None),
                }
            return JSONResponse(status_code=status_code, content=content)

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        return error_response(
            request,
            status_code=exc.status_code,
            stage=getattr(request.state, "error_stage", "request"),
            error_type=getattr(request.state, "error_type", "HTTPException"),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        request.state.error_stage = "request_validation"
        body = exc.body
        message = body.get("message", "") if isinstance(body, dict) else ""
        return error_response(
            request,
            status_code=422,
            stage="request_validation",
            error_type="InvalidRequest",
            message=message if isinstance(message, str) else "",
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.error(
            "http request_id=%s stage=%s outcome=exception error=%s",
            getattr(request.state, "request_id", "unknown"),
            getattr(request.state, "error_stage", "application"),
            type(exc).__name__,
        )
        return error_response(
            request,
            status_code=500,
            stage=getattr(request.state, "error_stage", "application"),
            error_type=type(exc).__name__,
        )

    @application.middleware("http")
    async def request_logging(request: Request, call_next):
            """Log requests with UUID request IDs; reject arbitrary client IDs to prevent log injection."""
            # Accept only UUID request IDs so arbitrary client text cannot enter server logs.
            supplied_id = request.headers.get("X-Request-ID", "")
            try:
                request_id = str(UUID(supplied_id))
            except (ValueError, TypeError, AttributeError):
                request_id = str(uuid4())
            request.state.request_id = request_id
            started = perf_counter()
            try:
                response = await call_next(request)
            except Exception as exc:
                logger.error(
                    "http request_id=%s method=%s path=%s outcome=exception error=%s",
                    request_id,
                    request.method,
                    request.url.path,
                    type(exc).__name__,
                )
                raise
            active_settings: Settings = request.app.state.settings
            if active_settings.app_env == "development" or response.status_code < 400:
                response.headers["X-Request-ID"] = request_id
            logger.info(
                "http request_id=%s method=%s path=%s status=%d duration_ms=%d",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                int((perf_counter() - started) * 1000),
            )
            return response

    @application.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    @application.get("/health")
    async def health(request: Request):
        """Check DB connectivity and report safe diagnostics in development."""
        active_settings: Settings = request.app.state.settings
        engine = request.app.state.engine
        router = request.app.state.router
        configured = [provider.name for provider in router.providers] if router else []
        if engine is None:
            if active_settings.app_env == "production":
                return {"status": "ok"}
            return {
                "status": "ok",
                "database": "not_checked",
                "llm": {"configured_providers": configured, "last_provider": None},
                "embedding_configured": False,
            }
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                verified_chunks = await connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM chunks c JOIN sources s USING (source_id)
                        WHERE s.status = 'verified'
                        """
                    )
                )
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            request_id = request.state.request_id
            logger.warning(
                "health request_id=%s database=unavailable error=%s",
                request_id,
                type(exc).__name__,
            )
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable"}
                if active_settings.app_env == "production"
                else {
                    "status": "unavailable",
                    "database": "unavailable",
                    "llm": {
                        "configured_providers": configured,
                        "last_provider": router.last_used_provider if router else None,
                    },
                    "knowledge_base": {"verified_chunks": None},
                    "embedding_configured": False,
                    "diagnosis": f"{DATABASE_HINT} Check that Compose initialization created the schema.",
                    "request_id": request_id,
                },
            )
        status = "ok" if configured else "degraded"
        if active_settings.app_env == "production":
            return {"status": status}
        return {
            "status": status,
            "database": "ok",
            "llm": {
                "configured_providers": configured,
                "last_provider": router.last_used_provider if router else None,
            },
            "knowledge_base": {"verified_chunks": int(verified_chunks or 0)},
            "embedding": {
                "endpoint_configured": bool(active_settings.ollama_embedding_url),
                "model_configured": bool(active_settings.embedding_model),
                "note": "Endpoint reachability is checked when a query needs embeddings.",
            },
            "diagnosis": None
            if configured
            else "No LLM provider is configured. Set provider API key/model values in .env.",
        }

    @application.post("/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request):
        """Delegate the chat request to the dialogue state machine."""
        request.state.message = payload.message
        active_settings: Settings = request.app.state.settings
        if len(payload.message) > active_settings.max_message_length:
            request.state.error_stage = "input_validation"
            request.state.error_type = "MessageTooLong"
            raise HTTPException(status_code=413, detail="Message is too long")
        try:
            result = await request.app.state.dialogue_service.handle(
                payload.session_id, payload.message, payload.action
            )
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            request_id = request.state.request_id
            request.state.error_stage = "persistence"
            request.state.error_type = type(exc).__name__
            logger.error(
                "chat request_id=%s stage=persistence outcome=unavailable error=%s",
                request_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="service_unavailable",
                headers={"X-Request-ID": request_id},
            ) from exc
        return ChatResponse(
            status=result.status,
            reply=result.reply,
            language=result.language,
            summary=result.summary,
            category=result.category,
            clarification_field=result.clarification_field,
            citations=result.citations or [],
        )

    return application


app = create_app()
