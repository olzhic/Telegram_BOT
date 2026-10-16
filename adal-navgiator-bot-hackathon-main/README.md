# Adal Navigator

Adal Navigator is an early RU/KK prototype for helping Almaty residents understand where to start with common municipal issues. The first interface is a small web chat; the backend is a FastAPI service that can later be reused by a thin Telegram client.

The assistant confirms its understanding before looking up guidance. It only answers civic questions from verified knowledge-base chunks, cites those sources, and falls back when evidence is missing. It does not submit appeals or provide general legal advice.

## Run locally

1. Install [`uv`](https://docs.astral.sh/uv/).
2. Copy `.env.example` to `.env`. Set unique values for `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, and `CHAT_ID_HMAC_SECRET`; configure at least one LLM provider. 
The example file is a template, not a ready-to-use production configuration.
3. Install locked dependencies:

   ```sh
   uv sync --all-groups
   ```

4. Start the production-style stack:

   ```sh
   docker compose up --build
   ```

5. Open `http://localhost:8000`. The API health endpoint is `http://localhost:8000/health`.

For active development, start the override instead:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

- The development override mounts `app/` (and read-only `data/`) into the container and enables Uvicorn reload, so Python and browser-client edits take effect without rebuilding. 
- Changes to application dependencies or the app Dockerfile require rebuilding; source edits do not. 
- The base Compose file runs without reload and sets `APP_ENV=production`. It does not mount host source into `/app`; the database mounts only its two read-only initialization scripts. 
- PostgreSQL is not published to the host and uses a non-superuser application role. 
- Ollama must be reachable from the app container; on Linux Compose maps `host.docker.internal` to the host gateway.

The database uses the prebuilt `pgvector/pgvector:pg16` image; Compose pulls it from its registry when it is not already local. No project-specific database image or registry upload is needed. The SQL and role setup scripts are mounted read-only into PostgreSQL's initialization directory. PostgreSQL runs those scripts only when creating a new, empty `postgres_data` volume; edits to them do not reinitialize an existing database. Use a real migration for an existing database, or reset only the development database volume if you intentionally want a fresh database.

## Configure the model providers

Set `LLM_PROVIDER_ORDER` to an ordered comma-separated list of `gemini`, `openrouter`, and `ollama`. Providers without required credentials/model configuration are omitted. Configure model IDs and API keys only through `.env`; do not put them in source files. For Ollama, configure `OLLAMA_MODEL`, run Ollama on the host, and pull the selected chat and embedding models there.

Provider inputs and outputs are never logged. The router makes one structured-output repair attempt, then fails over to the next provider. If all providers fail, the user receives a localized temporary-unavailability message.

## Debugging and logs

Logging stays enabled in both environments. Set `LOG_LEVEL=DEBUG` in `.env` for more server-side diagnostics, or leave it at `INFO` for routine use. The development Compose override sets `DEBUG`; production defaults to `INFO`. The API writes timestamped logs to standard output; view them with:

```sh
docker compose logs -f app
```

Also try:
```
docker exec -it <YOUR_APP_CONTAINER_NAME> curl http://host.docker.internal:11434
```
- This makes sures that app container could see and talk with running local Ollama server

The server logs a request ID with route, status, duration, and safe stage/error metadata; it deliberately omits chat text, session IDs, API keys, and database URLs. Development API errors may show an allowlisted stage, exception type, HTTP status, and request ID in the chat for debugging. Production chat errors show only a localized generic message; the request ID remains server-side. Stack traces, exception messages, database/provider details, and submitted request data are never included in API error responses. Production `/health` returns only readiness status; development `/health` includes subsystem diagnostics.

To follow the app container logs directly, use the command you already use:

```sh
docker logs --follow hackathon_rag_bot-app-1
```

Or let Compose resolve the container name:

```sh
docker compose logs --follow app
```

Router failures now log a safe `error_category` and, when available, the public model ID and HTTP status. Common categories:

- `rate_limited` — provider returned HTTP 429; check provider quotas and `Retry-After`.
- `provider_overloaded_or_unavailable` — provider returned a 5xx response; retry/failover is attempted.
- `authentication_failed` / `permission_denied` — check the API key, account access, and model permissions. Key values are never logged.
- `model_or_endpoint_not_found` — check the configured model ID and provider endpoint.
- `billing_or_credits` — provider returned HTTP 402; check account credits/billing.
- `invalid_request_or_model_parameters` — the request or structured-output settings may not be supported by that model.
- `provider_timeout` / `connection_error` — check connectivity, service availability, and timeout settings.
- `invalid_structured_output` / `malformed_provider_response` — provider responded but did not return the expected JSON shape.
- `missing_api_key`, `missing_model`, or `missing_models` — provider was disabled during startup because required configuration was absent.

Logs contain provider/model identifiers, status, and error categories only—not prompt text, response bodies, API keys, or raw exception messages.

In development, check `http://localhost:8000/health` for the database state, configured LLM provider names, last provider used, and indexed verified-chunk count. In production, health intentionally reports only `ok`, `degraded`, or `unavailable`. For deployment diagnosis, check that `.env` exists, `DATABASE_URL` points to the `db` Compose service, and the database container completed schema initialization. Configure at least one provider key and model in `.env`. `docker compose logs -f db` shows PostgreSQL startup and initialization errors.

Typical failure meanings:

- **Browser says the service is unavailable:** the API may be stopped or a backend dependency may be unavailable. Use server logs and `/health` during development; production intentionally shows no internal diagnostics.
- **HTTP 503:** `DATABASE_URL` is missing/wrong, PostgreSQL is stopped/unreachable, or initialization did not create the schema. In the current local prototype, without Docker or a separate PostgreSQL server, this response is expected.
- **Temporary LLM-unavailable message:** the health payload has no configured providers, or each configured provider timed out/failed. Set a provider API key and model, or ensure Ollama is reachable.
- **Fallback saying verified information was not found:** service/model connection succeeded, but there are no relevant verified chunks. Review and index source text; this is intentionally not treated as a service error.

For local diagnosis, after copying `.env.example` and starting a local PostgreSQL server, use `APP_ENV=development LOG_LEVEL=DEBUG uv run uvicorn app.main:app --reload` and inspect the terminal running Uvicorn. In Compose, use the development override above and `docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f app`. The `.env.example` uses `DATABASE_URL` for a locally installed PostgreSQL; Compose overrides its host to `db`. Do not paste database URLs, API keys, or user messages into bug reports.

## Add official source material

The initial Adilet registry entry points to [the supplied document](https://old.adilet.zan.kz/rus/docs/K2000000350) and is deliberately `needs_verification`; its Markdown file contains no legal text and is not indexed.

To add content:

1. Open the official source and select only the passage relevant to a supported user question. Check its current wording, effective date, and applicability; a URL or automated extraction is not verification.
2. Have a human review the passage. Keep it short and self-contained in `data/sources/<source_id>.md`. Do not paraphrase the law as though the paraphrase were the source.
3. Add or update the matching entry in `data/registry.yaml` with title, publisher, canonical URL, language, category, `checked_at`, and a precise list of claims the passage supports.
4. Only after review set `status: verified`. Unverified and excluded items are not sent to retrieval.
5. Configure the local Ollama embedding model and rebuild the index:

   ```sh
   docker compose exec app uv run python scripts/build_knowledge_base.py
   ```

6. Check relevant and irrelevant Russian and Kazakh queries before changing `RETRIEVAL_MIN_SCORE`:

   ```sh
   docker compose exec app uv run python scripts/inspect_retrieval.py "не вывезли мусор" --category garbage
   ```

Markdown is the reviewed input format in this MVP. URL crawling, PDF parsing/OCR, and bulk indexing are intentionally not included. Extracted text from PDFs or websites should be manually reviewed before becoming verified source content.

## API contract

- `GET /health` — production returns readiness status only; development also reports subsystem status and the last provider used. Neither mode exposes user text or secrets.
- `POST /chat` — JSON request:

  ```json
  {"session_id":"opaque-browser-session","message":"Во дворе не вывезли мусор","action":"message"}
  ```

  `action` may be `message`, `confirm`, `correct`, or `reset`. Responses have a status (`confirmation`, `clarification`, `answer`, `fallback`, `reset`, or `error`), localized reply, and optional citations.

The browser stores only a random opaque session key; PostgreSQL stores an HMAC-SHA256 digest and compact dialogue fields, not raw message history. Avoid sending IIN, passwords, EDS keys, or unnecessary personal information.

For civic issues, an unnamed city defaults to Almaty. The assistant does not ask for the city or repeat a recognized problem category; it asks a follow-up only when a missing place/detail could change the instructions. Explicitly naming a city outside Almaty still triggers the scope fallback.

## Architecture

```text
Browser web chat
      │ POST /chat
      ▼
FastAPI ── DialogueService (Python-owned state transitions)
                 ├── LLM router: Gemini → OpenRouter → Ollama
                 ├── answer/relevance/citation guards
                 ├── local Ollama embeddings
                 └── persistence and verified-only retrieval
                           │
                    PostgreSQL + pgvector
```

The dialogue service coordinates injected classifier, retriever, answerer, and repository interfaces; it does not issue SQL or call providers directly. The web client only renders state and sends user actions. A future Telegram adapter should call the same API and must not implement a second copy of the business flow.

## Code tour

- `app/main.py` wires runtime dependencies, exposes the API and health diagnostics, and logs request IDs/status/duration without message bodies.
- `app/application/dialogue_service.py` owns confirmation-before-retrieval, clarification, city boundary, and compact privacy-conscious state.
- `app/ai/intent.py` defines the structured issue classification contract; `app/ai/llm/` implements provider adapters and fallback/circuit-breaker behavior.
- `app/ai/retrieval.py` embeds the query locally and asks PostgreSQL for verified chunks only; `app/ai/answer.py` and `app/ai/guards.py` enforce evidence and citations.
- `app/knowledge/` reads human-reviewed files and indexes only registry entries marked `verified`.
- `app/web/` is a thin browser client; it sends messages/actions to `/chat`, displays citations, and follows the development/production error-disclosure policy.
- `db/schema.sql` defines source metadata, vector chunks, and compact conversation state.

## Test

Unit/API tests use a fake provider and in-memory conversation repository; they require no database, real model, or API keys:

```sh
uv run pytest
```

The integration path that exercises pgvector requires the Compose services to be running, Ollama with the configured embedding model, and verified source material.

## Current limitations

- The provided Adilet source has not yet been reviewed for a specific passage and remains excluded from retrieval.
- The prototype starts without seeded verified civic chunks; until sources are reviewed and indexed, substantive questions correctly fall back.
- The initial chat UI is intentionally minimal. Telegram, evaluation corpus expansion, database TTL cleanup, and PDF/OCR processing are follow-on work.
