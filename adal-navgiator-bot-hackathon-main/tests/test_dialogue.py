import pytest

from app.ai.answer import AnswerResult
from app.ai.intent import IntentResult
from app.ai.retrieval import RetrievedChunk
from app.application.dialogue_service import DialogueService


class MemoryRepository:
    def __init__(self):
        self.rows = {}

    async def load(self, key):
        return self.rows.get(key, ("await_description", {}))

    async def save(self, key, state, data):
        self.rows[key] = (state, data)

    async def reset(self, key):
        self.rows.pop(key, None)


class Fakes:
    def __init__(self, intents):
        self.intents = iter(intents)
        self.classifications = []
        self.retrieved = []
        self.answered = []

    async def classify(self, message):
        self.classifications.append(message)
        return next(self.intents)

    async def retrieve(self, query, category):
        self.retrieved.append((query, category))
        return [
            RetrievedChunk(
                chunk_id="source#0",
                content="Verified instruction.",
                title="Official source",
                url="https://example.gov.kz",
                checked_at="2026-10-14",
                score=0.9,
            )
        ]

    async def answer(self, query, chunks, language):
        self.answered.append(query)
        return AnswerResult(
            answer="Verified response.",
            citations=[
                {
                    "chunk_id": "source#0",
                    "title": "Official source",
                    "url": "https://example.gov.kz",
                    "checked_at": "2026-10-14",
                }
            ],
            supported=True,
        )


def make_service(fakes):
    return DialogueService(
        repository=MemoryRepository(),
        classifier=fakes.classify,
        retriever=fakes.retrieve,
        answerer=fakes.answer,
        hmac_secret="test-secret-that-is-at-least-thirty-two-bytes",
        max_message_length=4000,
    )


@pytest.mark.asyncio
async def test_retrieval_is_blocked_until_confirmation():
    fakes = Fakes(
        [
            IntentResult(
                intent="civic_issue",
                category="garbage",
                summary="Во дворе не вывезли мусор",
                city="Алматы",
            )
        ]
    )
    service = make_service(fakes)

    first = await service.handle("session", "Во дворе не вывезли мусор в Алматы", "message")

    assert first.status == "confirmation"
    assert fakes.retrieved == []
    answer = await service.handle("session", "", "confirm")
    assert answer.status == "answer"
    assert len(fakes.retrieved) == 1


@pytest.mark.asyncio
async def test_city_defaults_to_almaty_and_clear_lighting_issue_is_not_reasked():
    fakes = Fakes(
        [
            IntentResult(
                intent="civic_issue",
                category="lighting",
                summary="Не работает уличное освещение",
                missing_fields=["issue_details"],
            )
        ]
    )
    service = make_service(fakes)
    first = await service.handle("session", "Не работает уличное освещение", "message")
    assert first.status == "confirmation"
    stored = next(iter(service.repository.rows.values()))[1]
    assert stored["city"] == "Алматы"
    assert stored["missing_fields"] == []
    assert fakes.retrieved == []

    answer = await service.handle("session", "", "confirm")
    assert answer.status == "answer"
    assert len(fakes.retrieved) == 1
    assert len(fakes.classifications) == 1
    assert next(iter(service.repository.rows.values()), None) is None


@pytest.mark.asyncio
async def test_ambiguous_water_issue_can_still_ask_for_issue_details():
    fakes = Fakes(
        [
            IntentResult(
                intent="civic_issue",
                category="water",
                summary="Затопило всё",
                missing_fields=["issue_details"],
            )
        ]
    )
    service = make_service(fakes)

    await service.handle("session", "Затопило всё", "message")
    question = await service.handle("session", "", "confirm")

    assert question.status == "clarification"
    assert question.clarification_field == "issue_details"
    assert fakes.retrieved == []


@pytest.mark.asyncio
async def test_correction_reclassifies_and_other_city_never_retrieves():
    fakes = Fakes(
        [
            IntentResult(
                intent="civic_issue",
                category="garbage",
                summary="Мусор",
                city="Алматы",
            ),
            IntentResult(
                intent="civic_issue",
                category="heating",
                summary="Нет отопления",
                city="Астана",
            ),
        ]
    )
    service = make_service(fakes)
    await service.handle("session", "Не вывезли мусор в Алматы", "message")

    response = await service.handle("session", "Нет отопления в Астане", "correct")

    assert response.status == "fallback"
    assert fakes.retrieved == []
    assert len(fakes.classifications) == 2


@pytest.mark.asyncio
async def test_kazakh_language_is_kept_when_confirm_button_has_no_text():
    fakes = Fakes(
        [
            IntentResult(
                intent="civic_issue",
                category="heating",
                summary="Жылыту жоқ",
                city="Алматы",
            )
        ]
    )
    service = make_service(fakes)
    first = await service.handle("session", "Алматыда жылыту жоқ", "message")
    confirmed = await service.handle("session", "", "confirm")
    assert first.language == "kk"
    assert confirmed.language == "kk"


@pytest.mark.asyncio
async def test_dialogue_does_not_store_raw_input_and_redacts_sensitive_summary():
    fakes = Fakes(
        [
            IntentResult(
                intent="civic_issue",
                category="garbage",
                summary="Мусор по адресу example@example.com, ИИН 123456789012",
                city="Алматы",
            )
        ]
    )
    service = make_service(fakes)
    raw_message = "Описание, email@example.com, ИИН 123456789012, телефон +7 777 123 45 67"

    await service.handle("session", raw_message, "message")

    stored = next(iter(service.repository.rows.values()))[1]
    assert "query" not in stored
    assert "clarification_values" not in stored
    assert "example@example.com" not in stored["summary"]
    assert "123456789012" not in stored["summary"]
    assert raw_message not in fakes.classifications[0]
    assert "email@example.com" not in fakes.classifications[0]
    assert "123456789012" not in fakes.classifications[0]
    assert "+7 777 123 45 67" not in fakes.classifications[0]


@pytest.mark.asyncio
async def test_empty_model_summary_does_not_persist_raw_user_message():
    fakes = Fakes(
        [
            IntentResult(
                intent="civic_issue",
                category="garbage",
                summary="",
                city="Алматы",
            )
        ]
    )
    service = make_service(fakes)
    message = "Мусор не вывезли, мой номер 123456789012"

    await service.handle("session", message, "message")

    stored = next(iter(service.repository.rows.values()))[1]
    assert message not in str(stored)
    assert stored["summary"] == "Городская проблема"
