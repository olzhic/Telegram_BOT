# Adal Navigator — Copilot project context

Use this file as the fast orientation map at the start of a new task. It summarizes the current implementation and points to the smallest useful set of files; it is not a substitute for reading the code involved in a change.

## Project in one minute

Adal Navigator is an early Russian/Kazakh web-chat prototype for Almaty municipal questions. A browser sends messages to a FastAPI backend. Python owns the dialogue state machine; an LLM classifies the user's description and drafts an answer from retrieved material; PostgreSQL with pgvector stores conversation state and indexed source chunks.

The main product safety rule is **no verified source, no substantive claim**. The dialogue requires confirmation before retrieval, answers must cite retrieved chunks, and unsupported answers fall back. The bot does not submit appeals or provide general legal advice.

**Current implementation matters:** the interface is a browser chat in `app/web/`, not Telegram. There is no Telegram bot package. The source registry currently has an unverified Adilet entry with no indexed passage; don't assume a verified civic corpus is available.

## Runtime map

```text
Browser (app/web/)
  → FastAPI: GET /, GET /health, POST /chat (app/main.py)
  → DialogueService: state transitions + HMAC session key (app/application/)
  → intent classification (app/ai/intent.py)
  → after confirmation/clarification:
       local Ollama embeddings → PostgreSQL/pgvector retrieval
       → LLM answer → citation/fact guards
  → localized JSON response and source links → browser
```

`app/main.py` is the composition root: it wires the database, LLM router, embedder/retriever, answer pipeline, repository, and dialogue service. The `DialogueService` coordinates injected collaborators; it should not own SQL or provider-specific calls.

## Directory map

| Path | Responsibility |
|---|---|
| `app/main.py` | FastAPI app, routes, dependency wiring, request IDs, health checks |
| `app/api/models.py` | Pydantic HTTP request/response contract |
| `app/application/` | Conversation orchestration and persisted dialogue states |
| `app/domain/` | Civic categories and Almaty-specific domain rules |
| `app/ai/intent.py` | LLM-based intent/category/summary extraction |
| `app/ai/retrieval.py` | Ollama embeddings and verified-only pgvector search |
| `app/ai/answer.py`, `guards.py` | Grounded response generation and code-level checks |
| `app/ai/llm/` | Provider protocol, Gemini/OpenRouter/Ollama clients, failover router |
| `app/knowledge/` | Registry validation, source selection, chunking, embedding, ingestion |
| `app/persistence/` | Async SQLAlchemy setup and conversation repository |
| `app/web/` | Browser UI; deliberately thin client |
| `data/` | Human-maintained source registry and source text |
| `db/schema.sql` | `sources`, `chunks`, `conversations`, pgvector schema |
| `scripts/` | Build/index knowledge base and inspect retrieval results |
| `tests/` | Unit and API tests, mostly with fakes/in-memory conversation storage |

See [README.md](README.md) for setup, API examples, logs, source review, and known operational limitations. See [explanation.md](explanation.md) for a more detailed narrative of how the components interact. **If either document conflicts with the current code, verify the code and update the docs as needed.**

## Important implementation details

- Conversation states: `await_description`, `await_confirmation`, `await_clarification`. The service—not the model—controls transitions.
- Session IDs from the browser are HMAC-SHA256 hashed before persistence. Only compact dialogue fields are stored; don't add raw message history or user IDs to logs.
- The LLM router tries configured providers in order (Gemini, OpenRouter, Ollama), with timeouts, one structured-output repair attempt, and provider cooldowns.
- Embeddings use the local Ollama endpoint for both ingestion and querying. The schema expects 1024-dimensional vectors.
- Retrieval requires `sources.status = 'verified'`, applies category filtering and `RETRIEVAL_MIN_SCORE`, and returns source metadata for citations.
- Ingestion should index only human-verified text. Never write legal/source claims from memory; unreviewed material stays `needs_verification`.
- UI language strings are in `app/i18n.py`; the current detector uses Kazakh-specific characters to choose Kazakh, otherwise Russian.
- The app is one FastAPI service plus PostgreSQL/pgvector in Compose. Do not introduce microservices or a second copy of dialogue logic without a clear requirement.

## Start with only task-relevant files

### Planning or architecture

Start with `README.md`, this map, and `app/main.py`. Then inspect only the relevant component files from the directory map and matching tests. Consult the applicable product requirements in `AGENTS.md`, especially the architecture, safety, and scope sections. Don't infer planned features from the guide are already implemented.

### Debugging or bug fixes

Trace the affected request path from `app/main.py` → `app/application/dialogue_service.py` → the relevant collaborator. Read the matching test before editing; add or update a regression test. Check `app/config.py` and Compose only if settings, startup, or infrastructure are involved. Avoid broad repo scans unless the first trace shows the issue crosses a boundary.

### Refactoring or optimization

Read the target module, its callers, and its tests first. Preserve the HTTP contract, state transitions, citations, and privacy/safety behavior. Prefer a small, test-backed refactor over new abstractions.

### UI changes

Read `app/web/index.html`, `app/web/app.js`, `app/web/styles.css`, then `app/api/models.py` if the API contract may change. Keep civic reasoning and dialogue decisions in Python.

### Knowledge base or retrieval

Read `data/registry.yaml`, the exact source file, `app/knowledge/ingestion.py`, `app/ai/retrieval.py`, and the relevant tests. Never mark a source verified unless a human has checked its current official content and applicability.

### Database or deployment

Read `db/schema.sql`, `db/00-create-app-role.sh`, `docker-compose.yml`, `docker-compose.dev.yml` (if present), `Dockerfile`, and the relevant README setup section. PostgreSQL initialization scripts run only for a new empty data volume; do not assume editing them migrates a running database.

### Tests and validation

Read the relevant test(s), then use the narrowest suitable checks:

```sh
uv run pytest tests/test_<area>.py
uv run pytest
```

For the Compose stack, follow the exact production or development commands in `README.md`. The database-backed retrieval path also needs PostgreSQL/pgvector, Ollama, and indexed verified content; unit/API tests generally use fakes and need no real LLM.

## Project commands

```sh
uv sync --all-groups
uv run pytest
docker compose up --build
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
docker compose logs -f app
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f app
```

Do not run destructive database-volume operations unless the user explicitly requests a reset and the target is confirmed to be disposable development data.

## Working agreements for task-specific chats

- **Planning/architecture chat:** investigate and document options or an implementation plan; do not edit code unless asked.
- **Debugging chat:** reproduce/trace the concrete defect, make the smallest fix, add regression coverage, run relevant tests.
- **Refactoring/optimization chat:** preserve behavior, establish the affected tests first, avoid unrelated cleanup, compare measured behavior if optimizing.
- **Feature chat:** confirm expected behavior from the request and existing conventions, test first where practical, implement across all affected layers, then validate.
- **Review/security chat:** report concrete evidence and impact; do not silently change code unless asked to fix findings.

Useful starter prompt for any new task:

> Read `CONTEXT.md
` for project orientation. Follow the applicable requirements in `AGENTS.md`. For this task, inspect only the relevant files and their tests first: [task]. Implement/test only if requested, preserve existing safety and privacy behavior, and report changed files plus validation.

## Source-of-truth order

1. Current executable code and tests describe implemented behavior.
2. `AGENTS.md` describes product requirements and non-negotiable safety constraints; some sections describe future goals.
3. `README.md` describes setup and documented current behavior.
4. `explanation.md` and this file are navigation aids; update them if architecture changes materially.
