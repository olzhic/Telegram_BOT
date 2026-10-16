# How Adal Navigator works

This guide describes the code that is in the repository today. Adal Navigator is a small Russian/Kazakh web chat for Almaty civic questions. A browser sends messages to a FastAPI backend; Python controls the conversation; an LLM helps classify and draft an answer; PostgreSQL stores conversation state and verified knowledge-base chunks.

> **Current implementation vs. the original plan:** the working interface is a browser chat, not a Telegram bot. There is no `app/bot/` package or Telegram polling process. `AGENTS.md` contains broader product goals and planned features; this document describes what the source code currently implements.

## The request path at a glance

```text
Browser (app/web/)
  │ POST /chat: session_id, message, action
  ▼
FastAPI routes (app/main.py)
  │ validates request and hands it to the service
  ▼
DialogueService (app/application/)
  ├── intent classifier (app/ai/intent.py)
  ├── conversation repository (app/persistence/)
  └── after confirmation: retriever → answer pipeline (app/ai/)
                                  │
                     local embeddings + pgvector
                                  │
                     verified source chunks only
  ▼
JSON reply + optional citations → browser
```

On application startup, `create_app()` in [app/main.py](./app/main.py) wires the concrete components together. This is the **composition root**: it creates the database engine, configured LLM providers, retriever, answer pipeline, repository, and `DialogueService`. The service receives functions/interfaces for those jobs rather than constructing providers or issuing SQL itself.

## What each directory is for

### `app/api/` — the HTTP data contract

[app/api/models.py](./app/api/models.py) defines Pydantic request and response models:

- `ChatRequest` limits the session ID and message size and restricts actions to `message`, `confirm`, `correct`, or `reset`.
- `ChatResponse` defines the status and fields the UI can expect, including optional citations.

The actual HTTP routes are in `app/main.py`, not in this directory:

- `GET /` serves the chat page.
- `GET /health` reports database/model configuration and verified chunk count.
- `POST /chat` validates the body, calls the dialogue service, and returns a `ChatResponse`.

The API layer is the boundary between the browser and Python backend. The browser does not connect directly to the database or LLM providers.

### `app/application/` — conversation flow and orchestration

[app/application/dialogue_service.py](./app/application/dialogue_service.py) is the coordinator for one conversation. It:

1. Detects the message language, hashes the browser session ID with HMAC, applies a simple per-process rate limit, and trims/validates incoming text.
2. Loads the conversation state and compact data from the repository.
3. Calls the classifier to understand the message, then asks the user to confirm the short summary.
4. After confirmation, asks for missing information (such as the city or type of place) one field at a time.
5. Once it has enough information, calls retrieval and the answer pipeline.
6. Builds a localized reply and clears the stored conversation after a final answer or fallback.

[app/application/dialogue_states.py](./app/application/dialogue_states.py) names the persisted states: `await_description`, `await_confirmation`, and `await_clarification`. Keeping the transition rules here means an LLM cannot itself advance the user past the confirmation step.

`DialogueService` coordinates work; it does not contain the SQL queries, embedding implementation, or provider-specific API calls. That keeps the main flow testable with fake collaborators.

### `app/domain/` — product concepts and simple rules

[app/domain/scenarios.py](./app/domain/scenarios.py) defines the supported civic categories as a type and contains the Almaty-name check. These are product/domain rules, not web or database code.

The category returned by the classifier is used to narrow retrieval. City handling is also enforced by the application flow so that the service does not use Almaty guidance for a different city.

### `app/ai/` — model-assisted understanding and grounded answers

This directory contains the AI and retrieval pipeline:

- [app/ai/intent.py](./app/ai/intent.py) asks the configured LLM to return validated structured data: intent, likely category, short summary, city, location type, and missing fields. It asks the model to classify rather than answer the civic question.
- [app/ai/retrieval.py](./app/ai/retrieval.py) calls the local Ollama embedding endpoint, checks for a 1024-value vector, then searches PostgreSQL/pgvector for similar chunks. It filters to `verified` sources, optionally filters by category, and applies the configured similarity threshold.
- [app/ai/answer.py](./app/ai/answer.py) supplies retrieved source text to the LLM with instructions to answer only from that text. It returns the answer and citations only if validation succeeds.
- [app/ai/guards.py](./app/ai/guards.py) rejects unsupported or empty answers, missing citations, citations to chunks that were not retrieved, and phone numbers, URLs, or numeric deadlines not present in the cited text.

#### `app/ai/llm/` — model provider interface and fallback

- [app/ai/llm/base.py](./app/ai/llm/base.py) defines the provider protocol and typed errors.
- [app/ai/llm/providers.py](./app/ai/llm/providers.py) implements Gemini, OpenRouter, and Ollama structured-output calls.
- [app/ai/llm/router.py](./app/ai/llm/router.py) tries the configured providers in order, makes one retry after invalid structured output, applies timeouts, and temporarily skips providers after repeated failures.

Provider credentials and model names are loaded from environment configuration; they should not be added to source code. LLM embeddings are deliberately separate: both knowledge indexing and live queries use the configured local Ollama embedding model, so the vectors remain comparable.

### `app/knowledge/` — reviewed source material to indexed chunks

- [app/knowledge/source_registry.py](./app/knowledge/source_registry.py) parses and validates the YAML source registry.
- [app/knowledge/ingestion.py](./app/knowledge/ingestion.py) selects only entries marked `verified`, requires a review date, declared claims, and non-empty text, splits text into sentence/paragraph-based chunks, embeds each chunk, and writes the source and chunks to PostgreSQL.

The human-edited inputs live under `data/`:

- [data/registry.yaml](./data/registry.yaml) holds source metadata, review status, and claims.
- [data/sources/](./data/sources) holds the corresponding reviewed text files.

The registry is not itself the search index. The ingestion job copies the verified content and embeddings into database tables, where runtime retrieval reads them.

### `app/persistence/` — storage boundary

- [app/persistence/db.py](./app/persistence/db.py) creates the asynchronous SQLAlchemy engine and session factory.
- [app/persistence/conversation_repository.py](./app/persistence/conversation_repository.py) implements the conversation repository interface with PostgreSQL queries to load, save, and reset state.

The browser sends a random opaque session ID. The dialogue service stores an HMAC-SHA256 digest as `chat_key`, not the raw ID. The database stores only dialogue state and a compact set of fields (for example, summary, city, and category), not the full message history.

### `app/web/` — browser interface

- [app/web/index.html](./app/web/index.html) contains the chat layout and controls.
- [app/web/app.js](./app/web/app.js) creates/stores the opaque session ID in browser local storage, calls `/chat`, shows replies, and renders confirmation/correction/reset actions and citation links.
- [app/web/styles.css](./app/web/styles.css) styles the page.

The JavaScript is intentionally a thin client. It displays the server's result and sends the user's action; it does not classify civic issues or decide when retrieval is allowed.

## The conversation and answer lifecycle

1. **Description:** the user sends free text. The language helper in [app/i18n.py](./app/i18n.py) selects Kazakh when it sees Kazakh-specific letters, otherwise Russian.
2. **Understand:** the intent classifier returns structured data. For civic issues it identifies a likely category and records what details are missing.
3. **Confirm:** the service presents a short recap and waits. A regular message while awaiting confirmation repeats the recap; the explicit `confirm` action advances the flow. The `correct` action sends a revised description through classification again.
4. **Clarify:** after confirmation, missing fields are requested one at a time. A different city causes a localized fallback rather than retrieval against Almaty guidance.
5. **Retrieve:** the service builds a short query from the summary and location type. The retriever embeds it locally and searches verified chunks in PostgreSQL.
6. **Answer or fallback:** the answer pipeline asks the LLM to use only retrieved passages, then the code validates support and citations. If evidence is insufficient, it returns the localized fallback. On success, the service includes the source title, URL, and checked date.

The important safety boundary is that model output alone is not trusted: the code controls the flow and checks that an answer's citations refer to retrieved verified chunks and that recognized factual details are grounded in cited content.

## Database and knowledge-base setup

[db/schema.sql](./db/schema.sql) creates the `vector` extension and three tables:

- `sources` — title, publisher, URL, language, category, review date, and verification status.
- `chunks` — searchable text, stable chunk ID, source relation, position, and a `vector(1024)` embedding.
- `conversations` — hashed chat key, current state, compact JSON data, and update time.

[docker-compose.yml](./docker-compose.yml) runs PostgreSQL with pgvector and the API container. The database port is not published to the host; the app reaches it over the Compose network. [db/00-create-app-role.sh](./db/00-create-app-role.sh) creates the non-superuser application role. The Docker image in [Dockerfile](./Dockerfile) runs the app as a non-root user.

To index reviewed sources, run [scripts/build_knowledge_base.py](./scripts/build_knowledge_base.py). To inspect what retrieval finds for a query, run [scripts/inspect_retrieval.py](./scripts/inspect_retrieval.py). These scripts use the same configuration, database, and local embedding endpoint as the application.

## Configuration, logs, and tests

- [app/config.py](./app/config.py) loads settings from environment variables and `.env`, including database URL, provider order, credentials, model IDs, timeouts, retrieval `top_k`/threshold, and message-size limit. [pyproject.toml](./pyproject.toml) declares Python dependencies and pytest/Ruff settings.
- [app/observability.py](./app/observability.py) configures logging. HTTP middleware in `app/main.py` adds a request ID and records route/status/duration without logging the chat text.
- [tests/](./tests) contains API, dialogue, guard, localization, ingestion, scenario, and LLM-router tests. The tests use fakes and an in-memory repository for most application behavior, so they do not require a live model for the unit/API path.
- [README.md](./README.md) documents local setup, API payloads, provider configuration, database troubleshooting, source-review workflow, and current limitations.

## Current prototype limitations to keep in mind

- The supplied Adilet source is marked `needs_verification`, has no reviewed legal passage, and is not indexed.
- The prototype has no seeded verified civic chunks in the checked-in knowledge base. Until a human verifies and indexes source content, substantive questions should fall back rather than receive a sourced answer.
- The user-facing product is currently a web chat. Telegram integration, automatic appeal submission, login to eOtinish, PDF/OCR ingestion, and broad personal appeal tracking are not implemented.
- The current similarity threshold and small source corpus must be evaluated on representative Russian and Kazakh queries; an embedding score is not itself evidence that a claim is true.
