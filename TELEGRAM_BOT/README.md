# Adal Navigator — Telegram-бот и FastAPI Backend

Цифровой навигатор по вопросам законности, добросовестности и противодействия коррупции для хакатона **«Адал қоғам»**.

---

## 1. Назначение проекта

**Adal Navigator** — это программный комплекс, состоящий из двух независимых частей:
1. **Telegram-бота** на базе `aiogram 3.x` с интерактивным интерфейсом, поддержкой двух языков (русский и казахский), валидацией и обработкой ответов.
2. **FastAPI backend** с типизированными API-контрактами (`/health`, `/api/v1/ask`, `/api/v1/sources`), созданный специально для бесшовной интеграции моделей искусственного интеллекта и RAG-пайплайнов партнерами команды.

> **Важное архитектурное разделение**: Код Telegram-бота полностью изолирован от деталей AI-генерации. Бот общается с backend исключительно через HTTP API. Это позволяет команде AI/RAG дорабатывать и подключать модели, базы знаний и векторный поиск без изменения клиентского кода бота.

---

## 2. Архитектура и структура каталогов

```text
adal-navigator/
├── app/
│   ├── bot/                                # Клиентская часть: Telegram-бот
│   │   ├── handlers/                       # Обработчики сообщений и команд
│   │   │   ├── common.py                   # Фоллбэк для нераспознанных сообщений
│   │   │   ├── menu.py                     # Меню, справка, примеры, о проекте
│   │   │   ├── questions.py                # Ввод вопроса, валидация, вывод ответа
│   │   │   ├── sources.py                  # Просмотр источников системы
│   │   │   └── start.py                    # /start и выбор языка
│   │   ├── keyboards/                      # Разметка клавиатур
│   │   │   ├── answer.py                   # Инлайн-кнопки под ответом
│   │   │   ├── language.py                 # Выбор языка (RU/KK)
│   │   │   └── main_menu.py                # Кнопки главного меню (ReplyKeyboard)
│   │   ├── services/
│   │   │   └── api_client.py               # Асинхронный HTTP-клиент (httpx)
│   │   ├── config.py                       # Настройки Telegram-бота
│   │   ├── i18n.py                         # Двуязычная локализация и хранилище языков
│   │   ├── states.py                       # FSM-состояния (QuestionState)
│   │   └── main.py                         # Точка входа запуска бота
│   ├── api/                                # Серверная часть: FastAPI Backend
│   │   ├── routes/                         # Маршрутизаторы эндпоинтов
│   │   │   ├── health.py                   # GET /health
│   │   │   ├── questions.py                # POST /api/v1/ask
│   │   │   └── sources.py                  # GET /api/v1/sources
│   │   ├── services/
│   │   │   └── ai_provider.py              # Интерфейс (контракт) для AI/RAG провайдеров
│   │   ├── config.py                       # Настройки backend
│   │   ├── schemas.py                      # Pydantic-схемы валидации запросов и ответов
│   │   └── main.py                         # Точка входа запуска FastAPI
├── tests/                                  # Модульные и интеграционные тесты
│   ├── test_bot_validation.py              # Тесты клиента, локализации и изоляции
│   ├── test_health.py                      # Тест GET /health
│   ├── test_questions.py                   # Тесты POST /api/v1/ask и валидации
│   └── test_sources.py                     # Тесты GET /api/v1/sources
├── .env.example                            # Шаблон переменных окружения
├── .gitignore                              # Исключения версионного контроля
├── requirements.txt                        # Зависимости проекта
└── README.md                               # Документация проекта
```

---

## 3. Установка зависимостей

Требуется **Python 3.11+**.

### Windows PowerShell:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 4. Настройка окружения (`.env`)

Создайте файл `.env` на основе `.env.example`:

### Windows PowerShell:
```powershell
Copy-Item .env.example .env
```

### Linux / macOS:
```bash
cp .env.example .env
```

Параметры в `.env`:
```ini
# Токен бота, полученный у @BotFather
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ

# Адрес FastAPI backend
API_BASE_URL=http://127.0.0.1:8000

# Демонстрационный режим (true/false)
# В false (по умолчанию) API возвращает "not_configured" до интеграции AI
DEMO_MODE=false

# Таймаут запросов в секундах
API_TIMEOUT_SECONDS=30
```

---

## 5. Запуск компонентов

> **Внимание:** Backend и Telegram-бот запускаются в **отдельных терминалах (процессах)**. Не запускайте несколько экземпляров polling бота с одним токеном одновременно.

### Шаг 1: Запуск FastAPI Backend

#### Windows PowerShell:
```powershell
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

#### Linux / macOS:
```bash
python3 -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
```

Backend будет доступен по адресу: `http://127.0.0.1:8000`.  
Интерактивная документация Swagger UI: `http://127.0.0.1:8000/docs`.

### Шаг 2: Запуск Telegram-бота

Во **втором терминале** запустите бота:

#### Windows PowerShell:
```powershell
python -m app.bot.main
```

#### Linux / macOS:
```bash
python3 -m app.bot.main
```

---

## 6. Запуск тестов

Тесты не требуют реального токена Telegram или внешнего AI. Все вызовы изолированы и используют внутренние mock-провайдеры и ASGI-клиенты.

```bash
pytest -v
```

Тестовый набор покрывает:
1. `GET /health` возвращает корректный статус и имя сервиса.
2. `POST /api/v1/ask` отклоняет пустой вопрос (422).
3. `POST /api/v1/ask` отклоняет неподдерживаемый язык (422).
4. `POST /api/v1/ask` возвращает `not_configured` при отсутствии AI-провайдера.
5. `POST /api/v1/ask` возвращает `answered` с источниками при подключенном mock-провайдере.
6. `POST /api/v1/ask` корректно возвращает ответ с пометкой `[ДЕМО-РЕЖИМ]` при `DEMO_MODE=true`.
7. `GET /api/v1/sources` возвращает пустой список до подключения источников.
8. HTTP-клиент Telegram-бота передает вопрос и язык в backend.
9. Форматирование ответов, источников и корректное дробление сообщений длиннее 4000 символов.
10. Корректная обработка таймаута и недоступности API в боте.
11. Изоляция языка между разными пользователями Telegram.

---

## 7. Спецификация API (Контракты)

### 7.1. `GET /health`
Проверка работоспособности backend.
- **Ответ (200 OK)**:
```json
{
  "status": "ok",
  "service": "adal-navigator-api"
}
```

### 7.2. `POST /api/v1/ask`
Основной endpoint для обработки вопроса.

- **Запрос**:
```json
{
  "question": "Что означает принцип «Закон и Порядок»?",
  "language": "ru"
}
```
- **Правила валидации**:
  - `question`: не пустая строка после `strip()`, длина до 1000 символов.
  - `language`: только `"ru"` или `"kk"`.

- **Ответ при статусе `answered`**:
```json
{
  "status": "answered",
  "answer": "Принцип «Закон и Порядок» означает неукоснительное соблюдение законодательства всеми гражданами и институтами...",
  "sources": [
    {
      "title": "Закон РК «О противодействии коррупции»",
      "url": "https://adilet.zan.kz/rus/docs/Z1500000410",
      "section": "Статья 1"
    }
  ],
  "request_id": "c1f72a4d98344e1db873"
}
```

- **Ответ по умолчанию (до подключения AI)**:
```json
{
  "status": "not_configured",
  "answer": "AI-модуль пока не подключён. Попробуйте позже.",
  "sources": [],
  "request_id": "93b48f654b9d4e5f"
}
```

### 7.3. `GET /api/v1/sources`
Список доступных источников.

- **Ответ (200 OK)**:
```json
{
  "items": [
    {
      "id": "source-001",
      "title": "Закон РК «О противодействии коррупции»",
      "url": "https://adilet.zan.kz/rus/docs/Z1500000410"
    }
  ],
  "total": 1
}
```

---

## 8. Инструкция для AI/RAG-партнёров: как подключить свой модуль

Интерфейс провайдера полностью изолирован в файле [`app/api/services/ai_provider.py`](file:///c:/Users/Argos/Desktop/TELEGRAM_BOT/app/api/services/ai_provider.py).

### Шаги подключения:

1. **Создайте класс-реализацию провайдера**, отнаследовавшись от `BaseAIProvider`:

```python
# Например, в файле app/api/services/my_rag_provider.py
import uuid
from app.api.services.ai_provider import BaseAIProvider
from app.api.schemas import AskResponse, SourcesResponse, SourceItem, SourceListItem

class MyRAGProvider(BaseAIProvider):
    async def answer_question(self, question: str, language: str) -> AskResponse:
        # 1. Поиск по вашей векторной базе / документам
        # 2. Вызов вашей LLM с промптом на языке `language`
        # 3. Возврат строго типизированного ответа:
        return AskResponse(
            status="answered",  # или "insufficient_evidence" если нет подтверждений
            answer="Ответ вашей языковой модели...",
            sources=[
                SourceItem(
                    title="Название нормативного документа",
                    url="https://...",
                    section="Статья X"
                )
            ],
            request_id=uuid.uuid4().hex,
        )

    async def list_sources(self) -> SourcesResponse:
        # Возврат списка проиндексированных в RAG источников
        return SourcesResponse(
            items=[
                SourceListItem(id="doc-1", title="Документ 1", url="https://...")
            ],
            total=1
        )
```

2. **Зарегистрируйте ваш провайдер** в [`app/api/main.py`](file:///c:/Users/Argos/Desktop/TELEGRAM_BOT/app/api/main.py) или при запуске backend:

```python
from app.api.services.ai_provider import register_ai_provider
from app.api.services.my_rag_provider import MyRAGProvider

# Регистрация провайдера
register_ai_provider(MyRAGProvider())
```

**Все!** После этого:
- Эндпоинты `/api/v1/ask` и `/api/v1/sources` автоматически начнут вызывать вашу логику.
- Telegram-бот начнет отображать ваши ответы и источники пользователям без каких-либо правок в коде бота.

---

## 9. Демонстрационный режим (`DEMO_MODE`)

Для проверки верстки и интерактивных кнопок Telegram-бота до подключения реального AI предусмотрен демонстрационный режим:
- Включите его в `.env`:
  ```ini
  DEMO_MODE=true
  ```
- В этом режиме backend возвращает тестовые ответы и источники, четко помеченные префиксом `[ДЕМО-РЕЖИМ]`/`[DEMO]`, чтобы исключить дезинформацию.
- По умолчанию режим **выключен** (`DEMO_MODE=false`).

---

## 10. Известные ограничения первой версии

1. **Хранение языка пользователя**: выбор языка сохраняется в оперативной памяти текущего процесса (`user_language_storage`). При перезапуске процесса бота язык пользователя возвращается к значению по умолчанию (`ru`). Для продакшн-окружения класс `UserLanguageStorage` подготовлен к замене на Redis или СУБД с сохранением методов `get` и `set`.
2. **Сессии пользователей**: контекст диалога между вопросами намеренно не накапливается (каждый вопрос обрабатывается независимо как новый запрос).
3. **Лимиты Telegram**: максимальная длина одного сообщения в Telegram составляет 4096 символов. Бот автоматически разбивает длинные ответы на логические блоки, прикрепляя кнопки дальнейших действий к последнему блоку.
