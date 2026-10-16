# AGENTS.md — Adal Navigator: Implementation Guide for Coding Agents

> Audience: AI coding agents (Claude Code, OpenCode, Codex, etc.) and the 3-person human team.
> Tip: Claude Code reads `CLAUDE.md`. Create it with `ln -s AGENTS.md CLAUDE.md` (or copy the file).
> Start with [CONTEXT.md](CONTEXT.md) for a concise implementation map. Before changing code, read the relevant sections of this guide; its non-negotiable product rules and applicable requirements take precedence over assumptions.

---

## 1. Mission and context

**Adal Navigator** is a Telegram bot that helps residents of **Almaty, Kazakhstan** with everyday municipal problems (garbage not collected, broken street lighting, no heating, water issues, potholes, snow removal). The user describes the problem in plain words (Russian or Kazakh). The bot:

1. Understands the problem and **repeats it back for confirmation** ("Did I understand you correctly?").
2. Asks clarifying questions if needed (city, address type, what exactly happened).
3. Retrieves instructions from a **small, human-verified knowledge base of official sources**.
4. Answers with next steps, a **draft appeal text** the user can edit, and **links to sources**.
5. If the knowledge base does not support an answer, it **says so honestly** and suggests a safe next step. It never guesses.

It is built for the student competition **"Адал қоғам"** (Almaty Internal Policy Department + IITU Faculty of AI, Cybersecurity and Telecom). Deadline: **16 October 2026**. Defense: 3–5 min presentation/demo + up to 3 min jury questions, on a **working prototype**. Jury may ask the team to explain any part of the code or do a small live-coding task, so **keep the code simple, modular and readable**.

### Competition requirements that directly shape the implementation

| Req. | Implication |
|---|---|
| 4.5 | Not a button-only bot. Free-text understanding via LLM is required. |
| 4.6 | Natural language input, meaningful answers, real time, error handling, clear UI, **Kazakh AND Russian support**. |
| 4.7 / 4.8 | RAG over verified official sources. |
| 4.9 | **No knowingly false info. If no verified answer exists, say so — do not generate a speculative answer.** |
| 4.1 | Bot should also act as a navigator for domestic-policy documents and values (Constitution 2026, "Law and Order", "Adal Azamat", "Just Kazakhstan", "Taza Qazaqstan", etc.). If a concept is written into the 2026 Constitution, the bot must state that. See §12 "Principles mode". |
| 6.3 / 6.4 | Repo needs README, run instructions, architecture description, dependency/API list. **No secrets in the repo.** |
| 6.5 | Team must explain architecture, components, AI logic and Frontend/Backend/DB/AI interaction. |

Scoring (100 pts): Functionality & code quality 25, Technical implementation 20, Security & reliability 15, Relevance 10, Innovation 10, UX/UI 10, Presentation & Q&A 10. Tie-breaker: quality of the information base.

---

## 2. Non-negotiable rules

These are product rules. Enforce them **in code**, not only in prompts.

1. **No source, no claim.** Every procedure, contact, phone number, deadline or legal norm in an answer must come from a retrieved, verified chunk and be cited.
2. **Never invent** phone numbers, URLs, deadlines, article numbers, quotes from the Constitution or from Presidential addresses.
3. **No universal deadlines.** Do not state "authorities must answer in N days" unless the retrieved chunk states it for that appeal type.
4. **Do not claim an appeal was sent.** The bot only prepares text and instructions. (Auto-submission and eOtinish login are out of scope.)
5. **The dialogue flow is controlled by Python code**, not by the LLM. The LLM cannot skip the confirmation step.
6. **Almaty only.** If the user names another city, warn that the knowledge base covers Almaty and do not present Almaty contacts as national.
7. **Do not collect personal data.** Ask users not to send IIN, passwords, EDS keys or excess personal info. Do not log full message text.
8. **No secrets in git.** Tokens and API keys come from environment variables only.
9. **Honest fallback beats a confident wrong answer**, in every language and with every LLM provider (including the weak local fallback model).

---

## 3. Scope

### In MVP
- Telegram bot (long polling), Russian + Kazakh.
- Problem understanding → recap → confirm/correct → clarify → retrieve → answer / fallback.
- 4–5 fully verified civic scenarios (start with 3: garbage, street lighting, heating) + "Principles mode" with a tiny verified corpus.
- Draft appeal text; how to check appeal status yourself in the official service; what to attach.
- Source links in every substantive answer.
- LLM provider chain with automatic fallback (§6).
- pytest suite + evaluation set of ≥20 dialogues.

### Out of scope (do not build)
Auto-submission to government systems, eOtinish login, personal appeal-status lookup, general legal advice, microservices, multi-agent frameworks, voice/image features, WhatsApp, web UI, user auth.

---

## 4. Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.11+ |
| Backend | FastAPI (`/chat`, `/health`) |
| Telegram | aiogram 3.x, **long polling** |
| Database | **PostgreSQL 16 + pgvector** — one store for dialogue state, source registry, chunks and embeddings |
| DB access | SQLAlchemy 2.0 async + asyncpg + `pgvector` Python package. Plain SQL schema file (`db/schema.sql`); no Alembic in the MVP |
| Embeddings | **One local multilingual model** used for indexing AND querying (§7) |
| LLM | Provider chain: Gemini → OpenRouter free models → Ollama local (§6) |
| Validation | Pydantic v2 |
| Tests | pytest (+ pytest-asyncio) |
| Packaging | `pyproject.toml`, Docker + docker-compose |

Choose one library per job. Do not add abstractions "for the future".

---

## 5. Architecture

```
Telegram user
   │
   ▼
[bot/ aiogram handlers]  ── thin client, no business logic
   │  HTTP (or direct call to service in-process)
   ▼
[FastAPI  POST /chat]
   │
   ▼
[application/dialogue_service]  ── finite state machine, coordinates only
   │            │                │
   ▼            ▼                ▼
[persistence]  [ai/intent]    [ai/retrieval] ──► pgvector (verified chunks)
 Postgres      [ai/answer]       (same PostgreSQL instance)
                  │
                  ▼
            [ai/llm  provider router]
             Gemini → OpenRouter → Ollama
```

Responsibilities:

- **bot/** — receives messages, shows inline buttons, calls the API. No logic.
- **application/** — owns the dialogue state machine; decides what happens next.
- **domain/** — problem categories, supported scenarios, constants.
- **ai/** — LLM calls, retrieval, sufficiency check, answer validation.
- **knowledge/** — source registry, ingestion, chunking, indexing.
- **persistence/** — Postgres connection (`db.py`) and conversation repository.
- `dialogue_service.py` **coordinates**. It must not talk to the LLM, vector DB or SQL directly.

Keeping the bot a thin client over `POST /chat` means the whole product is testable with `curl` and pytest without Telegram, and gives a clean Frontend/Backend/DB/AI story for the defense.

---

## 6. LLM layer with fallback chain

### 6.1 Requirement
Free cloud models can be rate-limited (HTTP 429), overloaded (5xx) or slow. The bot must keep working. Provider order, configurable via env:

1. **Gemini** (Google AI Studio free tier) — primary.
2. **OpenRouter** free models (`:free` suffix) — second. Try several model IDs in order.
3. **Ollama** local model — last resort, runs on the team machine/server.

### 6.2 Interface

```python
# app/ai/llm/base.py
from typing import Protocol, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class LLMProvider(Protocol):
    name: str
    async def generate_structured(
        self, *, system: str, user: str, schema: type[T], timeout_s: float
    ) -> T: ...
    async def generate_text(self, *, system: str, user: str, timeout_s: float) -> str: ...
```

Implementations (one file each in `app/ai/llm/`):

- `gemini.py` — official `google-genai` SDK. Use native JSON/structured output where available.
- `openrouter.py` — OpenAI-compatible API, `base_url=https://openrouter.ai/api/v1`, header `Authorization: Bearer $OPENROUTER_API_KEY`. Model IDs come from env `OPENROUTER_MODELS` (comma-separated, ordered).
- `ollama.py` — HTTP to `OLLAMA_BASE_URL` (default `http://localhost:11434`), `/api/chat` with `format` set to JSON schema or `"json"`.
- `router.py` — `LLMRouter` that holds the ordered list and implements the policy below.

> Do **not** hardcode model names in code. Model availability and free-tier limits change often; verify current model IDs in the provider docs when setting `.env`. Put examples only in `.env.example`.

### 6.3 Router policy

- Try providers in order. Per-call timeout from config (e.g. 15 s cloud, 60 s local).
- On **429, 5xx, timeout, connection error, invalid JSON after one repair attempt** → move to the next provider.
- **Circuit breaker:** after N consecutive failures a provider is skipped for a cooldown period (e.g. 60 s), then retried.
- If a provider returns a 429 with `Retry-After`, respect it for the cooldown.
- If **all** providers fail → return a typed error; the dialogue layer replies "service temporarily unavailable, please retry" (RU/KK). The bot must **never crash** and never fabricate an answer.
- Log only: provider name, model, latency, outcome, error class. **No prompt/response text, no user ids in plain form.**
- Expose the last-used provider in `/health` (useful for the demo and debugging).

### 6.4 Structured output across providers

Not all models follow schemas equally. Always:
1. Ask for JSON matching the Pydantic schema.
2. Parse and validate with Pydantic.
3. On failure, **one** repair retry ("return only valid JSON matching this schema"), then fail over to the next provider.

### 6.5 Weak local model caveat
The local Ollama model is usually weaker, especially in Kazakh. Therefore the **sufficiency and citation checks (§9) are code-level and identical for every provider** — they are the safety net. When the local model answers, prefer shorter, more conservative output; it is acceptable that it falls back to "insufficient information" more often.

---

## 7. Embeddings and retrieval

**Do not put embeddings behind the cloud→local fallback chain.** The query vector must come from the same model that built the index; switching models at query time silently breaks retrieval.

- Use **one local multilingual embedding model** for both indexing and querying so retrieval never depends on cloud availability. Candidates: `bge-m3` (via Ollama or `sentence-transformers`) or a multilingual E5 model. Pick one, then **measure it on Kazakh queries** (see §14) before committing. If Kazakh retrieval is poor, switch early (day 1), not on day 3.
- Chunking: one chunk = one instruction, rule or contact. Keep chunks small and self-contained. Store metadata: `source_id`, `url`, `title`, `publisher`, `language`, `category`, `checked_at`, `chunk_id`.
- Retrieval: top-k (e.g. 4–6) with a **similarity threshold**. Optionally filter by `category` once the problem category is confirmed. If both RU and KK sources exist for a topic, retrieve across both and answer in the user's language.

### 7.1 Database schema (`db/schema.sql`, run by `docker-entrypoint-initdb.d`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE sources (
  source_id   text PRIMARY KEY,
  title       text NOT NULL,
  publisher   text NOT NULL,
  url         text NOT NULL,
  language    text NOT NULL CHECK (language IN ('ru','kk')),
  category    text NOT NULL,
  checked_at  date NOT NULL,
  status      text NOT NULL CHECK (status IN ('verified','needs_verification','excluded'))
);

CREATE TABLE chunks (
  chunk_id    text PRIMARY KEY,
  source_id   text NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  position    int  NOT NULL,
  content     text NOT NULL,
  embedding   vector(1024) NOT NULL          -- must equal the embedding model's dimension (bge-m3 = 1024)
);

CREATE TABLE conversations (
  chat_key    text PRIMARY KEY,              -- HMAC-SHA256(chat_id, CHAT_ID_HMAC_SECRET), never the raw id
  state       text NOT NULL,
  data        jsonb NOT NULL DEFAULT '{}',   -- category, summary, city, missing_fields; NOT full message history
  updated_at  timestamptz NOT NULL DEFAULT now()
);
```

Retrieval query (cosine distance; `score = 1 - distance`):

```sql
SELECT c.chunk_id, c.content, s.url, s.title, s.checked_at,
       1 - (c.embedding <=> :q) AS score
FROM chunks c JOIN sources s USING (source_id)
WHERE s.status = 'verified'
  AND (:category IS NULL OR s.category IN (:category, 'general'))
ORDER BY c.embedding <=> :q
LIMIT :k;
```

- The corpus is small (tens to hundreds of chunks): **no vector index** (exact scan, 100% recall, milliseconds). Add HNSW only if the corpus grows to thousands of chunks.
- `status = 'verified'` is enforced both in the ingestion script and in this query.
- DB roles (recommended, ~10 minutes): `adal_ingest` (write `sources`/`chunks`) used only by `scripts/build_knowledge_base.py`; `adal_app` (read `sources`/`chunks`, read/write `conversations`) used by the API. If short on time, use a single non-superuser app role. Never use the `postgres` superuser in app code.
- Delete conversations older than N days (config) with a small periodic task at startup.
- Do **not** publish port 5432 in `docker-compose.yml`; the API reaches the DB through the compose network.

### 7.2 Chunking and embedding specifics

- **One chunk = one self-contained unit**: one procedure, one rule, one contact block. Typical size: roughly 300–800 characters (about 80–250 tokens). If a source section is shorter, keep it whole. If longer, split on paragraph/list boundaries, never mid-sentence.
- Chunks are logical units, so use **no overlap** (or at most one sentence).
- **Never split a contact from what it is for** (phone number + channel + what it covers stay in the same chunk).
- Embed `f"{title}\n{content}"` (title as context header) but store `content` separately for display and for the fact-grounding check (§9).
- Each chunk gets a stable `chunk_id` (e.g. `<source_id>#<position>`) so citations stay valid after re-ingestion.
- If the embedding model needs task prefixes (multilingual E5: `"passage: "` for chunks and `"query: "` for queries), apply them consistently. `bge-m3` does not need them. Embed queries with the exact same model, normalization and prefix settings used at ingestion.
- Ingestion must be **idempotent**: re-running `build_knowledge_base.py` replaces chunks of changed sources and leaves the rest.
- Before building features on top, write `scripts/inspect_retrieval.py`: takes a query, prints top-5 chunks with scores. Use it to pick `RETRIEVAL_MIN_SCORE` from real data (compare scores of relevant vs irrelevant queries in RU and KK).

---

## 8. Dialogue state machine

State lives in PostgreSQL (`conversations` table) per hashed chat id. Transitions are enforced by code.

```
START ──► AWAIT_DESCRIPTION ──► UNDERSTAND ──► CONFIRM ──┬─(yes)──► [CLARIFY if fields missing] ──► RETRIEVE ──► ANSWER | FALLBACK
                                                          └─(no)───► AWAIT_CORRECTION ──► UNDERSTAND
```

- **UNDERSTAND** (LLM): classify intent: `civic_issue | principles_question | smalltalk | out_of_scope`; for `civic_issue` extract `{category, summary, city, location_type, missing_fields[]}`. Assume Almaty when the user does not name a city; only an explicitly named different city triggers the non-Almaty fallback.
- **CONFIRM**: show a short recap with buttons *"Yes / No, let me correct"*. Retrieval is **forbidden** until the user confirms.
- **CLARIFY**: ask **one** question at a time, and only when the missing detail materially changes routing. Never ask which city when none is named (default is Almaty), or repeat a problem category already understood. A place type may be requested when it changes the applicable instructions. Ambiguous inputs like *"everything got flooded"* must trigger a clarifying question (pipe burst / flooded entrance / sewage), not an immediate answer.
- **RETRIEVE → ANSWER/FALLBACK**: see §9.
- Must handle: `/start`, `/help`, `/cancel`, `/reset`, repeated messages, unexpected input in any state, empty text, stickers/voice/photos (reply politely: text only for now), very long messages (truncate safely), non-Almaty city (warn).
- The user must not be able to reach ANSWER without passing CONFIRM.

---

## 9. RAG answer pipeline and guards (core of the product)

```python
class RagAnswer(BaseModel):
    supported: bool           # True only if retrieved context fully supports the answer
    answer: str               # in the user's language
    citations: list[str]      # chunk_ids actually used
    missing_info: str | None  # what is not covered, if anything
```

Pipeline:

1. **Retrieve** top-k chunks for the confirmed problem summary.
2. **Gate 1 — relevance threshold:** if best score < threshold, go straight to FALLBACK (no LLM call).
3. **Generate** with the LLM: system prompt forces "answer ONLY from the provided context; if insufficient, set `supported=false`".
4. **Gate 2 — structural validation (code):**
   - `supported` is true and `citations` is non-empty;
   - every `citation` ∈ the set of retrieved `chunk_id`s;
   - otherwise → FALLBACK.
5. **Gate 3 — fact grounding (code):** extract from the answer all phone numbers, URLs, and numeric deadlines (e.g. `\d+\s*(дн|рабоч|күн|day)`) and verify each appears in the text of a cited chunk. Any ungrounded item → FALLBACK (or strip the sentence and re-validate).
6. **Render:** answer + "Sources:" list (title, URL, `checked_at`). Add the draft appeal text when relevant (US-04).

**FALLBACK message** (RU/KK): states that verified information was not found, does not guess, and offers a safe next step (e.g. call the city hotline *only if* that contact is in the verified base; otherwise suggest the official appeal portal found in sources).

Conflicting chunks (two official pages disagree) → do not pick one silently; either present both with sources or fall back.

---

## 10. Knowledge base

### 10.1 Source priorities
- **A — local Almaty procedures:** official akimat pages, public reception (Open Almaty), the unified city contact number. Verify the current number and channel on the official page; do not use old pages without re-checking.
- **B — electronic appeals:** eGov / eOtinish pages (how to submit, attach files, track status).
- **C — legal norms:** only specific norms needed for scenarios (e.g. appeal/complaint procedure in the Administrative Procedure Code), checked against the current edition on the official legal portal (Adilet).

### 10.2 Layout
```
data/
  registry.yaml            # one entry per source
  sources/
    <source_id>.md         # cleaned text with YAML front matter
  processed/               # optional chunk dumps for inspection (gitignored)
```

`registry.yaml` entry:
```yaml
- source_id: almaty-109-contact
  title: "..."
  publisher: "Akimat of Almaty"
  url: "https://..."
  language: ru            # ru | kk
  category: general       # garbage | lighting | heating | water | roads | playground | snow | appeals | principles | general
  checked_at: 2026-10-15
  status: verified        # verified | needs_verification | excluded
  claims: ["what this source confirms, one line each"]
```

PostgreSQL is the source of truth for indexed chunks; `registry.yaml` and `sources/*.md` are the human-edited inputs, re-ingested by the script.

**Only `status: verified` entries are indexed.** `scripts/build_knowledge_base.py` must refuse to index anything else.

### 10.3 Rules for agents working on the knowledge base
- **Never fabricate source content.** If you cannot fetch or read an official page, create the registry entry with `status: needs_verification` and an empty body, and tell the humans.
- If you can browse, you may draft cleaned text, but a **human must verify** each source against the live official page before it is set to `verified`.
- Keep the corpus small and precise: quality over volume (it is the tie-breaker criterion).

### 10.4 Initial scenarios (priority order)
P0: garbage not collected · street lighting out · no heating.
P1: water problems · potholes · snow removal · broken playground · "don't know where to apply" · "what to attach" · "no response / how to check status".
Plus the Principles mode corpus (§12).

---

## 11. Languages (Russian and Kazakh)

- Detect language per message: presence of Kazakh-specific letters (`ә ғ қ ң ө ұ ү һ і`) → `kk`, otherwise `ru`; for mixed text use the dominant language. Answer in the user's language. Keep all UI strings (buttons, fallback, errors) in `app/i18n.py` with `ru` and `kk` entries.
- Test colloquial phrasing, transliteration and **mixed RU/KK messages**.
- Kazakh output from LLMs can be weak: keep answers short and templated where possible (recaps, buttons, fallback), and let the LLM generate only the instruction text from retrieved chunks.

---

## 12. Principles mode (competition requirement 4.1)

Purpose: when the user asks about a state concept/value (e.g. "Law and Order", "Adal Azamat", "Just Kazakhstan", "Taza Qazaqstan", "Different Opinions – One Nation", "Tolyq Adam", "The Listening State", "Strong President – Influential Parliament – Accountable Government"), the bot gives an official description and **explicitly says whether the concept is written into the 2026 Constitution**, with a source link.

Rules:
- Corpus: a small set of verified chunks (≈5–10) from official sources (e.g. Akorda, Adilet, official Constitution text). Each chunk is copied from the official source by a human.
- **Never write Constitution article numbers or quotes from memory.** If the corpus does not contain the answer, the bot says so (same FALLBACK path).
- If the corpus has no chunk stating that a concept is in the Constitution, the bot must not claim either "yes" or "no"; it reports that this could not be verified from its sources.
- Same pipeline, same gates as §9. Intent `principles_question` routes here.

---

## 13. Project structure

```
adal-navigator/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── app/
│   ├── main.py                    # FastAPI app, /chat, /health
│   ├── config.py                  # pydantic-settings, reads env
│   ├── i18n.py                    # RU/KK strings
│   ├── bot/
│   │   ├── run.py                 # aiogram polling entrypoint
│   │   ├── handlers.py
│   │   └── keyboards.py
│   ├── application/
│   │   ├── dialogue_service.py
│   │   └── dialogue_states.py
│   ├── domain/
│   │   └── scenarios.py           # categories, supported scenarios
│   ├── ai/
│   │   ├── intent.py
│   │   ├── retrieval.py
│   │   ├── answer.py              # pipeline + gates (§9)
│   │   ├── guards.py              # citation + fact-grounding checks
│   │   └── llm/
│   │       ├── base.py
│   │       ├── gemini.py
│   │       ├── openrouter.py
│   │       ├── ollama.py
│   │       └── router.py
│   ├── knowledge/
│   │   ├── source_registry.py
│   │   └── ingestion.py
│   └── persistence/
│       ├── db.py                  # async engine/session
│       └── conversation_repository.py
├── db/schema.sql
├── data/ (registry.yaml, sources/, processed/)
├── scripts/
│   ├── build_knowledge_base.py
│   ├── inspect_retrieval.py      # query -> top-5 chunks with scores
│   └── run_eval.py                # runs the eval set, prints pass/fail table
└── tests/
    ├── test_dialogue.py
    ├── test_guards.py
    ├── test_llm_router.py
    ├── test_retrieval.py
    ├── fixtures/ (fake LLM provider, eval_dialogues.yaml)
    └── ...
```

Do not create files before they have content. Do not split a module that has only a few functions.

---

## 14. Configuration (`.env.example`)

```dotenv
# Telegram
TELEGRAM_BOT_TOKEN=

# LLM provider order, comma-separated: gemini,openrouter,ollama
LLM_PROVIDER_ORDER=gemini,openrouter,ollama

# Gemini
GEMINI_API_KEY=
GEMINI_MODEL=<set after checking current free-tier model list>

# OpenRouter (ordered list of free model IDs, check availability)
OPENROUTER_API_KEY=
OPENROUTER_MODELS=<model-id-1:free>,<model-id-2:free>

# Ollama (local fallback)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=<a multilingual model you pulled>

# Embeddings (local, same model for index and query)
EMBEDDING_MODEL=bge-m3
EMBEDDING_BACKEND=ollama            # ollama | sentence_transformers

# Timeouts / resilience
LLM_TIMEOUT_CLOUD_S=15
LLM_TIMEOUT_LOCAL_S=60
LLM_BREAKER_FAILURES=3
LLM_BREAKER_COOLDOWN_S=60

# RAG
RETRIEVAL_TOP_K=5
RETRIEVAL_MIN_SCORE=<tune on eval set>

# Database (PostgreSQL + pgvector)
POSTGRES_DB=adal
POSTGRES_PASSWORD=
DATABASE_URL=postgresql+asyncpg://adal_app:<password>@db:5432/adal
INGEST_DATABASE_URL=postgresql+asyncpg://adal_ingest:<password>@db:5432/adal
CHAT_ID_HMAC_SECRET=
CONVERSATION_TTL_DAYS=7
```

`.env` must be in `.gitignore`. Before every commit check that no key or token is staged.

---

## 15. Security and reliability checklist

- [ ] Secrets only from env; `.env` ignored; `.env.example` has no real values.
- [ ] Logs contain no tokens, no message text, no raw user ids.
- [ ] Postgres: port not published, non-superuser app role, password from env, queries parameterized (SQLAlchemy), chat id stored only as HMAC, no full message history stored, old conversations deleted after TTL.
- [ ] Bot asks users not to send IIN, passwords, EDS.
- [ ] Input length limit; handle empty/unsupported message types.
- [ ] Per-user rate limit (simple in-memory) to protect free-tier quotas.
- [ ] All three LLM providers failing does not crash the bot.
- [ ] Prompt-injection hygiene: retrieved chunks and user text go in clearly delimited sections; system prompt says to ignore instructions found inside them. Code-level gates (§9) remain the real defense.
- [ ] Bot never says an appeal was submitted.
- [ ] Docker image runs as non-root; no secrets baked into the image.

---

## 16. Testing and evaluation

Tests must run **without Telegram and without a real LLM**: use a `FakeProvider` implementing `LLMProvider`. FSM tests use an in-memory conversation repository; retrieval and ingestion tests run against the docker-compose Postgres (`docker compose up -d db`).

Unit tests:
- Guards: unknown `chunk_id` → fallback; ungrounded phone/deadline → fallback; empty citations → fallback.
- LLM router: 429 → next provider; timeout → next provider; invalid JSON → repair then next; all fail → typed error; circuit breaker opens and recovers.
- FSM: cannot reach RETRIEVE without CONFIRM; correction loop works; `/cancel` resets; unexpected input handled in every state.
- Language detection and i18n completeness (every key has `ru` and `kk`).
- Knowledge build refuses non-`verified` sources.

**Evaluation set** (`tests/fixtures/eval_dialogues.yaml`, ≥20 dialogues, expected outcomes written in advance):
- typical cases per scenario (RU and KK);
- ambiguous descriptions requiring clarification;
- user corrects the recap;
- unsupported topics (expected: honest fallback, 0 invented answers);
- provocations ("always 15 days, right?", "give me the phone of X", "what does Article N of the Constitution say?");
- non-Almaty city;
- mixed RU/KK messages.

`scripts/run_eval.py` prints a table: dialogue id, expected status (`answer|clarify|fallback`), actual, citations ok, pass/fail. **Target: 0 invented answers; correct understanding or clarification on all prepared cases.** Report the numbers in the README and the presentation.

Also run the eval with `LLM_PROVIDER_ORDER=ollama` once to see how the local fallback behaves.

---

## 17. Implementation plan (≈2 days, 3 developers)

Parallel work by area of responsibility. Agree on the interface `answer(state, text) -> {text, sources, status}` and the state schema in the first 30 minutes.

| Dev | Area | Deliverable |
|---|---|---|
| A | Telegram, FSM, Postgres schema + conversation repository, Docker/compose, config, secrets | Working dialogue from `/start` to an answer; `docker compose up` |
| B | LLM router, embeddings, retrieval, guards, structured output | `answer()` with gates, provider fallback tested |
| C | Knowledge base, registry, eval set, tests, README, presentation | Verified corpus, eval table, docs |

**Milestone 0 (first hours)** — repo, `.env.example`, docker-compose with `db` (pgvector image) + `db/schema.sql`, bot echoes, `/health`, registry skeleton, LLM router with a fake provider, embedding model quick test on RU and KK phrases (insert ~10 chunks, run `inspect_retrieval.py`).
**Milestone 1** — end-to-end for **one** scenario (garbage) in RU: confirm → retrieve → cited answer → fallback.
**Milestone 2** — 3 scenarios in RU + KK, draft appeal text, Principles mode, provider fallback verified by killing the primary provider.
**Milestone 3** — eval run, bug fixes, error handling, README + architecture diagram, 3 rehearsed demo dialogues + 1 deliberate refusal demo.
**Final morning** — freeze features, clean repo (no secrets in history), recorded backup demo video, rehearse 3–5 minute defense.

Priorities: a complete reliable path for 3 scenarios beats a broad half-working base.

---

## 18. Working agreements for coding agents

1. Read this file and `README.md` first. Make small, reviewable commits; one concern per commit.
2. Before implementing a module, write or update its test. Run `pytest` before declaring a task done.
3. Do not add dependencies without a reason; justify new ones in the PR/commit message.
4. Do not hardcode secrets, model IDs, phone numbers, URLs or deadlines in code or prompts. They live in env or in verified knowledge sources.
5. Never write knowledge-base content from memory. Unverified → `needs_verification` and report it.
6. Keep modules small and explainable: one module, one responsibility. The humans must be able to explain every line at the defense.
7. If a requirement is unclear, choose the simplest option consistent with §2 and note the assumption in the commit message or README.
8. Do not "fix" a failing eval by loosening a guard. Fix retrieval, data or prompts instead.

---

## 19. Definition of done (for the defense)

- [ ] Telegram bot runs 24/7 on the demo machine/server; backup video recorded.
- [ ] ≥3 scenarios fully verified in RU and KK, plus Principles mode.
- [ ] Confirmation step and correction loop work.
- [ ] Every substantive answer has source links; fallback works for unsupported questions.
- [ ] LLM fallback chain demonstrated (primary disabled → next provider answers).
- [ ] pytest passes; eval table available with numbers.
- [ ] README: install, configure, run, architecture diagram, tech/dependency/API list, source list, AI models used, limitations.
- [ ] No secrets in the repository or its history.
- [ ] Every team member can explain the request path, the RAG gates and the provider router.
