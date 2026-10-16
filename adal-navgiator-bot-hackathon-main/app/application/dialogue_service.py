import hashlib
import hmac
import logging
import re
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from app.ai.answer import AnswerResult
from app.ai.intent import IntentResult
from app.ai.llm.base import LLMUnavailableError
from app.ai.retrieval import RetrievedChunk, RetrievalUnavailableError
from app.application.dialogue_states import CLARIFICATION_QUESTIONS, DialogueState
from app.domain.scenarios import is_almaty
from app.i18n import detect_language, text
from app.persistence.conversation_repository import ConversationRepository

logger = logging.getLogger(__name__)
Classifier = Callable[[str], Awaitable[IntentResult]]
Retriever = Callable[[str, str | None], Awaitable[list[RetrievedChunk]]]
Answerer = Callable[[str, list[RetrievedChunk], str], Awaitable[AnswerResult]]

# Dialogue state machine: enforces confirmation before retrieval, clarification flow,
# Almaty-only scope, PII redaction, rate limiting. All external deps injected as callables.


@dataclass(frozen=True)
class DialogueReply:
    status: Literal["confirmation", "clarification", "answer", "fallback", "reset", "error"]
    reply: str
    language: Literal["ru", "kk"]
    summary: str | None = None
    category: str | None = None
    clarification_field: str | None = None
    citations: list[dict[str, str]] | None = None


class DialogueService:
    """Coordinate the chat state machine without owning provider or database logic."""

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        classifier: Classifier,
        retriever: Retriever,
        answerer: Answerer,
        hmac_secret: str,
        max_message_length: int,
        rate_limit_requests: int = 30,
        rate_limit_window_s: float = 60,
    ):
        if len(hmac_secret.encode()) < 32:
            raise ValueError("CHAT_ID_HMAC_SECRET must contain at least 32 bytes")
        self.repository = repository
        self.classifier = classifier
        self.retriever = retriever
        self.answerer = answerer
        self.hmac_secret = hmac_secret.encode()
        self.max_message_length = max_message_length
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_window_s = rate_limit_window_s
        self._request_times: dict[str, deque[float]] = defaultdict(deque)

    async def handle(self, session_id: str, message: str, action: str) -> DialogueReply:
            """Main entry point: rate limiting, HMAC session key, state dispatch."""
            language = detect_language(message)
            chat_key = hmac.new(self.hmac_secret, session_id.encode(), hashlib.sha256).hexdigest()
            now = time.monotonic()
            requests = self._request_times[chat_key]
            while requests and now - requests[0] >= self.rate_limit_window_s:
                requests.popleft()
            if len(requests) >= self.rate_limit_requests:
                return DialogueReply("fallback", text(language, "rate_limit"), language)
            requests.append(now)
            if action == "reset":
                await self.repository.reset(chat_key)
                return DialogueReply("reset", text(language, "reset"), language)
            message = message.strip()
            if len(message) > self.max_message_length:
                message = message[: self.max_message_length]
            if action in {"message", "correct"} and not message:
                return DialogueReply("fallback", text(language, "empty"), language)

            state_name, data = await self.repository.load(chat_key)
            if not message:
                language = data.get("language", language)
            try:
                state = DialogueState(state_name)
            except ValueError:
                await self.repository.reset(chat_key)
                state, data = DialogueState.AWAIT_DESCRIPTION, {}

            if state == DialogueState.AWAIT_CLARIFICATION and action == "message":
                return await self._accept_clarification(chat_key, data, message, language)
            if state == DialogueState.AWAIT_CONFIRMATION and action == "confirm":
                return await self._after_confirmation(chat_key, data, language)
            if state == DialogueState.AWAIT_CONFIRMATION and action == "message":
                return DialogueReply(
                    "confirmation",
                    text(language, "confirm", summary=data.get("summary", "")),
                    language,
                    summary=data.get("summary"),
                    category=data.get("category"),
                )
            return await self._qualify(chat_key, message, language)

    async def _qualify(self, chat_key: str, message: str, language: str) -> DialogueReply:
            """Classify intent, extract fields, enforce Almaty-only, build confirmation state."""
            try:
                result = await self.classifier(self._sanitize_model_input(message))
            except LLMUnavailableError:
                logger.warning("dialogue stage=qualification outcome=unavailable")
                return DialogueReply("error", text(language, "unavailable"), language)
            logger.info(
                "dialogue stage=qualification intent=%s category=%s",
                result.intent,
                result.category or "none",
            )
            if result.intent == "smalltalk":
                await self.repository.reset(chat_key)
                return DialogueReply("fallback", text(language, "smalltalk"), language)
            if result.intent == "out_of_scope":
                await self.repository.reset(chat_key)
                return DialogueReply("fallback", text(language, "out_of_scope"), language)
            if result.city and not is_almaty(result.city):
                await self.repository.reset(chat_key)
                return DialogueReply("fallback", text(language, "other_city"), language)

            missing = [
                field
                for field in dict.fromkeys(result.missing_fields)
                if field != "city"
            ]
            if (
                result.intent == "civic_issue"
                and "issue_details" in missing
                and result.category not in (None, "general")
                and result.summary.strip()
                and not self._is_ambiguous_issue(message)
            ):
                missing.remove("issue_details")
            location_type = (
                self._normalize_location_type(result.location_type)
                if result.location_type
                else None
            )
            if result.location_type and location_type is None and "location_type" not in missing:
                missing.append("location_type")
            summary = result.summary or (
                "Қалалық мәселе" if language == "kk" else "Городская проблема"
            )
            data = {
                "intent": result.intent,
                "category": result.category or ("principles" if result.intent == "principles_question" else "general"),
                "summary": self._redact_summary(summary),
                "city": "Алматы" if result.intent == "civic_issue" else result.city,
                "location_type": location_type,
                "missing_fields": missing,
                "language": language,
            }
            await self.repository.save(chat_key, DialogueState.AWAIT_CONFIRMATION.value, data)
            recap = text(language, "confirm", summary=data["summary"])
            recap += "\n\n" + text(language, "ask_sensitive")
            return DialogueReply(
                "confirmation",
                recap,
                language,
                summary=data["summary"],
                category=data["category"],
            )

    async def _after_confirmation(
        self, chat_key: str, data: dict, language: str
    ) -> DialogueReply:
        """Only transition from confirmation → clarification or retrieval."""
        missing = data.get("missing_fields", [])
        if missing:
            return await self._ask_clarification(chat_key, data, language)
        return await self._retrieve_and_answer(chat_key, data, language)

    async def _ask_clarification(
        self, chat_key: str, data: dict, language: str
    ) -> DialogueReply:
            """Ask one clarification question at a time from CLARIFICATION_QUESTIONS."""
            field = data["missing_fields"][0]
            key = CLARIFICATION_QUESTIONS.get(field)
            prompt = text(language, key) if key else text(language, "clarify_default", field=field)
            await self.repository.save(chat_key, DialogueState.AWAIT_CLARIFICATION.value, data)
            return DialogueReply(
                "clarification",
                prompt,
                language,
                summary=data.get("summary"),
                category=data.get("category"),
                clarification_field=field,
            )

    async def _accept_clarification(
        self, chat_key: str, data: dict, message: str, language: str
    ) -> DialogueReply:
            """Process user's clarification answer; validate city/location_type, re-classify if needed."""
            missing = list(data.get("missing_fields", []))
            if not missing:
                return await self._retrieve_and_answer(chat_key, data, language)
            field = missing.pop(0)
            if field == "city":
                data["city"] = "Алматы"
                if not is_almaty(message):
                    await self.repository.reset(chat_key)
                    return DialogueReply("fallback", text(language, "other_city"), language)
            elif field == "location_type":
                location_type = self._normalize_location_type(message)
                if location_type is None:
                    missing.insert(0, field)
                    data["missing_fields"] = missing
                    await self.repository.save(
                        chat_key, DialogueState.AWAIT_CLARIFICATION.value, data
                    )
                    return await self._ask_clarification(chat_key, data, language)
                data["location_type"] = location_type
            else:
                try:
                    updated = await self.classifier(
                        f"Existing issue summary: {data.get('summary', '')}\n"
                        f"Additional issue detail: {self._sanitize_model_input(message[:500])}"
                    )
                except LLMUnavailableError:
                    return DialogueReply("error", text(language, "unavailable"), language)
                data["summary"] = self._redact_summary(updated.summary or data.get("summary", ""))
            data["missing_fields"] = missing
            if missing:
                await self.repository.save(chat_key, DialogueState.AWAIT_CLARIFICATION.value, data)
                return await self._ask_clarification(chat_key, data, language)
            return await self._retrieve_and_answer(chat_key, data, language)

    async def _retrieve_and_answer(
        self, chat_key: str, data: dict, language: str
    ) -> DialogueReply:
            """Retrieve chunks → generate answer → apply guards (citations, grounding) → render or fallback."""
            if data.get("intent") == "civic_issue" and not is_almaty(data.get("city")):
                await self.repository.reset(chat_key)
                return DialogueReply("fallback", text(language, "other_city"), language)
            query = " ".join(
                value
                for value in (
                    data.get("summary", ""),
                    data.get("location_type", ""),
                )
                if value
            )
            try:
                chunks = await self.retriever(query, data.get("category"))
                logger.info(
                    "dialogue stage=retrieval category=%s chunks=%d",
                    data.get("category", "general"),
                    len(chunks),
                )
                result = await self.answerer(query, chunks, language)
            except (LLMUnavailableError, RetrievalUnavailableError) as exc:
                logger.warning(
                    "dialogue stage=answer outcome=unavailable error=%s",
                    type(exc).__name__,
                )
                return DialogueReply("error", text(language, "unavailable"), language)
            if not result.supported:
                await self.repository.reset(chat_key)
                return DialogueReply("fallback", result.answer or text(language, "fallback"), language)
            await self.repository.reset(chat_key)
            source_list = "\n".join(
                text(language, "source_item", **citation) for citation in result.citations
            )
            rendered = text(language, "answer", answer=result.answer, sources=source_list)
            citations = result.citations
            return DialogueReply(
                "answer",
                rendered,
                language,
                summary=data.get("summary"),
                category=data.get("category"),
                citations=citations,
            )

    @staticmethod
    def _redact_summary(value: str) -> str:
        """Redact PII (IIN, emails, phones) and truncate to 500 chars before any LLM call."""
        value = re.sub(r"\b\d{12}\b", "[redacted]", value)
        value = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted]", value)
        value = re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", "[redacted]", value)
        return value[:500]

    @staticmethod
    def _is_ambiguous_issue(value: str) -> bool:
        """Retain follow-up questions for vague descriptions where category alone is unsafe."""
        return bool(
            re.search(
                r"\b(?:всё|все|повсюду|что-то|непонятно|какая-то|бәрі|бірдеңе)\b|"
                r"затоп|потоп|су\s*(?:бас|тас)",
                value.casefold(),
            )
        )

    @staticmethod
    def _sanitize_model_input(value: str) -> str:
        """Redact PII from user text before sending to LLM (no truncation)."""
        value = re.sub(r"\b\d{12}\b", "[redacted]", value)
        value = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted]", value)
        return re.sub(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)", "[redacted]", value)

    @staticmethod
    def _normalize_location_type(value: str) -> str | None:
        """Map free-text location to canonical category (двор, улица, подъезд, etc.) for RU/KK."""
        normalized = value.casefold()
        categories = (
            ("двор", ("двор", "аула", "аулада")),
            ("улица", ("улиц", "көше", "көшеде")),
            ("подъезд", ("подъезд", "кіреберіс")),
            ("дорога", ("дорог", "жол", "жолда")),
            ("дом", ("дом", "үй", "үйде")),
            ("площадка", ("площадк", "алаң")),
        )
        return next(
            (label for label, terms in categories if any(term in normalized for term in terms)),
            None,
        )
