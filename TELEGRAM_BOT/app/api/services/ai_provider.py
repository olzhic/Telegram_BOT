import uuid
from abc import ABC, abstractmethod
from typing import Optional

from app.api.config import settings
from app.api.schemas import (
    AskResponse,
    ResponseStatus,
    SourceItem,
    SourceListItem,
    SourcesResponse,
)


class BaseAIProvider(ABC):
    """
    Абстрактный контракт для интеграции AI/RAG провайдера.

    ====================================================================
    ИНСТРУКЦИЯ ДЛЯ AI/RAG ПАРТНЁРОВ:
    ====================================================================
    Чтобы подключить собственную реализацию AI/RAG (LLM, LangChain, LlamaIndex,
    векторный поиск, эмбеддинги и т.д.):

    1. Создайте класс-наследник BaseAIProvider:
       class MyRAGProvider(BaseAIProvider):
           async def answer_question(self, question: str, language: str) -> AskResponse:
               # Ваша логика RAG: поиск документов, генерация ответа
               return AskResponse(
                   status="answered",
                   answer="...",
                   sources=[SourceItem(title="...", url="...")],
                   request_id=uuid.uuid4().hex,
               )

           async def list_sources(self) -> SourcesResponse:
               # Возврат списка зарегистрированных в RAG документов
               return SourcesResponse(items=[...], total=...)

    2. Зарегистрируйте ваш провайдер при старте приложения:
       from app.api.services.ai_provider import register_ai_provider
       register_ai_provider(MyRAGProvider())

    Код Telegram-бота и API-обработчиков при этом менять НЕ ТРЕБУЕТСЯ!
    ====================================================================
    """

    @abstractmethod
    async def answer_question(self, question: str, language: str) -> AskResponse:
        """Обработка вопроса пользователя и генерация ответа со ссылками на источники."""
        pass

    @abstractmethod
    async def list_sources(self) -> SourcesResponse:
        """Получение списка доступных в системе нормативных и справочных источников."""
        pass


class NotConfiguredAIProvider(BaseAIProvider):
    """
    Провайдер по умолчанию.
    Используется, когда AI/RAG модуль ещё не подключён командой.
    Возвращает статус 'not_configured' и пустой список источников,
    не придумывая фиктивные ответы.
    """

    async def answer_question(self, question: str, language: str) -> AskResponse:
        request_id = uuid.uuid4().hex
        if language == "kk":
            message = "AI-модулі әлі қосылмаған. Кейінірек көріңіз."
        else:
            message = "AI-модуль пока не подключён. Попробуйте позже."

        return AskResponse(
            status=ResponseStatus.NOT_CONFIGURED.value,
            answer=message,
            sources=[],
            request_id=request_id,
        )

    async def list_sources(self) -> SourcesResponse:
        return SourcesResponse(items=[], total=0)


class DemoAIProvider(BaseAIProvider):
    """
    Демонстрационный провайдер.
    Включается ТОЛЬКО при флаге DEMO_MODE=true в .env для проверки интерфейса бота.
    Все ответы и источники явно помечены префиксом [ДЕМО-РЕЖИМ] / [DEMO],
    чтобы исключить дезинформацию.
    """

    async def answer_question(self, question: str, language: str) -> AskResponse:
        request_id = uuid.uuid4().hex
        if language == "kk":
            answer_text = (
                f"[ДЕМО-РЕЖИМ] «{question}» сұрағы бойынша демонстрациялық жауап.\n\n"
                "«Заң және Тәртіп» қағидаты мен адалдық — әділетті қоғамның басты негіздері. "
                "Бұл жауап UI интерфейсін тексеру үшін ғана көрсетіледі."
            )
            demo_sources = [
                SourceItem(
                    title="[DEMO] ҚР «Сыбайлас жемқорлыққа қарсы іс-қимыл туралы» Заңы",
                    url="https://adilet.zan.kz/kaz/docs/Z1500000410",
                    section="1-бап. Негізгі ұғымдар",
                )
            ]
        else:
            answer_text = (
                f"[ДЕМО-РЕЖИМ] Демонстрационный ответ на вопрос: «{question}».\n\n"
                "Принцип «Закон и Порядок» и добросовестность (Адалдық) являются ключевыми "
                "основами справедливого общества. Данный ответ сформирован исключительно "
                "для демонстрации работы интерфейса Telegram-бота."
            )
            demo_sources = [
                SourceItem(
                    title="[DEMO] Закон РК «О противодействии коррупции»",
                    url="https://adilet.zan.kz/rus/docs/Z1500000410",
                    section="Статья 1. Основные понятия",
                )
            ]

        return AskResponse(
            status=ResponseStatus.ANSWERED.value,
            answer=answer_text,
            sources=demo_sources,
            request_id=request_id,
        )

    async def list_sources(self) -> SourcesResponse:
        return SourcesResponse(
            items=[
                SourceListItem(
                    id="demo-source-01",
                    title="[DEMO] Закон РК «О противодействии коррупции»",
                    url="https://adilet.zan.kz/rus/docs/Z1500000410",
                ),
                SourceListItem(
                    id="demo-source-02",
                    title="[DEMO] Концепция антикоррупционной политики РК на 2022-2026 годы",
                    url="https://adilet.zan.kz/rus/docs/U2200000802",
                ),
            ],
            total=2,
        )


# Глобальный реестр провайдера
_custom_provider: Optional[BaseAIProvider] = None


def register_ai_provider(provider: BaseAIProvider) -> None:
    """
    Регистрация кастомного AI/RAG провайдера.
    Вызывается партнёрами при интеграции своего модуля.
    """
    global _custom_provider
    _custom_provider = provider


def get_ai_provider() -> BaseAIProvider:
    """
    Фабрика получения текущего провайдера.
    1. Если зарегистрирован кастомный провайдер -> возвращает его.
    2. Если включён DEMO_MODE=true -> возвращает DemoAIProvider.
    3. Иначе -> возвращает NotConfiguredAIProvider.
    """
    if _custom_provider is not None:
        return _custom_provider

    if settings.DEMO_MODE:
        return DemoAIProvider()

    return NotConfiguredAIProvider()


def reset_ai_provider() -> None:
    """Сброс зарегистрированного провайдера (используется преимущественно в тестах)."""
    global _custom_provider
    _custom_provider = None
