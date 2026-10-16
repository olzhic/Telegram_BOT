import asyncio
import logging
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

import httpx

from app.api.config import ApiSettings, settings as default_settings
from app.api.schemas import (
    AskResponse,
    ResponseStatus,
    SourceItem,
    SourceListItem,
    SourcesResponse,
)
from app.api.services.ai_provider import (
    BaseAIProvider,
    DemoAIProvider,
    NotConfiguredAIProvider,
    register_ai_provider,
)

logger = logging.getLogger(__name__)

# Dynamically locate and optionally import adal-navigator package
ADAL_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "adal-navgiator-bot-hackathon-main"
if ADAL_PROJECT_ROOT.is_dir() and str(ADAL_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAL_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Direct Knowledge & RAG Index
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeChunk:
    chunk_id: str
    source_id: str
    title: str
    url: str
    content: str
    category: str
    checked_at: Optional[str] = None
    claims: list[str] = field(default_factory=list)


def split_into_chunks(content: str, max_chars: int = 1000) -> list[str]:
    """Split markdown text into logical chunks by sections (##) or paragraphs."""
    # If the text has section headers (e.g. ## Article), split by sections first
    sections = re.split(r"(?m)^(?=##\s+)", content)
    chunks: list[str] = []

    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chars:
            chunks.append(section)
        else:
            paragraphs = [p.strip() for p in section.split("\n\n") if p.strip()]
            current = ""
            for p in paragraphs:
                candidate = f"{current}\n\n{p}".strip() if current else p
                if current and len(candidate) > max_chars:
                    chunks.append(current)
                    current = p
                else:
                    current = candidate
            if current:
                chunks.append(current)
    return chunks


def extract_stems(text: str) -> list[str]:
    """Extract normalized word stems for multi-lingual RU/KK matching."""
    tokens = re.findall(r"\b[a-zA-Zа-яА-ЯёЁәіңғүұқөһӘІҢҒҮҰҚӨҺ]{3,}\b", text.lower())
    stop_words = {
        "что", "как", "где", "когда", "куда", "какой", "какая", "какие", "для",
        "или", "при", "про", "под", "над", "без", "после", "если", "это", "этот",
        "эта", "эти", "все", "всё", "был", "была", "были", "быть", "есть", "нет",
        "негізгі", "туралы", "қалай", "қайда", "қашан", "қандай", "және", "үшін",
        "бойынша", "жөнінде", "егер", "бірақ", "осы", "бұл", "олар", "біз",
    }
    stems = []
    for token in tokens:
        if token in stop_words:
            continue
        stem = token
        if len(token) > 6:
            stem = token[: len(token) - 3]
        elif len(token) > 5:
            stem = token[: len(token) - 2]
        elif len(token) > 4:
            stem = token[: len(token) - 1]
        stems.append(stem)
    return stems


class KnowledgeIndex:
    """Manages loaded source registry and verified chunks for in-process RAG."""

    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = self._resolve_data_path(data_path)
        self.registry: list[dict[str, Any]] = []
        self.chunks: list[KnowledgeChunk] = []
        self._load()

    def _resolve_data_path(self, configured_path: Optional[Path]) -> Path:
        if configured_path and configured_path.exists():
            return configured_path
        candidates = [
            ADAL_PROJECT_ROOT / "data",
            Path("data"),
            Path("../adal-navgiator-bot-hackathon-main/data"),
            Path("../../adal-navgiator-bot-hackathon-main/data"),
        ]
        for candidate in candidates:
            if candidate.is_dir() and (candidate / "registry.yaml").exists():
                return candidate.resolve()
        return (ADAL_PROJECT_ROOT / "data").resolve()

    def _load(self) -> None:
        registry_file = self.data_path / "registry.yaml"
        if not registry_file.exists():
            logger.warning("KnowledgeIndex: registry.yaml not found at %s", registry_file)
            return

        try:
            import yaml
            raw = yaml.safe_load(registry_file.read_text(encoding="utf-8")) or []
            if isinstance(raw, list):
                self.registry = raw
        except Exception as exc:
            logger.error("KnowledgeIndex: failed to load registry.yaml: %s", exc)
            return

        sources_dir = self.data_path / "sources"
        self.chunks.clear()

        for entry in self.registry:
            if entry.get("status") != "verified":
                continue
            source_id = entry.get("source_id", "")
            doc_file = sources_dir / f"{source_id}.md"
            if not doc_file.exists():
                continue

            try:
                content = doc_file.read_text(encoding="utf-8")
                raw_chunks = split_into_chunks(content)
                for idx, chunk_text in enumerate(raw_chunks):
                    self.chunks.append(
                        KnowledgeChunk(
                            chunk_id=f"{source_id}-chunk-{idx}",
                            source_id=source_id,
                            title=entry.get("title", source_id),
                            url=str(entry.get("url", "")),
                            content=chunk_text,
                            category=entry.get("category", "general"),
                            checked_at=str(entry.get("checked_at", "")),
                            claims=entry.get("claims", []),
                        )
                    )
            except Exception as exc:
                logger.warning("KnowledgeIndex: error reading %s: %s", doc_file, exc)

        logger.info(
            "KnowledgeIndex loaded %d verified chunks from %d sources in %s",
            len(self.chunks),
            len(self.registry),
            self.data_path,
        )

    def search(self, query: str, top_k: int = 3) -> list[tuple[KnowledgeChunk, float]]:
        """Score and return top matching chunks for query."""
        if not self.chunks:
            return []

        query_stems = extract_stems(query)
        if not query_stems:
            return []

        scored: list[tuple[KnowledgeChunk, float]] = []
        for chunk in self.chunks:
            content_lower = chunk.content.lower()
            title_lower = chunk.title.lower()
            claims_lower = " ".join(chunk.claims).lower()

            score = 0.0
            for stem in query_stems:
                cnt = content_lower.count(stem)
                if cnt > 0:
                    score += 2.0 + min(cnt, 5) * 0.5
                if stem in title_lower:
                    score += 1.5
                if stem in claims_lower:
                    score += 1.0

            if score > 0:
                scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# 1. AdalNavigatorHTTPProvider (Integrates with remote Adal Navigator /chat)
# ---------------------------------------------------------------------------

class AdalNavigatorHTTPProvider(BaseAIProvider):
    """
    HTTP-провайдер, взаимодействующий с удаленным сервисом Adal Navigator.
    Делегирует обработку вопросов в POST /chat и преобразует диалоговый автомат
    в типизированный ответ AskResponse со ссылками на первоисточники.
    """

    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._last_health_check: Optional[float] = None
        self._is_healthy_cached: bool = False

    async def check_health(self) -> bool:
        """Проверка доступности удаленного сервиса Adal Navigator."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    self._is_healthy_cached = data.get("status") in ("ok", "degraded")
                    return self._is_healthy_cached
                return False
        except Exception:
            self._is_healthy_cached = False
            return False

    async def answer_question(self, question: str, language: str) -> AskResponse:
        session_id = f"tg_{uuid.uuid4().hex[:16]}"
        chat_url = f"{self.base_url}/chat"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 1. Отправляем первичный вопрос
                first_payload = {
                    "session_id": session_id,
                    "message": question,
                    "action": "message",
                }
                resp = await client.post(chat_url, json=first_payload)
                if resp.status_code != 200:
                    logger.error("HTTP RAG provider error %s: %s", resp.status_code, resp.text[:200])
                    return AskResponse(
                        status=ResponseStatus.ERROR.value,
                        answer="Ошибка при обращении к сервису Adal Navigator.",
                        sources=[],
                        request_id=session_id,
                    )

                data = resp.json()
                status = data.get("status")
                reply = data.get("reply", "")

                # 2. Если сервис запросил подтверждение намерения — автоматически подтверждаем,
                #    чтобы диалоговый автомат перешёл к этапу поиска и генерации ответа
                if status == "confirmation":
                    confirm_payload = {
                        "session_id": session_id,
                        "message": "",
                        "action": "confirm",
                    }
                    confirm_resp = await client.post(chat_url, json=confirm_payload)
                    if confirm_resp.status_code == 200:
                        data = confirm_resp.json()
                        status = data.get("status")
                        reply = data.get("reply", reply)

                # 3. Преобразуем ответ и цитаты
                citations = data.get("citations") or []
                sources = [
                    SourceItem(
                        title=c.get("title", "Источник"),
                        url=c.get("url"),
                        section=c.get("chunk_id"),
                    )
                    for c in citations
                ]

                if status == "answer":
                    return AskResponse(
                        status=ResponseStatus.ANSWERED.value,
                        answer=reply,
                        sources=sources,
                        request_id=session_id,
                    )
                elif status in ("fallback", "clarification"):
                    return AskResponse(
                        status=ResponseStatus.INSUFFICIENT_EVIDENCE.value,
                        answer=reply,
                        sources=sources,
                        request_id=session_id,
                    )
                else:
                    return AskResponse(
                        status=ResponseStatus.ANSWERED.value,
                        answer=reply,
                        sources=sources,
                        request_id=session_id,
                    )

        except httpx.TimeoutException:
            logger.error("Timeout connecting to Adal Navigator at %s", chat_url)
            return AskResponse(
                status=ResponseStatus.ERROR.value,
                answer="Превышено время ожидания ответа от сервиса AI/RAG.",
                sources=[],
                request_id=session_id,
            )
        except Exception as exc:
            logger.exception("Failed to query Adal Navigator HTTP service: %s", exc)
            return AskResponse(
                status=ResponseStatus.ERROR.value,
                answer="Не удалось связаться с сервисом Adal Navigator.",
                sources=[],
                request_id=session_id,
            )

    async def list_sources(self) -> SourcesResponse:
        """Получение перечня источников."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/v1/sources")
                if resp.status_code == 200:
                    data = resp.json()
                    items = [
                        SourceListItem(id=item["id"], title=item["title"], url=item.get("url"))
                        for item in data.get("items", [])
                    ]
                    return SourcesResponse(items=items, total=len(items))
        except Exception:
            pass

        # Fallback to local index if available
        index = KnowledgeIndex()
        items = [
            SourceListItem(
                id=entry.get("source_id", f"src-{i}"),
                title=entry.get("title", "Источник"),
                url=str(entry.get("url", "")),
            )
            for i, entry in enumerate(index.registry)
        ]
        return SourcesResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# Ollama Local AI Agent
# ---------------------------------------------------------------------------

class OllamaAgent:
    """Интеграция с локальным ИИ-агентом Ollama для рассуждений и генерации ответов."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "llama3.1:8b",
        timeout: float = 90.0,
        num_predict: int = 512,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_predict = num_predict

    async def is_available(self) -> bool:
        """Проверка доступности Ollama сервера."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def generate_answer(
        self,
        question: str,
        chunks: list[KnowledgeChunk],
        language: str = "ru",
    ) -> Optional[str]:
        """Генерация структурированного ответа ИИ-агентом строго по проверенному контексту."""
        if not chunks:
            return None

        context_blocks = [f"--- Документ: {c.title} ---\n{c.content}" for c in chunks]
        context = "\n\n".join(context_blocks)

        if language == "kk":
            system_prompt = (
                "Сіз «Adal Navigator» («Адал қоғам») ресми заңгерлік ИИ-көмекшісісіз. "
                "Қолданушының сұрағына ТЕК ұсынылған ресми нормативтік дереккөздер контексі негізінде, қазақ тілінде сауатты әрі нақты жауап беріңіз. "
                "Контексте жоқ ақпаратты қоспаңыз. "
                "Жауапта нақты мерзімдерді және баптарды атап өтіңіз."
            )
            user_prompt = f"Ресми дереккөздердің мәтіні:\n{context}\n\nАзаматтың сұрағы: {question}"
        else:
            system_prompt = (
                "Ты — официальный юридический ИИ-ассистент проекта «Adal Navigator» («Адал қоғам»). "
                "Ответь на вопрос гражданина СТРОГО на основе предоставленного контекста проверенных официальных источников. "
                "Отвечай четко, грамотно, доброжелательно и по существу на русском языке. "
                "Не добавляй домыслов или внешних сведений, которых нет в контексте. "
                "В тексте ответа обязательно укажи конкретные сроки, статьи и права гражданина, содержащиеся в источнике."
            )
            user_prompt = f"Контекст из проверенных источников:\n{context}\n\nВопрос гражданина: {question}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": self.num_predict},
                    },
                )
                if resp.status_code == 200:
                    text = resp.json().get("message", {}).get("content", "").strip()
                    if text:
                        return text
        except Exception as exc:
            logger.warning("OllamaAgent: call to model %s failed: %s", self.model, exc)
        return None


# ---------------------------------------------------------------------------
# 2. AdalNavigatorDirectProvider (In-Process RAG & Local AI Agent Provider)
# ---------------------------------------------------------------------------

class AdalNavigatorDirectProvider(BaseAIProvider):
    """
    Прямой in-process провайдер Adal Navigator RAG с поддержкой локального ИИ-агента.
    1. Ищет верифицированные нормативные чанки (registry.yaml и data/sources/).
    2. При наличии локального Ollama генерирует осмысленный ответ ИИ-агентом (llama3.1:8b).
    3. При недоступности LLM автоматически использует точные выверенные выдержки статей.
    """

    def __init__(
        self,
        data_path: Optional[Path] = None,
        ollama_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
    ):
        self.index = KnowledgeIndex(data_path)
        base_url = ollama_url or default_settings.OLLAMA_BASE_URL or "http://127.0.0.1:11434"
        model = ollama_model or default_settings.OLLAMA_MODEL or "llama3.1:8b"
        self.ollama = OllamaAgent(
            base_url=base_url,
            model=model,
            timeout=default_settings.OLLAMA_TIMEOUT_SECONDS,
            num_predict=default_settings.OLLAMA_NUM_PREDICT,
        )

    def has_sources(self) -> bool:
        return len(self.index.registry) > 0

    def get_sources(self) -> list[dict[str, Any]]:
        return self.index.registry

    async def answer_question(self, question: str, language: str) -> AskResponse:
        request_id = uuid.uuid4().hex
        results = self.index.search(question, top_k=3)

        # Если не найден ни один релевантный чанк или оценка ниже порога
        if not results or results[0][1] < 1.0:
            if language == "kk":
                msg = (
                    "Өкінішке орай, тексерілген білім базасында бұл сұрақ бойынша "
                    "расталған ресми ақпарат табылмады. Қызмет тек заңнамалық "
                    "және верификацияланған нормативтік актілерге сүйенеді."
                )
            else:
                msg = (
                    "К сожалению, в проверенной базе знаний не найдено подтвержденных сведений "
                    "по вашему запросу. Сервис опирается исключительно на верифицированные "
                    "нормативно-правовые акты и официальные документы."
                )
            return AskResponse(
                status=ResponseStatus.INSUFFICIENT_EVIDENCE.value,
                answer=msg,
                sources=[],
                request_id=request_id,
            )

        top_chunk, score = results[0]
        sources: list[SourceItem] = []
        seen_titles = set()

        for chunk, _ in results:
            if chunk.title not in seen_titles:
                sources.append(
                    SourceItem(
                        title=chunk.title,
                        url=chunk.url,
                        section=chunk.chunk_id,
                    )
                )
                seen_titles.add(chunk.title)

        # 1. Попытка интеллектуальной генерации ответа локальным ИИ-агентом Ollama
        matching_chunks = [c for c, _ in results]
        ai_answer = await self.ollama.generate_answer(question, matching_chunks, language)

        if ai_answer:
            formatted_answer = ai_answer
        else:
            # 2. Надежный грациозный фоллбэк: формирование ответа из статьи первоисточника
            content_preview = top_chunk.content.strip()
            clean_lines = [
                line for line in content_preview.split("\n")
                if not line.startswith("Официальный источник:")
                and not line.startswith("Дата проверки:")
                and not line.startswith("Статус:")
            ]
            body = "\n".join(clean_lines).strip()

            if language == "kk":
                header = f"«{top_chunk.title}» ресми дереккөзіне сәйкес:"
            else:
                header = f"Согласно официальному источнику «{top_chunk.title}»:"

            formatted_answer = f"{header}\n\n{body}"

        return AskResponse(
            status=ResponseStatus.ANSWERED.value,
            answer=formatted_answer,
            sources=sources,
            request_id=request_id,
        )

    async def list_sources(self) -> SourcesResponse:
        items = [
            SourceListItem(
                id=entry.get("source_id", f"src-{i}"),
                title=entry.get("title", "Источник"),
                url=str(entry.get("url", "")),
            )
            for i, entry in enumerate(self.index.registry)
        ]
        return SourcesResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# 3. ContextAwareAIProvider (Master Adaptive Integrator)
# ---------------------------------------------------------------------------

class ContextAwareAIProvider(BaseAIProvider):
    """
    Интеллектуальный адаптивный интегратор.
    Автоматически выбирает оптимальный провайдер в зависимости от контекста окружения:
    1. Если задан явный режим AI_PROVIDER_TYPE (http, direct, demo, not_configured) — следует ему.
    2. В режиме "auto" (по умолчанию):
       - Проверяет доступность удаленного HTTP-сервиса Adal Navigator (ADAL_NAVIGATOR_URL).
       - Если сервис онлайн -> использует AdalNavigatorHTTPProvider.
       - Если сервис недоступен, но локальная база знаний найдена -> использует AdalNavigatorDirectProvider.
       - Если включен DEMO_MODE -> использует DemoAIProvider.
       - Иначе -> возвращает NotConfiguredAIProvider.
    """

    def __init__(self, api_settings: Optional[ApiSettings] = None):
        self.settings = api_settings or default_settings
        sources_path = Path(self.settings.ADAL_SOURCES_PATH) if self.settings.ADAL_SOURCES_PATH else None
        self._http_provider = AdalNavigatorHTTPProvider(
            base_url=self.settings.ADAL_NAVIGATOR_URL,
            timeout=self.settings.HTTP_TIMEOUT_SECONDS,
        )
        self._direct_provider = AdalNavigatorDirectProvider(
            data_path=sources_path,
            ollama_url=self.settings.OLLAMA_BASE_URL,
            ollama_model=self.settings.OLLAMA_MODEL,
        )
        self._demo_provider = DemoAIProvider()
        self._not_configured_provider = NotConfiguredAIProvider()

    async def resolve_provider(self) -> BaseAIProvider:
        mode = (self.settings.AI_PROVIDER_TYPE or "auto").lower()

        if mode == "http":
            return self._http_provider
        elif mode == "direct":
            return self._direct_provider
        elif mode == "demo":
            return self._demo_provider
        elif mode == "not_configured":
            return self._not_configured_provider

        # Auto mode context detection
        # 1. Проверяем удаленный HTTP-сервис Adal Navigator
        try:
            if await self._http_provider.check_health():
                logger.info(
                    "ContextAwareAIProvider: remote service healthy at %s -> using AdalNavigatorHTTPProvider",
                    self.settings.ADAL_NAVIGATOR_URL,
                )
                return self._http_provider
        except Exception:
            pass

        # 2. Проверяем прямое наличие источников на диске
        if self._direct_provider.has_sources():
            logger.info(
                "ContextAwareAIProvider: found %d local verified sources -> using AdalNavigatorDirectProvider",
                len(self._direct_provider.get_sources()),
            )
            return self._direct_provider

        # 3. Проверяем DEMO_MODE
        if self.settings.DEMO_MODE:
            logger.info("ContextAwareAIProvider: DEMO_MODE=True -> using DemoAIProvider")
            return self._demo_provider

        # 4. Фоллбэк
        return self._not_configured_provider

    async def answer_question(self, question: str, language: str) -> AskResponse:
        provider = await self.resolve_provider()
        return await provider.answer_question(question, language)

    async def list_sources(self) -> SourcesResponse:
        provider = await self.resolve_provider()
        return await provider.list_sources()

    async def get_context_info(self) -> dict[str, Any]:
        """Возвращает диагностическую информацию о текущем выбранном контексте."""
        provider = await self.resolve_provider()
        ollama_active = await self._direct_provider.ollama.is_available()
        return {
            "mode": self.settings.AI_PROVIDER_TYPE,
            "active_provider_class": provider.__class__.__name__,
            "remote_service_url": self.settings.ADAL_NAVIGATOR_URL,
            "sources_count": len(self._direct_provider.get_sources()),
            "demo_mode": self.settings.DEMO_MODE,
            "ollama_agent": {
                "configured_model": self.settings.OLLAMA_MODEL,
                "base_url": self.settings.OLLAMA_BASE_URL,
                "is_online": ollama_active,
            },
        }


# ---------------------------------------------------------------------------
# Global Helper for Registration
# ---------------------------------------------------------------------------

def register_context_provider(api_settings: Optional[ApiSettings] = None) -> ContextAwareAIProvider:
    """
    Регистрирует ContextAwareAIProvider в глобальном реестре Telegram Bot API.
    Вызывается при старте FastAPI сервера или вручную.
    """
    active_settings = api_settings or default_settings
    provider = ContextAwareAIProvider(active_settings)
    register_ai_provider(provider)
    logger.info("Successfully registered ContextAwareAIProvider for Adal Navigator.")
    return provider
